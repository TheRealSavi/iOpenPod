"""Reviewed Sync exercises actual database verification and Storage publication.

Private imports deliberately isolate scan, draft, and prepared-media regressions
without exposing implementation helpers as application API.
"""

import base64
import hashlib
import json
import re
import shutil
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from PIL import Image
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_music_import import FIXTURES

from iOpenPod.app.host_media_library import (
    HostArtworkKind,
    HostMediaArtworkSource,
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
    _build_library,  # pyright: ignore[reportPrivateUsage]
    _CachedPlaylistRecord,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    IPodImageFingerprint,
    IPodMediaCacheStats,
    IPodMediaLibrary,
    IPodTrackFingerprint,
    SyncDetails,
    SyncedTrack,
)
from iOpenPod.app.library_write import LibraryReview, LibrarySaveResult, WriteProgress
from iOpenPod.app.media.importing import ImportedSong, LibraryMediaSource
from iOpenPod.app.media.inspection import _parse  # pyright: ignore[reportPrivateUsage]
from iOpenPod.app.media.music_paths import MusicPathAllocator
from iOpenPod.app.media.transcoding import (
    MediaTranscoder,
    PreparedTranscode,
    VideoEncoding,
)
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services.device_coordinator import SyncCleanupCompletedError
from iOpenPod.app.sync_execution import (
    PlaylistSyncChange,
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
    _draft,  # pyright: ignore[reportPrivateUsage]
    _PreparedTrack,  # pyright: ignore[reportPrivateUsage]
    _song,  # pyright: ignore[reportPrivateUsage]
    preview_playlist_sync,
)
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanItem,
    prepare_sync_plan,
)
from iPodDB.library import (
    AudioEncoding,
    FileDependency,
    LibrarySnapshot,
    MediaContent,
    MediaType,
    Photo,
    PhotoAlbum,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Playlist,
    PlaylistEntry,
    Track,
    TrackMetadata,
    playlist_entries,
    prepared_audio,
)
from storage import DevicePath, HostPath, capture_host_file
from storage.host_input import LocalHostFile
from storage.media_processing import MediaTools


class _AvailableTools(MediaTranscoder):
    def preflight(self, *, checkpoint: Callable[[], None]) -> MediaTools:
        checkpoint()
        return cast("MediaTools", None)


def _photo_host(tmp_path: Path) -> HostMediaLibrary:
    path = tmp_path / "tall-photo.png"
    Image.new("RGB", (60, 120), "red").save(path)
    data = path.read_bytes()
    observation = LocalHostFile.observe(HostPath(path))
    return HostMediaLibrary(
        LibrarySnapshot(
            photos=PhotoLibrary(
                photos=(
                    Photo(
                        1,
                        source_size_bytes=len(data),
                        representations=(
                            PhotoRepresentation(
                                PhotoRepresentationKind.FULL_RESOLUTION,
                                0,
                                str(path),
                                0,
                                len(data),
                                60,
                                120,
                            ),
                        ),
                    ),
                )
            )
        ),
        (
            HostMediaSource(
                observation.path,
                HostMediaFileKind.PHOTO,
                observation.size_bytes,
                observation.modified_ns,
                content_sha256=hashlib.sha256(data).hexdigest(),
            ),
        ),
        (),
        HostMediaCacheStats(),
    )


def test_photo_creates_verified_library_files_and_sync_provenance(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _photo_host(tmp_path))
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.active.library.photos is not None
        assert len(result.active.library.photos.photos) == 1
        added = result.active.library.photos.photos[0]
        assert len(added.representations) > 1
        assert all(
            (device.root / representation.relative_path).exists()
            for representation in added.representations
        )
        assert result.helper is not None and len(result.helper.images) == 1
        assert result.helper.images[0].sync is not None
        assert result.helper.images[0].sync.host_path_hint == str(
            request.host.sources[0].path
        )
    finally:
        device.coordinator.close()


def test_photo_update_removes_unshared_old_original_after_library_publication(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path, photos=True)
    try:
        host = _photo_host(tmp_path)
        ipod = _ipod(device)
        old = ipod.images[0]
        source = host.sources[0]
        ipod = replace(
            ipod,
            images=(
                replace(
                    old,
                    sync=SyncDetails(
                        "2026-01-01T00:00:00Z",
                        str(source.path),
                        source.size_bytes - 1,
                        source.modified_ns - 1,
                        "png",
                        "png",
                        False,
                    ),
                ),
            ),
        )
        plan = prepare_sync_plan(host, ipod, device.active.library)
        request = SyncExecutionRequest(
            SyncPlan(
                tuple(
                    item for item in plan.items if item.action is SyncPlanAction.UPDATE
                )
            ),
            host,
            ipod,
            device.active,
            1,
            1,
        )
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert not (device.root / str(old.path)).exists()
        assert result.active is not None and result.active.library.photos is not None
        assert result.active.library.photos.photos[0].photo_id == old.image_id
    finally:
        device.coordinator.close()


