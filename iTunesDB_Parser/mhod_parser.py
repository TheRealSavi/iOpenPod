import struct


# String MHOD types have a string sub-header at offset 24.
# Types 1-44 are track/item string metadata, 200-300 are album item strings.
# Non-string types (50, 51, 52, 53, 100) have completely different binary layouts
# per libgpod's MhodHeaderSmartPlaylistData, etc.
STRING_MHOD_TYPES = set(range(1, 45)) | set(range(200, 301))

# Non-string MHOD types with dedicated binary formats
NON_STRING_MHOD_TYPES = {50, 51, 52, 53, 100, 102}


def parse_mhod(data, offset, header_length, chunk_length) -> dict:
    mhod_type = struct.unpack("<I", data[offset + 12:offset + 16])[0]

    # Dispatch non-string MHOD types to dedicated parsers
    if mhod_type in NON_STRING_MHOD_TYPES:
        parsed_data = _parse_nonstring_mhod(data, offset, header_length, chunk_length, mhod_type)
        return {"nextOffset": offset + chunk_length, "result": {"mhodType": mhod_type, "data": parsed_data}}

    # Only attempt string parsing for known string MHOD types
    if mhod_type not in STRING_MHOD_TYPES:
        # Unknown non-string MHOD — return stub
        return {"nextOffset": offset + chunk_length, "result": {"mhodType": mhod_type, "string": ""}}

    string_length = struct.unpack("<I", data[offset + 28:offset + 32])[0]
    # Read encoding flag from the string sub-header (0 or 1 = UTF-16LE, 2 = UTF-8)
    encoding_flag = struct.unpack("<I", data[offset + 24:offset + 28])[0]
    string_data = data[offset + 40:offset + 40 + string_length]

    string_decode = ""
    if encoding_flag == 2:
        string_decode = string_data.decode("utf-8", errors="replace")
    else:
        # encoding_flag 0 or 1 = UTF-16LE (most common on iPod)
        string_decode = string_data.decode("utf-16-le", errors="replace")

    return {"nextOffset": offset + chunk_length, "result": {"mhodType": mhod_type, "string": string_decode}}


# ============================================================
# Non-string MHOD dispatcher
# ============================================================

def _parse_nonstring_mhod(data, offset, header_length, chunk_length, mhod_type) -> dict:
    """Route non-string MHODs to their specific parsers."""
    body_offset = offset + 24  # All non-string MHODs start body at offset 24

    match mhod_type:
        case 50:
            return _parse_mhod50_smart_playlist_data(data, body_offset, chunk_length - 24)
        case 51:
            return _parse_mhod51_smart_playlist_rules(data, body_offset, chunk_length - 24)
        case 52:
            return _parse_mhod52_library_index(data, body_offset, chunk_length - 24)
        case 53:
            return _parse_mhod53_jump_table(data, body_offset, chunk_length - 24)
        case 100:
            return _parse_mhod100_playlist_prefs(data, body_offset, chunk_length - 24)
        case 102:
            return _parse_mhod102_playlist_settings(data, body_offset, chunk_length - 24)
        case _:
            return {}


# ============================================================
# MHOD Type 50 — Smart Playlist Preferences (SPLPref)
# ============================================================
#
# Based on libgpod's SPLPref struct (itdb_spl.c) and the iPodLinux wiki.
#
# The data section immediately follows the 24-byte MHOD header.
# Layout (offset from body start):
#   +0x00: liveupdate (1 byte) — 1 = auto-update when library changes
#   +0x01: checkrules (1 byte) — 1 = limit by rules (match checked items)
#   +0x02: checklimits (1 byte) — 1 = limit by size/count/time
#   +0x03: limittype (1 byte) — what the limit applies to:
#          0x01=minutes, 0x02=MB, 0x03=songs, 0x04=hours, 0x05=GB
#          (libgpod ItdbLimitType enum)
#   +0x04: limitsort (1 byte) — how to choose items when limited:
#          0x02=random, 0x03=song_name, 0x04=album, 0x05=artist,
#          0x07=genre, 0x10=most_recently_added, 0x14=most_often_played,
#          0x15=most_recently_played, 0x17=highest_rating
#          (libgpod ItdbLimitSort enum; high bit 0x80000000 set via
#           reverse flag at +0x0D for "least"/"lowest" variants)
#   +0x05: pad (3 bytes)
#   +0x08: limitvalue (4 bytes) — the limit value (songs/MB/min/etc.)
#   +0x0C: matchCheckedOnly (1 byte) — 1 = only match checked items
#   +0x0D: pad (119 bytes) to total 132 bytes

