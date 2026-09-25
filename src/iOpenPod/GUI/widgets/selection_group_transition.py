"""Viewport-bounded slide transitions for collapsible card sections."""

from dataclasses import dataclass

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QKeyEvent, QPainter, QPaintEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QAbstractItemView, QWidget

from iOpenPod.app.models.selection_grouping import SelectionGroupingRole
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


@dataclass(slots=True)
class _PendingSlide:
    row: int
    group: object
    header: QRect
    region: QRect
    before: QPixmap
    expanded: bool
    extent: int
    current: int
    reversing: bool
    attempts: int = 0


class SelectionGroupTransition(QObject):
    """Commit a toggle immediately, then slide clipped viewport snapshots.

    Two viewport-sized images keep memory independent of the number of cards and
    avoid relaying out the library on each frame. The real header stays interactive
    so a second toggle can reverse the current transition without jumping.
    """

    def __init__(self, view: QAbstractItemView) -> None:
        super().__init__(view)
        self._view = view
        self._viewport = view.viewport()
        self._overlay = _SectionSlide(self._viewport)
        self._changing = False
        self._model = view.model()
        self._group: object = None
        self._pending: _PendingSlide | None = None
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._prepare_slide)
        self._animation = QVariantAnimation(self)
        self._animation.setObjectName("selectionGroupAnimation")
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self.cancel)
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)
        view.verticalScrollBar().valueChanged.connect(self.cancel)
        view.horizontalScrollBar().valueChanged.connect(self.cancel)
        self._model.modelAboutToBeReset.connect(self.cancel)
        self._model.layoutAboutToBeChanged.connect(self.cancel)
        self._model.dataChanged.connect(self.cancel)
        self._model.rowsAboutToBeInserted.connect(self.cancel)
        self._model.rowsAboutToBeRemoved.connect(self.cancel)

    def toggle(self, index: QModelIndex | QPersistentModelIndex) -> bool:
        view = self._view
        model = index.model()
        row = index.row()
        keep_current = view.currentIndex() == index
        expanded = bool(index.data(SelectionGroupingRole.EXPANDED))
        group = index.data(SelectionGroupingRole.GROUP)
        reversing = (
            self._pending is None and self._overlay.isVisible() and group == self._group
        )
        current = self._overlay.reveal if reversing else 0
        if reversing:
            self._animation.stop()
        else:
            self.cancel()

        header = view.visualRect(index)
        region = QRect(
            0,
            header.bottom() + 1,
            view.viewport().width(),
            view.viewport().height() - header.bottom() - 1,
        )
        animate = (
            view.isVisible()
            and model is self._model
            and header.top() >= 0
            and region.height() > 0
        )
        before = (
            view.viewport().grab(region) if animate and not reversing else QPixmap()
        )
        extent = self._section_height(index) if expanded and animate else 0
        self._changing = True
        try:
            changed = model.setData(index, not expanded, SelectionGroupingRole.EXPANDED)
            view.executeDelayedItemsLayout()
            if keep_current:
                view.setCurrentIndex(model.index(row, 0))
        finally:
            self._changing = False
        if not changed or not animate:
            self.cancel()
            return changed
        self._pending = _PendingSlide(
            row,
            group,
            header,
            region,
            before,
            expanded,
            extent,
            current,
            reversing,
        )
        self._prepare_slide()
        return changed

    def _prepare_slide(self) -> None:
        pending = self._pending
        if pending is None:
            return
        view = self._view
        new_index = self._model.index(pending.row, 0)
        header = view.visualRect(new_index)
        if not header.isValid():
            # QListView schedules its first batch after a reset. Hold the old
            # frame until that batch exists instead of forcing a full layout.
            pending.attempts += 1
            if pending.attempts > 3:
                self.cancel()
                return
            if not pending.reversing:
                self._overlay.setGeometry(pending.region)
                self._overlay.expanded = pending.before
                self._overlay.extent = pending.region.height()
                self._overlay.reveal = pending.region.height()
                self._overlay.show()
            self._layout_timer.start(0)
            return
        # Scroll-range clamping can move the header. Never animate stale geometry.
        if header != pending.header:
            self.cancel()
            return
        self._pending = None
        current = pending.current

        if not pending.reversing:
            self._overlay.hide()
            after = view.viewport().grab(pending.region)
            extent = (
                pending.extent if pending.expanded else self._section_height(new_index)
            )
            self._overlay.setGeometry(pending.region)
            self._overlay.expanded = pending.before if pending.expanded else after
            self._overlay.collapsed = after if pending.expanded else pending.before
            # Offscreen rows do not need images or travel beyond the viewport.
            self._overlay.extent = min(extent, pending.region.height())
            current = self._overlay.extent if pending.expanded else 0
            self._group = pending.group

        target = 0 if pending.expanded else self._overlay.extent
        if current == target:
            self.cancel()
            return
        self._overlay.reveal = current
        self._overlay.show()
        self._overlay.raise_()
        self._animation.setDuration(
            max(
                1,
                round(
                    LAYOUT.selection_group_animation_ms
                    * abs(target - current)
                    / max(1, self._overlay.extent)
                ),
            )
        )
        self._animation.setStartValue(current)
        self._animation.setEndValue(target)
        self._animation.start()

    def cancel(self, *_args: object) -> None:
        """Reveal the authoritative view when its contents or geometry change."""

        if self._changing:
            return
        self._pending = None
        self._layout_timer.stop()
        self._animation.stop()
        self._overlay.hide()
        self._overlay.expanded = QPixmap()
        self._overlay.collapsed = QPixmap()
        self._group = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._viewport
            and isinstance(event, QResizeEvent)
            and event.size().height() == event.oldSize().height()
        ):
            # A vertical scrollbar changes only the viewport width. Equalized
            # cells already reserve its space, so their captured geometry holds.
            # A resize of the view itself still cancels through its own event.
            self._overlay.resize(event.size().width(), self._overlay.height())
            return False
        if event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Hide,
            QEvent.Type.Wheel,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
            QEvent.Type.PaletteChange,
        } or (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key()
            not in {
                Qt.Key.Key_Enter,
                Qt.Key.Key_Return,
                Qt.Key.Key_Select,
                Qt.Key.Key_Space,
            }
        ):
            self.cancel()
        return False

    def _advance(self, value: object) -> None:
        if isinstance(value, (int, float)):
            self._overlay.reveal = round(value)
            self._overlay.update()

    def _section_height(self, index: QModelIndex | QPersistentModelIndex) -> int:
        model = index.model()
        count = index.data(SelectionGroupingRole.ITEM_COUNT)
        if not isinstance(count, int) or count <= 0:
            return 0
        last_row = index.row() + count
        following = model.index(last_row + 1, 0)
        end_rect = self._view.visualRect(
            following if following.isValid() else model.index(last_row, 0)
        )
        if not end_rect.isValid():
            # Batched grids have not laid out distant rows yet. Only visible
            # travel matters; never force a full-library layout for an animation.
            return self._view.viewport().height()
        bottom = end_rect.top() if following.isValid() else end_rect.bottom() + 1
        return max(0, bottom - self._view.visualRect(index).bottom() - 1)


class _SectionSlide(QWidget):
    """Clip moving cards below the real header and move following sections too."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("selectionGroupSlide")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.expanded = QPixmap()
        self.collapsed = QPixmap()
        self.extent = 0
        self.reveal = 0
        self.hide()

    def event(self, event: QEvent) -> bool:
        # Snapshot cards cannot accept actions at their final, hidden positions.
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
        painter.fillRect(self.rect(), self.palette().base())
        painter.drawPixmap(0, self.reveal, self.collapsed)
        painter.setClipRect(0, 0, self.width(), self.reveal)
        painter.drawPixmap(0, self.reveal - self.extent, self.expanded)
        painter.end()


__all__ = ["SelectionGroupTransition"]