class _MissingTools(_AvailableTools):
    def preflight(self, *, checkpoint: Callable[[], None]) -> MediaTools:
        raise ValueError(
            "FFmpeg, FFprobe and fpcalc are missing. Install them and retry."
        )


class _Executor(SyncExecutor):
    """Replace CPU codec work only; retain the real orchestration and persistence."""

    def _prepare_one(
        self,
        request: SyncExecutionRequest,
        item: SyncPlanItem,
        source: HostMediaSource,
        track: Track,
        tools: MediaTools,
        checkpoint: Callable[[], None],
    ) -> _PreparedTrack:
        del tools
        checkpoint()
        if track.title == "Failure":
            raise ValueError("The selected encoder could not decode this source.")
        with ExitStack() as lifetime:
            observed = LocalHostFile.observe(source.path)
            if (source.size_bytes, source.modified_ns) != (
                observed.size_bytes,
                observed.modified_ns,
            ):
                raise ValueError("Source changed since scanning")
            captured = lifetime.enter_context(
                capture_host_file(source.path, checkpoint=checkpoint)
            )
            location = f"iPod_Control/Music/F00/sync-{track.track_id}.m4a"
            incoming = replace(
                track,
                track_id=0,
                size_bytes=captured.fingerprint.size,
                metadata=replace(track.metadata, location=location),
            )
            media = prepared_audio(
                0,
                FileDependency(
                    location, captured.fingerprint.size, captured.fingerprint.sha256
                ),
                AudioEncoding.AAC,
            )
            song = ImportedSong(
                incoming,
                LibraryMediaSource(captured.snapshot, captured.fingerprint, media),
            )
            provenance = SyncedTrack(
                DevicePath(location),
                source.acoustic_fingerprint or "1,2,3",
                SyncDetails(
                    datetime.now(UTC).isoformat(),
                    str(source.path),
                    source.size_bytes,
                    source.modified_ns,
                    "m4a",
                    "aac",
                    False,
                ),
            )
            return _PreparedTrack(item, song, provenance, lifetime.pop_all(), ())


def _host(tmp_path: Path, *names: str, playlists: bool = False) -> HostMediaLibrary:
    tracks: list[Track] = []
    sources: list[HostMediaSource] = []
    for index, name in enumerate(names, 100):
        path = tmp_path / f"{name}.m4a"
        path.write_bytes(f"Prepared media for {name}".encode())
        observed = LocalHostFile.observe(HostPath(path))
        tracks.append(
            Track(
                index,
                name,
                "Artist",
                "Album",
                1000,
                size_bytes=observed.size_bytes,
                bitrate_kbps=128,
                metadata=TrackMetadata(
                    location=str(path),
                    sample_rate_hz=44100,
                    file_format="AAC audio file",
                ),
            )
        )
        sources.append(
            HostMediaSource(
                observed.path,
                HostMediaFileKind.AUDIO,
                observed.size_bytes,
                observed.modified_ns,
                f"{index},2,3",
            )
        )
    return HostMediaLibrary(
        LibrarySnapshot(
            tracks=tuple(tracks),
            playlists=(
                Playlist(
                    1,
                    "Host Playlist",
                    entries=playlist_entries(track.track_id for track in tracks),
                ),
            )
            if playlists
            else (),
        ),
        tuple(sources),
        (),
        HostMediaCacheStats(),
    )


def _ipod(device: Device) -> IPodMediaLibrary:
    records: list[IPodTrackFingerprint] = []
    images: list[IPodImageFingerprint] = []
    with device.coordinator.sync_session(device.active) as session:
        for track in device.active.library.tracks:
            path = DevicePath(track.metadata.location)
            observed = session.stat(path)
            records.append(
                IPodTrackFingerprint(
                    0 if track.ipod is None else track.ipod.db_track_id,
                    track.track_id,
                    path,
                    observed.size,
                    observed.modified_ns,
                    f"{track.track_id},55,99",
                )
            )
        for photo in (
            ()
            if device.active.library.photos is None
            else device.active.library.photos.photos
        ):
            representation = next(
                item
                for item in photo.representations
                if item.kind is PhotoRepresentationKind.FULL_RESOLUTION
            )
            path = DevicePath(representation.relative_path)
            observed_file = session.fingerprint(path)
            images.append(
                IPodImageFingerprint(
                    photo.photo_id,
                    path,
                    observed_file.size,
                    observed_file.modified_ns,
                    observed_file.sha256,
                )
            )
    return IPodMediaLibrary(
        tuple(records), tuple(images), (), IPodMediaCacheStats(), None, False
    )


