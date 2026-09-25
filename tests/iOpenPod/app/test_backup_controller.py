"""Public Qt adapter behavior for Backup workflows."""

from __future__ import annotations

from threading import Event
from time import monotonic
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.backup_controller import (
    BackupController,
    BackupOperation,
    BackupOperationFailure,
)
from iOpenPod.app.backups.models import BackupDeviceInfo, BackupInventory, SnapshotInfo
from iOpenPod.app.backups.outcomes import (
    BackupFailure,
    BackupFailureCode,
    BackupImportCounts,
    CaptureCreated,
    CaptureFailed,
    CaptureOutcome,
    DeviceWritePolicy,
    ImportCompleted,
    RestoreCancelled,
    RestoreCompleted,
    RestoreIncomplete,
    RestoreOutcome,
    RestorePreMutationFailure,
    RestoreRecovered,
    RestoreUnchanged,
)
from iOpenPod.app.core.settings.definitions import BACKUP_LOCATION
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from storage import DevicePath, FlushResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

    from iOpenPod.app.backups.models import RestoreRecoveryRecord
    from iOpenPod.app.backups.service import BackupService
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _Devices(QObject):
    activeIPodChanged = Signal(object)
    busyChanged = Signal(bool)

    def __init__(self, active_ipod: ActiveIPod | None = None) -> None:
        super().__init__()
        self.active_ipod = active_ipod
        self.busy = False
        self.read_only_operations = 0
        self.reload_calls = 0
        self.finish_calls = 0

    @property
    def device_writes_allowed(self) -> bool:
        return (
            not self.busy
            and self.read_only_operations == 0
            and self.active_ipod is not None
        )

    def begin_read_only_operation(self) -> bool:
        if self.busy or self.active_ipod is None:
            return False
        self.read_only_operations += 1
        return True

    def finish_read_only_operation(self) -> None:
        self.finish_calls += 1
        self.read_only_operations -= 1

    def begin_exclusive_operation(self) -> bool:
        if not self.device_writes_allowed:
            return False
        self.busy = True
        self.busyChanged.emit(True)
        return True

    def finish_exclusive_operation(self) -> None:
        self.finish_calls += 1
        self.busy = False
        self.busyChanged.emit(False)

    def reload_active_ipod(self) -> bool:
        self.reload_calls += 1
        return True

    def replace_active_ipod(self, active_ipod: ActiveIPod | None) -> None:
        self.active_ipod = active_ipod
        self.activeIPodChanged.emit(active_ipod)


class _ImportService:
    def __init__(self, outcome: ImportCompleted) -> None:
        self.outcome = outcome
        self.calls: list[tuple[Path, Path]] = []
        self.inventory_calls = 0

    def import_original(
        self,
        root: Path,
        source: Path,
        **_kwargs: object,
    ) -> ImportCompleted:
        self.calls.append((root, source))
        return self.outcome

    def inventory(self, _root: Path) -> BackupInventory:
        self.inventory_calls += 1
        return BackupInventory(())


class _RestoreService:
    def __init__(self, outcome: RestoreOutcome) -> None:
        self.outcome = outcome
        self.inventory_calls = 0
        self.restore_calls = 0
        self.legacy_confirmations: list[bool] = []

    def restore_snapshot(self, *_args: object, **kwargs: object) -> RestoreOutcome:
        self.restore_calls += 1
        legacy_confirmed = kwargs.get("legacy_confirmed", False)
        assert isinstance(legacy_confirmed, bool)
        self.legacy_confirmations.append(legacy_confirmed)
        return self.outcome

    def inventory(self, _root: Path) -> BackupInventory:
        self.inventory_calls += 1
        return BackupInventory(())


class _RecoveryService:
    def __init__(self, outcome: RestoreRecovered) -> None:
        self.outcome = outcome
        self.pending = True
        self.recovery_calls: list[str] = []

    def inventory(self, _root: Path) -> BackupInventory:
        recoveries = (cast("RestoreRecoveryRecord", object()),) if self.pending else ()
        return BackupInventory((), pending_recoveries=recoveries)

    def recover_restore(
        self,
        *_args: object,
        recovery_id: str,
        **_kwargs: object,
    ) -> RestoreRecovered:
        self.recovery_calls.append(recovery_id)
        self.pending = False
        return self.outcome


class _FailingCaptureService:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.inventory_calls = 0

    def create_snapshot(self, *_args: object, **_kwargs: object) -> object:
        raise self.error

    def inventory(self, _root: Path) -> BackupInventory:
        self.inventory_calls += 1
        return BackupInventory(())


class _CaptureOutcomeService:
    def __init__(self, outcome: CaptureOutcome) -> None:
        self.outcome = outcome
        self.inventory_calls = 0

    def create_snapshot(self, *_args: object, **_kwargs: object) -> CaptureOutcome:
        return self.outcome

    def inventory(self, _root: Path) -> BackupInventory:
        self.inventory_calls += 1
        return BackupInventory(())


