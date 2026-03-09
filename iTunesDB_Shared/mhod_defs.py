"""MHOD (Data Object) field definitions and helpers.

Contains the :class:`FieldDef` list for the 24-byte common MHOD header,
plus type classification sets, string sub-header accessors, and
SPL / SLst / MHOD-52 / MHOD-53 / MHOD-100 / MHOD-102 parsing helpers.

The body-level layouts vary widely by MHOD type and do NOT fit the
simple ``FieldDef`` pattern, so they remain as hand-written helpers here.
"""

import struct

from .field_base import FieldDef, _u32

_S = "mhod"

MHOD_HEADER_SIZE: int = 24  # common header (body varies by type)

# ── String MHOD sub-header layout ──────────────────────────
MHOD_STRING_SUBHEADER_OFFSET = 0x18   # sub-header start (relative to chunk start)
MHOD_STRING_SUBHEADER_SIZE = 16       # encoding(4) + length(4) + unk0x20(4) + unk0x24(4)
MHOD_STRING_DATA_OFFSET = 0x28        # string data start (header + sub-header)

# ── SPLPref body (MHOD type 50) ───────────────────────────
SPLPREF_BODY_SIZE = 132

# ── SLst rule data (MHOD type 51) non-string body size ────
SPL_RULE_DATA_SIZE = 0x44  # 68 bytes

# ── MHOD type 52/53 body layout sizes ─────────────────────
MHOD52_BODY_HEADER_SIZE = 48  # sort_type(4) + count(4) + padding(40)
MHOD53_BODY_HEADER_SIZE = 16  # sort_type(4) + count(4) + padding(8)
MHOD53_ENTRY_SIZE = 12        # letter(2) + pad(2) + start(4) + count(4)

# ── MHOD type 100 body layout ─────────────────────────────
MHOD100_POSITION_BODY_SIZE = 20  # position(4) + padding(16)

# ── MHOD 52/53 sort type constants (from libgpod MHOD52_SORTTYPE) ──
SORT_TITLE = 0x03
SORT_ALBUM = 0x04
SORT_ARTIST = 0x05
SORT_GENRE = 0x07
SORT_COMPOSER = 0x12
SORT_SHOW = 0x1D
SORT_SEASON = 0x1E
SORT_EPISODE = 0x1F
SORT_ALBUM_ARTIST = 0x23

# ── Chapter Data atom constants (MHOD type 17, all big-endian) ──
# The chapter data body starts with 12 bytes of unknown data
# (unk024, unk028, unk032 per libgpod), followed by a "sean" atom tree.
CHAPTER_PREAMBLE_SIZE = 12  # 3 × u32 LE before the atom tree
SEAN_ATOM = b'sean'
CHAP_ATOM = b'chap'
NAME_ATOM = b'name'
HEDR_ATOM = b'hedr'
HEDR_SIZE = 28  # hedr atom is always 28 bytes

MHOD_FIELDS: list[FieldDef] = [
    _u32("mhod_type", 0x0C, section_type=_S, required=True),
    _u32("unk0x10", 0x10, section_type=_S),
    _u32("unk0x14", 0x14, section_type=_S),
]


# ============================================================
# Type Classification Sets
# ============================================================

# String MHOD types that use the standard sub-header at offset 0x18.
# Types 1-14, 18-31, 33-44 are track/item string metadata.
# Types 200-204 are album item strings.
#
# EXCLUDED from this set (handled separately):
#   15-16: Podcast URLs — UTF-8 string with NO sub-header
#   17:    Chapter data — big-endian atom blob
#   32:    Video track data — binary, not a string
STRING_MHOD_TYPES = (
    set(range(1, 15))      # 1..14
    | set(range(18, 32))   # 18..31
    | set(range(33, 45))   # 33..44
    | set(range(200, 205))  # 200..204
    | {300}                # artist item name (MHSD type 8)
)

# Podcast URL types — UTF-8/ASCII string directly at body start, no sub-header.
PODCAST_URL_MHOD_TYPES = {15, 16}