# Limit type names (from libgpod ItdbLimitType)
SPL_LIMIT_TYPE_MAP = {
    0x01: "minutes",
    0x02: "MB",
    0x03: "songs",
    0x04: "hours",
    0x05: "GB",
}

# Limit sort names (from libgpod ItdbLimitSort)
# The 0x80000000 bit is the "reverse" flag, stored separately at SPLPref +13.
# Values here include the combined flag for lookup convenience.
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


def _parse_mhod50_smart_playlist_data(data, body_offset, body_length) -> dict:
    """Parse SPLPref (Smart Playlist Preferences) from MHOD type 50."""
    if body_length < 12:
        return {"error": "SPLPref too short"}

    result = {}
    result["liveUpdate"] = bool(data[body_offset])
    result["checkRules"] = bool(data[body_offset + 1])
    result["checkLimits"] = bool(data[body_offset + 2])

    limit_type = data[body_offset + 3]
    result["limitType"] = limit_type
    result["limitTypeName"] = SPL_LIMIT_TYPE_MAP.get(limit_type, f"unknown({limit_type})")

    # limitsort lower byte at +4; reverse flag at +13
    limit_sort_raw = data[body_offset + 4]

    # 3 bytes padding at offset 5

    result["limitValue"] = struct.unpack("<I", data[body_offset + 8:body_offset + 12])[0]

    if body_length >= 13:
        result["matchCheckedOnly"] = bool(data[body_offset + 12])
    else:
        result["matchCheckedOnly"] = False

    # Reverse sort flag at +13 (libgpod: if get8int(cts, seek+13) then limitsort |= 0x80000000)
    if body_length >= 14 and data[body_offset + 13]:
        limit_sort = limit_sort_raw | 0x80000000
    else:
        limit_sort = limit_sort_raw

    result["limitSort"] = limit_sort
    result["limitSortName"] = SPL_LIMIT_SORT_MAP.get(limit_sort, f"unknown(0x{limit_sort:X})")

    return result


# ============================================================
# MHOD Type 51 — Smart Playlist Rules (SPLRules / SLst)
# ============================================================
#
# Based on libgpod's SPLRules / SPLRule structs and the definitive
# get_mhod() / mk_mhod() functions in itdb_itunesdb.c.
#
# CRITICAL: The SLst blob is the ONLY part of the iTunesDB that uses
# big-endian encoding (including UTF-16 strings). All multi-byte integers
# within the SLst must be read as big-endian.
#
# SLst header (136 bytes):
#   +0x00: 'SLst' magic (4 bytes)
#   +0x04: unk004 (4 bytes BE) — usually 0
#   +0x08: rule_count (4 bytes BE)
#   +0x0C: conjunction (4 bytes BE) — 0=AND (match all), 1=OR (match any)
#   +0x10: padding (120 bytes, zeros)
#
# Each rule (variable length):
#   +0x00: field (4 bytes BE) — what field to match (see SPL_FIELD_MAP)
#   +0x04: action (4 bytes BE) — comparison operator (see SPL_ACTION_MAP)
#   +0x08: padding (44 bytes, zeros)
#   +0x34: length (4 bytes BE) — byte length of following data
#   +0x38: data (length bytes):
#
#   For STRING rules (field type = STRING):
#     data = UTF-16 BE string (length bytes)
#
#   For non-STRING rules (INT/DATE/BOOLEAN/PLAYLIST/BINARY_AND):
#     length = 0x44 (68 bytes), containing:
#     +0x00: fromvalue  (8 bytes BE, unsigned 64-bit — guint64)
#     +0x08: fromdate   (8 bytes BE, signed 64-bit — gint64)
#     +0x10: fromunits  (8 bytes BE, unsigned 64-bit — guint64)
#     +0x18: tovalue    (8 bytes BE, unsigned 64-bit — guint64)
#     +0x20: todate     (8 bytes BE, signed 64-bit — gint64)
#     +0x28: tounits    (8 bytes BE, unsigned 64-bit — guint64)
#     +0x30: unk052     (4 bytes BE)
#     +0x34: unk056     (4 bytes BE)
#     +0x38: unk060     (4 bytes BE)
#     +0x3C: unk064     (4 bytes BE)
#     +0x40: unk068     (4 bytes BE)
#
# Total rule size = 56 + length (NOT 136 + string_length!)
#   Non-string rule:  56 + 0x44 = 124 bytes
#   String rule:      56 + string_byte_length

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

