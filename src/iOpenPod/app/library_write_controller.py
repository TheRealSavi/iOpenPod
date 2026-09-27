"""Background preparation with revision-bound review results and cooperative cancellation."""

from __future__ import annotations

import logging
import threading
from enum import StrEnum
from time import perf_counter
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot

from iOpenPod.app.core.settings.definitions import (
    DRAFT_ALL_CHANGES,
    MANAGE_VOLUME_PRESENTATION,
)
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    LibraryPreparationService,
    LibraryReview,
    LibrarySaveResult,
    PreparationCancelledError,
    WriteProgress,
    WriteTraceEvent,
)
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.track_playback_policy import enforce_library_playback_policy
from iPodDB.library import (
    IssueSeverity,
    LibraryWriteResult,
    WriteIssue,
)

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.library_workspace import EditRevision, LibraryWorkspace

logger = logging.getLogger(__name__)


class PreparationState(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    READY = "ready"
    BLOCKED = "blocked"
    STALE = "stale"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SAVING = "saving"
    SAVED = "saved"
    SAVE_FAILED = "save_failed"


class _Signals(QObject):
    progress = Signal(int, object)
    completed = Signal(int, object)


class _Work(QRunnable):
    def __init__(
        self,
        token: int,
        service: LibraryPreparationService,
        request: LibraryPreparationRequest,
    ) -> None:
        super().__init__()
        self.token = token
        self.service = service
        self.request = request
        self.cancelled = threading.Event()
        self.signals = _Signals()

    def run(self) -> None:
        try:
            review = self.service.prepare_library(
                self.request,
                lambda phase: self.signals.progress.emit(self.token, phase),
                self.cancelled,
            )
        except PreparationCancelledError:
            self.signals.completed.emit(self.token, None)
        except Exception:
            logger.exception("Unexpected Library preparation failure")
            self.signals.completed.emit(
                self.token,
                LibraryReview(
                    None,
                    LibraryWriteResult(
                        (
                            WriteIssue(
                                "preparation.internal_error",
                                "Preparation failed unexpectedly. Details were recorded in the application log.",
                                phase="application",
                            ),
                        )
                    ),
                ),
            )
        else:
            self.signals.completed.emit(self.token, review)


class LibraryWriteController(QObject):
    changed = Signal()
    progressChanged = Signal(str)
    automaticSaveFailed = Signal()
    automaticSaveWarning = Signal()

    def __init__(
        self,
        service: LibraryPreparationService,
        workspace: LibraryWorkspace,
        devices: DeviceController,
        settings: SettingsService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._workspace = workspace
        self._devices = devices
        self._settings = settings
        self._attempted_revision: EditRevision | None = None
        self._automatic_save_timer = QTimer(self)
        self._automatic_save_timer.setSingleShot(True)
        self._automatic_save_timer.timeout.connect(self._advance_automatic_save)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._token = 0
        self._closed = False
        self._jobs: dict[int, _Work | _SaveWork] = {}
        self._request: LibraryPreparationRequest | None = None
        self._source_invalidated = False
        self._trace: list[WriteTraceEvent] = []
        self._started = perf_counter()
        self.state = PreparationState.IDLE
        self.review: LibraryReview | None = None
        self._inspection_review: LibraryReview | None = None
        self.save_result: LibrarySaveResult | None = None
        workspace.changed.connect(self._invalidate)
        devices.activeIPodChanged.connect(self._source_changed)
        devices.busyChanged.connect(self._device_availability_changed)
        devices.deviceWritesAllowedChanged.connect(self._device_availability_changed)
        settings.settingChanged.connect(self._setting_changed)
        self.changed.connect(self._schedule_automatic_save)
        self._schedule_automatic_save()

    @property
    def draft_all_changes(self) -> bool:
        return self._settings.get(DRAFT_ALL_CHANGES)

    @Slot(str, object)
    def _setting_changed(self, key: str, _value: object) -> None:
        if key == MANAGE_VOLUME_PRESENTATION.key:
            # An executing transaction finishes under its captured policy. All
            # other attempts must be prepared again with the new preference.
            if self.state is not PreparationState.SAVING:
                self._source_invalidated = True
                self._attempted_revision = None
                self._invalidate()
            return
        if key == DRAFT_ALL_CHANGES.key:
            if self.state not in (
                PreparationState.PREPARING,
                PreparationState.READY,
                PreparationState.SAVING,
            ):
                self._attempted_revision = None
            self.changed.emit()

    @Slot()
    def _schedule_automatic_save(self) -> None:
        if self._closed or self.draft_all_changes:
            self._automatic_save_timer.stop()
        else:
            # Finish the edit and its synchronous observers before capturing it.
            self._automatic_save_timer.start(0)

    @Slot()
    def _advance_automatic_save(self) -> None:
        active = self._devices.active_ipod
        if (
            self._closed
            or self.draft_all_changes
            or not self._workspace.dirty
            or self._workspace.locked
            or active is None
            or self._workspace.snapshot is not active.library
        ):
            return
        if self.state is PreparationState.READY and self._request_is_current():
            if self.can_save:
                self.save()
        elif (
            self.can_prepare
            and self._attempted_revision != self._workspace.edit_revision
        ):
            # Retry a new edit, never loop over the same failed/cancelled attempt.
            self.prepare()

    def _report_automatic_failure(self) -> None:
        if not self.draft_all_changes:
            self.automaticSaveFailed.emit()

    @property
    def request(self) -> LibraryPreparationRequest | None:
        return self._request

    @property
    def trace(self) -> tuple[WriteTraceEvent, ...]:
        return tuple(self._trace)

    def _record(self, phase: str, message: str) -> None:
        self._trace.append(
            WriteTraceEvent(
                phase, message, round((perf_counter() - self._started) * 1000, 3)
            )
        )
        # The current attempt only; malformed/repetitive observers remain bounded.
        if len(self._trace) > 256:
            del self._trace[0]
        logger.debug(
            "Library write attempt=%d stage=%s elapsed_ms=%.3f message=%s",
            self._token,
            phase,
            self._trace[-1].elapsed_ms,
            message,
        )

    def _request_is_current(self) -> bool:
        request, active = self.request, self._devices.active_ipod
        return (
            request is not None
            and active is not None
            and not self._source_invalidated
            and request.source.candidate.id == active.candidate.id
            and request.source.library is active.library
            and request.workspace_generation == self._workspace.generation
            and request.workspace_revision == self._workspace.revision
        )

    def inspection_json(self) -> str:
        """Capture this attempt for a developer without granting save authority."""
        from iOpenPod.app.library_write_inspection import inspect_library_write

        return inspect_library_write(
            self.request,
            self.review or self._inspection_review,
            state=self.state.value,
            trace=self.trace,
            save=self.save_result,
            request_is_current=self._request_is_current(),
            current_revision=(self._workspace.generation, self._workspace.revision),
        )

    @property
    def can_prepare(self) -> bool:
        return (
            not self._closed
            and self._devices.active_ipod is not None
            and self._workspace.dirty
            and not self._devices.busy
            and self.state not in (PreparationState.PREPARING, PreparationState.SAVING)
        )

    @property
    def can_save(self) -> bool:
        return (
            not self._closed
            and self._devices.device_writes_allowed
            and self.state is PreparationState.READY
            and self.review is not None
            and self.review.result.prepared is not None
            and self._request_is_current()
        )

    @property
    def has_draft_changes(self) -> bool:
        return self._workspace.dirty

    @property
    def can_discard_changes(self) -> bool:
        return (
            not self._closed and self.has_draft_changes and not self._workspace.locked
        )

    @Slot()
    def discard_changes(self) -> None:
        if not self.can_discard_changes:
            return
        for job in self._jobs.values():
            job.cancelled.set()
        self._token += 1
        self._request = None
        self.review = None
        self._inspection_review = None
        self.save_result = None
        self._source_invalidated = False
        self._trace.clear()
        self.state = PreparationState.IDLE
        self._workspace.reset_changes()
        self.changed.emit()

    @Slot()
    def save(self) -> None:
        active = self._devices.active_ipod
        if not self.can_save or active is None or self.review is None:
            return
        if not self._devices.begin_library_save():
            return
        self._token += 1
        self.state = PreparationState.SAVING
        self._record(
            "application.saving", "Saving requested for the reviewed candidate"
        )
        self.save_result = None
        self._workspace.set_locked(True)
        job = _SaveWork(self._token, self._service, self.review, active)
        self._jobs[self._token] = job
        job.signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        job.signals.completed.connect(
            self._save_completed, Qt.ConnectionType.QueuedConnection
        )
        self.changed.emit()
        self._pool.start(job)

    @Slot(bool)
    def _device_availability_changed(self, _available: bool) -> None:
        self.changed.emit()

    @Slot(object)
    def _source_changed(self, value: object) -> None:
        if isinstance(value, ActiveIPod) and value.library is self._workspace.snapshot:
            return
        self._source_invalidated = True
        self._invalidate()

    @Slot()
    def prepare(self) -> None:
        active = self._devices.active_ipod
        if not self.can_prepare or active is None:
            return
        self._attempted_revision = self._workspace.edit_revision
        self._token += 1
        self._request = LibraryPreparationRequest(
            enforce_library_playback_policy(self._workspace.desired_snapshot()),
            active,
            self._workspace.generation,
            self._workspace.revision,
            delete_omissions=self._workspace.delete_omissions,
            artwork=self._workspace.artwork_assets,
            media=self._workspace.media_sources,
        )
        logger.debug(
            "Library write request attempt=%d workspace_generation=%d workspace_revision=%d "
            "candidate=%s iTunesDB=%s ArtworkDB=%s tracks=%d playlists=%d",
            self._token,
            self._request.workspace_generation,
            self._request.workspace_revision,
            active.candidate.id,
            active.database_fingerprint,
            active.artwork_database_fingerprint,
            len(self._request.snapshot.tracks),
            len(self._request.snapshot.playlists),
        )
        self._source_invalidated = False
        self._trace.clear()
        self._started = perf_counter()
        self._record("application.preparing", "Preparation requested")
        self.review = None
        self._inspection_review = None
        self.save_result = None
        self.state = PreparationState.PREPARING
        job = _Work(self._token, self._service, self._request)
        self._jobs[self._token] = job
        job.signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self.changed.emit()
        self._pool.start(job)

    @Slot()
    def cancel(self) -> None:
        if self.state is PreparationState.SAVING:
            self._record(
                "application.cancel_requested",
                "Cancellation requested; publication may already have started",
            )
            for job in self._jobs.values():
                job.cancelled.set()
            return
        for job in self._jobs.values():
            job.cancelled.set()
        self._token += 1
        self.review = None
        self.state = PreparationState.CANCELLED
        self._record(
            "application.cancelled", "Preparation cancelled; candidate discarded"
        )
        self.changed.emit()

    @Slot()
    def _invalidate(self) -> None:
        if self.state is PreparationState.SAVING:
            if not self._request_is_current():
                self.cancel()
            return
        if self._request_is_current():
            return
        if self.state in (
            PreparationState.PREPARING,
            PreparationState.READY,
            PreparationState.BLOCKED,
        ):
            self.cancel()
            self.state = PreparationState.STALE
            self._record(
                "application.stale",
                "Request no longer matches the current workspace or source",
            )
        self.changed.emit()

    @Slot(int, object)
    def _save_completed(self, token: int, value: object) -> None:
        job = self._jobs.pop(token, None)
        if self._closed or token != self._token:
            return
        result = (
            value if isinstance(value, LibrarySaveResult) else LibrarySaveResult(())
        )
        logger.debug(
            "Library save result attempt=%d saved=%s recovery=%r",
            token,
            result.active is not None,
            result.recovery_path,
        )
        for issue in result.issues:
            logger.debug("Library save issue attempt=%d %s", token, issue)
        active = self._devices.active_ipod
        if (
            not self._request_is_current()
            or not isinstance(job, _SaveWork)
            or active is None
            or active.library is not job.active.library
        ):
            self.save_result = LibrarySaveResult(
                (
                    *result.issues,
                    WriteIssue(
                        "save.stale_result",
                        "The save belongs to an earlier Library. Reload that iPod before further edits.",
                        severity=IssueSeverity.WARNING
                        if result.active
                        else IssueSeverity.ERROR,
                        phase="save",
                    ),
                ),
                recovery_path=result.recovery_path,
            )
            self.state = PreparationState.STALE
            self._record(
                "application.stale",
                "Request no longer matches the current workspace or source",
            )
            self._workspace.set_locked(False)
            self._devices.finish_library_save(None)
            self.changed.emit()
            self._report_automatic_failure()
            return
        self.save_result = result
        self.state = (
            PreparationState.SAVED
            if result.active is not None
            else PreparationState.SAVE_FAILED
        )
        if result.active is not None:
            prepared = self.review.result.prepared if self.review else None
            mapping = (
                {}
                if prepared is None
                else {
                    i.draft_id: i.output_id
                    for i in prepared.identities
                    if i.subject == "playlist"
                }
            )
            self._workspace.load(result.active.library, saved_playlist_ids=mapping)
        self._record("application." + self.state.value, "Save result received")
        self._workspace.set_locked(False)
        self._devices.finish_library_save(result.active)
        self.changed.emit()
        if result.active is None:
            self._report_automatic_failure()
        elif not self.draft_all_changes and any(
            issue.code in ("save.cleanup_pending", "save.cleanup_flush_pending")
            for issue in result.issues
        ):
            self.automaticSaveWarning.emit()

    @Slot(int, object)
    def _progress(self, token: int, progress: object) -> None:
        if (
            token == self._token
            and not self._closed
            and isinstance(progress, WriteProgress)
        ):
            self._record(progress.phase, progress.message)
            self.progressChanged.emit(progress.message)

    @Slot(int, object)
    def _completed(self, token: int, value: object) -> None:
        self._jobs.pop(token, None)
        if isinstance(value, LibraryReview):
            logger.debug(
                "Library review received attempt=%d prepared=%s issues=%d",
                token,
                value.result.prepared is not None,
                len(value.result.issues),
            )
            for issue in value.result.issues:
                logger.debug("Library review issue attempt=%d %s", token, issue)
        if self._closed or token != self._token:
            logger.debug(
                "Library review ignored attempt=%d current_attempt=%d closed=%s",
                token,
                self._token,
                self._closed,
            )
            return
        if not self._request_is_current():
            self._invalidate()
            return
        if not isinstance(value, LibraryReview):
            self.state = PreparationState.CANCELLED
        else:
            self.review = value
            self._inspection_review = value
            self.state = (
                PreparationState.READY
                if value.result.prepared
                else PreparationState.BLOCKED
            )
            if any(i.code == "preparation.internal_error" for i in value.result.issues):
                self.state = PreparationState.FAILED
        self._record("application." + self.state.value, "Preparation result received")
        self.changed.emit()
        if self.state in (PreparationState.BLOCKED, PreparationState.FAILED):
            self._report_automatic_failure()

    def shutdown(self) -> None:
        self._closed = True
        self._automatic_save_timer.stop()
        for job in self._jobs.values():
            job.cancelled.set()
        self._pool.clear()
        self._pool.waitForDone()
        self._jobs.clear()


class _SaveWork(QRunnable):
    def __init__(
        self,
        token: int,
        service: LibraryPreparationService,
        review: LibraryReview,
        active: ActiveIPod,
    ) -> None:
        super().__init__()
        self.token, self.service, self.review, self.active = (
            token,
            service,
            review,
            active,
        )
        self.cancelled = threading.Event()
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.service.save_library(
                self.review,
                self.active,
                lambda text: self.signals.progress.emit(self.token, text),
                self.cancelled,
            )
        except PreparationCancelledError:
            result = LibrarySaveResult(
                (
                    WriteIssue(
                        "save.cancelled",
                        "Saving cancelled before publication.",
                        phase="save",
                    ),
                )
            )
        except Exception:
            logger.exception("Unexpected Library save failure")
            result = LibrarySaveResult(
                (
                    WriteIssue(
                        "save.internal_error",
                        "Saving failed unexpectedly. Reload the iPod before retrying. See the application log for details.",
                        phase="save",
                    ),
                )
            )
        self.signals.completed.emit(self.token, result)
