"""
MHBD (Database Header) parser.

The MHBD chunk is the root of the iTunesDB file.  It contains global
metadata (version, IDs, crypto hashes) and all MHSD (DataSet) children.

Field layout (offset from chunk start):
    +0x00 (0):   'mhbd' magic (4B)
    +0x04 (4):   header_length (4B) — 0x68 for dbversion <= 0x15, 0xBC for >= 0x17
    +0x08 (8):   total_length (4B) — entire file size
    +0x0C (12):  unk1 (4B) — always 1
    +0x10 (16):  version_number (4B) — see constants.version_map
    +0x14 (20):  children_count (4B) — number of MHSD children (2–5)
    +0x18 (24):  database_id (8B) — dbid, not checked by iPod, zeroed before hashing
    +0x20 (32):  platform (2B) — 1=Mac, 2=Windows
    +0x22 (34):  unk_0x22 (2B)
    +0x24 (36):  id_0x24 (8B) — secondary 64-bit ID (dbversion 0x11+)
    +0x2C (44):  unk_0x2c (4B)
    +0x30 (48):  hashingScheme (2B) — 0x01 for Nano 3G / Classic (dbversion 0x19+)
    +0x32 (50):  unk_0x32 (20B) — zeroed before hashing on Nano 3G / Classic
    +0x46 (70):  language (2B) — e.g. 'en' (dbversion 0x13+)
    +0x48 (72):  lib_persist_id (8B) — Library Persistent ID (dbversion 0x14+)
    +0x50 (80):  unk_0x50 (4B)
    +0x54 (84):  unk_0x54 (4B)
    +0x58 (88):  hash58 (20B) — HMAC-SHA1 for Classic/Nano 3G-4G (dbversion 0x19+)
    +0x6C (108): timezone_offset (4B, signed) — seconds from UTC
    +0x70 (112): unk_0x70 (2B)
    +0x72 (114): hash72 (46B) — AES-CBC signature for Nano 5G

Cross-referenced against:
  - iPodLinux wiki: https://web.archive.org/web/20081006030946/http://ipodlinux.org/wiki/ITunesDB
  - libgpod itdb_itunesdb.c: parse_mhbd() / mk_mhbd()
"""

import base64
import struct
from typing import Any


def parse_db(data, offset, header_length, chunk_length) -> dict[str, Any]:
    from .chunk_parser import parse_chunk
    from .constants import version_map, chunk_type_map  # noqa: F401

    database: dict[str, Any] = {}

    database["unk1"] = struct.unpack(
        "<I", data[offset + 12:offset + 16])[0]  # always 1?

    version_number = struct.unpack("<I", data[offset + 16:offset + 20])[0]
    database["VersionHex"] = hex(version_number)

    database["ChildrenCount"] = struct.unpack(
        "<I", data[offset + 20:offset + 24])[0]
    database["DatabaseID"] = struct.unpack("<Q", data[offset + 24:offset + 32])[0]
    database["platform"] = struct.unpack(
        "<H", data[offset + 32:offset + 34])[0]  # 0x20: 1=Mac, 2=Windows
    database["unk_0x22"] = struct.unpack(
        "<H", data[offset + 34:offset + 36])[0]  # 0x22
    database["id_0x24"] = struct.unpack(
        "<Q", data[offset + 36:offset + 44])[0]  # 0x24: secondary 64-bit ID
    database["unk_0x2c"] = struct.unpack(
        "<I", data[offset + 44:offset + 48])[0]  # 0x2C
    database["hashingScheme"] = struct.unpack(
        "<H", data[offset + 48:offset + 50])[0]  # 0x30: version 0x19+
    # must be set to 0x01 for the new iPod Nano 3G (video) and iPod Classics.
    # The hash at offset 88 needs to be set as well.
    database["unk_0x32"] = data[offset + 50:offset + 70]  # 0x32: 20 bytes
    # for the new iPod Nano 3G (video) and iPod Classics.
    language_bytes = struct.unpack(
        "<2s", data[offset + 70:offset + 72])[0]  # 0x46: version 0x13+
    database["Lang"] = language_bytes.decode("utf-8")
    database["LibPersistID"] = struct.unpack(
        "<Q", data[offset + 72:offset + 80])[0]  # 0x48: version 0x14+
    # 64-bit Persistent ID for this iPod Library. This matches the value of
    # "Library Persistent ID" seen in hex form (as a 16-char hex string)
    # in the drag object XML when dragging a track from an iPod in iTunes.

    database["unk_0x50"] = struct.unpack(
        "<I", data[offset + 80:offset + 84])[0]  # 0x50
    database["unk_0x54"] = struct.unpack(
        "<I", data[offset + 84:offset + 88])[0]  # 0x54
    database["hash58"] = data[offset + 88:offset + 108]  # 0x58: 20 bytes
    database["timezoneOffset"] = struct.unpack(
        "<i", data[offset + 108:offset + 112])[0]  # 0x6C: signed, seconds
    database["unk_0x70"] = struct.unpack(
        "<H", data[offset + 112:offset + 114])[0]  # 0x70
    database["hash72"] = data[offset + 114:offset + 160]  # 0x72: 46 bytes

    # Extended fields (0xA0+) — only present in newer database versions.
    # These are read by extract_db_info() in the writer for round-trip,
    # but we also expose them in the parsed output for completeness.
    if header_length >= 0xA4:
        database["audioLanguage"] = struct.unpack(
            "<H", data[offset + 0xA0:offset + 0xA2])[0]
        database["subtitleLanguage"] = struct.unpack(
            "<H", data[offset + 0xA2:offset + 0xA4])[0]
    if header_length >= 0xAB:
        database["unk_0xa4"] = struct.unpack(
            "<H", data[offset + 0xA4:offset + 0xA6])[0]
        database["unk_0xa6"] = struct.unpack(
            "<H", data[offset + 0xA6:offset + 0xA8])[0]
        database["unk_0xa8"] = struct.unpack(
            "<H", data[offset + 0xA8:offset + 0xAA])[0]

    # parse children
    next_offset = offset + header_length
    for i in range(database["ChildrenCount"]):
        childResult = parse_chunk(data, next_offset)
        next_offset = childResult["nextOffset"]
        resultData = childResult["result"]
        resultType = childResult["datasetType"]
        type_key = chunk_type_map.get(resultType, f"mhsd_type_{resultType}")
        database[type_key] = resultData

    # Convert byte fields to base64 for JSON serialization
    def replace_bytes_with_base64(data: Any) -> Any:
        if isinstance(data, dict):  # If it's a dictionary, process each key-value pair
            return {key: replace_bytes_with_base64(value) for key, value in data.items()}
        elif isinstance(data, list):  # If it's a list, process each item
            return [replace_bytes_with_base64(item) for item in data]
        elif isinstance(data, bytes):  # If it's bytes, encode to Base64
            return base64.b64encode(data).decode("utf-8")
        else:
            return data  # If it's not bytes, return as-is

    cleaned_database = replace_bytes_with_base64(database)

    return {"nextOffset": offset + chunk_length, "result": cleaned_database}