# Action ID → human-readable name (from libgpod ItdbSPLAction enum in itdb.h)
# Actions are 32-bit bitmapped values, NOT small sequential integers.
SPL_ACTION_MAP = {
    # Integer comparisons (low bits only)
    0x00000001: "is",
    0x00000010: "is greater than",
    0x00000040: "is less than",
    0x00000100: "is in the range",
    0x00000200: "is in the last",
    0x00000400: "binary AND",
    # String comparisons (0x01xxxxxx)
    0x01000001: "is (string)",
    0x01000002: "contains",
    0x01000004: "starts with",
    0x01000008: "ends with",
    # Negated integer (0x02xxxxxx)
    0x02000001: "is not",
    0x02000010: "is not greater than",
    0x02000040: "is not less than",
    0x02000100: "is not in the range",
    0x02000200: "is not in the last",
    0x02000400: "not binary AND",
    0x02000800: "binary unknown2",
    # Binary unknown (low bits only)
    0x00000800: "binary unknown1",
    # Negated string (0x03xxxxxx)
    0x03000001: "is not (string)",
    0x03000002: "does not contain",
    0x03000004: "does not start with",
    0x03000008: "does not end with",
}

# Field type enum (from libgpod ItdbSPLFieldType — values start at 1)
SPLFT_STRING = 1
SPLFT_INT = 2
SPLFT_BOOLEAN = 3
SPLFT_DATE = 4
SPLFT_PLAYLIST = 5
SPLFT_UNKNOWN = 6
SPLFT_BINARY_AND = 7

# Map field ID → field type (equivalent to libgpod's itdb_splr_get_field_type)
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


def _parse_mhod51_smart_playlist_rules(data, body_offset, body_length) -> dict:
    """
    Parse SPLRules (Smart Playlist Rules) from MHOD type 51.

    The SLst blob uses BIG-ENDIAN encoding for ALL multi-byte integers.
    This is the only part of the iTunesDB that is big-endian.
    The SLst header is 136 bytes, followed by variable-length rules.
    """
    if body_length < 16:
        return {"error": "SPLRules too short"}

    # SLst header
    slst_magic = data[body_offset:body_offset + 4]
    if slst_magic != b'SLst':
        return {"error": f"Expected SLst magic, got {slst_magic!r}"}

    result = {}
    # All SLst fields are BIG-endian
    result["unk004"] = struct.unpack(">I", data[body_offset + 4:body_offset + 8])[0]
    rule_count = struct.unpack(">I", data[body_offset + 8:body_offset + 12])[0]
    conjunction = struct.unpack(">I", data[body_offset + 12:body_offset + 16])[0]

    result["ruleCount"] = rule_count
    result["conjunction"] = "OR" if conjunction else "AND"

    # Parse individual rules (start after 136-byte SLst header)
    SLST_HEADER_SIZE = 136
    rules = []
    rule_offset = body_offset + SLST_HEADER_SIZE

    for i in range(rule_count):
        # Minimum rule size is 56 bytes (header + length field, no data)
        if rule_offset + 56 > body_offset + body_length:
            break

        rule, rule_total_size = _parse_spl_rule(data, rule_offset)
        rules.append(rule)
        rule_offset += rule_total_size

    result["rules"] = rules
    return result


