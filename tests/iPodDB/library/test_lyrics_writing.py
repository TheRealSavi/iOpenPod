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
    AudioEncoding,
    FileDependency,
    IPodLibrary,
    PreparedLyrics,
    Track,
    TrackChapter,
    WriteResources,
    prepared_audio,
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


@pytest.mark.parametrize("flag", range(256))
def test_lyrics_availability_projects_only_low_bit_without_normalizing_raw_byte(
    flag: int,
) -> None:
    source = lyrics_source(flag=flag)
    original = source.serialize().itunes
    assert all(
        track.metadata.has_lyrics is bool(flag & 1) for track in source.snapshot.tracks
    )
    assert {
        selection.chunk.header.lyrics_flag
        for selection in parse_iTunesDB(original).find_chunks(MhitHeader)
    } == {flag}
    assert IPodLibrary(original).serialize().itunes == original


@pytest.mark.parametrize("flag", [0, 1, 2, 3, 0x80, 0xFE, 0xFF])
def test_unrelated_edit_and_noop_preserve_flag_only_source_without_file_reads(
    flag: int,
) -> None:
    source = lyrics_source(flag=flag)
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
    assert result.prepared.snapshot.tracks[0].metadata.has_lyrics is bool(flag & 1)
    assert {
        selection.chunk.header.lyrics_flag
        for selection in parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    } == {flag}


@pytest.mark.parametrize("flag", [2, 3, 0x80, 0xFF])
@pytest.mark.parametrize("new", ["New lyrics", ""])
def test_authored_lyrics_edits_replace_noncanonical_flags_with_zero_or_one(
    flag: int, new: str
) -> None:
    source = lyrics_source(flag=flag, text="Old lyrics")
    before, second = source.snapshot.tracks
    changed = replace(before, metadata=replace(before.metadata, lyrics=new))
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, tracks=(changed, second)))
    )
    result = source.prepare(plan, WriteResources(lyrics=(lyrics_resource(changed),)))
    assert result.prepared is not None, result.issues
    flags = {
        selection.chunk.header.track_id: selection.chunk.header.lyrics_flag
        for selection in parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    }
    assert flags == {changed.track_id: int(bool(new)), second.track_id: flag}
    assert result.prepared.snapshot.tracks[0].metadata.has_lyrics is bool(new)


@pytest.mark.parametrize("flag", [1, 3, 0xFF])
@pytest.mark.parametrize("relocated", [False, True])
def test_replacement_without_lyrics_requires_verified_absence_before_clearing_flag(
    flag: int, relocated: bool
) -> None:
    source = lyrics_source(flag=flag)
    original = source.serialize()
    first, second = source.snapshot.tracks
    payload = b"verified media without lyrics"
    replacement = replace(
        first,
        size_bytes=len(payload),
        metadata=replace(
            first.metadata,
            sample_rate_hz=44100,
            file_format="MP3",
            location="iPod_Control/Music/F00/replacement.mp3"
            if relocated
            else first.metadata.location,
        ),
    )
    desired = replace(source.snapshot, tracks=(replacement, second))
    plan = source.analyze(
        source.begin_draft(
            desired, replace_media=() if relocated else (first.track_id,)
        )
    )
    assert plan.required_media == plan.required_lyrics == (first.track_id,)
    assert plan.draft.snapshot.tracks[0].metadata.lyrics == ""
    evidence = lyrics_resource(replacement, payload)
    media = prepared_audio(first.track_id, evidence.file, AudioEncoding.MP3)
    missing = source.prepare(plan, WriteResources(media=(media,)))
    assert missing.prepared is None
    assert any(issue.code == "resources.missing_lyrics" for issue in missing.issues)
    # A caller cannot drop the required evidence by altering its reviewed plan.
    forged = source.prepare(
        replace(plan, required_lyrics=()), WriteResources(media=(media,))
    )
    assert forged.prepared is None
    result = source.prepare(plan, WriteResources(media=(media,), lyrics=(evidence,)))
    assert result.prepared is not None, result.issues
    updated = result.prepared.snapshot.tracks[0]
    assert not updated.metadata.has_lyrics and updated.metadata.lyrics == ""
    headers = {
        selection.chunk.header.track_id: selection.chunk.header
        for selection in parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    }
    assert headers[first.track_id].lyrics_flag == 0
    assert headers[second.track_id].lyrics_flag == flag
    assert source.serialize() == original


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
