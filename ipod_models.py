"""
iPod model identification database.

Single source of truth for all iPod model identification, mapping, image
resolution, and device capabilities.  Every other module imports model data
from here — no other file should define model tables, serial lookups, USB
PID maps, image mappings, or per-generation feature flags.

Data tables
~~~~~~~~~~~
- ``IPOD_MODELS``            Model number → (family, gen, capacity, color)
- ``USB_PID_TO_MODEL``       USB Product ID → (family, gen)
- ``IPOD_USB_PIDS``          All known iPod USB Product IDs (frozenset)
- ``SERIAL_LAST3_TO_MODEL``  Serial suffix → model number
- ``ChecksumType``           Enum of checksum algorithms
- ``COLOR_MAP``              (family, gen, color) → image filename
- ``MODEL_IMAGE``            Model number → image filename (revision overrides)
- ``FAMILY_FALLBACK``        Family → default image filename

Device capabilities
~~~~~~~~~~~~~~~~~~~
- ``ArtworkFormat``           Dataclass for one artwork thumbnail size
- ``DeviceCapabilities``      Dataclass aggregating all per-generation flags
- ``capabilities_for_family_gen()``  Lookup capabilities by (family, gen)
- ``CHECKSUM_MHBD_SCHEME``   ChecksumType → raw mhbd hashing_scheme value
- ``MHBD_SCHEME_TO_CHECKSUM``  Reverse: hashing_scheme → ChecksumType

Artwork format lookups
~~~~~~~~~~~~~~~~~~~~~~
- ``ITHMB_FORMAT_MAP``         Correlation ID → ``ArtworkFormat`` (all known)
- ``ITHMB_SIZE_MAP``           Byte size → ``ArtworkFormat`` (fallback)
- ``ithmb_formats_for_device()``  {corr_id: (w, h)} for a device's cover art

Lookup functions
~~~~~~~~~~~~~~~~
- ``checksum_type_for_family_gen()``
- ``extract_model_number()``
- ``get_model_info()``
- ``get_friendly_model_name()``
- ``lookup_by_serial()``
- ``resolve_image_filename()``
- ``image_for_model()``

Sources
~~~~~~~
- libgpod ``itdb_device.c`` (SourceForge / GitHub mirror)
- libgpod ``itdb_itunesdb.c`` (iTunesSD format, mhbd version)
- Universal Compendium iPod Models table
- The Apple Wiki: Models/iPod
- macOS AMPDevices.framework icon assets
"""

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Checksum types                                                         ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class ChecksumType(IntEnum):
    """Checksum types for different iPod generations.

    NONE        — Pre-2007 iPods (1G–5G, Photo, Video, Mini, Nano 1G–2G, Shuffle)
    HASH58      — iPod Classic (all gens), Nano 3G, Nano 4G
    HASH72      — Nano 5G
    HASHAB      — Nano 6G, Nano 7G (white-box AES, via WASM module)
    UNSUPPORTED — Reserved for any future unsupported scheme
    UNKNOWN     — Device not yet identified
    """
    NONE = 0
    HASH58 = 1
    HASH72 = 2
    HASHAB = 3
    UNSUPPORTED = 98
    UNKNOWN = 99


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  MHBD hashing scheme ↔ ChecksumType mapping                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# The mhbd header at offset 0x30 stores a 16-bit ``hashing_scheme`` value.
# These constants map between our ``ChecksumType`` enum and the raw wire
# values.  Note: HASHAB is enum 3 but wire 4.

CHECKSUM_MHBD_SCHEME: dict[ChecksumType, int] = {
    ChecksumType.NONE: 0,
    ChecksumType.HASH58: 1,
    ChecksumType.HASH72: 2,
    ChecksumType.HASHAB: 4,
}
"""Map ``ChecksumType`` → raw ``hashing_scheme`` field in mhbd header."""

MHBD_SCHEME_TO_CHECKSUM: dict[int, ChecksumType] = {
    v: k for k, v in CHECKSUM_MHBD_SCHEME.items()
}
"""Map raw ``hashing_scheme`` field in mhbd header → ``ChecksumType``."""


def checksum_type_for_family_gen(
    family: str,
    generation: str,
) -> Optional[ChecksumType]:
    """Return the checksum type for a (family, generation) pair.

    Derives the answer from ``_FAMILY_GEN_CAPABILITIES``.  Returns ``None``
    if the pair is not in the lookup table — callers should fall through to
    secondary detection (HashInfo, firmware hints, etc.).
    """
    caps = _FAMILY_GEN_CAPABILITIES.get((family, generation))
    if caps is not None:
        return caps.checksum
    return None


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Device capabilities — per-generation feature map                       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# Sources:
#   - libgpod ``itdb_device.c`` — itdb_device_supports_*() functions,
#     ipod_info_table, artwork format tables
#   - libgpod ``itdb_itunesdb.c`` — iTunesSD writer, mhbd version handling
#   - Empirical: iPod Classic 2G, Nano 3G confirmed
#
# This table captures every capability dimension that affects database
# writing, artwork generation, or sync behaviour.  It is the single
# authority for "what does this device support?" questions.

@dataclass(frozen=True)
class ArtworkFormat:
    """One artwork thumbnail size for a device generation.

    Attributes:
        format_id:    Ithmb correlation ID (e.g. 1055, 1060, 1061) — the
                      value stored in MHNIs and MHIFs in the ArtworkDB binary.
        width:        Pixel width
        height:       Pixel height
        row_bytes:    Bytes per row (often ``width * 2`` for RGB565)
        pixel_format: ``"RGB565_LE"`` (most iPods), ``"RGB565_LE_90"``
                      (rotated, Nano 4G), ``"RGB565_BE"`` (Mobile/Motorola)
        role:         ``"cover_small"``, ``"cover_large"``, ``"photo_full"``,
                      ``"tv_out"``, etc.
        description:  Human-readable label for logs / parser output.
    """
    format_id: int
    width: int
    height: int
    row_bytes: int
    pixel_format: str = "RGB565_LE"
    role: str = "cover"
    description: str = ""


@dataclass(frozen=True)
class DeviceCapabilities:
    """Per-generation device capability flags.

    Every (family, generation) pair maps to exactly one of these.  The
    flags drive decisions in the sync engine, iTunesDB writer, and
    ArtworkDB writer.

    All flags default to the *most common* value so that only deviations
    need to be specified in the lookup table.
    """

    # ── Database format ────────────────────────────────────────────────
    checksum: ChecksumType = ChecksumType.NONE
    is_shuffle: bool = False
    """If True, device uses iTunesSD (flat binary) instead of / in addition
    to iTunesDB.  Shadow DB version determines the iTunesSD format."""
    shadow_db_version: int = 0
    """0 = not a shuffle.  1 = iTunesSD v1 (Shuffle 1G/2G, 18-byte header,
    558-byte entries, big-endian).  2 = iTunesSD v2 (Shuffle 3G/4G,
    bdhs/hths/hphs chunk format, little-endian)."""
    supports_compressed_db: bool = False
    """If True, device expects iTunesCDB (zlib-compressed iTunesDB) and will
    generate an empty iTunesDB alongside it.  Nano 5G/6G/7G only."""

    # ── Media type support ─────────────────────────────────────────────
    supports_video: bool = False
    """Device can play video files (mediatype & VIDEO != 0)."""
    supports_podcast: bool = True
    """Device supports podcast mhsd types (type 3).  False only for
    very early iPods (1G–3G) and iPod Mobile."""
    supports_gapless: bool = False
    """Device honours gapless playback fields (pregap, postgap,
    samplecount, gapless_data, gapless_track_flag).  Introduced with
    iPod Video 5.5G (Late 2006)."""

    # ── Artwork ────────────────────────────────────────────────────────
    supports_artwork: bool = True
    """Device has an ArtworkDB and .ithmb files for album art."""
    supports_photo: bool = False
    """Device has additional photo artwork formats (for photo viewer)."""
    supports_chapter_image: bool = False
    """Device has chapter image artwork formats (for enhanced podcasts)."""
    supports_sparse_artwork: bool = False
    """Artwork can be written in sparse mode (Nano 3G+, Classic, Touch)."""
    cover_art_formats: tuple[ArtworkFormat, ...] = ()
    """Supported cover-art thumbnail sizes.  Empty means no artwork."""

    # ── Storage layout ─────────────────────────────────────────────────
    music_dirs: int = 20
    """Number of ``Fxx`` directories under ``iPod_Control/Music/``.
    Varies 0–50 depending on model and storage capacity."""

    # ── SQLite database ────────────────────────────────────────────────
    uses_sqlite_db: bool = False
    """If True, device uses SQLite databases in
    ``iTunes Library.itlp/`` instead of (or alongside) binary
    iTunesDB/iTunesCDB.  The firmware on Nano 6G/7G reads the SQLite
    databases and ignores iTunesCDB completely."""

    # ── Writer parameters ──────────────────────────────────────────────
    db_version: int = 0x30
    """iTunesDB version to write in mhbd header.  Older iPods need
    lower values (0x0c for Shuffle 1G/2G, 0x13 for pre-Classic)."""
    byte_order: str = "le"
    """Byte order for database writing.  ``"le"`` for almost all models.
    ``"be"`` for iPod Mobile (Motorola ROKR/SLVR/RAZR)."""

    # ── Screen / display ───────────────────────────────────────────────
    has_screen: bool = True
    """Device has a display.  Shuffles have no screen."""

    # ── Video encoding limits ──────────────────────────────────────────
    max_video_width: int = 0
    """Maximum H.264 decode width (pixels).  0 = no video support.
    This is the firmware decode ceiling, not the screen resolution —
    the device downscales to fit its screen."""
    max_video_height: int = 0
    """Maximum H.264 decode height (pixels).  0 = no video support."""


# ──────────────────────────────────────────────────────────────────────────
# Cover-art format sets — ithmb correlation IDs
#
# ``format_id`` is the correlation ID stored in MHNI/MHIF entries inside
# the ArtworkDB binary.  These are the values that appear on-disk and
# are used by both the parser and writer.
#
# Sources:
#   - Real ArtworkDB files from iPod Classic / Nano / Video / Photo
#   - libgpod itdb_device.c artwork_info_* arrays
#   - ArtworkDB_Parser FORMAT_ID_MAP (cross-referenced)
#   - ArtworkDB_Writer format tables (confirmed working)
# ──────────────────────────────────────────────────────────────────────────

_ART_PHOTO = (
    ArtworkFormat(1017, 56, 56, 112, "RGB565_LE", "cover_small", "Photo album art small"),
    ArtworkFormat(1016, 140, 140, 280, "RGB565_LE", "cover_large", "Photo album art large"),
)

