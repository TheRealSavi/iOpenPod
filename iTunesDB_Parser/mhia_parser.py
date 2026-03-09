"""MHIA (Album Item) parser.

Each MHIA lives inside an MHLA (album list) and contains album-level
metadata (album_id, SQL ID, compilation flag) plus MHOD string children
(types 200-204) with album name, artist, etc.
"""

from __future__ import annotations

from typing import Any

import iTunesDB_Shared as idb
from ._parsing import ParseResult, parse_children


def _parse_mhia_header(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
) -> dict[str, Any]:
    """Extract MHIA header fields."""
    return idb.read_fields(data, offset, "mhia", header_length)


def parse_album_item(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHIA (Album Item) chunk and its MHOD children."""
    mhia = _parse_mhia_header(data, offset, header_length)
    mhia["children"], _ = parse_children(
        data, offset + header_length, mhia["child_count"],
    )
    return {"next_offset": offset + chunk_length, "data": mhia}
