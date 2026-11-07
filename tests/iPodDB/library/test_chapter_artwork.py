"""Chapter representations and source-image counts in explicitly edited timelines."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_artwork_native_verification import ArtworkResult
from tests.iPodDB.library.test_timed_artwork import (
    corrupt_timed,
    group_bytes,
    timed_resources,
    timeline,
)
from tests.iPodDB.library.test_write_artwork import BLUE, COVER, RED, TARGET
from tests.iPodDB.library.test_writing import library

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import (
    ArtworkAsset,
    ArtworkGroupReference,
    CoverPixelFormat,
    IPodLibrary,
    PreparedFile,
    PreparedLibrary,
    TimedArtworkAsset,
    TimedArtworkFrame,
    WriteTarget,
)
from iPodDB.library import _write_preparation as preparation
from iPodDB.library._artwork_timing import checked_artwork_count
from iPodDB.library._artwork_writing import reconcile_artwork
from iPodDB.library.file_content import read_content

CHAPTER = replace(COVER, format_id=1029, width=2, height=2, row_bytes=4)
CHAPTER_TARGET = replace(TARGET, chapter_formats=(COVER, CHAPTER))


def _edit(
    source: IPodLibrary,
    asset: ArtworkAsset | TimedArtworkAsset,
    files: tuple[PreparedFile, ...] = (),
    target: WriteTarget = CHAPTER_TARGET,
) -> PreparedLibrary:
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, artwork_id=asset.artwork_id) for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        timed_resources(asset, files),
    )
    assert result.prepared is not None, result.issues
    return result.prepared


def _counts(data: bytes) -> list[int]:
    return [
        s.chunk.header.artwork_count
        for s in parse_iTunesDB(data).find_chunks(MhitHeader)
    ]


def test_track_count_counts_time_groups_instead_of_representations() -> None:
    source, _ = timeline()
    headers = parse_iTunesDB(source.serialize().itunes).find_chunks(MhitHeader)
    assert [s.chunk.header.artwork_count for s in headers] == [2, 2]


def test_explicit_timeline_adds_deduplicated_chapter_formats() -> None:
    source = library()
    chapter = replace(COVER, format_id=1029, width=2, height=2, row_bytes=4)
    target = replace(TARGET, chapter_formats=(COVER, chapter))
    asset = TimedArtworkAsset(
        -1, (TimedArtworkFrame(15000, BLUE.pixels), TimedArtworkFrame(0, RED.pixels))
    )
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-1) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target), timed_resources(asset, ())
    )
    assert result.prepared is not None, result.issues
    row = (
        parse_ArtworkDB(result.prepared.artwork or b"").find_chunks(MhiiHeader)[0].chunk
    )
    assert [
        (c.payload.child.header.image_time_key, c.payload.child.header.format_id)
        for c in row.children
        if isinstance(c.payload, MhodContainerPayload)
    ] == [(0, 1055), (0, 1029), (15000, 1055), (15000, 1029)]
    assert [
        s.chunk.header.artwork_count
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    ] == [2, 2]


def test_retained_time_groups_gain_missing_chapter_layout_without_rewriting_ranges() -> (
    None
):
    source, files = timeline()
    original = source.serialize().artwork or b""
    identity = source.snapshot.tracks[0].artwork_id
    chapter = replace(COVER, format_id=1029, width=2, height=2, row_bytes=4)
    target = replace(TARGET, chapter_formats=(COVER, chapter))
    asset = TimedArtworkAsset(
        -2,
        tuple(
            TimedArtworkFrame(time, ArtworkGroupReference(identity, time))
            for time in (0, 10000)
        ),
    )
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-2) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        timed_resources(asset, files),
    )
    assert result.prepared is not None, result.issues
    prepared = result.prepared
    assert [f.relative_path for f in prepared.artwork_files] == [
        "iPod_Control/Artwork/F1029_1.ithmb"
    ]
    loaded = IPodLibrary(prepared.itunes).with_artwork(prepared.artwork or b"")
    new_id = loaded.snapshot.tracks[0].artwork_id
    for time, channel in ((0, 0), (10000, 2)):
        assert (
            group_bytes(prepared.artwork or b"", new_id, time)[0]
            == group_bytes(original, identity, time)[0]
        )
        read = loaded.artwork_read(new_id, (chapter,), 2, display_time_ms=time)
        assert read is not None
        assert (
            read.decode(
                read_content(prepared.artwork_files[0].data, read.offset, read.length)
            ).rgb888[channel]
            > 240
        )


def test_ordinary_new_cover_uses_only_cover_formats_and_count_one() -> None:
    prepared = _edit(library(), RED)
    assert _counts(prepared.itunes) == [1, 1]
    assert [f.relative_path for f in prepared.artwork_files] == [
        "iPod_Control/Artwork/F1055_1.ithmb"
    ]


def test_shared_cover_refresh_rejects_different_existing_zero_formats() -> None:
    initial = _edit(library(), RED)
    source = IPodLibrary(initial.itunes).with_artwork(initial.artwork or b"")
    first, second = source.snapshot.tracks
    asset = TimedArtworkAsset(
        -2, (TimedArtworkFrame(0, ArtworkGroupReference(first.artwork_id, 0)),)
    )
    desired = replace(source.snapshot, tracks=(replace(first, artwork_id=-2), second))
    result = source.prepare(
        source.analyze(source.begin_draft(desired), CHAPTER_TARGET),
        timed_resources(asset, initial.artwork_files),
    )
    assert result.prepared is not None, result.issues
    completed = result.prepared
    source = IPodLibrary(completed.itunes).with_artwork(completed.artwork or b"")
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(track, artwork_id=-1) for track in source.snapshot.tracks),
    )
    rejected = source.prepare(
        source.analyze(source.begin_draft(desired), CHAPTER_TARGET),
        timed_resources(RED, (*initial.artwork_files, *completed.artwork_files)),
    )
    assert rejected.prepared is None
    assert any(
        "different existing zero-time formats" in str(i) for i in rejected.issues
    )


def test_ordinary_refresh_updates_existing_zero_chapter_representation() -> None:
    first = _edit(
        library(),
        TimedArtworkAsset(
            -1,
            (TimedArtworkFrame(0, RED.pixels), TimedArtworkFrame(15000, BLUE.pixels)),
        ),
    )
    source = IPodLibrary(first.itunes).with_artwork(first.artwork or b"")
    old_id = source.snapshot.tracks[0].artwork_id
    refreshed = _edit(source, BLUE, first.artwork_files)
    new_id = refreshed.snapshot.tracks[0].artwork_id
    assert _counts(refreshed.itunes) == [2, 2]
    assert group_bytes(refreshed.artwork or b"", new_id, 15000) == group_bytes(
        first.artwork or b"", old_id, 15000
    )
    loaded = IPodLibrary(refreshed.itunes).with_artwork(refreshed.artwork or b"")
    read = loaded.artwork_read(new_id, (CHAPTER,), 2, display_time_ms=0)
    assert read is not None
    output = next(
        f for f in refreshed.artwork_files if f.relative_path == read.relative_path
    )
    assert (
        read.decode(read_content(output.data, read.offset, read.length)).rgb888[2] > 240
    )


def test_special_group_is_counted_and_retained_without_new_chapter_representation() -> (
    None
):
    source, files = timeline(special=True)
    old_id = source.snapshot.tracks[0].artwork_id
    asset = TimedArtworkAsset(
        -2,
        (
            TimedArtworkFrame(0, ArtworkGroupReference(old_id, 0)),
            TimedArtworkFrame(0xFFFFFFFF, ArtworkGroupReference(old_id, 0xFFFFFFFF)),
        ),
    )
    prepared = _edit(source, asset, files)
    assert _counts(prepared.itunes) == [2, 2]
    assert group_bytes(
        prepared.artwork or b"", prepared.snapshot.tracks[0].artwork_id, 0xFFFFFFFF
    ) == group_bytes(source.serialize().artwork or b"", old_id, 0xFFFFFFFF)
    assert len(prepared.artwork_files[0].data) == 8


def test_count_decreases_when_removing_a_group_and_clears_with_artwork() -> None:
    source, files = timeline()
    old_id = source.snapshot.tracks[0].artwork_id
    prepared = _edit(
        source,
        TimedArtworkAsset(
            -2, (TimedArtworkFrame(0, ArtworkGroupReference(old_id, 0)),)
        ),
        files,
    )
    assert _counts(prepared.itunes) == [1, 1]
    loaded = IPodLibrary(prepared.itunes).with_artwork(prepared.artwork or b"")
    desired = replace(
        loaded.snapshot,
        tracks=tuple(replace(t, artwork_id=0) for t in loaded.snapshot.tracks),
    )
    cleared = loaded.prepare(
        loaded.analyze(loaded.begin_draft(desired), CHAPTER_TARGET)
    )
    assert cleared.prepared is not None, cleared.issues
    assert _counts(cleared.prepared.itunes) == [0, 0]


def test_noop_does_not_add_chapter_formats_or_normalize_retained_count() -> None:
    source, _ = timeline()
    original = source.serialize()
    raw = bytearray(original.itunes)
    for selection in parse_iTunesDB(original.itunes).find_chunks(MhitHeader):
        raw[selection.chunk.offset + 0x7C : selection.chunk.offset + 0x7E] = b"\x01\x00"
    loaded = IPodLibrary(bytes(raw)).with_artwork(original.artwork or b"")
    result = loaded.prepare(loaded.analyze(loaded.begin_draft(), CHAPTER_TARGET))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == bytes(raw)
    assert result.prepared.artwork == original.artwork
    assert result.prepared.artwork_files == ()


def test_missing_source_bytes_cannot_complete_a_retained_group() -> None:
    source, files = timeline()
    identity = source.snapshot.tracks[0].artwork_id
    asset = TimedArtworkAsset(
        -2, (TimedArtworkFrame(0, ArtworkGroupReference(identity, 0)),)
    )
    resources = replace(timed_resources(asset, files), files=())
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-2) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), CHAPTER_TARGET), resources
    )
    assert result.prepared is None
    assert any("decodable retained representation" in str(i) for i in result.issues)


@pytest.mark.parametrize("count", [0, 1, 2, 0xFFFF])
def test_artwork_count_accepts_u16_values(count: int) -> None:
    assert checked_artwork_count(count) == count


@pytest.mark.parametrize("count", [-1, 0x10000])
def test_artwork_count_rejects_overflow(count: int) -> None:
    with pytest.raises(ValueError, match="16-bit"):
        checked_artwork_count(count)


@pytest.mark.parametrize("corrupt_largest", [False, True])
def test_completion_uses_largest_decodable_retained_representation(
    corrupt_largest: bool,
) -> None:
    small = replace(COVER, width=2, height=2, row_bytes=4)
    large = replace(
        COVER, format_id=1060, row_bytes=0, pixel_format=CoverPixelFormat.JPEG
    )
    target = replace(TARGET, cover_formats=(small, large), chapter_formats=(CHAPTER,))
    seeded = _edit(library(), BLUE, target=target)
    source = IPodLibrary(seeded.itunes).with_artwork(seeded.artwork or b"")
    files = tuple(
        replace(
            f,
            data=(
                b"\x00\xf8" * 4
                if "F1055_" in f.relative_path
                else bytes(len(f.data))
                if corrupt_largest
                else f.data
            ),
        )
        for f in seeded.artwork_files
    )
    identity = source.snapshot.tracks[0].artwork_id
    prepared = _edit(
        source,
        TimedArtworkAsset(
            -3, (TimedArtworkFrame(0, ArtworkGroupReference(identity, 0)),)
        ),
        files,
        target,
    )
    assert [f.relative_path for f in prepared.artwork_files] == [
        "iPod_Control/Artwork/F1029_1.ithmb"
    ]
    loaded = IPodLibrary(prepared.itunes).with_artwork(prepared.artwork or b"")
    read = loaded.artwork_read(
        prepared.snapshot.tracks[0].artwork_id, (CHAPTER,), 2, display_time_ms=0
    )
    assert read is not None
    image = read.decode(
        read_content(prepared.artwork_files[0].data, read.offset, read.length)
    )
    assert image.rgb888[0 if corrupt_largest else 2] > 240


def _wrong_count[**P](method: Callable[P, ArtworkResult]) -> Callable[P, ArtworkResult]:
    def corrupt(*args: P.args, **kwargs: P.kwargs) -> ArtworkResult:
        itunes, artwork, files, identities = method(*args, **kwargs)
        for selection in itunes.find_chunks(MhitHeader):
            chunk = selection.chunk
            itunes = itunes.replace_chunk(
                selection,
                replace(chunk, header=replace(chunk.header, artwork_count=1)),
            )
        return itunes, artwork, files, identities

    return corrupt


@pytest.mark.parametrize("fault", ["count", "missing_chapter"])
def test_verifier_rejects_wrong_count_or_missing_retained_group_completion(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    source, files = timeline()
    identity = source.snapshot.tracks[0].artwork_id
    asset = TimedArtworkAsset(
        -2,
        tuple(
            TimedArtworkFrame(time, ArtworkGroupReference(identity, time))
            for time in (0, 10000)
        ),
    )
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-2) for t in source.snapshot.tracks),
    )
    plan = source.analyze(source.begin_draft(desired), CHAPTER_TARGET)
    resources = timed_resources(asset, files)
    assert source.prepare(plan, resources).prepared is not None
    monkeypatch.setattr(
        preparation,
        "reconcile_artwork",
        _wrong_count(reconcile_artwork)
        if fault == "count"
        else corrupt_timed(reconcile_artwork, "missing"),
    )
    result = source.prepare(plan, resources)
    assert result.prepared is None
    assert any(i.code == "verification.failed" for i in result.issues)
