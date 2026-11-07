"""Literal wire evidence for the full Track pair and protected timing selector."""

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
from iPodDB.shared.errors import iPodDBWriteError


def track_bytes(
    header_size: int = 0x154,
    *,
    payload_size: int = 0xFEDCBA9876543210,
    selector: int = 0x89ABCDEF,
) -> bytes:
    raw = bytearray(0x154)
    struct.pack_into("<Q", raw, 0xF8, payload_size)
    raw[0x13C:0x144] = b"BEFORE!!"
    struct.pack_into("<I", raw, 0x144, selector)
    raw[0x148:0x154] = b"AFTER_12BYTE"
    return itunes_database(
        dataset(
            1,
            list_chunk(
                b"mhlt",
                length_chunk(b"mhit", header_size, fields=bytes(raw[12:header_size])),
            ),
        )
    )


@pytest.mark.parametrize(
    "value", [0, 0x100000000, 0xFEDCBA9876543210, 0xFFFFFFFFFFFFFFFF]
)
def test_full_audio_pair_parses_and_edits_all_eight_bytes(value: int) -> None:
    original = track_bytes(payload_size=value)
    document = parse_iTunesDB(original)
    selected = document.find_chunks(MhitHeader)[0]
    assert selected.chunk.header.gapless_audio_payload_size == value
    assert write_iTunesDB(document) == original

    changed = document.replace_chunk(
        selected,
        replace(
            selected.chunk,
            header=replace(
                selected.chunk.header, gapless_audio_payload_size=0x123456789
            ),
        ),
    )
    expected = bytearray(original)
    struct.pack_into("<Q", expected, selected.chunk.offset + 0xF8, 0x123456789)
    assert write_iTunesDB(changed) == expected


@pytest.mark.parametrize("selector", [0, 1, 0x80000000, 0xFFFFFFFF])
def test_selector_edit_preserves_the_two_opaque_neighbors(selector: int) -> None:
    original = track_bytes(selector=selector)
    document = parse_iTunesDB(original)
    selected = document.find_chunks(MhitHeader)[0]
    assert selected.chunk.header.protected_timing_selector == selector
    assert selected.chunk.header.unk_mhit_0x13C == b"BEFORE!!"
    assert selected.chunk.header.unk_mhit_0x148 == b"AFTER_12BYTE"
    assert write_iTunesDB(document) == original
    changed = document.replace_chunk(
        selected,
        replace(
            selected.chunk,
            header=replace(selected.chunk.header, protected_timing_selector=0x12345678),
        ),
    )
    expected = bytearray(original)
    struct.pack_into("<I", expected, selected.chunk.offset + 0x144, 0x12345678)
    assert write_iTunesDB(changed) == expected


@pytest.mark.parametrize("length", [*range(0xF8, 0x100), *range(0x13C, 0x154)])
def test_short_and_partial_fields_retain_every_original_byte(length: int) -> None:
    original = track_bytes(length)
    document = parse_iTunesDB(original)
    selected = document.find_chunks(MhitHeader)[0]
    assert write_iTunesDB(document) == original
    changed = document.replace_chunk(
        selected,
        replace(selected.chunk, header=replace(selected.chunk.header, track_id=42)),
    )
    expected = bytearray(original)
    struct.pack_into("<I", expected, selected.chunk.offset + 0x10, 42)
    assert write_iTunesDB(changed) == expected


@pytest.mark.parametrize("value", [-1, 1 << 64])
def test_audio_pair_rejects_values_outside_u64(value: int) -> None:
    document = parse_iTunesDB(track_bytes())
    selected = document.find_chunks(MhitHeader)[0]
    changed = document.replace_chunk(
        selected,
        replace(
            selected.chunk,
            header=replace(selected.chunk.header, gapless_audio_payload_size=value),
        ),
    )
    with pytest.raises(iPodDBWriteError, match="gapless_audio_payload_size"):
        write_iTunesDB(changed)
