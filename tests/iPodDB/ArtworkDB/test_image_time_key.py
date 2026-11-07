"""The named MHNI key remains a raw little-endian word at the evidenced offset."""

import struct
from dataclasses import replace

import pytest

from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.shared.binary_struct import parse_binary_struct, write_binary_struct_into


@pytest.mark.parametrize("key", [0, 1, 15_000, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF])
def test_raw_time_key_round_trip_and_edit_preserve_unrelated_header_bytes(
    key: int,
) -> None:
    # Literal offset and endian packing are independent of the Chunk definition.
    original = bytearray(range(76))
    struct.pack_into("<I", original, 0x24, key)
    header = parse_binary_struct(original, 0, MhniHeader)
    assert header.image_time_key == key
    round_trip = bytearray(original)
    write_binary_struct_into(round_trip, header)
    assert round_trip == original

    edited = bytearray(original)
    write_binary_struct_into(edited, replace(header, image_time_key=15_000))
    assert struct.unpack_from("<I", edited, 0x24)[0] == 15_000
    assert edited[:0x24] == original[:0x24]
    assert edited[0x28:] == original[0x28:]
