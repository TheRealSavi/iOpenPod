"""
MHOD Type 50/51 Writer — Smart Playlist Preferences & Rules.

Type 50 (SPLPref): Controls live-update, checked-only, and limit settings.
Type 51 (SPLRules/SLst): The actual filter rules that define the smart playlist.

The SLst blob is the ONLY part of the iTunesDB that uses big-endian encoding.
All multi-byte integers within SLst must be written as big-endian, and
string values use UTF-16 BE (not LE like the rest of the database).

Based on libgpod's SPLPref/SPLRules structs in itdb_spl.c / itdb_itunesdb.c
and the parser in iTunesDB_Parser/mhod_parser.py.
"""

import struct
from dataclasses import dataclass, field
from typing import Optional


# ────────────────────────────────────────────────────────────
# Data classes
# ────────────────────────────────────────────────────────────

@dataclass
class SmartPlaylistPrefs:
    """Smart playlist preferences (MHOD type 50 / SPLPref).

    Mirrors the fields parsed by _parse_mhod50_smart_playlist_data().
    """
    live_update: bool = True
    check_rules: bool = True
    check_limits: bool = False
    limit_type: int = 0x03       # 1=minutes, 2=MB, 3=songs, 4=hours, 5=GB
    limit_sort: int = 0x02       # 2=random (low byte); high bit 0x80000000 = reverse
    limit_value: int = 25
    match_checked_only: bool = False


@dataclass
class SmartPlaylistRule:
    """A single smart playlist rule (one entry inside SLst).

    field_id and action_id use the raw integer codes from the parser
    constants (SPL_FIELD_MAP, SPL_ACTION_MAP).
    """
    field_id: int = 0x02         # e.g. 0x02=Song Name, 0x3C=Media Type
    action_id: int = 0x01000002  # e.g. 0x01000002 = "contains"

    # For STRING rules
    string_value: Optional[str] = None

    # For non-string rules (INT/DATE/BOOLEAN/PLAYLIST/BINARY_AND)
    from_value: int = 0
    from_date: int = 0
    from_units: int = 0
    to_value: int = 0
    to_date: int = 0
    to_units: int = 0

    # Five unknown trailing 32-bit values (preserved for round-trip)
    unk052: int = 0
    unk056: int = 0
    unk060: int = 0
    unk064: int = 0
    unk068: int = 0


@dataclass
class SmartPlaylistRules:
    """Full smart playlist rules container (MHOD type 51 / SLst).

    conjunction: "AND" (match all) or "OR" (match any)
    """
    conjunction: str = "AND"  # "AND" or "OR"
    rules: list[SmartPlaylistRule] = field(default_factory=list)


# ────────────────────────────────────────────────────────────
# Field type lookup (mirrors parser SPL_FIELD_TYPE_MAP)
# ────────────────────────────────────────────────────────────

SPLFT_STRING = 1
SPLFT_INT = 2
SPLFT_BOOLEAN = 3
SPLFT_DATE = 4
SPLFT_PLAYLIST = 5
SPLFT_UNKNOWN = 6
SPLFT_BINARY_AND = 7

_FIELD_TYPE_MAP = {
    0x02: SPLFT_STRING, 0x03: SPLFT_STRING, 0x04: SPLFT_STRING,
    0x08: SPLFT_STRING, 0x09: SPLFT_STRING, 0x0E: SPLFT_STRING,
    0x12: SPLFT_STRING, 0x27: SPLFT_STRING, 0x36: SPLFT_STRING,
    0x37: SPLFT_STRING, 0x3E: SPLFT_STRING, 0x47: SPLFT_STRING,
    0x4E: SPLFT_STRING, 0x4F: SPLFT_STRING, 0x50: SPLFT_STRING,
    0x51: SPLFT_STRING, 0x52: SPLFT_STRING, 0x53: SPLFT_STRING,
    0x05: SPLFT_INT, 0x06: SPLFT_INT, 0x07: SPLFT_INT,
    0x0B: SPLFT_INT, 0x0C: SPLFT_INT, 0x0D: SPLFT_INT,
    0x16: SPLFT_INT, 0x18: SPLFT_INT, 0x19: SPLFT_INT,
    0x23: SPLFT_INT, 0x3F: SPLFT_INT, 0x44: SPLFT_INT,
    0x5A: SPLFT_INT, 0x39: SPLFT_INT,
    0x0A: SPLFT_DATE, 0x10: SPLFT_DATE, 0x17: SPLFT_DATE,
    0x45: SPLFT_DATE,
    0x1F: SPLFT_BOOLEAN, 0x29: SPLFT_BOOLEAN,
    0x28: SPLFT_PLAYLIST,
    0x3C: SPLFT_BINARY_AND,
}


