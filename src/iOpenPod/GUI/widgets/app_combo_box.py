"""Application-wide combo box with a crisp, palette-driven popup and indicator."""

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    Qt,
)
from PySide6.QtGui import QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QWidget,
)

from iOpenPod.GUI.presentation.dropdown_indicator import paint_dropdown_indicator
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
        paint_dropdown_indicator(self, indicator_rect, expanded=self.view().isVisible())

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
