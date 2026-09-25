"""Bounded GUI presentation of lazily decoded artwork and derived colors."""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QPixmap, QPixmapCache

from iOpenPod.app.models.artwork import ArtworkImage
from iOpenPod.GUI.presentation.image_color import RGBColor, dominant_image_color
from iPodDB.library import ArtworkPixels

if TYPE_CHECKING:
    from iOpenPod.app.artwork_controller import ArtworkController

_CACHE_PREFIX = "iOpenPod/artwork/"
_DEFAULT_COLOR_CACHE_LIMIT = 512
_DEFAULT_COLOR_PENDING_LIMIT = 32

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ArtworkColorResult:
    artwork_id: int
    color: RGBColor


class _ArtworkColorSignals(QObject):
    succeeded = Signal(int, int, object)
    failed = Signal(int, int, object, object)
    finished = Signal(int, object)


class _ArtworkColorWork(QRunnable):
    def __init__(
        self,
        token: int,
        generation: int,
        image: ArtworkImage,
    ) -> None:
        super().__init__()
        self.token = token
        self.generation = generation
        self.image = image
        self.signals = _ArtworkColorSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            source = Image.frombytes(
                "RGB",
                (self.image.width, self.image.height),
                self.image.rgb888,
            )
            result = _ArtworkColorResult(
                artwork_id=self.image.artwork_id,
                color=dominant_image_color(source),
            )
        except Exception as error:
            self.signals.failed.emit(
                self.token,
                self.generation,
                self.image.artwork_id,
                error,
            )
        else:
            self.signals.succeeded.emit(self.token, self.generation, result)
        finally:
            self.signals.finished.emit(self.token, self.image.artwork_id)


