"""DPR-aware GUI pixmaps for asynchronously fetched Podcast artwork."""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage, QPixmap, QPixmapCache

from iOpenPod.app.podcasts.models import PodcastArtworkImage

if TYPE_CHECKING:
    from iOpenPod.app.podcasts.artwork_controller import PodcastArtworkController

_CACHE_PREFIX = "iOpenPod/podcast-artwork/"


class PodcastArtworkPixmapProvider(QObject):
    """Bridge remote Podcast RGB pixels to the GUI-owned pixmap cache."""

    artworkChanged = Signal(str)

    def __init__(
        self,
        controller: PodcastArtworkController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._qt_cache_keys: set[str] = set()
        self._closed = False
        controller.artworkReady.connect(self._artwork_ready)
        controller.artworkUnavailable.connect(self.artworkChanged)

    def pixmap(
        self,
        source_url: str,
        logical_size: int,
        device_pixel_ratio: float,
    ) -> QPixmap | None:
        if self._closed or not source_url.strip() or logical_size <= 0:
            return None
        target_px = max(1, ceil(logical_size * max(1.0, device_pixel_ratio)))
        image = self._controller.request(source_url, target_px)
        return self._pixmap_for(image) if image is not None else None

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._controller.artworkReady.disconnect(self._artwork_ready)
        self._controller.artworkUnavailable.disconnect(self.artworkChanged)
        for cache_key in self._qt_cache_keys:
            QPixmapCache.remove(cache_key)
        self._qt_cache_keys.clear()

    @Slot(object)
    def _artwork_ready(self, value: object) -> None:
        if self._closed or not isinstance(value, PodcastArtworkImage):
            return
        self._pixmap_for(value)
        self.artworkChanged.emit(value.source_url)

    def _pixmap_for(self, image: PodcastArtworkImage) -> QPixmap:
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
        pixmap = QPixmap.fromImage(wrapped.copy())
        QPixmapCache.insert(cache_key, pixmap)
        self._qt_cache_keys.add(cache_key)
        return pixmap


__all__ = ["PodcastArtworkPixmapProvider"]
