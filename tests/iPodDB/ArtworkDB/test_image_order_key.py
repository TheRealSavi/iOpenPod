"""Literal MHII ordering keys survive edits without changing adjacent metadata."""

import struct
from dataclasses import replace

import pytest
from tests.iPodDB.binary_fixtures import (
    artwork_database,
    dataset,
    length_chunk,
    list_chunk,
)

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB


@pytest.mark.parametrize("key", [0, 1, 0x80000000, 0xFFFFFFFF])
@pytest.mark.parametrize("header_length", [52, 152])
def test_image_order_key_round_trip_and_independent_edit(
    key: int, header_length: int
) -> None:
    fields = bytearray(header_length - 12)
    struct.pack_into("<I", fields, 4, 63)
    struct.pack_into("<IIII", fields, 0x1C - 12, 0xAABBCCDD, 97, key, 0x12345678)
    raw = artwork_database(
        dataset(
            1,
            list_chunk(
                b"mhli", length_chunk(b"mhii", header_length, fields=bytes(fields))
            ),
        )
    )
    document = parse_ArtworkDB(raw)
    selected = document.find_chunks(MhiiHeader)[0]
    assert selected.chunk.header.image_order_key == key
    assert selected.chunk.header.unk_mhii_0x1c == 0xAABBCCDD
    assert selected.chunk.header.rating == 97
    assert write_ArtworkDB(document) == raw
    edited = document.replace_chunk(
        selected,
        replace(
            selected.chunk,
            header=replace(selected.chunk.header, image_order_key=0x76543210),
        ),
    )
    expected = bytearray(raw)
    struct.pack_into("<I", expected, selected.chunk.offset + 0x24, 0x76543210)
    assert write_ArtworkDB(edited) == expected
