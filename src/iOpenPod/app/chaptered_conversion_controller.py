"""Revision-bound background conversion of a saved Music Album."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.chaptered_conversion import (
    ChapteredPreparation,
    can_convert_album,
    prepare_chaptered_album,
)
from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.models.track_order import album_track_sort_key

if TYPE_CHECKING:
    from tempfile import TemporaryDirectory

    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.library_workspace import EditRevision, LibraryWorkspace
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from iPodDB.library import Track

logger = logging.getLogger(__name__)


class _Signals(QObject):
    completed = Signal(int, object, str)
    progress = Signal(int, str)


class _Conversion(QRunnable):
    def __init__(
        self,
        token: int,
        tracks: tuple[Track, ...],
        active: ActiveIPod,
        coordinator: DeviceCoordinator,
        occupied_paths: tuple[str, ...],
    ) -> None:
        super().__init__()
        self.token = token
        self.tracks = tracks
        self.active = active
        self.coordinator = coordinator
        self.occupied_paths = occupied_paths
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise PreparationCancelledError

        try:
            self.signals.progress.emit(self.token, "Copying and checking Album Tracks…")
            result = prepare_chaptered_album(
                self.tracks,
                self.active,
                self.coordinator,
                self.occupied_paths,
                checkpoint=checkpoint,
                report=lambda message: self.signals.progress.emit(self.token, message),
            )
            try:
                checkpoint()
            except BaseException:
                result.directory.cleanup()
                raise
        except PreparationCancelledError:
            self.signals.completed.emit(self.token, None, "")
        except Exception as error:
            logger.exception("Chaptered Album conversion failed")
            self.signals.completed.emit(self.token, None, str(error))
        else:
            self.signals.completed.emit(self.token, result, "")


class ChapteredConversionController(QObject):
    changed = Signal()
    progressChanged = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        workspace: LibraryWorkspace,
        devices: DeviceController,
        coordinator: DeviceCoordinator,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._devices = devices
        self._coordinator = coordinator
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._token = 0
        self._jobs: dict[int, _Conversion] = {}
        self._directories: list[TemporaryDirectory[str]] = []
        self._revision: EditRevision = workspace.edit_revision
        self._source: ActiveIPod | None = None
        self._source_tracks: tuple[Track, ...] = ()
        self._closed = False
        self.busy = False
        workspace.changed.connect(self._invalidate)
        devices.activeIPodChanged.connect(self._invalidate)

    @property
    def can_start(self) -> bool:
        return (
            not self._closed
            and not self.busy
            and not self._devices.busy
            and not self._workspace.locked
            and self._devices.active_ipod is not None
        )

    def start(self, tracks: tuple[Track, ...]) -> bool:
        active = self._devices.active_ipod
        if not self.can_start or active is None:
            return False
        if not can_convert_album(tracks, self._workspace.tracks):
            raise ValueError(
                "Select a complete saved Music Album with at least two Tracks."
            )
        if not can_convert_album(tracks, active.library.tracks):
            raise ValueError(
                "Select a complete saved Music Album with at least two Tracks."
            )
        tracks = tuple(sorted(tracks, key=album_track_sort_key))
        self._token += 1
        self._revision, self._source = self._workspace.edit_revision, active
        self._source_tracks = tracks
        self.busy = True
        job = _Conversion(
            self._token,
            tracks,
            active,
            self._coordinator,
            tuple(
                t.metadata.location
                for t in (*active.library.tracks, *self._workspace.tracks)
            ),
        )
        self._jobs[self._token] = job
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        job.signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self.changed.emit()
        self._pool.start(job)
        return True

    @Slot()
    def cancel(self) -> None:
        self._token += 1
        for job in self._jobs.values():
            job.cancelled.set()
        self.busy = False
        self.changed.emit()

    def _invalidate(self, _value: object = None) -> None:
        if self.busy and (
            self._revision != self._workspace.edit_revision
            or self._devices.active_ipod is not self._source
            or self._workspace.locked
        ):
            self.cancel()
        used = {Path(source.source).parent for source in self._workspace.media_sources}
        retained: list[TemporaryDirectory[str]] = []
        for directory in self._directories:
            if Path(directory.name) in used:
                retained.append(directory)
            else:
                directory.cleanup()
        self._directories = retained

    @Slot(int, str)
    def _progress(self, token: int, message: str) -> None:
        if token == self._token and self.busy:
            self.progressChanged.emit(message)

    @Slot(int, object, str)
    def _completed(self, token: int, result: object, error: str) -> None:
        self._jobs.pop(token, None)
        if self._closed or token != self._token:
            if isinstance(result, ChapteredPreparation):
                result.directory.cleanup()
            return
        self._invalidate()
        if token != self._token:
            if isinstance(result, ChapteredPreparation):
                result.directory.cleanup()
            return
        self.busy = False
        if isinstance(result, ChapteredPreparation):
            try:
                self._directories.append(result.directory)
                self._workspace.replace_tracks_with_chaptered_song(
                    tuple(t.track_id for t in self._source_tracks),
                    result.song,
                    self._revision,
                )
            except ValueError as failure:
                self._directories.remove(result.directory)
                result.directory.cleanup()
                self.failed.emit(str(failure))
            else:
                self.finished.emit()
        elif error:
            self.failed.emit(error)
        self.changed.emit()

    def shutdown(self) -> None:
        self._closed = True
        self.cancel()
        self._pool.clear()
        self._pool.waitForDone()
        self._jobs.clear()
        for directory in self._directories:
            directory.cleanup()
        self._directories.clear()
