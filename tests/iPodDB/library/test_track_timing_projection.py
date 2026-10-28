"""Full-width Track projection and resource writing retain protected selectors."""

import struct
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_media_replacement import (
    replacement_media,
    replacement_source,
)

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import IPodLibrary, WriteResources


def retained_source() -> IPodLibrary:
    original = replacement_source().serialize().itunes
    selected = parse_iTunesDB(original).find_chunks(MhitHeader)[0]
    raw = bytearray(original)
    struct.pack_into("<Q", raw, selected.chunk.offset + 0xF8, 0xFEDCBA9876543210)
    raw[selected.chunk.offset + 0x13C : selected.chunk.offset + 0x144] = b"BEFORE!!"
    struct.pack_into("<I", raw, selected.chunk.offset + 0x144, 0x89ABCDEF)
    raw[selected.chunk.offset + 0x148 : selected.chunk.offset + 0x154] = b"AFTER_12BYTE"
    return IPodLibrary(bytes(raw))


def test_projection_and_metadata_edit_retain_full_pair_and_selector() -> None:
    source = retained_source()
    original = source.serialize()
    track = source.snapshot.tracks[0]
    assert track.ipod is not None
    assert track.ipod.gapless_audio_payload_size == 0xFEDCBA9876543210
    desired = replace(
        source.snapshot,
        tracks=(replace(track, title="New title"), *source.snapshot.tracks[1:]),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    header = (
        parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk.header
    )
    assert header.gapless_audio_payload_size == 0xFEDCBA9876543210
    assert header.protected_timing_selector == 0x89ABCDEF
    assert header.unk_mhit_0x13C == b"BEFORE!!"
    assert header.unk_mhit_0x148 == b"AFTER_12BYTE"
    saved = result.prepared.snapshot.tracks[0].ipod
    assert saved is not None
    assert saved.gapless_audio_payload_size == 0xFEDCBA9876543210
    assert source.serialize() == original


@pytest.mark.parametrize(
    "value", [0, 0x100000000, 0xFEDCBA9876543210, 0xFFFFFFFFFFFFFFFF]
)
def test_media_replacement_writes_and_verifies_full_pair(value: int) -> None:
    source = retained_source()
    media = replace(replacement_media(source), gapless_audio_payload_size=value)
    result = source.prepare(
        source.analyze(source.begin_draft(replace_media=(media.track_id,))),
        WriteResources(media=(media,)),
    )
    assert result.prepared is not None, result.issues
    selected = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0]
    assert (
        struct.unpack_from("<Q", result.prepared.itunes, selected.chunk.offset + 0xF8)[
            0
        ]
        == value
    )
    assert selected.chunk.header.gapless_audio_payload_size == value
    assert selected.chunk.header.protected_timing_selector == 0x89ABCDEF
    assert selected.chunk.header.unk_mhit_0x13C == b"BEFORE!!"
    assert selected.chunk.header.unk_mhit_0x148 == b"AFTER_12BYTE"
    saved = result.prepared.snapshot.tracks[0].ipod
    assert saved is not None
    assert saved.gapless_audio_payload_size == value