# Chapter data MHOD type — big-endian atom tree (sean/chap/name/hedr).
CHAPTER_DATA_MHOD_TYPES = {17}

# Binary / opaque MHOD types — stored as raw hex for round-tripping.
BINARY_BLOB_MHOD_TYPES = {32}

# Non-string MHOD types with dedicated binary formats.
NON_STRING_MHOD_TYPES = {50, 51, 52, 53, 100, 102}


# ============================================================
# Common MHOD Header (24 bytes — always 0x18)
# ============================================================
# The 3 common header fields (type, unk0x10, unk0x14) are defined in
# MHOD_FIELDS above and read via read_fields().  The per-type body
# helpers below still use struct directly since they don't fit FieldDef.


def write_mhod_header(mhod_type: int, total_length: int,
                      unk0x10: int = 0, unk0x14: int = 0) -> bytes:
    """Build the 24-byte MHOD common header.

    This is the shared pattern used by every MHOD writer — string,
    SPL, index, position, etc.

    Args:
        mhod_type: MHOD type ID (e.g. 1, 50, 51, 52, 53, 100, 102).
        total_length: Total length of the complete MHOD chunk
            (header + body).
        unk0x10: Unknown field at offset 0x10 (preserved from parser).
        unk0x14: Unknown field at offset 0x14 (preserved from parser).

    Returns:
        24-byte packed header.
    """
    return struct.pack(
        '<4sIIIII',
        b'mhod',
        MHOD_HEADER_SIZE,
        total_length,
        mhod_type,
        unk0x10,
        unk0x14,
    )


# ============================================================
# String MHOD Sub-Header (starts at 0x18, 16 bytes)
# ============================================================
# Present on STRING_MHOD_TYPES only. NOT present on podcast URLs (15/16).
# All functions take offset = start of the MHOD chunk.
#
#   +0x18: encoding (4 bytes) — 1=UTF-16LE, 2=UTF-8
#   +0x1C: string_length (4 bytes) — byte count of string data
#   +0x20: unk0x20 (4 bytes)
#   +0x24: unk0x24 (4 bytes)
#   +0x28: string data begins (string_length bytes)

def mhod_string_encoding(data, offset) -> int:
    """Position/encoding indicator at 0x18.
    1 (or 0) = UTF-16LE (standard iPod, little-endian strings).
    2 = UTF-8 (mobile-phone iTunesDBs, inversed endian).
    libgpod checks this same field to decide encoding."""
    return struct.unpack("<I", data[offset + 0x18:offset + 0x1C])[0]


def mhod_string_length(data, offset) -> int:
    """Byte length of string data at 0x1C."""
    return struct.unpack("<I", data[offset + 0x1C:offset + 0x20])[0]


def mhod_string_unk0x20(data, offset) -> int:
    return struct.unpack("<I", data[offset + 0x20:offset + 0x24])[0]


def mhod_string_unk0x24(data, offset) -> int:
    return struct.unpack("<I", data[offset + 0x24:offset + 0x28])[0]


# ============================================================
# SPLPref — Smart Playlist Preferences (MHOD type 50)
# ============================================================
# All functions take body_offset = start of SPLPref data (MHOD chunk + header_length).
#
# Based on libgpod's SPLPref struct (itdb_spl.c) and the iPodLinux wiki.
#
#   +0x00: liveUpdate (1 byte) — 1 = auto-update when library changes
#   +0x01: checkRules (1 byte) — 1 = limit by rules (match checked items)
#   +0x02: checkLimits (1 byte) — 1 = limit by size/count/time
#   +0x03: limitType (1 byte) — what the limit applies to (see SPL_LIMIT_TYPE_MAP)
#   +0x04: limitSort (1 byte) — how to choose items when limited (see SPL_LIMIT_SORT_MAP)
#   +0x05: pad (3 bytes)
#   +0x08: limitValue (4 bytes LE) — the limit value
#   +0x0C: matchCheckedOnly (1 byte) — 1 = only match checked items
#   +0x0D: reverseSort (1 byte) — if set, limitsort |= 0x80000000

