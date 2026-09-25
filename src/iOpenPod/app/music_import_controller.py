"""Background music inspection, applied only to the captured Library Workspace."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePosixPath
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.media.importing import ImportedSong, MusicImporter, relocate_song
from iOpenPod.app.media.music_paths import MusicPathAllocator

if TYPE_CHECKING:
    from device_registry import DeviceProfile
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.library_workspace import LibraryWorkspace
    from storage import HostPath

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Result:
    songs: tuple[ImportedSong, ...]


class _Signals(QObject):
    completed = Signal(int, object, str)
    progress = Signal(int, str)


class _Import(QRunnable):
    def __init__(
        self,
        token: int,
        paths: tuple[HostPath, ...],
        profile: DeviceProfile,
        importer: MusicImporter,
        occupied_paths: tuple[str, ...],
    ) -> None:
        super().__init__()
        self.token, self.paths, self.profile, self.importer = (
            token,
            paths,
            profile,
            importer,
        )
        self.cancelled = Event()
        self.signals = _Signals()
        self.occupied_paths = occupied_paths

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise PreparationCancelledError

        songs: list[ImportedSong] = []
        try:
            destinations = MusicPathAllocator(
                self.profile.capabilities.database.music_directory_count,
                self.occupied_paths,
            )
            for index, path in enumerate(self.paths, 1):
                checkpoint()
                self.signals.progress.emit(
                    self.token, f"{index}/{len(self.paths)} · {path.path.name}"
                )
                song = self.importer.inspect(path, self.profile, checkpoint=checkpoint)
                extension = PurePosixPath(
                    song.source.media.file.relative_path
                ).suffix.removeprefix(".")
                songs.append(
                    relocate_song(
                        song, destinations.allocate(extension, checkpoint=checkpoint)
                    )
                )
            checkpoint()
        except PreparationCancelledError:
            self.signals.completed.emit(self.token, None, "")
        except Exception as error:
            logger.exception("Music import inspection failed")
            self.signals.completed.emit(self.token, None, str(error))
        else:
            self.signals.completed.emit(self.token, _Result(tuple(songs)), "")


class MusicImportController(QObject):
    changed = Signal()
    progressChanged = Signal(str)
    finished = Signal(int)
    failed = Signal(str)

    def __init__(
        self,
        workspace: LibraryWorkspace,
        devices: DeviceController,
        parent: QObject | None = None,
        *,
        importer: MusicImporter | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace, self._devices = workspace, devices
        self._importer = importer or MusicImporter()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._token = 0
        self._closed = False
        self._jobs: dict[int, _Import] = {}
        self._revision = workspace.edit_revision
        self._source = devices.active_ipod
        self.busy = False
        workspace.changed.connect(self._invalidate)
        devices.activeIPodChanged.connect(self._invalidate)
        devices.busyChanged.connect(self._availability)

    @property
    def can_start(self) -> bool:
        return (
            not self._closed
            and not self.busy
            and not self._devices.busy
            and not self._workspace.locked
            and self._devices.active_ipod is not None
        )

    def start(self, paths: tuple[HostPath, ...]) -> None:
        active = self._devices.active_ipod
        if not paths or not self.can_start or active is None:
            return
        self._token += 1
        self._revision, self._source = self._workspace.edit_revision, active
        self.busy = True
        job = _Import(
            self._token,
            paths,
            active.profile,
            self._importer,
            tuple(
                track.metadata.location
                for track in (*active.library.tracks, *self._workspace.tracks)
            ),
        )
        self._jobs[self._token] = job
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        job.signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self.changed.emit()
        self._pool.start(job)

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
        self.changed.emit()

    def _availability(self, _busy: bool) -> None:
        self.changed.emit()

    @Slot(int, str)
    def _progress(self, token: int, message: str) -> None:
        if token == self._token and self.busy:
            self.progressChanged.emit(message)

    @Slot(int, object, str)
    def _completed(self, token: int, result: object, error: str) -> None:
        self._jobs.pop(token, None)
        if self._closed or token != self._token:
            return
        self._invalidate()
        if token != self._token:
            return
        self.busy = False
        if isinstance(result, _Result):
            try:
                self._workspace.add_songs(result.songs, self._revision)
            except ValueError as failure:
                self.failed.emit(str(failure))
            else:
                self.finished.emit(len(result.songs))
        elif error:
            self.failed.emit(error)
        self.changed.emit()

    def shutdown(self) -> None:
        self._closed = True
        self.cancel()
        self._pool.clear()
        self._pool.waitForDone()
        self._jobs.clear()
