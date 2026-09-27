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
    ROCKBOX_METADATA_SUPPORT,
    ROTATE_TALL_PHOTOS,
)
from iOpenPod.app.core.settings.transcoding import read_transcoder_settings
from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.models.device import DeviceCandidateIssueCode
from iOpenPod.app.services.device_coordinator import (
    SyncCleanupCompletedError,
    SyncRecoveryDeclinedError,
    SyncRecoveryRequiredError,
    SyncRecoveryRestoredError,
    SyncRestoredCleanupPendingError,
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
    from iOpenPod.app.podcasts.sync import PodcastSyncRequest
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
        except SyncRestoredCleanupPendingError as error:
            result = SyncExecutionResult(
                SyncExecutionStatus.RECOVERY_REQUIRED,
                issues=(
                    WriteIssue(
                        "sync.restored_cleanup_pending",
                        "The previous Library is restored. Retry recovery to finish cleaning its temporary files.",
                        detail=exception_text(error),
                    ),
                ),
                recovery_path=self.path,
            )
        except SyncRecoveryRestoredError as error:
            result = SyncExecutionResult(
                SyncExecutionStatus.CANCELLED,
                issues=(
                    WriteIssue(
                        "sync.recovered",
                        exception_text(error),
                        severity=IssueSeverity.WARNING,
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
                        detail=exception_text(error),
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


class _KeepContentsWork(QRunnable):
    def __init__(self, keep: Callable[[str], ActiveIPod], path: str) -> None:
        super().__init__()
        self.keep = keep
        self.path = path
        self.result: SyncExecutionResult | None = None
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        active = None
        path = ""
        status = SyncExecutionStatus.FAILED
        code = "sync.kept_current"
        message = (
            "Current contents were kept. The interrupted Sync may be incomplete. "
            "Recovery copies remain beside declined-transaction.json on the iPod. "
            "Scan again before starting another Sync."
        )
        try:
            active = self.keep(self.path)
        except SyncRecoveryDeclinedError as error:
            message = exception_text(error)
        except Exception as error:
            status = SyncExecutionStatus.RECOVERY_REQUIRED
            code = "sync.keep_failed"
            message = source_text(
                "Could not finish keeping current contents. {detail}",
                detail=exception_text(error),
            )
            path = (
                error.recovery_path
                if isinstance(error, SyncRecoveryRequiredError)
                else self.path
            )
        result = SyncExecutionResult(
            status,
            active=active,
            recovery_path=path,
            issues=(WriteIssue(code, message, severity=IssueSeverity.WARNING),),
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
                        detail=exception_text(error),
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
                        exception_text(error),
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
                        detail=exception_text(error),
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
    podcastStateInvalidated = Signal()

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
        keep_contents: Callable[[str], ActiveIPod] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._workspace = workspace
        self._devices = devices
        self._settings = settings
        self._recover = recovery
        self._cleanup = cleanup
        self._keep_contents = keep_contents
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job: (
            _SyncWork | _RecoveryWork | _CleanupWork | _KeepContentsWork | None
        ) = None
        self._closed = False
        self.result: SyncExecutionResult | None = None
        self.last_error = ""
        devices.activeIPodChanged.connect(self._source_changed)
        devices.recoveryRequired.connect(self._recovery_discovered)
        devices.cleanupAvailable.connect(self._cleanup_discovered)

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
        podcasts: PodcastSyncRequest | None = None,
    ) -> bool:
        self.last_error = ""
        if self.needs_recovery:
            self.last_error = "Restore the interrupted Sync or choose Keep Current Contents before starting another one."
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
        if (
            podcasts is None
            and not plan.change_count
            and not (
                reconcile_playlists and preview_playlist_sync(plan, host, ipod, source)
            )
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
                podcasts=podcasts,
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

    def start_podcasts(self, podcasts: PodcastSyncRequest, source: ActiveIPod) -> bool:
        """Run Podcast intent through the same reservation and execution lifecycle."""
        from iOpenPod.app.host_media_library import (
            HostMediaCacheStats,
            HostMediaLibrary,
        )
        from iOpenPod.app.library_sync_helper import (
            IPodMediaCacheStats,
            IPodMediaLibrary,
        )
        from iOpenPod.app.sync_plan import SyncPlan
        from iPodDB.library import LibrarySnapshot

        return self.start(
            SyncPlan(()),
            HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
            IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
            source,
            reconcile_playlists=False,
            podcasts=podcasts,
        )

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
    def _source_changed(self, value: object) -> None:
        self.cancel()
        if (
            not self.busy
            and value is not None
            and (self.needs_recovery or self.needs_cleanup)
        ):
            # A recovery choice belongs to one iPod, not to the whole app.
            if self.needs_recovery:
                self._workspace.set_locked(False)
                self._devices.set_recovery_required(False)
            self.result = None
            self.changed.emit()

    def keep_current_contents(self) -> bool:
        """Apply the user's explicit decision to decline restoration/cleanup."""
        result = self.result
        if (
            self._closed
            or self.busy
            or result is None
            or not result.recovery_path
            or self._keep_contents is None
        ):
            self.last_error = "No recovery choice is available."
            return False
        if not self._devices.begin_recovery_operation():
            self.last_error = "Wait for the current iPod operation to finish."
            return False
        self._workspace.set_locked(True)
        job = _KeepContentsWork(self._keep_contents, result.recovery_path)
        self._job = job
        job.signals.finished.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self.changed.emit()
        self._pool.start(job)
        return True

    @Slot(str)
    def _cleanup_discovered(self, path: str) -> None:
        if self.busy or self.needs_recovery:
            return
        active = self._devices.active_ipod
        detail = (
            "\n".join(
                issue.detail
                for issue in active.candidate.issues
                if issue.code is DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING
            )
            if active is not None
            else ""
        )
        self.result = SyncExecutionResult(
            SyncExecutionStatus.SUCCESS,
            issues=(
                WriteIssue(
                    "sync.cleanup_pending",
                    "A finished transaction has retained recovery files. Retry Cleanup to reclaim space, "
                    "or keep the current contents and recovery copies.",
                    severity=IssueSeverity.WARNING,
                    detail=detail,
                    artifact=path,
                ),
            ),
            recovery_path=path,
        )
        self.changed.emit()

    @Slot(str)
    def _recovery_discovered(self, path: str) -> None:
        self.cancel()
        self.result = SyncExecutionResult(
            SyncExecutionStatus.RECOVERY_REQUIRED,
            issues=(
                WriteIssue(
                    "sync.pending_recovery",
                    "An interrupted transaction was found. "
                    "Restore the previous Library or choose Keep Current Contents. "
                    "Keeping current contents may leave the interrupted Sync incomplete.",
                ),
            ),
            recovery_path=path,
        )
        self._devices.set_recovery_required(True)
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
        if isinstance(job, (_RecoveryWork, _KeepContentsWork)):
            self._workspace.active_ipod_changed(value.active)
            self._devices.finish_sync_recovery(value.active)
        elif current and value.active is not None:
            self._workspace.active_ipod_changed(value.active)
            self._devices.finish_library_save(value.active)
        else:
            self._devices.finish_library_save(None)
        self._workspace.set_locked(self.needs_recovery)
        self._job = None
        if (
            not self._closed
            and current
            and isinstance(job, _SyncWork)
            and job.request.podcasts is not None
            and value.active is None
            and value.status
            in (SyncExecutionStatus.FAILED, SyncExecutionStatus.CANCELLED)
        ):
            # Refresh/history publication can succeed before media preparation fails.
            # Reload their revisions even when no replacement Library is published.
            self.podcastStateInvalidated.emit()
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
            # not have run. Publish its final state before closing the app.
            self._completed(self._job.result)
        if self._job is not None:
            self._job = None
            self._devices.finish_exclusive_operation()
            self._workspace.set_locked(self.needs_recovery)


__all__ = ["SyncController"]
