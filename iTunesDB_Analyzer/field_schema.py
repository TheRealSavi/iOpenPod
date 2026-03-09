"""Canonical byte-level field schema for every iTunesDB chunk type.

Each entry maps a chunk type to a list of `FieldDef` tuples describing every
*known* byte range the parser handles.  Gaps between consecutive entries —
and between the last entry and the header_length boundary — are the unknown
territory targeted by the analysis pipeline.

Offsets are relative to the chunk start (where the 4-byte tag sits).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class FieldType(Enum):
    """Primitive type stored at a byte range."""
    UINT8 = auto()
    UINT16_LE = auto()
    UINT32_LE = auto()
    INT32_LE = auto()
    UINT64_LE = auto()
    FLOAT32_LE = auto()
    BYTES = auto()       # opaque blob (hash, padding, etc.)
    ASCII4 = auto()      # 4-byte ASCII tag


class FieldStatus(Enum):
    """Confidence level for a field's interpretation."""
    CONFIRMED = auto()   # parser reads + uses this
    UNKNOWN = auto()     # parser reads but labels unk*
    PADDING = auto()     # believed to be padding / reserved
    INFERRED = auto()    # added by the analyzer (hypothesis)


@dataclass(frozen=True, slots=True)
class FieldDef:
    """One contiguous byte range within a chunk header."""
    offset: int                    # relative to chunk start
    size: int                      # bytes
    name: str                      # e.g. "track_id", "unk0x84"
    field_type: FieldType
    status: FieldStatus
    min_header_length: int = 0     # 0 = always present
    description: str = ""
    transform: str = ""            # e.g. "mac_timestamp", "fixed16.16"

    @property
    def end(self) -> int:
        return self.offset + self.size


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

_C = FieldStatus.CONFIRMED
_U = FieldStatus.UNKNOWN
_P = FieldStatus.PADDING

_u8 = FieldType.UINT8
_u16 = FieldType.UINT16_LE
_u32 = FieldType.UINT32_LE
_i32 = FieldType.INT32_LE
_u64 = FieldType.UINT64_LE
_f32 = FieldType.FLOAT32_LE
_raw = FieldType.BYTES
_asc = FieldType.ASCII4


def _f(off: int, sz: int, name: str, ft: FieldType,
       st: FieldStatus = _C, min_hl: int = 0,
       desc: str = "", xform: str = "") -> FieldDef:
    return FieldDef(off, sz, name, ft, st, min_hl, desc, xform)


# ────────────────────────────────────────────────────────────────────
# Generic 12-byte header (all chunks share this)
# ────────────────────────────────────────────────────────────────────

GENERIC_HEADER: list[FieldDef] = [
    _f(0x00, 4, "chunk_type", _asc, desc="4-byte ASCII tag"),
    _f(0x04, 4, "header_length", _u32, desc="bytes to end of header"),
    _f(0x08, 4, "length_or_children", _u32, desc="total_length or child_count"),
]


# ────────────────────────────────────────────────────────────────────
# MHBD — Database Header
# ────────────────────────────────────────────────────────────────────

