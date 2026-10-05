"""Shared authored binary fixtures for database parser and preservation tests."""

import struct

from iPodDB.iTunesDB.parser.parser_definition import PARSER_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.shared.chunk import ParsedChunk
from iPodDB.shared.chunk_reader import parse_chunk_as


def length_chunk(
    marker: bytes,
    header_length: int,
    body: bytes = b"",
    *,
    fields: bytes = b"",
) -> bytes:
    header = bytearray(header_length)
    struct.pack_into(
        "<4sII", header, 0, marker, header_length, header_length + len(body)
    )
    header[12 : 12 + len(fields)] = fields
    return bytes(header) + body


def list_chunk(marker: bytes, *children: bytes) -> bytes:
    header = bytearray(92)
    struct.pack_into("<4sII", header, 0, marker, len(header), len(children))
    return bytes(header) + b"".join(children)


def dataset(dataset_type: int, child: bytes) -> bytes:
    return length_chunk(
        b"mhsd",
        96,
        child,
        fields=struct.pack("<I", dataset_type),
    )


def itunes_database(*datasets: bytes) -> bytes:
    fields = bytearray(12)
    struct.pack_into("<I", fields, 8, len(datasets))
    return length_chunk(b"mhbd", 244, b"".join(datasets), fields=bytes(fields))


def artwork_database(*datasets: bytes, next_mhii_id: int = 64) -> bytes:
    body = b"".join(datasets)
    header = bytearray(132)
    struct.pack_into("<4sII", header, 0, b"mhfd", len(header), len(header) + len(body))
    struct.pack_into("<I", header, 0x0C, 11)
    struct.pack_into("<I", header, 0x10, 2)
    struct.pack_into("<I", header, 0x14, len(datasets))
    struct.pack_into("<I", header, 0x18, 12)
    struct.pack_into("<I", header, 0x1C, next_mhii_id)
    struct.pack_into("<Q", header, 0x20, 0x0102030405060708)
    struct.pack_into("<Q", header, 0x28, 0x1112131415161718)
    struct.pack_into("<I", header, 0x30, 2)
    struct.pack_into("<IIII", header, 0x34, 13, 14, 15, 16)
    return bytes(header) + body


def artwork_string_mhod(mhod_type: int, value: str) -> bytes:
    encoding = "utf-16-le" if mhod_type == 3 else "utf-8"
    encoding_indicator = 2 if mhod_type == 3 else 1
    encoded = value.encode(encoding)
    padding = (4 - len(encoded) % 4) % 4
    body = (
        struct.pack("<IB3xI", len(encoded), encoding_indicator, 0)
        + encoded
        + bytes(padding)
    )
    header = bytearray(24)
    struct.pack_into(
        "<4sIIH", header, 0, b"mhod", len(header), len(header) + len(body), mhod_type
    )
    header[0x0F] = padding
    return bytes(header) + body


def photo_album(album_id: int, image_id: int, name: str) -> bytes:
    children = artwork_string_mhod(1, name)
    member = bytearray(40)
    struct.pack_into("<4sII", member, 0, b"mhia", len(member), len(member))
    struct.pack_into("<I", member, 0x10, image_id)
    children += member

    header = bytearray(148)
    struct.pack_into(
        "<4sII", header, 0, b"mhba", len(header), len(header) + len(children)
    )
    struct.pack_into("<II", header, 0x0C, 1, 1)
    struct.pack_into("<I", header, 0x14, album_id)
    struct.pack_into("<IH", header, 0x18, 0x1111, 0x2222)
    header[0x1E] = 2
    header[0x1F:0x24] = bytes((1, 2, 3, 4, 5))
    struct.pack_into("<II", header, 0x24, 6000, 700)
    header[0x2C:0x34] = b"ALBUMRAW"
    struct.pack_into("<Q", header, 0x34, 0x2122232425262728)
    struct.pack_into("<I", header, 0x3C, 6)
    return bytes(header) + children


def mhod(mhod_type: int, body: bytes) -> bytes:
    return (
        struct.pack(
            "<4sIIIII",
            b"mhod",
            0x18,
            0x18 + len(body),
            mhod_type,
            0,
            0,
        )
        + body
    )


def parse_mhod(mhod_type: int, body: bytes) -> ParsedChunk[MhodHeader]:
    data = mhod(mhod_type, body)
    chunk, next_offset = parse_chunk_as(
        data,
        0,
        MHOD_DEFINITION,
        parser_definition=PARSER_DEFINITION,
    )
    assert next_offset == len(data)
    return chunk
