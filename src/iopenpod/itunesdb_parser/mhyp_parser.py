"""MHYP (Playlist) parser.

An MHYP represents a single playlist.  Its children are split into two
groups parsed sequentially: MHOD metadata objects first, then MHIP
playlist-item entries.  The counts are stored separately in the header.
"""

from __future__ import annotations

import iopenpod.itunesdb_shared as idb
from iopenpod.itunesdb_shared.playlist_kinds import (
    is_playlist_folder,
    is_podcast_playlist,
)

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
    kind_flags = mhyp["playlist_kind_flags"]
    parent_folder_playlist_id = mhyp["parent_folder_playlist_id"]
    # Compatibility aliases retain the old parser keys while callers migrate
    # away from treating every non-zero +0x2A word as a podcast marker.
    mhyp["podcast_flag"] = kind_flags
    mhyp["unk0x30_playlist_ref"] = parent_folder_playlist_id
    mhyp["is_podcast"] = is_podcast_playlist(kind_flags)
    mhyp["is_folder"] = is_playlist_folder(kind_flags)

    # MHODs come first, then MHIPs — parsed sequentially with shared offset.
    body_start = offset + header_length
    mhyp["mhod_children"], mhip_start = parse_children(
        data, body_start, mhyp["mhod_child_count"],
    )
    mhyp["mhip_children"], child_end = parse_children(
        data, mhip_start, mhyp["mhip_child_count"],
    )

    return {
        "next_offset": offset + chunk_length,
        "data": mhyp,
        "_body_end": child_end,
    }