MHBD_FIELDS: list[FieldDef] = [
    *GENERIC_HEADER,
    _f(0x0C, 4, "compressed", _u32, desc="1=standard, 2=compressed-capable"),
    _f(0x10, 4, "version", _u32, desc="iTunesDB version (0x01..0x75)"),
    _f(0x14, 4, "child_count", _u32, desc="number of MHSD datasets"),
    _f(0x18, 8, "db_id", _u64),
    _f(0x20, 2, "platform", _u16, desc="1=Mac, 2=Windows"),
    _f(0x22, 2, "unk0x22", _u16, _U),
    _f(0x24, 8, "db_id_2", _u64),
    _f(0x2C, 4, "unk0x2c", _u32, _U),
    _f(0x30, 2, "hashing_scheme", _u16, desc="0=NONE,1=HASH58,2=HASH72,4=HASHAB"),
    _f(0x32, 20, "unk0x32", _raw, _U, desc="zeroed during HASH58 computation"),
    _f(0x46, 2, "language", _u16, desc="ISO 639 packed u16"),
    _f(0x48, 8, "db_persistent_id", _u64, desc="links to iTunesPrefs"),
    _f(0x50, 4, "unk0x50", _u32, _U, desc="device-specific"),
    _f(0x54, 4, "unk0x54", _u32, _U, desc="device-specific"),
    _f(0x58, 20, "hash58", _raw, desc="SHA1 hash for HASH58 devices"),
    _f(0x6C, 4, "timezone_offset", _i32, desc="seconds from UTC", xform="signed"),
    _f(0x70, 2, "hash_type_indicator", _u16, desc="0=none, 2=HASH72, 4=HASHAB"),
    _f(0x72, 46, "hash72", _raw, min_hl=0xA0, desc="HASH72 signature"),
    _f(0xA0, 2, "audio_language", _u16, _C, 0xA2),
    _f(0xA2, 2, "subtitle_language", _u16, _C, 0xA4),
    _f(0xA4, 2, "unk0xa4", _u16, _U, 0xA6),
    _f(0xA6, 2, "unk0xa6", _u16, _U, 0xA8),
    _f(0xA8, 2, "cdb_flag", _u16, _U, 0xAA, desc="1=CDB-capable, 0=uncompressed only"),
]


# ────────────────────────────────────────────────────────────────────
# MHSD — Dataset
# ────────────────────────────────────────────────────────────────────

MHSD_FIELDS: list[FieldDef] = [
    *GENERIC_HEADER,
    _f(0x0C, 4, "dataset_type", _u32, desc="1=mhlt, 2=mhlp, 3=podcast, 4=mhla, 5=smart, 8=artist, 9=genius"),
]


# ────────────────────────────────────────────────────────────────────
# MHIT — Track Item (the big one)
# ────────────────────────────────────────────────────────────────────