class _FailingRestoreService:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.inventory_calls = 0

    def restore_snapshot(self, *_args: object, **_kwargs: object) -> object:
        raise self.error

    def inventory(self, _root: Path) -> BackupInventory:
        self.inventory_calls += 1
        return BackupInventory(())


class _BlockingInventoryService:
    def __init__(self, result: BackupInventory) -> None:
        self.result = result
        self.started = Event()
        self.release = Event()

    def inventory(self, _root: Path) -> BackupInventory:
        self.started.set()
        if not self.release.wait(2):
            raise TimeoutError("test did not release inventory call")
        return self.result


class _BlockingCaptureService:
    def __init__(self, outcome: CaptureCreated) -> None:
        self.outcome = outcome
        self.started = Event()
        self.release = Event()

    def create_snapshot(self, *_args: object, **_kwargs: object) -> CaptureCreated:
        self.started.set()
        if not self.release.wait(2):
            raise TimeoutError("test did not release capture call")
        return self.outcome


def _controller(
    service: object,
    devices: _Devices,
    backup_root: Path,
) -> BackupController:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(BACKUP_LOCATION, str(backup_root))
    return BackupController(
        cast("BackupService", service),
        cast("DeviceController", devices),
        settings,
    )


def _settings(backup_root: Path) -> SettingsService:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(BACKUP_LOCATION, str(backup_root))
    return settings


def _wait_until(condition: Callable[[], bool], timeout_ms: int = 2_000) -> None:
    deadline = monotonic() + timeout_ms / 1_000
    while not condition() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert condition(), "Timed out waiting for BackupController"


def _write_policy(controller: BackupController) -> DeviceWritePolicy:
    return controller.device_write_policy


def _completion_slot(
    completed: list[tuple[BackupOperation, object]],
) -> Callable[[BackupOperation, object], None]:
    def record(operation: BackupOperation, result: object) -> None:
        completed.append((operation, result))

    return record


def test_import_original_publishes_typed_outcome_and_preserves_source_argument(
    tmp_path: Path,
) -> None:
    outcome = ImportCompleted(
        imported=BackupImportCounts(devices=1, snapshots=2, content_items=4),
        already_present=BackupImportCounts(),
    )
    service = _ImportService(outcome)
    controller = _controller(service, _Devices(), tmp_path / "native")
    completed: list[tuple[BackupOperation, object]] = []
    controller.operationCompleted.connect(_completion_slot(completed))

    try:
        assert controller.import_original(str(tmp_path / "original")) is True
        _wait_until(lambda: not controller.busy and service.inventory_calls == 1)

        assert service.calls == [(tmp_path / "native", tmp_path / "original")]
        assert (BackupOperation.IMPORT_ORIGINAL, outcome) in completed
    finally:
        controller.shutdown()


def test_refresh_discards_result_when_backup_root_changes(tmp_path: Path) -> None:
    result = BackupInventory((BackupDeviceInfo("device-1", "RoadPod", 1),))
    service = _BlockingInventoryService(result)
    settings = _settings(tmp_path / "first")
    controller = BackupController(
        cast("BackupService", service),
        cast("DeviceController", _Devices()),
        settings,
    )
    published: list[object] = []
    completed: list[tuple[BackupOperation, object]] = []
    controller.inventoryChanged.connect(published.append)
    controller.operationCompleted.connect(_completion_slot(completed))

    try:
        controller.refresh()
        assert service.started.wait(1)
        settings.set_global(BACKUP_LOCATION, str(tmp_path / "second"))
        service.release.set()
        _wait_until(lambda: not controller.busy)

        assert published == []
        assert controller.inventory == BackupInventory(())
        assert (BackupOperation.REFRESH, result) not in completed
    finally:
        service.release.set()
        controller.shutdown()


def test_capture_discards_result_when_active_ipod_changes(tmp_path: Path) -> None:
    outcome = CaptureCreated(SnapshotInfo("snapshot-1", "today", "device-1", "RoadPod"))
    service = _BlockingCaptureService(outcome)
    first = cast("ActiveIPod", object())
    devices = _Devices(first)
    controller = _controller(service, devices, tmp_path / "native")
    completed: list[tuple[BackupOperation, object]] = []
    controller.operationCompleted.connect(_completion_slot(completed))

    try:
        controller.create_snapshot()
        assert service.started.wait(1)
        devices.replace_active_ipod(cast("ActiveIPod", object()))
        service.release.set()
        _wait_until(lambda: not controller.busy)

        assert (BackupOperation.CREATE, outcome) not in completed
        assert devices.finish_calls == 1
    finally:
        service.release.set()
        controller.shutdown()


