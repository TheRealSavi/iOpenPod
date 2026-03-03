"""
MHLI (Artist List) parser for iTunesDB.

MHLI is the container for all artist items, used in MHSD type 8.
Its third header field (offset 8) is the number of MHII children,
NOT a total byte length — same convention as MHLT, MHLP, and MHLA.

NOTE: This is NOT the same as ArtworkDB's mhli (image list).  In the
iTunesDB context, mhli holds artist/composer items with mhii children.

Field layout:
    +0x00 (0):  'mhli' magic (4B)
    +0x04 (4):  header_length (4B)
    +0x08 (8):  artist_count (4B) — number of MHII children
    Rest of header is zero-padded.

Cross-referenced against:
  - libgpod itdb_itunesdb.c: parse_mhli() / mk_mhli()
  - docs/iTunesCDB-internals.md §Type 8
"""

from typing import Any


def parse_artistList(data, offset, header_length, artistCount) -> dict[str, Any]:
    from .chunk_parser import parse_chunk

    artistList = []

    # Parse Children (mhii artist items)
    next_offset = offset + header_length
    for i in range(artistCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        artistList.append(response["result"])

    return {"nextOffset": next_offset, "result": artistList}
