"""
MHII (Artist Item) parser for iTunesDB.

In the iTunesDB context (MHSD type 8), 'mhii' chunks represent artist
entries — NOT artwork images (which also use the 'mhii' magic in
ArtworkDB).  Each artist item has child MHOD strings, typically a single
MHOD type 300 containing the artist name.

Field layout (header size typically 80 bytes):
    +0x00 (0):  'mhii' magic (4B)
    +0x04 (4):  header_length (4B) — typically 80
    +0x08 (8):  total_length (4B) — header + child MHODs
    +0x0C (12): child_count (4B) — number of MHOD children
    +0x10 (16): artist_id (4B) — links to MHIT.artist_id
    +0x14 (20): sql_id (8B) — internal iPod DB id
    +0x1C (28): unk3 (4B) — always 2

    Children: MHOD type 300 (artist name)

Cross-referenced against:
  - libgpod itdb_itunesdb.c: mk_mhii() (artist variant)
  - docs/iTunesCDB-internals.md §Type 8
"""

import struct


def parse_artistItem(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk
    from .constants import mhod_type_map

    childCount = struct.unpack("<I", data[offset + 12:offset + 16])[0]

    artist_id = struct.unpack("<I", data[offset + 16:offset + 20])[0]
    # 0x10: Artist ID that tracks reference via MHIT.artist_id.

    sql_id = struct.unpack("<Q", data[offset + 20:offset + 28])[0]
    # 0x14: SQL ID (64-bit) — used by iPod's internal SQLite database.

    unk3 = struct.unpack("<I", data[offset + 28:offset + 32])[0]
    # 0x1C: Unknown — always 2, same as MHIA.

    artist = {}
    artist["artistId"] = artist_id
    artist["sqlId"] = sql_id
    artist["unk3"] = unk3

    # Parse Children (typically one MHOD type 300 with artist name)
    next_offset = offset + header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]

        mhodData = response["result"]
        mhod_type = mhodData.get("mhodType")
        if mhod_type is not None:
            field_name = mhod_type_map.get(mhod_type, f"unknown_mhod_{mhod_type}")
            artist[field_name] = mhodData.get("string", "")

    return {"nextOffset": offset + chunk_length, "result": artist}
