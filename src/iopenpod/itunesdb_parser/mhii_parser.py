"""MHII (Artist Item) parser for iTunesDB.

Each MHII lives inside an MHLI (artist list, MHSD type 8) and contains
artist-level metadata (artist_id, SQL ID) plus MHOD type-300 children
with the artist name string.

NOTE: This chunk shares the ``mhii`` magic with ArtworkDB image items,
but in the iTunesDB context it represents an artist record.
"""

from __future__ import annotations  # noqa: I001

import iopenpod.itunesdb_shared as idb

from ._parsing import ParseResult
from .chunk_parser import parse_children


def parse_artist_item(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHII (Artist Item) chunk and its MHOD children."""
    mhii = idb.read_fields(data, offset, "mhii", header_length)
    mhii["children"], _ = parse_children(
        data, offset + header_length, mhii["child_count"],
    )
    return {"next_offset": offset + chunk_length, "data": mhii}
