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

from iTunesDB_Shared.mhod_defs import (
    MHOD_HEADER_SIZE,
    SPLPREF_BODY_SIZE,
    SLST_HEADER_SIZE,
    SPL_RULE_HEADER_SIZE,
    SPL_RULE_DATA_SIZE,
    SPLFT_STRING,
    spl_get_field_type,
    write_mhod_header,
)


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
    unk004: int = 0  # SLst header +0x04, usually 0 (preserved for round-trip)


# ────────────────────────────────────────────────────────────
# MHOD Type 50 — Smart Playlist Preferences
# ────────────────────────────────────────────────────────────

def write_mhod50(prefs: SmartPlaylistPrefs) -> bytes:
    """Write MHOD type 50 (smart playlist preferences / SPLPref).

    Returns:
        Complete MHOD chunk bytes.
    """
    body = bytearray(SPLPREF_BODY_SIZE)

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

    return write_mhod_header(50, MHOD_HEADER_SIZE + SPLPREF_BODY_SIZE) + bytes(body)


# ────────────────────────────────────────────────────────────
# MHOD Type 51 — Smart Playlist Rules (SLst)
# ────────────────────────────────────────────────────────────

def _write_spl_rule(rule: SmartPlaylistRule) -> bytes:
    """Write a single SLst rule entry (big-endian).

    Rule layout:
        +0x00: field     (4 BE)
        +0x04: action    (4 BE)
        +0x08: padding   (44 bytes)
        +0x34: length    (4 BE) — byte length of data
        +0x38: data      (length bytes)

    Total = SPL_RULE_HEADER_SIZE + data_length.
    """
    ft = spl_get_field_type(rule.field_id)

    if ft == SPLFT_STRING and rule.string_value is not None:
        # String rule: data = UTF-16 BE string
        string_bytes = rule.string_value.encode('utf-16-be')
        data_length = len(string_bytes)
        data_section = string_bytes
    else:
        # Non-string: fixed SPL_RULE_DATA_SIZE (68) byte data section
        data_length = SPL_RULE_DATA_SIZE
        data_section = bytearray(SPL_RULE_DATA_SIZE)
        # from_value, to_value, from_units, to_units use unsigned '>Q' format
        # but can be negative for date-relative rules (e.g. "in the last N days").
        # Apply two's complement conversion so struct.pack doesn't raise.
        _mask = 0xFFFFFFFFFFFFFFFF
        struct.pack_into('>Q', data_section, 0x00, rule.from_value & _mask)
        struct.pack_into('>q', data_section, 0x08, rule.from_date)
        struct.pack_into('>Q', data_section, 0x10, rule.from_units & _mask)
        struct.pack_into('>Q', data_section, 0x18, rule.to_value & _mask)
        struct.pack_into('>q', data_section, 0x20, rule.to_date)
        struct.pack_into('>Q', data_section, 0x28, rule.to_units & _mask)
        struct.pack_into('>I', data_section, 0x30, rule.unk052)
        struct.pack_into('>I', data_section, 0x34, rule.unk056)
        struct.pack_into('>I', data_section, 0x38, rule.unk060)
        struct.pack_into('>I', data_section, 0x3C, rule.unk064)
        struct.pack_into('>I', data_section, 0x40, rule.unk068)
        data_section = bytes(data_section)

    # Build rule header
    rule_header = bytearray(SPL_RULE_HEADER_SIZE)
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
    slst_header = bytearray(SLST_HEADER_SIZE)
    slst_header[0:4] = b'SLst'
    struct.pack_into('>I', slst_header, 4, rules_data.unk004)
    struct.pack_into('>I', slst_header, 8, len(rules_data.rules))
    conjunction_val = 1 if rules_data.conjunction.upper() == "OR" else 0
    struct.pack_into('>I', slst_header, 12, conjunction_val)
    # 120 bytes padding already zero

    # Build individual rules
    rules_bytes = b''.join(_write_spl_rule(r) for r in rules_data.rules)

    slst_body = bytes(slst_header) + rules_bytes

    return write_mhod_header(51, MHOD_HEADER_SIZE + len(slst_body)) + slst_body


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
    return write_mhod_header(102, MHOD_HEADER_SIZE + len(raw_body)) + raw_body


# ────────────────────────────────────────────────────────────
# Helpers for building from parsed data (round-trip)
# ────────────────────────────────────────────────────────────

def prefs_from_parsed(parsed: dict) -> SmartPlaylistPrefs:
    """Create SmartPlaylistPrefs from a parsed MHOD type 50 dict.

    This is the inverse of _parse_mhod50_smart_playlist_data().
    """
    # Parser stores limit_sort as the raw low byte and reverse_sort
    # separately.  Reconstruct the combined value the writer expects.
    limit_sort = parsed.get("limit_sort", 0x02)
    if parsed.get("reverse_sort", 0):
        limit_sort |= 0x80000000

    return SmartPlaylistPrefs(
        live_update=parsed.get("live_update", True),
        check_rules=parsed.get("check_rules", True),
        check_limits=parsed.get("check_limits", False),
        limit_type=parsed.get("limit_type", 0x03),
        limit_sort=limit_sort,
        limit_value=parsed.get("limit_value", 25),
        match_checked_only=parsed.get("match_checked_only", False),
    )


def rules_from_parsed(parsed: dict) -> SmartPlaylistRules:
    """Create SmartPlaylistRules from a parsed MHOD type 51 dict.

    This is the inverse of _parse_mhod51_smart_playlist_rules().
    """
    rules = []
    for r in parsed.get("rules", []):
        rule = SmartPlaylistRule(
            field_id=r.get("field_id", 0),
            action_id=r.get("action_id", 0),
            string_value=r.get("string_value"),
            from_value=r.get("from_value", 0),
            from_date=r.get("from_date", 0),
            from_units=r.get("from_units", 0),
            to_value=r.get("to_value", 0),
            to_date=r.get("to_date", 0),
            to_units=r.get("to_units", 0),
            unk052=r.get("unk052", 0),
            unk056=r.get("unk056", 0),
            unk060=r.get("unk060", 0),
            unk064=r.get("unk064", 0),
            unk068=r.get("unk068", 0),
        )
        rules.append(rule)

    raw_conj = parsed.get("conjunction", "AND")
    if isinstance(raw_conj, int):
        conj = "OR" if raw_conj == 1 else "AND"
    else:
        conj = raw_conj

    return SmartPlaylistRules(
        conjunction=conj,
        rules=rules,
        unk004=parsed.get("unk004", 0),
    )