def _get_field_type(field_id: int) -> int:
    """Determine field type from field ID (equivalent to libgpod's itdb_splr_get_field_type)."""
    return SPL_FIELD_TYPE_MAP.get(field_id, SPLFT_UNKNOWN)


def _parse_spl_rule(data, rule_offset) -> tuple[dict, int]:
    """Parse a single SPL rule starting at rule_offset.

    All multi-byte integers within SLst rules are BIG-ENDIAN.

    Rule binary layout:
        +0x00: field     (4 bytes BE)
        +0x04: action    (4 bytes BE)
        +0x08: padding   (44 bytes)
        +0x34: length    (4 bytes BE) — byte length of following data
        +0x38: data      (length bytes)

    Total rule size = 56 + length.

    Returns:
        Tuple of (rule dict, total_rule_size_in_bytes).
    """
    rule = {}

    # All SLst rule fields are BIG-endian
    field_id = struct.unpack(">I", data[rule_offset:rule_offset + 4])[0]
    action_id = struct.unpack(">I", data[rule_offset + 4:rule_offset + 8])[0]

    rule["fieldID"] = field_id
    rule["field"] = SPL_FIELD_MAP.get(field_id, f"unknown(0x{field_id:02X})")

    rule["actionID"] = action_id
    rule["action"] = SPL_ACTION_MAP.get(action_id, f"unknown(0x{action_id:08X})")

    # Length of data section at +0x34 (BE)
    data_length = struct.unpack(">I", data[rule_offset + 0x34:rule_offset + 0x38])[0]

    # Determine field type from the field ID (NOT from binary data)
    field_type = _get_field_type(field_id)
    rule["fieldType"] = field_type

    # Data starts at +0x38
    data_offset = rule_offset + 0x38

    if field_type == SPLFT_STRING:
        # String rule: data is a UTF-16 BE string
        if data_length > 0:
            string_data = data[data_offset:data_offset + data_length]
            # SLst strings are UTF-16 BIG-endian (unlike the rest of iTunesDB)
            rule["stringValue"] = string_data.decode("utf-16-be", errors="replace")
        else:
            rule["stringValue"] = ""

    else:
        # Non-string rule: INT, DATE, BOOLEAN, PLAYLIST, BINARY_AND, UNKNOWN
        # libgpod expects length == 0x44 for these
        if data_length != 0x44:
            rule["warning"] = f"Expected data_length=0x44 for non-string rule, got 0x{data_length:X}"

        # 6 big-endian 64-bit values (signedness matches libgpod C struct types:
        # fromvalue/fromunits/tovalue/tounits = guint64, fromdate/todate = gint64)
        rule["fromValue"] = struct.unpack(">Q", data[data_offset:data_offset + 8])[0]
        rule["fromDate"] = struct.unpack(">q", data[data_offset + 8:data_offset + 16])[0]
        rule["fromUnits"] = struct.unpack(">Q", data[data_offset + 16:data_offset + 24])[0]
        rule["toValue"] = struct.unpack(">Q", data[data_offset + 24:data_offset + 32])[0]
        rule["toDate"] = struct.unpack(">q", data[data_offset + 32:data_offset + 40])[0]
        rule["toUnits"] = struct.unpack(">Q", data[data_offset + 40:data_offset + 48])[0]

        # 5 unknown 32-bit BE values (libgpod's unk052-unk068)
        rule["unk052"] = struct.unpack(">I", data[data_offset + 48:data_offset + 52])[0]
        rule["unk056"] = struct.unpack(">I", data[data_offset + 52:data_offset + 56])[0]
        rule["unk060"] = struct.unpack(">I", data[data_offset + 56:data_offset + 60])[0]
        rule["unk064"] = struct.unpack(">I", data[data_offset + 60:data_offset + 64])[0]
        rule["unk068"] = struct.unpack(">I", data[data_offset + 64:data_offset + 68])[0]

        # Field-type-specific annotations
        if field_type == SPLFT_DATE:
            # For relative dates, fromUnits is seconds per unit
            if rule["fromUnits"] != 0:
                abs_units = abs(rule["fromUnits"])
                rule["unitsName"] = SPL_DATE_UNITS_MAP.get(
                    abs_units, f"{abs_units} seconds"
                )

        elif field_type == SPLFT_INT:
            # For rating fields, convert from internal (0-100) to stars (0-5)
            if field_id == 0x19:  # Rating
                rule["fromValueStars"] = rule["fromValue"] // 20
                rule["toValueStars"] = rule["toValue"] // 20

        elif field_type == SPLFT_PLAYLIST:
            rule["playlistID"] = rule["fromValue"]

    # Total rule size = 56 bytes (field+action+padding+length) + data_length
    total_size = 56 + data_length
    return rule, total_size


