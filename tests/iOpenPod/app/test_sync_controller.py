"""Execution reserves the UI state, snapshots settings, and publishes safe outcomes."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtTest import QSignalSpy
from tests.iOpenPod.app.test_library_write_controller import (
    session as session,
)
from tests.iOpenPod.app.test_library_write_controller import (
    wait_for,
)

from iOpenPod.app.core.settings.definitions import (
    COMPUTE_SOUND_CHECK,
    PENDING_SYNC_CLEANUP,
    PENDING_SYNC_RECOVERY,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinator,
    SyncCleanupCompletedError,
    SyncRecoveryRequiredError,
    SyncRecoveryRestoredError,
)
from iOpenPod.app.sync_controller import SyncController
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
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
from iPodDB.library import LibrarySnapshot, Playlist


class _Execution:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.request: SyncExecutionRequest | None = None
        self.crash = False
        self.outcome: SyncExecutionResult | None = None

    def execute(
        self,
        request: SyncExecutionRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> SyncExecutionResult:
        self.request = request
        self.entered.set()
        progress(WriteProgress("sync.prepare", "Preparing on Host"))
        assert self.release.wait(5)
        if self.outcome is not None:
            return self.outcome
        if self.crash:
            raise RuntimeError("fixture failure")
        if cancelled.is_set():
            return SyncExecutionResult(SyncExecutionStatus.CANCELLED)
        return SyncExecutionResult(
            SyncExecutionStatus.SUCCESS,
            active=replace(
                request.source,
                library=replace(request.source.library, device_name="Synced"),
            ),
            completed=request.plan.items,
        )


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
    service = _Execution()
    controller = SyncController(service, workspace, devices, settings)
    finished = QSignalSpy(controller.finished)
    try:
        assert controller.start(*_inputs(), active)
        wait_for(service.entered.is_set)
        assert workspace.locked and devices.busy
        settings.set_global(COMPUTE_SOUND_CHECK, False)
        assert (
            service.request is not None and service.request.options.compute_sound_check
        )
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
    service = _Execution()
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


def test_pending_edits_block_sync_without_discarding_them(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    service = _Execution()
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
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    service = _Execution()
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
    service = _Execution()
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


def test_pending_recovery_survives_restart_and_blocks_writes_until_restored(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    path = ".iopenpod-recovery/" + "a" * 32 + "/transaction.json"
    settings.set_global(PENDING_SYNC_RECOVERY, path)
    recovered: list[str] = []

    def recover(journal: str) -> ActiveIPod:
        recovered.append(journal)
        return active

    controller = SyncController(
        _Execution(), workspace, devices, settings, recovery=recover
    )
    try:
        assert controller.needs_recovery and workspace.locked
        assert not devices.device_writes_allowed
        assert not controller.start(*_inputs(), active)
        assert controller.recover()
        wait_for(lambda: not controller.busy)
        assert recovered == [path]
        assert not controller.needs_recovery and not workspace.locked
        assert devices.device_writes_allowed
        assert settings.get(PENDING_SYNC_RECOVERY) == ""
    finally:
        controller.shutdown()


def test_closing_during_sync_persists_queued_recovery_result(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    service = _Execution()
    journal = ".iopenpod-recovery/" + "b" * 32 + "/transaction.json"
    service.outcome = SyncExecutionResult(
        SyncExecutionStatus.RECOVERY_REQUIRED, recovery_path=journal
    )
    controller = SyncController(service, workspace, devices, settings)
    assert controller.start(*_inputs(), active)
    wait_for(service.entered.is_set)
    service.release.set()
    controller.shutdown()
    assert settings.get(PENDING_SYNC_RECOVERY) == journal
    assert controller.needs_recovery and workspace.locked
    assert not devices.busy and not devices.device_writes_allowed


def test_cleanup_retry_preserves_success_and_survives_restart(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    _coordinator, devices, workspace, _ = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    journal = ".iopenpod-recovery/" + "c" * 32 + "/transaction.json"
    settings.set_global(PENDING_SYNC_CLEANUP, journal)
    attempts: list[str] = []

    def cleanup(path: str) -> None:
        attempts.append(path)
        if len(attempts) == 1:
            raise OSError("Reconnect the iPod")

    controller = SyncController(
        _Execution(), workspace, devices, settings, cleanup=cleanup
    )
    try:
        assert controller.needs_cleanup and not controller.needs_recovery
        assert controller.cleanup()
        wait_for(lambda: not controller.busy)
        assert controller.needs_cleanup
        assert settings.get(PENDING_SYNC_CLEANUP) == journal
        assert controller.result is not None
        assert controller.result.status is SyncExecutionStatus.SUCCESS
        assert "Reconnect" in controller.result.issues[-1].detail
        assert controller.cleanup()
        wait_for(lambda: not controller.busy)
        assert not controller.needs_cleanup and not controller.needs_recovery
        assert settings.get(PENDING_SYNC_CLEANUP) == ""
        assert settings.get(PENDING_SYNC_RECOVERY) == ""
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
    settings.set_global(
        PENDING_SYNC_CLEANUP, ".iopenpod-recovery/" + "d" * 32 + "/transaction.json"
    )

    def cleanup(_path: str) -> None:
        raise SyncCleanupCompletedError(
            "Recovery files were removed. Safely eject before unplugging."
        )

    controller = SyncController(
        _Execution(), workspace, devices, settings, cleanup=cleanup
    )
    try:
        assert controller.cleanup()
        wait_for(lambda: not controller.busy)
        assert not controller.needs_cleanup
        assert settings.get(PENDING_SYNC_CLEANUP) == ""
        assert controller.result is not None
        assert controller.result.status is SyncExecutionStatus.SUCCESS
        assert "Safely eject" in controller.result.issues[-1].message
    finally:
        controller.shutdown()


def test_restored_library_reload_failure_unblocks_recovery(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    _coordinator, devices, workspace, _ = session
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(
        PENDING_SYNC_RECOVERY, ".iopenpod-recovery/" + "e" * 32 + "/transaction.json"
    )

    def recover(_path: str) -> ActiveIPod:
        raise SyncRecoveryRestoredError(
            "Library restored. Refresh the Device Picker and select it again."
        )

    controller = SyncController(
        _Execution(), workspace, devices, settings, recovery=recover
    )
    try:
        assert controller.recover()
        wait_for(lambda: not controller.busy)
        assert not controller.needs_recovery and not workspace.locked
        assert settings.get(PENDING_SYNC_RECOVERY) == ""
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
    settings.set_global(
        PENDING_SYNC_RECOVERY, ".iopenpod-recovery/" + "e" * 32 + "/transaction.json"
    )
    next_path = ".iopenpod-recovery/" + "f" * 32 + "/transaction.json"

    def recover(_path: str) -> ActiveIPod:
        raise SyncRecoveryRequiredError(next_path)

    controller = SyncController(
        _Execution(), workspace, devices, settings, recovery=recover
    )
    try:
        assert controller.recover()
        wait_for(lambda: not controller.busy)
        assert controller.needs_recovery and workspace.locked
        assert settings.get(PENDING_SYNC_RECOVERY) == next_path
    finally:
        controller.shutdown()