def _request(
    device: Device, host: HostMediaLibrary, *, update: bool = False
) -> SyncExecutionRequest:
    ipod = _ipod(device)
    if update:
        source = host.sources[0]
        prior = SyncDetails(
            "2026-01-01T00:00:00+00:00",
            str(source.path),
            source.size_bytes - 1,
            source.modified_ns - 1,
            "m4a",
            "aac",
            False,
        )
        ipod = replace(
            ipod, tracks=(replace(ipod.tracks[0], sync=prior), *ipod.tracks[1:])
        )
    comparison = prepare_sync_plan(host, ipod, device.active.library)
    plan = SyncPlan(
        tuple(
            item
            for item in comparison.items
            if item.action is not SyncPlanAction.REMOVE
        )
    )
    return SyncExecutionRequest(plan, host, ipod, device.active, 1, 1)


def test_add_and_playlist_publish_before_successful_sync_history(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        host = _host(tmp_path, "New song", playlists=True)
        request = _request(device, host)
        helper = device.root / str(LIBRARY_SYNC_HELPER_PATH)
        observed_phases: list[str] = []

        def progress(event: WriteProgress) -> None:
            observed_phases.append(event.phase)
            if "sync.helper" not in observed_phases:
                assert not helper.exists()

        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, progress, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.playlist_change_count == 1
        assert result.active is not None
        added = next(
            track for track in result.active.library.tracks if track.title == "New song"
        )
        assert (device.root / added.metadata.location).read_bytes() == Path(
            host.sources[0].path
        ).read_bytes()
        assert re.fullmatch(
            r"iPod_Control/Music/F\d{2}/[A-Z]{4}\.m4a", added.metadata.location
        )
        playlist = next(
            playlist
            for playlist in result.active.library.playlists
            if playlist.name == "Host Playlist"
        )
        assert playlist.track_ids == (added.track_id,)
        data = json.loads(helper.read_bytes())
        synced = [record for record in data["tracks"] if record["sync"] is not None]
        assert len(synced) == 1
        assert synced[0]["path"] == added.metadata.location
        assert synced[0]["sync"]["host_path_hint"] == str(host.sources[0].path)
        assert observed_phases.index("save.storage.committed") < observed_phases.index(
            "sync.helper"
        )
        assert result.recovery_path == ""
        assert not tuple(device.root.glob(".iopenpod-recovery/*/transaction.json"))
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("shared", [False, True])
def test_update_keeps_track_identity_and_only_removes_unreferenced_old_media(
    tmp_path: Path, shared: bool
) -> None:
    device = build_device(tmp_path, shared_media=shared)
    try:
        host = _host(tmp_path, "Replacement")
        request = _request(device, host, update=True)
        original = request.source.library.tracks[0]
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        updated = next(
            track
            for track in result.active.library.tracks
            if track.title == "Replacement"
        )
        assert updated.track_id == original.track_id
        assert updated.ipod is not None and original.ipod is not None
        assert updated.ipod.db_track_id == original.ipod.db_track_id
        assert updated.metadata.location != original.metadata.location
        assert re.fullmatch(
            r"iPod_Control/Music/F\d{2}/[A-Z]{4}\.m4a", updated.metadata.location
        )
        assert (device.root / original.metadata.location).exists() is shared
        assert (device.root / updated.metadata.location).exists()
    finally:
        device.coordinator.close()


def test_bad_track_yields_safe_partial_success_without_partial_playlist(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, "Good", "Failure", playlists=True))
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.PARTIAL, result.issues
        assert result.active is not None
        assert "Good" in {track.title for track in result.active.library.tracks}
        assert "Failure" not in {track.title for track in result.active.library.tracks}
        assert not any(
            playlist.name == "Host Playlist"
            for playlist in result.active.library.playlists
        )
        assert len(result.completed) == 1
        assert result.playlist_change_count == 0
        assert any(
            issue.code == "sync.playlist_changes_skipped" for issue in result.issues
        )
        assert any(issue.code == "sync.item_failed" for issue in result.issues)
        assert result.helper is not None
        assert (
            len([track for track in result.helper.tracks if track.sync is not None])
            == 1
        )
    finally:
        device.coordinator.close()


def test_changed_host_is_skipped_without_blocking_other_tracks(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, "Good", "Changed"))
        Path(request.host.sources[1].path).write_bytes(b"edited since scan")
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.PARTIAL, result.issues
        assert len(result.completed) == 1
    finally:
        device.coordinator.close()