def _field_type(field_id: int) -> int:
    return _FIELD_TYPE_MAP.get(field_id, SPLFT_UNKNOWN)


# ────────────────────────────────────────────────────────────
# MHOD Type 50 — Smart Playlist Preferences
# ────────────────────────────────────────────────────────────

# SPLPref body layout: 132 bytes total (from libgpod).
_SPLPREF_BODY_SIZE = 132


def write_mhod50(prefs: SmartPlaylistPrefs) -> bytes:
    """Write MHOD type 50 (smart playlist preferences / SPLPref).

    Returns:
        Complete MHOD chunk bytes.
    """
    body = bytearray(_SPLPREF_BODY_SIZE)

    body[0] = 1 if prefs.live_update else 0
    body[1] = 1 if prefs.check_rules else 0
    body[2] = 1 if prefs.check_limits else 0
    body[3] = prefs.limit_type & 0xFF

    # limit_sort: low byte at +4, reverse flag at +13
    low_byte = prefs.limit_sort & 0xFF
    reverse = 1 if (prefs.limit_sort & 0x80000000) else 0
    body[4] = low_byte

    # 3 bytes padding (5..7) already zero

    struct.pack_into('<I', body, 8, prefs.limit_value)

    body[12] = 1 if prefs.match_checked_only else 0
    body[13] = reverse

    # Remaining bytes (14..131) are zero padding

    # MHOD header (24 bytes)
    header_len = 24
    total_len = header_len + _SPLPREF_BODY_SIZE

    header = struct.pack(
        '<4sIIIII',
        b'mhod',
        header_len,
        total_len,
        50,  # type
        0,   # unk1
        0,   # unk2
    )

    return header + bytes(body)


# ────────────────────────────────────────────────────────────
# MHOD Type 51 — Smart Playlist Rules (SLst)
# ────────────────────────────────────────────────────────────

_SLST_HEADER_SIZE = 136  # 4 magic + 4 unk + 4 count + 4 conjunction + 120 pad


def _write_spl_rule(rule: SmartPlaylistRule) -> bytes:
    """Write a single SLst rule entry (big-endian).

    Rule layout:
        +0x00: field     (4 BE)
        +0x04: action    (4 BE)
        +0x08: padding   (44 bytes)
        +0x34: length    (4 BE) — byte length of data
        +0x38: data      (length bytes)

    Total = 56 + length.
    """
    ft = _field_type(rule.field_id)

    if ft == SPLFT_STRING and rule.string_value is not None:
        # String rule: data = UTF-16 BE string
        string_bytes = rule.string_value.encode('utf-16-be')
        data_length = len(string_bytes)
        data_section = string_bytes
    else:
        # Non-string: fixed 0x44 (68) byte data section
        data_length = 0x44
        data_section = bytearray(0x44)
        struct.pack_into('>Q', data_section, 0x00, rule.from_value)
        struct.pack_into('>q', data_section, 0x08, rule.from_date)
        struct.pack_into('>Q', data_section, 0x10, rule.from_units)
        struct.pack_into('>Q', data_section, 0x18, rule.to_value)
        struct.pack_into('>q', data_section, 0x20, rule.to_date)
        struct.pack_into('>Q', data_section, 0x28, rule.to_units)
        struct.pack_into('>I', data_section, 0x30, rule.unk052)
        struct.pack_into('>I', data_section, 0x34, rule.unk056)
        struct.pack_into('>I', data_section, 0x38, rule.unk060)
        struct.pack_into('>I', data_section, 0x3C, rule.unk064)
        struct.pack_into('>I', data_section, 0x40, rule.unk068)
        data_section = bytes(data_section)

    # Build rule header (56 bytes)
    rule_header = bytearray(56)
    struct.pack_into('>I', rule_header, 0x00, rule.field_id)
    struct.pack_into('>I', rule_header, 0x04, rule.action_id)
    # 44 bytes padding (0x08..0x33) already zero
    struct.pack_into('>I', rule_header, 0x34, data_length)

    return bytes(rule_header) + data_section


