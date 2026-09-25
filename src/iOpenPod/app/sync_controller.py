"""Reserve one clean Library Workspace while a reviewed Sync runs off the GUI thread."""

from __future__ import annotations

import logging
from dataclasses import replace
from threading import Event
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.core.settings.definitions import (
    COMPUTE_SOUND_CHECK,
    FIT_THUMBNAILS,
    NORMALIZE_TAGS_AFTER_SYNC,
    PENDING_SYNC_CLEANUP,
    PENDING_SYNC_RECOVERY,
    ROCKBOX_METADATA_SUPPORT,
    ROTATE_TALL_PHOTOS,
)
from iOpenPod.app.core.settings.transcoding import read_transcoder_settings
from iOpenPod.app.services.device_coordinator import (
    SyncCleanupCompletedError,
    SyncRecoveryRequiredError,
    SyncRecoveryRestoredError,
)
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionResult,
    SyncExecutionStatus,
    SyncOptions,
    preview_playlist_sync,
)
from iPodDB.library import IssueSeverity, WriteIssue

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.host_media_library import HostMediaLibrary
    from iOpenPod.app.library_sync_helper import IPodMediaLibrary
    from iOpenPod.app.library_workspace import LibraryWorkspace
    from iOpenPod.app.library_write import WriteProgress
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.sync_plan import SyncPlan

logger = logging.getLogger(__name__)


