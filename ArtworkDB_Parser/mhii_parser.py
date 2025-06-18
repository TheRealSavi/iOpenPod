import struct


def parse_imageItem(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk
    from .constants import mhod_type_map

    image = {}

    childCount = struct.unpack("<I", data[offset + 12: offset + 16])[0]

    image["imgId"] = struct.unpack("<I", data[offset + 16: offset + 20])[0]

    # First mhii is 0x40, second is 0x41, ...
    # (on mobile phones the first mhii appears to be 0x64, second 0x65, ...)

    image["songId"] = struct.unpack("<Q", data[offset + 20: offset + 28])[0]
    # unique ID that matches the dbid field in the iTunesDB Track Item record.
    # this is what is used to map the ArtworkDB items to iTunesDB Items.

    image["unk1"] = struct.unpack(
        "<I", data[offset + 28: offset + 32])[0]  # always 0

    image["rating"] = struct.unpack("<I", data[offset + 32: offset + 36])[
        0
    ]  # iPhoto rating x20

    image["unk2"] = struct.unpack(
        "<I", data[offset + 36: offset + 40])[0]  # always 0

    image["originalDate"] = struct.unpack(
        "<I", data[offset + 40: offset + 44])[0]
    # always 0 in ArtworkDB. creation timestamp of file in photo database.

    image["exifTakenDate"] = struct.unpack(
        "<I", data[offset + 44: offset + 48])[0]
    # always 0 in ArtworkDB. timestamp of taken time probably from exif in photo db.

    image["srcImgSize"] = struct.unpack(
        "<I", data[offset + 48: offset + 52])[0]
    # size in bytes of the original source image.

    # Parse Children
    next_offset = offset + header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]

        mhodData = response["result"]
        image[mhod_type_map[mhodData["mhodType"]]["name"]] = mhodData

    return {"nextOffset": offset + chunk_length, "result": image}