_ART_NANO_1G2G = (
    ArtworkFormat(1031, 42, 42, 84, "RGB565_LE", "cover_small", "Nano album art small"),
    ArtworkFormat(1027, 100, 100, 200, "RGB565_LE", "cover_large", "Nano album art large"),
)

_ART_VIDEO = (
    ArtworkFormat(1028, 100, 100, 200, "RGB565_LE", "cover_small", "Video album art small"),
    ArtworkFormat(1029, 200, 200, 400, "RGB565_LE", "cover_large", "Video album art large"),
)

_ART_CLASSIC = (
    ArtworkFormat(1061, 56, 56, 112, "RGB565_LE", "cover_small", "Classic album art small"),
    ArtworkFormat(1055, 128, 128, 256, "RGB565_LE", "cover_medium", "Classic album art medium"),
    ArtworkFormat(1060, 320, 320, 640, "RGB565_LE", "cover_large", "Classic album art large"),
)

_ART_NANO_4G = (
    ArtworkFormat(1071, 240, 240, 480, "RGB565_LE", "cover_large", "Nano 4G album art large"),
    ArtworkFormat(1074, 50, 50, 100, "RGB565_LE", "cover_xsmall", "Nano 4G album art tiny"),
    ArtworkFormat(1078, 80, 80, 160, "RGB565_LE", "cover_small", "Nano 4G/5G album art small"),
)

_ART_NANO_5G = (
    ArtworkFormat(1073, 240, 240, 480, "RGB565_LE", "cover_large", "Nano 5G album art large"),
    ArtworkFormat(1056, 128, 128, 256, "RGB565_LE", "cover_medium", "Nano 5G album art medium"),
    ArtworkFormat(1078, 80, 80, 160, "RGB565_LE", "cover_small", "Nano 4G/5G album art small"),
    ArtworkFormat(1074, 50, 50, 100, "RGB565_LE", "cover_xsmall", "Nano 4G/5G album art tiny"),
)

# Nano 6G uses different format IDs than Nano 5G.  Dimensions extracted from
# a real Nano 6G ArtworkDB (written by iTunes).  libgpod has no hardcoded
# table for Nano 6G and relies on SysInfoExtended; these match the device.
_ART_NANO_6G = (
    ArtworkFormat(1073, 240, 240, 480, "RGB565_LE", "cover_large", "Nano 6G album art large"),
    ArtworkFormat(1085, 88, 88, 176, "RGB565_LE", "cover_medium", "Nano 6G album art medium"),
    ArtworkFormat(1089, 58, 58, 116, "RGB565_LE", "cover_small", "Nano 6G album art small"),
    ArtworkFormat(1074, 50, 50, 100, "RGB565_LE", "cover_xsmall", "Nano 6G album art tiny"),
)


# ──────────────────────────────────────────────────────────────────────────
# All known ithmb formats — comprehensive correlation-ID lookup
#
# This is the SINGLE SOURCE OF TRUTH for every known ithmb format ID,
# including photo-viewer, TV-output, and alternate cover-art formats that
# may appear in parsed ArtworkDB files from any iPod generation.
#
# Previously duplicated in:
#   - ArtworkDB_Parser/mhni_parser.py  FORMAT_ID_MAP
#   - ArtworkDB_Writer/rgb565.py       IPOD_*_FORMATS dicts
# ──────────────────────────────────────────────────────────────────────────

_EXTRA_FORMATS = (
    # iPod Photo/Video photos & TV
    ArtworkFormat(1009, 42, 30, 84, "RGB565_LE", "photo_list", "Photo list thumbnail"),
    ArtworkFormat(1013, 220, 176, 440, "RGB565_BE_90", "photo_full", "Photo full screen (rotated)"),
    ArtworkFormat(1015, 130, 88, 260, "RGB565_LE", "photo_preview", "Photo/Video preview"),
    ArtworkFormat(1019, 720, 480, 1440, "UYVY", "tv_out", "Photo/Video NTSC TV output"),
    # iPod Nano 1G/2G photos
    ArtworkFormat(1023, 176, 132, 352, "RGB565_BE", "photo_full", "Nano full screen"),
    ArtworkFormat(1032, 42, 37, 84, "RGB565_LE", "photo_list", "Nano list thumbnail"),
    # iPod Video photos
    ArtworkFormat(1024, 320, 240, 640, "RGB565_LE", "photo_full", "Video full screen"),
    ArtworkFormat(1036, 50, 41, 100, "RGB565_LE", "photo_list", "Video list thumbnail"),
    # iPod Classic alternates & photos
    ArtworkFormat(1056, 128, 128, 256, "RGB565_LE", "cover_medium_alt", "Classic album art (alt)"),
    ArtworkFormat(1068, 128, 128, 256, "RGB565_LE", "cover_medium_alt", "Classic album art (alt 2)"),
    ArtworkFormat(1066, 64, 64, 128, "RGB565_LE", "photo_thumb", "Classic photo thumbnail"),
    ArtworkFormat(1067, 720, 480, 1080, "I420_LE", "tv_out", "Classic TV output (YUV)"),
    # iPod Nano 4G/5G alternates & photos
    ArtworkFormat(1084, 240, 240, 480, "RGB565_LE", "cover_large_alt", "Nano 4G album art (alt)"),
    ArtworkFormat(1079, 80, 80, 160, "RGB565_LE", "photo_thumb", "Nano 4G/5G photo thumbnail"),
    ArtworkFormat(1083, 320, 240, 640, "RGB565_LE", "photo_full", "Nano 4G photo full screen"),
    ArtworkFormat(1087, 384, 384, 768, "RGB565_LE", "photo_large", "Nano 5G photo large"),
)

ITHMB_FORMAT_MAP: dict[int, ArtworkFormat] = {}
"""Comprehensive lookup of ithmb correlation ID → `ArtworkFormat`.

This replaces all per-file ``FORMAT_ID_MAP`` dicts.  Used by the parser
to identify image formats by correlation ID, and by the writer to
validate format IDs.
"""
for _group in (_ART_PHOTO, _ART_NANO_1G2G, _ART_VIDEO, _ART_CLASSIC,
               _ART_NANO_4G, _ART_NANO_5G, _ART_NANO_6G, _EXTRA_FORMATS):
    for _af in _group:
        if _af.format_id not in ITHMB_FORMAT_MAP:
            ITHMB_FORMAT_MAP[_af.format_id] = _af

ITHMB_SIZE_MAP: dict[int, ArtworkFormat] = {}
"""Fallback lookup: byte size → `ArtworkFormat`.

Byte size is computed as ``row_bytes × height``.  Used when the
correlation ID is unknown or zero and only the raw image byte count
is available.
"""
for _af in ITHMB_FORMAT_MAP.values():
    _byte_size = _af.row_bytes * _af.height
    if _byte_size > 0 and _byte_size not in ITHMB_SIZE_MAP:
        ITHMB_SIZE_MAP[_byte_size] = _af


def ithmb_formats_for_device(
    family: str,
    generation: str,
) -> dict[int, tuple[int, int]]:
    """Return ``{correlation_id: (width, height)}`` for a device's cover art.

    This is the format expected by the ArtworkDB writer.  Returns an empty
    dict if the device is not recognised or has no artwork support.
    """
    caps = _FAMILY_GEN_CAPABILITIES.get((family, generation))
    if caps is None or not caps.supports_artwork:
        return {}
    return {af.format_id: (af.width, af.height) for af in caps.cover_art_formats}


# ──────────────────────────────────────────────────────────────────────────
# The master capabilities table
# ──────────────────────────────────────────────────────────────────────────

