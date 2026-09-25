"""Qt adapter for non-blocking Backup Snapshot workflows."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.backups import (
    BackupCancelledError,
    BackupCatalog,
    BackupInventory,
    BackupProgress,
    BackupReason,
    BackupRestoreResult,
    SnapshotInfo,
)
from iOpenPod.app.backups.outcomes import (
    BackupFailure,
    BackupFailureCode,
    CaptureCancelled,
    CaptureCreated,
    CaptureFailed,
    CaptureUnchanged,
    DeviceWritePolicy,
    FollowUpRequirement,
    ImportCompleted,
    RestoreCancelled,
    RestoreCompleted,
    RestoreDurabilityPending,
    RestoreIncomplete,
    RestorePreMutationFailure,
    RestoreRecovered,
    RestoreUnchanged,
)
from iOpenPod.app.backups.service import backup_failure_for
from iOpenPod.app.core.settings.definitions import BACKUP_LOCATION, MAX_BACKUPS

_LOGGER = logging.getLogger(__name__)
_NO_ACTIVE_IPOD_CHECK = object()
_UNEXPECTED_FAILURE = BackupFailure(
    BackupFailureCode.UNEXPECTED,
    "The Backup operation could not be completed safely.",
    "Review the application log, then try again.",
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.backups.service import BackupService
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.device_controller import DeviceController


class BackupOperation(StrEnum):
    REFRESH = "refresh"
    LOAD_CATALOG = "load_catalog"
    CREATE = "create"
    RESTORE = "restore"
    RECOVER_RESTORE = "recover_restore"
    DELETE = "delete"
    EXPORT = "export"
    IMPORT_ORIGINAL = "import_original"
    UPDATE_NOTE = "update_note"


class _DeviceReservationMode(StrEnum):
    READ_ONLY = "read_only"
    EXCLUSIVE = "exclusive"


@dataclass(frozen=True, slots=True)
class BackupOperationFailure:
    operation: BackupOperation
    message: str
    error_type: str
    requires_device_reload: bool = False
    failure: BackupFailure = _UNEXPECTED_FAILURE


class _Signals(QObject):
    progress = Signal(int, object)
    succeeded = Signal(int, object, object)
    failed = Signal(int, object, object)
    finished = Signal(int, object)


class _Work(QRunnable):
    def __init__(
        self,
        token: int,
        operation: BackupOperation,
        backup_root: Path,
        expected_active_ipod: object,
        work: Callable[[threading.Event, Callable[[BackupProgress], None]], object],
    ) -> None:
        super().__init__()
        self.token = token
        self.operation = operation
        self.backup_root = backup_root
        self.expected_active_ipod = expected_active_ipod
        self.work = work
        self.cancelled = threading.Event()
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.work(
                self.cancelled,
                lambda value: self.signals.progress.emit(self.token, value),
            )
        except Exception as error:
            self.signals.failed.emit(self.token, self.operation, error)
        else:
            self.signals.succeeded.emit(self.token, self.operation, result)
        finally:
            self.signals.finished.emit(self.token, self.operation)


class BackupController(QObject):
    """Run archive and device I/O away from the GUI thread."""

    inventoryChanged = Signal(object)
    catalogChanged = Signal(object)
    progressChanged = Signal(object)
    busyChanged = Signal(bool)
    operationFailed = Signal(object)
    operationCancelled = Signal(object)
    operationCompleted = Signal(object, object)
    deviceWritePolicyChanged = Signal(object)

    def __init__(
        self,
        service: BackupService,
        devices: DeviceController,
        settings: SettingsService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._devices = devices
        self._settings = settings
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._token = 0
        self._active_token: int | None = None
        self._jobs: dict[int, _Work] = {}
        self._device_reservation: _DeviceReservationMode | None = None
        self._closed = False
        self._busy = False
        self._refresh_after = False
        self._reload_after = False
        self._device_write_policy = DeviceWritePolicy.ALLOWED
        self.inventory = BackupInventory(())
        self.catalog: BackupCatalog | None = None
        devices.activeIPodChanged.connect(self._active_ipod_changed)

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def backup_root(self) -> Path:
        return Path(self._settings.get(BACKUP_LOCATION))

    @property
    def device_write_policy(self) -> DeviceWritePolicy:
        return self._device_write_policy

    def archive_path(self, device_id: str = "") -> Path:
        """Resolve a native archive path without exposing its layout to the GUI."""

        return self._service.archive_path(self.backup_root, device_id)

    @Slot()
    def refresh(self) -> None:
        root = self.backup_root
        self._begin(
            BackupOperation.REFRESH,
            lambda _cancelled, _progress: self._service.inventory(root),
            backup_root=root,
        )

    @Slot(str)
    def load_catalog(self, device_id: str) -> None:
        root = self.backup_root
        self._begin(
            BackupOperation.LOAD_CATALOG,
            lambda _cancelled, _progress: self._service.catalog(root, device_id),
            backup_root=root,
        )

    @Slot()
    def create_snapshot(self) -> bool:
        active = self._devices.active_ipod
        reservation = _DeviceReservationMode.READ_ONLY
        if active is None or not self._reserve_device(reservation):
            return False
        root = self.backup_root
        maximum = self._settings.get(MAX_BACKUPS)
        return self._begin(
            BackupOperation.CREATE,
            lambda cancelled, progress: self._service.create_snapshot(
                root,
                active,
                max_backups=maximum,
                reason=BackupReason.MANUAL,
                progress=progress,
                cancelled=cancelled.is_set,
            ),
            backup_root=root,
            expected_active_ipod=active,
            device_reservation=reservation,
        )

    @Slot(str, str)
    def restore_snapshot(
        self,
        device_id: str,
        snapshot_id: str,
        *,
        legacy_confirmed: bool = False,
    ) -> bool:
        active = self._devices.active_ipod
        reservation = _DeviceReservationMode.EXCLUSIVE
        if (
            active is None
            or self._device_write_policy is not DeviceWritePolicy.ALLOWED
            or not self._reserve_device(reservation)
        ):
            return False
        root = self.backup_root
        return self._begin(
            BackupOperation.RESTORE,
            lambda cancelled, progress: self._service.restore_snapshot(
                root,
                active,
                device_id=device_id,
                snapshot_id=snapshot_id,
                progress=progress,
                cancelled=cancelled.is_set,
                legacy_confirmed=legacy_confirmed,
            ),
            backup_root=root,
            expected_active_ipod=active,
            device_reservation=reservation,
        )

    @Slot(str)
    def recover_restore(self, recovery_id: str) -> bool:
        """Run the one mutation allowed while Restore Recovery blocks writes."""

        active = self._devices.active_ipod
        reservation = _DeviceReservationMode.EXCLUSIVE
        if active is None or not self._reserve_device(reservation):
            return False
        root = self.backup_root
        return self._begin(
            BackupOperation.RECOVER_RESTORE,
            lambda cancelled, progress: self._service.recover_restore(
                root,
                active,
                recovery_id=recovery_id,
                progress=progress,
                cancelled=cancelled.is_set,
            ),
            backup_root=root,
            expected_active_ipod=active,
            device_reservation=reservation,
        )

    @Slot(str, str)
    def delete_snapshot(self, device_id: str, snapshot_id: str) -> None:
        root = self.backup_root
        self._begin(
            BackupOperation.DELETE,
            lambda _cancelled, _progress: self._service.delete_snapshot(
                root, device_id, snapshot_id
            ),
            backup_root=root,
        )

    @Slot(str, str, str)
    def export_snapshot(
        self, device_id: str, snapshot_id: str, destination: str
    ) -> None:
        root = self.backup_root
        target = Path(destination)
        self._begin(
            BackupOperation.EXPORT,
            lambda cancelled, progress: self._service.export_snapshot(
                root,
                device_id,
                snapshot_id,
                target,
                progress=progress,
                cancelled=cancelled.is_set,
            ),
            backup_root=root,
        )

    @Slot(str)
    def import_original(self, source: str) -> bool:
        root = self.backup_root
        return self._begin(
            BackupOperation.IMPORT_ORIGINAL,
            lambda cancelled, progress: self._service.import_original(
                root,
                Path(source),
                progress=progress,
                cancelled=cancelled.is_set,
            ),
            backup_root=root,
        )

    @Slot(str, str, str)
    def update_note(self, device_id: str, snapshot_id: str, note: str) -> None:
        root = self.backup_root
        self._begin(
            BackupOperation.UPDATE_NOTE,
            lambda _cancelled, _progress: self._service.update_note(
                root, device_id, snapshot_id, note
            ),
            backup_root=root,
        )

    @Slot()
    def cancel(self) -> None:
        if self._active_token is None:
            return
        job = self._jobs.get(self._active_token)
        if job is not None:
            job.cancelled.set()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        for job in self._jobs.values():
            job.cancelled.set()
        self._pool.clear()
        self._pool.waitForDone()
        self._jobs.clear()
        self._release_device()

    def _reserve_device(self, mode: _DeviceReservationMode) -> bool:
        if self._busy or self._closed:
            return False
        reserved = (
            self._devices.begin_read_only_operation()
            if mode is _DeviceReservationMode.READ_ONLY
            else self._devices.begin_exclusive_operation()
        )
        if not reserved:
            return False
        self._device_reservation = mode
        return True

    def _release_device(self) -> None:
        reservation = self._device_reservation
        self._device_reservation = None
        if reservation is _DeviceReservationMode.READ_ONLY:
            self._devices.finish_read_only_operation()
        elif reservation is _DeviceReservationMode.EXCLUSIVE:
            self._devices.finish_exclusive_operation()

    def _begin(
        self,
        operation: BackupOperation,
        work: Callable[[threading.Event, Callable[[BackupProgress], None]], object],
        *,
        backup_root: Path,
        expected_active_ipod: object = _NO_ACTIVE_IPOD_CHECK,
        device_reservation: _DeviceReservationMode | None = None,
    ) -> bool:
        if self._busy or self._closed:
            if device_reservation is not None:
                self._release_device()
            return False
        self._token += 1
        token = self._token
        job = _Work(
            token,
            operation,
            backup_root,
            expected_active_ipod,
            work,
        )
        job.signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        job.signals.succeeded.connect(
            self._succeeded, Qt.ConnectionType.QueuedConnection
        )
        job.signals.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        job.signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self._active_token = token
        self._jobs[token] = job
        self._set_busy(True)
        self._pool.start(job)
        return True

    @Slot(int, object)
    def _progress(self, token: int, value: object) -> None:
        job = self._jobs.get(token)
        if (
            token == self._active_token
            and job is not None
            and self._job_is_current(job)
            and isinstance(value, BackupProgress)
        ):
            self.progressChanged.emit(value)

    @Slot(int, object, object)
    def _succeeded(self, token: int, operation: object, result: object) -> None:
        if token != self._active_token or self._closed:
            return
        job = self._jobs.get(token)
        if job is None or not self._job_is_current(job):
            return
        resolved = BackupOperation(str(operation))
        if resolved is BackupOperation.REFRESH and isinstance(result, BackupInventory):
            self.inventory = result
            if result.pending_recoveries:
                self._set_device_write_policy(DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY)
            self.inventoryChanged.emit(result)
        elif resolved is BackupOperation.LOAD_CATALOG and isinstance(
            result, BackupCatalog
        ):
            self.catalog = result
            self.catalogChanged.emit(result)
        elif resolved is BackupOperation.CREATE:
            if isinstance(result, CaptureCreated):
                self._refresh_after = True
            elif isinstance(result, CaptureFailed):
                # Capture publication is atomic, but a later retention or
                # durability failure can occur after the new catalog appears.
                self._refresh_after = True
            elif isinstance(result, CaptureCancelled):
                self.operationCancelled.emit(resolved)
            elif isinstance(result, SnapshotInfo):
                result = CaptureCreated(result)
                self._refresh_after = True
            elif result is None:
                result = CaptureUnchanged("")
        elif resolved in {BackupOperation.DELETE, BackupOperation.UPDATE_NOTE} or (
            resolved is BackupOperation.IMPORT_ORIGINAL
            and isinstance(result, ImportCompleted)
        ):
            self._refresh_after = True
        elif resolved in {
            BackupOperation.RESTORE,
            BackupOperation.RECOVER_RESTORE,
        }:
            if isinstance(
                result,
                (
                    RestoreCompleted,
                    RestoreUnchanged,
                    RestoreRecovered,
                    RestoreDurabilityPending,
                    RestoreCancelled,
                    RestorePreMutationFailure,
                    RestoreIncomplete,
                ),
            ):
                self._refresh_after = (
                    result.follow_up.archive_refresh is FollowUpRequirement.REQUIRED
                )
                self._reload_after = (
                    result.follow_up.device_reload is FollowUpRequirement.REQUIRED
                )
                self._set_device_write_policy(result.follow_up.device_writes)
                if resolved is BackupOperation.RECOVER_RESTORE and isinstance(
                    result,
                    (RestorePreMutationFailure, RestoreIncomplete),
                ):
                    self._set_device_write_policy(
                        DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY
                    )
            elif isinstance(result, BackupRestoreResult):
                self._refresh_after = True
                self._reload_after = True
        self.operationCompleted.emit(resolved, result)

    @Slot(int, object, object)
    def _failed(self, token: int, operation: object, error: object) -> None:
        if token != self._active_token or self._closed:
            return
        job = self._jobs.get(token)
        if job is None or not self._job_is_current(job):
            return
        resolved = BackupOperation(str(operation))
        if resolved in {
            BackupOperation.CREATE,
            BackupOperation.RESTORE,
            BackupOperation.RECOVER_RESTORE,
            BackupOperation.DELETE,
            BackupOperation.IMPORT_ORIGINAL,
            BackupOperation.UPDATE_NOTE,
        }:
            # Reconcile the catalog even when a worker stopped after a Host-side
            # publication boundary; the refreshed archive remains authoritative.
            self._refresh_after = True
        if resolved in {
            BackupOperation.RESTORE,
            BackupOperation.RECOVER_RESTORE,
        }:
            self._reload_after = True
            self._set_device_write_policy(DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY)
        if isinstance(error, BackupCancelledError):
            self.operationCancelled.emit(resolved)
            return
        if isinstance(error, BaseException):
            _LOGGER.error(
                "Unexpected exception during Backup operation %s",
                resolved.value,
                exc_info=(type(error), error, error.__traceback__),
            )
        else:
            _LOGGER.error(
                "Unexpected non-exception failure during Backup operation %s: %r",
                resolved.value,
                error,
            )
        failure = (
            backup_failure_for(error, operation=resolved.value)
            if isinstance(error, Exception)
            else _UNEXPECTED_FAILURE
        )
        reported = BackupOperationFailure(
            resolved,
            failure.summary,
            type(error).__name__,
            requires_device_reload=resolved
            in {BackupOperation.RESTORE, BackupOperation.RECOVER_RESTORE},
            failure=failure,
        )
        self.operationFailed.emit(reported)

    @Slot(int, object)
    def _finished(self, token: int, _operation: object) -> None:
        self._jobs.pop(token, None)
        if token != self._active_token:
            return
        self._active_token = None
        self._release_device()
        self._set_busy(False)
        reload_after, refresh_after = self._reload_after, self._refresh_after
        self._reload_after = False
        self._refresh_after = False
        if reload_after:
            self._devices.reload_active_ipod()
        if refresh_after:
            self.refresh()

    def _set_busy(self, value: bool) -> None:
        if value == self._busy:
            return
        self._busy = value
        self.busyChanged.emit(value)

    def _job_is_current(self, job: _Work) -> bool:
        return job.backup_root == self.backup_root and (
            job.expected_active_ipod is _NO_ACTIVE_IPOD_CHECK
            or self._devices.active_ipod is job.expected_active_ipod
        )

    def _set_device_write_policy(self, value: DeviceWritePolicy) -> None:
        if value is self._device_write_policy:
            return
        self._device_write_policy = value
        self.deviceWritePolicyChanged.emit(value)

    @Slot(object)
    def _active_ipod_changed(self, value: object) -> None:
        if (
            value is not None
            and self._device_write_policy is DeviceWritePolicy.BLOCKED_UNTIL_RELOAD
        ):
            self._set_device_write_policy(DeviceWritePolicy.ALLOWED)


__all__ = [
    "BackupController",
    "BackupOperation",
    "BackupOperationFailure",
]
