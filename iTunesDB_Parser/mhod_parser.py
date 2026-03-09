"""MHOD (Data Object) parser.

MHODs are the most varied chunk type in the iTunesDB.  They are always
leaf nodes (no sub-chunks) but have a ``type`` field at offset 0x0C that
determines how the body should be decoded.

Body layouts by type family:

- **String types** (1-14, 18-31, 33-44, 200-204, 300):
  Standard sub-header at +0x18 with encoding + string_length, then
  UTF-16LE or UTF-8 string data starting at +0x28.

- **Podcast URL types** (15, 16):
  UTF-8 string directly after the 24-byte MHOD header (no sub-header).

- **Chapter data** (17):
  Big-endian atom tree (sean → chap → name) after 12-byte preamble.
  Contains chapter titles and start positions for audiobooks/podcasts.

- **Binary blob types** (32=video track data):
  Raw binary stored as hex string for JSON round-tripping.

- **Smart playlist types** (50=SPLPref, 51=SLst rules):
  Dedicated binary formats.  SLst is the **only** big-endian section
  in the entire iTunesDB (besides chapter data atoms).

- **Index types** (52=sorted index, 53=jump table):
  Library playlist indexing data.

- **Playlist settings** (100=position/preferences, 102=binary prefs):
  Context-dependent layout based on parent chunk (MHIP vs MHYP).
"""

from __future__ import annotations

import logging
import struct
from typing import Any

import iTunesDB_Shared as idb
from ._parsing import UINT16_LE, UINT32_LE, ParseResult

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Common MHOD header (24 bytes at +0x00..+0x18)
# ────────────────────────────────────────────────────────────────────

def _parse_mhod_header(
    data: bytes | bytearray,
    offset: int,
) -> dict[str, Any]:
    """Parse the common 24-byte MHOD header fields."""
    return idb.read_fields(data, offset, "mhod")


# ────────────────────────────────────────────────────────────────────
# Top-level dispatcher
# ────────────────────────────────────────────────────────────────────

