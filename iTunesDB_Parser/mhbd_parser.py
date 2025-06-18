import base64
import struct

from .chunk_parser import parse_chunk
from .constants import version_map, chunk_type_map


def parse_db(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk
    from .constants import version_map, chunk_type_map

    database = {}

    database["unk1"] = struct.unpack(
        "<I", data[offset + 12:offset + 16])[0]  # always 1?

    version_number = struct.unpack("<I", data[offset + 16:offset + 20])[0]
    database["VersionHex"] = hex(version_number)
    # TODO: get the rest of the database version numbers and add them to the map
    # database["VersionName"] = version_map[database["VersionHex"]]

    database["ChildrenCount"] = struct.unpack(
        "<I", data[offset + 20:offset + 24])[0]
    database["DatabaseID"] = struct.unpack("<Q", data[offset + 24:offset + 32])[0]
    database["unk2"] = struct.unpack(
        "<H", data[offset + 32:offset + 34])[0]  # always 2?
    # nothing in docs for data[34:38]
    database["unk3"] = struct.unpack(
        "<Q", data[offset + 38:offset + 46])[0]  # version 0x11+ unknown use
    # nothing in docs for data[46:48]
    database["unk4"] = struct.unpack(
        "<H", data[offset + 48:offset + 50])[0]  # version 0x19+
    # must be set to 0x01 for the new iPod Nano 3G (video) and iPod Classics.
    # The obscure hash at offset 88 needs to be set as well.
    database["unk5"] = data[offset + 50:offset + 70]  # version 0x19+ unknown use
    # for the new iPod Nano 3G (video) and iPod Classics.
    language_bytes = struct.unpack(
        "<2s", data[offset + 70:offset + 72])[0]  # version 0x13+
    database["Lang"] = language_bytes.decode("utf-8")
    database["LibPersistID"] = struct.unpack(
        "<Q", data[offset + 72:offset + 80])  # version 0x14+
    # 64-bit Persistent ID for this iPod Library. This matches the value of
    # "Library Persistent ID" seen in hex form (as a 16-char hex string)
    # in the drag object XML when dragging a song from an iPod in iTunes.

    # nothing in docs for data[80:88]
    database["obscure_hash"] = data[offset + 88:offset + 108]  # version 0x19+
    # for the new iPod Nano 3G (video) and iPod Classics. Must be set.

    # parse children
    next_offset = offset + header_length
    for i in range(database["ChildrenCount"]):
        childResult = parse_chunk(data, next_offset)
        next_offset = childResult["nextOffset"]
        resultData = childResult["result"]
        resultType = childResult["datasetType"]
        database[chunk_type_map[resultType]] = resultData

    # TODO: TEMPORARY FIX FOR FIXING BYTE DATA INTO BASE64 TO BE JSON WRITABLE
    def replace_bytes_with_base64(data):
        if isinstance(data, dict):  # If it's a dictionary, process each key-value pair
            return {key: replace_bytes_with_base64(value) for key, value in data.items()}
        elif isinstance(data, list):  # If it's a list, process each item
            return [replace_bytes_with_base64(item) for item in data]
        elif isinstance(data, bytes):  # If it's bytes, encode to Base64
            return base64.b64encode(data).decode("utf-8")
        else:
            return data  # If it's not bytes, return as-is

    cleaned_database = replace_bytes_with_base64(database)

    return cleaned_database
