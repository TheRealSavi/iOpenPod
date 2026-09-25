"""Background-safe import of one explicitly selected Host artwork file."""

from __future__ import annotations

import logging
from threading import Event
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iPodDB.library import ArtworkPixels
from storage import HostPath, StorageError, capture_host_file
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_MAX_ENCODED_BYTES = 32 * 1024 * 1024
_MAX_DIMENSION = 8192
_MAX_PIXEL_AREA = 32 * 1024 * 1024


class ArtworkImportError(ValueError):
    """The selected Host file cannot become a bounded artwork image."""


def import_artwork(
    source: HostPath,
    *,
    checkpoint: Callable[[], None],
) -> ArtworkPixels:
    """Capture and decode one stable Host image into owned RGB888 pixels."""

    try:
        with capture_host_file(
            source,
            checkpoint=checkpoint,
            max_bytes=_MAX_ENCODED_BYTES,
        ) as captured:
            checkpoint()
            with (
                LocalHostFile.observe(captured.snapshot).open_read(
                    checkpoint=checkpoint
                ) as stream,
                Image.open(stream) as opened,
            ):
                _validate_dimensions(*opened.size)
                checkpoint()
                oriented = ImageOps.exif_transpose(opened)
                _validate_dimensions(*oriented.size)
                checkpoint()
                rgb = oriented.convert("RGB")
                pixels = ArtworkPixels(rgb.width, rgb.height, rgb.tobytes())
                checkpoint()
                return pixels
    except UnidentifiedImageError as error:
        raise ArtworkImportError(
            "The selected file is not a supported image."
        ) from error
    except Image.DecompressionBombError as error:
        raise ArtworkImportError(
            "The selected image exceeds safe pixel limits."
        ) from error
    except InterruptedError:
        raise
    except OSError as error:
        raise ArtworkImportError(
            f"The artwork image could not be decoded: {error}"
        ) from error


def _validate_dimensions(width: int, height: int) -> None:
    if (
        width <= 0
        or height <= 0
        or width > _MAX_DIMENSION
        or height > _MAX_DIMENSION
        or width * height > _MAX_PIXEL_AREA
    ):
        raise ArtworkImportError(
            "Artwork must be at most 8192 pixels per side and 32 megapixels."
        )


class _Signals(QObject):
    completed = Signal(int, object, str, str)


class _ImportWork(QRunnable):
    def __init__(self, token: int, source: HostPath) -> None:
        super().__init__()
        self.token = token
        self.source = source
        self.cancelled = Event()
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise InterruptedError

        try:
            result = import_artwork(self.source, checkpoint=checkpoint)
        except InterruptedError:
            self.signals.completed.emit(self.token, None, "", "")
        except (ArtworkImportError, StorageError) as error:
            self.signals.completed.emit(self.token, None, "", str(error))
        except Exception as error:
            logger.exception("Artwork import failed")
            self.signals.completed.emit(self.token, None, "", str(error))
        else:
            self.signals.completed.emit(
                self.token,
                result,
                self.source.path.name,
                "",
            )


class ArtworkImportController(QObject):
    """Capture and decode one selected Host image without blocking the GUI."""

    busyChanged = Signal(bool)
    finished = Signal(object, str)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._jobs: dict[int, _ImportWork] = {}
        self._token = 0
        self._closed = False
        self.busy = False

    def start(self, source: HostPath) -> None:
        if self._closed:
            return
        self.cancel()
        self._token += 1
        job = _ImportWork(self._token, source)
        job.signals.completed.connect(
            self._completed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._jobs[self._token] = job
        self.busy = True
        self.busyChanged.emit(True)
        self._pool.start(job)

    def cancel(self) -> None:
        self._token += 1
        for job in self._jobs.values():
            job.cancelled.set()
        if self.busy:
            self.busy = False
            self.busyChanged.emit(False)

    @Slot(int, object, str, str)
    def _completed(
        self,
        token: int,
        result: object,
        source_name: str,
        error: str,
    ) -> None:
        self._jobs.pop(token, None)
        if self._closed or token != self._token:
            return
        self.busy = False
        self.busyChanged.emit(False)
        if isinstance(result, ArtworkPixels):
            self.finished.emit(result, source_name)
        elif error:
            self.failed.emit(error)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.cancel()
        self._pool.clear()
        self._pool.waitForDone()
        self._jobs.clear()


__all__ = [
    "ArtworkImportController",
    "ArtworkImportError",
    "import_artwork",
]
