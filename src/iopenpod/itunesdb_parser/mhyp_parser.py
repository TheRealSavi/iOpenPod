"""MHYP (Playlist) parser.

An MHYP represents a single playlist.  Its children are split into two
groups parsed sequentially: MHOD metadata objects first, then MHIP
playlist-item entries.  The counts are stored separately in the header.
"""

from __future__ import annotations

import iopenpod.itunesdb_shared as idb

from ._parsing import ParseResult
from .chunk_parser import parse_children


def parse_playlist(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHYP (Playlist) chunk with MHOD + MHIP child groups."""
    mhyp = idb.read_fields(data, offset, "mhyp", header_length)

    # MHODs come first, then MHIPs — parsed sequentially with shared offset.
    body_start = offset + header_length
    mhyp["mhod_children"], mhip_start = parse_children(
        data, body_start, mhyp["mhod_child_count"],
    )
    mhyp["mhip_children"], _ = parse_children(
        data, mhip_start, mhyp["mhip_child_count"],
    )

    return {"next_offset": offset + chunk_length, "data": mhyp}