class ArtworkPixmapProvider(QObject):
    """Bridge RGB pixels to bounded pixmap and asynchronously derived-color caches."""

    artworkChanged = Signal(object)
    cleared = Signal()

    def __init__(
        self,
        controller: ArtworkController,
        parent: QObject | None = None,
        *,
        color_cache_limit: int = _DEFAULT_COLOR_CACHE_LIMIT,
        max_color_pending: int = _DEFAULT_COLOR_PENDING_LIMIT,
    ) -> None:
        super().__init__(parent)
        if color_cache_limit <= 0:
            raise ValueError("Artwork color cache size must be positive")
        if max_color_pending <= 0:
            raise ValueError("Artwork pending-color limit must be positive")
        self._controller = controller
        self._qt_cache_keys: set[str] = set()
        self._color_cache_limit = color_cache_limit
        self._max_color_pending = max_color_pending
        self._dominant_colors: OrderedDict[int, RGBColor] = OrderedDict()
        self._requested_color_ids: OrderedDict[int, None] = OrderedDict()
        self._color_pending: dict[int, int] = {}
        self._color_work_items: dict[int, _ArtworkColorWork] = {}
        self._color_pool = QThreadPool(self)
        self._color_pool.setMaxThreadCount(1)
        self._generation = 0
        self._next_color_token = 0
        self._closed = False
        controller.artworkReady.connect(self._artwork_ready)
        controller.artworkUnavailable.connect(self._artwork_unavailable)
        controller.generationChanged.connect(self._generation_changed)

    def pixmap(
        self,
        artwork_id: int,
        logical_size: int,
        device_pixel_ratio: float,
    ) -> QPixmap | None:
        """Return a display pixmap now, queuing a decode on a cache miss."""

        if self._closed or artwork_id <= 0 or logical_size <= 0:
            return None
        target_px = max(1, ceil(logical_size * max(1.0, device_pixel_ratio)))
        image = self._controller.request(artwork_id, target_px)
        if image is None:
            return None
        return self._pixmap_for(image)

    def pixels(
        self,
        artwork_id: int,
        logical_size: int,
        device_pixel_ratio: float,
    ) -> ArtworkPixels | None:
        """Return exact decoded pixels now, queuing a decode on a cache miss."""

        if self._closed or artwork_id <= 0 or logical_size <= 0:
            return None
        target_px = max(1, ceil(logical_size * max(1.0, device_pixel_ratio)))
        image = self._controller.request(artwork_id, target_px)
        if image is None:
            return None
        return ArtworkPixels(image.width, image.height, image.rgb888)

    def dominant_color(
        self,
        artwork_id: int,
        logical_size: int,
        device_pixel_ratio: float,
    ) -> RGBColor | None:
        """Return or asynchronously request one reusable image-derived color."""

        retained = self._dominant_colors.pop(artwork_id, None)
        if retained is not None:
            self._dominant_colors[artwork_id] = retained
            return retained
        if self._closed or artwork_id <= 0 or logical_size <= 0:
            return None
        self._requested_color_ids[artwork_id] = None
        self._requested_color_ids.move_to_end(artwork_id)
        while len(self._requested_color_ids) > self._color_cache_limit:
            self._requested_color_ids.popitem(last=False)
        target_px = max(1, ceil(logical_size * max(1.0, device_pixel_ratio)))
        image = self._controller.request(artwork_id, target_px)
        if image is not None:
            self._schedule_color(image)
        return None

    def shutdown(self) -> None:
        """Stop derived-color work before the owning window is discarded."""

        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._cancel_queued_color_work()
        self._color_pool.waitForDone()
        self._color_work_items.clear()
        self._color_pending.clear()
        self._requested_color_ids.clear()
        self._dominant_colors.clear()

    @Slot(object)
    def _artwork_ready(self, value: object) -> None:
        if self._closed or not isinstance(value, ArtworkImage):
            return
        self._pixmap_for(value)
        if value.artwork_id in self._requested_color_ids:
            self._schedule_color(value)
        self.artworkChanged.emit(value.artwork_id)

    @Slot(object)
    def _artwork_unavailable(self, artwork_id: object) -> None:
        if not isinstance(artwork_id, int):
            return
        self._requested_color_ids.pop(artwork_id, None)
        self.artworkChanged.emit(artwork_id)

    @Slot(int)
    def _generation_changed(self, _generation: int) -> None:
        self._generation += 1
        self._cancel_queued_color_work()
        for cache_key in self._qt_cache_keys:
            QPixmapCache.remove(cache_key)
        self._qt_cache_keys.clear()
        self._dominant_colors.clear()
        self._requested_color_ids.clear()
        self._color_pending.clear()
        self.cleared.emit()

    def _schedule_color(self, image: ArtworkImage) -> None:
        if (
            self._closed
            or image.artwork_id in self._dominant_colors
            or image.artwork_id in self._color_pending
            or len(self._color_pending) >= self._max_color_pending
        ):
            return
        self._next_color_token += 1
        token = self._next_color_token
        item = _ArtworkColorWork(token, self._generation, image)
        item.signals.succeeded.connect(
            self._color_work_succeeded,
            Qt.ConnectionType.QueuedConnection,
        )
        item.signals.failed.connect(
            self._color_work_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        item.signals.finished.connect(
            self._color_work_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._color_pending[image.artwork_id] = token
        self._color_work_items[token] = item
        self._color_pool.start(item)

    @Slot(int, int, object)
    def _color_work_succeeded(
        self,
        token: int,
        generation: int,
        value: object,
    ) -> None:
        if (
            self._closed
            or generation != self._generation
            or not isinstance(value, _ArtworkColorResult)
            or self._color_pending.get(value.artwork_id) != token
        ):
            return
        self._dominant_colors[value.artwork_id] = value.color
        self._dominant_colors.move_to_end(value.artwork_id)
        while len(self._dominant_colors) > self._color_cache_limit:
            self._dominant_colors.popitem(last=False)
        self._requested_color_ids.pop(value.artwork_id, None)
        self.artworkChanged.emit(value.artwork_id)

    @Slot(int, int, object, object)
    def _color_work_failed(
        self,
        token: int,
        generation: int,
        artwork_id: object,
        error: object,
    ) -> None:
        if (
            self._closed
            or generation != self._generation
            or not isinstance(artwork_id, int)
            or self._color_pending.get(artwork_id) != token
        ):
            return
        self._requested_color_ids.pop(artwork_id, None)
        logger.warning(
            "Artwork color extraction for %s failed (%s): %s",
            artwork_id,
            type(error).__name__,
            error,
        )

    @Slot(int, object)
    def _color_work_finished(self, token: int, artwork_id: object) -> None:
        self._color_work_items.pop(token, None)
        if isinstance(artwork_id, int) and self._color_pending.get(artwork_id) == token:
            self._color_pending.pop(artwork_id, None)

    def _cancel_queued_color_work(self) -> None:
        for token, item in tuple(self._color_work_items.items()):
            if self._color_pool.tryTake(item):
                self._color_work_items.pop(token, None)
                if self._color_pending.get(item.image.artwork_id) == token:
                    self._color_pending.pop(item.image.artwork_id, None)

    def _pixmap_for(self, image: ArtworkImage) -> QPixmap:
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
        owned = wrapped.copy()
        pixmap = QPixmap.fromImage(owned)
        QPixmapCache.insert(cache_key, pixmap)
        self._qt_cache_keys.add(cache_key)
        return pixmap


__all__ = ["ArtworkPixmapProvider"]