def test_missing_tools_fail_before_device_mutation(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, "Good"))
        result = _Executor(device.coordinator, transcoder=_MissingTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.FAILED
        assert "FFmpeg, FFprobe and fpcalc" in result.issues[-1].detail
        device.assert_original()
        assert not (device.root / str(LIBRARY_SYNC_HELPER_PATH)).exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "phase", ["sync.prepare", "save.storage.staging", "save.storage.prepared"]
)
def test_cancellation_cleans_staged_files_without_sync_history(
    tmp_path: Path, phase: str
) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, "Good"))
        cancelled = Event()

        def progress(event: WriteProgress) -> None:
            if event.phase == phase:
                cancelled.set()

        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, progress, cancelled
        )
        assert result.status is SyncExecutionStatus.CANCELLED, result.issues
        device.assert_original()
        assert {
            path.relative_to(device.root).as_posix()
            for path in (device.root / "iPod_Control/Music").rglob("*")
            if path.is_file()
        } == {track.metadata.location for track in request.source.library.tracks}
        assert not (device.root / str(LIBRARY_SYNC_HELPER_PATH)).exists()
        assert not tuple(device.root.glob(".iopenpod-recovery/*/transaction.json"))
    finally:
        device.coordinator.close()


def test_helper_failure_reports_committed_library_without_reverting_it(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, "Good"))

        def progress(event: WriteProgress) -> None:
            if event.phase == "sync.helper":
                helper = device.root / str(LIBRARY_SYNC_HELPER_PATH)
                helper.parent.mkdir(parents=True, exist_ok=True)
                helper.write_bytes(b"malformed history must be preserved")

        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, progress, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is None
        assert any(issue.code == "sync.helper_failed" for issue in result.issues)
        assert (
            device.root / str(LIBRARY_SYNC_HELPER_PATH)
        ).read_bytes() == b"malformed history must be preserved"
        assert any(track.title == "Good" for track in result.active.library.tracks)
    finally:
        device.coordinator.close()


def test_interrupted_publication_restores_originals_and_cleans_new_media(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, "Good"))
        interrupted = False

        def progress(event: WriteProgress) -> None:
            nonlocal interrupted
            if event.phase == "save.storage.publishing" and not interrupted:
                interrupted = True
                raise OSError("simulated removable-media write interruption")

        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, progress, Event()
        )
        assert interrupted
        assert result.status is SyncExecutionStatus.FAILED, result.issues
        device.assert_original()
        assert {
            path.relative_to(device.root).as_posix()
            for path in (device.root / "iPod_Control/Music").rglob("*")
            if path.is_file()
        } == {track.metadata.location for track in request.source.library.tracks}
        assert result.recovery_path == ""
        assert not tuple(device.root.glob(".iopenpod-recovery/*/transaction.json"))
        assert not (device.root / str(LIBRARY_SYNC_HELPER_PATH)).exists()
    finally:
        device.coordinator.close()


def test_next_sync_refuses_pending_journal_even_without_previous_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, "Good"))
        cancelled = Event()

        def progress(event: WriteProgress) -> None:
            if event.phase == "save.storage.prepared":
                cancelled.set()

        def disconnected(*_args: object) -> None:
            raise OSError("The iPod disconnected during recovery")

        monkeypatch.setattr(device.coordinator, "recover_failed_sync", disconnected)
        first = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, progress, cancelled
        )
        assert first.status is SyncExecutionStatus.RECOVERY_REQUIRED
        assert first.recovery_path
        second = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert second.status is SyncExecutionStatus.RECOVERY_REQUIRED, second.issues
        assert second.recovery_path == first.recovery_path
        assert not (device.root / str(LIBRARY_SYNC_HELPER_PATH)).exists()
    finally:
        device.coordinator.close()