def test_capture_keeps_device_reads_available_while_blocking_device_writes(
    tmp_path: Path,
) -> None:
    outcome = CaptureCreated(SnapshotInfo("snapshot-1", "today", "device-1", "RoadPod"))
    service = _BlockingCaptureService(outcome)
    devices = _Devices(cast("ActiveIPod", object()))
    controller = _controller(service, devices, tmp_path / "native")

    try:
        assert controller.create_snapshot() is True
        assert service.started.wait(1)

        assert controller.busy is True
        assert devices.busy is False
        assert devices.device_writes_allowed is False
    finally:
        service.release.set()
        controller.shutdown()


def test_successful_reload_releases_restore_write_block(tmp_path: Path) -> None:
    outcome = RestoreCompleted(
        "target-snapshot",
        "safety-snapshot",
        FlushResult(complete=True, detail="flushed"),
    )
    service = _RestoreService(outcome)
    devices = _Devices(cast("ActiveIPod", object()))
    controller = _controller(service, devices, tmp_path / "native")

    try:
        assert controller.restore_snapshot("device-1", "target-snapshot") is True
        _wait_until(lambda: not controller.busy and service.inventory_calls == 1)
        assert _write_policy(controller) is DeviceWritePolicy.BLOCKED_UNTIL_RELOAD

        devices.replace_active_ipod(cast("ActiveIPod", object()))

        assert _write_policy(controller) is DeviceWritePolicy.ALLOWED
    finally:
        controller.shutdown()


def test_unchanged_restore_refreshes_archive_without_blocking_device_writes(
    tmp_path: Path,
) -> None:
    outcome = RestoreUnchanged("target-snapshot", "safety-snapshot")
    service = _RestoreService(outcome)
    devices = _Devices(cast("ActiveIPod", object()))
    controller = _controller(service, devices, tmp_path / "native")

    try:
        assert controller.restore_snapshot("device-1", "target-snapshot") is True
        _wait_until(lambda: not controller.busy and service.inventory_calls == 1)

        assert controller.device_write_policy is DeviceWritePolicy.ALLOWED
        assert devices.reload_calls == 0
        assert devices.finish_calls == 1
    finally:
        controller.shutdown()


def test_controller_passes_explicit_legacy_confirmation_to_service(
    tmp_path: Path,
) -> None:
    service = _RestoreService(RestoreCancelled("legacy-snapshot"))
    controller = _controller(
        service,
        _Devices(cast("ActiveIPod", object())),
        tmp_path / "native",
    )

    try:
        assert (
            controller.restore_snapshot(
                "legacy--roadpod",
                "legacy-snapshot",
                legacy_confirmed=True,
            )
            is True
        )
        _wait_until(lambda: not controller.busy)

        assert service.legacy_confirmations == [True]
    finally:
        controller.shutdown()


def test_incomplete_restore_reloads_refreshes_and_blocks_more_restore_writes(
    tmp_path: Path,
) -> None:
    failure = BackupFailure(
        BackupFailureCode.VERIFICATION_FAILED,
        "Restored content could not be verified.",
        "Recover the interrupted restore.",
    )
    outcome = RestoreIncomplete(
        "target-snapshot",
        "safety-snapshot",
        DevicePath(".iopenpod-recovery/restore.json"),
        failure,
    )
    service = _RestoreService(outcome)
    devices = _Devices(cast("ActiveIPod", object()))
    controller = _controller(service, devices, tmp_path / "native")
    policies: list[DeviceWritePolicy] = []
    controller.deviceWritePolicyChanged.connect(policies.append)

    try:
        assert controller.restore_snapshot("device-1", "target-snapshot") is True
        _wait_until(lambda: not controller.busy and service.inventory_calls == 1)

        assert devices.reload_calls == 1
        assert (
            controller.device_write_policy is DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY
        )
        assert policies[-1] is DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY
        assert controller.restore_snapshot("device-1", "target-snapshot") is False
        assert service.restore_calls == 1
    finally:
        controller.shutdown()


def test_safety_snapshot_created_before_restore_failure_refreshes_archive(
    tmp_path: Path,
) -> None:
    failure = BackupFailure(
        BackupFailureCode.INSUFFICIENT_SPACE,
        "There is not enough space to restore this snapshot.",
        "Free space on the iPod and try again.",
    )
    outcome = RestorePreMutationFailure(
        "target-snapshot",
        failure,
        safety_snapshot_id="safety-snapshot",
    )
    service = _RestoreService(outcome)
    active = cast("ActiveIPod", object())
    devices = _Devices(active)
    controller = _controller(service, devices, tmp_path / "native")
    completed: list[tuple[BackupOperation, object]] = []
    controller.operationCompleted.connect(_completion_slot(completed))

    try:
        controller.restore_snapshot("device-1", "target-snapshot")
        _wait_until(lambda: not controller.busy and service.inventory_calls == 1)

        assert (BackupOperation.RESTORE, outcome) in completed
        assert devices.reload_calls == 0
        assert devices.finish_calls == 1
    finally:
        controller.shutdown()