def mhod_spl_live_update(data, body_offset) -> int:
    return data[body_offset]


def mhod_spl_check_rules(data, body_offset) -> int:
    return data[body_offset + 1]


def mhod_spl_check_limits(data, body_offset) -> int:
    return data[body_offset + 2]


def mhod_spl_limit_type(data, body_offset) -> int:
    return data[body_offset + 3]


def mhod_spl_limit_sort_raw(data, body_offset) -> int:
    """Raw limit sort byte at +0x04 (before reverse flag is applied)."""
    return data[body_offset + 4]


def mhod_spl_limit_value(data, body_offset) -> int:
    return struct.unpack("<I", data[body_offset + 8:body_offset + 12])[0]


def mhod_spl_match_checked_only(data, body_offset) -> int:
    return data[body_offset + 12]


def mhod_spl_reverse_sort(data, body_offset) -> int:
    """Reverse flag at +0x0D. If set, limitsort |= 0x80000000."""
    return data[body_offset + 13]


# Limit type names (from libgpod ItdbLimitType)
SPL_LIMIT_TYPE_MAP = {
    0x01: "minutes",
    0x02: "MB",
    0x03: "songs",
    0x04: "hours",
    0x05: "GB",
}

# Limit sort names (from libgpod ItdbLimitSort).
# The 0x80000000 bit is the "reverse" flag, stored separately at SPLPref +13.
SPL_LIMIT_SORT_MAP = {
    0x02: "random",
    0x03: "song_name",
    0x04: "album",
    0x05: "artist",
    0x07: "genre",
    0x10: "most_recently_added",
    0x80000010: "least_recently_added",
    0x14: "most_often_played",
    0x80000014: "least_often_played",
    0x15: "most_recently_played",
    0x80000015: "least_recently_played",
    0x17: "highest_rating",
    0x80000017: "lowest_rating",
}


# ============================================================
# SLst — Smart Playlist Rules (MHOD type 51)
# ============================================================
# CRITICAL: The SLst blob is the ONLY part of the iTunesDB that uses
# big-endian encoding. All multi-byte integers within SLst use big-endian.
#
# SLst header (136 bytes):
#   +0x00: 'SLst' magic (4 bytes)
#   +0x04: unk004 (4 bytes BE) — usually 0
#   +0x08: rule_count (4 bytes BE)
#   +0x0C: conjunction (4 bytes BE) — 0=AND, 1=OR
#   +0x10: padding (120 bytes)
#
# All SLst header functions take body_offset = start of SLst data.

SLST_HEADER_SIZE = 136


def mhod_slst_magic(data, body_offset) -> bytes:
    return data[body_offset:body_offset + 4]


def mhod_slst_unk004(data, body_offset) -> int:
    return struct.unpack(">I", data[body_offset + 4:body_offset + 8])[0]


def mhod_slst_rule_count(data, body_offset) -> int:
    return struct.unpack(">I", data[body_offset + 8:body_offset + 12])[0]


def mhod_slst_conjunction(data, body_offset) -> int:
    """0=AND (match all), 1=OR (match any)."""
    return struct.unpack(">I", data[body_offset + 12:body_offset + 16])[0]


# SPL Rule header fields.
# Each rule starts at a variable offset within the SLst body.
# Functions take rule_offset = start of the individual rule.
#
# Rule layout:
#   +0x00: field (4 bytes BE) — what field to match (see SPL_FIELD_MAP)
#   +0x04: action (4 bytes BE) — comparison operator (see SPL_ACTION_MAP)
#   +0x08: padding (44 bytes)
#   +0x34: data_length (4 bytes BE) — byte length of following data
#   +0x38: data (data_length bytes)
#
# Total rule size = 56 + data_length.

SPL_RULE_HEADER_SIZE = 56


def mhod_spl_rule_field(data, rule_offset) -> int:
    return struct.unpack(">I", data[rule_offset:rule_offset + 4])[0]


