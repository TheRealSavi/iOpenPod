"""Readable Calendar and Alarm rows without persistent per-item widgets."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class ExtrasDelegate(QStyledItemDelegate):
    """Paint a title, time and supporting line from ordinary accessible item text."""

    def __init__(self, parent: QWidget, *, alarms: bool = False) -> None:
        super().__init__(parent)
        self._alarms = alarms

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        line = option.fontMetrics.height()
        if self._alarms:
            time_font = QFont(option.font)
            time_font.setBold(True)
            time_font.setPointSizeF(max(1.0, time_font.pointSizeF()) * 2.1)
            return QSize(
                240,
                QFontMetrics(time_font).height()
                + line * 2
                + LAYOUT.space_lg
                + LAYOUT.space_md
                + LAYOUT.space_2xs,
            )
        return QSize(240, line * 4 + LAYOUT.space_md)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        painter.setClipRect(option.rect)
        rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        palette = option.palette
        # QSS can derive a translucent PlaceholderText from the view's foreground.
        # Keep the application's opaque, contrast-qualified secondary text role.
        secondary = QApplication.palette().color(
            QPalette.ColorGroup.Active, QPalette.ColorRole.PlaceholderText
        )
        if selected or hovered:
            fill = palette.color(
                QPalette.ColorRole.Link if selected else QPalette.ColorRole.Mid
            )
            fill.setAlpha(24 if selected else 16)
            painter.fillRect(rect, fill)
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(
                QPen(palette.color(QPalette.ColorRole.Link), 1, Qt.PenStyle.DotLine)
            )
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        time = str(index.sibling(index.row(), 1).data() or "")
        detail = str(index.sibling(index.row(), 2).data() or "")
        status = str(index.sibling(index.row(), 3).data() or "")
        x, y = rect.x() + LAYOUT.space_md, rect.y() + LAYOUT.space_sm
        width = rect.width() - LAYOUT.space_xl
        font = QFont(option.font)
        font.setBold(True)
        if self._alarms:
            font.setPointSizeF(max(1.0, font.pointSizeF()) * 2.1)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        enabled: object = index.data(int(Qt.ItemDataRole.UserRole) + 1)
        painter.setPen(
            secondary
            if self._alarms and enabled is False
            else palette.color(QPalette.ColorRole.Text)
        )
        time_width = width
        if self._alarms and status:
            status_font = QFont(option.font)
            status_font.setBold(True)
            status_metrics = QFontMetrics(status_font)
            status_width = min(width // 3, status_metrics.horizontalAdvance(status))
            painter.setFont(status_font)
            painter.setPen(palette.color(QPalette.ColorRole.Text))
            painter.drawText(
                QRect(x + width - status_width, y, status_width, metrics.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                status_metrics.elidedText(
                    status, Qt.TextElideMode.ElideRight, status_width
                ),
            )
            painter.setFont(font)
            painter.setPen(
                secondary
                if enabled is False
                else palette.color(QPalette.ColorRole.Text)
            )
            time_width -= status_width + LAYOUT.space_lg
        painter.drawText(
            QRect(x, y, time_width, metrics.height()),
            Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(
                time if self._alarms else title, Qt.TextElideMode.ElideRight, time_width
            ),
        )
        y += metrics.height() + LAYOUT.space_xs
        font = QFont(option.font)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        painter.setPen(
            palette.color(
                QPalette.ColorRole.Text if self._alarms else QPalette.ColorRole.Link
            )
        )
        painter.drawText(
            QRect(x, y, width, metrics.height()),
            Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(
                title if self._alarms else time, Qt.TextElideMode.ElideRight, width
            ),
        )
        y += metrics.height() + LAYOUT.space_2xs
        painter.setPen(
            secondary
            if self._alarms
            else palette.color(QPalette.ColorRole.PlaceholderText)
        )
        painter.drawText(
            QRect(x, y, width, metrics.height()),
            Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(
                detail
                if self._alarms
                else " · ".join(part for part in (detail, status) if part),
                Qt.TextElideMode.ElideRight,
                width,
            ),
        )
        painter.restore()
