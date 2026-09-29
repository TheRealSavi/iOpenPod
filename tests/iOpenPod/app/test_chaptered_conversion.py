"""A chaptered Album is prepared before one reversible Library replacement."""

import base64
import shutil
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtCore import QObject, Signal
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_library_write_controller import wait_for
from tests.iPodDB.library.test_writing import library

from iOpenPod.app.chaptered_conversion import (
    can_convert_album,
    chapter_timeline,
    prepare_chaptered_album,
)
from iOpenPod.app.chaptered_conversion_controller import ChapteredConversionController
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.media.importing import ImportedSong, LibraryMediaSource
from iOpenPod.app.media.inspection import MediaInspector
from iOpenPod.app.models.device import ActiveIPod
from iPodDB.library import (
    FileDependency,
    IPodLibrary,
    LibrarySnapshot,
    PhotoAlbum,
    PhotoLibrary,
    Playlist,
    PreparedMedia,
    Track,
    TrackChapter,
    TrackMetadata,
    playlist_entries,
)
from storage import FileFingerprint, HostPath

if TYPE_CHECKING:
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "media"
    / "chapters-cover.m4a.b64"
)


def _tracks(duration: int) -> tuple[Track, Track]:
    return (
        Track(
            1,
            "Opening",
            "Artist",
            "Album",
            duration,
            track_number=1,
            artwork_id=100,
            metadata=TrackMetadata(location="iPod_Control/Music/F00/one.m4a"),
        ),
        Track(
            2,
            "Finale",
            "Artist",
            "Album",
            duration,
            track_number=2,
            artwork_id=100,
            metadata=TrackMetadata(location="iPod_Control/Music/F00/two.m4a"),
        ),
    )


def test_complete_album_validation_and_chapter_order() -> None:
    tracks = _tracks(120_000)
    assert can_convert_album(tracks, tracks)
    assert not can_convert_album(tracks[:1], tracks)
    assert not can_convert_album(tracks[:1], tracks[:1])
    assert not can_convert_album(tracks, (*tracks, replace(tracks[1], track_id=3)))
    assert chapter_timeline(tracks, (120_000, 130_000)) == (
        TrackChapter("01. Opening", 0),
        TrackChapter("02. Finale", 120_000),
    )


def test_chaptered_album_replaces_playlist_occurrence_with_a_new_entry(
    tmp_path: Path,
) -> None:
    source = library()
    original = replace(
        source.snapshot,
        tracks=tuple(replace(track, album="Album") for track in source.snapshot.tracks),
    )
    prepared = source.prepare(source.analyze(source.begin_draft(original)))
    assert prepared.prepared is not None, prepared.issues
    source = IPodLibrary(prepared.prepared.itunes)
    workspace = LibraryWorkspace()
    workspace.load(source.snapshot)
    location = "iPod_Control/Music/F00/chaptered.m4a"
    digest = "a" * 64
    track = Track(
        0,
        "Album",
        "Artist",
        "Album",
        2_000,
        size_bytes=10,
        metadata=TrackMetadata(
            location=location,
            chapters=(TrackChapter("Opening", 0), TrackChapter("Finale", 1_000)),
        ),
    )
    song = ImportedSong(
        track,
        LibraryMediaSource(
            HostPath(tmp_path / "chaptered.m4a"),
            FileFingerprint(10, 0, 0, 0, digest),
            PreparedMedia(0, FileDependency(location, 10, digest), 0, 0, 0, 0, 0),
        ),
    )

    workspace.replace_tracks_with_chaptered_song((1, 2), song, workspace.edit_revision)
    entry = workspace.playlists[0].entries[0]
    assert workspace.playlists[0].track_ids == (workspace.tracks[0].track_id,)
    assert entry.entry_id not in {
        prior.entry_id for prior in source.snapshot.playlists[0].entries
    }
    assert entry.position is None
    plan = source.analyze(
        source.begin_draft(workspace.desired_snapshot(), delete_omissions=True)
    )

    assert not [
        issue for issue in plan.issues if issue.code == "playlist.entry_reassigned"
    ], plan.issues


class _CopyingCoordinator:
    def __init__(self, active: object, source: Path) -> None:
        self.active_ipod = active
        self.source = source

    def copy_track_to_host(self, _track: Track, destination: HostPath) -> None:
        shutil.copyfile(self.source, destination.path)


class _Devices(QObject):
    activeIPodChanged = Signal(object)

    def __init__(self, active: ActiveIPod) -> None:
        super().__init__()
        self.active_ipod = active
        self.busy = False