def test_duplicate_review_action_is_rejected_before_preparation(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, "Good"))
        request = replace(
            request, plan=SyncPlan((*request.plan.items, *request.plan.items))
        )
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.FAILED
        assert "repeats a Host source" in result.issues[-1].detail
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe", "fpcalc")),
    reason="Sync media tools required",
)
def test_real_aac_passes_through_full_sync_without_reencoding(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        source = tmp_path / "real.m4a"
        data = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
        source.write_bytes(data)
        observed = LocalHostFile.observe(HostPath(source))
        host = HostMediaLibrary(
            LibrarySnapshot(
                tracks=(
                    Track(
                        100,
                        "Real audio",
                        "",
                        "",
                        1000,
                        metadata=TrackMetadata(location=str(source)),
                    ),
                )
            ),
            (
                HostMediaSource(
                    observed.path,
                    HostMediaFileKind.AUDIO,
                    observed.size_bytes,
                    observed.modified_ns,
                    "100,2,3",
                ),
            ),
            (),
            HostMediaCacheStats(),
        )
        result = SyncExecutor(device.coordinator).execute(
            _request(device, host), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        added = next(
            track
            for track in result.active.library.tracks
            if track.title == "Real audio"
        )
        assert (device.root / added.metadata.location).read_bytes() == data
        assert added.metadata.file_format == "AAC audio file"
        assert result.helper is not None
        synced = next(track for track in result.helper.tracks if track.sync is not None)
        assert synced.sync is not None and synced.sync.was_transcoded is False
    finally:
        device.coordinator.close()


def test_source_changed_during_photo_preparation_is_skipped_before_commit(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        tracks, photos = _host(tmp_path, "Changed later"), _photo_host(tmp_path)
        host = replace(
            tracks,
            snapshot=replace(tracks.snapshot, photos=photos.snapshot.photos),
            sources=(*tracks.sources, *photos.sources),
        )
        request = _request(device, host)

        def progress(event: WriteProgress) -> None:
            if event.phase == "sync.photos":
                Path(tracks.sources[0].path).write_bytes(
                    b"new source after Track preparation"
                )

        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, progress, Event()
        )
        assert result.status is SyncExecutionStatus.PARTIAL, result.issues
        assert result.active is not None and result.active.library.photos is not None
        assert not any(
            track.title == "Changed later" for track in result.active.library.tracks
        )
        assert len(result.active.library.photos.photos) == 1
        assert any(issue.code == "sync.source_changed" for issue in result.issues)
    finally:
        device.coordinator.close()


def test_shared_album_artwork_is_captured_once_and_referenced_by_new_tracks(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        host = _host(tmp_path, "First", "Second")
        path = tmp_path / "cover.png"
        Image.new("RGB", (180, 180), "blue").save(path)
        observed = LocalHostFile.observe(HostPath(path))
        artwork_source = HostMediaArtworkSource(
            123,
            HostArtworkKind.FOLDER,
            observed.path,
            observed.size_bytes,
            observed.modified_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        host = replace(
            host,
            snapshot=replace(
                host.snapshot,
                tracks=tuple(
                    replace(track, artwork_id=123) for track in host.snapshot.tracks
                ),
            ),
            artwork_sources=(artwork_source,),
        )
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            _request(device, host), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        incoming = tuple(
            track
            for track in result.active.library.tracks
            if track.title in ("First", "Second")
        )
        assert len(incoming) == 2
        assert incoming[0].artwork_id == incoming[1].artwork_id > 0
        assert all(track.metadata.artwork_count > 0 for track in incoming)
    finally:
        device.coordinator.close()


def test_sync_preserves_unresolved_playlist_and_photo_music_references(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path))
        unresolved = replace(
            request.source.library,
            playlists=(
                Playlist(
                    42, "Retained", entries=(PlaylistEntry("retained-occurrence", 999),)
                ),
            ),
            photos=PhotoLibrary(
                albums=(PhotoAlbum(100, "Slideshow", play_music=True),)
            ),
        )
        request = replace(request, source=replace(request.source, library=unresolved))
        draft, completed, changed = _draft(request, [], [])
        assert draft.snapshot == unresolved
        assert not completed and not changed
    finally:
        device.coordinator.close()


class _HostCleanupFailureExecutor(_Executor):
    def _prepare_one(
        self,
        request: SyncExecutionRequest,
        item: SyncPlanItem,
        source: HostMediaSource,
        track: Track,
        tools: MediaTools,
        checkpoint: Callable[[], None],
    ) -> _PreparedTrack:
        result = super()._prepare_one(request, item, source, track, tools, checkpoint)

        def cleanup_failure() -> None:
            raise OSError("Temporary Host staging was held open by another process")

        result.resources.callback(cleanup_failure)
        return result


def test_host_cleanup_failure_does_not_hide_successful_device_commit(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        result = _HostCleanupFailureExecutor(
            device.coordinator, transcoder=_AvailableTools()
        ).execute(
            _request(device, _host(tmp_path, "Committed")), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        assert any(track.title == "Committed" for track in result.active.library.tracks)
        assert any(issue.code == "sync.host_cleanup_pending" for issue in result.issues)
        assert result.recovery_path == ""
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("cancelled", [False, True])
def test_completed_cleanup_with_unconfirmed_flush_does_not_offer_missing_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancelled: bool,
) -> None:
    device = build_device(tmp_path)
    try:
        cancellation = Event()
        cleanup = (
            device.coordinator.recover_failed_sync
            if cancelled
            else device.coordinator.finalize_sync_success
        )

        def flush_pending(expected: object, path: str) -> None:
            assert expected is request.source or expected is device.active
            cleanup(device.active, path)
            raise SyncCleanupCompletedError(
                "The final volume flush failed after cleanup"
            )

        request = _request(device, _host(tmp_path, "Song"))
        monkeypatch.setattr(
            device.coordinator,
            "recover_failed_sync" if cancelled else "finalize_sync_success",
            flush_pending,
        )

        def progress(event: WriteProgress) -> None:
            if cancelled and event.phase == "save.storage.prepared":
                cancellation.set()

        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, progress, cancellation
        )
        assert result.status is (
            SyncExecutionStatus.CANCELLED if cancelled else SyncExecutionStatus.SUCCESS
        ), result.issues
        assert result.recovery_path == ""
        assert any(
            issue.code == "sync.cleanup_flush_pending" for issue in result.issues
        )
        assert not any(
            issue.code in ("sync.cleanup_pending", "sync.recovery_required")
            for issue in result.issues
        )
        assert not tuple(device.root.glob(".iopenpod-recovery/*/transaction.json"))
    finally:
        device.coordinator.close()


def test_scan_marks_playlists_with_unresolved_references_as_incomplete(
    tmp_path: Path,
) -> None:
    library = _build_library(
        (
            _CachedPlaylistRecord(
                HostPath(tmp_path / "missing.m3u"),
                HostMediaFileKind.PLAYLIST,
                20,
                1,
                title="Missing reference",
                references=(HostPath(tmp_path / "missing.mp3"),),
            ),
            _CachedPlaylistRecord(
                HostPath(tmp_path / "partial.m3u"),
                HostMediaFileKind.PLAYLIST,
                20,
                1,
                warning="A network reference was excluded",
                title="Partial parse",
            ),
        ),
        (),
        HostMediaCacheStats(),
    )
    assert set(library.incomplete_playlist_ids) == {
        playlist.playlist_id for playlist in library.snapshot.playlists
    }


def test_incomplete_host_playlist_cannot_trim_existing_device_memberships(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        original_ids = tuple(track.track_id for track in device.active.library.tracks)
        review = device.prepare(
            replace(
                device.active.library,
                playlists=(
                    *device.active.library.playlists,
                    Playlist(
                        -1, "Host Playlist", entries=playlist_entries(original_ids)
                    ),
                ),
            )
        )
        assert device.save(review).active is not None
        host = _host(tmp_path, "New media", playlists=True)
        host = replace(
            host, incomplete_playlist_ids=(host.snapshot.playlists[0].playlist_id,)
        )
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            _request(device, host), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        playlist = next(
            item
            for item in result.active.library.playlists
            if item.name == "Host Playlist"
        )
        assert playlist.track_ids == original_ids
        assert any(issue.code == "sync.playlist_incomplete" for issue in result.issues)
    finally:
        device.coordinator.close()


def test_playlist_only_creates_empty_playlist_and_commits_sync_history(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, playlists=True))
        assert request.plan.change_count == 0
        assert preview_playlist_sync(
            request.plan, request.host, request.ipod, request.source
        ) == (PlaylistSyncChange("Host Playlist", "create", 0, 0, False),)
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        assert result.playlist_change_count == 1 and result.completed == ()
        assert (
            next(
                item
                for item in result.active.library.playlists
                if item.name == "Host Playlist"
            ).track_ids
            == ()
        )
        assert result.recovery_path == ""
    finally:
        device.coordinator.close()


def test_playlist_only_reorders_existing_tracks_with_identical_preview(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        original_ids = tuple(track.track_id for track in device.active.library.tracks)
        review = device.prepare(
            replace(
                device.active.library,
                playlists=(
                    *device.active.library.playlists,
                    Playlist(
                        -1, "Host Playlist", entries=playlist_entries(original_ids)
                    ),
                ),
            )
        )
        assert device.save(review).active is not None
        host = _host(tmp_path, "One", "Two", playlists=True)
        ipod = _ipod(device)
        host = replace(
            host,
            sources=tuple(
                replace(source, acoustic_fingerprint=record.acoustic_fingerprint)
                for source, record in zip(host.sources, ipod.tracks, strict=True)
            ),
            snapshot=replace(
                host.snapshot,
                playlists=(
                    replace(
                        host.snapshot.playlists[0],
                        entries=playlist_entries((101, 100)),
                    ),
                ),
            ),
        )
        request = _request(device, host)
        assert request.plan.change_count == 0
        assert preview_playlist_sync(
            request.plan, host, request.ipod, request.source
        ) == (PlaylistSyncChange("Host Playlist", "update", 0, 0, True),)
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert result.playlist_change_count == 1
        assert (
            next(
                item
                for item in result.active.library.playlists
                if item.name == "Host Playlist"
            ).track_ids
            == original_ids[::-1]
        )
    finally:
        device.coordinator.close()


def test_preview_preserves_excluded_update_correlation_and_duplicate_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    try:
        host = _host(tmp_path, "Replacement", playlists=True)
        host = replace(
            host,
            snapshot=replace(
                host.snapshot,
                playlists=(
                    replace(
                        host.snapshot.playlists[0], entries=playlist_entries((100, 100))
                    ),
                ),
            ),
        )
        request = replace(_request(device, host, update=True), plan=SyncPlan(()))

        def forbid_io(*args: object, **kwargs: object) -> None:
            pytest.fail("Playlist preview must perform no filesystem I/O")

        with monkeypatch.context() as context:
            context.setattr(LocalHostFile, "observe", forbid_io)
            assert preview_playlist_sync(
                request.plan, host, request.ipod, request.source
            ) == (PlaylistSyncChange("Host Playlist", "create", 2, 0, False),)
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.playlist_change_count == 1
        assert (
            next(
                item
                for item in result.active.library.playlists
                if item.name == "Host Playlist"
            ).track_ids
            == (request.source.library.tracks[0].track_id,) * 2
        )
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("with_media", [False, True])
def test_stale_playlist_source_skips_reviewed_playlist_but_allows_safe_media(
    tmp_path: Path, with_media: bool
) -> None:
    device = build_device(tmp_path)
    try:
        host = _host(tmp_path, *(("New song",) if with_media else ()), playlists=True)
        path = tmp_path / "Host Playlist.m3u"
        path.write_text("#EXTM3U\n", encoding="utf-8")
        facts = LocalHostFile.observe(HostPath(path))
        host = replace(
            host,
            sources=(
                *host.sources,
                HostMediaSource(
                    facts.path,
                    HostMediaFileKind.PLAYLIST,
                    facts.size_bytes,
                    facts.modified_ns,
                ),
            ),
        )
        request = _request(device, host)
        assert preview_playlist_sync(request.plan, host, request.ipod, request.source)
        path.write_text("#EXTM3U\nchanged after review\n", encoding="utf-8")
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is (
            SyncExecutionStatus.PARTIAL if with_media else SyncExecutionStatus.FAILED
        ), result.issues
        assert result.playlist_change_count == 0
        assert len(result.completed) == int(with_media)
        assert any(
            issue.code == "sync.playlist_source_changed" for issue in result.issues
        )
        assert any(
            issue.code == "sync.playlist_changes_skipped" for issue in result.issues
        )
        if with_media:
            assert result.active is not None
            assert not any(
                item.name == "Host Playlist" for item in result.active.library.playlists
            )
        else:
            device.assert_original()
            assert not (device.root / str(LIBRARY_SYNC_HELPER_PATH)).exists()
    finally:
        device.coordinator.close()


def test_disabling_playlist_reconciliation_still_cleans_explicit_track_removal(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        original_ids = tuple(track.track_id for track in device.active.library.tracks)
        review = device.prepare(
            replace(
                device.active.library,
                playlists=(
                    *device.active.library.playlists,
                    Playlist(
                        -1, "Retained Playlist", entries=playlist_entries(original_ids)
                    ),
                ),
            )
        )
        assert device.save(review).active is not None
        request = _request(device, _host(tmp_path, playlists=True))
        comparison = prepare_sync_plan(
            request.host, request.ipod, request.source.library
        )
        request = replace(
            request,
            plan=SyncPlan((comparison.items[0],)),
            reconcile_playlists=False,
        )
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.playlist_change_count == 0
        assert not any(
            item.name == "Host Playlist" for item in result.active.library.playlists
        )
        assert (
            next(
                item
                for item in result.active.library.playlists
                if item.name == "Retained Playlist"
            ).track_ids
            == original_ids[1:]
        )
    finally:
        device.coordinator.close()


def test_prepared_silent_video_uses_motion_duration_without_audio_sample_rate(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _host(tmp_path, "Silent"))
        host = replace(request.host.snapshot.tracks[0], media_types=(MediaType.VIDEO,))
        with capture_host_file(
            request.host.sources[0].path, checkpoint=lambda: None
        ) as captured:
            inspection = _parse(
                json.dumps(
                    {
                        "format": {
                            "format_name": "mov",
                            "size": str(captured.fingerprint.size),
                        },
                        "streams": [
                            {
                                "index": 0,
                                "codec_type": "video",
                                "codec_name": "h264",
                                "duration": "1.5",
                                "bit_rate": "800000",
                                "disposition": {"attached_pic": 0},
                            }
                        ],
                    }
                ).encode(),
                captured,
            )
            prepared = PreparedTranscode(
                captured.snapshot,
                inspection,
                VideoEncoding.MP4,
                captured.fingerprint,
                True,
            )
            song = _song(request, host, prepared)
        assert song.track.length_ms == 1500
        assert song.track.metadata.sample_rate_hz == 0
        assert song.track.bitrate_kbps == 800
        assert song.source.media.content is MediaContent.VIDEO
        assert song.track.metadata.location.endswith(".m4v")
        assert len(Path(song.track.metadata.location).stem) == 4
    finally:
        device.coordinator.close()


def test_short_filenames_avoid_untracked_files_and_match_committed_sync_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def first_slot(_capacity: int) -> int:
        return 0

    monkeypatch.setattr("iOpenPod.app.media.music_paths.randbelow", first_slot)
    device = build_device(tmp_path)
    try:
        occupied = device.root / "iPod_Control/Music/F00/AAAA.m4a"
        occupied.write_bytes(b"untracked file must survive")
        request = _request(device, _host(tmp_path, "First", "Second"))
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        incoming = {
            track.title: track.metadata.location
            for track in result.active.library.tracks
            if track.title in {"First", "Second"}
        }
        assert len(set(incoming.values())) == 2
        assert "iPod_Control/Music/F00/AAAA.m4a" not in incoming.values()
        for source in request.host.sources:
            location = incoming[source.path.path.stem]
            assert re.fullmatch(r"iPod_Control/Music/F\d{2}/[A-Z]{4}\.m4a", location)
            assert (device.root / location).read_bytes() == Path(
                source.path
            ).read_bytes()
            recorded = next(
                record
                for record in result.helper.tracks
                if str(record.path) == location
            )
            assert recorded.sync is not None
            assert recorded.sync.host_path_hint == str(source.path)
        assert occupied.read_bytes() == b"untracked file must survive"
    finally:
        device.coordinator.close()


def test_replacement_reserves_its_old_four_character_filename_until_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def first_slot(_capacity: int) -> int:
        return 0

    monkeypatch.setattr("iOpenPod.app.media.music_paths.randbelow", first_slot)
    device = build_device(tmp_path)
    try:
        executor = _Executor(device.coordinator, transcoder=_AvailableTools())
        first = executor.execute(
            _request(device, _host(tmp_path, "First replacement"), update=True),
            lambda _: None,
            Event(),
        )
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert first.active is not None
        first_track = first.active.library.tracks[0]
        assert first_track.metadata.location == "iPod_Control/Music/F00/AAAA.m4a"
        second = executor.execute(
            _request(device, _host(tmp_path, "Second replacement"), update=True),
            lambda _: None,
            Event(),
        )
        assert second.status is SyncExecutionStatus.SUCCESS, second.issues
        assert second.active is not None
        second_track = second.active.library.tracks[0]
        assert second_track.track_id == first_track.track_id
        assert second_track.metadata.location == "iPod_Control/Music/F01/AAAA.m4a"
        assert not (device.root / first_track.metadata.location).exists()
        assert (device.root / second_track.metadata.location).is_file()
    finally:
        device.coordinator.close()


def test_filename_failure_keeps_failed_replacement_and_commits_other_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed_call = 0

    class FirstFilenameFails(MusicPathAllocator):
        calls = 0

        def allocate(
            self,
            extension: str,
            *,
            checkpoint: Callable[[], None] | None = None,
        ) -> str:
            self.calls += 1
            if self.calls == failed_call:
                raise ValueError("The selected Music folder is inaccessible")
            return super().allocate(extension, checkpoint=checkpoint)

    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.MusicPathAllocator", FirstFilenameFails
    )
    device = build_device(tmp_path)
    try:
        request = _request(
            device, _host(tmp_path, "Skipped replacement", "Good"), update=True
        )
        failed_call = next(
            index
            for index, item in enumerate(request.plan.items, 1)
            if item.action is SyncPlanAction.UPDATE
        )
        original = request.source.library.tracks[0]
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.PARTIAL, result.issues
        assert result.active is not None and result.helper is not None
        assert (
            next(
                track
                for track in result.active.library.tracks
                if track.track_id == original.track_id
            )
            == original
        )
        assert any(track.title == "Good" for track in result.active.library.tracks)
        assert not any(
            track.title == "Skipped replacement"
            for track in result.active.library.tracks
        )
        assert len(result.completed) == 1
        retained = next(
            record
            for record in result.helper.tracks
            if str(record.path) == original.metadata.location
        )
        assert retained.sync == request.ipod.tracks[0].sync
        assert (
            sum(
                record.sync is not None and record.path != retained.path
                for record in result.helper.tracks
            )
            == 1
        )
        issue = next(
            issue for issue in result.issues if issue.code == "sync.filename_failed"
        )
        assert "rescan and retry" in issue.message
        assert "inaccessible" in issue.detail
    finally:
        device.coordinator.close()


def test_short_filename_appearing_after_review_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    try:
        save = device.coordinator.save_library
        unexpected: list[Path] = []

        def collide_after_review(
            review: LibraryReview,
            expected: ActiveIPod,
            progress: Callable[[WriteProgress], None],
            cancelled: Event,
        ) -> LibrarySaveResult:
            location = next(
                item.path
                for item in review.file_changes
                if item.action == "write"
                and item.path.startswith("iPod_Control/Music/")
            )
            path = device.root / location
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"external file appeared after Review")
            unexpected.append(path)
            return save(review, expected, progress, cancelled)

        monkeypatch.setattr(device.coordinator, "save_library", collide_after_review)
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            _request(device, _host(tmp_path, "New song")), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.FAILED, result.issues
        device.assert_original()
        assert len(unexpected) == 1
        assert unexpected[0].read_bytes() == b"external file appeared after Review"
        assert not (device.root / str(LIBRARY_SYNC_HELPER_PATH)).exists()
    finally:
        device.coordinator.close()