# ============================================================
# MHOD Type 52 — Library Playlist Index
# ============================================================
#
# Based on libgpod's mk_mhod52() in itdb_itunesdb.c
#
# Body layout (after 24-byte MHOD header):
#   +0x00: sort_type (4 bytes) — 3=title, 4=album, 5=artist, 7=genre, 18=composer
#   +0x04: count (4 bytes) — number of index entries
#   +0x08: padding (40 bytes)
#   +0x30: indices (count × 4 bytes) — sorted track positions

SORT_TYPE_MAP = {
    0x03: "title",
    0x04: "album",
    0x05: "artist",
    0x07: "genre",
    0x12: "composer",
}


def _parse_mhod52_library_index(data, body_offset, body_length) -> dict:
    """Parse library playlist index from MHOD type 52."""
    if body_length < 8:
        return {"error": "MHOD52 too short"}

    result = {}
    sort_type = struct.unpack("<I", data[body_offset:body_offset + 4])[0]
    count = struct.unpack("<I", data[body_offset + 4:body_offset + 8])[0]

    result["sortType"] = sort_type
    result["sortTypeName"] = SORT_TYPE_MAP.get(sort_type, f"unknown(0x{sort_type:02X})")
    result["count"] = count

    # Parse actual indices (each is a u32 track position)
    # They start at offset 48 (sort_type + count + 40 bytes padding)
    indices_offset = body_offset + 48
    indices = []
    for i in range(count):
        idx_off = indices_offset + i * 4
        if idx_off + 4 <= body_offset + body_length:
            indices.append(struct.unpack("<I", data[idx_off:idx_off + 4])[0])
    result["indices"] = indices

    return result


# ============================================================
# MHOD Type 53 — Library Playlist Jump Table
# ============================================================
#
# Based on libgpod's mk_mhod53() in itdb_itunesdb.c
#
# Body layout (after 24-byte MHOD header):
#   +0x00: sort_type (4 bytes) — must match corresponding type 52
#   +0x04: count (4 bytes) — number of jump entries
#   +0x08: padding (8 bytes)
#   +0x10: entries (count × 12 bytes):
#          letter (2 bytes, UTF-16) + pad (2 bytes) + start (4 bytes) + count (4 bytes)

def _parse_mhod53_jump_table(data, body_offset, body_length) -> dict:
    """Parse library playlist jump table from MHOD type 53."""
    if body_length < 8:
        return {"error": "MHOD53 too short"}

    result = {}
    sort_type = struct.unpack("<I", data[body_offset:body_offset + 4])[0]
    count = struct.unpack("<I", data[body_offset + 4:body_offset + 8])[0]

    result["sortType"] = sort_type
    result["sortTypeName"] = SORT_TYPE_MAP.get(sort_type, f"unknown(0x{sort_type:02X})")
    result["count"] = count

    # Jump entries start at offset 16 (sort_type + count + 8 padding)
    entries_offset = body_offset + 16
    entries = []
    for i in range(count):
        entry_off = entries_offset + i * 12
        if entry_off + 12 <= body_offset + body_length:
            letter_code = struct.unpack("<H", data[entry_off:entry_off + 2])[0]
            # pad 2 bytes
            start = struct.unpack("<I", data[entry_off + 4:entry_off + 8])[0]
            entry_count = struct.unpack("<I", data[entry_off + 8:entry_off + 12])[0]
            entries.append({
                "letter": chr(letter_code) if letter_code > 0 else "",
                "start": start,
                "count": entry_count,
            })
    result["entries"] = entries

    return result


