"""Timed artwork stays explicit while ordinary covers retain their zero group."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_artwork_native_verification import ArtworkResult
from tests.iPodDB.library.test_write_artwork import (
    BLUE,
    COVER,
    RED,
    TARGET,
    with_shared_artwork,
)
from tests.iPodDB.library.test_writing import library

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import (
    ArtworkAsset,
    ArtworkGroupReference,
    FileDependency,
    IPodLibrary,
    PreparedFile,
    PreparedLibrary,
    SourceFile,
    TimedArtworkAsset,
    TimedArtworkFrame,
    WriteResources,
)
from iPodDB.library import _write_preparation as preparation
from iPodDB.library._artwork_writing import reconcile_artwork
from iPodDB.library.file_content import content_sha256, read_content

TIMED_TARGET = replace(
    TARGET,
    cover_formats=(
        COVER,
        replace(COVER, format_id=1056, width=2, height=2, row_bytes=4),
    ),
)


def test_exact_time_read_and_metadata_preserve_raw_time_keys() -> None:
    source, _ = with_shared_artwork()
    original = source.serialize()
    document = parse_ArtworkDB(original.artwork or b"")
    item = document.find_chunks(MhiiHeader)[0]
    wrapper = item.chunk.children[0]
    assert isinstance(wrapper.payload, MhodContainerPayload)
    location = wrapper.payload.child
    later = replace(
        wrapper,
        payload=replace(
            wrapper.payload,
            child=replace(
                location,
                header=replace(location.header, unk_mhni_0x24=10000, ithmb_offset=32),
            ),
        ),
    )
    document = document.replace_chunk(
        item, replace(item.chunk, children=(later, *item.chunk.children))
    )
    encoded = write_ArtworkDB(document)
    loaded = IPodLibrary(original.itunes).with_artwork(encoded)
    artwork_id = loaded.snapshot.tracks[0].artwork_id
    assert loaded.artwork_display_times(artwork_id) == (0, 10000)
    default = loaded.artwork_read(artwork_id, (COVER,), 4)
    exact = loaded.artwork_read(artwork_id, (COVER,), 4, display_time_ms=10000)
    assert default is not None and default.offset == 0
    assert exact is not None and exact.offset == 32
    assert loaded.artwork_read(artwork_id, (COVER,), 4, display_time_ms=1) is None
    assert loaded.serialize().artwork == encoded


def test_authored_timeline_serializes_sorted_complete_groups_and_reads_each() -> None:
    source = library()
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-1) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TIMED_TARGET),
        WriteResources(
            artwork=(
                TimedArtworkAsset(
                    -1,
                    (
                        TimedArtworkFrame(10000, BLUE.pixels),
                        TimedArtworkFrame(0, RED.pixels),
                    ),
                ),
            ),
            file_inventory=(),
        ),
    )
    assert result.prepared is not None, result.issues
    prepared = result.prepared
    loaded = IPodLibrary(prepared.itunes).with_artwork(prepared.artwork or b"")
    identity = loaded.snapshot.tracks[0].artwork_id
    assert loaded.artwork_display_times(identity) == (0, 10000)
    document = parse_ArtworkDB(prepared.artwork or b"")
    row = next(
        s.chunk
        for s in document.find_chunks(MhiiHeader)
        if s.chunk.header.image_id == identity
    )
    assert [
        c.payload.child.header.unk_mhni_0x24
        for c in row.children
        if isinstance(c.payload, MhodContainerPayload)
    ] == [0, 0, 10000, 10000]
    assert [
        c.payload.child.header.format_id
        for c in row.children
        if isinstance(c.payload, MhodContainerPayload)
    ] == [1055, 1056, 1055, 1056]
    for time, channel in ((0, 0), (10000, 2)):
        read = loaded.artwork_read(identity, (COVER,), 4, display_time_ms=time)
        assert read is not None
        output = next(
            f for f in prepared.artwork_files if f.relative_path == read.relative_path
        )
        assert (
            read.decode(read_content(output.data, read.offset, read.length)).rgb888[
                channel
            ]
            > 240
        )


def _prepare(
    source: IPodLibrary,
    asset: ArtworkAsset | TimedArtworkAsset,
    files: tuple[PreparedFile, ...] = (),
) -> PreparedLibrary:
    resources = timed_resources(asset, files)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, artwork_id=asset.artwork_id) for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), resources
    )
    assert result.prepared is not None, result.issues
    return result.prepared


def timed_resources(
    asset: ArtworkAsset | TimedArtworkAsset, files: tuple[PreparedFile, ...]
) -> WriteResources:
    dependencies = tuple(
        FileDependency(f.relative_path, len(f.data), content_sha256(f.data))
        for f in files
    )
    return WriteResources(
        artwork=(asset,),
        file_inventory=dependencies,
        files=tuple(
            SourceFile(d, f.data) for d, f in zip(dependencies, files, strict=True)
        ),
    )


def timeline(*, special: bool = False) -> tuple[IPodLibrary, tuple[PreparedFile, ...]]:
    prepared = _prepare(
        library(),
        TimedArtworkAsset(
            -1,
            (TimedArtworkFrame(0, RED.pixels), TimedArtworkFrame(10000, BLUE.pixels)),
        ),
    )
    data = bytearray(prepared.artwork or b"")
    document = parse_ArtworkDB(data)
    row = document.find_chunks(MhiiHeader)[0].chunk
    for child in row.children:
        if (
            isinstance(child.payload, MhodContainerPayload)
            and child.payload.child.header.unk_mhni_0x24 == 10000
        ):
            offset = child.payload.child.offset
            # Independent wire fixture: unknown MHNI bytes must survive edits.
            data[offset + 0x30 : offset + 0x34] = b"KEEP"
            if special:
                data[offset + 0x24 : offset + 0x28] = b"\xff" * 4
    return IPodLibrary(prepared.itunes).with_artwork(
        bytes(data)
    ), prepared.artwork_files


def group_bytes(data: bytes, identity: int, time: int) -> tuple[bytes, ...]:
    document = parse_ArtworkDB(data)
    row = next(
        s.chunk
        for s in document.find_chunks(MhiiHeader)
        if s.chunk.header.image_id == identity
    )
    return tuple(
        data[c.offset : c.offset + c.generic_header.length_or_child_count]
        for c in row.children
        if isinstance(c.payload, MhodContainerPayload)
        and c.payload.child.header.unk_mhni_0x24 == time
    )


@pytest.mark.parametrize("special", [False, True])
def test_legacy_cover_refresh_retains_later_group_bytes_and_ranges(
    special: bool,
) -> None:
    source, files = timeline(special=special)
    old_id = source.snapshot.tracks[0].artwork_id
    time = 0xFFFFFFFF if special else 10000
    original_group = group_bytes(source.serialize().artwork or b"", old_id, time)
    prepared = _prepare(source, BLUE, files)
    new_id = prepared.snapshot.tracks[0].artwork_id
    assert group_bytes(prepared.artwork or b"", new_id, time) == original_group
    loaded = IPodLibrary(prepared.itunes).with_artwork(prepared.artwork or b"")
    assert loaded.artwork_display_times(new_id) == (0, time)
    assert (
        read_content(prepared.artwork_files[0].data, 0, len(files[0].data))
        == files[0].data
    )


def test_reference_retime_and_remove_leave_pixel_files_unchanged() -> None:
    source, files = timeline()
    identity = source.snapshot.tracks[0].artwork_id
    asset = TimedArtworkAsset(
        -2,
        (
            TimedArtworkFrame(5000, ArtworkGroupReference(identity, 10000)),
            TimedArtworkFrame(0, ArtworkGroupReference(identity, 0)),
        ),
    )
    prepared = _prepare(source, asset, files)
    assert prepared.artwork_files == ()
    loaded = IPodLibrary(prepared.itunes).with_artwork(prepared.artwork or b"")
    new_id = loaded.snapshot.tracks[0].artwork_id
    assert loaded.artwork_display_times(new_id) == (0, 5000)
    read = loaded.artwork_read(new_id, (COVER,), 4, display_time_ms=5000)
    assert read is not None and read.offset == 32
    expected = bytearray(
        group_bytes(source.serialize().artwork or b"", identity, 10000)[0]
    )
    # MHOD header is 24 bytes, followed by MHNI; only its time field changes.
    expected[24 + 0x24 : 24 + 0x28] = (5000).to_bytes(4, "little")
    assert group_bytes(prepared.artwork or b"", new_id, 5000) == (bytes(expected),)
    removed = _prepare(
        loaded,
        TimedArtworkAsset(
            -3, (TimedArtworkFrame(0, ArtworkGroupReference(new_id, 0)),)
        ),
        files,
    )
    assert IPodLibrary(removed.itunes).with_artwork(
        removed.artwork or b""
    ).artwork_display_times(removed.snapshot.tracks[0].artwork_id) == (0,)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("failure", ["missing", "truncated", "unavailable"])
def test_retained_groups_cannot_authorize_regeneration_without_complete_shards(
    legacy: bool, failure: str
) -> None:
    source, files = timeline(special=True)
    identity = source.snapshot.tracks[0].artwork_id
    asset = (
        BLUE
        if legacy
        else TimedArtworkAsset(
            -2,
            (
                TimedArtworkFrame(0, BLUE.pixels),
                TimedArtworkFrame(
                    0xFFFFFFFF, ArtworkGroupReference(identity, 0xFFFFFFFF)
                ),
            ),
        )
    )
    resources = timed_resources(asset, files)
    if failure == "missing":
        resources = replace(resources, files=(), file_inventory=())
    elif failure == "truncated":
        resources = replace(
            resources,
            file_inventory=(replace(resources.file_inventory[0], size=32),)
            if resources.file_inventory
            else (),
        )
    else:
        resources = replace(resources, reserved_artwork_paths=(files[0].relative_path,))
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-2) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), resources
    )
    assert result.prepared is None
    assert any(
        "range" in str(issue) or "captured" in str(issue) for issue in result.issues
    )


def test_explicit_all_pixel_sequence_can_replace_damaged_source_timeline() -> None:
    source, files = timeline(special=True)
    prepared = _prepare(
        source, TimedArtworkAsset(-2, (TimedArtworkFrame(0, BLUE.pixels),))
    )
    assert prepared.artwork_files[0].relative_path != files[0].relative_path
    assert IPodLibrary(prepared.itunes).with_artwork(
        prepared.artwork or b""
    ).artwork_display_times(prepared.snapshot.tracks[0].artwork_id) == (0,)


@pytest.mark.parametrize(
    "times", [(), (1,), (0, 0), (-1, 0), (0, 0x100000000), (0, 0xFFFFFFFF)]
)
def test_authored_timeline_rejects_invalid_times(times: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        TimedArtworkAsset(-1, tuple(TimedArtworkFrame(t, RED.pixels) for t in times))


def test_special_time_may_only_be_referenced_at_its_existing_time() -> None:
    reference = ArtworkGroupReference(100, 0xFFFFFFFF)
    assert TimedArtworkFrame(0xFFFFFFFF, reference).source == reference
    with pytest.raises(ValueError):
        TimedArtworkFrame(0, reference)
    with pytest.raises(ValueError):
        TimedArtworkFrame(0xFFFFFFFF, ArtworkGroupReference(100, 0))


def test_shared_legacy_refresh_rejects_different_existing_timelines() -> None:
    source, files = timeline()
    identity = source.snapshot.tracks[0].artwork_id
    first, second = source.snapshot.tracks
    asset = TimedArtworkAsset(
        -2,
        (
            TimedArtworkFrame(0, ArtworkGroupReference(identity, 0)),
            TimedArtworkFrame(5000, ArtworkGroupReference(identity, 10000)),
        ),
    )
    draft = replace(source.snapshot, tracks=(replace(first, artwork_id=-2), second))
    result = source.prepare(
        source.analyze(source.begin_draft(draft), TARGET), timed_resources(asset, files)
    )
    assert result.prepared is not None, result.issues
    loaded = IPodLibrary(result.prepared.itunes).with_artwork(
        result.prepared.artwork or b""
    )
    draft = replace(
        loaded.snapshot,
        tracks=tuple(replace(t, artwork_id=-1) for t in loaded.snapshot.tracks),
    )
    ambiguous = loaded.prepare(
        loaded.analyze(loaded.begin_draft(draft), TARGET), timed_resources(RED, files)
    )
    assert ambiguous.prepared is None
    assert any("different retained timelines" in str(i) for i in ambiguous.issues)


def test_shared_legacy_refresh_accepts_separate_clones_of_same_timeline() -> None:
    source, files = timeline()
    identity = source.snapshot.tracks[0].artwork_id
    first, second = source.snapshot.tracks
    asset = TimedArtworkAsset(
        -2,
        (
            TimedArtworkFrame(0, ArtworkGroupReference(identity, 0)),
            TimedArtworkFrame(10000, ArtworkGroupReference(identity, 10000)),
        ),
    )
    draft = replace(source.snapshot, tracks=(replace(first, artwork_id=-2), second))
    result = source.prepare(
        source.analyze(source.begin_draft(draft), TARGET), timed_resources(asset, files)
    )
    assert result.prepared is not None, result.issues
    loaded = IPodLibrary(result.prepared.itunes).with_artwork(
        result.prepared.artwork or b""
    )
    prepared = _prepare(loaded, RED, files)
    assert (
        prepared.snapshot.tracks[0].artwork_id == prepared.snapshot.tracks[1].artwork_id
    )


def corrupt_timed[**P](
    method: Callable[P, ArtworkResult], mode: str
) -> Callable[P, ArtworkResult]:
    def corrupt(*args: P.args, **kwargs: P.kwargs) -> ArtworkResult:
        itunes, artwork, files, identities = method(*args, **kwargs)
        assert artwork is not None
        selection = artwork.find_chunks(MhiiHeader)[-1]
        row = selection.chunk
        children = list(row.children)
        if mode == "order":
            children[0], children[1] = children[1], children[0]
        elif mode == "duplicate":
            children.insert(1, children[0])
        elif mode == "missing":
            children.pop(1)
        else:
            wrapper = children[1]
            payload = wrapper.payload
            assert isinstance(payload, MhodContainerPayload)
            location = payload.child
            if mode == "time":
                location = replace(
                    location, header=replace(location.header, unk_mhni_0x24=9999)
                )
            else:
                location = replace(
                    location,
                    raw_header=location.raw_header[:-1]
                    + bytes([location.raw_header[-1] ^ 255]),
                )
            children[1] = replace(wrapper, payload=replace(payload, child=location))
        artwork = artwork.replace_chunk(
            selection, replace(row, children=tuple(children))
        )
        return itunes, artwork, files, identities

    return corrupt


@pytest.mark.parametrize(
    "mode", ["order", "duplicate", "missing", "time", "reference_unknown"]
)
def test_corrupt_prepared_timeline_is_withheld(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    source, files = timeline()
    identity = source.snapshot.tracks[0].artwork_id
    asset = TimedArtworkAsset(
        -2,
        (
            TimedArtworkFrame(0, RED.pixels),
            TimedArtworkFrame(10000, ArtworkGroupReference(identity, 10000)),
        ),
    )
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-2) for t in source.snapshot.tracks),
    )
    plan = source.analyze(source.begin_draft(desired), TARGET)
    resources = timed_resources(asset, files)
    assert source.prepare(plan, resources).prepared is not None
    monkeypatch.setattr(
        preparation, "reconcile_artwork", corrupt_timed(reconcile_artwork, mode)
    )
    result = source.prepare(plan, resources)
    assert result.prepared is None
    assert any(i.code == "verification.failed" for i in result.issues)


def test_timed_frames_roll_over_shards_and_preserve_captured_prefixes() -> None:
    target = replace(TIMED_TARGET, max_artwork_file_bytes=64)
    source = library()
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-1) for t in source.snapshot.tracks),
    )
    seeded = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        timed_resources(RED, ()),
    )
    assert seeded.prepared is not None, seeded.issues
    source = IPodLibrary(seeded.prepared.itunes).with_artwork(
        seeded.prepared.artwork or b""
    )
    green = replace(RED.pixels, rgb888=bytes((0, 255, 0)) * 16)
    asset = TimedArtworkAsset(
        -2,
        (
            TimedArtworkFrame(10000, green),
            TimedArtworkFrame(0, RED.pixels),
            TimedArtworkFrame(5000, BLUE.pixels),
        ),
    )
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-2) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        timed_resources(asset, seeded.prepared.artwork_files),
    )
    assert result.prepared is not None, result.issues
    prepared = result.prepared
    outputs = {f.relative_path: f.data for f in prepared.artwork_files}
    assert set(outputs) == {
        "iPod_Control/Artwork/F1055_1.ithmb",
        "iPod_Control/Artwork/F1055_2.ithmb",
        "iPod_Control/Artwork/F1056_1.ithmb",
    }
    assert all(len(data) <= 64 for data in outputs.values())
    for retained in seeded.prepared.artwork_files:
        assert read_content(
            outputs[retained.relative_path], 0, len(retained.data)
        ) == read_content(retained.data, 0, len(retained.data))
    loaded = IPodLibrary(prepared.itunes).with_artwork(prepared.artwork or b"")
    identity = loaded.snapshot.tracks[0].artwork_id
    row = next(
        s.chunk
        for s in parse_ArtworkDB(prepared.artwork or b"").find_chunks(MhiiHeader)
        if s.chunk.header.image_id == identity
    )
    assert [
        (c.payload.child.header.unk_mhni_0x24, c.payload.child.header.format_id)
        for c in row.children
        if isinstance(c.payload, MhodContainerPayload)
    ] == [
        (0, 1055),
        (0, 1056),
        (5000, 1055),
        (5000, 1056),
        (10000, 1055),
        (10000, 1056),
    ]
    for time, channel, shard, offset in (
        (0, 0, 1, 32),
        (5000, 2, 2, 0),
        (10000, 1, 2, 32),
    ):
        for cover in target.cover_formats:
            read = loaded.artwork_read(identity, (cover,), 4, display_time_ms=time)
            assert read is not None
            if cover.format_id == 1055:
                assert read.relative_path == f"iPod_Control/Artwork/F1055_{shard}.ithmb"
                assert read.offset == offset
            image = read.decode(
                read_content(outputs[read.relative_path], read.offset, read.length)
            )
            assert image.rgb888[channel] > 240
