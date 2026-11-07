"""Explicit chapter artwork enables native gates without rewriting timelines."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_chapter_artwork import CHAPTER_TARGET
from tests.iPodDB.library.test_native_chapters import chapter_payload, chapter_source
from tests.iPodDB.library.test_timed_artwork import timed_resources
from tests.iPodDB.library.test_write_artwork import BLUE, RED, TARGET
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataChapter,
    MhodChapterDataPayload,
)
from iPodDB.library import (
    IPodLibrary,
    TimedArtworkAsset,
    TimedArtworkFrame,
    TrackChapter,
)


@pytest.mark.parametrize("flags", [None, 0, 1, 2, 3, 0x80000001])
@pytest.mark.parametrize("chapter_capable", [False, True])
def test_explicit_timeline_coordinates_known_flags_only(
    flags: int | None, chapter_capable: bool
) -> None:
    source = chapter_source(chapter_payload(flags))
    original = source.serialize().itunes
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(replace(track, artwork_id=-1), *source.snapshot.tracks[1:]),
    )
    asset = TimedArtworkAsset(
        -1, (TimedArtworkFrame(500, BLUE.pixels), TimedArtworkFrame(0, RED.pixels))
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired), CHAPTER_TARGET if chapter_capable else TARGET
        ),
        timed_resources(asset, ()),
    )
    assert result.prepared is not None, result.issues
    saved = IPodLibrary(result.prepared.itunes).snapshot.tracks[0]
    assert saved.ipod is not None and saved.ipod.native_chapters is not None
    expected = flags | 3 if flags is not None and chapter_capable else flags
    assert saved.ipod.native_chapters.flags == expected
    assert saved.metadata.chapters == track.metadata.chapters
    assert source.serialize().itunes == original
    if flags is None and chapter_capable:
        assert "chapter.artwork_ineligible" in {issue.code for issue in result.issues}
    assert "chapter.artwork_timeline_mismatch" not in {
        issue.code for issue in result.issues
    }


def test_new_chapters_plus_timeline_enable_artwork_and_report_unshifted_mismatch() -> (
    None
):
    source = library()
    track = source.snapshot.tracks[0]
    chapters = (TrackChapter("Start", 0), TrackChapter("Later", 500))
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                track,
                artwork_id=-1,
                metadata=replace(track.metadata, chapters=chapters),
            ),
            *source.snapshot.tracks[1:],
        ),
    )
    asset = TimedArtworkAsset(
        -1, (TimedArtworkFrame(0, RED.pixels), TimedArtworkFrame(499, BLUE.pixels))
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), CHAPTER_TARGET),
        timed_resources(asset, ()),
    )
    assert result.prepared is not None, result.issues
    assert "chapter.artwork_timeline_mismatch" in {
        issue.code for issue in result.issues
    }
    loaded = IPodLibrary(result.prepared.itunes).with_artwork(
        result.prepared.artwork or b""
    )
    saved = loaded.snapshot.tracks[0]
    assert saved.ipod is not None and saved.ipod.native_chapters is not None
    assert saved.ipod.native_chapters.flags == 3
    assert saved.metadata.chapters == chapters
    assert loaded.artwork_display_times(saved.artwork_id) == (0, 499)


def test_ordinary_cover_preserves_chapter_atom_bytes_and_flags() -> None:
    source = chapter_source(chapter_payload(0x80000002))
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=RED.artwork_id),
            *source.snapshot.tracks[1:],
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), CHAPTER_TARGET),
        timed_resources(RED, ()),
    )
    assert result.prepared is not None, result.issues

    def raw_chapter(data: bytes) -> bytes:
        track = parse_iTunesDB(data).find_chunks(MhitHeader)[0].chunk
        return next(
            c.raw_body
            for c in track.children
            if isinstance(c.payload, MhodChapterDataPayload)
        )

    assert raw_chapter(result.prepared.itunes) == raw_chapter(source.serialize().itunes)


@pytest.mark.parametrize("opaque_header", [False, True])
def test_unusable_chapter_header_is_diagnosed_and_preserved(
    opaque_header: bool,
) -> None:
    payload = (
        replace(chapter_payload(), hedr_trailing_data=b"opaque extension")
        if opaque_header
        else chapter_payload(chapters=(MhodChapterDataChapter("", 0, ()),))
    )
    source = chapter_source(payload)
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-1),
            *source.snapshot.tracks[1:],
        ),
    )
    asset = TimedArtworkAsset(-1, (TimedArtworkFrame(0, RED.pixels),))
    result = source.prepare(
        source.analyze(source.begin_draft(desired), CHAPTER_TARGET),
        timed_resources(asset, ()),
    )
    assert result.prepared is not None, result.issues
    assert "chapter.artwork_ineligible" in {issue.code for issue in result.issues}
    before = parse_iTunesDB(source.serialize().itunes).find_chunks(MhitHeader)[0].chunk
    after = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert [
        c.raw_body
        for c in after.children
        if isinstance(c.payload, MhodChapterDataPayload)
    ] == [
        c.raw_body
        for c in before.children
        if isinstance(c.payload, MhodChapterDataPayload)
    ]
