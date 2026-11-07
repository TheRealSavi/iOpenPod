"""Classic 2.0.1 counter evidence uses literal offsets, independent of the schema."""

import struct
from dataclasses import replace

from tests.iPodDB.library.test_sidecar_projection import short_header_library
from tests.iPodDB.library.test_writing import library
from tests.iPodDB.sidecars.test_sidecar_readers import counts

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import IPodLibrary, WriteResources
from iPodDB.sidecars import PlaybackSidecar


def counter_library() -> IPodLibrary:
    data = bytearray(library().serialize().itunes)
    offset = parse_iTunesDB(data).find_chunks(MhitHeader)[0].chunk.offset
    # The measured firmware loads these into distinct native counters. The
    # semantic total must not be inferred from whichever field the schema names.
    struct.pack_into("<II", data, offset + 0x98, 7, 11)
    return IPodLibrary(bytes(data))


def raw_counters(data: bytes) -> tuple[int, int]:
    offset = parse_iTunesDB(data).find_chunks(MhitHeader)[0].chunk.offset
    return (
        int.from_bytes(data[offset + 0x98 : offset + 0x9C], "little"),
        int.from_bytes(data[offset + 0x9C : offset + 0xA0], "little"),
    )


def test_skip_total_projects_from_0x98_without_changing_either_counter() -> None:
    source = counter_library()
    original = source.serialize().itunes
    assert source.snapshot.tracks[0].metadata.skip_count == 7
    details = source.snapshot.tracks[0].ipod
    assert details is not None and details.secondary_skip_count == 11
    assert raw_counters(original) == (7, 11)
    assert IPodLibrary(original).serialize().itunes == original


def test_unrelated_edit_preserves_both_skip_counters() -> None:
    source = counter_library()
    original = source.serialize().itunes
    first, *rest = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, title="Renamed"), *rest))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert raw_counters(result.prepared.itunes) == (7, 11)
    assert result.prepared.snapshot.tracks[0].metadata.skip_count == 7
    assert source.serialize().itunes == original


def test_skip_total_fits_156_byte_header_without_inventing_secondary_counter() -> None:
    data = bytearray(short_header_library().serialize().itunes)
    offset = parse_iTunesDB(data).find_chunks(MhitHeader)[0].chunk.offset
    struct.pack_into("<I", data, offset + 0x98, 7)
    source = IPodLibrary(bytes(data))
    first, *rest = source.snapshot.tracks
    assert first.metadata.skip_count == 7
    assert first.ipod is not None and first.ipod.secondary_skip_count == 0
    desired = replace(
        source.snapshot,
        tracks=(replace(first, metadata=replace(first.metadata, skip_count=9)), *rest),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert saved.generic_header.header_length == 156
    assert int.from_bytes(saved.raw_header[0x98:0x9C], "little") == 9
    assert len(saved.raw_header[0x9C:0xA0]) == 0


def test_explicit_skip_total_edit_preserves_secondary_counter() -> None:
    source = counter_library()
    first, *rest = source.snapshot.tracks
    desired = replace(
        source.snapshot,
        tracks=(
            replace(first, metadata=replace(first.metadata, skip_count=23)),
            *rest,
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert raw_counters(result.prepared.itunes) == (23, 11)
    assert result.prepared.snapshot.tracks[0].metadata.skip_count == 23


def test_play_counts_delta_updates_total_and_retains_secondary_counter() -> None:
    source = counter_library()
    original = source.serialize().itunes
    sidecars = (
        PlaybackSidecar("Play Counts", counts(((0, 0, 0, 0xFFFFFFFF, 0, 2, 0),))),
    )
    loaded = source.with_sidecars(sidecars)
    assert loaded.snapshot.tracks[0].metadata.skip_count == 9
    assert loaded.with_sidecars(sidecars).snapshot == loaded.snapshot
    assert loaded.serialize().itunes == original
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert raw_counters(result.prepared.itunes) == (9, 11)
    assert (
        IPodLibrary(result.prepared.itunes).snapshot.tracks[0].metadata.skip_count == 9
    )
    assert source.serialize().itunes == original
