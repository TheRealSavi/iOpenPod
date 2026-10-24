"""Paint Genius sections and collections in the shared source-list style."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from iOpenPod.GUI.delegates.collection_list_delegate import CollectionListDelegate
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

DETAIL_ROLE = Qt.ItemDataRole.UserRole + 1
SECTION_ROLE = Qt.ItemDataRole.UserRole + 2


class GeniusCollectionDelegate(CollectionListDelegate):
    """Use the Genre list's shape, type scale, and selection treatment."""

    def sizeHint(
        self,
        _option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        height = (
            LAYOUT.control_height_large
            if index.data(SECTION_ROLE)
            else LAYOUT.collection_list_row_height
        )
        return QSize(LAYOUT.source_list_minimum_width, height)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        section = bool(index.data(SECTION_ROLE))
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        selected = enabled and bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = enabled and bool(option.state & QStyle.StateFlag.State_MouseOver)
        pressed = enabled and bool(option.state & QStyle.StateFlag.State_Sunken)
        focused = enabled and bool(option.state & QStyle.StateFlag.State_HasFocus)
        cell = QRectF(option.rect).adjusted(
            0.0, float(LAYOUT.space_3xs), 0.0, -float(LAYOUT.space_3xs)
        )
        tokens = self._theme_manager.tokens
        typography = self._theme_manager.typography
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not section:
            self._paint_background(painter, cell, selected, hovered, pressed)
        font = QFont(option.font)
        font.setPointSizeF(typography.small_pt if section else typography.body_pt)
        font.setWeight(QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        left = cell.left() + LAYOUT.space_sm
        width = max(1.0, cell.right() - left - LAYOUT.space_xs)
        title = index.data(Qt.ItemDataRole.DisplayRole)
        painter.setFont(font)
        painter.setPen(QColor(tokens.accent if section else tokens.text))
        if section:
            painter.drawText(
                QRectF(left, cell.top(), width, cell.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(
                    str(title or ""), Qt.TextElideMode.ElideRight, round(width)
                ),
            )
        else:
            detail_font = QFont(option.font)
            detail_font.setPointSizeF(typography.small_pt)
            detail_font.setWeight(QFont.Weight.Normal)
            detail_metrics = QFontMetrics(detail_font)
            text_height = metrics.height() + LAYOUT.space_3xs + detail_metrics.height()
            top = cell.top() + max(0.0, (cell.height() - text_height) / 2.0)
            painter.drawText(
                QRectF(left, top, width, metrics.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(
                    str(title or ""), Qt.TextElideMode.ElideRight, round(width)
                ),
            )
            painter.setFont(detail_font)
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(
                QRectF(
                    left,
                    top + metrics.height() + LAYOUT.space_3xs,
                    width,
                    detail_metrics.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                detail_metrics.elidedText(
                    str(index.data(DETAIL_ROLE) or ""),
                    Qt.TextElideMode.ElideRight,
                    round(width),
                ),
            )
            if focused:
                self._paint_focus(painter, cell)
        painter.restore()
