"""A compact themed dropdown for selecting any number of options."""

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, Qt
from PySide6.QtGui import (
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QStandardItem,
    QStandardItemModel,
    QWheelEvent,
)
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QWidget

from iOpenPod.GUI.widgets.app_combo_box import AppComboBox

SUMMARY_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class SelectionDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not isinstance(option.widget, CheckableComboBox):
            super().paint(painter, option, index)
            return
        combo = option.widget
        painter.save()
        group = (
            QPalette.ColorGroup.Active
            if combo.isEnabled()
            else QPalette.ColorGroup.Disabled
        )
        painter.setPen(option.palette.color(group, QPalette.ColorRole.ButtonText))
        painter.drawText(
            option.rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading,
            option.fontMetrics.elidedText(
                combo.selection_text(), Qt.TextElideMode.ElideRight, option.rect.width()
            ),
        )
        painter.restore()


class CheckableComboBox(AppComboBox):
    """Keep the popup open while toggling rows with the mouse or Space."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = QStandardItemModel(self)
        self.setModel(self._items)
        self.setItemDelegate(SelectionDelegate(self))
        self.setLabelDrawingMode(self.LabelDrawingMode.UseDelegate)
        self.setSizeAdjustPolicy(
            self.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.setMinimumContentsLength(12)
        self.view().installEventFilter(self)
        self.view().viewport().installEventFilter(self)
        self._items.dataChanged.connect(self.refresh_summary)

    def add_choice(
        self, label: str, value: object, *, checked: bool, enabled: bool
    ) -> None:
        item = QStandardItem(label)
        item.setData(value, Qt.ItemDataRole.UserRole)
        item.setToolTip(label)
        item.setCheckable(True)
        item.setEditable(False)
        item.setEnabled(enabled)
        item.setCheckState(
            Qt.CheckState.Checked if checked and enabled else Qt.CheckState.Unchecked
        )
        self._items.appendRow(item)
        self.refresh_summary()

    def item(self, index: int) -> QStandardItem:
        return self._items.item(index)

    def selection_text(self) -> str:
        labels = self._selected_labels()
        if not self.count():
            return self.placeholderText()
        if not labels:
            return self.tr("None")
        if len(labels) == 1:
            return labels[0]
        return self.tr("%1 selected").replace("%1", str(len(labels)))

    def _selected_labels(self) -> tuple[str, ...]:
        return tuple(
            summary
            if isinstance(summary := item.data(SUMMARY_ROLE), str)
            else item.text()
            for index in range(self.count())
            if (item := self.item(index)).isEnabled()
            and item.checkState() == Qt.CheckState.Checked
        )

    def refresh_summary(self) -> None:
        self.setToolTip("\n".join(self._selected_labels()) or self.selection_text())
        self.setAccessibleDescription(self.toolTip())
        self.update()

    def _toggle(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        item = self.item(index.row())
        if item.isEnabled():
            item.setCheckState(
                Qt.CheckState.Unchecked
                if item.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and watched is self.view().viewport()
        ):
            if event.type() == QEvent.Type.MouseButtonPress:
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                index = self.view().indexAt(event.position().toPoint())
                self.view().setCurrentIndex(index)
                self._toggle(index)
                return True
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and watched is self.view()
        ):
            if event.key() == Qt.Key.Key_Space:
                self._toggle(self.view().currentIndex())
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
                self.hidePopup()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Down,
            Qt.Key.Key_Up,
        ):
            self.showPopup()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()
