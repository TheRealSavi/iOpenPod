"""Qt adapter for cancellable Host Media Library scanning."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.host_media_library import (
    HostMediaLibrary,
    HostMediaScanCancelledError,
    HostMediaScanner,
    PendingHostMediaScan,
)

if TYPE_CHECKING:
    from iOpenPod.app.host_media_folders import HostMediaFolder
    from storage import HostPath

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _InitialResult:
    pending: PendingHostMediaScan | None = None
    library: HostMediaLibrary | None = None


class _Signals(QObject):
    completed = Signal(int, object, str)
    progress = Signal(int, object)


class _InitialScan(QRunnable):
    def __init__(
        self,
        token: int,
        folders: tuple[HostMediaFolder, ...],
        scanner: HostMediaScanner,
    ) -> None:
        super().__init__()
        self.token = token
        self.folders = folders
        self.scanner = scanner
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise HostMediaScanCancelledError

        try:
            pending = self.scanner.scan(
                self.folders,
                checkpoint=checkpoint,
                progress=lambda value: self.signals.progress.emit(self.token, value),
            )
            result = (
                _InitialResult(pending=pending)
                if pending.external_references
                else _InitialResult(
                    library=self.scanner.complete(
                        pending,
                        frozenset(),
                        checkpoint=checkpoint,
                        progress=lambda value: self.signals.progress.emit(
                            self.token, value
                        ),
                    )
                )
            )
        except HostMediaScanCancelledError:
            self.signals.completed.emit(self.token, None, "")
        except Exception as error:
            logger.exception("Host Media Library scan failed")
            self.signals.completed.emit(self.token, None, str(error))
        else:
            self.signals.completed.emit(self.token, result, "")


class _CompleteScan(QRunnable):
    def __init__(
        self,
        token: int,
        pending: PendingHostMediaScan,
        accepted: frozenset[HostPath],
        scanner: HostMediaScanner,
    ) -> None:
        super().__init__()
        self.token = token
        self.pending = pending
        self.accepted = accepted
        self.scanner = scanner
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise HostMediaScanCancelledError

        try:
            result = self.scanner.complete(
                self.pending,
                self.accepted,
                checkpoint=checkpoint,
                progress=lambda value: self.signals.progress.emit(self.token, value),
            )
        except HostMediaScanCancelledError:
            self.signals.completed.emit(self.token, None, "")
        except Exception as error:
            logger.exception("External playlist file scan failed")
            self.signals.completed.emit(self.token, None, str(error))
        else:
            self.signals.completed.emit(self.token, result, "")


type _ScanJob = _InitialScan | _CompleteScan


class HostMediaScanController(QObject):
    """Serialize Host scans and publish only immutable application results."""

    changed = Signal()
    progressChanged = Signal(object)
    externalReferencesFound = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        scanner: HostMediaScanner,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._scanner = scanner
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._token = 0
        self._closed = False
        self._jobs: dict[int, _ScanJob] = {}
        self._pending: PendingHostMediaScan | None = None
        self.busy = False
        self.latest_library: HostMediaLibrary | None = None

    @property
    def awaiting_external_decisions(self) -> bool:
        return self._pending is not None

    def start(self, folders: tuple[HostMediaFolder, ...]) -> bool:
        if self._closed or self.busy:
            return False
        self._token += 1
        self._pending = None
        self.busy = True
        job = _InitialScan(self._token, folders, self._scanner)
        self._start_job(job)
        self.changed.emit()
        return True

    def resolve_external(self, accepted: frozenset[HostPath]) -> bool:
        pending = self._pending
        if self._closed or not self.busy or pending is None:
            return False
        self._pending = None
        job = _CompleteScan(self._token, pending, accepted, self._scanner)
        self._start_job(job)
        self.changed.emit()
        return True

    @Slot()
    def cancel(self) -> None:
        if not self.busy:
            return
        self._token += 1
        for job in self._jobs.values():
            job.cancelled.set()
        self._pending = None
        self.busy = False
        self.changed.emit()
        self.cancelled.emit()

    def shutdown(self) -> None:
        self._closed = True
        self.cancel()
        self._pool.clear()
        self._pool.waitForDone()
        self._jobs.clear()

    def _start_job(self, job: _ScanJob) -> None:
        self._jobs[job.token] = job
        job.signals.completed.connect(
            self._completed,
            Qt.ConnectionType.QueuedConnection,
        )
        job.signals.progress.connect(
            self._progress,
            Qt.ConnectionType.QueuedConnection,
        )
        self._pool.start(job)

    @Slot(int, object)
    def _progress(self, token: int, value: object) -> None:
        if token == self._token and self.busy:
            self.progressChanged.emit(value)

    @Slot(int, object, str)
    def _completed(self, token: int, value: object, error: str) -> None:
        self._jobs.pop(token, None)
        if self._closed or token != self._token or not self.busy:
            return
        if error:
            self.busy = False
            self.failed.emit(error)
            self.changed.emit()
            return
        if isinstance(value, _InitialResult) and value.pending is not None:
            self._pending = value.pending
            self.externalReferencesFound.emit(value.pending.external_references)
            self.changed.emit()
            return
        library = (
            value.library
            if isinstance(value, _InitialResult)
            else value
            if isinstance(value, HostMediaLibrary)
            else None
        )
        if library is None:
            self.busy = False
            self.cancelled.emit()
            self.changed.emit()
            return
        self.latest_library = library
        self.busy = False
        self.finished.emit(library)
        self.changed.emit()


__all__ = ["HostMediaScanController"]
