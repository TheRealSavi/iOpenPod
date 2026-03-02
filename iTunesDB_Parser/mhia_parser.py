"""
MHIA (Album Item) parser.

MHIA entries live inside the MHLA (Album List) introduced in iTunes 7.1.
Each MHIA represents one album and has child MHOD strings for album name,
artist, sort-artist, podcast URL, and show name.

Field layout (header size 0x58 = 88 bytes):
    +0x00 (0):  'mhia' magic (4B)
    +0x04 (4):  header_length (4B) — typically 0x58
    +0x08 (8):  total_length (4B) — header + child MHODs
    +0x0C (12): child_count (4B) — number of MHOD children
    +0x10 (16): album_id (4B) — links to MHIT.albumID
                libgpod treats this as u32 at offset 0x10.
                The older iPodLinux wiki documented 2B unk at 0x10 and
                2B albumID at 0x12; libgpod is authoritative for newer iPods.
    +0x14 (20): unk2 (8B) — possibly a timestamp (dbversion 0x18+)
    +0x1C (28): unk3 (4B) — always 2 (dbversion 0x18+)

  Children: MHOD types 200 (album), 201 (artist), 202 (sort artist),
            203 (podcast URL), 204 (show).

Cross-referenced against:
  - iPodLinux wiki § Album Item
  - libgpod itdb_itunesdb.c
"""

import struct


def parse_albumItem(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk
    from .constants import mhod_type_map

    childCount = struct.unpack("<I", data[offset + 12:offset + 16])[0]

    album_id_for_track = struct.unpack(
        "<I", data[offset + 16:offset + 20])[0]
    # 0x10: Album ID that tracks reference via MHIT.albumID.
    # libgpod reads this as u32.  Older wiki incorrectly splits into
    # 2B unk + 2B albumID.

    unk2 = struct.unpack("<Q", data[offset + 20:offset + 28])[0]
    # 0x14: Unknown 8B — possibly a timestamp (dbversion 0x18+).

    unk3 = struct.unpack("<I", data[offset + 28:offset + 32])[0]
    # 0x1C: Unknown — always 2 (dbversion 0x18+).

    album = {}

    album["AlbumIDforTrack"] = album_id_for_track
    album["unk2"] = unk2
    album["unk3"] = unk3

    # Parse Children
    next_offset = offset + header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]

        albumData = response["result"]
        mhod_type = albumData["mhodType"]
        field_name = mhod_type_map.get(mhod_type, f"unknown_mhod_{mhod_type}")
        album[field_name] = albumData["string"]

    return {"nextOffset": offset + chunk_length, "result": album}
