"""Podcast policy reaches MHIT's native marker without normalizing retained values."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iOpenPod.app.track_playback_policy import (
    enforce_library_playback_policy,
    enforce_track_playback_policy,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.constants import (
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_VIDEO_PODCAST,
)
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    AudioEncoding,
    FileDependency,
    IPodLibrary,
    MediaType,
    Track,
    TrackMetadata,
    WriteResources,
    prepared_audio,
    prepared_video,
)
from iPodDB.shared.binary_struct import binary_fields


def _native_marker(data: bytes, track_id: int) -> int:
    chunk = next(
        selection.chunk
        for selection in parse_iTunesDB(data).find_chunks(MhitHeader)
        if selection.chunk.header.track_id == track_id
    )
    schema = next(
        field.schema
        for field in binary_fields(MhitHeader)
        if field.attribute_name == "podcast_now_playing_flag"
    )
    assert (schema.offset, schema.size) == (0xA7, 1)
    raw = data[chunk.offset + schema.offset]
    assert chunk.header.podcast_now_playing_flag == raw
    return raw


@pytest.mark.parametrize("kind", (MediaType.PODCAST, MediaType.VIDEO_PODCAST))
def test_new_podcast_policy_writes_native_now_playing_marker(kind: MediaType) -> None:
    source = library()
    track = Track(
        -1,
        "New episode",
        "Publisher",
        "Show",
        1_000,
        size_bytes=1_024,
        media_types=(kind,),
        metadata=TrackMetadata(
            location="iPod_Control/Music/F00/new.mp4",
            file_format="Podcast media",
            sample_rate_hz=44_100,
            skip_shuffle=True,
            remember_position=True,
        ),
    )
    desired_track = enforce_track_playback_policy(track)
    dependency = FileDependency(track.metadata.location, track.size_bytes, "a" * 64)
    media = (
        prepared_audio(track.track_id, dependency, AudioEncoding.AAC)
        if kind is MediaType.PODCAST
        else prepared_video(track.track_id, dependency, has_audio=True)
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, desired_track))

    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(media=(media,), pending_playback_sidecars=False),
    )

    assert result.prepared is not None, result.issues
    identity = next(
        mapping.output_id
        for mapping in result.prepared.identities
        if mapping.subject == "track" and mapping.draft_id == track.track_id
    )
    assert _native_marker(result.prepared.itunes, identity) == 1
    assert not track.metadata.podcast
    assert desired_track.metadata.podcast


@pytest.mark.parametrize("kind", (MediaType.PODCAST, MediaType.VIDEO_PODCAST))
def test_existing_native_marker_two_survives_roundtrip_and_ordinary_edit(
    kind: MediaType,
) -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    selection = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            header=replace(
                selection.chunk.header,
                media_type=MEDIA_TYPE_PODCAST
                if kind is MediaType.PODCAST
                else MEDIA_TYPE_VIDEO_PODCAST,
                podcast_now_playing_flag=2,
                skip_when_shuffling=1,
                remember_position=1,
            ),
        ),
    )
    original_bytes = write_iTunesDB(document)
    source = IPodLibrary(original_bytes)
    retained = source.snapshot.tracks[0]
    assert retained.metadata.podcast
    assert source.serialize().itunes == original_bytes

    unchanged = source.prepare(source.analyze(source.begin_draft()))

    assert unchanged.prepared is not None, unchanged.issues
    assert unchanged.prepared.itunes == original_bytes
    assert _native_marker(unchanged.prepared.itunes, retained.track_id) == 2
    desired = enforce_library_playback_policy(
        replace(
            source.snapshot,
            tracks=(
                replace(retained, title="Edited episode"),
                *source.snapshot.tracks[1:],
            ),
        )
    )

    edited = source.prepare(source.analyze(source.begin_draft(desired)))

    assert edited.prepared is not None, edited.issues
    assert edited.prepared.snapshot.tracks[0].title == "Edited episode"
    assert _native_marker(edited.prepared.itunes, retained.track_id) == 2
    assert source.serialize().itunes == original_bytes
