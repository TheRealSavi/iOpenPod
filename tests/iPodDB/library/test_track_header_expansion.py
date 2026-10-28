"""Device-authorized expansion preserves playback evidence and original bytes."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_sidecar_projection import short_header_library
from tests.iPodDB.library.test_write_artwork import COVER, RED
from tests.iPodDB.sidecars.test_sidecar_readers import counts

from iPodDB.iTunesDB.builder.build_iTunesDB import new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteResources, WriteTarget
from iPodDB.library._track_header_expansion import extension_values
from iPodDB.library._track_verification import verify_native_tracks
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.sidecars import PlaybackSidecar


@pytest.mark.parametrize(
    "version,size", [(0x13, 328), (0x19, 328), (0x2D, 504), (0x30, 624)]
)
@pytest.mark.parametrize("source_size", [156, 160, 164, 178, 179])
def test_playback_expands_only_edited_track_to_supported_extent(
    version: int, size: int, source_size: int
) -> None:
    source = short_header_library(source_size)
    original = source.serialize().itunes
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", counts()),))
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft(), WriteTarget(database_version=version)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    track = result.prepared.snapshot.tracks[0]
    assert track.play_count == 3
    assert track.metadata.skip_count == 2
    assert (
        track.metadata.last_skipped == loaded.snapshot.tracks[0].metadata.last_skipped
    )
    assert track.metadata.played
    document = parse_iTunesDB(result.prepared.itunes)
    tracks = [s.chunk for s in document.find_chunks(MhitHeader)]
    # 164 stores both skip fields; played state can still follow play count.
    expected_size = source_size if source_size >= 164 else size
    assert tracks[0].generic_header.header_length == expected_size
    assert tracks[1].generic_header.header_length == source_size
    assert tracks[0].header.db_track_id_2 == (101 if source_size < 164 else 0)
    assert tracks[0].header.not_played_flag == (2 if 164 <= source_size < 179 else 1)
    assert write_iTunesDB(document) == result.prepared.itunes
    assert source.serialize().itunes == original
    assert loaded.serialize().itunes == original


@pytest.mark.parametrize("version", [None, 0x12])
def test_absent_or_insufficient_capability_keeps_all_evidence(
    version: int | None,
) -> None:
    source = short_header_library()
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", counts()),))
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft(), WriteTarget(database_version=version)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert loaded.snapshot.tracks[0].metadata.skip_count == 2
    assert loaded.serialize() == source.serialize()


@pytest.mark.parametrize("length", [156, 328, 584, 624, 640])
def test_capability_does_not_normalize_noop_or_unrelated_edit(length: int) -> None:
    source = short_header_library(length) if length <= 624 else short_header_library()
    if length > 624:
        doc = parse_iTunesDB(source.serialize().itunes)
        for selection in doc.find_chunks(MhitHeader):
            doc = doc.replace_chunk(
                selection,
                replace(
                    selection.chunk,
                    generic_header=replace(
                        selection.chunk.generic_header, header_length=length
                    ),
                    raw_header=selection.chunk.raw_header.ljust(length, b"\0"),
                ),
            )
        source = IPodLibrary(write_iTunesDB(doc))
    target = WriteTarget(database_version=0x30)
    untouched = source.prepare(source.analyze(source.begin_draft(), target))
    assert untouched.prepared is not None, untouched.issues
    assert untouched.prepared.itunes == source.serialize().itunes
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Renamed"),
            *source.snapshot.tracks[1:],
        ),
    )
    edited = source.prepare(source.analyze(source.begin_draft(desired), target))
    assert edited.prepared is not None, edited.issues
    assert all(
        s.chunk.generic_header.header_length == length
        for s in parse_iTunesDB(edited.prepared.itunes).find_chunks(MhitHeader)
    )


@pytest.mark.parametrize("length", [158, 162, 170, 249, 252, 255, 325, 327])
def test_numeric_partial_fields_block_expansion(length: int) -> None:
    source = short_header_library(length)
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                track,
                metadata=replace(track.metadata, composer="Requires expanded header"),
            ),
            *source.snapshot.tracks[1:],
        ),
    )
    loaded = source
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft(desired), WriteTarget(database_version=0x30))
    )
    assert result.prepared is None
    assert any("numeric field" in issue.message for issue in result.issues)
    assert loaded.serialize() == source.serialize()


def test_expansion_policy_preserves_partial_opaque_field() -> None:
    source = short_header_library(332)
    doc = parse_iTunesDB(source.serialize().itunes)
    selection = doc.find_chunks(MhitHeader)[0]
    raw = bytearray(selection.chunk.raw_header)
    field = next(
        f.schema
        for f in binary_fields(MhitHeader)
        if f.attribute_name == "unk_mhit_0x148"
    )
    raw[field.offset : 332] = b"tail"
    chunk = replace(selection.chunk, raw_header=bytes(raw))
    seeds = extension_values(chunk, source.snapshot.tracks[0], 624)
    assert seeds["unk_mhit_0x148"] == b"tail" + bytes(8)
    opaque = seeds["unk_mhit_0x148"]
    assert isinstance(opaque, bytes)
    extended = replace(
        chunk,
        header=replace(chunk.header, unk_mhit_0x148=opaque),
        raw_header=chunk.raw_header.ljust(624, b"\0"),
        generic_header=replace(chunk.generic_header, header_length=624),
    )
    output = parse_iTunesDB(write_iTunesDB(doc.replace_chunk(selection, extended)))
    actual = output.find_chunks(MhitHeader)[0].chunk
    assert actual.raw_header[field.offset : 332] == b"tail"
    assert actual.header.unk_mhit_0x148 == b"tail" + bytes(8)


@pytest.mark.parametrize("version,expected", [(0x12, 0x30), (0x75, 0x75)])
def test_expansion_raises_old_database_version_without_downgrading(
    version: int, expected: int
) -> None:
    doc = parse_iTunesDB(short_header_library().serialize().itunes)
    source = IPodLibrary(
        write_iTunesDB(replace(doc, header=replace(doc.header, version=version)))
    )
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", counts()),))
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft(), WriteTarget(database_version=0x30)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert parse_iTunesDB(result.prepared.itunes).header.version == expected


def test_verifier_rejects_corrupted_expansion_identity_and_extent() -> None:
    source = short_header_library()
    original = parse_iTunesDB(source.serialize().itunes)
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", counts()),))
    target = WriteTarget(database_version=0x30)
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft(), target),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    good = parse_iTunesDB(result.prepared.itunes)
    selection = good.find_chunks(MhitHeader)[0]
    bad = good.replace_chunk(
        selection,
        replace(
            selection.chunk,
            header=replace(selection.chunk.header, db_track_id_2=999),
            generic_header=replace(selection.chunk.generic_header, header_length=625),
        ),
    )
    issues = verify_native_tracks(
        original,
        bad,
        source.snapshot,
        loaded.snapshot,
        (),
        WriteResources(),
        database_version=0x30,
    )
    assert {issue.field for issue in issues} >= {"db_track_id_2", "header_length"}


def test_expansion_retains_unknown_bytes_children_and_float_representation() -> None:
    doc = parse_iTunesDB(short_header_library().serialize().itunes)
    selection = doc.find_chunks(MhitHeader)[0]
    schemas = {f.attribute_name: f.schema for f in binary_fields(MhitHeader)}
    raw = bytearray(selection.chunk.raw_header)
    reserved = schemas["unk_mhit_0x84"]
    raw[reserved.offset : reserved.offset + reserved.size] = b"KEEP"
    floating = schemas["sample_rate_2"]
    # Quiet NaN with a noncanonical payload: equality alone cannot verify this.
    raw[floating.offset : floating.offset + floating.size] = b"\x34\x12\xc0\x7f"
    doc = doc.replace_chunk(selection, replace(selection.chunk, raw_header=bytes(raw)))
    # Parse the patched fixture so its typed diagnostics describe its raw bytes.
    encoded = bytearray(write_iTunesDB(doc))
    encoded[
        selection.chunk.offset + reserved.offset : selection.chunk.offset
        + reserved.offset
        + reserved.size
    ] = b"KEEP"
    encoded[
        selection.chunk.offset + floating.offset : selection.chunk.offset
        + floating.offset
        + floating.size
    ] = b"\x34\x12\xc0\x7f"
    source = IPodLibrary(bytes(encoded) + b"opaque suffix")
    original = parse_iTunesDB(source.serialize().itunes)
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", counts()),))
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft(), WriteTarget(database_version=0x30)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    old_tracks = [s.chunk for s in original.find_chunks(MhitHeader)]
    new_tracks = [s.chunk for s in checked.find_chunks(MhitHeader)]
    assert new_tracks[0].raw_body == old_tracks[0].raw_body
    assert new_tracks[1].raw_header == old_tracks[1].raw_header
    assert new_tracks[1].raw_body == old_tracks[1].raw_body
    changed_fields = {
        "rating",
        "play_count_1",
        "play_count_2",
        "last_played",
        "bookmark_time",
        "skip_count",
    }
    allowed = {
        i
        for name in changed_fields
        for i in range(schemas[name].offset, schemas[name].offset + schemas[name].size)
    } | set(range(4, 12))
    assert all(
        old == new_tracks[0].raw_header[i]
        for i, old in enumerate(old_tracks[0].raw_header)
        if i not in allowed
    )
    assert checked.raw_source_suffix == b"opaque suffix"
    assert checked.children[-1].raw_body == original.children[-1].raw_body
    assert write_iTunesDB(checked) == result.prepared.itunes


@pytest.mark.parametrize("action", ["set", "clear", "rename"])
def test_expanding_partial_sort_indicators_retains_unknown_flag_bits(
    action: str,
) -> None:
    doc = parse_iTunesDB(short_header_library(310).serialize().itunes)
    selected = doc.find_chunks(MhitHeader)[0]
    raw = bytearray(selected.chunk.raw_header)
    schema = next(
        f.schema
        for f in binary_fields(MhitHeader)
        if f.attribute_name == "sort_mhod_indicators"
    )
    raw[schema.offset : 310] = b"\x01\x00" if action != "set" else b"\x80\x40"
    chunk = replace(selected.chunk, raw_header=bytes(raw))
    if action != "set":
        chunk = chunk.append_child(
            new_string_mhod(MhodType.SORT_TITLE, "Original sorting")
        )
    doc = doc.replace_chunk(selected, chunk)
    source = IPodLibrary(write_iTunesDB(doc))
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                track,
                metadata=replace(
                    track.metadata, sort_title="" if action == "clear" else "Sort title"
                ),
            ),
            *source.snapshot.tracks[1:],
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), WriteTarget(database_version=0x30))
    )
    assert result.prepared is not None, result.issues
    actual = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert actual.generic_header.header_length == (310 if action == "rename" else 624)
    if action == "rename":
        assert actual.raw_header[schema.offset : 310] == b"\x01\x00"
    else:
        assert actual.header.sort_mhod_indicators == (
            bytes(8) if action == "clear" else b"\x81\x40" + bytes(6)
        )
    without_capability = source.prepare(source.analyze(source.begin_draft(desired)))
    assert (without_capability.prepared is not None) == (action == "rename")
    assert source.serialize().itunes == write_iTunesDB(doc)


def test_expansion_and_artwork_change_verify_the_requested_artwork() -> None:
    source = short_header_library()
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                track, artwork_id=-1, metadata=replace(track.metadata, skip_count=2)
            ),
            *source.snapshot.tracks[1:],
        ),
    )
    target = WriteTarget(
        database_version=0x30, cover_formats=(COVER,), artwork_root_value=2
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared is not None, result.issues
    actual = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert actual.generic_header.header_length == 624
    assert actual.header.skip_count == 2
    assert actual.header.has_artwork == 1
    assert result.prepared.snapshot.tracks[0].artwork_id > 0


def test_expansion_retains_played_state_when_clearing_the_play_count() -> None:
    doc = parse_iTunesDB(short_header_library().serialize().itunes)
    selected = doc.find_chunks(MhitHeader)[0]
    doc = doc.replace_chunk(
        selected,
        replace(selected.chunk, header=replace(selected.chunk.header, play_count_1=3)),
    )
    source = IPodLibrary(write_iTunesDB(doc))
    track = source.snapshot.tracks[0]
    assert track.metadata.played
    desired = replace(
        source.snapshot,
        tracks=(replace(track, play_count=0), *source.snapshot.tracks[1:]),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), WriteTarget(database_version=0x30))
    )
    assert result.prepared is not None, result.issues
    actual = result.prepared.snapshot.tracks[0]
    assert actual.play_count == 0
    assert actual.metadata.played
