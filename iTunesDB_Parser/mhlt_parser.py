"""
MHLT (Track List) parser.

MHLT is the container for all track items in the database.
Its third header field (offset 8) is the number of MHIT children,
NOT a total byte length — same convention as MHLP and MHLA.

Field layout:
    +0x00 (0):  'mhlt' magic (4B)
    +0x04 (4):  header_length (4B)
    +0x08 (8):  track_count (4B) — total number of MHIT children
    Rest of header is zero-padded.

Cross-referenced against:
  - iPodLinux wiki § TrackList
  - libgpod itdb_itunesdb.c
"""

from typing import Any


def parse_trackList(data, offset, header_length, trackCount) -> dict[str, Any]:
    from .chunk_parser import parse_chunk

    trackList = []

    # Parse Children
    next_offset = offset + header_length
    for i in range(trackCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        trackList.append(response["result"])

    return {"nextOffset": next_offset, "result": trackList}
