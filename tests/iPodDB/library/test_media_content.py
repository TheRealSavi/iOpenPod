"""Prepared media describes physical content independently of Library categories."""

import base64
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source

from iPodDB.library import (
    FileDependency,
    IPodLibrary,
    MediaContent,
    MediaType,
    PreparedMedia,
    Track,
    TrackMetadata,
    WriteResources,
)


def test_silent_video_prepares_without_an_invented_audio_sample_rate() -> None:
    source = browse_source()
    fixture = Path(__file__).resolve().parents[2] / "fixtures/media/silent.mp4.b64"
    payload = base64.decodebytes(fixture.read_bytes())
    track = Track(
        -1,
        "Silent video",
        "",
        "",
        267,
        size_bytes=len(payload),
        media_types=(MediaType.VIDEO,),
        metadata=TrackMetadata(
            location="iPod_Control/Music/F00/silent.mp4",
            file_format="MPEG-4 video file",
            sample_rate_hz=0,
        ),
    )
    media = PreparedMedia(
        track.track_id,
        FileDependency(
            track.metadata.location, len(payload), hashlib.sha256(payload).hexdigest()
        ),
        filetype=int.from_bytes(b"MP4 ", "big"),
        mp3_flag=0,
        audio_format_flag=0xFFFF,
        mpeg_audio_type=0,
        gapless_audio_payload_size=0,
        content=MediaContent.VIDEO,
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                replace(source.snapshot, tracks=(*source.snapshot.tracks, track))
            )
        ),
        WriteResources(media=(media,), pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    imported = next(
        t for t in result.prepared.snapshot.tracks if t.title == "Silent video"
    )
    assert imported.length_ms == 267
    assert imported.metadata.sample_rate_hz == 0
    assert imported.ipod is not None and imported.ipod.sample_rate_2 == 0
    # A later metadata edit uses retained source facts, without another media input.
    loaded = IPodLibrary(result.prepared.itunes)
    renamed = replace(imported, album="Silent films")
    desired = replace(
        loaded.snapshot,
        tracks=tuple(
            renamed if t.track_id == imported.track_id else t
            for t in loaded.snapshot.tracks
        ),
    )
    edited = loaded.prepare(loaded.analyze(loaded.begin_draft(desired)))
    assert edited.prepared is not None, edited.issues
    actual = next(
        t for t in edited.prepared.snapshot.tracks if t.track_id == imported.track_id
    )
    assert actual.album == "Silent films"
    assert actual.metadata.sample_rate_hz == 0
    assert actual.ipod is not None and actual.ipod.sample_rate_2 == 0


@pytest.mark.parametrize("media_type", [MediaType.PDF_BOOK, MediaType.EPUB_BOOK])
def test_document_records_do_not_require_audio_timing(media_type: MediaType) -> None:
    source = browse_source()
    # The database API accepts a caller-owned captured identity, never file contents.
    dependency = FileDependency("iPod_Control/Music/F00/book.bin", 1024, "a" * 64)
    track = Track(
        -1,
        "Document",
        "",
        "",
        0,
        size_bytes=dependency.size,
        media_types=(media_type,),
        metadata=TrackMetadata(
            location=dependency.relative_path, file_format="Document"
        ),
    )
    media = PreparedMedia(-1, dependency, 0, 0, 0, 0, 0, content=MediaContent.DOCUMENT)
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                replace(source.snapshot, tracks=(*source.snapshot.tracks, track))
            )
        ),
        WriteResources(media=(media,), pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    imported = next(t for t in result.prepared.snapshot.tracks if t.title == "Document")
    assert imported.length_ms == 0
    assert imported.metadata.sample_rate_hz == 0
    assert imported.media_types == (media_type,)


@pytest.mark.parametrize(
    "content,duration,metadata,payload_size,message",
    [
        (MediaContent.AUDIO, 0, TrackMetadata(sample_rate_hz=44100), 0, "duration"),
        (MediaContent.AUDIO, 1000, TrackMetadata(), 0, "sample rate"),
        (
            MediaContent.AUDIO_VIDEO,
            0,
            TrackMetadata(sample_rate_hz=44100),
            0,
            "duration",
        ),
        (MediaContent.AUDIO_VIDEO, 1000, TrackMetadata(), 0, "sample rate"),
        (MediaContent.VIDEO, 0, TrackMetadata(), 0, "duration"),
        (MediaContent.DOCUMENT, 1000, TrackMetadata(), 0, "zero playback duration"),
        (
            MediaContent.DOCUMENT,
            0,
            TrackMetadata(sample_rate_hz=44100),
            0,
            "without audio",
        ),
        (
            MediaContent.VIDEO,
            1000,
            TrackMetadata(sample_rate_hz=44100),
            0,
            "without audio",
        ),
        (
            MediaContent.VIDEO,
            1000,
            TrackMetadata(sample_count=44100),
            0,
            "without audio",
        ),
        (MediaContent.VIDEO, 1000, TrackMetadata(pregap=1), 0, "without audio"),
        (MediaContent.VIDEO, 1000, TrackMetadata(postgap=1), 0, "without audio"),
        (MediaContent.VIDEO, 1000, TrackMetadata(gapless=True), 0, "without audio"),
        (MediaContent.VIDEO, 1000, TrackMetadata(), 1, "without audio"),
    ],
)
def test_prepared_content_rejects_contradictory_timing(
    content: MediaContent,
    duration: int,
    metadata: TrackMetadata,
    payload_size: int,
    message: str,
) -> None:
    source = browse_source()
    original = source.serialize()
    file = FileDependency("iPod_Control/Music/F00/media.bin", 1024, "a" * 64)
    track = Track(
        -1,
        "New media",
        "",
        "",
        duration,
        size_bytes=file.size,
        metadata=replace(metadata, location=file.relative_path),
    )
    draft = source.begin_draft(
        replace(source.snapshot, tracks=(*source.snapshot.tracks, track))
    )
    result = source.prepare(
        source.analyze(draft),
        WriteResources(
            media=(PreparedMedia(-1, file, 0, 0, 0, 0, payload_size, content=content),),
            pending_playback_sidecars=False,
        ),
    )
    assert result.prepared is None
    assert any(
        issue.code == "resources.invalid_media"
        and issue.record_id == -1
        and message in issue.message
        for issue in result.issues
    ), result.issues
    assert source.serialize() == original
    assert draft.snapshot.tracks[-1] == track


def test_audio_video_accepts_audio_timing_and_can_be_replaced_by_silent_video() -> None:
    source = browse_source()
    prior = source.snapshot.tracks[0]
    file = FileDependency("iPod_Control/Music/F00/movie.mp4", 1024, "a" * 64)
    track = replace(
        prior,
        length_ms=1000,
        size_bytes=file.size,
        media_types=(MediaType.VIDEO,),
        metadata=replace(
            prior.metadata,
            location=file.relative_path,
            file_format="MPEG-4 video file",
            sample_rate_hz=48000,
        ),
    )
    desired = replace(source.snapshot, tracks=(track, *source.snapshot.tracks[1:]))
    media = PreparedMedia(
        track.track_id,
        file,
        int.from_bytes(b"MP4 ", "big"),
        0,
        0xFFFF,
        0,
        0,
        content=MediaContent.AUDIO_VIDEO,
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired)), WriteResources(media=(media,))
    )
    assert result.prepared is not None, result.issues
    loaded = IPodLibrary(result.prepared.itunes)
    voiced = loaded.snapshot.tracks[0]
    assert voiced.ipod is not None and voiced.ipod.sample_rate_2 == 48000
    silent = replace(voiced, metadata=replace(voiced.metadata, sample_rate_hz=0))
    desired = replace(loaded.snapshot, tracks=(silent, *loaded.snapshot.tracks[1:]))
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft(desired)),
        WriteResources(
            media=(
                replace(
                    media,
                    file=replace(file, sha256="b" * 64),
                    content=MediaContent.VIDEO,
                ),
            )
        ),
    )
    assert result.prepared is not None, result.issues
    actual = result.prepared.snapshot.tracks[0]
    assert actual.metadata.sample_rate_hz == 0
    assert actual.ipod is not None and actual.ipod.sample_rate_2 == 0
    assert prior.ipod is not None
    assert actual.ipod.db_track_id == prior.ipod.db_track_id
