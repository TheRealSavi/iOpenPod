"""Qt adapter for the post-Host-scan Active-iPod media scan."""

from __future__ import annotations

import logging
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.library_sync_helper import LibrarySyncHelperCancelledError

if TYPE_CHECKING:
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator

logger = logging.getLogger(__name__)


class _Signals(QObject):
    completed = Signal(int, object, str)
    progress = Signal(int, object)


class _IPodScan(QRunnable):
    def __init__(
        self,
        token: int,
        expected: ActiveIPod,
        coordinator: DeviceCoordinator,
    ) -> None:
        super().__init__()
        self.token = token
        self.expected = expected
        self.coordinator = coordinator
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.coordinator.scan_ipod_media(
                self.expected,
                lambda value: self.signals.progress.emit(self.token, value),
                self.cancelled,
            )
        except LibrarySyncHelperCancelledError:
            self.signals.completed.emit(self.token, None, "")
        except Exception as error:
            logger.exception("iPod media scan failed")
            self.signals.completed.emit(self.token, None, str(error))
        else:
            self.signals.completed.emit(self.token, result, "")


class IPodMediaScanController(QObject):
    """Reserve the Active iPod while its correlation helper is refreshed."""

    changed = Signal()
    progressChanged = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        coordinator: DeviceCoordinator,
        device_controller: DeviceController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._device_controller = device_controller
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._token = 0
        self._job: _IPodScan | None = None
        self._closed = False
        self.busy = False

    def start(self) -> bool:
        expected = self._device_controller.active_ipod
        if (
            self._closed
            or self.busy
            or expected is None
            or not self._device_controller.begin_exclusive_operation()
        ):
            return False
        self._token += 1
        self.busy = True
        job = _IPodScan(self._token, expected, self._coordinator)
        self._job = job
        job.signals.completed.connect(
            self._completed,
            Qt.ConnectionType.QueuedConnection,
        )
        job.signals.progress.connect(
            self._progress,
            Qt.ConnectionType.QueuedConnection,
        )
        self._pool.start(job)
        self.changed.emit()
        return True

    @Slot()
    def cancel(self) -> None:
        if self._job is not None:
            self._job.cancelled.set()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.cancel()
        self._pool.clear()
        self._pool.waitForDone()
        if self.busy:
            self._device_controller.finish_exclusive_operation()
        self._job = None
        self.busy = False

    @Slot(int, object)
    def _progress(self, token: int, value: object) -> None:
        if token == self._token and self.busy:
            self.progressChanged.emit(value)

    @Slot(int, object, str)
    def _completed(self, token: int, value: object, error: str) -> None:
        if token != self._token or not self.busy:
            return
        self._job = None
        self.busy = False
        self._device_controller.finish_exclusive_operation()
        self.changed.emit()
        if self._closed:
            return
        if error:
            self.failed.emit(error)
        elif value is None:
            self.cancelled.emit()
        else:
            self.finished.emit(value)


__all__ = ["IPodMediaScanController"]
