"""Shared pointer and box-selection behavior for Library card grids."""

from PySide6.QtCore import QEvent, QModelIndex, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget

from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView


class SelectionGridView(EqualizedGridView):
    """Keep card-grid selection and empty-space gestures consistent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unmodified_box_select_blocked = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() is Qt.MouseButton.LeftButton
            and not self.indexAt(event.position().toPoint()).isValid()
        ):
            self.clearSelection()
            self.setCurrentIndex(QModelIndex())
            if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._unmodified_box_select_blocked = True
                event.accept()
                return
        self._unmodified_box_select_blocked = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        cursor = (
            Qt.CursorShape.PointingHandCursor
            if self.indexAt(event.position().toPoint()).isValid()
            else Qt.CursorShape.ArrowCursor
        )
        self.viewport().setCursor(cursor)
        if self._unmodified_box_select_blocked:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._unmodified_box_select_blocked:
            self._unmodified_box_select_blocked = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)


__all__ = ["SelectionGridView"]
