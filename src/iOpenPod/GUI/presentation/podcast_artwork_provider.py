"""DPR-aware GUI pixmaps for asynchronously fetched Podcast artwork."""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

from iOpenPod.app.podcasts.models import PodcastArtworkImage
from iOpenPod.GUI.presentation.pixmap_cache import PixmapCache

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
        self._pixmaps = PixmapCache(_CACHE_PREFIX)
        self._closed = False
        controller.artworkReady.connect(self._artwork_ready)
        controller.artworkUnavailable.connect(self.artworkChanged)
        controller.feedArtworkChanged.connect(self.artworkChanged)

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
        self._controller.feedArtworkChanged.disconnect(self.artworkChanged)
        self._pixmaps.clear()

    def feed_pixmap(
        self, feed_url: str, logical_size: int, device_pixel_ratio: float
    ) -> QPixmap | None:
        """Use publisher-feed artwork for a visible directory result."""
        if self._closed or not feed_url.strip() or logical_size <= 0:
            return None
        target_px = max(1, ceil(logical_size * max(1.0, device_pixel_ratio)))
        image = self._controller.request_feed(feed_url, target_px)
        return self._pixmap_for(image) if image is not None else None

    @Slot(object)
    def _artwork_ready(self, value: object) -> None:
        if self._closed or not isinstance(value, PodcastArtworkImage):
            return
        self._pixmap_for(value)
        self.artworkChanged.emit(value.source_url)

    def _pixmap_for(self, image: PodcastArtworkImage) -> QPixmap:
        cached = self._pixmaps.get(image.cache_key)
        if cached is not None:
            return cached
        wrapped = QImage(
            image.rgb888,
            image.width,
            image.height,
            image.width * 3,
            QImage.Format.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(wrapped.copy())
        self._pixmaps.insert(image.cache_key, pixmap)
        return pixmap


__all__ = ["PodcastArtworkPixmapProvider"]
