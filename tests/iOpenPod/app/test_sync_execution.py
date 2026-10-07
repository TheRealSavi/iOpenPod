"""Reviewed Sync exercises actual database verification and Storage publication.

Private imports deliberately isolate scan, draft, and prepared-media regressions
without exposing implementation helpers as application API.
"""

import base64
import hashlib
import io
import json
import re
import shutil
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Protocol, cast

import pytest
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from PIL import Image
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_media_lyrics import WORDS
from tests.iOpenPod.app.test_music_import import FIXTURES

from iOpenPod.app import sync_execution
from iOpenPod.app.display_text import SourceText
from iOpenPod.app.export_tagging import ExportMediaTagger
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
from iOpenPod.app.media.lyrics import embedded_lyrics, rewrite_lyrics
from iOpenPod.app.media.music_paths import MusicPathAllocator
from iOpenPod.app.media.progress import MediaPreparationPhase, MediaPreparationProgress
from iOpenPod.app.media.transcoding import (
    MediaTranscoder,
    PreparedTranscode,
    VideoEncoding,
)
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services import library_resources
from iOpenPod.app.services.device_coordinator import SyncCleanupCompletedError
from iOpenPod.app.sync_execution import (
    PlaylistSyncChange,
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
    SyncOptions,
    _draft,  # pyright: ignore[reportPrivateUsage]
    _PreparedTrack,  # pyright: ignore[reportPrivateUsage]
    _song,  # pyright: ignore[reportPrivateUsage]
    preview_playlist_sync,
)
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanItem,
    host_path_identity,
    prepare_sync_plan,
    select_sync_plan,
)
from iPodDB.library import (
    AudioEncoding,
    CoverFormat,
    CoverPixelFormat,
    FileDependency,
    IPodLibrary,
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
from storage import (
    DevicePath,
    FilesystemSession,
    FlushResult,
    HostPath,
    StorageOperationError,
    TransactionRecovery,
    TransactionState,
    capture_host_file,
)
from storage.host_input import LocalHostFile
from storage.media_processing import MediaToolError, MediaTools


class _SyncArtworkFrame(Protocol):
    data: bytes


class _SyncID3TagView(Protocol):
    def getall(self, key: str) -> list[_SyncArtworkFrame]: ...

    def __getitem__(self, key: str) -> object: ...


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


@pytest.mark.parametrize("budget", [10, 2 * 1024 * 1024 * 1024])
def test_photo_creates_verified_library_files_and_sync_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    budget: int,
) -> None:
    monkeypatch.setattr(sync_execution, "_PHOTO_MEMORY_BUDGET", budget)
    device = build_device(tmp_path)
    try:
        request = _request(device, _photo_host(tmp_path))
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert not any(
            issue.code == "sync.photo_disk_staging" for issue in result.issues
        )
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


