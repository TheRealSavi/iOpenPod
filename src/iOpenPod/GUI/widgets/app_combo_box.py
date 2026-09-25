"""Application-wide combo box with a crisp, palette-driven popup and indicator."""

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPointF,
    QSize,
    Qt,
)
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class _ComboPopupDelegate(QStyledItemDelegate):
    """Keep combo separators compact while preserving native item rendering."""

    _SEPARATOR_HEIGHT = (2 * LAYOUT.space_2xs) + 1

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        size = super().sizeHint(option, index)
        if _is_separator(index):
            size.setHeight(self._SEPARATOR_HEIGHT)
        return size

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not _is_separator(index):
            super().paint(painter, option, index)
            return

        left = option.rect.left() + LAYOUT.space_xs
        right = option.rect.right() - LAYOUT.space_xs
        if right < left:
            return
        painter.save()
        pen = QPen(option.palette.color(QPalette.ColorRole.Mid))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        y = option.rect.center().y()
        painter.drawLine(left, y, right, y)
        painter.restore()


def _is_separator(index: QModelIndex | QPersistentModelIndex) -> bool:
    description = index.data(Qt.ItemDataRole.AccessibleDescriptionRole)
    return isinstance(description, str) and description == "separator"


class AppComboBox(QComboBox):
    """Provide the default iOpenPod drop-down treatment over native behavior."""

    _CHEVRON_HALF_WIDTH = 5.0
    _CHEVRON_HALF_HEIGHT = 2.5
    _CHEVRON_STROKE_WIDTH = 1.75

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("themedIndicator", True)
        popup_view = QListView(self)
        popup_view.setProperty("themedComboPopup", True)
        popup_view.setItemDelegate(_ComboPopupDelegate(popup_view))
        self.setView(popup_view)
        self._refresh_cursor()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.EnabledChange:
            self._refresh_cursor()
        super().changeEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)

        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        indicator_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        if indicator_rect.isEmpty():
            return

        color_group = (
            QPalette.ColorGroup.Active
            if self.isEnabled()
            else QPalette.ColorGroup.Disabled
        )
        color_role = (
            QPalette.ColorRole.Accent
            if self.hasFocus() or self.view().isVisible()
            else QPalette.ColorRole.ButtonText
        )
        center = indicator_rect.center()
        direction = -1.0 if self.view().isVisible() else 1.0
        path = QPainterPath(
            QPointF(
                center.x() - self._CHEVRON_HALF_WIDTH,
                center.y() - (direction * self._CHEVRON_HALF_HEIGHT),
            )
        )
        path.lineTo(
            QPointF(
                center.x(),
                center.y() + (direction * self._CHEVRON_HALF_HEIGHT),
            )
        )
        path.lineTo(
            QPointF(
                center.x() + self._CHEVRON_HALF_WIDTH,
                center.y() - (direction * self._CHEVRON_HALF_HEIGHT),
            )
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self.palette().color(color_group, color_role))
        pen.setWidthF(self._CHEVRON_STROKE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def showPopup(self) -> None:
        super().showPopup()
        self.update()

    def hidePopup(self) -> None:
        super().hidePopup()
        self.update()

    def _refresh_cursor(self) -> None:
        cursor = (
            Qt.CursorShape.PointingHandCursor
            if self.isEnabled()
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)