def mhod_spl_rule_action(data, rule_offset) -> int:
    return struct.unpack(">I", data[rule_offset + 4:rule_offset + 8])[0]


def mhod_spl_rule_data_length(data, rule_offset) -> int:
    return struct.unpack(">I", data[rule_offset + 0x34:rule_offset + 0x38])[0]


# SPL Rule non-string data fields (0x44 = 68 bytes).
# Functions take data_offset = rule_offset + 0x38.
#
#   +0x00: fromValue  (8 bytes BE, guint64)
#   +0x08: fromDate   (8 bytes BE, gint64 — signed)
#   +0x10: fromUnits  (8 bytes BE, guint64)
#   +0x18: toValue    (8 bytes BE, guint64)
#   +0x20: toDate     (8 bytes BE, gint64 — signed)
#   +0x28: toUnits    (8 bytes BE, guint64)
#   +0x30: unk052     (4 bytes BE)
#   +0x34: unk056     (4 bytes BE)
#   +0x38: unk060     (4 bytes BE)
#   +0x3C: unk064     (4 bytes BE)
#   +0x40: unk068     (4 bytes BE)

def mhod_spl_rule_from_value(data, data_offset) -> int:
    return struct.unpack(">Q", data[data_offset:data_offset + 8])[0]


def mhod_spl_rule_from_date(data, data_offset) -> int:
    """Signed 64-bit big-endian."""
    return struct.unpack(">q", data[data_offset + 8:data_offset + 16])[0]


def mhod_spl_rule_from_units(data, data_offset) -> int:
    return struct.unpack(">Q", data[data_offset + 16:data_offset + 24])[0]


def mhod_spl_rule_to_value(data, data_offset) -> int:
    return struct.unpack(">Q", data[data_offset + 24:data_offset + 32])[0]


def mhod_spl_rule_to_date(data, data_offset) -> int:
    """Signed 64-bit big-endian."""
    return struct.unpack(">q", data[data_offset + 32:data_offset + 40])[0]


def mhod_spl_rule_to_units(data, data_offset) -> int:
    return struct.unpack(">Q", data[data_offset + 40:data_offset + 48])[0]


def mhod_spl_rule_unk052(data, data_offset) -> int:
    return struct.unpack(">I", data[data_offset + 48:data_offset + 52])[0]


def mhod_spl_rule_unk056(data, data_offset) -> int:
    return struct.unpack(">I", data[data_offset + 52:data_offset + 56])[0]


def mhod_spl_rule_unk060(data, data_offset) -> int:
    return struct.unpack(">I", data[data_offset + 56:data_offset + 60])[0]


def mhod_spl_rule_unk064(data, data_offset) -> int:
    return struct.unpack(">I", data[data_offset + 60:data_offset + 64])[0]


def mhod_spl_rule_unk068(data, data_offset) -> int:
    return struct.unpack(">I", data[data_offset + 64:data_offset + 68])[0]


# Field ID → human-readable name (from libgpod ItdbSPLField enum in itdb.h)
SPL_FIELD_MAP = {
    0x02: "Song Name",
    0x03: "Album",
    0x04: "Artist",
    0x05: "Bitrate",
    0x06: "Sample Rate",
    0x07: "Year",
    0x08: "Genre",
    0x09: "Kind",
    0x0A: "Date Modified",
    0x0B: "Track Number",
    0x0C: "Size",
    0x0D: "Time",
    0x0E: "Comment",
    0x10: "Date Added",
    0x12: "Composer",
    0x16: "Play Count",
    0x17: "Last Played",
    0x18: "Disc Number",
    0x19: "Rating",
    0x1F: "Compilation",
    0x23: "BPM",
    0x27: "Grouping",
    0x28: "Playlist",
    0x29: "Purchased",
    0x36: "Description",
    0x37: "Category",
    0x39: "Podcast",
    0x3C: "Media Type",
    0x3E: "TV Show",
    0x3F: "Season Number",
    0x44: "Skip Count",
    0x45: "Last Skipped",
    0x47: "Album Artist",
    0x4E: "Sort Song Name",
    0x4F: "Sort Album",
    0x50: "Sort Artist",
    0x51: "Sort Album Artist",
    0x52: "Sort Composer",
    0x53: "Sort TV Show",
    0x5A: "Album Rating",
}

