"""High-DPI drag previews for Track selections."""

from math import ceil

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap

from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, ThemeTokens
from iPodDB.library import Track

_SINGLE_PREVIEW_WIDTH = 328
_SINGLE_PREVIEW_HEIGHT = 72
_COUNT_PREVIEW_MINIMUM_WIDTH = 112
_COUNT_PREVIEW_HEIGHT = 44
_CARD_INSET = 3


def render_single_track_drag_preview(
    track: Track,
    *,
    title: str,
    artist: str,
    album: str,
    base_font: QFont,
    tokens: ThemeTokens,
    artwork_provider: ArtworkPixmapProvider,
    device_pixel_ratio: float,
) -> QPixmap:
    """Render one queue-inspired Track card for ``QDrag.setPixmap``."""

    pixmap = _transparent_pixmap(
        _SINGLE_PREVIEW_WIDTH,
        _SINGLE_PREVIEW_HEIGHT,
        device_pixel_ratio,
    )
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    card = _paint_card(painter, pixmap, tokens)

    artwork_size = LAYOUT.playback_row_artwork_size
    artwork = QRectF(
        card.left() + LAYOUT.space_xs,
        card.center().y() - artwork_size / 2.0,
        artwork_size,
        artwork_size,
    )
    cover = artwork_provider.pixmap(
        track.artwork_id,
        artwork_size,
        pixmap.devicePixelRatio(),
    )
    if cover is None:
        paint_artwork_placeholder(
            painter,
            artwork,
            stable_artwork_seed(track.album_key),
            tokens,
            float(LAYOUT.radius_control),
        )
    else:
        paint_artwork_pixmap(
            painter,
            artwork,
            cover,
            tokens,
            float(LAYOUT.radius_control),
        )

    content = QRectF(
        artwork.right() + LAYOUT.space_sm,
        card.top() + LAYOUT.space_2xs,
        card.right() - artwork.right() - LAYOUT.space_md,
        card.height() - (2 * LAYOUT.space_2xs),
    )
    _paint_metadata(
        painter,
        content,
        title=title,
        artist=artist,
        album=album,
        base_font=base_font,
        tokens=tokens,
    )
    painter.end()
    return pixmap


def render_count_drag_preview(
    text: str,
    *,
    base_font: QFont,
    tokens: ThemeTokens,
    device_pixel_ratio: float,
) -> QPixmap:
    """Render a compact count card for a dragged Library selection."""

    label_font = QFont(base_font)
    label_font.setWeight(QFont.Weight.DemiBold)
    width = max(
        _COUNT_PREVIEW_MINIMUM_WIDTH,
        QFontMetrics(label_font).horizontalAdvance(text) + (2 * LAYOUT.space_md),
    )
    pixmap = _transparent_pixmap(width, _COUNT_PREVIEW_HEIGHT, device_pixel_ratio)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    card = _paint_card(painter, pixmap, tokens)
    painter.setFont(label_font)
    painter.setPen(QColor(tokens.text))
    painter.drawText(card, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


def render_track_count_drag_preview(
    text: str,
    *,
    base_font: QFont,
    tokens: ThemeTokens,
    device_pixel_ratio: float,
) -> QPixmap:
    """Render the count card through the existing Track-specific interface."""

    return render_count_drag_preview(
        text,
        base_font=base_font,
        tokens=tokens,
        device_pixel_ratio=device_pixel_ratio,
    )


def drag_preview_hot_spot(pixmap: QPixmap) -> QPoint:
    """Anchor the preview just below and to the right of the pointer."""

    logical_height = round(pixmap.height() / pixmap.devicePixelRatio())
    return QPoint(LAYOUT.space_sm, min(LAYOUT.space_sm, logical_height // 2))


def _transparent_pixmap(width: int, height: int, device_pixel_ratio: float) -> QPixmap:
    ratio = max(1.0, device_pixel_ratio)
    pixmap = QPixmap(ceil(width * ratio), ceil(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _paint_card(
    painter: QPainter,
    pixmap: QPixmap,
    tokens: ThemeTokens,
) -> QRectF:
    width = pixmap.width() / pixmap.devicePixelRatio()
    height = pixmap.height() / pixmap.devicePixelRatio()
    card = QRectF(
        _CARD_INSET,
        _CARD_INSET,
        width - (2 * _CARD_INSET),
        height - (2 * _CARD_INSET) - LAYOUT.space_3xs,
    )
    shadow = card.translated(0, LAYOUT.space_3xs)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 58))
    painter.drawRoundedRect(
        shadow,
        float(LAYOUT.radius_panel),
        float(LAYOUT.radius_panel),
    )
    painter.setBrush(QColor(tokens.surface))
    painter.setPen(QPen(QColor(tokens.border_strong), 1))
    painter.drawRoundedRect(
        card,
        float(LAYOUT.radius_panel),
        float(LAYOUT.radius_panel),
    )
    return card


def _paint_metadata(
    painter: QPainter,
    rect: QRectF,
    *,
    title: str,
    artist: str,
    album: str,
    base_font: QFont,
    tokens: ThemeTokens,
) -> None:
    title_font = QFont(base_font)
    title_font.setWeight(QFont.Weight.DemiBold)
    detail_font = QFont(base_font)
    detail_font.setPointSizeF(max(1.0, detail_font.pointSizeF() - 1.0))
    title_metrics = QFontMetrics(title_font)
    detail_metrics = QFontMetrics(detail_font)
    line_heights = (
        title_metrics.height(),
        detail_metrics.height(),
        detail_metrics.height(),
    )
    top = rect.center().y() - sum(line_heights) / 2.0
    lines = (
        (title, title_font, title_metrics, QColor(tokens.text)),
        (artist, detail_font, detail_metrics, QColor(tokens.text_secondary)),
        (album, detail_font, detail_metrics, QColor(tokens.text_secondary)),
    )
    for (text, font, metrics, color), line_height in zip(
        lines, line_heights, strict=True
    ):
        painter.setFont(font)
        painter.setPen(color)
        line = QRectF(rect.left(), top, rect.width(), line_height)
        painter.drawText(
            line,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(text, Qt.TextElideMode.ElideRight, round(rect.width())),
        )
        top += line_height


__all__ = [
    "drag_preview_hot_spot",
    "render_count_drag_preview",
    "render_single_track_drag_preview",
    "render_track_count_drag_preview",
]
