"""Shared painting for single covers, collection collages, and placeholders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, ThemeTokens

if TYPE_CHECKING:
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider


def paint_artwork_collage(
    painter: QPainter,
    rect: QRectF,
    artwork_ids: tuple[int, int, int, int],
    seed: int,
    tokens: ThemeTokens,
    provider: ArtworkPixmapProvider,
    device_pixel_ratio: float,
) -> None:
    """Paint the same ordered, lazy four-tile cover in cards and detail views."""

    gap = float(LAYOUT.space_2xs)
    tile_size = (min(rect.width(), rect.height()) - gap) / 2.0
    for position, artwork_id in enumerate(artwork_ids):
        column = position % 2
        row = position // 2
        tile_rect = QRectF(
            rect.left() + column * (tile_size + gap),
            rect.top() + row * (tile_size + gap),
            tile_size,
            tile_size,
        )
        if artwork_id <= 0:
            painter.setPen(QPen(QColor(tokens.border)))
            painter.setBrush(QColor(tokens.surface_alt))
            painter.drawRoundedRect(tile_rect, 2.0, 2.0)
            continue
        pixmap = provider.pixmap(artwork_id, round(tile_size), device_pixel_ratio)
        if pixmap is None:
            paint_artwork_placeholder(painter, tile_rect, seed + position, tokens, 2.0)
        else:
            paint_artwork_pixmap(painter, tile_rect, pixmap, tokens, 2.0)


def paint_artwork_placeholder(
    painter: QPainter,
    rect: QRectF,
    seed: int,
    tokens: ThemeTokens,
    radius: float,
) -> None:
    """Paint deterministic, allocation-free placeholder cover artwork."""

    palette = (
        tokens.artwork_blue,
        tokens.artwork_green,
        tokens.artwork_gold,
        tokens.artwork_coral,
        tokens.artwork_violet,
        tokens.artwork_slate,
    )
    first = QColor(palette[seed % len(palette)])
    second = QColor(palette[(seed // 7 + 2) % len(palette)])
    ink = QColor(tokens.artwork_ink)

    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(clip)
    painter.fillRect(rect, first)

    unit = max(4.0, min(rect.width(), rect.height()) / 8.0)
    offset = float(seed % 5) * unit * 0.35
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(second))
    painter.drawEllipse(
        QPointF(rect.right() - unit * 1.6, rect.top() + unit * 1.8),
        unit * 2.5,
        unit * 2.5,
    )

    pen = QPen(ink)
    pen.setWidthF(max(1.5, unit * 0.22))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for index in range(-2, 8):
        y = rect.top() + (index * unit) + offset
        painter.drawLine(
            QPointF(rect.left() - unit, y),
            QPointF(rect.right() + unit, y + unit * 3.2),
        )
    painter.restore()

    border = QPen(QColor(tokens.border))
    border.setWidthF(1.0)
    painter.setPen(border)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)


def paint_artwork_pixmap(
    painter: QPainter,
    rect: QRectF,
    pixmap: QPixmap,
    tokens: ThemeTokens,
    radius: float,
) -> None:
    """Paint one real cover with the same clipping and border as placeholders."""

    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(clip)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
    painter.restore()

    border = QPen(QColor(tokens.border))
    border.setWidthF(1.0)
    painter.setPen(border)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
