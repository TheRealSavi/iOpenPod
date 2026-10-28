"""Record-class naming preserves the MHIT wire contract and unrecognized values."""

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
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB


@pytest.mark.parametrize("record_class", [1, 2, 3, 0, 0xDEADBEEF])
def test_record_class_preserves_unknown_values_and_edits_only_its_word(
    record_class: int,
) -> None:
    fields = bytearray(0x9C - 12)
    struct.pack_into("<I", fields, 0x14 - 12, record_class)
    fields[0x10 - 12 : 0x14 - 12] = b"BEFR"
    fields[0x18 - 12 : 0x1C - 12] = b"AFTR"
    original = itunes_database(
        dataset(
            1,
            list_chunk(b"mhlt", length_chunk(b"mhit", 0x9C, fields=bytes(fields))),
        )
    )
    document = parse_iTunesDB(original)
    selected = document.find_chunks(MhitHeader)[0]
    assert selected.chunk.header.record_class == record_class
    assert write_iTunesDB(document) == original

    updated = document.replace_chunk(
        selected,
        replace(selected.chunk, header=replace(selected.chunk.header, record_class=3)),
    )
    expected = bytearray(original)
    struct.pack_into("<I", expected, selected.chunk.offset + 0x14, 3)
    assert write_iTunesDB(updated) == expected


def test_new_track_keeps_file_record_class_default() -> None:
    assert MhitHeader().record_class == 1
