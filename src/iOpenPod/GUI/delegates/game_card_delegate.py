# Hallmark · component: game card · theme: iOpenPod · genre: modern-minimal
# pre-emit critique: P5 H5 E4 S5 R5 V4
"""Landscape game artwork with the shared Library card captions and states."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QIcon, QPainter, QPainterPath
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QWidget

from iOpenPod.GUI.presentation.library_card import library_card_size, paint_library_card
from iOpenPod.GUI.presentation.selection_checkbox import (
    handle_library_card_check_event,
    paint_library_card_checkbox,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LAYOUT,
    LIGHT_TOKENS,
    resolve_typography,
)

TITLE_ROLE = Qt.ItemDataRole.UserRole + 1
VERSION_ROLE = Qt.ItemDataRole.UserRole + 2
_ART_HEIGHT = LAYOUT.album_artwork_size * 3 // 4


class GameCardDelegate(QStyledItemDelegate):
    def __init__(self, theme_manager: ThemeManager | None, parent: QWidget) -> None:
        super().__init__(parent)
        self._theme = theme_manager
        self._typography = resolve_typography()

    def sizeHint(
        self, option: QStyleOptionViewItem, _index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        typography = self._theme.typography if self._theme else self._typography
        return library_card_size(option.font, typography, artwork_height=_ART_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        tokens = (
            self._theme.tokens
            if self._theme
            else (
                DARK_TOKENS
                if option.palette.window().color().lightness() < 128
                else LIGHT_TOKENS
            )
        )
        typography = self._theme.typography if self._theme else self._typography
        icon = index.data(Qt.ItemDataRole.DecorationRole)

        def artwork(rect: QRectF) -> None:
            if not isinstance(icon, QIcon):
                return
            painter.save()
            path = QPainterPath()
            path.addRoundedRect(
                rect, float(LAYOUT.radius_control), float(LAYOUT.radius_control)
            )
            painter.setClipPath(path)
            icon.paint(painter, rect.toRect(), Qt.AlignmentFlag.AlignCenter)
            painter.restore()

        paint_library_card(
            painter,
            option,
            title=str(index.data(TITLE_ROLE) or ""),
            detail=str(index.data(VERSION_ROLE) or ""),
            tint=None,
            tokens=tokens,
            typography=typography,
            paint_artwork=artwork,
            artwork_height=_ART_HEIGHT,
        )
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        if state == Qt.CheckState.Checked or state == Qt.CheckState.Checked.value:
            paint_library_card_checkbox(
                painter,
                option,
                Qt.CheckState.Checked,
                tokens,
                typography,
                artwork_height=_ART_HEIGHT,
            )

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        # The complete game card toggles selection, including keyboard Space.
        return handle_library_card_check_event(
            event,
            model,
            option,
            index,
            self._theme.typography if self._theme else self._typography,
            checkbox_only=False,
            artwork_height=_ART_HEIGHT,
        )
