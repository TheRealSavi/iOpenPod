"""Run Host exports away from the GUI thread with cooperative cancellation."""

from __future__ import annotations

import logging
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.library_export import (
    ExportCancelledError,
    ExportProgress,
    ExportResult,
    LibraryExporter,
    PhotoExporter,
    PhotoExportResult,
    PlaylistExportMode,
    PlaylistFileType,
)

if TYPE_CHECKING:
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from iPodDB.library import Photo, Track
    from storage import HostPath

logger = logging.getLogger(__name__)


class _Signals(QObject):
    progress = Signal(int, object)
    completed = Signal(int, object, str, bool)


class _ExportWork(QRunnable):
    def __init__(
        self,
        token: int,
        exporter: LibraryExporter,
        photo_exporter: PhotoExporter,
        directory: HostPath,
        tracks: tuple[Track, ...],
        *,
        playlist_name: str | None = None,
        file_type: PlaylistFileType = PlaylistFileType.M3U8,
        mode: PlaylistExportMode = PlaylistExportMode.COPY_TRACKS,
        photos: tuple[Photo, ...] = (),
        photo_album_name: str | None = None,
    ) -> None:
        super().__init__()
        self.token = token
        self.exporter = exporter
        self.photo_exporter = photo_exporter
        self.directory = directory
        self.tracks = tracks
        self.playlist_name = playlist_name
        self.file_type = file_type
        self.mode = mode
        self.photos = photos
        self.photo_album_name = photo_album_name
        self.cancel_requested = Event()
        self.signals = _Signals()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancel_requested.is_set():
                raise ExportCancelledError

        def progress(value: ExportProgress) -> None:
            self.signals.progress.emit(self.token, value)

        try:
            result: ExportResult | PhotoExportResult
            if self.photos and self.photo_album_name is not None:
                result = self.photo_exporter.export_photo_album(
                    self.photo_album_name,
                    self.photos,
                    self.directory,
                    checkpoint=checkpoint,
                    progress=progress,
                )
            elif self.photos:
                result = self.photo_exporter.export_photos(
                    self.photos,
                    self.directory,
                    checkpoint=checkpoint,
                    progress=progress,
                )
            elif self.playlist_name is not None:
                result = self.exporter.export_playlist(
                    self.playlist_name,
                    self.tracks,
                    self.directory,
                    self.file_type,
                    self.mode,
                    checkpoint=checkpoint,
                    progress=progress,
                )
            else:
                result = self.exporter.export_tracks(
                    self.tracks,
                    self.directory,
                    checkpoint=checkpoint,
                    progress=progress,
                )
        except ExportCancelledError:
            self.signals.completed.emit(self.token, None, "", True)
        except Exception as error:
            logger.exception("Library export failed")
            self.signals.completed.emit(self.token, None, str(error), False)
        else:
            self.signals.completed.emit(self.token, result, "", False)


class LibraryExportController(QObject):
    """Own one background export and surface only current completion events."""

    progressChanged = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    busyChanged = Signal(bool)

    def __init__(
        self,
        coordinator: DeviceCoordinator,
        devices: DeviceController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._exporter = LibraryExporter(coordinator)
        self._photo_exporter = PhotoExporter(coordinator)
        self._devices = devices
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._jobs: dict[int, _ExportWork] = {}
        self._token = 0
        self._closed = False
        self.busy = False
        devices.activeIPodChanged.connect(self._source_changed)

    @property
    def can_start(self) -> bool:
        return (
            not self._closed and not self.busy and self._devices.active_ipod is not None
        )

    def start_tracks(self, tracks: tuple[Track, ...], directory: HostPath) -> bool:
        return self._start(
            _ExportWork(
                0,
                self._exporter,
                self._photo_exporter,
                directory,
                tracks,
            )
        )

    def start_playlist(
        self,
        name: str,
        tracks: tuple[Track, ...],
        directory: HostPath,
        file_type: PlaylistFileType,
        mode: PlaylistExportMode,
    ) -> bool:
        return self._start(
            _ExportWork(
                0,
                self._exporter,
                self._photo_exporter,
                directory,
                tracks,
                playlist_name=name,
                file_type=file_type,
                mode=mode,
            )
        )

    def start_photos(self, photos: tuple[Photo, ...], directory: HostPath) -> bool:
        return self._start(
            _ExportWork(
                0,
                self._exporter,
                self._photo_exporter,
                directory,
                (),
                photos=photos,
            )
        )

    def start_photo_album(
        self,
        name: str,
        photos: tuple[Photo, ...],
        directory: HostPath,
    ) -> bool:
        return self._start(
            _ExportWork(
                0,
                self._exporter,
                self._photo_exporter,
                directory,
                (),
                photos=photos,
                photo_album_name=name,
            )
        )

    def _start(self, job: _ExportWork) -> bool:
        if not job.tracks and not job.photos and job.playlist_name is None:
            return False
        if not self.can_start:
            return False
        self._token += 1
        job.token = self._token
        self._jobs[job.token] = job
        job.signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self.busy = True
        self.busyChanged.emit(True)
        self._pool.start(job)
        return True

    @Slot()
    def cancel(self) -> None:
        for job in self._jobs.values():
            job.cancel_requested.set()

    @Slot(object)
    def _source_changed(self, _active: object) -> None:
        if self.busy:
            self.cancel()

    @Slot(int, object)
    def _progress(self, token: int, value: object) -> None:
        if token == self._token and self.busy and isinstance(value, ExportProgress):
            self.progressChanged.emit(value)

    @Slot(int, object, str, bool)
    def _completed(
        self, token: int, value: object, error: str, was_cancelled: bool
    ) -> None:
        self._jobs.pop(token, None)
        if self._closed or token != self._token:
            return
        self.busy = False
        self.busyChanged.emit(False)
        if isinstance(value, ExportResult | PhotoExportResult):
            self.finished.emit(value)
        elif was_cancelled:
            self.cancelled.emit()
        else:
            self.failed.emit(error or "The export could not be completed.")

    def shutdown(self) -> None:
        self._closed = True
        self.cancel()
        self._pool.clear()
        self._pool.waitForDone()
        self._jobs.clear()


__all__ = ["LibraryExportController"]
