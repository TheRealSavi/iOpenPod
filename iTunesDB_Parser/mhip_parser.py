"""MHIP (Playlist Item) parser.

Each MHIP lives inside an MHYP (playlist) and references a track by
``track_id``.  It may also carry MHOD type-100 children for position
information.
"""

from __future__ import annotations

from typing import Any

import iTunesDB_Shared as idb
from ._parsing import ParseResult, parse_children


def _parse_mhip_header(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
) -> dict[str, Any]:
    """Extract MHIP header fields."""
    return idb.read_fields(data, offset, "mhip", header_length)


def parse_playlist_item(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHIP (Playlist Item) chunk and its MHOD children."""
    mhip = _parse_mhip_header(data, offset, header_length)
    mhip["children"], _ = parse_children(
        data, offset + header_length, mhip["child_count"],
    )
    return {"next_offset": offset + chunk_length, "data": mhip}