MHIT_FIELDS: list[FieldDef] = [
    *GENERIC_HEADER,
    # ── Core (always present, min header 0x9C) ──
    _f(0x0C, 4, "child_count", _u32),
    _f(0x10, 4, "track_id", _u32),
    _f(0x14, 4, "visible", _u32),
    _f(0x18, 4, "filetype", _u32, desc="FourCC as u32", xform="fourcc"),
    _f(0x1C, 1, "vbr_flag", _u8),
    _f(0x1D, 1, "mp3_flag", _u8),
    _f(0x1E, 1, "compilation_flag", _u8),
    _f(0x1F, 1, "rating", _u8, desc="stars*20 (0-100)"),
    _f(0x20, 4, "last_modified", _u32, xform="mac_timestamp"),
    _f(0x24, 4, "size", _u32, desc="file size bytes"),
    _f(0x28, 4, "length", _u32, desc="duration ms"),
    _f(0x2C, 4, "track_number", _u32),
    _f(0x30, 4, "total_tracks", _u32),
    _f(0x34, 4, "year", _u32),
    _f(0x38, 4, "bitrate", _u32, desc="kbps"),
    _f(0x3C, 4, "sample_rate_1", _u32, xform="fixed16.16"),
    _f(0x40, 4, "volume", _i32, desc="-255..+255"),
    _f(0x44, 4, "start_time", _u32, desc="ms"),
    _f(0x48, 4, "stop_time", _u32, desc="ms"),
    _f(0x4C, 4, "sound_check", _u32, desc="linear gain*1000"),
    _f(0x50, 4, "play_count_1", _u32),
    _f(0x54, 4, "play_count_2", _u32),
    _f(0x58, 4, "last_played", _u32, xform="mac_timestamp"),
    _f(0x5C, 4, "disc_number", _u32),
    _f(0x60, 4, "total_discs", _u32),
    _f(0x64, 4, "user_id", _u32, desc="iTunes/Audible DRM user ID"),
    _f(0x68, 4, "date_added", _u32, xform="mac_timestamp"),
    _f(0x6C, 4, "bookmark_time", _u32, desc="ms"),
    _f(0x70, 8, "db_id", _u64),
    _f(0x78, 1, "checked_flag", _u8),
    _f(0x79, 1, "app_rating", _u8, desc="stars*20 backup"),
    _f(0x7A, 2, "bpm", _u16),
    _f(0x7C, 2, "artwork_count", _u16),
    _f(0x7E, 2, "audio_format_flag", _u16, desc="0xFFFF=lossy,0=lossless,1=Audible"),
    _f(0x80, 4, "artwork_size", _u32, desc="embedded artwork bytes"),
    _f(0x84, 4, "unk0x84", _u32, _U, desc="libgpod: track->unk132"),
    _f(0x88, 4, "sample_rate_2", _f32, desc="IEEE 754 float Hz"),
    _f(0x8C, 4, "date_released", _u32, xform="mac_timestamp"),
    _f(0x90, 2, "mpeg_audio_type", _u16, desc="codec id"),
    _f(0x92, 1, "explicit_flag", _u8, desc="0=none,1=explicit,2=clean"),
    _f(0x93, 1, "purchased_aac_flag", _u8, desc="1=purchased AAC (M4A), 0=other"),
    _f(0x94, 4, "unk0x94", _u32, _U, desc="DRM-related, 0x01010100 for Store"),
    _f(0x98, 4, "genius_category_id", _u32, _U, desc="Genius Mixes category index, 0=unset"),
    # ── Extended (guarded by header_length) ──
    _f(0x9C, 4, "skip_count", _u32, _C, 0xA0),
    _f(0xA0, 4, "last_skipped", _u32, _C, 0xA4, xform="mac_timestamp"),
    _f(0xA4, 1, "has_artwork", _u8, _C, 0xA5),
    _f(0xA5, 1, "skip_when_shuffling", _u8, _C, 0xA6),
    _f(0xA6, 1, "remember_position", _u8, _C, 0xA7),
    _f(0xA7, 1, "use_podcast_now_playing_flag", _u8, _C, 0xA8),
    _f(0xA8, 8, "db_id_2", _u64, _C, 0xB0),
    _f(0xB0, 1, "lyrics_flag", _u8, _C, 0xB1),
    _f(0xB1, 1, "movie_flag", _u8, _C, 0xB2),
    _f(0xB2, 1, "not_played_flag", _u8, _C, 0xB3),
    _f(0xB3, 1, "unk0xB3", _u8, _U, 0xB4, desc="always 0"),
    _f(0xB4, 4, "unk0xB4", _u32, _U, 0xB8),
    _f(0xB8, 4, "pregap", _u32, _C, 0xBC, desc="gapless pregap"),
    _f(0xBC, 8, "sample_count", _u64, _C, 0xC4),
    _f(0xC4, 4, "unk0xC4", _u32, _U, 0xC8),
    _f(0xC8, 4, "postgap", _u32, _C, 0xCC, desc="gapless postgap"),
    _f(0xCC, 4, "encoder", _u32, _C, 0xD0),
    _f(0xD0, 4, "media_type", _u32, _C, 0xD4, desc="bitmask"),
    _f(0xD4, 4, "season_number", _u32, _C, 0xD8),
    _f(0xD8, 4, "episode_number", _u32, _C, 0xDC),
    _f(0xDC, 4, "date_added_to_itunes", _u32, _C, 0xE0, xform="mac_timestamp"),
    _f(0xE0, 4, "store_track_id", _u32, _C, 0xE4),
    _f(0xE4, 4, "store_encoder_version", _u32, _C, 0xE8),
    _f(0xE8, 4, "store_artist_id", _u32, _C, 0xEC),
    _f(0xEC, 4, "unk0xEC", _u32, _U, 0xF0),
    _f(0xF0, 4, "store_album_id", _u32, _C, 0xF4),
    _f(0xF4, 4, "store_content_flag", _u32, _C, 0xF8),
    _f(0xF8, 4, "gapless_audio_payload_size", _u32, _C, 0xFC),
    _f(0xFC, 4, "unk0xFC", _u32, _U, 0x100),
    _f(0x100, 2, "gapless_track_flag", _u16, _C, 0x102),
    _f(0x102, 2, "gapless_album_flag", _u16, _C, 0x104),
    _f(0x104, 20, "hash_0x104", _raw, _C, 0x118, desc="SHA1, not checked by firmware"),
    _f(0x118, 4, "unk0x118", _u32, _U, 0x11C, desc="iPodLinux: unk40, seen 0xBF"),
    _f(0x11C, 4, "unk0x11C", _u32, _U, 0x120),
    _f(0x120, 4, "album_id", _u32, _C, 0x124),
    _f(0x124, 8, "mhbd_id_ref", _u64, _C, 0x12C),
    _f(0x12C, 4, "size_2", _u32, _C, 0x130, desc="duplicate of size at 0x24"),
    _f(0x130, 4, "unk0x130", _u32, _U, 0x134),
    _f(0x134, 8, "sort_mhod_indicators", _raw, _C, 0x13C, desc="6 sort flags + 2 pad"),
    # GAP: 0x13C..0x160 (~36 bytes unmapped)
    _f(0x160, 4, "artwork_id_ref", _u32, _C, 0x164, desc="links to ArtworkDB mhii"),
    # GAP: 0x164..0x1E0 (~124 bytes unmapped)
    _f(0x1E0, 4, "artist_id_ref", _u32, _C, 0x1E4),
    # GAP: 0x1E4..0x1F4 (16 bytes unmapped)
    _f(0x1F4, 4, "composer_id", _u32, _C, 0x1F8),
]


