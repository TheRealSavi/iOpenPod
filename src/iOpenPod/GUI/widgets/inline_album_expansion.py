"""Reveal one Album panel inside the existing virtualized card grid."""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPointF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QWidget

from iOpenPod.GUI.delegates.inline_album_delegate import InlineAlbumDelegate
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView
from iOpenPod.GUI.widgets.inline_album_panel import InlineAlbumPanel


class InlineAlbumExpansion(QObject):
    """Reserve space below a complete card row and clip the revealing panel."""

    def __init__(self, view: EqualizedGridView, panel: InlineAlbumPanel) -> None:
        super().__init__(view)
        self._view = view
        self._viewport = view.viewport()
        self._panel = panel
        self._enabled = False
        self._index = QPersistentModelIndex()
        self._height = 0
        self._target_height = 0
        self._laying_out = False
        self._closing = False
        self._batch_size = view.batchSize()
        self._delegate = InlineAlbumDelegate(view.itemDelegate(), view)
        view.setItemDelegate(self._delegate)
        self._clip = QWidget(view.viewport())
        self._clip.setObjectName("inlineAlbumReveal")
        # The reveal overlays enlarged card cells. Keep unhandled child input
        # from bubbling into those cells as Album hover, selection, or actions.
        self._clip.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self._clip.setCursor(Qt.CursorShape.ArrowCursor)
        self._clip.installEventFilter(self)
        panel.setParent(self._clip)
        self._clip.hide()
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._resize)
        self._animation = QVariantAnimation(self)
        self._animation.setObjectName("inlineAlbumAnimation")
        self._animation.setDuration(LAYOUT.selection_group_animation_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self._finished)
        panel.closeRequested.connect(self.close)
        panel.preferredHeightChanged.connect(self._queue_resize)
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)
        view.verticalScrollBar().valueChanged.connect(self._position_panel)
        model = view.model()
        model.modelAboutToBeReset.connect(self.reset)
        model.layoutAboutToBeChanged.connect(self.reset)
        model.rowsAboutToBeInserted.connect(self.reset)
        model.rowsAboutToBeRemoved.connect(self.reset)

    @property
    def expanded_index(self) -> QModelIndex:
        return (
            self._view.model().index(self._index.row(), 0)
            if self._index.isValid()
            else QModelIndex()
        )

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled == enabled:
            return
        self.reset()
        self._enabled = enabled
        self._view.set_sectioned_layout(enabled)

    def open(self, index: QModelIndex) -> None:
        if not self._enabled or not index.isValid():
            return
        self._animation.stop()
        if self._index != index:
            self.reset()
            self._index = QPersistentModelIndex(index)
        self._closing = False
        # Opening already consumes the panel's latest preferred size. A queued
        # content resize would otherwise snap an interrupted reveal fully open.
        self._layout_timer.stop()
        self._target_height = self._panel.preferred_height(
            self._view.viewport().width()
        )
        self._panel.show()
        self._animate_to(self._target_height)

    def close(self) -> None:
        if not self._index.isValid():
            return
        self._closing = True
        self._view.setFocus(Qt.FocusReason.OtherFocusReason)
        self._animate_to(0)

    def reset(self, *_args: object) -> None:
        self._animation.stop()
        self._layout_timer.stop()
        self._index = QPersistentModelIndex()
        self._height = 0
        self._target_height = 0
        self._closing = False
        self._restore_batch_size()
        self._delegate.configure_expansion(-1, -1, 0)
        self._clip.hide()
        self._view.scheduleDelayedItemsLayout()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._clip and isinstance(event, QWheelEvent):
            # The mouse boundary also blocks wheel propagation. Forward only
            # wheel input left unhandled by the Track table to the smooth grid
            # scroller, preserving trackpad deltas and scroll phases.
            forwarded = QWheelEvent(
                event.position() + QPointF(self._clip.pos()),
                event.globalPosition(),
                event.pixelDelta(),
                event.angleDelta(),
                event.buttons(),
                event.modifiers(),
                event.phase(),
                event.inverted(),
                event.source(),
                event.pointingDevice(),
            )
            QApplication.sendEvent(self._viewport, forwarded)
            event.setAccepted(forwarded.isAccepted())
            return True
        if (
            watched is self._view
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and self._index.isValid()
        ):
            self.close()
            return True
        if watched is self._viewport:
            if event.type() == QEvent.Type.Resize:
                self._queue_resize()
            elif event.type() == QEvent.Type.Paint:
                self._position_panel()
        return False

    def _queue_resize(self) -> None:
        if self._index.isValid():
            self._layout_timer.start(0)

    def _resize(self) -> None:
        if not self._index.isValid():
            return
        if self._closing:
            self.reset()
            return
        self._animation.stop()
        self._target_height = self._panel.preferred_height(
            self._view.viewport().width()
        )
        self._advance(self._target_height)
        self._restore_batch_size()

    def _animate_to(self, height: int) -> None:
        self._animation.stop()
        # Stopped animations retain their old time. Reconfiguring their endpoints
        # can emit that time's value and briefly reveal a fully expanded panel.
        blocked = self._animation.blockSignals(True)
        try:
            self._animation.setStartValue(self._height)
            self._animation.setEndValue(height)
            self._animation.setCurrentTime(0)
        finally:
            self._animation.blockSignals(blocked)
        self._animation.start()

    def _advance(self, value: object) -> None:
        if not isinstance(value, (int, float)) or not self._index.isValid():
            return
        self._height = int(value)
        view = self._view
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.widget = view
        size = self._delegate.normal_cell_size(option, self._index)
        columns = max(1, view.section_header_width() // max(1, size.width()))
        first = self._index.row() // columns * columns
        last = min(first + columns - 1, view.model().rowCount() - 1)
        # Each animation frame restarts batched layout. Include the selected row
        # and viewport in its first batch so a deep-scrolled Album never vanishes
        # while Qt catches up in later event-loop turns.
        visible_rows = view.viewport().height() // max(1, size.height()) + 2
        batch_items = max(self._batch_size, last + 1 + visible_rows * columns)
        view.setBatchSize(((batch_items + columns - 1) // columns) * columns)
        self._delegate.configure_expansion(first, last, self._height)
        self._laying_out = True
        try:
            view.doItemsLayout()
        finally:
            self._laying_out = False
        self._position_panel()

    def _position_panel(self, *_args: object) -> None:
        if self._laying_out or not self._index.isValid() or self._height <= 0:
            return
        view = self._view
        rect = view.visualRect(self._index)
        if not rect.isValid():
            self._clip.hide()
            return
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.widget = view
        card_height = self._delegate.normal_cell_size(option, self._index).height()
        # Batched layout may still expose the previous frame's cell rectangle.
        # Reveal only the space actually reserved by that layout, with the top
        # anchored below the card. Subtracting the next animation height from a
        # stale rectangle briefly paints the panel over the card itself.
        revealed_height = max(0, rect.height() - card_height)
        if revealed_height == 0:
            self._clip.hide()
            return
        top = rect.top() + card_height
        width = view.viewport().width()
        self._clip.setGeometry(0, top, width, revealed_height)
        # The panel retains its final layout while the grid reveals it from above.
        self._panel.setGeometry(0, 0, width, self._target_height)
        self._panel.set_pointer_x(rect.center().x())
        self._clip.show()
        self._clip.raise_()

    def _finished(self) -> None:
        self._restore_batch_size()
        if self._height == 0:
            self.reset()
        else:
            # Keep the selected card and the beginning of its contents together.
            rect = self._view.visualRect(self._index)
            viewport_height = self._viewport.height()
            delta = (
                rect.top()
                if rect.top() < 0
                else min(rect.top(), max(0, rect.bottom() + 1 - viewport_height))
            )
            bar = self._view.verticalScrollBar()
            bar.setValue(bar.value() + delta)

    def _restore_batch_size(self) -> None:
        """Restore the ordinary budget while keeping complete visual rows."""

        view = self._view
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.widget = view
        cell_width = (
            self._delegate.normal_cell_size(option, QModelIndex()).width()
            if view.sectioned_layout
            else view.gridSize().width()
        )
        columns = max(1, view.section_header_width() // max(1, cell_width))
        view.setBatchSize(max(1, self._batch_size // columns) * columns)


__all__ = ["InlineAlbumExpansion"]
