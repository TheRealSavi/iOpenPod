"""Device capabilities — per-generation feature map backed by canonical artwork formats.

Sources:
  - libgpod ``itdb_device.c`` — itdb_device_supports_*() functions,
    ipod_info_table, artwork format tables
  - libgpod ``itdb_itunesdb.c`` — iTunesSD writer, mhbd version handling
  - Empirical: iPod Classic 6.5G, Nano 3G confirmed

This table captures every capability dimension that affects database
writing, artwork generation, or sync behaviour.  It is the single
authority for "what does this device support?" questions.
"""

from dataclasses import dataclass, replace

from .artwork_presets import (
    ARTWORK_FORMATS_BY_ID,
    CLASSIC_COVER_ART_FORMATS,
    NANO_7G_COVER_ART_FORMATS,
    ArtworkFormat,
)
from .checksum import ChecksumType
from .models import canonicalize_model_identity

_MIB = 1024 * 1024
_DEFAULT_MAX_DATABASE_BYTES = 32 * _MIB
_LARGE_MAX_DATABASE_BYTES = 64 * _MIB
_HIGH_MEMORY_VIDEO_MODELS = frozenset({"MA003", "MA147", "MA448", "MA450"})


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
    iPod 5.5G (Late 2006)."""

    # ── Artwork ────────────────────────────────────────────────────────
    supports_artwork: bool = True
    """Device has an ArtworkDB and .ithmb files for album art."""
    supports_photo: bool = False
    """Device has additional photo artwork formats (for photo viewer)."""
    photo_formats: tuple[ArtworkFormat, ...] = ()
    """Photo/slideshow ithmb formats used by the Photos database pipeline."""
    supports_chapter_image: bool = False
    """Device has chapter image artwork formats (for enhanced podcasts)."""
    supports_sparse_artwork: bool = False
    """Artwork can be written in sparse mode (Nano 3G+, Classic, Touch)."""
    supports_alac: bool = True
    """Device supports Apple Lossless (ALAC) audio playback.
    False for iPod 1G–3G and Mini 1G (pre-firmware-update era hardware that
    received ALAC support only from 4th Gen photo/color / Mini 2G onwards)."""
    cover_art_formats: tuple[ArtworkFormat, ...] = ()
    """Supported cover-art thumbnail sizes.  Empty means no artwork."""

    # ── Storage layout ─────────────────────────────────────────────────
    music_dirs: int = 20
    """Number of ``Fxx`` directories under ``iPod_Control/Music/``.
    Varies 0–50 depending on model and storage capacity."""
    max_database_bytes: int = _DEFAULT_MAX_DATABASE_BYTES
    """Maximum supported on-device music database size.

    Click-wheel firmware loads the database into device RAM. Treat this as
    the practical ceiling for iTunesDB/iTunesCDB footprint checks.
    """

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
    max_video_fps: int = 30
    """Maximum frame rate for H.264 decode (fps).  All video-capable iPods
    support 30 fps; PAL-resolution Nano 7G content is typically 25 fps but
    30 fps playback is still supported."""
    max_video_bitrate: int = 0
    """Hard bitrate ceiling for H.264 decode (kbps).  0 = no explicit cap
    (quality-controlled by CRF only).  Non-zero values enforce a -maxrate
    flag in ffmpeg.
    Nano 3G/4G use Baseline Profile Level 1.3, capped at 768 kbps by spec."""
    h264_level: str = "3.0"
    """H.264 Baseline Profile level to target when encoding video.
    Most iPods support Level 3.0.  iPod Classic supports 3.1.
    Nano 3G/4G are limited to Level 1.3 by their hardware decoder."""


# ──────────────────────────────────────────────────────────────────────────
# The master capabilities table
# ──────────────────────────────────────────────────────────────────────────

_FAMILY_GEN_CAPABILITIES: dict[tuple[str, str], DeviceCapabilities] = {

    # ── iPod 1G–3G: earliest models, no podcast, no gapless ───────────
    ("iPod", "1st Gen"): DeviceCapabilities(
        supports_podcast=False,
        supports_artwork=False,
        supports_alac=True,
        has_screen=True,
        music_dirs=20,
        db_version=0x13,
    ),
    ("iPod", "2nd Gen"): DeviceCapabilities(
        supports_podcast=False,
        supports_artwork=False,
        supports_alac=True,
        has_screen=True,
        music_dirs=20,
        db_version=0x13,
    ),
    ("iPod", "3rd Gen"): DeviceCapabilities(
        supports_podcast=False,
        supports_artwork=False,
        supports_alac=True,
        has_screen=True,
        music_dirs=20,
        db_version=0x13,
    ),

    # ── iPod 4G mono (Click Wheel): first with podcast support ────────
    ("iPod", "4th Gen (mono)"): DeviceCapabilities(
        supports_artwork=False,
        music_dirs=20,
        db_version=0x13,
    ),

    # ── iPod 4G photo/color (Color Display) ───────────────────────────
    ("iPod", "4th Gen (photo)"): DeviceCapabilities(
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1009],
            ARTWORK_FORMATS_BY_ID[1013],
            ARTWORK_FORMATS_BY_ID[1015],
            ARTWORK_FORMATS_BY_ID[1019],
        ),
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1017],
            ARTWORK_FORMATS_BY_ID[1016],
        ),
        music_dirs=20,
        db_version=0x13,
    ),
    ("iPod", "4th Gen (color)"): DeviceCapabilities(
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1009],
            ARTWORK_FORMATS_BY_ID[1013],
            ARTWORK_FORMATS_BY_ID[1015],
            ARTWORK_FORMATS_BY_ID[1019],
        ),
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1017],
            ARTWORK_FORMATS_BY_ID[1016],
        ),
        music_dirs=20,
        db_version=0x13,
    ),

    # ── iPod 5th Gen ──────────────────────────────────────────────────
    ("iPod", "5th Gen"): DeviceCapabilities(
        supports_video=True,
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1036],
            ARTWORK_FORMATS_BY_ID[1024],
            ARTWORK_FORMATS_BY_ID[1015],
            ARTWORK_FORMATS_BY_ID[1019],
        ),
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1028],
            ARTWORK_FORMATS_BY_ID[1029],
        ),
        music_dirs=20,
        db_version=0x19,
        max_video_width=640,
        max_video_height=480,
    ),

    # ── iPod 5.5th Gen — first with gapless playback ──────────────────
    ("iPod", "5.5th Gen"): DeviceCapabilities(
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1036],
            ARTWORK_FORMATS_BY_ID[1024],
            ARTWORK_FORMATS_BY_ID[1015],
            ARTWORK_FORMATS_BY_ID[1019],
        ),
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1028],
            ARTWORK_FORMATS_BY_ID[1029],
        ),
        music_dirs=20,
        db_version=0x19,
        max_video_width=640,
        max_video_height=480,
    ),

    # ── iPod Classic (all gens): HASH58, gapless, video ───────────────
    ("iPod Classic", "6th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH58,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1067],
            ARTWORK_FORMATS_BY_ID[1024],
            ARTWORK_FORMATS_BY_ID[1066],
        ),
        supports_chapter_image=True,
        supports_sparse_artwork=True,
        cover_art_formats=CLASSIC_COVER_ART_FORMATS,
        music_dirs=50,
        max_database_bytes=_LARGE_MAX_DATABASE_BYTES,
        db_version=0x30,
        max_video_width=640,
        max_video_height=480,
    ),
    ("iPod Classic", "6.5th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH58,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1067],
            ARTWORK_FORMATS_BY_ID[1024],
            ARTWORK_FORMATS_BY_ID[1066],
        ),
        supports_chapter_image=True,
        supports_sparse_artwork=True,
        cover_art_formats=CLASSIC_COVER_ART_FORMATS,
        music_dirs=50,
        max_database_bytes=_LARGE_MAX_DATABASE_BYTES,
        db_version=0x30,
        max_video_width=640,
        max_video_height=480,
    ),
    ("iPod Classic", "7th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH58,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1067],
            ARTWORK_FORMATS_BY_ID[1024],
            ARTWORK_FORMATS_BY_ID[1066],
        ),
        supports_chapter_image=True,
        supports_sparse_artwork=True,
        cover_art_formats=CLASSIC_COVER_ART_FORMATS,
        music_dirs=50,
        max_database_bytes=_LARGE_MAX_DATABASE_BYTES,
        db_version=0x30,
        max_video_width=640,
        max_video_height=480,
    ),

    # ── iPod Mini ─────────────────────────────────────────────────────
    ("iPod Mini", "1st Gen"): DeviceCapabilities(
        supports_artwork=False,
        supports_alac=True,
        music_dirs=6,
        db_version=0x13,
    ),
    ("iPod Mini", "2nd Gen"): DeviceCapabilities(
        supports_artwork=False,
        music_dirs=6,
        db_version=0x13,
    ),

    # ── iPod Nano 1G/2G ──────────────────────────────────────────────
    ("iPod Nano", "1st Gen"): DeviceCapabilities(
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1032],
            ARTWORK_FORMATS_BY_ID[1023],
        ),
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1031],
            ARTWORK_FORMATS_BY_ID[1027],
        ),
        music_dirs=14,
        db_version=0x13,
    ),
    ("iPod Nano", "2nd Gen"): DeviceCapabilities(
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1032],
            ARTWORK_FORMATS_BY_ID[1023],
        ),
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1031],
            ARTWORK_FORMATS_BY_ID[1027],
        ),
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
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1067],
            ARTWORK_FORMATS_BY_ID[1024],
            ARTWORK_FORMATS_BY_ID[1066],
        ),
        supports_sparse_artwork=True,
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1061],
            ARTWORK_FORMATS_BY_ID[1055],
            ARTWORK_FORMATS_BY_ID[1068],
            ARTWORK_FORMATS_BY_ID[1060],
        ),
        music_dirs=20,
        db_version=0x30,
        max_video_width=320,
        max_video_height=240,
        max_video_bitrate=768,
        h264_level="1.3",
    ),

    # ── iPod Nano 4G: HASH58 ─────────────────────────────────────────
    ("iPod Nano", "4th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH58,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1024],
            ARTWORK_FORMATS_BY_ID[1066],
            ARTWORK_FORMATS_BY_ID[1079],
            ARTWORK_FORMATS_BY_ID[1083],
        ),
        supports_chapter_image=True,
        supports_sparse_artwork=True,
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1055],
            ARTWORK_FORMATS_BY_ID[1068],
            ARTWORK_FORMATS_BY_ID[1071],
            ARTWORK_FORMATS_BY_ID[1074],
            ARTWORK_FORMATS_BY_ID[1078],
            ARTWORK_FORMATS_BY_ID[1084],
        ),
        music_dirs=20,
        db_version=0x30,
        max_video_width=480,
        max_video_height=320,
        max_video_bitrate=768,
        h264_level="1.3",
    ),

    # ── iPod Nano 5G: HASH72, compressed DB + SQLite ─────────────────
    ("iPod Nano", "5th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASH72,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1087],
            ARTWORK_FORMATS_BY_ID[1079],
            ARTWORK_FORMATS_BY_ID[1066],
        ),
        supports_sparse_artwork=True,
        supports_compressed_db=True,
        uses_sqlite_db=True,
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1056],
            ARTWORK_FORMATS_BY_ID[1078],
            ARTWORK_FORMATS_BY_ID[1073],
            ARTWORK_FORMATS_BY_ID[1074],
        ),
        music_dirs=14,
        max_database_bytes=_LARGE_MAX_DATABASE_BYTES,
        db_version=0x30,
        max_video_width=640,
        max_video_height=480,
    ),

    # ── iPod Nano 6G: HASHAB, no video ───────────────────────────────
    ("iPod Nano", "6th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASHAB,
        supports_video=False,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1092],
            ARTWORK_FORMATS_BY_ID[1093],
        ),
        supports_sparse_artwork=True,
        supports_compressed_db=True,
        uses_sqlite_db=True,
        cover_art_formats=(
            ARTWORK_FORMATS_BY_ID[1073],
            ARTWORK_FORMATS_BY_ID[1085],
            ARTWORK_FORMATS_BY_ID[1089],
            ARTWORK_FORMATS_BY_ID[1074],
        ),
        music_dirs=20,
        max_database_bytes=_LARGE_MAX_DATABASE_BYTES,
        db_version=0x30,
    ),

    # ── iPod Nano 7G: HASHAB, video returns ──────────────────────────
    ("iPod Nano", "7th Gen"): DeviceCapabilities(
        checksum=ChecksumType.HASHAB,
        supports_video=True,
        supports_gapless=True,
        supports_artwork=True,
        supports_photo=True,
        photo_formats=(
            ARTWORK_FORMATS_BY_ID[1007],
            ARTWORK_FORMATS_BY_ID[1005],
        ),
        supports_sparse_artwork=True,
        supports_compressed_db=True,
        uses_sqlite_db=True,
        cover_art_formats=NANO_7G_COVER_ART_FORMATS,
        music_dirs=20,
        max_database_bytes=_LARGE_MAX_DATABASE_BYTES,
        db_version=0x30,
        max_video_width=720,
        max_video_height=576,
    ),

    # ── iPod Shuffle 1G ──────────────────────────────────────────────
    ("iPod Shuffle", "1st Gen"): DeviceCapabilities(
        is_shuffle=True,
        shadow_db_version=1,
        supports_podcast=True,
        supports_artwork=False,
        has_screen=False,
        music_dirs=3,
        db_version=0x0c,
    ),

    # ── iPod Shuffle 2G ──────────────────────────────────────────────
    ("iPod Shuffle", "2nd Gen"): DeviceCapabilities(
        is_shuffle=True,
        shadow_db_version=1,
        supports_podcast=True,
        supports_artwork=False,
        has_screen=False,
        music_dirs=3,
        db_version=0x13,
    ),

    # ── iPod Shuffle 3G ──────────────────────────────────────────────
    ("iPod Shuffle", "3rd Gen"): DeviceCapabilities(
        is_shuffle=True,
        shadow_db_version=2,
        supports_podcast=True,
        supports_artwork=False,
        has_screen=False,
        music_dirs=3,
        db_version=0x19,
    ),

    # ── iPod Shuffle 4G ──────────────────────────────────────────────
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


def _capacity_gb(capacity: str | None) -> int:
    parts = "".join(
        char if char.isdigit() else " "
        for char in str(capacity or "")
    ).split()
    return int(parts[0]) if parts else 0


def _with_capacity_specific_database_limit(
    family: str,
    generation: str,
    caps: DeviceCapabilities,
    *,
    capacity: str | None,
    model_number: str | None,
) -> DeviceCapabilities:
    if family != "iPod":
        return caps
    if generation not in {"5th Gen", "5.5th Gen"}:
        return caps

    normalized_model = str(model_number or "").strip().upper()
    if (
        _capacity_gb(capacity) >= 60
        or normalized_model in _HIGH_MEMORY_VIDEO_MODELS
    ):
        return replace(caps, max_database_bytes=_LARGE_MAX_DATABASE_BYTES)
    return caps


def capabilities_for_family_gen(
    family: str,
    generation: str,
    *,
    capacity: str | None = None,
    model_number: str | None = None,
) -> DeviceCapabilities | None:
    """Return the device capabilities for a (family, generation) pair.

    If the exact pair is not found but *generation* is empty/unknown,
    checks whether all known generations of *family* share identical
    capabilities and returns those.

    Returns ``None`` if the pair is not in the lookup table and the
    family-level fallback is ambiguous.
    """
    family, generation, _color = canonicalize_model_identity(
        family,
        generation,
        capacity=capacity or "",
        model_number=model_number,
    )

    caps = _FAMILY_GEN_CAPABILITIES.get((family, generation))
    if caps is not None:
        return _with_capacity_specific_database_limit(
            family,
            generation,
            caps,
            capacity=capacity,
            model_number=model_number,
        )

    if family and not generation:
        family_caps = [
            c for (f, _g), c in _FAMILY_GEN_CAPABILITIES.items()
            if f == family
        ]
        if family_caps and all(c == family_caps[0] for c in family_caps):
            return _with_capacity_specific_database_limit(
                family,
                generation,
                family_caps[0],
                capacity=capacity,
                model_number=model_number,
            )

    return None


def cover_art_formats_for_family_gen(
    family: str,
    generation: str,
    *,
    capacity: str | None = None,
    model_number: str | None = None,
) -> tuple[ArtworkFormat, ...]:
    """Return cover-art formats for a family/generation pair.

    This is intentionally narrower than ``capabilities_for_family_gen``. Some
    families have generations with different playback capabilities but the same
    ArtworkDB cover formats, so a full capability fallback would be ambiguous
    while artwork generation is still safe.
    """
    family, generation, _color = canonicalize_model_identity(
        family,
        generation,
        capacity=capacity or "",
        model_number=model_number,
    )

    caps = _FAMILY_GEN_CAPABILITIES.get((family, generation))
    if caps is not None:
        return caps.cover_art_formats if caps.supports_artwork else ()

    if family and not generation:
        family_formats = [
            c.cover_art_formats if c.supports_artwork else ()
            for (f, _g), c in _FAMILY_GEN_CAPABILITIES.items()
            if f == family
        ]
        if family_formats and all(formats == family_formats[0] for formats in family_formats):
            return family_formats[0]

    return ()


def checksum_type_for_family_gen(
    family: str,
    generation: str,
) -> ChecksumType | None:
    """Return the checksum type for a (family, generation) pair.

    Derives the answer from ``_FAMILY_GEN_CAPABILITIES``.  If the exact
    (family, generation) pair is not found but *generation* is empty/unknown,
    checks whether all known generations of *family* share the same checksum
    type and returns it.

    Returns ``None`` if the pair is not in the lookup table and the family-
    level fallback is ambiguous.
    """
    family, generation, _color = canonicalize_model_identity(family, generation)

    caps = _FAMILY_GEN_CAPABILITIES.get((family, generation))
    if caps is not None:
        return caps.checksum

    if family and not generation:
        family_checksums = {
            c.checksum
            for (f, _g), c in _FAMILY_GEN_CAPABILITIES.items()
            if f == family
        }
        if len(family_checksums) == 1:
            return family_checksums.pop()

    return None
