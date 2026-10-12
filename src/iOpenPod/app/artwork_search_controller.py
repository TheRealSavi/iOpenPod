"""Cancellable Qt worker adapter for album artwork searches and previews."""

from __future__ import annotations

from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, Qt, QThreadPool, Signal

from iOpenPod.app.artwork_search import (
    ArtworkCandidate,
    ArtworkSearchClient,
    ArtworkSource,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from iPodDB.library import ArtworkPixels


class _Signals(QObject):
    completed = Signal(int, object, str)


class _Work(QRunnable):
    def __init__(
        self, token: int, operation: Callable[[Callable[[], None]], object]
    ) -> None:
        super().__init__()
        self.token = token
        self.operation = operation
        self.cancelled = Event()
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise InterruptedError

        try:
            checkpoint()
            result = self.operation(checkpoint)
            checkpoint()
        except InterruptedError:
            self.signals.completed.emit(self.token, None, "")
        except Exception as error:
            self.signals.completed.emit(self.token, None, str(error))
        else:
            self.signals.completed.emit(self.token, result, "")
        finally:
            # Release closures that may retain an authentication token.
            self.operation = lambda _check: None


class ArtworkSearchController(QObject):
    """Reject stale work and keep closing a dialog independent of network I/O."""

    finished = Signal(object)
    failed = Signal(str)
    busyChanged = Signal(bool)

    def __init__(self, client: ArtworkSearchClient | None = None) -> None:
        # Application ownership retains running workers after their dialog closes.
        # Completion releases this controller once cancelled jobs have drained.
        super().__init__(QCoreApplication.instance())
        self._client = client or ArtworkSearchClient()
        self._jobs: dict[int, _Work] = {}
        self._token = 0
        self._closed = False
        self.busy = False

    def search(
        self, source: ArtworkSource, term: str, *, country: str, token: str
    ) -> None:
        def operation(checkpoint: Callable[[], None]) -> tuple[ArtworkCandidate, ...]:
            return self._client.search(
                source, term, country=country, token=token, checkpoint=checkpoint
            )

        self._start(operation)

    def load(self, candidate: ArtworkCandidate) -> None:
        def operation(checkpoint: Callable[[], None]) -> ArtworkPixels:
            return self._client.load(candidate, checkpoint=checkpoint)

        self._start(operation)

    def _start(self, operation: Callable[[Callable[[], None]], object]) -> None:
        if self._closed:
            return
        self.cancel()
        job = _Work(self._token, operation)
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self._jobs[self._token] = job
        self.busy = True
        self.busyChanged.emit(True)
        QThreadPool.globalInstance().start(job)

    def cancel(self) -> None:
        self._token += 1
        for job in self._jobs.values():
            job.cancelled.set()
        self.busy = False
        self.busyChanged.emit(False)

    def _completed(self, token: int, result: object, error: str) -> None:
        self._jobs.pop(token, None)
        if self._closed:
            if not self._jobs:
                self.deleteLater()
            return
        if token != self._token:
            return
        self.busy = False
        self.busyChanged.emit(False)
        if error:
            self.failed.emit(error)
        elif result is not None:
            self.finished.emit(result)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.cancel()
        if not self._jobs:
            self.deleteLater()
