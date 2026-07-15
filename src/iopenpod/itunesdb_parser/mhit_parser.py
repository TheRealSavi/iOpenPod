"""MHIT (Track Item) parser.

Parses a single track record and its MHOD string children.  The MHIT
header is the largest in the iTunesDB (up to ~500 bytes in newer
database versions) and contains all numeric track metadata.

The third generic-header field is ``total_length`` (header + body).
Child count is stored inside the header at offset 0x0C.
"""

from __future__ import annotations

import iopenpod.itunesdb_shared as idb

from ._parsing import ParseResult
from .chunk_parser import parse_children


def parse_track_item(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHIT (Track Item) chunk and its MHOD children."""
    mhit = idb.read_fields(data, offset, "mhit", header_length)
    mhit["children"], _ = parse_children(
        data, offset + header_length, mhit["child_count"],
    )
    return {"next_offset": offset + chunk_length, "data": mhit}