_FAMILY_GEN_CAPABILITIES: dict[tuple[str, str], DeviceCapabilities] = {

    # ── iPod 1G–3G: earliest models, no podcast, no gapless ───────────
    ("iPod", "1st Gen"): DeviceCapabilities(
        supports_podcast=False,
        supports_artwork=False,
        has_screen=True,
        music_dirs=20,
        db_version=0x13,
    ),
    ("iPod", "2nd Gen"): DeviceCapabilities(
        supports_podcast=False,
        supports_artwork=False,
        has_screen=True,
        music_dirs=20,
        db_version=0x13,
    ),
    ("iPod", "3rd Gen"): DeviceCapabilities(
        supports_podcast=False,
        supports_artwork=False,
        has_screen=True,
        music_dirs=20,
        db_version=0x13,
    ),

    # ── iPod 4G (Click Wheel): first with podcast support ─────────────
    ("iPod", "4th Gen"): DeviceCapabilities(
        supports_artwork=False,
        music_dirs=20,
        db_version=0x13,
    ),

    # ── iPod U2 Special Edition (4th Gen hardware) ────────────────────
    ("iPod U2", "4th Gen"): DeviceCapabilities(
        supports_artwork=False,
        music_dirs=20,
        db_version=0x13,
    ),

    # ── iPod Photo (Color Display) ────────────────────────────────────
    ("iPod Photo", "4th Gen"): DeviceCapabilities(
        supports_artwork=True,
        supports_photo=True,
        cover_art_formats=_ART_PHOTO,
        music_dirs=20,
        db_version=0x13,
    ),

    # ── iPod Video 5th Gen ────────────────────────────────────────────
    ("iPod Video", "5th Gen"): DeviceCapabilities(
        supports_video=True,
        supports_artwork=True,
        supports_photo=True,
        cover_art_formats=_ART_VIDEO,
        music_dirs=20,
        db_version=0x19,
        max_video_width=640,
        max_video_height=480,
    ),

    # ── iPod Video 5.5th Gen — first with gapless playback ───────────
    ("iPod Video", "5.5th Gen"): DeviceCapabilities(
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        cover_art_formats=_ART_VIDEO,
        music_dirs=20,
        db_version=0x19,
        max_video_width=640,
        max_video_height=480,
    ),

    # ── iPod Video U2 editions (same hardware as their base) ─────────
    ("iPod Video U2", "5th Gen"): DeviceCapabilities(
        supports_video=True,
        supports_artwork=True,
        supports_photo=True,
        cover_art_formats=_ART_VIDEO,
        music_dirs=20,
        db_version=0x19,
        max_video_width=640,
        max_video_height=480,
    ),
    ("iPod Video U2", "5.5th Gen"): DeviceCapabilities(
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        cover_art_formats=_ART_VIDEO,
        music_dirs=20,
        db_version=0x19,
        max_video_width=640,
        max_video_height=480,
    ),

    # ── iPod Classic (all gens): HASH58, gapless, video ───────────────
    ("iPod Classic", "1st Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH58,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        supports_chapter_image=True,
        supports_sparse_artwork=True,
        cover_art_formats=_ART_CLASSIC,
        music_dirs=50,
        db_version=0x30,
        max_video_width=640,
        max_video_height=480,
    ),
    ("iPod Classic", "2nd Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH58,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        supports_chapter_image=True,
        supports_sparse_artwork=True,
        cover_art_formats=_ART_CLASSIC,
        music_dirs=50,
        db_version=0x30,
        max_video_width=640,
        max_video_height=480,
    ),
    ("iPod Classic", "3rd Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH58,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        supports_chapter_image=True,
        supports_sparse_artwork=True,
        cover_art_formats=_ART_CLASSIC,
        music_dirs=50,
        db_version=0x30,
        max_video_width=640,
        max_video_height=480,
    ),

    # ── iPod Mini (no artwork, no video) ──────────────────────────────
    ("iPod Mini", "1st Gen"): DeviceCapabilities(
        supports_artwork=False,
        music_dirs=6,
        db_version=0x13,
    ),
    ("iPod Mini", "2nd Gen"): DeviceCapabilities(
        supports_artwork=False,
        music_dirs=6,
        db_version=0x13,
    ),

    # ── iPod Nano 1G/2G: small cover art, no video, no gapless ───────
    ("iPod Nano", "1st Gen"): DeviceCapabilities(
        supports_artwork=True,
        supports_photo=True,
        cover_art_formats=_ART_NANO_1G2G,
        music_dirs=14,
        db_version=0x13,
    ),
    ("iPod Nano", "2nd Gen"): DeviceCapabilities(
        supports_artwork=True,
        supports_photo=True,
        cover_art_formats=_ART_NANO_1G2G,
        music_dirs=14,
        db_version=0x13,
    ),

    # ── iPod Nano 3G ("Fat"): first Nano with video, HASH58 ──────────
    ("iPod Nano", "3rd Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH58,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        supports_sparse_artwork=True,
        cover_art_formats=_ART_CLASSIC,  # shares Classic 1G formats
        music_dirs=20,
        db_version=0x30,
        max_video_width=320,
        max_video_height=240,
    ),

    # ── iPod Nano 4G: HASH58, rotated artwork (RGB565_LE_90) ─────────
    ("iPod Nano", "4th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH58,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        supports_chapter_image=True,
        supports_sparse_artwork=True,
        cover_art_formats=_ART_NANO_4G,
        music_dirs=20,
        db_version=0x30,
        max_video_width=480,
        max_video_height=320,
    ),

    # ── iPod Nano 5G: HASH72, camera, compressed DB ──────────────────
    ("iPod Nano", "5th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH72,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        supports_sparse_artwork=True,
        supports_compressed_db=True,
        cover_art_formats=_ART_NANO_5G,
        music_dirs=20,
        db_version=0x30,
        max_video_width=640,
        max_video_height=480,
    ),

    # ── iPod Nano 6G: HASHAB, square touchscreen, no video ───────────
    ("iPod Nano", "6th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASHAB,
        supports_video=False,   # Nano 6G dropped video playback
        supports_gapless=True,
        supports_artwork=True,
        supports_sparse_artwork=True,
        supports_compressed_db=True,
        uses_sqlite_db=True,    # Firmware reads SQLite, ignores iTunesCDB
        cover_art_formats=_ART_NANO_6G,
        music_dirs=20,
        db_version=0x30,
    ),

    # ── iPod Nano 7G: HASHAB, tall touchscreen, video returns ────────
    ("iPod Nano", "7th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASHAB,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_sparse_artwork=True,
        supports_compressed_db=True,
        uses_sqlite_db=True,    # Firmware reads SQLite, ignores iTunesCDB
        cover_art_formats=_ART_NANO_6G,  # assumed same as 6G; no SysInfoExtended data
        music_dirs=20,
        db_version=0x30,
        max_video_width=720,
        max_video_height=576,
    ),

    # ── iPod Shuffle 1G: iTunesSD v1, no screen, no artwork ──────────
    ("iPod Shuffle", "1st Gen"): DeviceCapabilities(
        is_shuffle=True,
        shadow_db_version=1,
        supports_podcast=True,
        supports_artwork=False,
        has_screen=False,
        music_dirs=3,
        db_version=0x0c,
    ),

    # ── iPod Shuffle 2G: iTunesSD v1, no screen ──────────────────────
    ("iPod Shuffle", "2nd Gen"): DeviceCapabilities(
        is_shuffle=True,
        shadow_db_version=1,
        supports_podcast=True,
        supports_artwork=False,
        has_screen=False,
        music_dirs=3,
        db_version=0x13,
    ),

    # ── iPod Shuffle 3G: iTunesSD v2, VoiceOver, no screen ───────────
    ("iPod Shuffle", "3rd Gen"): DeviceCapabilities(
        is_shuffle=True,
        shadow_db_version=2,
        supports_podcast=True,
        supports_artwork=False,
        has_screen=False,
        music_dirs=3,
        db_version=0x19,
    ),

    # ── iPod Shuffle 4G: iTunesSD v2, buttons return, no screen ──────
    ("iPod Shuffle", "4th Gen"): DeviceCapabilities(
        is_shuffle=True,
        shadow_db_version=2,
        supports_podcast=True,
        supports_artwork=False,
        has_screen=False,
        music_dirs=3,
        db_version=0x19,
    ),
}


def capabilities_for_family_gen(
    family: str,
    generation: str,
) -> Optional[DeviceCapabilities]:
    """Return the device capabilities for a (family, generation) pair.

    Returns ``None`` if the pair is not in the lookup table.

    Usage::

        caps = capabilities_for_family_gen("iPod Classic", "2nd Gen")
        if caps and caps.supports_video:
            ...
    """
    return _FAMILY_GEN_CAPABILITIES.get((family, generation))


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Comprehensive iPod model database                                      ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# Maps order number prefixes to (product_line, generation, capacity, color)
#
# Sources:
#   - Universal Compendium iPod Models table (universalcompendium.com)
#   - The Apple Wiki: Models/iPod (theapplewiki.com)
#
# Generation naming conventions:
#   The full-size iPod line has TWO numbering systems. This table uses the
#   product-specific generation (matching what users see in "About" screens),
#   with the overall iPod lineage noted in comments.
#
#   Overall iPod gen │ Product-specific gen │ Years │ Apple Model
#   ─────────────────┼──────────────────────┼───────┼────────────
#   1st gen           │ iPod 1st Gen         │ 2001  │ M8541
#   2nd gen           │ iPod 2nd Gen         │ 2002  │ A1019
#   3rd gen           │ iPod 3rd Gen         │ 2003  │ A1040
#   4th gen           │ iPod 4th Gen         │ 2004  │ A1059
#   4th gen (color)   │ iPod Photo           │ 2004  │ A1099
#   5th gen           │ iPod Video 5th Gen   │ 2005  │ A1136
#   5.5th gen         │ iPod Video 5.5th Gen │ 2006  │ A1136 (Rev B)
#   6th gen           │ iPod Classic 1st Gen │ 2007  │ A1238
#   6.5th gen         │ iPod Classic 2nd Gen │ 2008  │ A1238 (Rev A)
#   7th gen           │ iPod Classic 3rd Gen │ 2009  │ A1238 (Rev B/C)