# Action ID → human-readable name (from libgpod ItdbSPLAction enum in itdb.h;
# confirmed against iPodLinux wiki).
# Actions are 32-bit bitmapped values, NOT small sequential integers.
# Byte layout:
#   Bits 24-25: 0x00=int/date, 0x01=string, 0x02=negated int, 0x03=negated string
#   Bits 0-10:  comparison operator flags
SPL_ACTION_MAP = {
    # Integer / date comparisons (0x00xxxxxx)
    0x00000001: "is",
    0x00000010: "is greater than",
    0x00000020: "is greater than or equal to",  # not in iTunes UI
    0x00000040: "is less than",
    0x00000080: "is less than or equal to",  # not in iTunes UI
    0x00000100: "is in the range",
    0x00000200: "is in the last",
    0x00000400: "binary AND",  # used for Media Type / Video Kind
    0x00000800: "binary unknown1",
    # String comparisons (0x01xxxxxx)
    0x01000001: "is (string)",
    0x01000002: "contains",
    0x01000004: "starts with",
    0x01000008: "ends with",
    # Negated integer / date (0x02xxxxxx)
    0x02000001: "is not",
    0x02000010: "is not greater than",  # not in iTunes UI
    0x02000020: "is not greater than or equal to",  # not in iTunes UI
    0x02000040: "is not less than",  # not in iTunes UI
    0x02000080: "is not less than or equal to",  # not in iTunes UI
    0x02000100: "is not in the range",  # not in iTunes UI
    0x02000200: "is not in the last",
    0x02000400: "not binary AND",
    0x02000800: "binary unknown2",
    # Negated string (0x03xxxxxx)
    0x03000001: "is not (string)",
    0x03000002: "does not contain",
    0x03000004: "does not start with",  # not in iTunes UI
    0x03000008: "does not end with",  # not in iTunes UI
}

# Field type enum (from libgpod ItdbSPLFieldType — values start at 1)
SPLFT_STRING = 1
SPLFT_INT = 2
SPLFT_BOOLEAN = 3
SPLFT_DATE = 4
SPLFT_PLAYLIST = 5
SPLFT_UNKNOWN = 6
SPLFT_BINARY_AND = 7

# Map field ID → field type (equivalent to libgpod's itdb_splr_get_field_type).
# This is how libgpod determines how to parse the rule data — NOT from a binary field.
SPL_FIELD_TYPE_MAP = {
    # String fields
    0x02: SPLFT_STRING,    # Song Name
    0x03: SPLFT_STRING,    # Album
    0x04: SPLFT_STRING,    # Artist
    0x08: SPLFT_STRING,    # Genre
    0x09: SPLFT_STRING,    # Kind
    0x0E: SPLFT_STRING,    # Comment
    0x12: SPLFT_STRING,    # Composer
    0x27: SPLFT_STRING,    # Grouping
    0x36: SPLFT_STRING,    # Description
    0x37: SPLFT_STRING,    # Category
    0x3E: SPLFT_STRING,    # TV Show
    0x47: SPLFT_STRING,    # Album Artist
    0x4E: SPLFT_STRING,    # Sort Song Name
    0x4F: SPLFT_STRING,    # Sort Album
    0x50: SPLFT_STRING,    # Sort Artist
    0x51: SPLFT_STRING,    # Sort Album Artist
    0x52: SPLFT_STRING,    # Sort Composer
    0x53: SPLFT_STRING,    # Sort TV Show
    # Integer fields
    0x05: SPLFT_INT,       # Bitrate
    0x06: SPLFT_INT,       # Sample Rate
    0x07: SPLFT_INT,       # Year
    0x0B: SPLFT_INT,       # Track Number
    0x0C: SPLFT_INT,       # Size
    0x0D: SPLFT_INT,       # Time
    0x16: SPLFT_INT,       # Play Count
    0x18: SPLFT_INT,       # Disc Number
    0x19: SPLFT_INT,       # Rating
    0x23: SPLFT_INT,       # BPM
    0x3F: SPLFT_INT,       # Season Number
    0x44: SPLFT_INT,       # Skip Count
    0x5A: SPLFT_INT,       # Album Rating
    # Date fields
    0x0A: SPLFT_DATE,      # Date Modified
    0x10: SPLFT_DATE,      # Date Added
    0x17: SPLFT_DATE,      # Last Played
    0x45: SPLFT_DATE,      # Last Skipped
    # Boolean fields
    0x1F: SPLFT_BOOLEAN,   # Compilation
    0x29: SPLFT_BOOLEAN,   # Purchased
    0x39: SPLFT_INT,       # Podcast
    # Playlist field
    0x28: SPLFT_PLAYLIST,  # Playlist
    # Binary AND
    0x3C: SPLFT_BINARY_AND,  # Video Kind
}

