"""
MHLA (Album List) parser.

MHLA is the container for all album items, introduced with iTunes 7.1.
Its third header field (offset 8) is the number of MHIA children,
NOT a total byte length — same convention as MHLT and MHLP.

Field layout:
    +0x00 (0):  'mhla' magic (4B)
    +0x04 (4):  header_length (4B)
    +0x08 (8):  album_count (4B) — number of MHIA children
    Rest of header is zero-padded.

Cross-referenced against:
  - iPodLinux wiki § Album List
  - libgpod itdb_itunesdb.c
"""

from typing import Any


def parse_albumList(data, offset, header_length, albumCount) -> dict[str, Any]:
    from .chunk_parser import parse_chunk

    albumList = []

    # Parse Children
    next_offset = offset + header_length
    for i in range(albumCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        albumList.append(response["result"])

    return {"nextOffset": next_offset, "result": albumList}