IPOD_MODELS: dict[str, tuple[str, str, str, str]] = {
    # ==========================================================================
    # iPod Classic (2007-2009)
    # Community: "6th gen / 6.5th gen / 7th gen iPod"
    # ==========================================================================
    # 1st Gen Classic / 6th gen overall (2007) — Apple Model A1238, Internal N25
    'MB029': ("iPod Classic", "1st Gen", "80GB", "Silver"),
    'MB147': ("iPod Classic", "1st Gen", "80GB", "Black"),
    'MB145': ("iPod Classic", "1st Gen", "160GB", "Silver"),
    'MB150': ("iPod Classic", "1st Gen", "160GB", "Black"),
    # 2nd Gen Classic / 6.5th gen overall (2008) — A1238 Rev A (thin, 120GB)
    'MB562': ("iPod Classic", "2nd Gen", "120GB", "Silver"),
    'MB565': ("iPod Classic", "2nd Gen", "120GB", "Black"),
    # 3rd Gen Classic / 7th gen overall (Late 2009) — A1238 Rev B/C
    'MC293': ("iPod Classic", "3rd Gen", "160GB", "Silver"),
    'MC297': ("iPod Classic", "3rd Gen", "160GB", "Black"),

    # ==========================================================================
    # iPod (Scroll Wheel) — 1st Generation (2001)
    # Apple Model: M8541 — Internal: P68/P68C
    # ==========================================================================
    'M8513': ("iPod", "1st Gen", "5GB", "White"),
    'M8541': ("iPod", "1st Gen", "5GB", "White"),
    'M8697': ("iPod", "1st Gen", "5GB", "White"),
    'M8709': ("iPod", "1st Gen", "10GB", "White"),

    # ==========================================================================
    # iPod (Touch Wheel) — 2nd Generation (2002)
    # Apple Model: A1019 — Internal: P97
    # ==========================================================================
    'M8737': ("iPod", "2nd Gen", "10GB", "White"),
    'M8740': ("iPod", "2nd Gen", "10GB", "White"),
    'M8738': ("iPod", "2nd Gen", "20GB", "White"),
    'M8741': ("iPod", "2nd Gen", "20GB", "White"),

    # ==========================================================================
    # iPod (Dock Connector) — 3rd Generation (2003)
    # Apple Model: A1040 — Internal: Q14
    # ==========================================================================
    'M8976': ("iPod", "3rd Gen", "10GB", "White"),
    'M8946': ("iPod", "3rd Gen", "15GB", "White"),
    'M8948': ("iPod", "3rd Gen", "30GB", "White"),
    'M9244': ("iPod", "3rd Gen", "20GB", "White"),
    'M9245': ("iPod", "3rd Gen", "40GB", "White"),
    'M9460': ("iPod", "3rd Gen", "15GB", "White"),  # Rev B

    # ==========================================================================
    # iPod (Click Wheel) — 4th Generation (2004)
    # Apple Model: A1059 — Internal: Q21
    # ==========================================================================
    'M9268': ("iPod", "4th Gen", "40GB", "White"),
    'M9282': ("iPod", "4th Gen", "20GB", "White"),
    # HP-branded iPod 4th Gen (libgpod: E436)
    'ME436': ("iPod", "4th Gen", "40GB", "White"),
    # U2 Special Edition — 4th Gen
    'M9787': ("iPod U2", "4th Gen", "20GB", "Black"),

    # ==========================================================================
    # iPod Photo / iPod with color Display — 4th Gen (Color) (2004-2005)
    # Apple Model: A1099 — Internal: P98
    # Community: "4th gen color" or "iPod Photo"
    # ==========================================================================
    'M9585': ("iPod Photo", "4th Gen", "40GB", "White"),
    'M9586': ("iPod Photo", "4th Gen", "60GB", "White"),
    'M9829': ("iPod Photo", "4th Gen", "30GB", "White"),
    'M9830': ("iPod Photo", "4th Gen", "60GB", "White"),
    'MA079': ("iPod Photo", "4th Gen", "20GB", "White"),
    # U2 Special Edition (color Display)
    'MA127': ("iPod U2", "4th Gen", "20GB", "Black"),
    # HP-branded iPod Photo (libgpod: S492)
    'MS492': ("iPod Photo", "4th Gen", "30GB", "White"),
    # Harry Potter Special Edition
    'MA215': ("iPod Photo", "4th Gen", "20GB", "White"),

    # ==========================================================================
    # iPod Video — 5th Generation (2005)
    # Apple Model: A1136 — Internal: M25
    # Same A1136 for both 5th and 5.5th gen; Rev B = "Enhanced" / 5.5th gen
    # ==========================================================================
    'MA002': ("iPod Video", "5th Gen", "30GB", "White"),
    'MA003': ("iPod Video", "5th Gen", "60GB", "White"),
    'MA146': ("iPod Video", "5th Gen", "30GB", "Black"),
    'MA147': ("iPod Video", "5th Gen", "60GB", "Black"),
    # U2 Special Edition — 5th Gen
    'MA452': ("iPod Video U2", "5th Gen", "30GB", "Black"),

    # ==========================================================================
    # iPod Video — 5.5th Generation / Enhanced (Late 2006)
    # Apple Model: A1136 Rev B — Internal: M25
    # Community: "5.5th gen" — brighter screen, search feature, gapless playback
    # ==========================================================================
    'MA444': ("iPod Video", "5.5th Gen", "30GB", "White"),
    'MA446': ("iPod Video", "5.5th Gen", "30GB", "Black"),
    'MA448': ("iPod Video", "5.5th Gen", "80GB", "White"),
    'MA450': ("iPod Video", "5.5th Gen", "80GB", "Black"),
    # U2 Special Edition — 5.5th Gen
    'MA664': ("iPod Video U2", "5.5th Gen", "30GB", "Black"),

    # ==========================================================================
    # iPod Mini — 1st Generation (2004)
    # Apple Model: A1051 — Internal: Q22
    # ==========================================================================
    'M9160': ("iPod Mini", "1st Gen", "4GB", "Silver"),
    'M9434': ("iPod Mini", "1st Gen", "4GB", "Green"),
    'M9435': ("iPod Mini", "1st Gen", "4GB", "Pink"),
    'M9436': ("iPod Mini", "1st Gen", "4GB", "Blue"),
    'M9437': ("iPod Mini", "1st Gen", "4GB", "Gold"),

    # ==========================================================================
    # iPod Mini — 2nd Generation (2005)
    # Apple Model: A1051 — Internal: Q22B
    # ==========================================================================
    'M9800': ("iPod Mini", "2nd Gen", "4GB", "Silver"),
    'M9801': ("iPod Mini", "2nd Gen", "6GB", "Silver"),
    'M9802': ("iPod Mini", "2nd Gen", "4GB", "Blue"),
    'M9803': ("iPod Mini", "2nd Gen", "6GB", "Blue"),
    'M9804': ("iPod Mini", "2nd Gen", "4GB", "Pink"),
    'M9805': ("iPod Mini", "2nd Gen", "6GB", "Pink"),
    'M9806': ("iPod Mini", "2nd Gen", "4GB", "Green"),
    'M9807': ("iPod Mini", "2nd Gen", "6GB", "Green"),

    # ==========================================================================
    # iPod Nano — 1st Generation (2005)
    # Apple Model: A1137 — Internal: M26
    # ==========================================================================
    'MA004': ("iPod Nano", "1st Gen", "2GB", "White"),
    'MA005': ("iPod Nano", "1st Gen", "4GB", "White"),
    'MA099': ("iPod Nano", "1st Gen", "2GB", "Black"),
    'MA107': ("iPod Nano", "1st Gen", "4GB", "Black"),
    'MA350': ("iPod Nano", "1st Gen", "1GB", "White"),
    'MA352': ("iPod Nano", "1st Gen", "1GB", "Black"),

    # ==========================================================================
    # iPod Nano — 2nd Generation (2006)
    # Apple Model: A1199 — Internal: N36
    # ==========================================================================
    'MA426': ("iPod Nano", "2nd Gen", "4GB", "Silver"),
    'MA428': ("iPod Nano", "2nd Gen", "4GB", "Blue"),
    'MA477': ("iPod Nano", "2nd Gen", "2GB", "Silver"),
    'MA487': ("iPod Nano", "2nd Gen", "4GB", "Green"),
    'MA489': ("iPod Nano", "2nd Gen", "4GB", "Pink"),
    'MA497': ("iPod Nano", "2nd Gen", "8GB", "Black"),
    'MA725': ("iPod Nano", "2nd Gen", "4GB", "Red"),
    'MA726': ("iPod Nano", "2nd Gen", "8GB", "Red"),
    'MA899': ("iPod Nano", "2nd Gen", "8GB", "Red"),

    # ==========================================================================
    # iPod Nano — 3rd Generation (2007, "Fat" Nano with video)
    # Apple Model: A1236 — Internal: N46
    # ==========================================================================
    'MA978': ("iPod Nano", "3rd Gen", "4GB", "Silver"),
    'MA980': ("iPod Nano", "3rd Gen", "8GB", "Silver"),
    'MB249': ("iPod Nano", "3rd Gen", "8GB", "Blue"),
    'MB253': ("iPod Nano", "3rd Gen", "8GB", "Green"),
    'MB257': ("iPod Nano", "3rd Gen", "8GB", "Red"),
    'MB261': ("iPod Nano", "3rd Gen", "8GB", "Black"),
    'MB453': ("iPod Nano", "3rd Gen", "8GB", "Pink"),

    # ==========================================================================
    # iPod Nano — 4th Generation (2008)
    # Apple Model: A1285 — Internal: N58
    # ==========================================================================
    # 4GB
    'MB480': ("iPod Nano", "4th Gen", "4GB", "Silver"),
    'MB651': ("iPod Nano", "4th Gen", "4GB", "Blue"),
    'MB654': ("iPod Nano", "4th Gen", "4GB", "Pink"),
    'MB657': ("iPod Nano", "4th Gen", "4GB", "Purple"),
    'MB660': ("iPod Nano", "4th Gen", "4GB", "Orange"),
    'MB663': ("iPod Nano", "4th Gen", "4GB", "Green"),
    'MB666': ("iPod Nano", "4th Gen", "4GB", "Yellow"),
    # 8GB
    'MB598': ("iPod Nano", "4th Gen", "8GB", "Silver"),
    'MB732': ("iPod Nano", "4th Gen", "8GB", "Blue"),
    'MB735': ("iPod Nano", "4th Gen", "8GB", "Pink"),
    'MB739': ("iPod Nano", "4th Gen", "8GB", "Purple"),
    'MB742': ("iPod Nano", "4th Gen", "8GB", "Orange"),
    'MB745': ("iPod Nano", "4th Gen", "8GB", "Green"),
    'MB748': ("iPod Nano", "4th Gen", "8GB", "Yellow"),
    'MB751': ("iPod Nano", "4th Gen", "8GB", "Red"),
    'MB754': ("iPod Nano", "4th Gen", "8GB", "Black"),
    # 16GB
    'MB903': ("iPod Nano", "4th Gen", "16GB", "Silver"),
    'MB905': ("iPod Nano", "4th Gen", "16GB", "Blue"),
    'MB907': ("iPod Nano", "4th Gen", "16GB", "Pink"),
    'MB909': ("iPod Nano", "4th Gen", "16GB", "Purple"),
    'MB911': ("iPod Nano", "4th Gen", "16GB", "Orange"),
    'MB913': ("iPod Nano", "4th Gen", "16GB", "Green"),
    'MB915': ("iPod Nano", "4th Gen", "16GB", "Yellow"),
    'MB917': ("iPod Nano", "4th Gen", "16GB", "Red"),
    'MB918': ("iPod Nano", "4th Gen", "16GB", "Black"),

    # ==========================================================================
    # iPod Nano — 5th Generation (2009, Camera Nano)
    # Apple Model: A1320 — Internal: N33
    # ==========================================================================
    # 8GB
    'MC027': ("iPod Nano", "5th Gen", "8GB", "Silver"),
    'MC031': ("iPod Nano", "5th Gen", "8GB", "Black"),
    'MC034': ("iPod Nano", "5th Gen", "8GB", "Purple"),
    'MC037': ("iPod Nano", "5th Gen", "8GB", "Blue"),
    'MC040': ("iPod Nano", "5th Gen", "8GB", "Green"),
    'MC043': ("iPod Nano", "5th Gen", "8GB", "Yellow"),
    'MC046': ("iPod Nano", "5th Gen", "8GB", "Orange"),
    'MC049': ("iPod Nano", "5th Gen", "8GB", "Red"),
    'MC050': ("iPod Nano", "5th Gen", "8GB", "Pink"),
    # 16GB
    'MC060': ("iPod Nano", "5th Gen", "16GB", "Silver"),
    'MC062': ("iPod Nano", "5th Gen", "16GB", "Black"),
    'MC064': ("iPod Nano", "5th Gen", "16GB", "Purple"),
    'MC066': ("iPod Nano", "5th Gen", "16GB", "Blue"),
    'MC068': ("iPod Nano", "5th Gen", "16GB", "Green"),
    'MC070': ("iPod Nano", "5th Gen", "16GB", "Yellow"),
    'MC072': ("iPod Nano", "5th Gen", "16GB", "Orange"),
    'MC074': ("iPod Nano", "5th Gen", "16GB", "Red"),
    'MC075': ("iPod Nano", "5th Gen", "16GB", "Pink"),

    # ==========================================================================
    # iPod Nano — 6th Generation (2010, Square Touchscreen)
    # Apple Model: A1366 — Internal: N20
    # ==========================================================================
    # 8GB
    'MC525': ("iPod Nano", "6th Gen", "8GB", "Silver"),
    'MC688': ("iPod Nano", "6th Gen", "8GB", "Graphite"),
    'MC689': ("iPod Nano", "6th Gen", "8GB", "Blue"),
    'MC690': ("iPod Nano", "6th Gen", "8GB", "Green"),
    'MC691': ("iPod Nano", "6th Gen", "8GB", "Orange"),
    'MC692': ("iPod Nano", "6th Gen", "8GB", "Pink"),
    'MC693': ("iPod Nano", "6th Gen", "8GB", "Red"),
    # 16GB
    'MC526': ("iPod Nano", "6th Gen", "16GB", "Silver"),
    'MC694': ("iPod Nano", "6th Gen", "16GB", "Graphite"),
    'MC695': ("iPod Nano", "6th Gen", "16GB", "Blue"),
    'MC696': ("iPod Nano", "6th Gen", "16GB", "Green"),
    'MC697': ("iPod Nano", "6th Gen", "16GB", "Orange"),
    'MC698': ("iPod Nano", "6th Gen", "16GB", "Pink"),
    'MC699': ("iPod Nano", "6th Gen", "16GB", "Red"),

    # ==========================================================================
    # iPod Nano — 7th Generation (2012, Tall Touchscreen)
    # Apple Model: A1446 — Internal: N31
    # ==========================================================================
    'MD475': ("iPod Nano", "7th Gen", "16GB", "Pink"),
    'MD476': ("iPod Nano", "7th Gen", "16GB", "Yellow"),
    'MD477': ("iPod Nano", "7th Gen", "16GB", "Blue"),
    'MD478': ("iPod Nano", "7th Gen", "16GB", "Green"),
    'MD479': ("iPod Nano", "7th Gen", "16GB", "Purple"),
    'MD480': ("iPod Nano", "7th Gen", "16GB", "Silver"),
    'MD481': ("iPod Nano", "7th Gen", "16GB", "Slate"),
    'MD744': ("iPod Nano", "7th Gen", "16GB", "Red"),
    'ME971': ("iPod Nano", "7th Gen", "16GB", "Space Gray"),
    # Mid 2015 refresh (Rev A) — same A1446
    'MKMV2': ("iPod Nano", "7th Gen", "16GB", "Pink"),
    'MKMX2': ("iPod Nano", "7th Gen", "16GB", "Gold"),
    'MKN02': ("iPod Nano", "7th Gen", "16GB", "Blue"),
    'MKN22': ("iPod Nano", "7th Gen", "16GB", "Silver"),
    'MKN52': ("iPod Nano", "7th Gen", "16GB", "Space Gray"),
    'MKN72': ("iPod Nano", "7th Gen", "16GB", "Red"),

    # ==========================================================================
    # iPod Shuffle — 1st Generation (2005)
    # Apple Model: A1112 — Internal: Q98
    # ==========================================================================
    'M9724': ("iPod Shuffle", "1st Gen", "512MB", "White"),
    'M9725': ("iPod Shuffle", "1st Gen", "1GB", "White"),

    # ==========================================================================
    # iPod Shuffle — 2nd Generation (2006-2008)
    # Apple Model: A1204 — Internal: N98
    # Multiple color refreshes within same generation
    # ==========================================================================
    # Initial (2006) — order number MA564LL/A, ModelNumStr xA546
    'MA546': ("iPod Shuffle", "2nd Gen", "1GB", "Silver"),
    'MA564': ("iPod Shuffle", "2nd Gen", "1GB", "Silver"),
    # Jan 2007 colors
    'MA947': ("iPod Shuffle", "2nd Gen", "1GB", "Pink"),
    'MA949': ("iPod Shuffle", "2nd Gen", "1GB", "Blue"),
    'MA951': ("iPod Shuffle", "2nd Gen", "1GB", "Green"),
    'MA953': ("iPod Shuffle", "2nd Gen", "1GB", "Orange"),
    # Sept 2007 (Rev A) — 1GB
    'MB225': ("iPod Shuffle", "2nd Gen", "1GB", "Silver"),
    'MB227': ("iPod Shuffle", "2nd Gen", "1GB", "Blue"),
    'MB228': ("iPod Shuffle", "2nd Gen", "1GB", "Blue"),
    'MB229': ("iPod Shuffle", "2nd Gen", "1GB", "Green"),
    'MB231': ("iPod Shuffle", "2nd Gen", "1GB", "Red"),
    'MB233': ("iPod Shuffle", "2nd Gen", "1GB", "Purple"),
    # Sept 2007 (Rev A) — 2GB
    'MB518': ("iPod Shuffle", "2nd Gen", "2GB", "Silver"),
    'MB520': ("iPod Shuffle", "2nd Gen", "2GB", "Blue"),
    'MB522': ("iPod Shuffle", "2nd Gen", "2GB", "Green"),
    'MB524': ("iPod Shuffle", "2nd Gen", "2GB", "Red"),
    'MB526': ("iPod Shuffle", "2nd Gen", "2GB", "Purple"),
    # 2008 (Rev B) — 1GB
    'MB811': ("iPod Shuffle", "2nd Gen", "1GB", "Pink"),
    'MB813': ("iPod Shuffle", "2nd Gen", "1GB", "Blue"),
    'MB815': ("iPod Shuffle", "2nd Gen", "1GB", "Green"),
    'MB817': ("iPod Shuffle", "2nd Gen", "1GB", "Red"),
    # 2008 (Rev B) — 2GB
    'MB681': ("iPod Shuffle", "2nd Gen", "2GB", "Pink"),
    'MB683': ("iPod Shuffle", "2nd Gen", "2GB", "Blue"),
    'MB685': ("iPod Shuffle", "2nd Gen", "2GB", "Green"),
    'MB779': ("iPod Shuffle", "2nd Gen", "2GB", "Red"),
    # Special Edition
    'MC167': ("iPod Shuffle", "2nd Gen", "1GB", "Gold"),

    # ==========================================================================
    # iPod Shuffle — 3rd Generation (2009, Buttonless/VoiceOver)
    # Apple Model: A1271 — Internal: D98
    # ==========================================================================
    'MB867': ("iPod Shuffle", "3rd Gen", "4GB", "Silver"),
    'MC164': ("iPod Shuffle", "3rd Gen", "4GB", "Black"),
    # Sept 2009 refresh — 2GB
    'MC306': ("iPod Shuffle", "3rd Gen", "2GB", "Silver"),
    'MC323': ("iPod Shuffle", "3rd Gen", "2GB", "Black"),
    'MC381': ("iPod Shuffle", "3rd Gen", "2GB", "Green"),
    'MC384': ("iPod Shuffle", "3rd Gen", "2GB", "Blue"),
    'MC387': ("iPod Shuffle", "3rd Gen", "2GB", "Pink"),
    # Sept 2009 refresh — 4GB
    'MC303': ("iPod Shuffle", "3rd Gen", "4GB", "Stainless Steel"),
    'MC307': ("iPod Shuffle", "3rd Gen", "4GB", "Green"),
    'MC328': ("iPod Shuffle", "3rd Gen", "4GB", "Blue"),
    'MC331': ("iPod Shuffle", "3rd Gen", "4GB", "Pink"),

    # ==========================================================================
    # iPod Shuffle — 4th Generation (2010-2015)
    # Apple Model: A1373 — Internal: N12
    # ==========================================================================
    # Initial (Sept 2010)
    'MC584': ("iPod Shuffle", "4th Gen", "2GB", "Silver"),
    'MC585': ("iPod Shuffle", "4th Gen", "2GB", "Pink"),
    'MC749': ("iPod Shuffle", "4th Gen", "2GB", "Orange"),
    'MC750': ("iPod Shuffle", "4th Gen", "2GB", "Green"),
    'MC751': ("iPod Shuffle", "4th Gen", "2GB", "Blue"),
    # Late 2012 (Rev A)
    'MD773': ("iPod Shuffle", "4th Gen", "2GB", "Pink"),
    'MD774': ("iPod Shuffle", "4th Gen", "2GB", "Yellow"),
    'MD775': ("iPod Shuffle", "4th Gen", "2GB", "Blue"),
    'MD776': ("iPod Shuffle", "4th Gen", "2GB", "Green"),
    'MD777': ("iPod Shuffle", "4th Gen", "2GB", "Purple"),
    'MD778': ("iPod Shuffle", "4th Gen", "2GB", "Silver"),
    'MD779': ("iPod Shuffle", "4th Gen", "2GB", "Slate"),
    'MD780': ("iPod Shuffle", "4th Gen", "2GB", "Red"),
    'ME949': ("iPod Shuffle", "4th Gen", "2GB", "Space Gray"),
    # Mid 2015 (Rev B)
    'MKM72': ("iPod Shuffle", "4th Gen", "2GB", "Pink"),
    'MKM92': ("iPod Shuffle", "4th Gen", "2GB", "Gold"),
    'MKME2': ("iPod Shuffle", "4th Gen", "2GB", "Blue"),
    'MKMG2': ("iPod Shuffle", "4th Gen", "2GB", "Silver"),
    'MKMJ2': ("iPod Shuffle", "4th Gen", "2GB", "Space Gray"),
    'MKML2': ("iPod Shuffle", "4th Gen", "2GB", "Red"),
}


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  USB Product ID → iPod generation (Apple VID = 0x05AC)                  ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# Sources: Linux USB ID Repository, The Apple Wiki, empirical testing.
#
# IMPORTANT: The 0x124x range are DFU/WTF recovery mode PIDs, NOT normal
# operation PIDs.  They should only appear if the iPod is in recovery mode.
# In normal disk mode, iPods use PIDs from 0x120x and 0x126x ranges.
#
# Note: Some PIDs are shared across generations or USB modes.  PID-based
# identification is a LOW-confidence fallback — prefer SysInfo ModelNumStr
# or serial number suffix matching.

