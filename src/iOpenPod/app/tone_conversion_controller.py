"""Cancellable tone preparation, independent of Library edits and publication."""

from __future__ import annotations

import logging
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from device_registry import FeatureSupport
from iOpenPod.app.tone_conversion import (
    ToneArrangement,
    can_convert_track,
    convert_track_to_tone,
)

if TYPE_CHECKING:
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.playback.backend import PlaybackSourceProvider
    from iPodDB.library import Track
    from storage.media_processing import MediaToolFinder

_LOGGER = logging.getLogger(__name__)


class _CancelledError(Exception):
    pass


class _Signals(QObject):
    completed = Signal(object, object)
    progress = Signal(object, str)


class _Conversion(QRunnable):
    def __init__(
        self,
        track: Track,
        active: ActiveIPod,
        provider: PlaybackSourceProvider,
        find_tool: MediaToolFinder | None,
    ) -> None:
        super().__init__()
        self.track, self.active, self.provider, self.find_tool = (
            track,
            active,
            provider,
            find_tool,
        )
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise _CancelledError

        outcome: ToneArrangement | Exception
        try:
            outcome = convert_track_to_tone(
                self.track,
                self.provider,
                checkpoint=checkpoint,
                report=lambda message: self.signals.progress.emit(self, message),
                find_tool=self.find_tool,
            )
        except Exception as error:
            outcome = error
        self.signals.completed.emit(self, outcome)


class ToneConversionController(QObject):
    changed = Signal()

    def __init__(
        self,
        devices: DeviceController,
        provider: PlaybackSourceProvider,
        parent: QObject | None = None,
        *,
        find_tool: MediaToolFinder | None = None,
    ) -> None:
        super().__init__(parent)
        self._devices, self._provider, self._find_tool = devices, provider, find_tool
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job: _Conversion | None = None
        self._target: ActiveIPod | None = None
        self._closed = False
        self.arrangement: ToneArrangement | None = None
        self.message = ""
        self.error = ""
        devices.activeIPodChanged.connect(self._device_changed)

    @property
    def busy(self) -> bool:
        return self._job is not None

    def start(self, track: Track) -> bool:
        active = self._devices.active_ipod
        if (
            self._closed
            or self.busy
            or active is None
            or not can_convert_track(track)
            or active.profile.capabilities.extras.custom_tones
            is not FeatureSupport.SUPPORTED
        ):
            return False
        if (
            track not in active.library.tracks
            or not self._devices.begin_read_only_operation()
        ):
            return False
        self._target = active
        self.arrangement, self.message, self.error = None, "Reading the track…", ""
        job = _Conversion(track, active, self._provider, self._find_tool)
        self._job = job
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        job.signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self.changed.emit()
        self._pool.start(job)
        return True

    def cancel(self) -> None:
        if self._job is not None:
            self._job.cancelled.set()
        self.arrangement = None
        self.changed.emit()

    @Slot(object)
    def _device_changed(self, _active: object) -> None:
        if self._devices.active_ipod is not self._target:
            self.cancel()

    @Slot(object, str)
    def _progress(self, job: object, message: str) -> None:
        if job is self._job and not self._closed:
            self.message = message
            self.changed.emit()

    @Slot(object, object)
    def _completed(self, job: object, outcome: object) -> None:
        if job is not self._job or not isinstance(job, _Conversion) or self._closed:
            return
        self._devices.finish_read_only_operation()
        self._job = None
        self.message = ""
        if not job.cancelled.is_set() and self._devices.active_ipod is job.active:
            if isinstance(outcome, ToneArrangement):
                self.arrangement = outcome
            elif not isinstance(outcome, _CancelledError):
                self.error = str(outcome)
                _LOGGER.warning("Tone conversion failed: %s", outcome)
        self.changed.emit()

    def shutdown(self) -> None:
        self._closed = True
        self.cancel()
        self._pool.waitForDone()
        if self._job is not None:
            self._devices.finish_read_only_operation()
        self._job = None


__all__ = ["ToneConversionController"]