def test_draft_change_cancels_a_pending_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    tracks = _tracks(1_000)
    snapshot = LibrarySnapshot(tracks)
    active = replace(device.active, library=snapshot)
    devices = _Devices(active)
    workspace = LibraryWorkspace()
    workspace.load(snapshot)
    entered, release = Event(), Event()

    def wait_for_release(*_args: object, checkpoint: object, **_kwargs: object) -> None:
        entered.set()
        assert release.wait(5)
        assert callable(checkpoint)
        checkpoint()
        raise AssertionError("Cancelled work must not complete")

    monkeypatch.setattr(
        "iOpenPod.app.chaptered_conversion_controller.prepare_chaptered_album",
        wait_for_release,
    )
    controller = ChapteredConversionController(
        workspace,
        cast("DeviceController", devices),
        device.coordinator,
    )
    failures: list[str] = []
    controller.failed.connect(failures.append)
    try:
        assert controller.start(tracks)
        wait_for(entered.is_set)
        workspace.remove_tracks((1,), workspace.edit_revision)
        assert not controller.busy
    finally:
        release.set()
        controller.shutdown()
        device.coordinator.close()
    assert workspace.tracks == (tracks[1],)
    assert not workspace.media_sources
    assert not failures


def test_encoded_album_is_verified_then_staged_with_playlist_membership(
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and FFprobe are required for real Album conversion")
    source = tmp_path / "source.m4a"
    source.write_bytes(base64.decodebytes(FIXTURE.read_bytes()))
    observed = MediaInspector().inspect(HostPath(source), checkpoint=lambda: None)
    duration = observed.audio_streams[0].duration_seconds or observed.duration_seconds
    assert duration is not None
    tracks = _tracks(round(float(duration) * 1000))
    playlist = Playlist(10, "Favorites", entries=playlist_entries((2, 1, 2)))
    snapshot = LibrarySnapshot(tracks, (playlist,))
    device = build_device(tmp_path / "device")
    try:
        active = replace(device.active, library=snapshot)
        coordinator = cast("DeviceCoordinator", _CopyingCoordinator(active, source))
        result = prepare_chaptered_album(
            tracks,
            active,
            coordinator,
            tuple(t.metadata.location for t in tracks),
            checkpoint=lambda: None,
        )
        try:
            assert Path(result.song.source.source).is_file()
            assert result.song.track.title == "Album"
            assert result.song.track.metadata.chapters[0].start_ms == 0
            assert len(result.song.track.metadata.chapters) == 2
            assert abs(result.song.track.length_ms - 2 * tracks[0].length_ms) < 500

            photos = PhotoLibrary(albums=(PhotoAlbum(7, "Slides", music_track_id=2),))
            photo_workspace = LibraryWorkspace()
            photo_workspace.load(replace(snapshot, photos=photos))
            photo_workspace.replace_tracks_with_chaptered_song(
                (1, 2), result.song, photo_workspace.edit_revision
            )
            assert photo_workspace.photos is not None
            assert (
                photo_workspace.photos.albums[0].music_track_id
                == photo_workspace.tracks[0].track_id
            )
            photo_workspace.reset_changes()
            assert photo_workspace.photos == photos

            workspace = LibraryWorkspace()
            workspace.load(snapshot)
            original_revision = workspace.edit_revision
            workspace.replace_tracks_with_chaptered_song(
                (1, 2), result.song, original_revision
            )
            assert len(workspace.tracks) == 1
            replacement = workspace.tracks[0]
            assert replacement.track_id < 0
            assert replacement.artwork_id == 100
            assert workspace.playlists[0].track_ids == (replacement.track_id,)
            assert workspace.delete_omissions
            assert len(workspace.media_sources) == 1
            assert workspace.media_sources[0].media.track_id == replacement.track_id
            review = device.coordinator.prepare_library(
                LibraryPreparationRequest(
                    workspace.desired_snapshot(),
                    device.active,
                    workspace.generation,
                    workspace.revision,
                    delete_omissions=workspace.delete_omissions,
                    media=workspace.media_sources,
                ),
                lambda _progress: None,
                Event(),
            )
            assert review.result.prepared is not None, review.result.issues
            assert any(
                change.action == "write"
                and change.path == replacement.metadata.location
                for change in review.file_changes
            )
            assert sum(change.action == "remove" for change in review.file_changes) >= 2
            saved = device.save(review)
            assert not saved.issues
            assert (device.root / replacement.metadata.location).is_file()
            assert saved.recovery_path
            device.restore(saved.recovery_path)
            workspace.reset_changes()
            assert tuple(workspace.tracks) == tuple(tracks)
            assert workspace.playlists == (playlist,)
        finally:
            result.directory.cleanup()
    finally:
        device.coordinator.close()