def parse_mhod(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse a complete MHOD chunk, dispatching by type to the appropriate decoder."""
    mhod: dict[str, Any] = _parse_mhod_header(data, offset)
    mhod_type: int = mhod["mhod_type"]

    if mhod_type in idb.mhod_defs.NON_STRING_MHOD_TYPES:
        body_offset = offset + header_length
        body_length = chunk_length - header_length
        mhod["data"] = _parse_nonstring_mhod(data, body_offset, body_length, mhod_type)

    elif mhod_type in idb.mhod_defs.PODCAST_URL_MHOD_TYPES:
        # Podcast URL types (15, 16): UTF-8/ASCII string directly after
        # header, with NO sub-header.
        url_length = chunk_length - header_length
        if url_length > 0:
            raw = data[offset + header_length:offset + header_length + url_length]
            mhod["string"] = raw.decode("utf-8", errors="replace").rstrip("\x00")
        else:
            mhod["string"] = ""

    elif mhod_type in idb.mhod_defs.CHAPTER_DATA_MHOD_TYPES:
        body_offset = offset + header_length
        body_length = chunk_length - header_length
        mhod["data"] = _parse_chapter_data(data, body_offset, body_length)

    elif mhod_type in idb.mhod_defs.BINARY_BLOB_MHOD_TYPES:
        # Binary blob types (32=video track data).
        blob_length = chunk_length - header_length
        blob = data[offset + header_length:offset + header_length + blob_length]
        mhod["string"] = blob.hex()

    elif mhod_type in idb.mhod_defs.STRING_MHOD_TYPES:
        _parse_string_mhod(data, offset, mhod)

    else:
        # Unknown MHOD type — return stub.
        mhod["string"] = ""

    return {"next_offset": offset + chunk_length, "data": mhod}


# ────────────────────────────────────────────────────────────────────
# String MHOD decoder
# ────────────────────────────────────────────────────────────────────

def _parse_string_mhod(
    data: bytes | bytearray,
    offset: int,
    mhod: dict[str, Any],
) -> None:
    """Decode a standard string MHOD (sub-header at +0x18) into *mhod* in-place."""
    encoding = idb.mhod_defs.mhod_string_encoding(data, offset)
    string_length = idb.mhod_defs.mhod_string_length(data, offset)
    mhod["unk_0x20"] = idb.mhod_defs.mhod_string_unk0x20(data, offset)
    mhod["unk_0x24"] = idb.mhod_defs.mhod_string_unk0x24(data, offset)

    # String data starts after 24-byte header + 16-byte sub-header.
    string_start = offset + idb.mhod_defs.MHOD_STRING_DATA_OFFSET
    string_data = data[string_start:string_start + string_length]

    if encoding == 2:
        mhod["string"] = string_data.decode("utf-8", errors="replace")
    else:
        # encoding 0 or 1 = UTF-16LE (most common on iPod).
        mhod["string"] = string_data.decode("utf-16-le", errors="replace")


# ────────────────────────────────────────────────────────────────────
# Non-string MHOD dispatcher
# ────────────────────────────────────────────────────────────────────

def _parse_nonstring_mhod(
    data: bytes | bytearray,
    body_offset: int,
    body_length: int,
    mhod_type: int,
) -> dict[str, Any]:
    """Route non-string MHODs to their specific decoders."""
    match mhod_type:
        case 50:
            return _parse_mhod50(data, body_offset, body_length)
        case 51:
            return _parse_mhod51(data, body_offset, body_length)
        case 52:
            return _parse_mhod52(data, body_offset, body_length)
        case 53:
            return _parse_mhod53(data, body_offset, body_length)
        case 100:
            return _parse_mhod100(data, body_offset, body_length)
        case 102:
            return _parse_mhod102(data, body_offset, body_length)
        case _:
            return {}


# ────────────────────────────────────────────────────────────────────
# MHOD Type 50 — Smart Playlist Preferences (SPLPref)
# ────────────────────────────────────────────────────────────────────

def _parse_mhod50(
    data: bytes | bytearray,
    body_offset: int,
    body_length: int,
) -> dict[str, Any]:
    """Parse SPLPref (Smart Playlist Preferences) from MHOD type 50.

    Binary layout (relative to body_offset)::

        +0x00  liveUpdate     (u8)
        +0x01  checkRules     (u8)
        +0x02  checkLimits    (u8)
        +0x03  limitType      (u8)
        +0x04  limitSort      (u8) + 3 padding bytes
        +0x08  limitValue     (u32 LE)
        +0x0C  matchCheckedOnly (u8)  — optional
        +0x0D  reverseSort    (u8)  — optional
    """
    if body_length < 12:
        return {"error": "SPLPref too short"}

    defs = idb.mhod_defs
    result: dict[str, Any] = {
        "live_update": defs.mhod_spl_live_update(data, body_offset),
        "check_rules": defs.mhod_spl_check_rules(data, body_offset),
        "check_limits": defs.mhod_spl_check_limits(data, body_offset),
        "limit_type": defs.mhod_spl_limit_type(data, body_offset),
        "limit_sort": defs.mhod_spl_limit_sort_raw(data, body_offset),
        "limit_value": defs.mhod_spl_limit_value(data, body_offset),
    }

    if body_length >= 13:
        result["match_checked_only"] = defs.mhod_spl_match_checked_only(data, body_offset)
    if body_length >= 14:
        result["reverse_sort"] = defs.mhod_spl_reverse_sort(data, body_offset)

    return result


# ────────────────────────────────────────────────────────────────────
# MHOD Type 51 — Smart Playlist Rules (SLst)
# ────────────────────────────────────────────────────────────────────

def _parse_mhod51(
    data: bytes | bytearray,
    body_offset: int,
    body_length: int,
) -> dict[str, Any]:
    """Parse SPLRules (Smart Playlist Rules) from MHOD type 51.

    CRITICAL: The SLst blob uses BIG-ENDIAN encoding for ALL multi-byte
    integers — the only part of the iTunesDB that does so.
    """
    if body_length < 16:
        return {"error": "SPLRules too short"}

    slst_magic = idb.mhod_defs.mhod_slst_magic(data, body_offset)
    if slst_magic != b'SLst':
        return {"error": f"Expected SLst magic, got {slst_magic!r}"}

    defs = idb.mhod_defs
    rule_count = defs.mhod_slst_rule_count(data, body_offset)
    result: dict[str, Any] = {
        "unk004": defs.mhod_slst_unk004(data, body_offset),
        "rule_count": rule_count,
        "conjunction": defs.mhod_slst_conjunction(data, body_offset),
    }

    # Parse individual rules (start after 136-byte SLst header).
    rules: list[dict[str, Any]] = []
    rule_offset = body_offset + defs.SLST_HEADER_SIZE

    for _ in range(rule_count):
        if rule_offset + defs.SPL_RULE_HEADER_SIZE > body_offset + body_length:
            break
        rule, rule_total_size = _parse_spl_rule(data, rule_offset)
        rules.append(rule)
        rule_offset += rule_total_size

    result["rules"] = rules
    return result


def _parse_spl_rule(
    data: bytes | bytearray,
    rule_offset: int,
) -> tuple[dict[str, Any], int]:
    """Parse a single SPL rule starting at *rule_offset*.

    All multi-byte integers within SLst rules are BIG-ENDIAN.

    Returns:
        Tuple of ``(rule_dict, total_rule_size_in_bytes)``.
    """
    defs = idb.mhod_defs
    rule: dict[str, Any] = {}

    field_id = defs.mhod_spl_rule_field(data, rule_offset)
    rule["field_id"] = field_id
    rule["action_id"] = defs.mhod_spl_rule_action(data, rule_offset)

    data_length = defs.mhod_spl_rule_data_length(data, rule_offset)
    rule["data_length"] = data_length

    # Rule data starts at rule_offset + 0x38 (56 bytes header).
    data_offset = rule_offset + 0x38

    field_type = defs.spl_get_field_type(field_id)

    if field_type == defs.SPLFT_STRING:
        # SLst strings are UTF-16 BIG-endian.
        if data_length > 0:
            raw = data[data_offset:data_offset + data_length]
            rule["string_value"] = raw.decode("utf-16-be", errors="replace")
        else:
            rule["string_value"] = ""
    else:
        # Numeric rule data (INT, DATE, BOOLEAN, PLAYLIST, BINARY_AND).
        rule["from_value"] = defs.mhod_spl_rule_from_value(data, data_offset)
        rule["from_date"] = defs.mhod_spl_rule_from_date(data, data_offset)
        rule["from_units"] = defs.mhod_spl_rule_from_units(data, data_offset)
        rule["to_value"] = defs.mhod_spl_rule_to_value(data, data_offset)
        rule["to_date"] = defs.mhod_spl_rule_to_date(data, data_offset)
        rule["to_units"] = defs.mhod_spl_rule_to_units(data, data_offset)
        rule["unk052"] = defs.mhod_spl_rule_unk052(data, data_offset)
        rule["unk056"] = defs.mhod_spl_rule_unk056(data, data_offset)
        rule["unk060"] = defs.mhod_spl_rule_unk060(data, data_offset)
        rule["unk064"] = defs.mhod_spl_rule_unk064(data, data_offset)
        rule["unk068"] = defs.mhod_spl_rule_unk068(data, data_offset)

    total_size = defs.SPL_RULE_HEADER_SIZE + data_length
    return rule, total_size


# ────────────────────────────────────────────────────────────────────
# MHOD Type 52 — Library Playlist Index
# ────────────────────────────────────────────────────────────────────

def _parse_mhod52(
    data: bytes | bytearray,
    body_offset: int,
    body_length: int,
) -> dict[str, Any]:
    """Parse library playlist sorted index from MHOD type 52.

    Layout::

        +0x00  sort_type  (u32 LE)
        +0x04  count      (u32 LE)
        +0x08  padding    (40 bytes)
        +0x30  indices    (count x u32 LE) — sorted track positions
    """
    if body_length < 8:
        return {"error": "MHOD52 too short"}

    defs = idb.mhod_defs
    count = defs.mhod52_count(data, body_offset)
    result: dict[str, Any] = {
        "sort_type": defs.mhod52_sort_type(data, body_offset),
        "count": count,
    }

    # Indices start at body_offset + 48 (sort_type + count + 40 padding).
    indices_start = body_offset + 48
    indices: list[int] = []
    for i in range(count):
        pos = indices_start + i * 4
        if pos + 4 <= body_offset + body_length:
            indices.append(UINT32_LE.unpack_from(data, pos)[0])
    result["indices"] = indices

    return result


# ────────────────────────────────────────────────────────────────────
# MHOD Type 53 — Library Playlist Jump Table
# ────────────────────────────────────────────────────────────────────

def _parse_mhod53(
    data: bytes | bytearray,
    body_offset: int,
    body_length: int,
) -> dict[str, Any]:
    """Parse library playlist jump table from MHOD type 53.

    Layout::

        +0x00  sort_type  (u32 LE)
        +0x04  count      (u32 LE)
        +0x08  padding    (8 bytes)
        +0x10  entries    (count x 12 bytes each):
               letter (u16 LE) + pad(2) + start(u32 LE) + count(u32 LE)
    """
    if body_length < 8:
        return {"error": "MHOD53 too short"}

    defs = idb.mhod_defs
    count = defs.mhod53_count(data, body_offset)
    result: dict[str, Any] = {
        "sort_type": defs.mhod53_sort_type(data, body_offset),
        "count": count,
    }

    # Jump entries start at body_offset + 16.
    entries_start = body_offset + 16
    entries: list[dict[str, int]] = []
    for i in range(count):
        pos = entries_start + i * 12
        if pos + 12 <= body_offset + body_length:
            letter_code = UINT16_LE.unpack_from(data, pos)[0]
            start = UINT32_LE.unpack_from(data, pos + 4)[0]
            entry_count = UINT32_LE.unpack_from(data, pos + 8)[0]
            entries.append({
                "letter_code": letter_code,
                "start": start,
                "count": entry_count,
            })
    result["entries"] = entries

    return result


# ────────────────────────────────────────────────────────────────────
# MHOD Type 100 — Playlist Position / Preferences
# ────────────────────────────────────────────────────────────────────
#
# Type 100 appears in two contexts:
# 1. As a child of MHIP: contains track position (small, <=20-byte body)
# 2. As a child of MHYP: contains playlist display preferences (large, ~624-byte body)

def _parse_mhod100(
    data: bytes | bytearray,
    body_offset: int,
    body_length: int,
) -> dict[str, Any]:
    """Parse playlist position or preferences from MHOD type 100."""
    result: dict[str, Any] = {}

    if body_length <= 20:
        # MHIP context: simple position field.
        if body_length >= 4:
            result["position"] = idb.mhod_defs.mhod100_position(data, body_offset)
    else:
        # MHYP context: playlist display preferences.
        result["fields"] = _scan_nonzero_fields(data, body_offset, body_length)
        # Preserve raw bytes for round-trip fidelity.
        result["raw_body"] = bytes(data[body_offset:body_offset + body_length])

    return result


def _scan_nonzero_fields(
    data: bytes | bytearray,
    body_offset: int,
    body_length: int,
) -> dict[str, int]:
    """Scan a binary body for all nonzero bytes, grouped into u32 values.

    Returns a dict mapping hex-offset strings to integer values.
    Contiguous nonzero bytes within the same 4-byte-aligned u32 are
    merged into a single LE u32 entry.  Isolated single bytes are
    returned as-is.
    """
    fields: dict[str, int] = {}
    body = data[body_offset:body_offset + body_length]
    visited: set[int] = set()

    for i in range(len(body)):
        if body[i] != 0 and i not in visited:
            # Try to read as aligned u32 if within bounds.
            aligned = (i // 4) * 4
            if aligned + 4 <= len(body):
                val = UINT32_LE.unpack_from(body, aligned)[0]
                if val != 0:
                    fields[f"0x{aligned:03X}"] = val
                    visited.update(range(aligned, aligned + 4))
                    continue
            # Fallback: single byte.
            fields[f"0x{i:03X}"] = body[i]
            visited.add(i)

    return fields


# ────────────────────────────────────────────────────────────────────
# MHOD Type 102 — Playlist Settings (binary, post-iTunes 7)
# ────────────────────────────────────────────────────────────────────

def _parse_mhod102(
    data: bytes | bytearray,
    body_offset: int,
    body_length: int,
) -> dict[str, Any]:
    """Parse MHOD type 102 — playlist settings (opaque binary blob)."""
    return {
        "fields": _scan_nonzero_fields(data, body_offset, body_length),
        # Preserve raw bytes for round-trip fidelity.
        "raw_body": bytes(data[body_offset:body_offset + body_length]),
    }


# ────────────────────────────────────────────────────────────────────
# MHOD Type 17 — Chapter Data (big-endian atom tree)
# ────────────────────────────────────────────────────────────────────
#
# Chapter data for audiobooks and enhanced podcasts.  The body
# contains a 12-byte preamble (3 × u32 LE unknown fields) followed by
# a big-endian atom tree: ``sean`` → ``chap`` × N → ``name`` + ``hedr``.
#
# This is the ONLY part of the iTunesDB (besides the SLst smart
# playlist rules) that uses big-endian encoding for its atoms.
#
# Layout (from libgpod itdb_itunesdb.c and iPodLinux wiki):
#
#   Preamble (LE):
#     +0x00  unk024 (u32)
#     +0x04  unk028 (u32)
#     +0x08  unk032 (u32)
#
#   sean atom (BE):
#     +0x00  total_size (u32 BE)
#     +0x04  "sean" (4 bytes)
#     +0x08  unknown (u32 BE, always 1)
#     +0x0C  child_count (u32 BE, = num_chapters + 1 for hedr)
#     +0x10  unknown (u32 BE, always 0)
#
#   chap atom (BE), repeated per chapter:
#     +0x00  total_size (u32 BE)
#     +0x04  "chap" (4 bytes)
#     +0x08  startpos (u32 BE, milliseconds)
#     +0x0C  child_count (u32 BE, = 1 for name)
#     +0x10  unknown (u32 BE, always 0)
#     +0x14  name atom...
#
#   name atom (BE):
#     +0x00  total_size (u32 BE)
#     +0x04  "name" (4 bytes)
#     +0x08  unknown (u32 BE, always 1)
#     +0x0C  unknown (u32 BE, always 0)
#     +0x10  unknown (u32 BE, always 0)
#     +0x14  string_length (u16 BE, in UTF-16BE code units)
#     +0x16  title (string_length × 2 bytes, UTF-16BE)
#
#   hedr atom (BE, 28 bytes):
#     +0x00  size=28 (u32 BE)
#     +0x04  "hedr" (4 bytes)
#     +0x08  unknown (u32 BE, always 1)
#     +0x0C  child_count=0 (u32 BE)
#     +0x10  unknown (u32 BE, always 0)
#     +0x14  unknown (u32 BE, always 0)
#     +0x18  unknown (u32 BE, always 1)

_UINT32_BE = struct.Struct(">I")
_UINT16_BE = struct.Struct(">H")


def _parse_chapter_data(
    data: bytes | bytearray,
    body_offset: int,
    body_length: int,
) -> dict[str, Any]:
    """Parse chapter data atom tree from MHOD type 17.

    Returns a dict with:
      - ``unk024``, ``unk028``, ``unk032``: preamble unknowns
      - ``chapters``: list of {``startpos``: int, ``title``: str}
    """
    defs = idb.mhod_defs
    result: dict[str, Any] = {}

    if body_length < defs.CHAPTER_PREAMBLE_SIZE:
        result["error"] = "Chapter data too short for preamble"
        return result

    # Read 12-byte preamble (little-endian, like the rest of iTunesDB).
    result["unk024"] = UINT32_LE.unpack_from(data, body_offset)[0]
    result["unk028"] = UINT32_LE.unpack_from(data, body_offset + 4)[0]
    result["unk032"] = UINT32_LE.unpack_from(data, body_offset + 8)[0]

    seek = body_offset + defs.CHAPTER_PREAMBLE_SIZE
    end = body_offset + body_length

    # Check for "sean" atom.
    if seek + 20 > end:
        result["chapters"] = []
        return result

    _sean_size = _UINT32_BE.unpack_from(data, seek)[0]  # noqa: F841
    sean_magic = data[seek + 4:seek + 8]
    if sean_magic != defs.SEAN_ATOM:
        logger.warning("Chapter data: expected 'sean' atom, got %r", sean_magic)
        result["chapters"] = []
        return result

    num_children = _UINT32_BE.unpack_from(data, seek + 12)[0]
    num_chapters = max(0, num_children - 1)  # subtract 1 for hedr
    seek += 20  # skip sean header

    chapters: list[dict[str, Any]] = []
    for _ in range(num_chapters):
        if seek + 20 > end:
            break
        chap_magic = data[seek + 4:seek + 8]
        if chap_magic != defs.CHAP_ATOM:
            break  # unexpected atom, stop parsing

        chap_size = _UINT32_BE.unpack_from(data, seek)[0]
        startpos = _UINT32_BE.unpack_from(data, seek + 8)[0]
        children = _UINT32_BE.unpack_from(data, seek + 12)[0]
        child_seek = seek + 20

        title = ""
        for _ in range(children):
            if child_seek + 22 > end:
                break
            child_size = _UINT32_BE.unpack_from(data, child_seek)[0]
            child_magic = data[child_seek + 4:child_seek + 8]
            if child_magic == defs.NAME_ATOM:
                str_len = _UINT16_BE.unpack_from(data, child_seek + 20)[0]
                str_start = child_seek + 22
                str_end = str_start + str_len * 2
                if str_end <= end:
                    title = data[str_start:str_end].decode("utf-16-be", errors="replace")
            child_seek += child_size

        chapters.append({"startpos": startpos, "title": title})
        seek += chap_size

    # Skip hedr atom if present.
    if seek + 8 <= end:
        hedr_magic = data[seek + 4:seek + 8]
        if hedr_magic == defs.HEDR_ATOM:
            hedr_size = _UINT32_BE.unpack_from(data, seek)[0]
            seek += hedr_size

    result["chapters"] = chapters
    return result
