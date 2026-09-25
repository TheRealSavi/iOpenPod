# Hallmark · component: Artist/Genre collection list · genre: modern-minimal
# theme: iOpenPod · states: default · hover · focus · pressed · disabled · selected
# contrast: pass (40-41) · slop: pass (applicable gates)
# pre-emit critique: P5 H4 E4 S5 R5 V4
"""Compact two-line rows for Artist and Genre source lists."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from iOpenPod.app.models.collection_list_model import (
    CollectionRole,
    CollectionSummary,
)
from iOpenPod.GUI.presentation.collection_text import collection_summary_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class CollectionListDelegate(QStyledItemDelegate):
    """Paint collection identity and scale without allocating row widgets."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager

    def sizeHint(
        self,
        _option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(
            LAYOUT.source_list_minimum_width,
            LAYOUT.collection_list_row_height,
        )

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        summary = index.data(CollectionRole.SUMMARY)
        if not isinstance(summary, CollectionSummary):
            return

        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        selected = enabled and bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = enabled and bool(option.state & QStyle.StateFlag.State_MouseOver)
        pressed = enabled and bool(option.state & QStyle.StateFlag.State_Sunken)
        focused = enabled and bool(option.state & QStyle.StateFlag.State_HasFocus)
        cell = QRectF(option.rect).adjusted(
            0.0,
            float(LAYOUT.space_3xs),
            0.0,
            -float(LAYOUT.space_3xs),
        )

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_background(painter, cell, selected, hovered, pressed)
        self._paint_text(painter, option, cell, index, summary, enabled)
        if focused:
            self._paint_focus(painter, cell)
        painter.restore()

    def _paint_background(
        self,
        painter: QPainter,
        cell: QRectF,
        selected: bool,
        hovered: bool,
        pressed: bool,
    ) -> None:
        tokens = self._theme_manager.tokens
        fill = None
        if pressed:
            fill = tokens.surface_pressed
        elif selected:
            fill = tokens.surface_selected
        elif hovered:
            fill = tokens.surface_hover
        if fill is None:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(
            cell,
            float(LAYOUT.radius_control),
            float(LAYOUT.radius_control),
        )

    def _paint_text(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        cell: QRectF,
        index: QModelIndex | QPersistentModelIndex,
        summary: CollectionSummary,
        enabled: bool,
    ) -> None:
        tokens = self._theme_manager.tokens
        typography = self._theme_manager.typography
        title_font = QFont(option.font)
        title_font.setPointSizeF(typography.body_pt)
        title_font.setWeight(QFont.Weight.Bold)
        detail_font = QFont(option.font)
        detail_font.setPointSizeF(typography.small_pt)
        detail_font.setWeight(QFont.Weight.Normal)
        title_metrics = QFontMetrics(title_font)
        detail_metrics = QFontMetrics(detail_font)
        text_height = (
            title_metrics.height() + LAYOUT.space_3xs + detail_metrics.height()
        )
        text_left = cell.left() + LAYOUT.space_sm
        text_width = max(
            1.0,
            cell.right() - text_left - LAYOUT.space_xs,
        )
        text_top = cell.top() + max(0.0, (cell.height() - text_height) / 2.0)
        title = index.data(Qt.ItemDataRole.DisplayRole)
        title_text = title if isinstance(title, str) else ""

        painter.setFont(title_font)
        painter.setPen(QColor(tokens.text if enabled else tokens.text_disabled))
        painter.drawText(
            QRectF(text_left, text_top, text_width, title_metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(
                title_text,
                Qt.TextElideMode.ElideRight,
                round(text_width),
            ),
        )

        painter.setFont(detail_font)
        painter.setPen(
            QColor(tokens.text_secondary if enabled else tokens.text_disabled)
        )
        painter.drawText(
            QRectF(
                text_left,
                text_top + title_metrics.height() + LAYOUT.space_3xs,
                text_width,
                detail_metrics.height(),
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            detail_metrics.elidedText(
                collection_summary_text(summary),
                Qt.TextElideMode.ElideRight,
                round(text_width),
            ),
        )

    def _paint_focus(self, painter: QPainter, cell: QRectF) -> None:
        pen = QPen(QColor(self._theme_manager.tokens.focus))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = 1.0
        painter.drawRoundedRect(
            cell.adjusted(inset, inset, -inset, -inset),
            float(LAYOUT.radius_control) - inset,
            float(LAYOUT.radius_control) - inset,
        )


__all__ = ["CollectionListDelegate"]