# ────────────────────────────────────────────────────────────────────
# MHIA — Album Item
# ────────────────────────────────────────────────────────────────────

MHIA_FIELDS: list[FieldDef] = [
    *GENERIC_HEADER,
    _f(0x0C, 4, "child_count", _u32),
    _f(0x10, 4, "album_id", _u32),
    _f(0x14, 8, "sql_id", _u64),
    _f(0x1C, 2, "platform_flag", _u16),
    _f(0x1E, 2, "album_compilation_flag", _u16),
    # Discovered by iOpenPod analyzer: db_id of a representative track in this album
    _f(0x20, 8, "album_track_db_id", _u64, _C, 0x28,
       desc="representative track db_id, only populated by some iTunes versions"),
]


# ────────────────────────────────────────────────────────────────────
# MHII — Artist Item (iTunesDB context, MHSD type 8)
# ────────────────────────────────────────────────────────────────────

MHII_FIELDS: list[FieldDef] = [
    *GENERIC_HEADER,
    _f(0x0C, 4, "child_count", _u32),
    _f(0x10, 4, "artist_id", _u32),
    _f(0x14, 8, "sql_id", _u64),
    _f(0x1C, 4, "platform_flag", _u32),
]


# ────────────────────────────────────────────────────────────────────
# MHIP — Playlist Item
# ────────────────────────────────────────────────────────────────────

MHIP_FIELDS: list[FieldDef] = [
    *GENERIC_HEADER,
    _f(0x0C, 4, "child_count", _u32),
    _f(0x10, 2, "podcast_group_flag", _u16),
    _f(0x12, 2, "unk0x12", _u16, _U),
    _f(0x14, 4, "group_id", _u32),
    _f(0x18, 4, "track_id", _u32, desc="references mhit track_id"),
    _f(0x1C, 4, "timestamp", _u32, xform="mac_timestamp"),
    _f(0x20, 4, "group_id_ref", _u32),
    # Discovered by iOpenPod analyzer: track's db_id stored in MHIP
    _f(0x2C, 8, "track_persistent_id", _u64, _C, 0x34,
       desc="track db_id — 100% match across all tested databases"),
    # Per-track persistent ID, consistent across playlists, absent in older iTunes
    _f(0x3C, 8, "mhip_persistent_id", _u64, _C, 0x44,
       desc="per-track persistent ID, same value in all playlists"),
]


# ────────────────────────────────────────────────────────────────────
# MHYP — Playlist
# ────────────────────────────────────────────────────────────────────

