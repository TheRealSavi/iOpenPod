"""Video flag mirrors follow explicit media changes within the retained header."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.device_time import TimeConversion
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    FileDependency,
    IPodLibrary,
    MediaContent,
    MediaType,
    PreparedMedia,
    Track,
    TrackMetadata,
    WriteResources,
    _write_preparation,
)
from iPodDB.library._reconcile import reconcile
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library.writing import IdentityMapping, WriteIssue
from iPodDB.shared.chunk import DatabaseDocument


def video_source(
    *, video: bool, header_length: int = 0x270, mirror: int | None = None
) -> IPodLibrary:
    document = parse_iTunesDB(library().serialize().itunes)
    selection = document.find_chunks(MhitHeader)[0]
    chunk = selection.chunk
    header = replace(
        chunk.header,
        media_type=2 if video else 1,
        video_flag=int(video),
        video_flag_2=(int(video) if mirror is None else mirror)
        if header_length >= 0x195
        else 0,
        sample_rate_1=44100 << 16,
        sample_rate_2=44100.0,
    )
    document = document.replace_chunk(
        selection,
        replace(
            chunk,
            header=header,
            generic_header=replace(chunk.generic_header, header_length=header_length),
            raw_header=chunk.raw_header[:header_length],
        ),
    )
    return IPodLibrary(write_iTunesDB(document))


def media_for(track: Track) -> PreparedMedia:
    # Caller-supplied resource facts exercise the database contract, not a decoder.
    audio = track.media_types == (MediaType.AUDIO,)
    return PreparedMedia(
        track.track_id,
        FileDependency(track.metadata.location, track.size_bytes, "a" * 64),
        int.from_bytes(b"M4A " if audio else b"MP4 ", "big"),
        0,
        0xFFFF,
        0,
        0,
        content=MediaContent.AUDIO if audio else MediaContent.AUDIO_VIDEO,
    )


@pytest.mark.parametrize(
    "media_type,video",
    [
        (MediaType.VIDEO, True),
        (MediaType.AUDIO_VIDEO, True),
        (MediaType.MUSIC_VIDEO, True),
        (MediaType.TV_SHOW, True),
        (MediaType.VIDEO_PODCAST, True),
        (MediaType.AUDIO, False),
    ],
)
def test_new_track_populates_both_video_flags(
    media_type: MediaType, video: bool
) -> None:
    source = library()
    track = Track(
        -1,
        "New media",
        "",
        "",
        1000,
        size_bytes=1024,
        media_types=(media_type,),
        metadata=TrackMetadata(
            location="iPod_Control/Music/F00/new.mp4",
            file_format="Media file",
            sample_rate_hz=44100,
        ),
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, track))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(media=(media_for(track),), pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    mapping = next(
        m
        for m in result.prepared.identities
        if m.subject == "track" and m.draft_id == -1
    )
    chunk = next(
        s.chunk
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
        if s.chunk.header.track_id == mapping.output_id
    )
    assert chunk.header.video_flag == chunk.header.video_flag_2 == int(video)


@pytest.mark.parametrize("header_length", [0x148, 0x194, 0x195, 0x1F8, 0x270])
@pytest.mark.parametrize("video", [False, True])
def test_reclassification_updates_present_video_mirror_without_expanding_header(
    header_length: int, video: bool
) -> None:
    source = video_source(video=not video, header_length=header_length)
    original = source.serialize()
    prior = source.snapshot.tracks[0]
    track = replace(
        prior,
        media_types=(MediaType.VIDEO if video else MediaType.AUDIO,),
        size_bytes=1024,
        metadata=replace(
            prior.metadata,
            location="iPod_Control/Music/F00/replacement.mp4",
            file_format="Media file",
        ),
    )
    desired = replace(source.snapshot, tracks=(track, *source.snapshot.tracks[1:]))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(media=(media_for(track),)),
    )
    assert result.prepared is not None, result.issues
    chunk = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert chunk.generic_header.header_length == header_length
    assert chunk.header.video_flag == int(video)
    assert chunk.header.video_flag_2 == (int(video) if header_length >= 0x195 else 0)
    assert source.serialize() == original


def test_unrelated_metadata_edit_preserves_noncanonical_video_mirror() -> None:
    source = video_source(video=True, mirror=9)
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Edited"),
            *source.snapshot.tracks[1:],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    header = (
        parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk.header
    )
    assert (header.video_flag, header.video_flag_2) == (1, 9)


def test_changed_video_category_rederives_both_flags() -> None:
    source = video_source(video=True, mirror=9)
    prior = source.snapshot.tracks[0]
    track = replace(
        prior,
        media_types=(MediaType.MUSIC_VIDEO,),
        size_bytes=1024,
        metadata=replace(
            prior.metadata,
            location="iPod_Control/Music/F00/movie.mp4",
            file_format="Media file",
        ),
    )
    desired = replace(source.snapshot, tracks=(track, *source.snapshot.tracks[1:]))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(media=(media_for(track),)),
    )
    assert result.prepared is not None, result.issues
    header = (
        parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk.header
    )
    assert (header.video_flag, header.video_flag_2) == (1, 1)


@pytest.mark.parametrize("addition", [False, True])
def test_verification_rejects_stale_secondary_video_flag(
    monkeypatch: pytest.MonkeyPatch, addition: bool
) -> None:
    source = video_source(video=False)
    prior = source.snapshot.tracks[0]
    track = replace(
        prior,
        track_id=-1 if addition else prior.track_id,
        ipod=None if addition else prior.ipod,
        media_types=(MediaType.VIDEO,),
        size_bytes=1024,
        metadata=replace(
            prior.metadata,
            location="iPod_Control/Music/F00/video.mp4",
            file_format="Media file",
        ),
    )
    desired = replace(
        source.snapshot,
        tracks=(*source.snapshot.tracks, track)
        if addition
        else (track, *source.snapshot.tracks[1:]),
    )
    resources = WriteResources(
        media=(media_for(track),), pending_playback_sidecars=False
    )
    baseline = source.prepare(source.analyze(source.begin_draft(desired)), resources)
    assert baseline.prepared is not None, baseline.issues

    def corrupt(
        document: DatabaseDocument[MhbdHeader],
        resolved: ResolvedWrite,
        resources: WriteResources,
        issues: list[WriteIssue],
        device_time: TimeConversion = 0,
    ) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
        output, mappings = reconcile(document, resolved, resources, issues, device_time)
        native_id = next(
            (
                m.output_id
                for m in mappings
                if m.subject == "track" and m.draft_id == track.track_id
            ),
            track.track_id,
        )
        selection = next(
            s
            for s in output.find_chunks(MhitHeader)
            if s.chunk.header.track_id == native_id
        )
        return output.replace_chunk(
            selection,
            replace(
                selection.chunk, header=replace(selection.chunk.header, video_flag_2=0)
            ),
        ), mappings

    monkeypatch.setattr(_write_preparation, "reconcile", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)), resources)
    assert result.prepared is None
    assert any(
        i.code == "verification.track_native"
        and i.field == "video_flag_2"
        and i.record_id == track.track_id
        for i in result.issues
    ), result.issues
