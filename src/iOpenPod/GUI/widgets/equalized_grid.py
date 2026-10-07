"""Stable equal-width cells for virtualized card grids."""

from typing import cast

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QSize, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QListView, QStyle, QStyleOptionViewItem, QWidget

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

_EXACT_FIT_GUARD = 1


class EqualizedGridView(QListView):
    """Distribute fixed-size cards across equal-width viewport cells."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._equalized_layout_width = -1
        self._equalized_column_count = -1
        self._equalized_cell_width = LAYOUT.album_card_width + LAYOUT.space_md
        self._sectioned_layout = False
        self._batch_item_budget: int | None = None
        self._card_size = QSize(
            LAYOUT.album_card_width,
            LAYOUT.album_card_minimum_height,
        )
        self._deferred_equalize_timer = QTimer(self)
        self._deferred_equalize_timer.setSingleShot(True)
        self._deferred_equalize_timer.timeout.connect(self._equalize_cells)
        self.setResizeMode(QListView.ResizeMode.Fixed)
        self.setSpacing(0)
        self.setGridSize(self._cell_size(self._card_size.width() + LAYOUT.space_md))

    @property
    def sectioned_layout(self) -> bool:
        return self._sectioned_layout

    def set_sectioned_layout(self, enabled: bool) -> None:
        """Allow variable full-width header rows around equalized card cells."""

        if enabled == self._sectioned_layout:
            return
        self._sectioned_layout = enabled
        self.setUniformItemSizes(not enabled)
        self.setResizeMode(
            QListView.ResizeMode.Adjust if enabled else QListView.ResizeMode.Fixed
        )
        self._equalized_layout_width = -1
        if enabled:
            self.setGridSize(QSize())
        self._equalize_cells()

    def section_header_width(self) -> int:
        """Return the stable width available to a full-row section header."""

        return max(1, self._equalized_layout_width)

    def sectioned_item_size(self, item_size: QSize) -> QSize:
        """Return one equalized card cell while QListView uses variable hints."""

        return QSize(
            max(item_size.width(), self._equalized_cell_width),
            item_size.height() + LAYOUT.space_xs,
        )

    def synchronize_item_size(self) -> None:
        """Refresh uniform cell geometry from the installed delegate's size hint."""

        option = QStyleOptionViewItem()
        option.initFrom(self)
        option.font = self.font()
        card_size = self.itemDelegate().sizeHint(option, QModelIndex())
        if not card_size.isValid() or card_size == self._card_size:
            return
        self._card_size = card_size
        self._equalized_layout_width = -1
        self._equalize_cells()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._equalize_cells()

    def updateGeometries(self) -> None:
        scrollbar = self.verticalScrollBar()
        position = scrollbar.value()
        maximum = scrollbar.maximum()
        super().updateGeometries()
        # PySide's stub omits None, which Qt returns before a model is installed.
        model = cast("QAbstractItemModel | None", self.model())
        if (
            self._sectioned_layout
            and self.layoutMode() is QListView.LayoutMode.Batched
            and model is not None
            and model.rowCount() > 0
            and not self.visualRect(model.index(model.rowCount() - 1, 0)).isValid()
        ):
            # Regrouping restarts batched layout. Its temporary first-batch range
            # must not clamp an existing viewport back toward the start. Once the
            # last row is laid out, Qt can clamp against the actual content size.
            scrollbar.setMaximum(max(maximum, scrollbar.maximum()))
            scrollbar.setValue(position)

    def viewportEvent(self, event: QEvent) -> bool:
        handled = super().viewportEvent(event)
        if event.type() is QEvent.Type.Resize:
            # QAbstractScrollArea can resize only its viewport when an automatic
            # scrollbar appears or disappears. Queue one coalesced pass because
            # scrollbar visibility settles after the synchronous resize callback.
            self._deferred_equalize_timer.start(0)
        return handled

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        }:
            self.synchronize_item_size()
            self._equalize_cells()

    def _equalize_cells(self) -> None:
        viewport_width = max(1, self.viewport().width())
        # QListView's auto-scrollbar layout reserves the vertical scrollbar extent
        # while deciding whether wrapped content fits. Use the same stable width
        # whether the scrollbar is currently visible or hidden so its appearance
        # cannot feed back into a different card formation.
        scrollbar = self.verticalScrollBar()
        scrollbar_extent = max(
            1,
            self.style().pixelMetric(
                QStyle.PixelMetric.PM_ScrollBarExtent,
                None,
                scrollbar,
            ),
        )
        unobscured_viewport_width = viewport_width + (
            scrollbar_extent if scrollbar.isVisible() else 0
        )
        layout_width = max(
            1,
            unobscured_viewport_width - scrollbar_extent - _EXACT_FIT_GUARD,
        )
        if layout_width == self._equalized_layout_width:
            return
        self._equalized_layout_width = layout_width

        minimum_cell_width = self._card_size.width() + LAYOUT.space_md
        column_count = max(1, layout_width // minimum_cell_width)
        cell_width = max(self._card_size.width(), layout_width // column_count)
        self._equalized_cell_width = cell_width
        target = self._cell_size(cell_width)
        column_count_changed = column_count != self._equalized_column_count
        self._equalized_column_count = column_count

        batch_size_changed = False
        if self.layoutMode() is QListView.LayoutMode.Batched:
            if self._batch_item_budget is None:
                self._batch_item_budget = self.batchSize()
            batch_rows = max(1, self._batch_item_budget // column_count)
            aligned_batch_size = batch_rows * column_count
            batch_size_changed = aligned_batch_size != self.batchSize()
            if batch_size_changed:
                # Qt begins each batch on a fresh visual row. Ending batches on a
                # complete row prevents a short row at every batch boundary.
                self.setBatchSize(aligned_batch_size)

        expected_grid_size = QSize() if self._sectioned_layout else target
        grid_size_changed = expected_grid_size != self.gridSize()
        if grid_size_changed:
            self.setGridSize(expected_grid_size)
        if grid_size_changed or column_count_changed or batch_size_changed:
            # Fixed resize mode avoids unconditional whole-model churn. Force the
            # visible batch to catch up only when its geometry actually changed.
            self.doItemsLayout()

    def _cell_size(self, width: int) -> QSize:
        return QSize(width, self._card_size.height() + LAYOUT.space_xs)


__all__ = ["EqualizedGridView"]
