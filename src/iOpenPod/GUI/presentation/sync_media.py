"""Sync membership colors and the persistent iPod marker for Library cards."""

from dataclasses import replace
from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyleOptionViewItem

from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.library_card import library_card_artwork_rect
from iOpenPod.GUI.presentation.theme.dynamic import contrasting_ink
from iOpenPod.GUI.presentation.theme.tokens import ThemeTokens, TypographyTokens


@lru_cache(maxsize=128)
def sync_checkbox_tokens(
    tokens: ThemeTokens, state: Qt.CheckState, on_ipod: bool
) -> ThemeTokens:
    """Keep blue mixed states; distinguish additions and removals by color."""

    if state is Qt.CheckState.Unchecked and on_ipod:
        return replace(
            tokens,
            surface=tokens.danger,
            surface_hover=tokens.danger,
            surface_pressed=tokens.danger,
        )
    if state is Qt.CheckState.Checked and not on_ipod:
        return replace(
            tokens,
            accent=tokens.success,
            accent_hover=tokens.success,
            accent_pressed=tokens.success,
            accent_ink=contrasting_ink(tokens.success, tokens),
        )
    return tokens


def library_card_ipod_rect(
    option: QStyleOptionViewItem, typography: TypographyTokens
) -> QRectF:
    artwork = library_card_artwork_rect(option, typography)
    return QRectF(artwork.left() + 8.0, artwork.top() + 8.0, 36.0, 36.0)


def paint_library_card_ipod_marker(
    painter: QPainter,
    option: QStyleOptionViewItem,
    tokens: ThemeTokens,
    typography: TypographyTokens,
) -> None:
    """Keep an iPod glyph readable over any artwork at the top left."""

    rect = library_card_ipod_rect(option, typography)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor(tokens.border_strong), 1.5))
    painter.setBrush(QColor(tokens.surface))
    painter.drawRoundedRect(rect, 8.0, 8.0)
    glyph_icon(
        "ipod", 24, QColor(tokens.text), option.widget.devicePixelRatioF()
    ).paint(painter, rect.adjusted(6.0, 6.0, -6.0, -6.0).toRect())
    painter.restore()