USB_PID_TO_MODEL: dict[int, tuple[str, str]] = {
    # (model_family, generation)

    # ── Normal-mode PIDs (0x120x) ──────────────────────────────────────────
    0x1201: ("iPod", "3rd Gen"),       # iPod 3G (dock connector)
    0x1202: ("iPod", "2nd Gen"),       # iPod 2G (touch wheel)
    0x1203: ("iPod", "4th Gen"),       # iPod 4G (click wheel, grayscale)
    0x1204: ("iPod Photo", "4th Gen"),  # iPod Photo / iPod with color Display
    0x1205: ("iPod Mini", "1st Gen"),  # iPod Mini 1G
    0x1206: ("iPod Nano", "1st Gen"),  # iPod Nano 1G (A1137)
    0x1207: ("iPod Mini", "2nd Gen"),  # iPod Mini 2G
    0x1208: ("iPod", "1st Gen"),       # iPod 1G (scroll wheel, FireWire)
    0x1209: ("iPod Video", "5th Gen"),  # iPod Video 5G/5.5G (A1136)
    0x120A: ("iPod Nano", "2nd Gen"),  # iPod Nano 2G (A1199) — disk mode

    # ── DFU / WTF recovery mode PIDs (0x124x) ─────────────────────────────
    # These appear when the iPod is in firmware recovery, NOT normal use.
    # Included so recovery-mode devices are still identified, but marked with
    # a "(Recovery)" suffix in the generation string.
    0x1240: ("iPod Nano", "2nd Gen (Recovery)"),     # Nano 2G DFU
    0x1241: ("iPod Classic", "1st Gen (Recovery)"),   # Classic 1G DFU
    0x1242: ("iPod Nano", "3rd Gen (Recovery)"),      # Nano 3G WTF
    0x1243: ("iPod Nano", "4th Gen (Recovery)"),      # Nano 4G WTF
    0x1245: ("iPod Classic", "3rd Gen (Recovery)"),   # Classic 3G WTF
    0x1246: ("iPod Nano", "5th Gen (Recovery)"),      # Nano 5G WTF
    0x1255: ("iPod Nano", "4th Gen (Recovery)"),      # Nano 4G DFU

    # ── Normal-mode PIDs (0x126x) ──────────────────────────────────────────
    0x1260: ("iPod Nano", "2nd Gen"),  # iPod Nano 2G (A1199) — normal mode
    0x1261: ("iPod Classic", ""),      # iPod Classic (all gens share this PID)
    0x1262: ("iPod Nano", "3rd Gen"),  # iPod Nano 3G (A1236)
    0x1263: ("iPod Nano", "4th Gen"),  # iPod Nano 4G (A1285)
    0x1265: ("iPod Nano", "5th Gen"),  # iPod Nano 5G (A1320)
    0x1266: ("iPod Nano", "6th Gen"),  # iPod Nano 6G (A1366)
    0x1267: ("iPod Nano", "7th Gen"),  # iPod Nano 7G (A1446)

    # ── iPod Shuffle PIDs ──────────────────────────────────────────────────
    0x1300: ("iPod Shuffle", "1st Gen"),
    0x1301: ("iPod Shuffle", "2nd Gen"),
    0x1302: ("iPod Shuffle", "3rd Gen"),
    0x1303: ("iPod Shuffle", "4th Gen"),
}


