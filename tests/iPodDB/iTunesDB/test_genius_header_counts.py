"""Firmware-named Genius thresholds retain independent serialized halfwords."""

import struct
from dataclasses import replace

import pytest
from tests.iPodDB.binary_fixtures import itunes_database

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB


@pytest.mark.parametrize("target,minimum", [(0, 0), (25, 10), (1, 2), (65535, 65534)])
def test_genius_count_fields_preserve_values_and_isolated_edits(
    target: int, minimum: int
) -> None:
    original = bytearray(itunes_database())
    original[0xA2:0xA4] = b"BE"
    original[0xA8:0xAA] = b"AF"
    struct.pack_into("<HH", original, 0xA4, target, minimum)
    document = parse_iTunesDB(bytes(original))
    root = document.find_chunks(MhbdHeader)[0]
    assert root.chunk.header.genius_target_count == target
    assert root.chunk.header.genius_minimum_count == minimum
    assert write_iTunesDB(document) == original

    renamed = document.replace_chunk(
        root,
        replace(root.chunk, header=replace(root.chunk.header, language=b"fr")),
    )
    expected = bytearray(original)
    expected[0x46:0x48] = b"fr"
    assert write_iTunesDB(renamed) == expected

    changed = document.replace_chunk(
        root,
        replace(
            root.chunk,
            header=replace(root.chunk.header, genius_minimum_count=7),
        ),
    )
    expected = bytearray(original)
    struct.pack_into("<H", expected, 0xA6, 7)
    assert write_iTunesDB(changed) == expected


def test_genius_count_names_do_not_introduce_authoring_defaults() -> None:
    header = MhbdHeader()
    assert header.genius_target_count == 0
    assert header.genius_minimum_count == 0


def test_database_control_bytes_are_independent_and_preserved() -> None:
    original = bytearray(itunes_database())
    original[0x20:0x24] = bytes((2, 201, 0xAB, 0xCD))
    document = parse_iTunesDB(bytes(original))
    root = document.find_chunks(MhbdHeader)[0]
    header = root.chunk.header
    assert header.platform == 2
    assert header.played_mark_threshold_percent == 201
    assert header.unk_mhbd_0x22 == 0xAB
    assert header.unk_mhbd_0x23 == 0xCD
    assert write_iTunesDB(document) == original

    updated = document.replace_chunk(
        root,
        replace(
            root.chunk,
            header=replace(header, played_mark_threshold_percent=80),
        ),
    )
    expected = bytearray(original)
    expected[0x21] = 80
    assert write_iTunesDB(updated) == expected
