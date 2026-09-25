"""Shared four-cover artwork treatment for the All Podcasts projection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPen

from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from iOpenPod.app.podcasts.models import PodcastSubscription
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
    from iOpenPod.GUI.presentation.podcast_artwork_provider import (
        PodcastArtworkPixmapProvider,
    )
    from iOpenPod.GUI.presentation.theme.tokens import ThemeTokens


def paint_podcast_collection_artwork(
    painter: QPainter,
    rect: QRectF,
    subscriptions: Sequence[PodcastSubscription],
    provider: PodcastArtworkPixmapProvider,
    tokens: ThemeTokens,
    device_pixel_ratio: float,
    device_provider: ArtworkPixmapProvider | None = None,
) -> None:
    """Paint the first four Podcast covers as a fixed 2-by-2 collection grid."""

    gap = float(LAYOUT.space_2xs)
    tile_size = (min(rect.width(), rect.height()) - gap) / 2.0
    tile_radius = float(LAYOUT.space_2xs)
    for position in range(4):
        column = position % 2
        row = position // 2
        tile_rect = QRectF(
            rect.left() + column * (tile_size + gap),
            rect.top() + row * (tile_size + gap),
            tile_size,
            tile_size,
        )
        if position >= len(subscriptions):
            painter.setPen(QPen(QColor(tokens.border)))
            painter.setBrush(QColor(tokens.surface_alt))
            painter.drawRoundedRect(tile_rect, tile_radius, tile_radius)
            continue

        subscription = subscriptions[position]
        pixmap = provider.pixmap(
            subscription.artwork_url,
            round(tile_size),
            device_pixel_ratio,
        )
        if (
            pixmap is None
            and device_provider is not None
            and subscription.artwork_id > 0
        ):
            pixmap = device_provider.pixmap(
                subscription.artwork_id,
                round(tile_size),
                device_pixel_ratio,
            )
        if pixmap is None:
            paint_artwork_placeholder(
                painter,
                tile_rect,
                stable_artwork_seed(subscription.subscription_id),
                tokens,
                tile_radius,
            )
        else:
            paint_artwork_pixmap(
                painter,
                tile_rect,
                pixmap,
                tokens,
                tile_radius,
            )


__all__ = ["paint_podcast_collection_artwork"]