# Convenience set for USB device filtering (all known iPod USB Product IDs).
IPOD_USB_PIDS: frozenset[int] = frozenset(USB_PID_TO_MODEL)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Serial number last-3-char → model number (from libgpod)                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

SERIAL_LAST3_TO_MODEL: dict[str, str] = {
    # ── iPod Classic ────────────────────────────────────────────────────
    "Y5N": "MB029", "YMV": "MB147", "YMU": "MB145", "YMX": "MB150",
    "2C5": "MB562", "2C7": "MB565",
    "9ZS": "MC293", "9ZU": "MC297",
    # ── iPod 1G (scroll wheel) ─────────────────────────────────────────
    "LG6": "M8541", "NAM": "M8541", "MJ2": "M8541",
    "ML1": "M8709", "MME": "M8709",
    # ── iPod 2G (touch wheel) ──────────────────────────────────────────
    "MMB": "M8737", "MMC": "M8738",
    "NGE": "M8740", "NGH": "M8740", "MMF": "M8741",
    # ── iPod 3G (dock connector) ───────────────────────────────────────
    "NLW": "M8946", "NRH": "M8976", "QQF": "M9460",
    "PQ5": "M9244", "PNT": "M9244", "NLY": "M8948", "NM7": "M8948",
    "PNU": "M9245",
    # ── iPod 4G (click wheel) ──────────────────────────────────────────
    "PS9": "M9282", "Q8U": "M9282", "PQ7": "M9268",
    # ── iPod U2 ────────────────────────────────────────────────────────
    "V9V": "M9787", "S2X": "M9787",
    # ── iPod Photo / Color Display ─────────────────────────────────────
    "TDU": "MA079", "TDS": "MA079", "TM2": "MA127",
    "SAZ": "M9830", "SB1": "M9830", "SAY": "M9829",
    "R5Q": "M9585", "R5R": "M9586", "R5T": "M9586",
    # ── iPod Mini 1G ───────────────────────────────────────────────────
    "PFW": "M9160", "PRC": "M9160",
    "QKL": "M9436", "QKQ": "M9436", "QKK": "M9435", "QKP": "M9435",
    "QKJ": "M9434", "QKN": "M9434", "QKM": "M9437", "QKR": "M9437",
    # ── iPod Mini 2G ───────────────────────────────────────────────────
    "S41": "M9800", "S4C": "M9800", "S43": "M9802", "S45": "M9804",
    "S47": "M9806", "S4J": "M9806", "S42": "M9801", "S44": "M9803",
    "S48": "M9807",
    # ── Shuffle 1G ─────────────────────────────────────────────────────
    "RS9": "M9724", "QGV": "M9724", "TSX": "M9724", "PFV": "M9724",
    "R80": "M9724", "RSA": "M9725", "TSY": "M9725", "C60": "M9725",
    # ── Shuffle 2G ─────────────────────────────────────────────────────
    "VTE": "MA546", "VTF": "MA546",
    "XQ5": "MA947", "XQS": "MA947", "XQV": "MA949", "XQX": "MA949",
    "YX7": "MB228", "XQY": "MA951", "YX8": "MA951", "XR1": "MA953",
    "YXA": "MB233", "YX6": "MB225", "YX9": "MB225",
    "8CQ": "MC167", "1ZH": "MB518",
    # ── Shuffle 3G ─────────────────────────────────────────────────────
    "A1S": "MC306", "A78": "MC323", "ALB": "MC381", "ALD": "MC384",
    "ALG": "MC387", "4NZ": "MB867", "891": "MC164",
    "A1L": "MC303", "A1U": "MC307", "A7B": "MC328", "A7D": "MC331",
    # ── Shuffle 4G ─────────────────────────────────────────────────────
    "CMJ": "MC584", "CMK": "MC585", "FDM": "MC749", "FDN": "MC750",
    "FDP": "MC751",
    # ── Nano 1G ────────────────────────────────────────────────────────
    "TUZ": "MA004", "TV0": "MA005", "TUY": "MA099", "TV1": "MA107",
    "UYN": "MA350", "UYP": "MA352",
    "UNA": "MA350", "UNB": "MA350", "UPR": "MA352", "UPS": "MA352",
    "SZB": "MA004", "SZV": "MA004", "SZW": "MA004",
    "SZC": "MA005", "SZT": "MA005",
    "TJT": "MA099", "TJU": "MA099", "TK2": "MA107", "TK3": "MA107",
    # ── Nano 2G (A1199) ────────────────────────────────────────────────
    "VQ5": "MA477", "VQ6": "MA477",
    "V8T": "MA426", "V8U": "MA426",
    "V8W": "MA428", "V8X": "MA428",
    "VQH": "MA487", "VQJ": "MA487",
    "VQK": "MA489", "VQL": "MA489", "VKL": "MA489",
    "WL2": "MA725", "WL3": "MA725",
    "X9A": "MA726", "X9B": "MA726",
    "VQT": "MA497", "VQU": "MA497",
    "YER": "MA899", "YES": "MA899",
    # ── Nano 3G ────────────────────────────────────────────────────────
    "Y0P": "MA978", "Y0R": "MA980",
    "YXR": "MB249", "YXV": "MB257", "YXT": "MB253", "YXX": "MB261",
    # ── Nano 4G ────────────────────────────────────────────────────────
    "37P": "MB663", "37Q": "MB666", "37H": "MB654", "1P1": "MB480",
    "37K": "MB657", "37L": "MB660", "2ME": "MB598",
    "3QS": "MB732", "3QT": "MB735", "3QU": "MB739", "3QW": "MB742",
    "3QX": "MB745", "3QY": "MB748", "3R0": "MB754", "3QZ": "MB751",
    "5B7": "MB903", "5B8": "MB905", "5B9": "MB907", "5BA": "MB909",
    "5BB": "MB911", "5BC": "MB913", "5BD": "MB915", "5BE": "MB917",
    "5BF": "MB918",
    # ── Nano 5G ────────────────────────────────────────────────────────
    "71V": "MC027", "71Y": "MC031", "721": "MC034", "726": "MC037",
    "72A": "MC040", "72F": "MC046", "72K": "MC049", "72L": "MC050",
    "72Q": "MC060", "72R": "MC062",
    "72S": "MC064", "72X": "MC066", "734": "MC068", "738": "MC070",
    "739": "MC072", "73A": "MC074", "73B": "MC075",
    # ── Nano 6G ────────────────────────────────────────────────────────
    "CMN": "MC525", "CMP": "MC526",
    "DVX": "MC688", "DVY": "MC689", "DW0": "MC690", "DW1": "MC691",
    "DW2": "MC692", "DW3": "MC693",
    "DW4": "MC694", "DW5": "MC695", "DW6": "MC696", "DW7": "MC697",
    "DW8": "MC698", "DW9": "MC699",
    # ── Video 5G ───────────────────────────────────────────────────────
    "SZ9": "MA002", "WEC": "MA002", "WED": "MA002", "WEG": "MA002",
    "WEH": "MA002", "WEL": "MA002",
    "TXK": "MA146", "TXM": "MA146", "WEF": "MA146",
    "WEJ": "MA146", "WEK": "MA146",
    "SZA": "MA003", "SZU": "MA003", "TXL": "MA147", "TXN": "MA147",
    # ── Video 5.5G ─────────────────────────────────────────────────────
    "V9K": "MA444", "V9L": "MA444", "WU9": "MA444",
    "VQM": "MA446", "V9M": "MA446", "V9N": "MA446", "WEE": "MA446",
    "V9P": "MA448", "V9Q": "MA448",
    "V9R": "MA450", "V9S": "MA450", "V95": "MA450",
    "V96": "MA450", "WUC": "MA450",
    "W9G": "MA664",  # Video U2 5.5G
}


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Model lookup functions                                                 ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def extract_model_number(model_str: str) -> Optional[str]:
    """Extract normalised model number from ModelNumStr.

    ModelNumStr format varies:
    - ``"xA623"`` → ``"MA623"``
    - ``"MC293"`` → ``"MC293"``
    - ``"M9282"`` → ``"M9282"``
    """
    if not model_str:
        return None

    # Remove leading 'x' if present (some devices use xANNN format)
    if model_str.startswith('x'):
        model_str = 'M' + model_str[1:]

    # Extract model number (typically 5 characters: MXXXX or MAXXXX)
    match = re.match(r'^(M[A-Z]?\d{3,4})', model_str.upper())
    if match:
        return match.group(1)

    return model_str.upper()[:5] if len(model_str) >= 5 else model_str.upper()