MHYP_FIELDS: list[FieldDef] = [
    *GENERIC_HEADER,
    _f(0x0C, 4, "mhod_child_count", _u32),
    _f(0x10, 4, "mhip_child_count", _u32),
    _f(0x14, 1, "master_flag", _u8),
    _f(0x15, 1, "flag1", _u8, _U),
    _f(0x16, 1, "flag2", _u8, _U),
    _f(0x17, 1, "flag3", _u8, _U),
    _f(0x18, 4, "timestamp", _u32, xform="mac_timestamp"),
    _f(0x1C, 8, "playlist_id", _u64),
    _f(0x24, 4, "unk0x24", _u32, _U, desc="always 0"),
    _f(0x28, 2, "string_mhod_child_count", _u16),
    _f(0x2A, 2, "podcast_flag", _u16),
    _f(0x2C, 4, "sort_order", _u32),
    # GAP: 0x30..0x3C (12 bytes unmapped in basic header)
    _f(0x3C, 8, "db_id_2", _u64, _C, 0x44),
    _f(0x44, 8, "playlist_id_2", _u64, _C, 0x4C),
    _f(0x50, 2, "mhsd5_type", _u16, _C, 0x52),
    # GAP: 0x4C..0x58 (12 bytes unmapped)
    _f(0x58, 4, "timestamp_2", _u32, _C, 0x5C, xform="mac_timestamp"),
]


# ────────────────────────────────────────────────────────────────────
# MHOD — Data Object header (body varies by type, not modeled here)
# ────────────────────────────────────────────────────────────────────

MHOD_HEADER_FIELDS: list[FieldDef] = [
    *GENERIC_HEADER,
    _f(0x0C, 4, "mhod_type", _u32, desc="body layout selector"),
    _f(0x10, 4, "unk0x10", _u32, _U),
    _f(0x14, 4, "unk0x14", _u32, _U),
]


# ────────────────────────────────────────────────────────────────────
# Container lists (mhlt, mhla, mhli, mhlp) — only the generic header
# ────────────────────────────────────────────────────────────────────

MHLT_FIELDS = list(GENERIC_HEADER)
MHLA_FIELDS = list(GENERIC_HEADER)
MHLI_FIELDS = list(GENERIC_HEADER)
MHLP_FIELDS = list(GENERIC_HEADER)


# ────────────────────────────────────────────────────────────────────
# Lookup table: chunk_type_tag → field list
# ────────────────────────────────────────────────────────────────────

SCHEMA: dict[str, list[FieldDef]] = {
    "mhbd": MHBD_FIELDS,
    "mhsd": MHSD_FIELDS,
    "mhlt": MHLT_FIELDS,
    "mhla": MHLA_FIELDS,
    "mhli": MHLI_FIELDS,
    "mhlp": MHLP_FIELDS,
    "mhit": MHIT_FIELDS,
    "mhia": MHIA_FIELDS,
    "mhii": MHII_FIELDS,
    "mhip": MHIP_FIELDS,
    "mhyp": MHYP_FIELDS,
    "mhod": MHOD_HEADER_FIELDS,
}


def fields_for_chunk(chunk_type: str) -> list[FieldDef]:
    """Return the known field list for a chunk type tag, or the generic header."""
    return SCHEMA.get(chunk_type, GENERIC_HEADER)


def covered_ranges(
    chunk_type: str,
    header_length: int,
) -> list[tuple[int, int, str]]:
    """Return sorted list of (start, end, field_name) byte ranges covered by the schema.

    Only includes fields whose ``min_header_length`` threshold is met.
    """
    out: list[tuple[int, int, str]] = []
    for f in fields_for_chunk(chunk_type):
        if f.min_header_length and header_length < f.min_header_length:
            continue
        if f.offset < header_length:
            out.append((f.offset, f.end, f.name))
    out.sort()
    return out


def unknown_ranges(
    chunk_type: str,
    header_length: int,
) -> list[tuple[int, int]]:
    """Return byte ranges within the header NOT covered by any known field.

    These are the primary targets for analysis.
    """
    covered = covered_ranges(chunk_type, header_length)
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for start, end, _ in covered:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < header_length:
        gaps.append((cursor, header_length))
    return gaps