# Date units for relative date rules
SPL_DATE_UNITS_MAP = {
    1: "seconds",
    60: "minutes",
    3600: "hours",
    86400: "days",
    604800: "weeks",
    2628000: "months",  # ~30.4 days
}


def spl_get_field_type(field_id: int) -> int:
    """Determine SPL field type from field ID (equivalent to libgpod's itdb_splr_get_field_type)."""
    return SPL_FIELD_TYPE_MAP.get(field_id, SPLFT_UNKNOWN)


# ============================================================
# MHOD Type 52/53 — Library Playlist Index / Jump Table
# ============================================================
# Both types share header structure (sort_type + count).
# Functions take body_offset = start of body data (MHOD chunk + header_length).
#
# Type 52 layout:
#   +0x00: sort_type (4 bytes LE) — 3=title, 4=album, 5=artist, 7=genre, 18=composer
#   +0x04: count (4 bytes LE) — number of index entries
#   +0x08: padding (40 bytes)
#   +0x30: indices (count × 4 bytes LE) — sorted track positions
#
# Type 53 layout:
#   +0x00: sort_type (4 bytes LE) — must match corresponding type 52
#   +0x04: count (4 bytes LE) — number of jump entries
#   +0x08: padding (8 bytes)
#   +0x10: entries (count × 12 bytes):
#          letter (2 bytes UTF-16 LE) + pad (2 bytes) + start (4 bytes) + count (4 bytes)

SORT_TYPE_MAP = {
    0x03: "title",
    0x04: "album",          # then disc/track number, then title
    0x05: "artist",         # then album, then disc/track number, then title
    0x07: "genre",          # then artist, then album, then disc/track number, then title
    0x12: "composer",       # then title
    0x1D: "show",           # iTunes 7.2+; secondary sort TBD
    0x1E: "season_number",  # iTunes 7.2+; secondary sort TBD
    0x1F: "episode_number",  # iTunes 7.2+; secondary sort TBD
    0x23: "album_artist",   # then artist (ignoring sort-artist), then album, disc/track, title
    0x24: "artist_nosort",  # artist (ignoring sort-artist), then album, disc/track, title
}


def mhod52_sort_type(data, body_offset) -> int:
    return struct.unpack("<I", data[body_offset:body_offset + 4])[0]


def mhod52_count(data, body_offset) -> int:
    return struct.unpack("<I", data[body_offset + 4:body_offset + 8])[0]


def mhod53_sort_type(data, body_offset) -> int:
    return struct.unpack("<I", data[body_offset:body_offset + 4])[0]


def mhod53_count(data, body_offset) -> int:
    return struct.unpack("<I", data[body_offset + 4:body_offset + 8])[0]


# ============================================================
# MHOD Type 100 — Playlist Position (MHIP context)
# ============================================================
# In MHIP context (body ≤ 20 bytes):
#   +0x00: position (4 bytes LE) — 0-based track position in playlist

def mhod100_position(data, body_offset) -> int:
    return struct.unpack("<I", data[body_offset:body_offset + 4])[0]