class SyncExecutionService(Protocol):
    def execute(
        self,
        request: SyncExecutionRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> SyncExecutionResult: ...


class _Signals(QObject):
    progress = Signal(object)
    finished = Signal(object)


class _SyncWork(QRunnable):
    def __init__(
        self, service: SyncExecutionService, request: SyncExecutionRequest
    ) -> None:
        super().__init__()
        self.service = service
        self.request = request
        self.result: SyncExecutionResult | None = None
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.service.execute(
                self.request, self.signals.progress.emit, self.cancelled
            )
        except Exception:
            logger.exception("Unexpected Sync execution failure")
            result = SyncExecutionResult(
                SyncExecutionStatus.FAILED,
                issues=(
                    WriteIssue(
                        "sync.internal_error",
                        "Sync stopped unexpectedly. Reload the iPod before retrying; "
                        "inspect any retained Storage recovery journal first. "
                        "Details are in the application log.",
                        phase="sync",
                    ),
                ),
            )
        self.result = result
        self.signals.finished.emit(result)


class _RecoveryWork(QRunnable):
    def __init__(self, recover: Callable[[str], ActiveIPod], path: str) -> None:
        super().__init__()
        self.recover = recover
        self.path = path
        self.result: SyncExecutionResult | None = None
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        try:
            active = self.recover(self.path)
        except SyncRecoveryRestoredError as error:
            result = SyncExecutionResult(
                SyncExecutionStatus.CANCELLED,
                issues=(
                    WriteIssue(
                        "sync.recovered", str(error), severity=IssueSeverity.WARNING
                    ),
                ),
            )
        except Exception as error:
            logger.exception("Sync recovery could not complete")
            result = SyncExecutionResult(
                SyncExecutionStatus.RECOVERY_REQUIRED,
                issues=(
                    WriteIssue(
                        "sync.recovery_failed",
                        "Recovery could not finish. "
                        "Keep the journal and reconnect the same iPod before retrying.",
                        detail=str(error),
                    ),
                ),
                recovery_path=(
                    error.recovery_path
                    if isinstance(error, SyncRecoveryRequiredError)
                    else self.path
                ),
            )
        else:
            result = SyncExecutionResult(
                SyncExecutionStatus.CANCELLED,
                active=active,
                issues=(
                    WriteIssue(
                        "sync.recovered",
                        "The previous Library was restored, "
                        "temporary device files were cleaned up, and the iPod was reloaded. "
                        "Scan again before starting another Sync.",
                        severity=IssueSeverity.WARNING,
                    ),
                ),
            )
        self.result = result
        self.signals.finished.emit(result)


class _CleanupWork(QRunnable):
    def __init__(
        self, cleanup: Callable[[str], None], previous: SyncExecutionResult
    ) -> None:
        super().__init__()
        self.cleanup = cleanup
        self.previous = previous
        self.result: SyncExecutionResult | None = None
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        issues = tuple(
            issue
            for issue in self.previous.issues
            if issue.code != "sync.cleanup_pending"
        )
        try:
            self.cleanup(self.previous.recovery_path)
        except SyncRecoveryRequiredError as error:
            result = SyncExecutionResult(
                SyncExecutionStatus.RECOVERY_REQUIRED,
                issues=(
                    *issues,
                    WriteIssue(
                        "sync.recovery_required",
                        "The transaction is unfinished and requires recovery before further changes.",
                        detail=str(error),
                    ),
                ),
                recovery_path=error.recovery_path,
            )
        except SyncCleanupCompletedError as error:
            result = replace(
                self.previous,
                active=None,
                recovery_path="",
                issues=(
                    *issues,
                    WriteIssue(
                        "sync.cleanup_flush_pending",
                        str(error),
                        severity=IssueSeverity.WARNING,
                    ),
                ),
            )
        except Exception as error:
            logger.exception("Committed Sync cleanup could not complete")
            result = replace(
                self.previous,
                active=None,
                issues=(
                    *issues,
                    WriteIssue(
                        "sync.cleanup_pending",
                        "Sync remains committed. Reconnect the same iPod and choose Retry Cleanup. "
                        "Safely eject before unplugging.",
                        severity=IssueSeverity.WARNING,
                        detail=str(error),
                    ),
                ),
            )
        else:
            result = replace(
                self.previous,
                active=None,
                recovery_path="",
                issues=(
                    *issues,
                    WriteIssue(
                        "sync.cleaned",
                        "Recovery files were cleaned up. Safely eject before unplugging.",
                        severity=IssueSeverity.WARNING,
                    ),
                ),
            )
        self.result = result
        self.signals.finished.emit(result)


class SyncController(QObject):
    """Keep device selection, Library edits, and settings stable for one execution."""

    changed = Signal()
    progressChanged = Signal(object)
    finished = Signal(object)

    def __init__(
        self,
        service: SyncExecutionService,
        workspace: LibraryWorkspace,
        devices: DeviceController,
        settings: SettingsService,
        parent: QObject | None = None,
        *,
        recovery: Callable[[str], ActiveIPod] | None = None,
        cleanup: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._workspace = workspace
        self._devices = devices
        self._settings = settings
        self._recover = recovery
        self._cleanup = cleanup
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job: _SyncWork | _RecoveryWork | _CleanupWork | None = None
        self._closed = False
        self.result: SyncExecutionResult | None = None
        self.last_error = ""
        devices.activeIPodChanged.connect(self._source_changed)
        devices.recoveryRequired.connect(self._recovery_discovered)
        pending = settings.get(PENDING_SYNC_RECOVERY)
        if pending:
            self.result = SyncExecutionResult(
                SyncExecutionStatus.RECOVERY_REQUIRED,
                issues=(
                    WriteIssue(
                        "sync.pending_recovery",
                        "A previous Sync was interrupted. "
                        "Reconnect the same iPod and choose Retry Recovery before making further changes.",
                    ),
                ),
                recovery_path=pending,
            )
            devices.set_recovery_required(True)
            workspace.set_locked(True)
        elif cleanup_path := settings.get(PENDING_SYNC_CLEANUP):
            self.result = SyncExecutionResult(
                SyncExecutionStatus.SUCCESS,
                issues=(
                    WriteIssue(
                        "sync.cleanup_pending",
                        "A previous Sync completed but recovery-file cleanup is pending. "
                        "Reconnect the same iPod and choose Retry Cleanup.",
                        severity=IssueSeverity.WARNING,
                    ),
                ),
                recovery_path=cleanup_path,
            )

    @property
    def busy(self) -> bool:
        return self._job is not None

    @property
    def needs_recovery(self) -> bool:
        return (
            self.result is not None
            and self.result.status is SyncExecutionStatus.RECOVERY_REQUIRED
        )

    @property
    def needs_cleanup(self) -> bool:
        return (
            self.result is not None
            and self.result.status
            in (SyncExecutionStatus.SUCCESS, SyncExecutionStatus.PARTIAL)
            and bool(self.result.recovery_path)
        )

    def start(
        self,
        plan: SyncPlan,
        host: HostMediaLibrary,
        ipod: IPodMediaLibrary,
        source: ActiveIPod,
        *,
        reconcile_playlists: bool = True,
    ) -> bool:
        self.last_error = ""
        if self.needs_recovery:
            self.last_error = (
                "Recover the interrupted Sync before starting another one."
            )
            return False
        if self.needs_cleanup:
            self.last_error = "Choose Retry Cleanup for the previous Sync before starting another one."
            return False
        if self._closed or self.busy or self._workspace.locked:
            self.last_error = "Wait for the current Library operation to finish."
            return False
        if self._workspace.dirty:
            self.last_error = (
                "Save or discard pending Library changes, then scan again before Sync."
            )
            return False
        if (
            self._devices.active_ipod is not source
            or self._workspace.snapshot is not source.library
        ):
            self.last_error = (
                "The Active iPod or Library changed. Scan again before Sync."
            )
            return False
        if not plan.change_count and not (
            reconcile_playlists and preview_playlist_sync(plan, host, ipod, source)
        ):
            self.last_error = "Select at least one change in Review."
            return False
        try:
            request = SyncExecutionRequest(
                plan,
                host,
                ipod,
                source,
                self._workspace.generation,
                self._workspace.revision,
                settings=read_transcoder_settings(self._settings),
                options=SyncOptions(
                    compute_sound_check=self._settings.get(COMPUTE_SOUND_CHECK),
                    normalize_tags=self._settings.get(NORMALIZE_TAGS_AFTER_SYNC),
                    rotate_tall_photos=self._settings.get(ROTATE_TALL_PHOTOS),
                    fit_thumbnails=self._settings.get(FIT_THUMBNAILS),
                    rockbox_metadata=self._settings.get(ROCKBOX_METADATA_SUPPORT),
                ),
                reconcile_playlists=reconcile_playlists,
            )
        except ValueError as error:
            self.last_error = f"Check the transcoding settings: {error}"
            return False
        if not self._devices.begin_exclusive_operation():
            self.last_error = (
                "Wait for the current iPod operation to finish, then retry."
            )
            return False
        self._workspace.set_locked(True)
        self.result = None
        job = _SyncWork(self._service, request)
        self._job = job
        job.signals.progress.connect(
            self.progressChanged.emit, Qt.ConnectionType.QueuedConnection
        )
        job.signals.finished.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self.changed.emit()
        self._pool.start(job)
        return True

    @Slot()
    def cancel(self) -> None:
        if self._job is not None:
            self._job.cancelled.set()

    def recover(self) -> bool:
        result = self.result
        if (
            self._closed
            or self.busy
            or not self.needs_recovery
            or result is None
            or self._recover is None
        ):
            self.last_error = "No interrupted Sync is available for recovery."
            return False
        if not self._devices.begin_recovery_operation():
            self.last_error = "Wait for the current iPod operation to finish."
            return False
        self._workspace.set_locked(True)
        job = _RecoveryWork(self._recover, result.recovery_path)
        self._job = job
        job.signals.finished.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self.changed.emit()
        self._pool.start(job)
        return True

    def cleanup(self) -> bool:
        result = self.result
        if (
            self._closed
            or self.busy
            or not self.needs_cleanup
            or result is None
            or self._cleanup is None
        ):
            self.last_error = "No completed Sync needs cleanup."
            return False
        if not self._devices.begin_recovery_operation():
            self.last_error = "Wait for the current iPod operation to finish."
            return False
        self._workspace.set_locked(True)
        job = _CleanupWork(self._cleanup, result)
        self._job = job
        job.signals.finished.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self.changed.emit()
        self._pool.start(job)
        return True

    @Slot(object)
    def _source_changed(self, _value: object) -> None:
        self.cancel()

    @Slot(str)
    def _recovery_discovered(self, path: str) -> None:
        self.cancel()
        self.result = SyncExecutionResult(
            SyncExecutionStatus.RECOVERY_REQUIRED,
            issues=(
                WriteIssue(
                    "sync.pending_recovery",
                    "An interrupted transaction was found. "
                    "Reconnect the same iPod and choose Retry Recovery before making further changes.",
                ),
            ),
            recovery_path=path,
        )
        self._workspace.set_locked(True)
        self.changed.emit()
        if not self._closed:
            self.finished.emit(self.result)

    @Slot(object)
    def _completed(self, value: object) -> None:
        job = self._job
        if job is None or not isinstance(value, SyncExecutionResult):
            return
        current = not isinstance(job, _SyncWork) or (
            self._devices.active_ipod is job.request.source
            and self._workspace.generation == job.request.workspace_generation
            and self._workspace.revision == job.request.workspace_revision
        )
        if not current and value.status is not SyncExecutionStatus.RECOVERY_REQUIRED:
            value = replace(
                value,
                status=SyncExecutionStatus.FAILED,
                issues=(
                    *value.issues,
                    WriteIssue(
                        "sync.stale_result",
                        "This Sync belongs to an earlier Library. Its result was not loaded. "
                        "Reload that iPod before further edits.",
                    ),
                ),
            )
        self.result = value
        self._devices.set_recovery_required(self.needs_recovery)
        try:
            self._settings.set_global(
                PENDING_SYNC_RECOVERY,
                value.recovery_path if self.needs_recovery else "",
            )
            self._settings.set_global(
                PENDING_SYNC_CLEANUP,
                value.recovery_path if self.needs_cleanup else "",
            )
            self._settings.sync()
        except Exception:
            logger.exception("Could not persist the pending Sync recovery location")
        if isinstance(job, _RecoveryWork):
            self._workspace.active_ipod_changed(value.active)
            self._devices.finish_sync_recovery(value.active)
        elif current and value.active is not None:
            self._workspace.active_ipod_changed(value.active)
            self._devices.finish_library_save(value.active)
        else:
            self._devices.finish_library_save(None)
        self._workspace.set_locked(self.needs_recovery)
        self._job = None
        self.changed.emit()
        if not self._closed:
            self.finished.emit(value)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.cancel()
        self._pool.waitForDone()
        if self._job is not None and self._job.result is not None:
            # The GUI loop is blocked while waiting, so the queued completion may
            # not have run. Persist its recovery location before closing the app.
            self._completed(self._job.result)
        if self._job is not None:
            self._job = None
            self._devices.finish_exclusive_operation()
            self._workspace.set_locked(self.needs_recovery)


__all__ = ["SyncController"]
