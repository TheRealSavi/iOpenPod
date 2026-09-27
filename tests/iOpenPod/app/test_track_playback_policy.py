"""Application-required flags without changing retained database projections."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.library.test_video_flags import video_source

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.media.importing import ImportedSong, LibraryMediaSource
from iOpenPod.app.track_playback_policy import (
    enforce_library_playback_policy,
    enforce_track_playback_policy,
    requires_track_playback_policy,
)
from iPodDB.library import (
    FileDependency,
    LibrarySnapshot,
    MediaType,
    Track,
    TrackMetadata,
    prepared_video,
)
from storage import FileFingerprint, HostPath


@pytest.mark.parametrize(
    "kind",
    (
        MediaType.PODCAST,
        MediaType.VIDEO_PODCAST,
        MediaType.VIDEO,
        MediaType.AUDIO_VIDEO,
        MediaType.TV_SHOW,
        MediaType.MUSIC_VIDEO,
    ),
)
def test_all_podcasts_and_video_types_require_both_flags(kind: MediaType) -> None:
    original = Track(1, "Title", "Artist", "Album", 1_000, media_types=(kind,))

    updated = enforce_track_playback_policy(original)

    assert requires_track_playback_policy(original)
    assert updated == replace(
        original,
        metadata=replace(
            original.metadata,
            skip_shuffle=True,
            remember_position=True,
            podcast=kind in (MediaType.PODCAST, MediaType.VIDEO_PODCAST),
        ),
    )
    assert enforce_track_playback_policy(updated) is updated
    assert not original.metadata.skip_shuffle
    assert not original.metadata.remember_position


@pytest.mark.parametrize("kind", (MediaType.PODCAST, MediaType.VIDEO_PODCAST))
def test_podcast_display_is_repaired_when_playback_flags_are_already_enabled(
    kind: MediaType,
) -> None:
    track = Track(
        1,
        "Episode",
        "",
        "",
        1_000,
        media_types=(kind,),
        metadata=TrackMetadata(skip_shuffle=True, remember_position=True),
    )

    updated = enforce_track_playback_policy(track)

    assert updated.metadata.podcast
    assert updated.metadata.skip_shuffle and updated.metadata.remember_position


def test_legacy_semantic_podcast_flag_also_requires_both_flags() -> None:
    track = Track(1, "Episode", "", "", 1_000, metadata=TrackMetadata(podcast=True))

    updated = enforce_track_playback_policy(track)

    assert updated.metadata.skip_shuffle and updated.metadata.remember_position
    assert updated.media_types == track.media_types


@pytest.mark.parametrize("kind", (MediaType.AUDIO, MediaType.AUDIOBOOK, MediaType.MEMO))
@pytest.mark.parametrize("enabled", (False, True))
def test_other_media_keep_their_existing_playback_preferences(
    kind: MediaType,
    enabled: bool,
) -> None:
    track = Track(
        1,
        "Title",
        "",
        "",
        1_000,
        media_types=(kind,),
        metadata=TrackMetadata(skip_shuffle=enabled, remember_position=enabled),
    )
    snapshot = LibrarySnapshot((track,))

    assert not requires_track_playback_policy(track)
    assert enforce_track_playback_policy(track) is track
    assert enforce_library_playback_policy(snapshot) is snapshot


def test_incoming_video_gets_required_flags_before_entering_the_workspace(
    tmp_path: Path,
) -> None:
    location = "iPod_Control/Music/F00/VIDE.m4v"
    fingerprint = FileFingerprint(10, 0, 0, 0, "a" * 64)
    track = Track(
        0,
        "Movie",
        "",
        "",
        1_000,
        size_bytes=10,
        media_types=(MediaType.VIDEO,),
        metadata=TrackMetadata(location=location),
    )
    song = ImportedSong(
        track,
        LibraryMediaSource(
            HostPath(tmp_path / "source.m4v"),
            fingerprint,
            prepared_video(
                0, FileDependency(location, 10, fingerprint.sha256), has_audio=True
            ),
        ),
    )
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot())

    workspace.add_songs((song,), workspace.edit_revision)

    imported = workspace.tracks[0]
    assert imported.metadata.skip_shuffle and imported.metadata.remember_position
    assert not song.track.metadata.skip_shuffle
    assert not song.track.metadata.remember_position


def test_write_policy_repairs_existing_flags_without_changing_loaded_bytes() -> None:
    source = video_source(video=True)
    original_bytes = source.serialize()
    original = source.snapshot
    workspace = LibraryWorkspace()

    workspace.load(original)
    desired = enforce_library_playback_policy(workspace.desired_snapshot())

    assert not workspace.dirty
    assert workspace.tracks == original.tracks
    assert workspace.desired_snapshot() == original
    assert desired.tracks[0].metadata.skip_shuffle
    assert desired.tracks[0].metadata.remember_position
    assert source.serialize() == original_bytes