# ============================================================
# MHOD Type 100 — Playlist Position / Preferences
# ============================================================
#
# Type 100 appears in two contexts:
# 1. As a child of MHIP: contains track position (small, ~20-byte body)
# 2. As a child of MHYP: contains playlist display preferences (large, ~624-byte body)
#
# MHIP context (body = 20 bytes):
#   +0x00: position (4 bytes) — 0-based track position in playlist
#   +0x04: padding (16 bytes)
#
# MHYP context (body = ~624 bytes):
#   Column/view preference blob.  libgpod calls this the "Preferences
#   mhod" and writes canned defaults via mk_long_mhod_id_playlist().
#   iTunes writes a very sparse version — typically only 2-3 nonzero
#   bytes in the entire 624-byte body.  We scan for all nonzero u8/u16/u32
#   values and return them keyed by hex offset.
#
#   Known structure (from libgpod + real-device observation):
#     +0x00-0x0F : 16 bytes padding (always zero on iTunes-created DBs)
#     +0x10      : u32 — first column descriptor (libgpod: 0x010084)
#                        iTunes typically writes 0x00010000 (byte 0x12=1)
#     +0x14      : u32 — second column descriptor (libgpod: 0x05)
#                        iTunes typically writes 0x01
#     +0x18-0x21F: column entries / spacing — mostly zero on iTunes
#     +0x220     : u32 — optional value (observed: 0x8C=140 on non-master lists)
#     +0x224-end : trailing zeros

def _parse_mhod100_playlist_prefs(data, body_offset, body_length) -> dict:
    """Parse playlist position or preferences from MHOD type 100."""
    result = {}

    if body_length <= 20:
        # MHIP context: simple position field
        if body_length >= 4:
            result["position"] = struct.unpack("<I", data[body_offset:body_offset + 4])[0]
        result["context"] = "playlist_item"
    else:
        # MHYP context: playlist display preferences
        result["context"] = "playlist_prefs"
        result["bodyLength"] = body_length
        result["fields"] = _scan_nonzero_fields(data, body_offset, body_length)

    return result


def _scan_nonzero_fields(data, body_offset, body_length) -> dict:
    """Scan a binary body for all nonzero bytes, grouped into u32 values.

    Returns a dict mapping hex-offset strings to integer values.
    Contiguous nonzero bytes within the same 4-byte-aligned u32 are
    merged into a single LE u32 entry.  Isolated single bytes are
    returned as-is.
    """
    fields = {}
    body = data[body_offset:body_offset + body_length]
    visited = set()

    for i in range(len(body)):
        if body[i] != 0 and i not in visited:
            # Try to read as aligned u32 if within bounds
            aligned = (i // 4) * 4
            if aligned + 4 <= len(body):
                val = struct.unpack("<I", body[aligned:aligned + 4])[0]
                if val != 0:
                    fields[f"0x{aligned:03X}"] = val
                    visited.update(range(aligned, aligned + 4))
                    continue
            # Fallback: single byte
            fields[f"0x{i:03X}"] = body[i]
            visited.add(i)

    return fields


# ============================================================
# MHOD Type 102 — Playlist Settings (binary, post-iTunes 7)
# ============================================================
#
# MHOD type 102 appears on playlists created by newer iTunes versions.
# It is a 356-byte (0x164 total, 332 body) binary blob containing
# playlist view settings / column configuration.  The exact format is
# undocumented in libgpod.
#
# From real-device observation (iTunes-written, all instances identical):
#   +0x00: u32 = 1   — unknown flag
#   +0x08: u32 = 1   — unknown flag
#   +0x4C: u32 = 4   — possibly view type or column count
#   +0x8C: u32 = 120 (0x78) — possibly column width in pixels
#   All other bytes are zero.

def _parse_mhod102_playlist_settings(data, body_offset, body_length) -> dict:
    """Parse MHOD type 102 — playlist settings."""
    result = {
        "context": "playlist_settings",
        "bodyLength": body_length,
        "fields": _scan_nonzero_fields(data, body_offset, body_length),
    }
    return result
