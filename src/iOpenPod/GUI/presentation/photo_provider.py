"""GUI-thread conversion of lazily decoded Photo images into display pixmaps."""

from __future__ import annotations

from enum import StrEnum
from math import ceil
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage, QPixmap, QPixmapCache

from iOpenPod.app.models.photos import PhotoImage
from iOpenPod.app.photo_controller import PhotoLoadFailure, PhotoUnavailable

if TYPE_CHECKING:
    from iOpenPod.app.photo_controller import PhotoController

_CACHE_PREFIX = "iOpenPod/photo/"


class PhotoPixmapState(StrEnum):
    """Presentation state for one automatic or exact Photo representation."""

    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class PhotoPixmapProvider(QObject):
    """Bridge owned Photo RGB pixels to Qt's bounded display-pixmap cache."""

    photoChanged = Signal(object)
    cleared = Signal()
    capacityAvailable = Signal()

    def __init__(
        self,
        controller: PhotoController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._qt_cache_keys: set[str] = set()
        self._states: dict[tuple[int, int | None], PhotoPixmapState] = {}
        self._closed = False
        controller.photoReady.connect(self._photo_ready)
        controller.photoUnavailable.connect(self._photo_unavailable)
        controller.photoFailed.connect(self._photo_failed)
        controller.generationChanged.connect(self._generation_changed)
        controller.capacityAvailable.connect(self._capacity_available)

    def pixmap(
        self,
        photo_id: int,
        logical_size: int,
        device_pixel_ratio: float,
        *,
        format_id: int | None = None,
    ) -> QPixmap | None:
        """Return a pixmap now, queuing automatic or exact-format decode on miss."""

        if (
            self._closed
            or photo_id <= 0
            or logical_size <= 0
            or (format_id is not None and format_id < 0)
        ):
            return None
        target_px = max(1, ceil(logical_size * max(1.0, device_pixel_ratio)))
        image = self._controller.request(
            photo_id,
            target_px,
            format_id=format_id,
        )
        if image is None:
            key = (photo_id, format_id)
            if self._states.get(key) not in (
                PhotoPixmapState.UNAVAILABLE,
                PhotoPixmapState.FAILED,
            ):
                self._states[key] = PhotoPixmapState.LOADING
            return None
        self._states[(photo_id, format_id)] = PhotoPixmapState.READY
        return self._pixmap_for(image)

    def state(
        self,
        photo_id: int,
        *,
        format_id: int | None = None,
    ) -> PhotoPixmapState:
        """Return the last observed presentation state without starting I/O."""

        return self._states.get((photo_id, format_id), PhotoPixmapState.IDLE)

    def retry(self, photo_id: int, *, format_id: int | None = None) -> None:
        """Clear one terminal state so the next paint retries the request."""

        if self._closed or photo_id <= 0 or (format_id is not None and format_id < 0):
            return
        self._controller.retry(photo_id, format_id=format_id)
        self._states.pop((photo_id, format_id), None)
        self.photoChanged.emit(photo_id)

    def shutdown(self) -> None:
        """Release presentation cache entries before the owning window closes."""

        if self._closed:
            return
        self._closed = True
        self._clear_pixmaps()
        self._states.clear()

    @Slot(object)
    def _photo_ready(self, value: object) -> None:
        if self._closed or not isinstance(value, PhotoImage):
            return
        self._pixmap_for(value)
        for key in tuple(self._states):
            if key[0] == value.photo_id and (
                key[1] is None or key[1] == value.format_id
            ):
                self._states[key] = PhotoPixmapState.READY
        self.photoChanged.emit(value.photo_id)

    @Slot(object)
    def _photo_unavailable(self, value: object) -> None:
        if self._closed or not isinstance(value, PhotoUnavailable):
            return
        self._states[(value.photo_id, value.format_id)] = PhotoPixmapState.UNAVAILABLE
        self.photoChanged.emit(value.photo_id)

    @Slot(object)
    def _photo_failed(self, value: object) -> None:
        if self._closed or not isinstance(value, PhotoLoadFailure):
            return
        self._states[(value.photo_id, value.format_id)] = PhotoPixmapState.FAILED
        self.photoChanged.emit(value.photo_id)

    @Slot(int)
    def _generation_changed(self, _generation: int) -> None:
        if self._closed:
            return
        self._clear_pixmaps()
        self._states.clear()
        self.cleared.emit()

    @Slot()
    def _capacity_available(self) -> None:
        if not self._closed:
            self.capacityAvailable.emit()

    def _clear_pixmaps(self) -> None:
        for cache_key in self._qt_cache_keys:
            QPixmapCache.remove(cache_key)
        self._qt_cache_keys.clear()

    def _pixmap_for(self, image: PhotoImage) -> QPixmap:
        cache_key = f"{_CACHE_PREFIX}{image.cache_key}"
        cached = QPixmap()
        if QPixmapCache.find(cache_key, cached) and not cached.isNull():
            return cached

        wrapped = QImage(
            image.rgb888,
            image.width,
            image.height,
            image.width * 3,
            QImage.Format.Format_RGB888,
        )
        # QImage's raw-buffer constructor borrows Python memory. Detach from that
        # buffer before crossing into Qt's independently retained pixmap cache.
        owned = wrapped.copy()
        pixmap = QPixmap.fromImage(owned)
        QPixmapCache.insert(cache_key, pixmap)
        self._qt_cache_keys.add(cache_key)
        return pixmap


__all__ = ["PhotoPixmapProvider", "PhotoPixmapState"]
