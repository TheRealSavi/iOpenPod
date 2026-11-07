"""Inspect one scanned Host source on demand without blocking stream choices."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.media.inspection import MediaInspector
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from iOpenPod.app.host_media_library import HostMediaSource
    from iOpenPod.app.media.models import MediaScanMetadata


@dataclass(frozen=True, slots=True)
class _Result:
    metadata: MediaScanMetadata | None = None
    error: str = ""


class _Signals(QObject):
    finished = Signal(object)


class _InspectWork(QRunnable):
    def __init__(self, source: HostMediaSource, inspector: MediaInspector) -> None:
        super().__init__()
        self.source = source
        self.inspector = inspector
        self.cancelled = Event()
        self.signals = _Signals()

    def checkpoint(self) -> None:
        if self.cancelled.is_set():
            raise InterruptedError("Stream inspection cancelled")

    def run(self) -> None:
        try:
            self.checkpoint()
            observed = LocalHostFile.observe(self.source.path)
            if (observed.size_bytes, observed.modified_ns) != (
                self.source.size_bytes,
                self.source.modified_ns,
            ):
                raise ValueError(
                    source_text(
                        "The Host file changed after scanning. Rescan before choosing streams."
                    )
                )
            metadata = self.inspector.scan_metadata(
                self.source.path, checkpoint=self.checkpoint
            )
            if LocalHostFile.observe(self.source.path) != observed:
                raise ValueError(
                    source_text(
                        "The Host file changed during inspection. Rescan before choosing streams."
                    )
                )
            self.checkpoint()
            result = _Result(metadata)
        except Exception as error:
            result = _Result(error=exception_text(error))
        self.signals.finished.emit(result)


class MediaStreamController(QObject):
    inspected = Signal(object)
    failed = Signal(object)

    def __init__(
        self, parent: QObject | None = None, *, inspector: MediaInspector | None = None
    ) -> None:
        super().__init__(parent)
        self._inspector = inspector or MediaInspector()
        self._work: _InspectWork | None = None

    @property
    def busy(self) -> bool:
        return self._work is not None

    def start(self, source: HostMediaSource) -> bool:
        if self.busy:
            return False
        work = _InspectWork(source, self._inspector)
        self._work = work
        work.signals.finished.connect(
            self._finished, Qt.ConnectionType.QueuedConnection
        )
        QThreadPool.globalInstance().start(work)
        return True

    def cancel(self) -> None:
        if self._work is not None:
            self._work.cancelled.set()

    @Slot(object)
    def _finished(self, value: object) -> None:
        work = self._work
        self._work = None
        if work is None or work.cancelled.is_set() or not isinstance(value, _Result):
            return
        if value.metadata is not None:
            self.inspected.emit(value.metadata)
        else:
            self.failed.emit(value.error)