def test_pending_recovery_survives_refresh_and_can_run_while_writes_are_blocked(
    tmp_path: Path,
) -> None:
    outcome = RestoreRecovered(
        "target-snapshot",
        "safety-snapshot",
        FlushResult(True, "recovered and flushed"),
    )
    service = _RecoveryService(outcome)
    devices = _Devices(cast("ActiveIPod", object()))
    controller = _controller(service, devices, tmp_path / "native")
    completed: list[tuple[BackupOperation, object]] = []
    controller.operationCompleted.connect(_completion_slot(completed))

    try:
        controller.refresh()
        _wait_until(
            lambda: (
                not controller.busy
                and controller.device_write_policy
                is DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY
            )
        )
        assert controller.restore_snapshot("device", "snapshot") is False

        assert controller.recover_restore("recovery-1") is True
        _wait_until(
            lambda: (
                not controller.busy
                and service.recovery_calls == ["recovery-1"]
                and controller.device_write_policy
                is DeviceWritePolicy.BLOCKED_UNTIL_RELOAD
            )
        )
        devices.replace_active_ipod(cast("ActiveIPod", object()))

        assert (BackupOperation.RECOVER_RESTORE, outcome) in completed
        assert devices.reload_calls == 1
        assert controller.device_write_policy is DeviceWritePolicy.ALLOWED
    finally:
        controller.shutdown()


def test_unexpected_exception_uses_one_safe_failure_signal_and_logs_cause(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_cause = "credential at C:\\private\\archive was rejected"
    devices = _Devices(cast("ActiveIPod", object()))
    service = _FailingCaptureService(RuntimeError(raw_cause))
    controller = _controller(
        service,
        devices,
        tmp_path / "native",
    )
    failures: list[BackupOperationFailure] = []
    completed: list[tuple[BackupOperation, object]] = []
    controller.operationFailed.connect(failures.append)
    controller.operationCompleted.connect(_completion_slot(completed))

    try:
        controller.create_snapshot()
        _wait_until(
            lambda: (
                not controller.busy and bool(failures) and service.inventory_calls == 1
            )
        )

        failure = failures[-1]
        assert failure.failure.code is BackupFailureCode.UNEXPECTED
        assert raw_cause not in failure.message
        assert raw_cause not in failure.failure.summary
        assert raw_cause not in failure.failure.action
        assert failure.failure.detail == ""
        assert all(
            operation is not BackupOperation.CREATE for operation, _result in completed
        )
        assert service.inventory_calls == 1
        assert raw_cause in caplog.text
    finally:
        controller.shutdown()


def test_expected_capture_failure_uses_one_terminal_outcome_signal(
    tmp_path: Path,
) -> None:
    failure = BackupFailure(
        BackupFailureCode.ARCHIVE_UNAVAILABLE,
        "The backup location is unavailable.",
        "Reconnect it and retry.",
    )
    outcome = CaptureFailed(failure)
    devices = _Devices(cast("ActiveIPod", object()))
    service = _CaptureOutcomeService(outcome)
    controller = _controller(
        service,
        devices,
        tmp_path / "native",
    )
    failures: list[BackupOperationFailure] = []
    completed: list[tuple[BackupOperation, object]] = []
    controller.operationFailed.connect(failures.append)
    controller.operationCompleted.connect(_completion_slot(completed))

    try:
        assert controller.create_snapshot() is True
        _wait_until(lambda: not controller.busy and bool(completed))

        assert failures == []
        assert [item for item in completed if item[0] is BackupOperation.CREATE] == [
            (BackupOperation.CREATE, outcome)
        ]
        assert service.inventory_calls == 1
    finally:
        controller.shutdown()


def test_unexpected_restore_failure_blocks_more_writes_and_requests_reload(
    tmp_path: Path,
) -> None:
    devices = _Devices(cast("ActiveIPod", object()))
    controller = _controller(
        _FailingRestoreService(RuntimeError("opaque transaction failure")),
        devices,
        tmp_path / "native",
    )
    failures: list[BackupOperationFailure] = []
    controller.operationFailed.connect(failures.append)

    try:
        assert controller.restore_snapshot("device-1", "snapshot-1") is True
        _wait_until(lambda: not controller.busy and bool(failures))

        assert failures[-1].requires_device_reload is True
        assert failures[-1].failure.code is BackupFailureCode.UNEXPECTED
        assert (
            controller.device_write_policy is DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY
        )
        assert devices.reload_calls == 1
        assert controller.restore_snapshot("device-1", "snapshot-1") is False
    finally:
        controller.shutdown()
