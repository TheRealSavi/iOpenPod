"""MHIP (Playlist Item) parser.

Each MHIP lives inside an MHYP (playlist) and references a track by
``track_id``.  It may also carry MHOD type-100 children for position
information.
"""

from __future__ import annotations

import iopenpod.itunesdb_shared as idb

from ._parsing import ParseResult
from .chunk_parser import parse_children


def parse_playlist_item(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHIP (Playlist Item) chunk and its MHOD children."""
    mhip = idb.read_fields(data, offset, "mhip", header_length)
    mhip["children"], _ = parse_children(
        data, offset + header_length, mhip["child_count"],
    )
    return {"next_offset": offset + chunk_length, "data": mhip}