def get_model_info(model_number: Optional[str]) -> tuple[str, str, str, str] | None:
    """Get detailed model information from model number.

    Args:
        model_number: 5-char model number (e.g., ``'MC293'``)

    Returns:
        Tuple of ``(name, generation, capacity, color)`` or ``None``.
    """
    if not model_number:
        return None

    # Exact match first
    if model_number in IPOD_MODELS:
        return IPOD_MODELS[model_number]

    # Try prefix matching (some models share prefixes)
    for prefix, info in IPOD_MODELS.items():
        if model_number.startswith(prefix[:4]):
            return info

    return None


def get_friendly_model_name(model_number: Optional[str]) -> str:
    """Return a user-friendly model name string.

    Args:
        model_number: 5-char model number (e.g., ``'MC293'``)

    Returns:
        Friendly name like ``"iPod Classic 160GB Silver (2nd Gen)"``
    """
    info = get_model_info(model_number)
    if info:
        name, gen, capacity, color = info
        parts = [name, capacity]
        if color:
            parts.append(color)
        if gen:
            parts.append(f"({gen})")
        return " ".join(p for p in parts if p)
    return f"Unknown iPod ({model_number})" if model_number else "Unknown iPod"


def lookup_by_serial(serial: str) -> tuple[str, tuple[str, str, str, str]] | None:
    """Look up iPod model from a serial number's last 3 characters.

    Combines ``SERIAL_LAST3_TO_MODEL`` and ``IPOD_MODELS`` in a single call.

    Args:
        serial: Full Apple serial number (at least 3 characters).

    Returns:
        ``(model_number, (family, generation, capacity, color))`` or ``None``.
    """
    if not serial or len(serial) < 3:
        return None
    model_num = SERIAL_LAST3_TO_MODEL.get(serial[-3:])
    if not model_num:
        return None
    info = IPOD_MODELS.get(model_num)
    if not info:
        return None
    return (model_num, info)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  iPod product image mapping                                             ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# Maps iPod model families, generations, and colors to official Apple device
# icons stored in assets/ipod_images/.  Icons extracted from macOS
# AMPDevices.framework — the same images Finder/iTunes use.
#
# Apple's icon filenames use an internal "iPodNN" numbering that corresponds
# to Apple's FamilyID system.  The mapping below was confirmed empirically
# (iPod Nano 2G → FamilyID 9 → iPod9-*.png, iPod Classic → FamilyID 11 →
# iPod11-*.png).
#
# Icon numbering reference:
#   iPod1          iPod 1st Gen / 2nd Gen
#   iPod2          iPod 3rd Gen (dock connector)
#   iPod3          iPod Mini 1st Gen; also Mini 2nd Gen Silver
#   iPod3B         iPod Mini 2nd Gen (non-Silver)
#   iPod4          iPod 4th Gen (click wheel) + U2 edition
#   iPod5          iPod Photo / iPod with Color Display + U2 edition
#   iPod6          iPod with Video (5th Gen) + U2 edition
#   iPod7          iPod Nano 1st Gen
#   iPod9          iPod Nano 2nd Gen
#   iPod11         iPod Classic 6th Gen Silver
#   iPod11B        iPod Classic 2nd/3rd Gen Gray ("Black")
#   iPod12         iPod Nano 3rd Gen
#   iPod15         iPod Nano 4th Gen
#   iPod16         iPod Nano 5th Gen
#   iPod17         iPod Nano 6th Gen
#   iPod18         iPod Nano 7th Gen (2013)
#   iPod18A        iPod Nano 7th Gen (2015 refresh)
#   iPod128        iPod Shuffle 1st Gen
#   iPod130/C/F    iPod Shuffle 2nd Gen (2007/late-2007/2008 revisions)
#   iPod132/B      iPod Shuffle 3rd Gen
#   iPod133/B/D    iPod Shuffle 4th Gen (2010/2012/2015 revisions)

# Key: (model_family_lower, generation_lower, color_lower) → filename
COLOR_MAP: dict[tuple[str, str, str], str] = {
    # ── iPod (1G–4G) ────────────────────────────────────────
    ("ipod", "1st gen", "white"): "iPod1.png",
    ("ipod", "2nd gen", "white"): "iPod1.png",
    ("ipod", "3rd gen", "white"): "iPod2.png",
    ("ipod", "4th gen", "white"): "iPod4-White.png",
    ("ipod u2", "4th gen", "black"): "iPod4-BlackRed.png",

    # ── iPod Photo / iPod with Color Display (4th gen)──────
    ("ipod photo", "4th gen", "white"): "iPod5-White.png",
    ("ipod photo u2", "4th gen", "black"): "iPod5-BlackRed.png",

    # ── iPod with Video (5th Gen / 5.5th Gen) ────────────
    # 5th and 5.5th gen are visually identical — same images.
    ("ipod video", "5th gen", "white"): "iPod6-White.png",
    ("ipod video", "5th gen", "black"): "iPod6-Black.png",
    ("ipod video", "5.5th gen", "white"): "iPod6-White.png",
    ("ipod video", "5.5th gen", "black"): "iPod6-Black.png",
    ("ipod video u2", "5th gen", "black"): "iPod6-BlackRed.png",
    ("ipod video u2", "5.5th gen", "black"): "iPod6-BlackRed.png",

    # ── iPod Classic (1st–3rd Gen) ───────────────────────
    ("ipod classic", "1st gen", "silver"): "iPod11-Silver.png",
    ("ipod classic", "1st gen", "black"): "iPod11-Black.png",
    ("ipod classic", "2nd gen", "silver"): "iPod11-Silver.png",
    ("ipod classic", "2nd gen", "black"): "iPod11B-Black.png",
    ("ipod classic", "3rd gen", "silver"): "iPod11-Silver.png",
    ("ipod classic", "3rd gen", "black"): "iPod11B-Black.png",

    # ── iPod Mini 1st Gen ────────────
    ("ipod mini", "1st gen", "silver"): "iPod3-Silver.png",
    ("ipod mini", "1st gen", "blue"): "iPod3-Blue.png",
    ("ipod mini", "1st gen", "gold"): "iPod3-Gold.png",
    ("ipod mini", "1st gen", "green"): "iPod3-Green.png",
    ("ipod mini", "1st gen", "pink"): "iPod3-Pink.png",

    # ── iPod Mini 2nd Gen ───
    ("ipod mini", "2nd gen", "silver"): "iPod3-Silver.png",
    ("ipod mini", "2nd gen", "blue"): "iPod3B-Blue.png",
    ("ipod mini", "2nd gen", "green"): "iPod3B-Green.png",
    ("ipod mini", "2nd gen", "pink"): "iPod3B-Pink.png",

    # ── iPod Nano 1st Gen ──────────────────────────────
    ("ipod nano", "1st gen", "white"): "iPod7-White.png",
    ("ipod nano", "1st gen", "black"): "iPod7-Black.png",

    # ── iPod Nano 2nd Gen ─────
    ("ipod nano", "2nd gen", "silver"): "iPod9-Silver.png",
    ("ipod nano", "2nd gen", "black"): "iPod9-Black.png",
    ("ipod nano", "2nd gen", "blue"): "iPod9-Blue.png",
    ("ipod nano", "2nd gen", "green"): "iPod9-Green.png",
    ("ipod nano", "2nd gen", "pink"): "iPod9-Pink.png",
    ("ipod nano", "2nd gen", "red"): "iPod9-Red.png",

    # ── iPod Nano 3rd Gen ─────
    ("ipod nano", "3rd gen", "silver"): "iPod12-Silver.png",
    ("ipod nano", "3rd gen", "black"): "iPod12-Black.png",
    ("ipod nano", "3rd gen", "blue"): "iPod12-Blue.png",
    ("ipod nano", "3rd gen", "green"): "iPod12-Green.png",
    ("ipod nano", "3rd gen", "pink"): "iPod12-Pink.png",
    ("ipod nano", "3rd gen", "red"): "iPod12-Red.png",

    # ── iPod Nano 4th Gen ─────────────────────────────────
    ("ipod nano", "4th gen", "silver"): "iPod15-Silver.png",
    ("ipod nano", "4th gen", "black"): "iPod15-Black.png",
    ("ipod nano", "4th gen", "blue"): "iPod15-Blue.png",
    ("ipod nano", "4th gen", "green"): "iPod15-Green.png",
    ("ipod nano", "4th gen", "orange"): "iPod15-Orange.png",
    ("ipod nano", "4th gen", "pink"): "iPod15-Pink.png",
    ("ipod nano", "4th gen", "purple"): "iPod15-Purple.png",
    ("ipod nano", "4th gen", "red"): "iPod15-Red.png",
    ("ipod nano", "4th gen", "yellow"): "iPod15-Yellow.png",

    # ── iPod Nano 5th Gen ─────────────────────────────────
    ("ipod nano", "5th gen", "silver"): "iPod16-Silver.png",
    ("ipod nano", "5th gen", "black"): "iPod16-Black.png",
    ("ipod nano", "5th gen", "blue"): "iPod16-Blue.png",
    ("ipod nano", "5th gen", "green"): "iPod16-Green.png",
    ("ipod nano", "5th gen", "orange"): "iPod16-Orange.png",
    ("ipod nano", "5th gen", "pink"): "iPod16-Pink.png",
    ("ipod nano", "5th gen", "purple"): "iPod16-Purple.png",
    ("ipod nano", "5th gen", "red"): "iPod16-Red.png",
    ("ipod nano", "5th gen", "yellow"): "iPod16-Yellow.png",

    # ── iPod Nano 6th Gen ─────────────────────────────────
    ("ipod nano", "6th gen", "silver"): "iPod17-Silver.png",
    ("ipod nano", "6th gen", "graphite"): "iPod17-DarkGray.png",
    ("ipod nano", "6th gen", "blue"): "iPod17-Blue.png",
    ("ipod nano", "6th gen", "green"): "iPod17-Green.png",
    ("ipod nano", "6th gen", "orange"): "iPod17-Orange.png",
    ("ipod nano", "6th gen", "pink"): "iPod17-Pink.png",
    ("ipod nano", "6th gen", "red"): "iPod17-Red.png",

    # ── iPod Nano 7th Gen ─────────────────────────────────────────────
    # Two physical revisions (2012 iPod18, 2015 iPod18A) share colors.
    # COLOR_MAP defaults to iPod18A for shared colors; MODEL_IMAGE below
    # overrides to iPod18 for 2012-era model numbers (MD*/ME*).
    ("ipod nano", "7th gen", "silver"): "iPod18A-Silver.png",
    ("ipod nano", "7th gen", "space gray"): "iPod18A-SpaceGray.png",
    ("ipod nano", "7th gen", "blue"): "iPod18A-Blue.png",
    ("ipod nano", "7th gen", "pink"): "iPod18A-Pink.png",
    ("ipod nano", "7th gen", "red"): "iPod18A-Red.png",
    ("ipod nano", "7th gen", "gold"): "iPod18A-Gold.png",
    # 2012-only colors (not in 2015 refresh) — no ambiguity
    ("ipod nano", "7th gen", "slate"): "iPod18-DarkGray.png",
    ("ipod nano", "7th gen", "green"): "iPod18-Green.png",
    ("ipod nano", "7th gen", "purple"): "iPod18-Purple.png",
    ("ipod nano", "7th gen", "yellow"): "iPod18-Yellow.png",

    # ── iPod Shuffle 1st Gen ───────────────────────
    ("ipod shuffle", "1st gen", "white"): "iPod128.png",

    # ── iPod Shuffle 2nd Gen ──────────────────────────────────────────
    # Three revisions share the same generation: iPod130 (2006/early-2007),
    # iPod130C (Sept 2007), iPod130F (2008).  COLOR_MAP defaults to the
    # earliest image for each color; MODEL_IMAGE overrides to the correct
    # revision when the model number is known.
    ("ipod shuffle", "2nd gen", "silver"): "iPod130-Silver.png",
    ("ipod shuffle", "2nd gen", "blue"): "iPod130-Blue.png",
    ("ipod shuffle", "2nd gen", "green"): "iPod130-Green.png",
    ("ipod shuffle", "2nd gen", "pink"): "iPod130-Pink.png",
    ("ipod shuffle", "2nd gen", "orange"): "iPod130-Orange.png",
    ("ipod shuffle", "2nd gen", "purple"): "iPod130C-Purple.png",
    ("ipod shuffle", "2nd gen", "red"): "iPod130C-Red.png",
    ("ipod shuffle", "2nd gen", "gold"): "iPod130F-Gold.png",

    # ── iPod Shuffle 3rd Gen ───────────────────────────────────
    ("ipod shuffle", "3rd gen", "silver"): "iPod132-Silver.png",
    ("ipod shuffle", "3rd gen", "black"): "iPod132-DarkGray.png",
    ("ipod shuffle", "3rd gen", "blue"): "iPod132-Blue.png",
    ("ipod shuffle", "3rd gen", "green"): "iPod132-Green.png",
    ("ipod shuffle", "3rd gen", "pink"): "iPod132-Pink.png",
    # iPod132B — stainless-steel special edition
    ("ipod shuffle", "3rd gen", "stainless steel"): "iPod132B-Silver.png",

    # ── iPod Shuffle 4th Gen (2010–2017) ───────────────────────────────
    # Three revisions: iPod133 (2010), iPod133B (2012), iPod133D (2015).
    # COLOR_MAP defaults to iPod133D for shared colors; MODEL_IMAGE
    # overrides to the correct revision when the model number is known.
    ("ipod shuffle", "4th gen", "silver"): "iPod133D-Silver.png",
    ("ipod shuffle", "4th gen", "space gray"): "iPod133D-SpaceGray.png",
    ("ipod shuffle", "4th gen", "blue"): "iPod133D-Blue.png",
    ("ipod shuffle", "4th gen", "pink"): "iPod133D-Pink.png",
    ("ipod shuffle", "4th gen", "red"): "iPod133D-Red.png",
    ("ipod shuffle", "4th gen", "gold"): "iPod133D-Gold.png",
    # 2012-only colors (not in 2015 refresh) — no ambiguity
    ("ipod shuffle", "4th gen", "slate"): "iPod133B-DarkGray.png",
    ("ipod shuffle", "4th gen", "green"): "iPod133B-Green.png",
    ("ipod shuffle", "4th gen", "purple"): "iPod133B-Purple.png",
    ("ipod shuffle", "4th gen", "yellow"): "iPod133B-Yellow.png",
    # 2010-only color — no ambiguity
    ("ipod shuffle", "4th gen", "orange"): "iPod133-Orange.png",
}

