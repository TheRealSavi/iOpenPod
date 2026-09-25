"""Shared painting and font-aware geometry for virtualized Library cards."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from iOpenPod.GUI.presentation.theme.dynamic import colorful_card_fill
from iOpenPod.GUI.presentation.theme.tokens import (
    LAYOUT,
    ThemeTokens,
    TypographyTokens,
)

if TYPE_CHECKING:
    from iOpenPod.GUI.presentation.image_color import RGBColor

type ArtworkPainter = Callable[[QRectF], None]


def library_card_size(font: QFont, typography: TypographyTokens) -> QSize:
    """Return the shared card size without clipping Host-relative typography."""

    title_font, detail_font = _caption_fonts(font, typography)
    caption_height = (
        QFontMetrics(title_font).height() + QFontMetrics(detail_font).height()
    )
    required_height = (
        LAYOUT.album_card_padding
        + LAYOUT.album_artwork_size
        + LAYOUT.album_caption_gap
        + caption_height
        + LAYOUT.album_card_padding
    )
    return QSize(
        LAYOUT.album_card_width,
        max(LAYOUT.album_card_minimum_height, required_height),
    )


def library_card_artwork_rect(
    option: QStyleOptionViewItem,
    typography: TypographyTokens,
) -> QRectF:
    """Return the shared artwork area for overlays and caller-owned painting."""

    card_rect = library_card_rect(option, typography)
    return QRectF(
        card_rect.left() + LAYOUT.album_card_padding,
        card_rect.top() + LAYOUT.album_card_padding,
        LAYOUT.album_artwork_size,
        LAYOUT.album_artwork_size,
    )


def paint_library_card(
    painter: QPainter,
    option: QStyleOptionViewItem,
    *,
    title: str,
    detail: str,
    tint: RGBColor | None,
    tokens: ThemeTokens,
    typography: TypographyTokens,
    paint_artwork: ArtworkPainter,
) -> None:
    """Paint shared card chrome and captions around caller-provided artwork."""

    card_rect = library_card_rect(option, typography)
    artwork_rect = library_card_artwork_rect(option, typography)
    selected = bool(option.state & QStyle.StateFlag.State_Selected)
    hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
    focused = bool(option.state & QStyle.StateFlag.State_HasFocus)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _paint_chrome(painter, card_rect, tokens, tint, selected, hovered)
    paint_artwork(artwork_rect)
    _paint_caption(
        painter,
        artwork_rect,
        title,
        detail,
        option.font,
        typography,
        tokens,
    )
    if selected:
        _paint_selection(painter, card_rect, tokens)
    if focused:
        _paint_focus(painter, card_rect, tokens)
    painter.restore()


def library_card_rect(
    option: QStyleOptionViewItem,
    typography: TypographyTokens,
) -> QRectF:
    """Return the rendered card bounds within an equalized grid cell."""

    card_size = library_card_size(option.font, typography)
    cell_rect = QRectF(option.rect)
    card_width = min(float(card_size.width()), cell_rect.width())
    card_height = min(float(card_size.height()), cell_rect.height())
    return QRectF(
        cell_rect.left() + ((cell_rect.width() - card_width) / 2.0),
        cell_rect.top() + ((cell_rect.height() - card_height) / 2.0),
        card_width,
        card_height,
    )


def _paint_chrome(
    painter: QPainter,
    card_rect: QRectF,
    tokens: ThemeTokens,
    tint: RGBColor | None,
    selected: bool,
    hovered: bool,
) -> None:
    if tint is not None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            colorful_card_fill(tint, tokens, emphasized=selected or hovered)
        )
        painter.drawRoundedRect(
            card_rect,
            float(LAYOUT.radius_panel),
            float(LAYOUT.radius_panel),
        )
    elif selected or hovered:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(tokens.surface_selected if selected else tokens.surface_hover)
        )
        painter.drawRoundedRect(
            card_rect,
            float(LAYOUT.radius_panel),
            float(LAYOUT.radius_panel),
        )


def _paint_caption(
    painter: QPainter,
    artwork_rect: QRectF,
    title: str,
    detail: str,
    base_font: QFont,
    typography: TypographyTokens,
    tokens: ThemeTokens,
) -> None:
    title_font, detail_font = _caption_fonts(base_font, typography)
    title_metrics = QFontMetrics(title_font)
    detail_metrics = QFontMetrics(detail_font)
    title_top = artwork_rect.bottom() + LAYOUT.album_caption_gap
    text_width = artwork_rect.width()

    painter.setFont(title_font)
    painter.setPen(QColor(tokens.text))
    painter.drawText(
        QRectF(
            artwork_rect.left(),
            title_top,
            text_width,
            title_metrics.height(),
        ),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        title_metrics.elidedText(
            title,
            Qt.TextElideMode.ElideRight,
            round(text_width),
        ),
    )

    painter.setFont(detail_font)
    painter.setPen(QColor(tokens.text_secondary))
    painter.drawText(
        QRectF(
            artwork_rect.left(),
            title_top + title_metrics.height(),
            text_width,
            detail_metrics.height(),
        ),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        detail_metrics.elidedText(
            detail,
            Qt.TextElideMode.ElideRight,
            round(text_width),
        ),
    )


def _paint_selection(
    painter: QPainter,
    card_rect: QRectF,
    tokens: ThemeTokens,
) -> None:
    # Selection belongs to every selected card, independently of hover, artwork
    # color, and which item currently owns keyboard focus.
    width = 3.0
    inset = width / 2.0
    painter.setPen(QPen(QColor(tokens.accent), width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(
        card_rect.adjusted(inset, inset, -inset, -inset),
        max(0.0, float(LAYOUT.radius_panel) - inset),
        max(0.0, float(LAYOUT.radius_panel) - inset),
    )


def _paint_focus(
    painter: QPainter,
    card_rect: QRectF,
    tokens: ThemeTokens,
) -> None:
    focus_pen = QPen(QColor(tokens.focus))
    focus_pen.setWidthF(1.0)
    focus_pen.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(focus_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # Fit a separate keyboard cue between the selection outline and the artwork.
    inset = 4.5
    painter.drawRoundedRect(
        card_rect.adjusted(inset, inset, -inset, -inset),
        max(0.0, float(LAYOUT.radius_panel) - inset),
        max(0.0, float(LAYOUT.radius_panel) - inset),
    )


def _caption_fonts(
    base_font: QFont,
    typography: TypographyTokens,
) -> tuple[QFont, QFont]:
    title_font = QFont(base_font)
    title_font.setPointSizeF(typography.album_card_title_pt)
    title_font.setWeight(QFont.Weight.DemiBold)
    detail_font = QFont(base_font)
    detail_font.setPointSizeF(typography.album_card_detail_pt)
    detail_font.setWeight(QFont.Weight.Medium)
    return title_font, detail_font


__all__ = [
    "library_card_artwork_rect",
    "library_card_rect",
    "library_card_size",
    "paint_library_card",
]
