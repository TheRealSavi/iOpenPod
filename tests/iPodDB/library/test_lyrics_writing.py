"""Lyrics flags and file sizes require evidence of the embedded text."""

import hashlib
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    FileDependency,
    IPodLibrary,
    PreparedLyrics,
    Track,
    TrackChapter,
    WriteResources,
)


def lyrics_source(*, flag: int = 0, text: str = "", size_2: int = 100) -> IPodLibrary:
    document = parse_iTunesDB(library().serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        # Refresh selections after each immutable edit.
        current = next(
            s
            for s in document.find_chunks(MhitHeader)
            if s.chunk.header.track_id == selection.chunk.header.track_id
        )
        chunk = current.chunk
        document = document.replace_chunk(
            current,
            replace(
                chunk,
                header=replace(chunk.header, size=100, size_2=size_2, lyrics_flag=flag),
                children=(
                    *chunk.children,
                    new_string_mhod(
                        MhodType.LOCATION,
                        f":iPod_Control:Music:F00:{chunk.header.track_id}.mp3",
                    ),
                    *((new_string_mhod(MhodType.LYRICS, text),) if text else ()),
                ),
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


def lyrics_resource(
    track: Track, data: bytes = b"verified tagged media"
) -> PreparedLyrics:
    return PreparedLyrics(
        track.track_id,
        track.metadata.lyrics,
        FileDependency(
            track.metadata.location, len(data), hashlib.sha256(data).hexdigest()
        ),
    )


@pytest.mark.parametrize(
    "old,new", [("", "New lyrics"), ("Old lyrics", "Replaced"), ("Old lyrics", "")]
)
@pytest.mark.parametrize("size_2", [0, 100])
def test_lyrics_require_file_evidence_and_update_only_affected_size_and_flag(
    old: str, new: str, size_2: int
) -> None:
    source = lyrics_source(flag=int(bool(old)), text=old, size_2=size_2)
    original = source.serialize()
    before, second = source.snapshot.tracks
    changed = replace(before, metadata=replace(before.metadata, lyrics=new))
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, tracks=(changed, second)))
    )
    assert plan.required_lyrics == (before.track_id,)
    assert not plan.required_media
    blocked = source.prepare(replace(plan, required_lyrics=()))
    assert blocked.prepared is None
    assert any(i.code == "resources.missing_lyrics" for i in blocked.issues)
    evidence = lyrics_resource(changed)
    result = source.prepare(plan, WriteResources(lyrics=(evidence,)))
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[1] == second
    after = result.prepared.snapshot.tracks[0]
    assert after.metadata.lyrics == new
    assert after.metadata.has_lyrics == bool(new)
    assert after.size_bytes == evidence.file.size
    assert after.ipod is not None
    assert after.ipod.secondary_size == (evidence.file.size if size_2 else 0)
    assert result.prepared.retained_files == (evidence.file,)
    assert source.serialize() == original


@pytest.mark.parametrize(
    "invalid", ["missing", "text", "path", "hash", "size", "duplicate", "unrequested"]
)
def test_bad_lyrics_evidence_cannot_prepare_database(invalid: str) -> None:
    source = lyrics_source()
    before, second = source.snapshot.tracks
    changed = replace(before, metadata=replace(before.metadata, lyrics="Words"))
    evidence = lyrics_resource(changed)
    items: tuple[PreparedLyrics, ...] = (evidence,)
    if invalid == "missing":
        items = ()
    elif invalid == "text":
        items = (replace(evidence, lyrics="different"),)
    elif invalid == "path":
        items = (
            replace(
                evidence, file=replace(evidence.file, relative_path="../escape.mp3")
            ),
        )
    elif invalid == "hash":
        items = (replace(evidence, file=replace(evidence.file, sha256="not a hash")),)
    elif invalid == "size":
        items = (replace(evidence, file=replace(evidence.file, size=2**32)),)
    elif invalid == "duplicate":
        items = (evidence, evidence)
    else:
        items = (evidence, lyrics_resource(second))
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, tracks=(changed, second)))
    )
    result = source.prepare(plan, WriteResources(lyrics=items))
    assert result.prepared is None
    assert any("lyrics" in issue.code for issue in result.issues)


def test_unrelated_edit_and_noop_preserve_flag_only_source_without_file_reads() -> None:
    source = lyrics_source(flag=1)
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None
    assert noop.prepared.itunes == source.serialize().itunes
    before, second = source.snapshot.tracks
    plan = source.analyze(
        source.begin_draft(
            replace(source.snapshot, tracks=(replace(before, title="Renamed"), second))
        )
    )
    assert not plan.required_lyrics
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[0].metadata.has_lyrics


@pytest.mark.parametrize("clear_reported_issues", [False, True])
def test_invalid_draft_reports_chapters_without_cascading_missing_lyrics(
    clear_reported_issues: bool,
) -> None:
    source = lyrics_source()
    before, second = source.snapshot.tracks
    changed = replace(
        before,
        metadata=replace(
            before.metadata,
            chapters=(TrackChapter("Beyond duration", before.length_ms + 1),),
            lyrics="Words",
        ),
    )
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, tracks=(changed, second)))
    )
    assert plan.blocked and plan.required_lyrics == (before.track_id,)
    if clear_reported_issues:
        plan = replace(plan, issues=())
    result = source.prepare(plan)
    assert result.prepared is None
    assert any(
        issue.code == "track.invalid_value"
        and issue.record_id == before.track_id
        and issue.field == "metadata.chapters"
        for issue in result.issues
    )
    assert not any(issue.code.startswith("resources.") for issue in result.issues)
