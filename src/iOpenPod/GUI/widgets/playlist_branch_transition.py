"""Move Playlist rows and their enclosing layout with the same spring clock."""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QSignalBlocker,
    Qt,
    Signal,
)
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QTreeView, QWidget

from iOpenPod.GUI.presentation.motion import SpringAnimation


class PlaylistBranchTransition(QObject):
    """Keep native navigation authoritative while painting a bounded row slide.

    QTreeView's built-in branch animation has an independent, fixed easing curve.
    Instead, capture both layouts and use the enclosing body's animated height
    to reveal children and translate following rows. Reversing the same folder
    reuses its images and leaves the shared spring's velocity intact.
    """

    settleRequested = Signal()

    def __init__(self, view: QTreeView, animation: SpringAnimation) -> None:
        super().__init__(view)
        self._view = view
        self._animation = animation
        self._index = QPersistentModelIndex()
        self._closed_height = 0
        self._extent = 0
        self._capturing = False
        self._overlay = _BranchSlide(view.viewport())
        animation.valueChanged.connect(self._advance)
        animation.finished.connect(self.clear)
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)
        view.selectionModel().currentChanged.connect(self._selection_changed)

    def finish_other_branch(self, index: QModelIndex) -> None:
        """Settle an earlier branch before a different branch changes geometry."""

        if self._index.isValid() and self._index != index:
            self.settleRequested.emit()

    def prepare(self, index: QModelIndex, before: int, after: int) -> bool:
        """Capture after a native expansion signal, with native animation off."""

        if (
            self._index == index
            and self._animation.state() != QAbstractAnimation.State.Stopped
        ):
            return True
        self.clear()
        view = self._view
        viewport = view.viewport()
        header = view.visualRect(index)
        if not header.isValid() or before == after:
            return False
        region = QRect(
            0,
            header.bottom() + 1,
            viewport.width(),
            min(
                viewport.height() - header.bottom() - 1,
                view.screen().availableGeometry().height(),
            ),
        )
        if region.isEmpty():
            return False
        expanded = view.isExpanded(index)
        self._capturing = True
        try:
            # Signals have already committed the user's intent. Temporarily
            # render the other layout without publishing a second toggle.
            with QSignalBlocker(view):
                try:
                    view.setExpanded(index, not expanded)
                    view.doItemsLayout()
                    old = viewport.grab(region)
                finally:
                    view.setExpanded(index, expanded)
                    view.doItemsLayout()
                new = viewport.grab(region)
        finally:
            self._capturing = False
        self._index = QPersistentModelIndex(index)
        self._closed_height = min(before, after)
        self._extent = abs(after - before)
        self._overlay.expanded = new if expanded else old
        self._overlay.collapsed = old if expanded else new
        self._overlay.setGeometry(region)
        self._advance(before)
        self._overlay.show()
        self._overlay.raise_()
        return True

    def clear(self) -> None:
        """Discard snapshots when the authoritative view can be shown again."""

        self._overlay.hide()
        self._overlay.expanded = QPixmap()
        self._overlay.collapsed = QPixmap()
        self._index = QPersistentModelIndex()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not self._index.isValid() or self._capturing:
            return False
        if (
            event.type()
            in {
                QEvent.Type.Wheel,
                QEvent.Type.FontChange,
                QEvent.Type.StyleChange,
                QEvent.Type.PaletteChange,
                QEvent.Type.DragEnter,
                QEvent.Type.DragMove,
            }
            or (
                isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and (
                    event.key() not in {Qt.Key.Key_Left, Qt.Key.Key_Right}
                    or self._view.currentIndex() != self._index
                )
            )
            or (
                watched is self._view.viewport()
                and isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonPress
                and self._view.indexAt(event.position().toPoint()) != self._index
            )
        ):
            self.settleRequested.emit()
        return False

    def _advance(self, value: object) -> None:
        if isinstance(value, (int, float)):
            self._overlay.reveal = max(
                0, min(self._extent, round(value - self._closed_height))
            )
            self._overlay.update()

    def _selection_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not self._capturing:
            self.finish_other_branch(current)


class _BranchSlide(QWidget):
    """Leave the folder header live; moving snapshots cannot activate rows."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("playlistBranchSlide")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.expanded = QPixmap()
        self.collapsed = QPixmap()
        self.reveal = 0
        self.hide()

    def event(self, event: QEvent) -> bool:
        if event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.ContextMenu,
        }:
            event.accept()
            return True
        return super().event(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        # Both captures include the themed background. Always cover the full
        # region, including pixels vacated by following rows during a collapse.
        painter.drawPixmap(0, 0, self.expanded)
        painter.drawPixmap(0, self.reveal, self.collapsed)
        painter.end()


__all__ = ["PlaylistBranchTransition"]