# ── Model-number → image overrides ─────────────────────────────────────────
#
# When a model number is known, it pins the exact hardware revision.  For
# product lines where multiple color refreshes share the same (family, gen)
# pair — Shuffle 2G, Shuffle 4G, Nano 7G — COLOR_MAP can only pick ONE
# revision as the default.  MODEL_IMAGE provides per-model overrides so
# ``image_for_model()`` returns the correct revision-specific image.
#
# Only entries that DIFFER from ``resolve_image_filename(family, gen, color)``
# are listed here; all other models resolve correctly via COLOR_MAP already.

MODEL_IMAGE: dict[str, str] = {
    # ── iPod Nano 7th Gen (2012 original → iPod18) ─────────────────────
    # COLOR_MAP defaults shared colors to iPod18A (2015).  Override 2012
    # models (MD*/ME*) to iPod18.
    'MD475': 'iPod18-Pink.png',
    'MD477': 'iPod18-Blue.png',
    'MD480': 'iPod18-Silver.png',
    'MD744': 'iPod18-Red.png',
    'ME971': 'iPod18-SpaceGray.png',

    # ── iPod Shuffle 2nd Gen — Sept 2007 Rev A (iPod130C) ─────────────
    # COLOR_MAP defaults Blue/Green to iPod130 (early 2007).
    # 1GB
    'MB227': 'iPod130C-Blue.png',
    'MB228': 'iPod130C-Blue.png',
    'MB229': 'iPod130C-Green.png',
    # 2GB
    'MB520': 'iPod130C-Blue.png',
    'MB522': 'iPod130C-Green.png',

    # ── iPod Shuffle 2nd Gen — 2008 Rev B (iPod130F) ──────────────────
    # COLOR_MAP defaults Pink/Blue/Green to iPod130; Red to iPod130C.
    # 1GB
    'MB811': 'iPod130F-Pink.png',
    'MB813': 'iPod130F-Blue.png',
    'MB815': 'iPod130F-Green.png',
    'MB817': 'iPod130F-Red.png',
    # 2GB
    'MB681': 'iPod130F-Pink.png',
    'MB683': 'iPod130F-Blue.png',
    'MB685': 'iPod130F-Green.png',
    'MB779': 'iPod130F-Red.png',

    # ── iPod Shuffle 4th Gen — 2010 original (iPod133) ────────────────
    # COLOR_MAP defaults shared colors to iPod133D (2015) / iPod133B (2012).
    'MC584': 'iPod133-Silver.png',
    'MC585': 'iPod133-Pink.png',
    'MC750': 'iPod133-Green.png',
    'MC751': 'iPod133-Blue.png',

    # ── iPod Shuffle 4th Gen — Late 2012 Rev A (iPod133B) ─────────────
    # COLOR_MAP defaults shared colors to iPod133D (2015).
    'MD773': 'iPod133B-Pink.png',
    'MD775': 'iPod133B-Blue.png',
    'MD778': 'iPod133B-Silver.png',
    'MD780': 'iPod133B-Red.png',
    'ME949': 'iPod133B-SpaceGray.png',
}


# Family-level fallback — used when color is unknown or generation doesn't
# match.  For color-unknown lookups resolve_image_filename() first tries the
# "silver" or "white" key from COLOR_MAP for the given (family, gen) before
# falling back here.
FAMILY_FALLBACK: dict[str, str] = {
    "ipod": "iPod4-White.png",
    "ipod u2": "iPod4-BlackRed.png",
    "ipod photo": "iPod5-White.png",
    "ipod photo u2": "iPod5-BlackRed.png",
    "ipod video": "iPod6-White.png",
    "ipod video u2": "iPod6-BlackRed.png",
    "ipod classic": "iPod11-Silver.png",
    "ipod mini": "iPod3-Silver.png",
    "ipod nano": "iPod15-Silver.png",
    "ipod shuffle": "iPod133D-Silver.png",
}

# Generic fallback when nothing else matches.
GENERIC_IMAGE = "iPodGeneric.png"

# Preferred default color per family when generation is known but color is
# not — tried in order against COLOR_MAP[(fam, gen, color)].
_DEFAULT_COLOR_PREFERENCE = ("silver", "white")


def resolve_image_filename(
    family: str,
    generation: str,
    color: str = "",
) -> str:
    """Resolve an image filename through a tiered lookup.

    1. Exact (family, generation, color)
    2. Inferred default — try "silver" then "white" for (family, generation)
    3. Family-level fallback
    4. ``iPodGeneric.png``

    Returns:
        Filename (not full path) of the iPod product image.
    """
    fam = family.lower()
    gen = generation.lower()
    col = color.lower().strip()

    # 1. color-specific
    if col:
        filename = COLOR_MAP.get((fam, gen, col))
        if filename:
            return filename

    # 2. Inferred default — pick the most representative color
    for default_col in _DEFAULT_COLOR_PREFERENCE:
        filename = COLOR_MAP.get((fam, gen, default_col))
        if filename:
            return filename

    # 3. Family-level fallback (generation unknown or unrecognised)
    return FAMILY_FALLBACK.get(fam, GENERIC_IMAGE)


def image_for_model(model_number: str) -> str:
    """Return the exact image filename for a known model number.

    When the model number is known, it uniquely identifies the hardware
    revision, so we can pick the correct revision-specific image file
    (e.g., iPod133 vs iPod133B vs iPod133D for Shuffle 4G).

    Lookup priority:
      1. ``MODEL_IMAGE`` — direct override for revision-sensitive models
      2. ``IPOD_MODELS`` → ``resolve_image_filename(family, gen, color)``
      3. ``GENERIC_IMAGE``

    Args:
        model_number: e.g. ``'MC584'``, ``'MD475'``

    Returns:
        Filename (not full path) of the iPod product image.
    """
    # 1. Direct override (handles revision-sensitive models)
    override = MODEL_IMAGE.get(model_number)
    if override:
        return override

    # 2. Standard resolution via IPOD_MODELS color
    info = IPOD_MODELS.get(model_number)
    if info:
        return resolve_image_filename(info[0], info[1], info[3])

    return GENERIC_IMAGE
