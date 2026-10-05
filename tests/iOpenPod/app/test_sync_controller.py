"""Execution reserves the UI state, snapshots settings, and publishes safe outcomes."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from tests.iOpenPod.app.sync_test_support import SyncExecutionStub
from tests.iOpenPod.app.test_library_write_controller import (
    session as session,
)
from tests.iOpenPod.app.test_library_write_controller import (
    track_model as track_model,
)
from tests.iOpenPod.app.test_library_write_controller import (
    wait_for,
)
from tests.iOpenPod.GUI.application_shell_test_support import build_context

from iOpenPod.app.core.settings.definitions import (
    COMPUTE_SOUND_CHECK,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.models.library_filter_models import (
    AlbumFilterProxyModel,
    CollectionFilterProxyModel,
    TrackFilterProxyModel,
)
from iOpenPod.app.models.photo_list_model import PhotoListModel
from iOpenPod.app.models.track_table_model import TrackColumn, TrackTableModel
from iOpenPod.app.podcasts.models import PodcastSnapshot
from iOpenPod.app.podcasts.sync import PodcastSyncRequest
from iOpenPod.app.scrobbling.settings import LASTFM_USERNAME, SCROBBLE_DURING_SYNC
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinator,
    SyncCleanupCompletedError,
    SyncRecoveryRequiredError,
    SyncRecoveryRestoredError,
    SyncRestoredCleanupPendingError,
)
from iOpenPod.app.sync_controller import SyncController
from iOpenPod.app.sync_execution import (
    SyncExecutionResult,
    SyncExecutionStatus,
)
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iPodDB.library import LibrarySnapshot, Photo, PhotoLibrary, Playlist, Track


def _inputs() -> tuple[SyncPlan, HostMediaLibrary, IPodMediaLibrary]:
    return (
        SyncPlan(
            (
                SyncPlanItem(
                    SyncPlanAction.REMOVE,
                    SyncPlanMediaKind.TRACK,
                    SyncPlanBasis.IPOD_ONLY,
                    "Track",
                    ipod_id=1,
                ),
            )
        ),
        HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
        IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
    )


def test_execution_reserves_workspace_and_uses_immutable_settings(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(COMPUTE_SOUND_CHECK, True)
    settings.set_global(SCROBBLE_DURING_SYNC, True)
    settings.set_global(LASTFM_USERNAME, "listener")
    service = SyncExecutionStub()
    controller = SyncController(service, workspace, devices, settings)
    finished = QSignalSpy(controller.finished)
    try:
        assert controller.start(*_inputs(), active)
        wait_for(service.entered.is_set)
        assert workspace.locked and devices.busy
        settings.set_global(COMPUTE_SOUND_CHECK, False)
        settings.set_global(SCROBBLE_DURING_SYNC, False)
        assert (
            service.request is not None and service.request.options.compute_sound_check
        )
        assert service.request.options.scrobble
        assert service.request.scrobble_accounts[0].username == "listener"
        assert not controller.start(*_inputs(), active)
        service.release.set()
        wait_for(lambda: finished.count() == 1)
        assert not workspace.locked and not devices.busy
        assert workspace.device_name == "Synced"
        assert controller.result is not None
        assert controller.result.status is SyncExecutionStatus.SUCCESS
    finally:
        service.release.set()
        controller.shutdown()


@pytest.mark.parametrize(
    "status", [SyncExecutionStatus.SUCCESS, SyncExecutionStatus.PARTIAL]
)
@pytest.mark.parametrize("media", ["tracks", "photos", "artwork"])
def test_committed_sync_refreshes_changed_media(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    status: SyncExecutionStatus,
    media: str,
) -> None:
    coordinator, _, _, _ = session
    context = build_context(device_coordinator=coordinator)
    devices = context.device_controller
    workspace = context.library_workspace
    track_model = context.track_model
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    track_model.reset_tracks(active.library.tracks)
    photos = PhotoListModel(workspace)
    if media == "tracks":
        first, *remaining = active.library.tracks
        committed_tracks = (
            replace(first, title="Updated Track", album="Updated Album"),
            *remaining,
            replace(
                first,
                track_id=max(t.track_id for t in active.library.tracks) + 1,
                title="Added Track",
            ),
        )
        committed = replace(
            active, library=replace(active.library, tracks=committed_tracks)
        )
    elif media == "photos":
        committed = replace(
            active,
            library=replace(active.library, photos=PhotoLibrary(photos=(Photo(101),))),
            photos_database_fingerprint=replace(
                active.database_fingerprint, sha256="a" * 64
            ),
        )
    else:
        # Cover pixels can change while retained Track/artwork identities stay the same.
        committed = replace(
            active,
            artwork_database_fingerprint=replace(
                active.database_fingerprint, sha256="b" * 64
            ),
        )
    service = SyncExecutionStub()
    service.outcome = SyncExecutionResult(status, active=committed)
    service.release.set()
    controller = SyncController(
        service,
        workspace,
        devices,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    finished = QSignalSpy(controller.finished)
    published = QSignalSpy(devices.activeIPodChanged)
    artwork_generations = QSignalSpy(context.artwork_controller.generationChanged)
    photo_generations = QSignalSpy(context.photo_controller.generationChanged)
    try:
        assert controller.start(*_inputs(), active)
        wait_for(lambda: finished.count() == 1)
        wait_for(lambda: not devices.busy and not context.podcast_controller.busy)
        assert track_model.tracks == committed.library.tracks
        assert workspace.snapshot is committed.library
        assert devices.active_ipod is committed
        assert published.count() == 1
        assert artwork_generations.count() == photo_generations.count() == 1
        if media == "tracks":
            assert "Updated Album" in {
                album.title
                for row in range(context.album_model.album_count)
                if (album := context.album_model.album_at(row)) is not None
            }
        elif media == "photos":
            assert photos.rowCount() == 1 and photos.photo_at(0) == Photo(101)
            assert committed.library.tracks is active.library.tracks
        else:
            assert committed.library is active.library
        assert controller.result is not None and controller.result.status is status
        assert not workspace.dirty and not workspace.locked and not devices.busy
    finally:
        controller.shutdown()
        context.shutdown()


@pytest.mark.parametrize("direction", tuple(Qt.SortOrder))
@pytest.mark.parametrize("view", ["tracks", "albums", "artists"])
def test_committed_sync_keeps_new_library_items_sorted(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    direction: Qt.SortOrder,
    view: str,
) -> None:
    coordinator, _, _, _ = session
    context = build_context(device_coordinator=coordinator)
    active = coordinator.active_ipod
    assert active is not None
    retained = Track(1, "Bravo", "Bravo", "Bravo", 1_000)
    active = replace(active, library=LibrarySnapshot(tracks=(retained,)))
    context.library_workspace.load(active.library)
    context.device_controller.finish_library_save(active)
    proxy: TrackFilterProxyModel | AlbumFilterProxyModel | CollectionFilterProxyModel
    if view == "tracks":
        proxy = TrackFilterProxyModel(context.track_model)
        proxy.sort(TrackColumn.TITLE, direction)
    elif view == "albums":
        proxy = AlbumFilterProxyModel(context.album_model)
        proxy.set_sort_direction(direction)
    else:
        proxy = CollectionFilterProxyModel(context.artist_model)
        proxy.set_sort_direction(direction)
    column = TrackColumn.TITLE if view == "tracks" else 0
    assert proxy.index(0, column).data() == "Bravo"

    # Sync retains existing source order and appends the newly committed Track.
    title = "Alpha" if direction == Qt.SortOrder.AscendingOrder else "Zulu"
    added = Track(2, title, title, title, 1_000)
    committed = replace(active, library=LibrarySnapshot(tracks=(retained, added)))
    service = SyncExecutionStub()
    service.outcome = SyncExecutionResult(SyncExecutionStatus.SUCCESS, active=committed)
    service.release.set()
    controller = SyncController(
        service, context.library_workspace, context.device_controller, context.settings
    )
    finished = QSignalSpy(controller.finished)
    try:
        assert controller.start(*_inputs(), active)
        wait_for(lambda: finished.count() == 1)
        assert context.track_model.tracks == (retained, added)
        assert tuple(
            proxy.index(row, column).data() for row in range(proxy.rowCount())
        ) == (title, "Bravo")
        assert proxy.sortOrder() == direction
    finally:
        controller.shutdown()
        context.shutdown()


def test_playlist_only_sync_requires_enabled_review_choice(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    _, host, ipod = _inputs()
    host = replace(
        host, snapshot=LibrarySnapshot(playlists=(Playlist(9, "New empty playlist"),))
    )
    service = SyncExecutionStub()
    service.release.set()
    controller = SyncController(
        service,
        workspace,
        devices,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    try:
        assert not controller.start(
            SyncPlan(()), host, ipod, active, reconcile_playlists=False
        )
        assert controller.start(
            SyncPlan(()), host, ipod, active, reconcile_playlists=True
        )
        wait_for(lambda: not controller.busy)
        assert service.request is not None and service.request.reconcile_playlists
        assert controller.result is not None
        assert controller.result.status is SyncExecutionStatus.SUCCESS
    finally:
        controller.shutdown()


def test_podcast_sync_uses_shared_reservation_without_host_scans(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    service = SyncExecutionStub()
    controller = SyncController(
        service,
        workspace,
        devices,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    podcasts = PodcastSyncRequest(PodcastSnapshot(writable=True))
    try:
        assert controller.start_podcasts(podcasts, active)
        wait_for(service.entered.is_set)
        assert workspace.locked and devices.busy
        assert service.request is not None and service.request.podcasts is podcasts
        assert not service.request.reconcile_playlists
        assert not service.request.plan.items and not service.request.host.sources
        assert not controller.start_podcasts(podcasts, active)
        service.release.set()
        wait_for(lambda: not controller.busy)
        assert not workspace.locked and not devices.busy
    finally:
        service.release.set()
        controller.shutdown()


def test_pending_edits_block_sync_without_discarding_them(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    service = SyncExecutionStub()
    controller = SyncController(
        service,
        workspace,
        devices,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    try:
        assert not controller.start(*_inputs(), active)
        assert "Save or discard" in controller.last_error
        assert workspace.dirty and not devices.busy and not service.entered.is_set()
    finally:
        controller.shutdown()


def test_cancel_leaves_library_unchanged_and_releases_reservation(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    track_model: TrackTableModel,
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    track_model.reset_tracks(active.library.tracks)
    published = QSignalSpy(devices.activeIPodChanged)
    service = SyncExecutionStub()
    controller = SyncController(
        service,
        workspace,
        devices,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    try:
        assert controller.start(*_inputs(), active)
        wait_for(service.entered.is_set)
        controller.cancel()
        service.release.set()
        wait_for(lambda: not controller.busy)
        assert controller.result is not None
        assert controller.result.status is SyncExecutionStatus.CANCELLED
        assert workspace.snapshot is active.library
        assert track_model.tracks == active.library.tracks
        assert published.count() == 0
        assert not workspace.locked and not devices.busy
    finally:
        service.release.set()
        controller.shutdown()


def test_worker_exception_becomes_visible_failure(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    service = SyncExecutionStub()
    service.crash = True
    service.release.set()
    controller = SyncController(
        service,
        workspace,
        devices,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    try:
        assert controller.start(*_inputs(), active)
        wait_for(lambda: controller.result is not None)
        assert controller.result is not None
        assert controller.result.status is SyncExecutionStatus.FAILED
        assert controller.result.issues[0].code == "sync.internal_error"
        assert not workspace.locked and not devices.busy
    finally:
        controller.shutdown()


def test_discovered_recovery_blocks_writes_until_restored(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    path = ".iopenpod-recovery/" + "a" * 32 + "/transaction.json"
    pending_recovery = path
    recovered: list[str] = []

    def recover(journal: str) -> ActiveIPod:
        recovered.append(journal)
        return active

    controller = SyncController(
        SyncExecutionStub(), workspace, devices, settings, recovery=recover
    )
    devices.recoveryRequired.emit(pending_recovery)
    try:
        assert controller.needs_recovery and workspace.locked
        assert not devices.device_writes_allowed
        assert not controller.start(*_inputs(), active)
        assert controller.recover()
        wait_for(lambda: not controller.busy)
        assert recovered == [path]
        assert not controller.needs_recovery and not workspace.locked
        assert devices.device_writes_allowed
    finally:
        controller.shutdown()


def test_closing_during_sync_publishes_queued_recovery_result(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    service = SyncExecutionStub()
    journal = ".iopenpod-recovery/" + "b" * 32 + "/transaction.json"
    service.outcome = SyncExecutionResult(
        SyncExecutionStatus.RECOVERY_REQUIRED, recovery_path=journal
    )
    controller = SyncController(service, workspace, devices, settings)
    assert controller.start(*_inputs(), active)
    wait_for(service.entered.is_set)
    service.release.set()
    controller.shutdown()
    assert controller.result is not None and controller.result.recovery_path == journal
    assert controller.needs_recovery and workspace.locked
    assert not devices.busy and not devices.device_writes_allowed


def test_discovered_cleanup_retry_preserves_success(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    _coordinator, devices, workspace, _ = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    journal = ".iopenpod-recovery/" + "c" * 32 + "/transaction.json"
    pending_cleanup = journal
    attempts: list[str] = []

    def cleanup(path: str) -> None:
        attempts.append(path)
        if len(attempts) == 1:
            raise OSError("Reconnect the iPod")

    controller = SyncController(
        SyncExecutionStub(), workspace, devices, settings, cleanup=cleanup
    )
    devices.cleanupAvailable.emit(pending_cleanup)
    try:
        assert controller.needs_cleanup and not controller.needs_recovery
        assert controller.cleanup()
        wait_for(lambda: not controller.busy)
        assert controller.needs_cleanup
        assert (
            controller.result is not None and controller.result.recovery_path == journal
        )
        assert controller.result.status is SyncExecutionStatus.SUCCESS
        assert "Reconnect" in controller.result.issues[-1].detail
        assert controller.cleanup()
        wait_for(lambda: not controller.busy)
        assert not controller.needs_cleanup and not controller.needs_recovery
        assert controller.result is not None
        assert controller.result.status is SyncExecutionStatus.SUCCESS
        assert not workspace.locked and not devices.busy
        assert attempts == [journal, journal]
    finally:
        controller.shutdown()


def test_completed_cleanup_flush_warning_does_not_leave_missing_journal_retry(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    _coordinator, devices, workspace, _ = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    pending_cleanup = ".iopenpod-recovery/" + "d" * 32 + "/transaction.json"

    def cleanup(_path: str) -> None:
        raise SyncCleanupCompletedError(
            "Recovery files were removed. Safely eject before unplugging."
        )

    controller = SyncController(
        SyncExecutionStub(), workspace, devices, settings, cleanup=cleanup
    )
    devices.cleanupAvailable.emit(pending_cleanup)
    try:
        assert controller.cleanup()
        wait_for(lambda: not controller.busy)
        assert not controller.needs_cleanup
        assert controller.result is not None
        assert controller.result.status is SyncExecutionStatus.SUCCESS
        assert "Safely eject" in controller.result.issues[-1].message
    finally:
        controller.shutdown()


def test_restored_cleanup_failure_keeps_journal_and_reports_restoration_truthfully(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    _coordinator, devices, workspace, _ = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    path = ".iopenpod-recovery/" + "e" * 32 + "/transaction.json"
    pending_recovery = path

    def recover(_path: str) -> ActiveIPod:
        raise SyncRestoredCleanupPendingError("A recovery entry is still in use")

    controller = SyncController(
        SyncExecutionStub(), workspace, devices, settings, recovery=recover
    )
    devices.recoveryRequired.emit(pending_recovery)
    try:
        assert controller.recover()
        wait_for(lambda: not controller.busy)
        assert controller.needs_recovery and workspace.locked
        assert controller.result is not None and controller.result.recovery_path == path
        assert controller.result.issues[-1].code == "sync.restored_cleanup_pending"
    finally:
        controller.shutdown()


def test_restored_library_reload_failure_unblocks_recovery(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    _coordinator, devices, workspace, _ = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    pending_recovery = ".iopenpod-recovery/" + "e" * 32 + "/transaction.json"

    def recover(_path: str) -> ActiveIPod:
        raise SyncRecoveryRestoredError(
            "Library restored. Refresh the Device Picker and select it again."
        )

    controller = SyncController(
        SyncExecutionStub(), workspace, devices, settings, recovery=recover
    )
    devices.recoveryRequired.emit(pending_recovery)
    try:
        assert controller.recover()
        wait_for(lambda: not controller.busy)
        assert not controller.needs_recovery and not workspace.locked
        assert not controller.needs_recovery
        assert devices.active_ipod is None and workspace.snapshot is None
        assert not devices.device_writes_allowed
        assert controller.result is not None
        assert "Device Picker" in controller.result.issues[-1].message
    finally:
        controller.shutdown()


def test_recovery_discovers_another_journal_and_keeps_its_path(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    _coordinator, devices, workspace, _ = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    pending_recovery = ".iopenpod-recovery/" + "e" * 32 + "/transaction.json"
    next_path = ".iopenpod-recovery/" + "f" * 32 + "/transaction.json"

    def recover(_path: str) -> ActiveIPod:
        raise SyncRecoveryRequiredError(next_path)

    controller = SyncController(
        SyncExecutionStub(), workspace, devices, settings, recovery=recover
    )
    devices.recoveryRequired.emit(pending_recovery)
    try:
        assert controller.recover()
        wait_for(lambda: not controller.busy)
        assert controller.needs_recovery and workspace.locked
        assert (
            controller.result is not None
            and controller.result.recovery_path == next_path
        )
    finally:
        controller.shutdown()
