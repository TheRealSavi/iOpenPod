"""MHII (Artist Item) parser for iTunesDB.

Each MHII lives inside an MHLI (artist list, MHSD type 8) and contains
artist-level metadata (artist_id, SQL ID) plus MHOD type-300 children
with the artist name string.

NOTE: This chunk shares the ``mhii`` magic with ArtworkDB image items,
but in the iTunesDB context it represents an artist record.
"""

from __future__ import annotations

from typing import Any

import iTunesDB_Shared as idb
from ._parsing import ParseResult, parse_children


def _parse_mhii_header(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
) -> dict[str, Any]:
    """Extract MHII (artist item) header fields."""
    return idb.read_fields(data, offset, "mhii", header_length)


def parse_artist_item(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHII (Artist Item) chunk and its MHOD children."""
    mhii = _parse_mhii_header(data, offset, header_length)
    mhii["children"], _ = parse_children(
        data, offset + header_length, mhii["child_count"],
    )
    return {"next_offset": offset + chunk_length, "data": mhii}
