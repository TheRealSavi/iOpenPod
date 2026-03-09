"""MHIT (Track Item) parser.

Parses a single track record and its MHOD string children.  The MHIT
header is the largest in the iTunesDB (up to ~500 bytes in newer
database versions) and contains all numeric track metadata.

The third generic-header field is ``total_length`` (header + body).
Child count is stored inside the header at offset 0x0C.
"""

from __future__ import annotations

from typing import Any

import iTunesDB_Shared as idb
from ._parsing import ParseResult, parse_children


def _parse_mhit_header(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
) -> dict[str, Any]:
    """Extract all MHIT header fields into a flat dict."""
    header = idb.read_fields(data, offset, "mhit", header_length)
    # Convert raw bytes to list of ints for JSON serialization.
    raw = header.get("sort_mhod_indicators", b"")
    if isinstance(raw, (bytes, bytearray)):
        header["sort_mhod_indicators"] = list(raw)
    return header


def parse_track_item(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHIT (Track Item) chunk and its MHOD children."""
    mhit = _parse_mhit_header(data, offset, header_length)
    mhit["children"], _ = parse_children(
        data, offset + header_length, mhit["child_count"],
    )
    return {"next_offset": offset + chunk_length, "data": mhit}
