"""Readable Extras rows without persistent per-item widgets."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


def _paint_row_surface(
    painter: QPainter,
    option: QStyleOptionViewItem,
    *,
    separator: bool,
    collection: bool = True,
) -> QRect:
    rect = option.rect.adjusted(
        LAYOUT.space_2xs, LAYOUT.space_2xs, -LAYOUT.space_2xs, -LAYOUT.space_2xs
    )
    selected = bool(option.state & QStyle.StateFlag.State_Selected)
    hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if selected or hovered:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            option.palette.brush(
                QPalette.ColorRole.Highlight
                if selected
                else QPalette.ColorRole.AlternateBase
            )
        )
        painter.drawRoundedRect(rect, LAYOUT.radius_control, LAYOUT.radius_control)
    if separator and not selected and (not collection or not hovered):
        inset = LAYOUT.space_md if collection else 0
        painter.setPen(option.palette.color(QPalette.ColorRole.Mid))
        painter.drawLine(
            rect.bottomLeft() + QPoint(inset, 0),
            rect.bottomRight() - QPoint(inset, 0),
        )
    if option.state & QStyle.StateFlag.State_HasFocus:
        painter.setPen(
            QPen(option.palette.color(QPalette.ColorRole.Link), 1, Qt.PenStyle.DotLine)
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            rect.adjusted(1, 1, -1, -1), LAYOUT.radius_control, LAYOUT.radius_control
        )
    return rect


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
        rect = _paint_row_surface(
            painter,
            option,
            separator=not self._alarms or index.sibling(index.row() + 1, 0).isValid(),
            collection=self._alarms,
        )
        palette = option.palette
        # QSS can derive a translucent PlaceholderText from the view's foreground.
        # Keep the application's opaque, contrast-qualified secondary text role.
        secondary = QApplication.palette().color(
            QPalette.ColorGroup.Active, QPalette.ColorRole.PlaceholderText
        )
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
            status_rect = QRect(
                x + width - status_width - LAYOUT.space_md,
                y
                + (metrics.height() - status_metrics.height()) // 2
                - LAYOUT.space_2xs,
                status_width + LAYOUT.space_md,
                status_metrics.height() + LAYOUT.space_xs,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.brush(QPalette.ColorRole.AlternateBase))
            painter.drawRoundedRect(
                status_rect, LAYOUT.radius_control, LAYOUT.radius_control
            )
            painter.setFont(status_font)
            painter.setPen(
                secondary
                if enabled is False
                else palette.color(QPalette.ColorRole.Text)
            )
            painter.drawText(
                status_rect.adjusted(LAYOUT.space_xs, 0, -LAYOUT.space_xs, 0),
                Qt.AlignmentFlag.AlignCenter,
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
            time_width -= status_rect.width() + LAYOUT.space_lg
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
        painter.setPen(secondary)
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


class ToneDelegate(QStyledItemDelegate):
    """A name-led tone row with quiet type and duration, using accessible columns."""

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        title_font = QFont(option.font)
        title_font.setBold(True)
        title_font.setPointSizeF(max(1.0, title_font.pointSizeF()) * 1.25)
        return QSize(
            240,
            QFontMetrics(title_font).height()
            + option.fontMetrics.height()
            + LAYOUT.space_xl
            + LAYOUT.space_2xs,
        )

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        painter.setClipRect(option.rect)
        rect = _paint_row_surface(
            painter, option, separator=index.sibling(index.row() + 1, 0).isValid()
        )
        rect.adjust(
            LAYOUT.space_md, LAYOUT.space_sm, -LAYOUT.space_md, -LAYOUT.space_sm
        )
        secondary = QApplication.palette().color(
            QPalette.ColorGroup.Active, QPalette.ColorRole.PlaceholderText
        )
        title_font = QFont(option.font)
        title_font.setBold(True)
        title_font.setPointSizeF(max(1.0, title_font.pointSizeF()) * 1.25)
        title_metrics = QFontMetrics(title_font)
        detail_metrics = option.fontMetrics
        duration = str(index.sibling(index.row(), 2).data() or "")
        duration_width = min(
            rect.width() // 3, detail_metrics.horizontalAdvance(duration)
        )
        title_width = max(0, rect.width() - duration_width - LAYOUT.space_lg)
        painter.setFont(title_font)
        painter.setPen(option.palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            QRect(rect.x(), rect.y(), title_width, title_metrics.height()),
            Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(
                str(index.data() or ""), Qt.TextElideMode.ElideRight, title_width
            ),
        )
        painter.setFont(option.font)
        painter.setPen(secondary)
        painter.drawText(
            QRect(
                rect.right() - duration_width,
                rect.y(),
                duration_width,
                title_metrics.height(),
            ),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            detail_metrics.elidedText(
                duration, Qt.TextElideMode.ElideRight, duration_width
            ),
        )
        painter.drawText(
            QRect(
                rect.x(),
                rect.y() + title_metrics.height() + LAYOUT.space_2xs,
                rect.width(),
                detail_metrics.height(),
            ),
            Qt.AlignmentFlag.AlignVCenter,
            detail_metrics.elidedText(
                str(index.sibling(index.row(), 1).data() or ""),
                Qt.TextElideMode.ElideRight,
                rect.width(),
            ),
        )
        painter.restore()
