"""Independent MHIP bytes retain physical offsets and noncanonical values."""

import struct
from dataclasses import replace

import pytest
from tests.iPodDB.binary_fixtures import (
    dataset,
    itunes_database,
    length_chunk,
    list_chunk,
)

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.shared.binary_struct import parse_binary_struct, write_binary_struct_into
from iPodDB.shared.errors import iPodDBWriteError


@pytest.mark.parametrize("word_order", ["<", ">"])
@pytest.mark.parametrize("unchecked", [0, 1, 2, 0x80, 0xFF])
@pytest.mark.parametrize("marker", [0, 1, 2, 0x80, 0xFF])
def test_flag_bytes_do_not_follow_surrounding_word_order(
    word_order: str, unchecked: int, marker: int
) -> None:
    # Tests the byte fields in isolation, not support for a whole swapped DB.
    raw = bytearray(76)
    struct.pack_into(word_order + "I", raw, 0x14, 0x01020304)
    raw[0x10:0x14] = bytes((unchecked, marker, 0xA5, 0x5A))
    header = parse_binary_struct(raw, 0, MhipHeader)
    assert header.unchecked_override == unchecked
    assert header.group_marker == marker
    assert header.is_group == (marker != 0)
    untouched = bytearray(raw)
    write_binary_struct_into(untouched, header)
    assert untouched == raw

    low_edit = bytearray(raw)
    write_binary_struct_into(low_edit, replace(header, unchecked_override=0x7F))
    expected = bytearray(raw)
    expected[0x10] = 0x7F
    assert low_edit == expected

    marker_edit = bytearray(raw)
    write_binary_struct_into(marker_edit, replace(header, group_marker=0xA0))
    expected = bytearray(raw)
    expected[0x11] = 0xA0
    assert marker_edit == expected


@pytest.mark.parametrize("length", [16, 17, 18, 19, 20])
def test_partial_header_preserves_and_exposes_each_available_byte(length: int) -> None:
    fields = b"\0\0\0\0\x80\x02\xa5\x5a"[: length - 12]
    original = itunes_database(
        dataset(
            3,
            list_chunk(
                b"mhlp",
                length_chunk(
                    b"mhyp",
                    108,
                    length_chunk(b"mhip", length, fields=fields),
                    fields=struct.pack("<II", 0, 1),
                ),
            ),
        )
    )
    document = parse_iTunesDB(original)
    selected = document.find_chunks(MhipHeader)[0]
    assert selected.chunk.header.unchecked_override == (0x80 if length >= 17 else 0)
    assert selected.chunk.header.group_marker == (2 if length >= 18 else 0)
    assert write_iTunesDB(document) == original
    if length >= 17:
        changed = document.replace_chunk(
            selected,
            replace(
                selected.chunk,
                header=replace(selected.chunk.header, unchecked_override=0xFF),
            ),
        )
        expected = bytearray(original)
        expected[selected.chunk.offset + 0x10] = 0xFF
        assert write_iTunesDB(changed) == expected
    if length == 17:
        changed = document.replace_chunk(
            selected,
            replace(
                selected.chunk, header=replace(selected.chunk.header, group_marker=1)
            ),
        )
        with pytest.raises(iPodDBWriteError, match="group_marker cannot fit"):
            write_iTunesDB(changed)


@pytest.mark.parametrize("field", ["unchecked_override", "group_marker"])
@pytest.mark.parametrize("value", [-1, 256])
def test_each_field_enforces_its_own_byte_range(field: str, value: int) -> None:
    header = replace(MhipHeader(), **{field: value})
    with pytest.raises(iPodDBWriteError, match=field):
        write_binary_struct_into(bytearray(76), header)
