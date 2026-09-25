# Hallmark · component: Library selection checkbox · genre: modern-minimal
# theme: iOpenPod · states: unchecked · checked · mixed · hover · focus · disabled
# contrast: pass · pre-emit critique: P5 H5 E5 S5 R5 V4
"""Shared circular selection control for virtualized Library cards."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QLineF,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from iOpenPod.GUI.presentation.library_card import (
    library_card_artwork_rect,
    library_card_rect,
)
from iOpenPod.GUI.presentation.theme.tokens import ThemeTokens, TypographyTokens

_CHECKBOX_EXTENT = 36.0
_CHECKBOX_MARGIN = 8.0
_CHECKBOX_BORDER_WIDTH = 2.0


def library_card_checkbox_rect(
    option: QStyleOptionViewItem,
    typography: TypographyTokens,
) -> QRectF:
    artwork = library_card_artwork_rect(option, typography)
    return QRectF(
        artwork.right() - _CHECKBOX_MARGIN - _CHECKBOX_EXTENT,
        artwork.top() + _CHECKBOX_MARGIN,
        _CHECKBOX_EXTENT,
        _CHECKBOX_EXTENT,
    )


def paint_library_card_checkbox(
    painter: QPainter,
    option: QStyleOptionViewItem,
    state: Qt.CheckState,
    tokens: ThemeTokens,
    typography: TypographyTokens,
) -> None:
    checked = state is Qt.CheckState.Checked
    partial = state is Qt.CheckState.PartiallyChecked
    active = checked or partial
    enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
    hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
    focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
    rect = library_card_checkbox_rect(option, typography)
    fill = (
        tokens.accent_hover
        if active and hovered
        else tokens.accent
        if active
        else tokens.surface_hover
        if hovered
        else tokens.surface
    )
    if not enabled:
        fill = tokens.surface_alt
    border = tokens.text_disabled if not enabled else tokens.border_strong
    mark = tokens.text_disabled if not enabled else tokens.accent_ink

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if focused:
        painter.setPen(QPen(QColor(tokens.focus), _CHECKBOX_BORDER_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect.adjusted(-3.0, -3.0, 3.0, 3.0))
    painter.setPen(QPen(QColor(border), _CHECKBOX_BORDER_WIDTH))
    painter.setBrush(QColor(fill))
    painter.drawEllipse(rect)
    if checked:
        path = QPainterPath()
        path.moveTo(rect.left() + 9.0, rect.center().y())
        path.lineTo(rect.left() + 15.0, rect.bottom() - 10.0)
        path.lineTo(rect.right() - 8.0, rect.top() + 10.0)
        pen = QPen(QColor(mark), 3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    elif partial:
        pen = QPen(QColor(mark), 3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            QLineF(
                rect.left() + 9.0,
                rect.center().y(),
                rect.right() - 9.0,
                rect.center().y(),
            )
        )
    painter.restore()


def handle_library_card_check_event(
    event: QEvent,
    model: QAbstractItemModel,
    option: QStyleOptionViewItem,
    index: QModelIndex | QPersistentModelIndex,
    typography: TypographyTokens,
    *,
    checkbox_only: bool = True,
) -> bool:
    if not index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
        return False
    activate = False
    if isinstance(event, QMouseEvent):
        hit_rect = (
            library_card_checkbox_rect(option, typography)
            if checkbox_only
            else library_card_rect(option, typography)
        )
        activate = (
            event.type() is QEvent.Type.MouseButtonRelease
            and event.button() is Qt.MouseButton.LeftButton
            and hit_rect.contains(event.position())
        )
    elif isinstance(event, QKeyEvent):
        activate = event.type() is QEvent.Type.KeyPress and event.key() in {
            Qt.Key.Key_Space,
            Qt.Key.Key_Select,
        }
    if not activate:
        return False
    state = index.data(Qt.ItemDataRole.CheckStateRole)
    next_state = (
        Qt.CheckState.Unchecked
        if state == Qt.CheckState.Checked
        else Qt.CheckState.Checked
    )
    return model.setData(index, next_state, Qt.ItemDataRole.CheckStateRole)


__all__ = [
    "handle_library_card_check_event",
    "library_card_checkbox_rect",
    "paint_library_card_checkbox",
]
