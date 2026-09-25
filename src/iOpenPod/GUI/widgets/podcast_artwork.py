"""Reusable cover-art surface for Podcast mastheads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.podcast_collection_artwork import (
    paint_podcast_collection_artwork,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

if TYPE_CHECKING:
    from iOpenPod.app.podcasts.models import PodcastSubscription
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
    from iOpenPod.GUI.presentation.podcast_artwork_provider import (
        PodcastArtworkPixmapProvider,
    )
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager


class PodcastArtworkView(QWidget):
    """Paint one real Podcast cover or its deterministic placeholder."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        provider: PodcastArtworkPixmapProvider,
        size: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._provider = provider
        self._size = size
        self._source_url = ""
        self._seed = 0
        self.setObjectName("podcastArtworkView")
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        provider.artworkChanged.connect(self._artwork_changed)

    def set_artwork(self, source_url: str, seed: int) -> None:
        if source_url == self._source_url and seed == self._seed:
            return
        self._source_url = source_url
        self._seed = seed
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        pixmap = self._provider.pixmap(
            self._source_url,
            round(rect.width()),
            self.devicePixelRatioF(),
        )
        if pixmap is None:
            paint_artwork_placeholder(
                painter,
                rect,
                self._seed,
                self._theme_manager.tokens,
                float(LAYOUT.radius_panel),
            )
        else:
            paint_artwork_pixmap(
                painter,
                rect,
                pixmap,
                self._theme_manager.tokens,
                float(LAYOUT.radius_panel),
            )

    def _artwork_changed(self, source_url: str) -> None:
        if source_url == self._source_url:
            self.update()


class PodcastCollectionArtworkView(QWidget):
    """Paint the All Podcasts identity as a four-cover collection grid."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        provider: PodcastArtworkPixmapProvider,
        size: int,
        parent: QWidget | None = None,
        *,
        device_artwork_provider: ArtworkPixmapProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._provider = provider
        self._device_artwork_provider = device_artwork_provider
        self._size = size
        self._subscriptions: tuple[PodcastSubscription, ...] = ()
        self.setObjectName("podcastCollectionArtworkView")
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        provider.artworkChanged.connect(self._artwork_changed)
        if device_artwork_provider is not None:
            device_artwork_provider.artworkChanged.connect(self._device_artwork_changed)

    def set_subscriptions(
        self,
        subscriptions: tuple[PodcastSubscription, ...],
    ) -> None:
        visible = subscriptions[:4]
        if visible == self._subscriptions:
            return
        self._subscriptions = visible
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_podcast_collection_artwork(
            painter,
            QRectF(self.rect()).adjusted(1, 1, -1, -1),
            self._subscriptions,
            self._provider,
            self._theme_manager.tokens,
            self.devicePixelRatioF(),
            self._device_artwork_provider,
        )

    def _artwork_changed(self, source_url: str) -> None:
        if any(item.artwork_url == source_url for item in self._subscriptions):
            self.update()

    def _device_artwork_changed(self, artwork_id: int) -> None:
        if any(item.artwork_id == artwork_id for item in self._subscriptions):
            self.update()


__all__ = ["PodcastArtworkView", "PodcastCollectionArtworkView"]