def write_mhod51(rules_data: SmartPlaylistRules) -> bytes:
    """Write MHOD type 51 (smart playlist rules / SLst).

    The entire SLst blob is big-endian.

    Returns:
        Complete MHOD chunk bytes.
    """
    # Build SLst header
    slst_header = bytearray(_SLST_HEADER_SIZE)
    slst_header[0:4] = b'SLst'
    struct.pack_into('>I', slst_header, 4, 0)  # unk004
    struct.pack_into('>I', slst_header, 8, len(rules_data.rules))
    conjunction_val = 1 if rules_data.conjunction.upper() == "OR" else 0
    struct.pack_into('>I', slst_header, 12, conjunction_val)
    # 120 bytes padding already zero

    # Build individual rules
    rules_bytes = b''.join(_write_spl_rule(r) for r in rules_data.rules)

    slst_body = bytes(slst_header) + rules_bytes

    # MHOD header (24 bytes)
    header_len = 24
    total_len = header_len + len(slst_body)

    header = struct.pack(
        '<4sIIIII',
        b'mhod',
        header_len,
        total_len,
        51,  # type
        0,   # unk1
        0,   # unk2
    )

    return header + slst_body


# ────────────────────────────────────────────────────────────
# MHOD Type 102 — Playlist Settings (opaque blob passthrough)
# ────────────────────────────────────────────────────────────

def write_mhod102(raw_body: bytes) -> bytes:
    """Write MHOD type 102 (playlist settings).

    This is an opaque iTunes binary blob. We preserve it verbatim
    from the parsed data for round-trip fidelity.

    Args:
        raw_body: The raw body bytes (everything after the 24-byte header).

    Returns:
        Complete MHOD chunk bytes.
    """
    header_len = 24
    total_len = header_len + len(raw_body)

    header = struct.pack(
        '<4sIIIII',
        b'mhod',
        header_len,
        total_len,
        102,  # type
        0,    # unk1
        0,    # unk2
    )

    return header + raw_body


# ────────────────────────────────────────────────────────────
# Helpers for building from parsed data (round-trip)
# ────────────────────────────────────────────────────────────

def prefs_from_parsed(parsed: dict) -> SmartPlaylistPrefs:
    """Create SmartPlaylistPrefs from a parsed MHOD type 50 dict.

    This is the inverse of _parse_mhod50_smart_playlist_data().
    """
    return SmartPlaylistPrefs(
        live_update=parsed.get("liveUpdate", True),
        check_rules=parsed.get("checkRules", True),
        check_limits=parsed.get("checkLimits", False),
        limit_type=parsed.get("limitType", 0x03),
        limit_sort=parsed.get("limitSort", 0x02),
        limit_value=parsed.get("limitValue", 25),
        match_checked_only=parsed.get("matchCheckedOnly", False),
    )


def rules_from_parsed(parsed: dict) -> SmartPlaylistRules:
    """Create SmartPlaylistRules from a parsed MHOD type 51 dict.

    This is the inverse of _parse_mhod51_smart_playlist_rules().
    """
    rules = []
    for r in parsed.get("rules", []):
        rule = SmartPlaylistRule(
            field_id=r.get("fieldID", 0),
            action_id=r.get("actionID", 0),
            string_value=r.get("stringValue"),
            from_value=r.get("fromValue", 0),
            from_date=r.get("fromDate", 0),
            from_units=r.get("fromUnits", 0),
            to_value=r.get("toValue", 0),
            to_date=r.get("toDate", 0),
            to_units=r.get("toUnits", 0),
            unk052=r.get("unk052", 0),
            unk056=r.get("unk056", 0),
            unk060=r.get("unk060", 0),
            unk064=r.get("unk064", 0),
            unk068=r.get("unk068", 0),
        )
        rules.append(rule)

    return SmartPlaylistRules(
        conjunction=parsed.get("conjunction", "AND"),
        rules=rules,
    )
