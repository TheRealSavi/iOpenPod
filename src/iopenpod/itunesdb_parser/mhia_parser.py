"""MHIA (Album Item) parser.

Each MHIA lives inside an MHLA (album list) and contains album-level
metadata (album_id, SQL ID, compilation flag) plus MHOD string children
(types 200-204) with album name, artist, etc.
"""

from __future__ import annotations

import iopenpod.itunesdb_shared as idb

from ._parsing import ParseResult
from .chunk_parser import parse_children


def parse_album_item(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHIA (Album Item) chunk and its MHOD children."""
    mhia = idb.read_fields(data, offset, "mhia", header_length)
    mhia["children"], _ = parse_children(
        data, offset + header_length, mhia["child_count"],
    )
    return {"next_offset": offset + chunk_length, "data": mhia}