def test_large_animated_photo_converts_and_matches_again_after_reload(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        path = tmp_path / "animation.gif"
        Image.new("RGB", (80, 60), "red").save(
            path,
            save_all=True,
            append_images=[Image.new("RGB", (80, 60), "blue")],
            duration=100,
        )
        # Oversized container without putting a large binary fixture in the repo.
        with path.open("r+b") as stream:
            stream.truncate(65 * 1024 * 1024)
        facts = LocalHostFile.observe(HostPath(path))
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        base = _photo_host(tmp_path)
        host = replace(
            base,
            snapshot=replace(
                base.snapshot,
                photos=PhotoLibrary(
                    photos=(
                        Photo(
                            1,
                            representations=(
                                PhotoRepresentation(
                                    PhotoRepresentationKind.FULL_RESOLUTION,
                                    0,
                                    str(path),
                                    0,
                                    facts.size_bytes,
                                    80,
                                    60,
                                ),
                            ),
                        ),
                    )
                ),
            ),
            sources=(
                HostMediaSource(
                    facts.path,
                    HostMediaFileKind.PHOTO,
                    facts.size_bytes,
                    facts.modified_ns,
                    content_sha256=digest,
                ),
            ),
        )
        result = _Executor(device.coordinator, transcoder=_MissingTools()).execute(
            _request(device, host),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        synced = result.helper.images[0]
        assert synced.sync is not None and synced.sync.was_transcoded
        assert synced.sync.host_content_sha256 == digest
        assert synced.content_sha256 != digest
        assert str(synced.path).endswith(".png")
        with Image.open(device.root / str(synced.path)) as image:
            assert image.size == (80, 60) and image.convert("RGB").getpixel((0, 0)) == (
                255,
                0,
                0,
            )
        assert path.stat().st_size == facts.size_bytes
        reloaded = device.coordinator.scan_ipod_media(
            result.active, lambda _: None, Event()
        )
        plan = prepare_sync_plan(host, reloaded, result.active.library)
        assert (
            next(item for item in plan.items if item.host_path == str(path)).action
            is SyncPlanAction.UNCHANGED
        )
        assert any(issue.code == "sync.photo_converted" for issue in result.issues)
        changed = replace(
            host, sources=(replace(host.sources[0], content_sha256="0" * 64),)
        )
        changed_plan = prepare_sync_plan(changed, reloaded, result.active.library)
        assert (
            next(
                item for item in changed_plan.items if item.host_path == str(path)
            ).action
            is SyncPlanAction.ATTENTION
        )
    finally:
        device.coordinator.close()


def test_restoration_cleanup_failure_has_truthful_result_and_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    try:
        finalize = FilesystemSession.finalize_transaction

        def fail_cleanup(
            session: FilesystemSession, recovery: TransactionRecovery
        ) -> FlushResult:
            if recovery.state is TransactionState.RESTORED:
                raise StorageOperationError("Simulated cleanup failure")
            return finalize(session, recovery)

        monkeypatch.setattr(FilesystemSession, "finalize_transaction", fail_cleanup)
        events: list[WriteProgress] = []

        def progress(event: WriteProgress) -> None:
            events.append(event)
            if event.phase == "save.storage.publishing":
                raise RuntimeError("Simulated publication interruption")

        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            _request(device, _host(tmp_path, "Good")),
            progress,
            Event(),
        )
        assert result.status is SyncExecutionStatus.RECOVERY_REQUIRED
        assert any(
            issue.code == "sync.restored_cleanup_pending" for issue in result.issues
        )
        assert not any(
            issue.code == "sync.recovery_required" for issue in result.issues
        )
        assert any(event.phase == "save.recovery.inspect" for event in events)
        assert any(event.phase == "save.recovery.restoring" for event in events)
        assert any(event.phase == "save.recovery.cleanup" for event in events)
        device.assert_original()
        monkeypatch.setattr(FilesystemSession, "finalize_transaction", finalize)

        def no_second_rollback(*args: object, **kwargs: object) -> None:
            pytest.fail("Verified restoration must not be repeated for cleanup")

        monkeypatch.setattr(
            FilesystemSession, "restore_transaction", no_second_rollback
        )
        device.coordinator.recover_sync_journal(result.recovery_path)
        assert not (device.root / result.recovery_path).exists()
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
        raise MediaToolError(
            "media.tools_missing",
            "FFmpeg and FFprobe are missing. Install them and retry.",
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
        activity: Callable[[MediaPreparationProgress], None],
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


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_preparation_reports_all_concurrent_tracks(
    tmp_path: Path, outcome: str
) -> None:
    release = Event()
    cancellation = Event()
    second_title = "Failure" if outcome == "failure" else "Second song"

    class ConcurrentExecutor(_Executor):
        def _prepare_one(
            self,
            request: SyncExecutionRequest,
            item: SyncPlanItem,
            source: HostMediaSource,
            track: Track,
            tools: MediaTools,
            checkpoint: Callable[[], None],
            activity: Callable[[MediaPreparationProgress], None],
        ) -> _PreparedTrack:
            activity(
                MediaPreparationProgress(
                    MediaPreparationPhase.CONVERTING,
                    "Preparing compatible media for this iPod",
                    30,
                    120,
                    2,
                )
            )
            assert release.wait(5), "Both active workers must be reported while running"
            return super()._prepare_one(
                request, item, source, track, tools, checkpoint, activity
            )

    device = build_device(tmp_path)
    observed: list[WriteProgress] = []
    started: set[str] = set()

    def progress(event: WriteProgress) -> None:
        observed.append(event)
        if event.current_item:
            started.add(event.current_item)
        started.update(item.name for item in event.active_items)
        if len(started) == 2:
            if outcome == "cancel":
                cancellation.set()
            release.set()

    try:
        host = _host(tmp_path, "First song", second_title)
        result = ConcurrentExecutor(
            device.coordinator, transcoder=_AvailableTools(), workers=2
        ).execute(_request(device, host), progress, cancellation)
        expected_status = {
            "success": SyncExecutionStatus.SUCCESS,
            "failure": SyncExecutionStatus.PARTIAL,
            "cancel": SyncExecutionStatus.CANCELLED,
        }
        assert result.status is expected_status[outcome], result.issues
        concurrent = next(event for event in observed if len(event.active_items) == 2)
        assert {item.name for item in concurrent.active_items} == {
            "First song",
            second_title,
        }
        assert all(
            item.progress.processed_seconds == 30 for item in concurrent.active_items
        )
        preparation = [event for event in observed if event.phase == "sync.prepare"]
        assert preparation[-1].active_items == ()
        assert preparation[-1].completed == 2
    finally:
        release.set()
        device.coordinator.close()


def test_add_and_playlist_publish_before_successful_sync_history(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        host = _host(tmp_path, "New song", playlists=True)
        request = _request(device, host)
        helper = device.root / str(LIBRARY_SYNC_HELPER_PATH)
        observed_phases: list[str] = []
        observed_progress: list[WriteProgress] = []

        def progress(event: WriteProgress) -> None:
            observed_phases.append(event.phase)
            observed_progress.append(event)
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
        track_progress = [
            event for event in observed_progress if event.phase == "sync.prepare"
        ]
        assert track_progress[0].completed == 0
        assert track_progress[0].total == 1
        assert track_progress[-1].completed == 1
        assert track_progress[-1].current_item == "New song"
        storage_progress = next(
            event
            for event in observed_progress
            if event.phase == "save.storage.publishing"
        )
        assert storage_progress.total is not None
        assert storage_progress.current_item
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
        assert updated.artwork_id == 0
        assert updated.ipod is not None and original.ipod is not None
        assert updated.ipod.db_track_id == original.ipod.db_track_id
        assert updated.metadata.location != original.metadata.location
        assert re.fullmatch(
            r"iPod_Control/Music/F\d{2}/[A-Z]{4}\.m4a", updated.metadata.location
        )
        assert (device.root / original.metadata.location).exists() is shared
        assert (device.root / updated.metadata.location).exists()
        assert result.helper is not None
        next_plan = prepare_sync_plan(host, result.helper, result.active.library)
        assert (
            next(
                item
                for item in next_plan.items
                if item.host_path == str(host.sources[0].path)
            ).action
            is SyncPlanAction.UNCHANGED
        )
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
        failure = next(
            issue for issue in result.issues if issue.code == "sync.item_failed"
        )
        assert isinstance(failure.message, SourceText)
        assert failure.message == (
            "Failure was skipped. No iPod copy was added. "
            "Correct the source or encoder settings and retry."
        )
        assert dict(failure.message.parameters) == {"name": "Failure"}
        assert "{name}" in failure.message.source
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
        assert "FFmpeg and FFprobe" in result.issues[-1].detail
        device.assert_original()
        assert not (device.root / str(LIBRARY_SYNC_HELPER_PATH)).exists()
    finally:
        device.coordinator.close()


def test_missing_audio_tools_do_not_block_photo_only_sync(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        request = _request(device, _photo_host(tmp_path))
        result = SyncExecutor(device.coordinator, transcoder=_MissingTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert len(result.completed) == 1
    finally:
        device.coordinator.close()


def test_missing_audio_tools_allow_independent_photos_in_a_mixed_sync(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        host = _host(tmp_path, "Unavailable audio")
        photos = _photo_host(tmp_path)
        host = replace(
            host,
            snapshot=replace(host.snapshot, photos=photos.snapshot.photos),
            sources=(*host.sources, *photos.sources),
        )
        result = SyncExecutor(device.coordinator, transcoder=_MissingTools()).execute(
            _request(device, host), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.PARTIAL, result.issues
        assert len(result.completed) == 1
        assert result.active is not None and result.active.library.photos is not None
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
@pytest.mark.parametrize("rockbox_metadata", [False, True])
@pytest.mark.parametrize("file_has_lyrics", [False, True])
def test_sync_writes_lyrics_to_media_and_prefers_existing_file_text(
    tmp_path: Path, rockbox_metadata: bool, file_has_lyrics: bool
) -> None:
    device = build_device(tmp_path)
    try:
        source = tmp_path / "lyrics.m4a"
        original = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
        source.write_bytes(
            rewrite_lyrics(original, source.name, WORDS)
            if file_has_lyrics
            else original
        )
        observed = LocalHostFile.observe(HostPath(source))
        host = HostMediaLibrary(
            LibrarySnapshot(
                tracks=(
                    Track(
                        100,
                        "Lyrics song",
                        "",
                        "",
                        1000,
                        metadata=TrackMetadata(
                            location=str(source),
                            lyrics="Stale database words" if file_has_lyrics else WORDS,
                        ),
                    ),
                )
            ),
            (
                HostMediaSource(
                    observed.path,
                    HostMediaFileKind.AUDIO,
                    observed.size_bytes,
                    observed.modified_ns,
                ),
            ),
            (),
            HostMediaCacheStats(),
        )
        request = _request(device, host)
        request = replace(
            request,
            plan=select_sync_plan(
                request.plan,
                selected_host_paths=frozenset({host_path_identity(str(source))}),
                selected_ipod_removals=frozenset(),
            ),
            options=SyncOptions(rockbox_metadata=rockbox_metadata),
        )
        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        added = next(
            track
            for track in result.active.library.tracks
            if track.title == "Lyrics song"
        )
        assert added.metadata.lyrics == WORDS
        assert added.metadata.has_lyrics
        assert (
            embedded_lyrics(
                MP4(device.root / added.metadata.location)  # type: ignore[no-untyped-call]
            )
            == WORDS
        )
    finally:
        device.coordinator.close()


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe", "fpcalc")),
    reason="Sync media tools required",
)
@pytest.mark.parametrize("fingerprint", ["100,2,3", None])
@pytest.mark.parametrize("oversized_lyrics_media", [False, True])
def test_real_aac_passes_through_full_sync_without_reencoding(
    tmp_path: Path,
    fingerprint: str | None,
    monkeypatch: pytest.MonkeyPatch,
    oversized_lyrics_media: bool,
) -> None:
    device = build_device(tmp_path)
    try:
        source = tmp_path / "real.m4a"
        data = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
        if oversized_lyrics_media:
            data = rewrite_lyrics(data, source.name, WORDS)
            monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", 10)
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
                        metadata=TrackMetadata(
                            location=str(source),
                            lyrics=WORDS if oversized_lyrics_media else "",
                        ),
                    ),
                )
            ),
            (
                HostMediaSource(
                    observed.path,
                    HostMediaFileKind.AUDIO,
                    observed.size_bytes,
                    observed.modified_ns,
                    fingerprint,
                ),
            ),
            (),
            HostMediaCacheStats(),
        )
        request = _request(device, host)
        request = replace(
            request,
            plan=select_sync_plan(
                request.plan,
                selected_host_paths=frozenset({host_path_identity(str(source))}),
                selected_ipod_removals=frozenset(),
            ),
        )
        events: list[WriteProgress] = []
        result = SyncExecutor(device.coordinator).execute(
            request, events.append, Event()
        )
        assert any(
            any(
                item.name == "Real audio" and "Inspecting" in item.progress.message
                for item in e.active_items
            )
            and e.completed == 0
            for e in events
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert not any(
            issue.code == "resources.lyrics_disk_staging" for issue in result.issues
        )
        assert source.read_bytes() == data
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
        assert synced.acoustic_fingerprint == (fingerprint or "")
        reloaded = device.coordinator.scan_ipod_media(
            result.active, lambda _: None, Event()
        )
        assert any(track.sync == synced.sync for track in reloaded.tracks)
        repeated = prepare_sync_plan(host, reloaded, result.active.library)
        assert (
            next(
                item for item in repeated.items if item.host_path == str(source)
            ).action
            is SyncPlanAction.UNCHANGED
        )
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
        detail = next(
            issue.detail
            for issue in result.issues
            if issue.code == "sync.source_changed"
        )
        assert isinstance(detail, SourceText)
        assert (
            detail.source
            == "The Host source {name} changed after scanning. Rescan before Sync."
        )
    finally:
        device.coordinator.close()


def test_changed_photo_detail_retains_its_translation_source(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        host = _photo_host(tmp_path)
        host = replace(
            host, sources=(replace(host.sources[0], content_sha256="0" * 64),)
        )
        request = _request(device, host)
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        detail = next(
            issue.detail for issue in result.issues if issue.code == "sync.photo_failed"
        )
        assert isinstance(detail, SourceText)
        assert (
            detail.source
            == "The Photo changed after scanning. Rescan this source before retrying."
        )
        assert not result.completed
        device.assert_original()
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


@pytest.mark.parametrize("problem", ["missing", "truncated", "directory"])
@pytest.mark.parametrize("update", [False, True])
def test_artwork_failure_defers_covers_but_commits_media(
    tmp_path: Path, problem: str, update: bool
) -> None:
    device = build_device(tmp_path, artwork_size_multiplier=760)
    try:
        original = device.active.library.tracks[0]
        artwork_path = device.root / "iPod_Control/Artwork/ArtworkDB"
        before = artwork_path.read_bytes()
        thumbnail = next((device.root / "iPod_Control/Artwork").glob("*.ithmb"))
        if problem == "truncated":
            thumbnail.write_bytes(b"short")
        else:
            thumbnail.unlink()
            if problem == "directory":
                thumbnail.mkdir()
        host = _host(tmp_path, "Cover deferred")
        path = tmp_path / "cover.png"
        Image.new("RGB", (180, 180), "blue").save(path)
        observed = LocalHostFile.observe(HostPath(path))
        cover = HostMediaArtworkSource(
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
                tracks=(replace(host.snapshot.tracks[0], artwork_id=123),),
            ),
            artwork_sources=(cover,),
        )
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            _request(device, host, update=update), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.PARTIAL, result.issues
        assert any(issue.code == "sync.artwork_deferred" for issue in result.issues)
        assert result.active is not None and result.helper is not None
        changed = next(
            t for t in result.active.library.tracks if t.title == "Cover deferred"
        )
        assert changed.artwork_id == (original.artwork_id if update else 0)
        assert (device.root / changed.metadata.location).is_file()
        assert artwork_path.read_bytes() == before
        recorded = next(
            t for t in result.helper.tracks if t.track_id == changed.track_id
        )
        assert recorded.sync is not None and recorded.sync.host_artwork_sha256 == ""
        next_plan = prepare_sync_plan(host, result.helper, result.active.library)
        assert any(item.artwork_changed for item in next_plan.items)
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("missing_thumbnail", [False, True])
def test_folder_artwork_only_update_is_committed_and_recorded(
    tmp_path: Path, missing_thumbnail: bool
) -> None:
    device = build_device(tmp_path)
    try:
        original = device.active.library.tracks[0]
        assert original.artwork_id > 0
        if missing_thumbnail:
            next((device.root / "iPod_Control/Artwork").glob("*.ithmb")).unlink()
        host = _host(tmp_path, "Updated cover")
        path = tmp_path / "cover.png"
        Image.new("RGB", (180, 180), "blue").save(path)
        observed = LocalHostFile.observe(HostPath(path))
        cover = HostMediaArtworkSource(
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
                tracks=(replace(host.snapshot.tracks[0], artwork_id=123),),
            ),
            artwork_sources=(cover,),
        )
        request = _request(device, host, update=True)
        source = host.sources[0]
        prior = request.ipod.tracks[0].sync
        assert prior is not None
        ipod = replace(
            request.ipod,
            tracks=(
                replace(
                    request.ipod.tracks[0],
                    acoustic_fingerprint=source.acoustic_fingerprint or "",
                    sync=replace(
                        prior,
                        host_size_bytes=source.size_bytes,
                        host_modified_ns=source.modified_ns,
                        host_artwork_sha256="a" * 64,
                        ipod_artwork_id=original.artwork_id,
                    ),
                ),
                *request.ipod.tracks[1:],
            ),
        )
        plan = prepare_sync_plan(host, ipod, device.active.library)
        changed = next(
            item for item in plan.items if item.host_path == str(source.path)
        )
        assert changed.action is SyncPlanAction.UPDATE
        assert changed.artwork_changed and not changed.host_modified_changed
        assert changed.audio_payload_changed is False
        request = replace(request, ipod=ipod, plan=plan)
        result = _Executor(device.coordinator, transcoder=_MissingTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is (
            SyncExecutionStatus.PARTIAL
            if missing_thumbnail
            else SyncExecutionStatus.SUCCESS
        ), result.issues
        assert result.active is not None and result.helper is not None
        updated = next(
            track
            for track in result.active.library.tracks
            if track.track_id == original.track_id
        )
        assert (updated.artwork_id == original.artwork_id) is missing_thumbnail
        recorded = next(
            item for item in result.helper.tracks if item.track_id == original.track_id
        )
        assert recorded.sync is not None
        assert recorded.sync.host_artwork_sha256 == (
            "" if missing_thumbnail else cover.content_sha256
        )
        assert recorded.sync.ipod_artwork_id == updated.artwork_id
        next_plan = prepare_sync_plan(host, result.helper, result.active.library)
        assert next(
            item for item in next_plan.items if item.host_path == str(source.path)
        ).action is (
            SyncPlanAction.UPDATE if missing_thumbnail else SyncPlanAction.UNCHANGED
        )
    finally:
        device.coordinator.close()


def test_non_cover_device_publishes_display_only_artwork_for_iopenpod(
    tmp_path: Path,
) -> None:
    device = bare_device(tmp_path, model_number="M9802")
    try:
        host = _host(tmp_path, "First", "Second")
        path = tmp_path / "cover.png"
        Image.new("RGB", (180, 180), "blue").save(path)
        observed = LocalHostFile.observe(HostPath(path))
        host = replace(
            host,
            snapshot=replace(
                host.snapshot,
                tracks=tuple(
                    replace(track, artwork_id=123) for track in host.snapshot.tracks
                ),
            ),
            artwork_sources=(
                HostMediaArtworkSource(
                    123,
                    HostArtworkKind.FOLDER,
                    observed.path,
                    observed.size_bytes,
                    observed.modified_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                ),
            ),
        )

        ipod = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
        comparison = prepare_sync_plan(host, ipod, device.active.library)
        request = SyncExecutionRequest(
            SyncPlan(
                tuple(
                    item
                    for item in comparison.items
                    if item.action is not SyncPlanAction.REMOVE
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
        assert result.active is not None
        incoming = tuple(
            track
            for track in result.active.library.tracks
            if track.title in ("First", "Second")
        )
        assert len(incoming) == 2
        assert all(track.artwork_id > 0 for track in incoming)
        assert all(track.metadata.artwork_count == 1 for track in incoming)
        artwork_path = device.root / "iPod_Control/Artwork/ArtworkDB"
        assert artwork_path.exists()

        parsed = IPodLibrary(
            (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        ).with_artwork(artwork_path.read_bytes())
        display_format = CoverFormat(1060, 320, 320, 640, CoverPixelFormat.RGB565_LE)
        for track in incoming:
            read = parsed.artwork_read(track.artwork_id, (display_format,), 320)
            assert read is not None
            payload = (device.root / read.relative_path).read_bytes()
            pixels = read.decode(payload[read.offset : read.offset + read.length])
            assert (pixels.width, pixels.height) == (320, 320)
            assert len(set(pixels.rgb888)) > 1
    finally:
        device.coordinator.close()


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="Sync media tools required",
)
@pytest.mark.parametrize("capture_budget", [None, 0])
def test_rockbox_sync_embeds_compact_artwork_in_a_non_cover_device_file(
    tmp_path: Path,
    capture_budget: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if capture_budget is not None:
        monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", capture_budget)
    device = bare_device(tmp_path, model_number="M9802")
    try:
        media_path = tmp_path / "rockbox-track.mp3"
        media_path.write_bytes(
            base64.decodebytes((FIXTURES / "tone.mp3.b64").read_bytes())
        )
        media = LocalHostFile.observe(HostPath(media_path))
        cover_path = tmp_path / "rockbox-cover.png"
        Image.new("RGB", (240, 240), (30, 80, 140)).save(cover_path)
        cover = LocalHostFile.observe(HostPath(cover_path))
        host = HostMediaLibrary(
            LibrarySnapshot(
                tracks=(
                    Track(
                        100,
                        "Rockbox track",
                        "Artist",
                        "Album",
                        1000,
                        artwork_id=123,
                        metadata=TrackMetadata(
                            location=str(media_path),
                            file_format="MPEG audio file",
                            sample_rate_hz=44100,
                        ),
                    ),
                )
            ),
            (
                HostMediaSource(
                    media.path,
                    HostMediaFileKind.AUDIO,
                    media.size_bytes,
                    media.modified_ns,
                    acoustic_fingerprint="1,2,3",
                    content_sha256=hashlib.sha256(media_path.read_bytes()).hexdigest(),
                ),
            ),
            (),
            HostMediaCacheStats(),
            artwork_sources=(
                HostMediaArtworkSource(
                    123,
                    HostArtworkKind.FOLDER,
                    cover.path,
                    cover.size_bytes,
                    cover.modified_ns,
                    hashlib.sha256(cover_path.read_bytes()).hexdigest(),
                ),
            ),
        )
        ipod = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
        comparison = prepare_sync_plan(host, ipod, device.active.library)
        request = replace(
            SyncExecutionRequest(
                select_sync_plan(
                    comparison,
                    selected_host_paths=frozenset(
                        {host_path_identity(str(media_path))}
                    ),
                    selected_ipod_removals=frozenset(),
                ),
                host,
                ipod,
                device.active,
                1,
                1,
            ),
            options=SyncOptions(rockbox_metadata=True),
        )

        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )

        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        added = next(
            (
                track
                for track in result.active.library.tracks
                if track.title == "Rockbox track"
            ),
            None,
        )
        assert added is not None, (
            tuple(track.title for track in result.active.library.tracks),
            request.plan.items,
            result.issues,
        )
        tags = cast(
            "_SyncID3TagView | None",
            MP3(device.root / added.metadata.location).tags,  # type: ignore[no-untyped-call]
        )
        assert tags is not None
        cover_data = tags.getall("APIC")[0].data
        with Image.open(io.BytesIO(cover_data)) as image:
            assert image.size == (120, 120)
            assert image.mode == "L"

        original_location = added.metadata.location
        ExportMediaTagger().prepare(
            HostPath(media_path), replace(added, title="Updated Rockbox track"), None
        )
        updated_source = LocalHostFile.observe(HostPath(media_path))
        updated_host = replace(
            host,
            snapshot=replace(
                host.snapshot,
                tracks=(
                    replace(
                        host.snapshot.tracks[0],
                        title="Updated Rockbox track",
                        metadata=replace(
                            host.snapshot.tracks[0].metadata, lyrics=WORDS
                        ),
                    ),
                ),
            ),
            sources=(
                replace(
                    host.sources[0],
                    size_bytes=updated_source.size_bytes,
                    modified_ns=updated_source.modified_ns,
                ),
            ),
        )
        assert added.ipod is not None
        with device.coordinator.sync_session(result.active) as session:
            observed_device_file = session.stat(DevicePath(original_location))
        updated_ipod = IPodMediaLibrary(
            (
                IPodTrackFingerprint(
                    added.ipod.db_track_id,
                    added.track_id,
                    DevicePath(original_location),
                    observed_device_file.size,
                    observed_device_file.modified_ns,
                    "1,2,3",
                    SyncDetails(
                        "2026-01-01T00:00:00+00:00",
                        str(media_path),
                        media.size_bytes,
                        media.modified_ns,
                        "mp3",
                        "mp3",
                        False,
                        host_artwork_sha256=hashlib.sha256(
                            cover_path.read_bytes()
                        ).hexdigest(),
                        ipod_artwork_id=added.artwork_id,
                    ),
                ),
            ),
            (),
            (),
            IPodMediaCacheStats(),
            None,
            False,
        )
        updated_plan = prepare_sync_plan(
            updated_host, updated_ipod, result.active.library
        )
        updated_item = next(
            item for item in updated_plan.items if item.host_path == str(media_path)
        )
        assert updated_item.action is SyncPlanAction.UPDATE
        assert updated_item.audio_payload_changed is False
        updated_request = SyncExecutionRequest(
            SyncPlan((updated_item,)),
            updated_host,
            updated_ipod,
            result.active,
            1,
            1,
            options=SyncOptions(rockbox_metadata=True),
        )
        updated_result = SyncExecutor(
            device.coordinator, transcoder=_MissingTools()
        ).execute(updated_request, lambda _: None, Event())
        assert updated_result.status is SyncExecutionStatus.SUCCESS, (
            updated_result.issues
        )
        assert updated_result.active is not None
        assert (
            next(
                track
                for track in updated_result.active.library.tracks
                if track.metadata.location == original_location
            ).title
            == "Updated Rockbox track"
        )
        updated_tags = MP3(device.root / original_location).tags  # type: ignore[no-untyped-call]
        assert updated_tags is not None
        updated_track = next(
            track
            for track in updated_result.active.library.tracks
            if track.metadata.location == original_location
        )
        assert (
            updated_track.size_bytes == (device.root / original_location).stat().st_size
        )
        assert embedded_lyrics(MP3(device.root / original_location)) == WORDS
        assert (
            str(cast("_SyncID3TagView", updated_tags)["TIT2"])
            == "Updated Rockbox track"
        )
        updated_cover_data = (
            cast("_SyncID3TagView", updated_tags).getall("APIC")[0].data
        )
        with Image.open(io.BytesIO(updated_cover_data)) as image:
            assert image.size == (120, 120)
            assert image.mode == "L"

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
        activity: Callable[[MediaPreparationProgress], None],
    ) -> _PreparedTrack:
        result = super()._prepare_one(
            request, item, source, track, tools, checkpoint, activity
        )

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

        def flush_pending(
            expected: object,
            path: str,
            _progress: Callable[[WriteProgress], None] | None = None,
        ) -> None:
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


@pytest.mark.parametrize("playlists", [False, True])
def test_unavailable_unchanged_host_source_does_not_block_independent_add(
    tmp_path: Path, playlists: bool
) -> None:
    device = build_device(tmp_path)
    try:
        host = _host(tmp_path, "Already synced", "New song", playlists=playlists)
        request = _request(device, host, update=True)
        retained = request.ipod.tracks[0]
        assert retained.sync is not None
        source = host.sources[0]
        ipod = replace(
            request.ipod,
            tracks=(
                replace(
                    retained,
                    acoustic_fingerprint=source.acoustic_fingerprint or "",
                    sync=replace(
                        retained.sync,
                        host_size_bytes=source.size_bytes,
                        host_modified_ns=source.modified_ns,
                    ),
                ),
                *request.ipod.tracks[1:],
            ),
        )
        plan = prepare_sync_plan(host, ipod, device.active.library)
        request = replace(
            request,
            ipod=ipod,
            reconcile_playlists=playlists,
            plan=SyncPlan(
                tuple(
                    item
                    for item in plan.items
                    if item.action is not SyncPlanAction.REMOVE
                )
            ),
        )
        assert any(
            item.action is SyncPlanAction.UNCHANGED for item in request.plan.items
        )
        Path(source.path).unlink()
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is (
            SyncExecutionStatus.PARTIAL if playlists else SyncExecutionStatus.SUCCESS
        ), result.issues
        assert result.active is not None
        assert any(track.title == "New song" for track in result.active.library.tracks)
        assert next(
            track
            for track in result.active.library.tracks
            if track.track_id == retained.track_id
        ) == next(
            track
            for track in device.active.library.tracks
            if track.track_id == retained.track_id
        )
        assert result.playlist_change_count == 0
        assert (
            any(issue.code == "sync.playlist_source_changed" for issue in result.issues)
            is playlists
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
        assert song.track.metadata.remember_position
        assert song.track.metadata.skip_shuffle
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
            *,
            retain_recovery: bool = False,
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
            return save(
                review, expected, progress, cancelled, retain_recovery=retain_recovery
            )

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
