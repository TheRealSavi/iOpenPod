"""MHSD (DataSet) parser.

An MHSD contains exactly one child chunk whose type is determined by the
dataset type field at offset 0x0C (see ``constants.chunk_type_map``).

Dataset types: 1=TrackList, 2=PlaylistList, 3=PodcastList, 4=AlbumList,
5=SmartPlaylistList, 6/10=empty stubs, 8=ArtistList, 9=Genius CUID.
"""

from __future__ import annotations

from typing import Any

import iopenpod.itunesdb_shared as idb

from ._parsing import ParseResult
from .chunk_parser import parse_children


def parse_dataset(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHSD (DataSet) chunk and its single child."""
    mhsd: dict[str, Any] = idb.read_fields(data, offset, "mhsd", header_length)
    if mhsd.get("dataset_type") == 9:
        raw_payload = bytes(data[offset + header_length:offset + chunk_length])
        mhsd["raw_payload"] = raw_payload
        try:
            mhsd["genius_cuid"] = raw_payload.decode("ascii")
        except UnicodeDecodeError:
            mhsd["genius_cuid"] = raw_payload.hex()
        mhsd["children"] = []
        return {"next_offset": offset + chunk_length, "data": mhsd}

    # MHSD always has exactly one child.
    mhsd["children"], _ = parse_children(data, offset + header_length, 1)
    return {"next_offset": offset + chunk_length, "data": mhsd}
