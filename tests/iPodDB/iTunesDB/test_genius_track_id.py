"""Genius IDs in extended MHIT headers, independently authored on-wire bytes."""

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


@pytest.mark.parametrize("header_size", [0x1F8, 0x270])
def test_genius_id_reads_and_edits_only_its_eight_bytes(header_size: int) -> None:
    header = bytearray(header_size - 12)
    struct.pack_into("<Q", header, 0x1E4 - 12, 0xFEDCBA9876543210)
    header[0x1EC - 12 : 0x1F4 - 12] = b"RETAINED"
    original = itunes_database(
        dataset(
            1,
            list_chunk(
                b"mhlt", length_chunk(b"mhit", header_size, fields=bytes(header))
            ),
        )
    )
    document = parse_iTunesDB(original)
    selected = document.find_chunks(MhitHeader)[0]
    assert selected.chunk.header.genius_id == 0xFEDCBA9876543210
    assert write_iTunesDB(document) == original

    updated = document.replace_chunk(
        selected,
        replace(selected.chunk, header=replace(selected.chunk.header, genius_id=42)),
    )
    expected = bytearray(original)
    struct.pack_into("<Q", expected, selected.chunk.offset + 0x1E4, 42)
    assert write_iTunesDB(updated) == expected


def test_older_header_has_no_genius_id_and_stays_unchanged() -> None:
    original = itunes_database(
        dataset(1, list_chunk(b"mhlt", length_chunk(b"mhit", 0x9C)))
    )
    document = parse_iTunesDB(original)
    assert document.find_chunks(MhitHeader)[0].chunk.header.genius_id == 0
    assert write_iTunesDB(document) == original
