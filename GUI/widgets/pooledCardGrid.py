from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QEvent, QObject, QRect, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QWidget

from ..styles import Metrics

_ROW_BUFFER = 2
_SCROLL_THROTTLE_MS = 16


@dataclass(frozen=True)
class PooledWidgetState:
    """Tracks which record is currently rendered by a pooled widget."""

    record_index: int
    record_identity: Hashable


class PooledCardGrid(QFrame):
    """Generic pooled card grid backed by a QScrollArea viewport."""

    currentIndexChanged = pyqtSignal(int)
    visibleIndicesChanged = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.gridItems: list[QWidget] = []
        self.columnCount = 1
        self._load_id = 0
        self._current_index = -1

        self._scroll_area: QScrollArea | None = None
        self._refresh_scheduled = False
        self._refresh_force = False
        self._last_view_state: tuple[int, int, int, int] | None = None

        self._viewport_records: list[Any] = []
        self._widget_pool: list[QWidget] = []
        self._visible_widgets: dict[int, QWidget] = {}
        self._bound_widget_state: dict[QWidget, PooledWidgetState] = {}

        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def attachScrollArea(self, scroll_area: QScrollArea | None) -> None:
        if self._scroll_area is scroll_area:
            return

        if self._scroll_area is not None:
            old_bar = self._scroll_area.verticalScrollBar()
            try:
                if old_bar is not None:
                    old_bar.valueChanged.disconnect(self._on_scroll_changed)
            except Exception:
                pass

            old_viewport = self._scroll_area.viewport()
            try:
                if old_viewport is not None:
                    old_viewport.removeEventFilter(self)
            except Exception:
                pass

        self._scroll_area = scroll_area
        if scroll_area is None:
            return

        bar = scroll_area.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(self._on_scroll_changed)

        viewport = scroll_area.viewport()
        if viewport is not None:
            viewport.installEventFilter(self)

        self._schedule_viewport_refresh(force=True)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if (
            self._scroll_area is not None
            and a0 is self._scroll_area.viewport()
            and a1 is not None
            and a1.type() in (QEvent.Type.Resize, QEvent.Type.Show)
        ):
            self._schedule_viewport_refresh(force=True)
        return super().eventFilter(a0, a1)

    def rearrangeGrid(self) -> None:
        self._schedule_viewport_refresh(force=True)

    def clearGrid(self, preserve_all_items: bool = False) -> None:
        self._load_id += 1
        self._recycle_all_visible_widgets()
        self._destroy_pool_widgets()
        self._last_view_state = None
        self.columnCount = 1
        self.gridItems = []
        self._set_current_index_internal(-1, emit_signal=False)

        if not preserve_all_items:
            self._viewport_records = []

        self.setMinimumHeight(0)
        self.visibleIndicesChanged.emit(tuple())

    def count(self) -> int:
        return len(self._viewport_records)

    def currentIndex(self) -> int:
        return self._current_index

    def visibleIndices(self) -> tuple[int, ...]:
        return tuple(sorted(self._visible_widgets))

    def setCurrentIndex(self, index: int) -> None:
        normalized = index if 0 <= index < len(self._viewport_records) else -1
        self._set_current_index_internal(normalized, emit_signal=True)

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        self._schedule_viewport_refresh(force=True)

    def showEvent(self, a0) -> None:
        super().showEvent(a0)
        self._schedule_viewport_refresh(force=True)

    def _set_viewport_records(
        self,
        records: list[Any],
        *,
        reset_scroll: bool,
        preserve_selection: bool = False,
        fallback_index: int = -1,
    ) -> None:
        selected_identity: Hashable | None = None
        if preserve_selection and 0 <= self._current_index < len(self._viewport_records):
            selected_identity = self._record_identity(
                self._viewport_records[self._current_index]
            )

        self._viewport_records = list(records)
        self._load_id += 1
        self._last_view_state = None

        if reset_scroll and self._scroll_area is not None:
            bar = self._scroll_area.verticalScrollBar()
            if bar is not None:
                bar.setValue(0)

        next_index = -1
        if selected_identity is not None:
            next_index = self._find_index_by_identity(selected_identity)
        if next_index < 0 and 0 <= fallback_index < len(self._viewport_records):
            next_index = fallback_index

        self._set_current_index_internal(next_index, emit_signal=False)
        self._schedule_viewport_refresh(force=True)
        self.currentIndexChanged.emit(self._current_index)

    def _find_index_by_identity(self, identity: Hashable) -> int:
        for index, record in enumerate(self._viewport_records):
            if self._record_identity(record) == identity:
                return index
        return -1

    def _set_current_index_internal(self, index: int, *, emit_signal: bool) -> None:
        if self._current_index == index:
            return
        self._current_index = index
        self._sync_visible_selection()
        if emit_signal:
            self.currentIndexChanged.emit(index)

    def _sync_visible_selection(self) -> None:
        for record_index, widget in self._visible_widgets.items():
            self._apply_widget_selection(widget, record_index == self._current_index)

    def _record_for_index(self, index: int) -> Any | None:
        if 0 <= index < len(self._viewport_records):
            return self._viewport_records[index]
        return None

    def _record_index_for_widget(self, widget: QWidget) -> int | None:
        state = self._bound_widget_state.get(widget)
        return state.record_index if state is not None else None

    def _schedule_viewport_refresh(self, *, force: bool = False) -> None:
        if force:
            self._refresh_force = True
            self._last_view_state = None
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        QTimer.singleShot(0 if force else _SCROLL_THROTTLE_MS, self._refresh_viewport)

    def _on_scroll_changed(self, _value: int) -> None:
        self._schedule_viewport_refresh()

    def _refresh_viewport(self) -> None:
        self._refresh_scheduled = False

        width = self.width()
        if width <= 0:
            self._schedule_viewport_refresh(force=True)
            return

        columns = self._compute_columns(width)
        self.columnCount = columns

        count = len(self._viewport_records)
        row_pitch = Metrics.GRID_ITEM_H + Metrics.GRID_SPACING
        margin = Metrics.GRID_SPACING
        total_rows = (count + columns - 1) // columns if count else 0
        total_height = (
            margin * 2
            + total_rows * Metrics.GRID_ITEM_H
            + max(0, total_rows - 1) * Metrics.GRID_SPACING
        )
        self.setMinimumHeight(total_height)

        if count == 0:
            self._recycle_all_visible_widgets()
            self.gridItems = []
            self._refresh_force = False
            self._last_view_state = (0, 0, columns, 0)
            self.visibleIndicesChanged.emit(tuple())
            self._after_viewport_refresh()
            return

        scroll_value, viewport_height = self._current_scroll_state()
        if viewport_height <= 0:
            self._schedule_viewport_refresh(force=True)
            return

        start_index, end_index = self._compute_visible_range(
            count=count,
            columns=columns,
            scroll_value=scroll_value,
            viewport_height=viewport_height,
            margin=margin,
            row_pitch=row_pitch,
            row_buffer=_ROW_BUFFER,
        )

        view_state = (start_index, end_index, columns, count)
        if self._last_view_state == view_state and not self._refresh_force:
            return

        self._last_view_state = view_state
        self._refresh_force = False

        needed_indices = set(range(start_index, end_index))
        for index in list(self._visible_widgets.keys()):
            if index not in needed_indices:
                self._release_widget(index)

        for index in range(start_index, end_index):
            record = self._viewport_records[index]
            widget = self._visible_widgets.get(index)
            if widget is None:
                widget = self._acquire_widget()
                self._visible_widgets[index] = widget

            state = self._bound_widget_state.get(widget)
            identity = self._record_identity(record)
            if (
                state is None
                or state.record_index != index
                or state.record_identity != identity
            ):
                self._bind_widget(widget, index, record)
                self._bound_widget_state[widget] = PooledWidgetState(
                    record_index=index,
                    record_identity=identity,
                )

            row = index // columns
            col = index % columns
            x = self._row_x_layout(
                width=width,
                column_count=columns,
                column_index=col,
            )
            y = margin + row * (Metrics.GRID_ITEM_H + Metrics.GRID_SPACING)
            widget.setGeometry(QRect(x, y, Metrics.GRID_ITEM_W, Metrics.GRID_ITEM_H))
            self._apply_widget_selection(widget, index == self._current_index)
            widget.show()

        ordered_indices = sorted(self._visible_widgets)
        self.gridItems = [self._visible_widgets[index] for index in ordered_indices]
        self.visibleIndicesChanged.emit(tuple(ordered_indices))
        self._after_viewport_refresh()

    def _current_scroll_state(self) -> tuple[int, int]:
        scroll_value = 0
        viewport_height = self.height()
        if self._scroll_area is not None:
            viewport = self._scroll_area.viewport()
            scroll_bar = self._scroll_area.verticalScrollBar()
            if viewport is not None and scroll_bar is not None:
                scroll_value = scroll_bar.value()
                viewport_height = viewport.height()
        return scroll_value, viewport_height

    @staticmethod
    def _compute_columns(width: int) -> int:
        margin = Metrics.GRID_SPACING
        usable = max(1, width - (margin * 2))
        cell = Metrics.GRID_ITEM_W + Metrics.GRID_SPACING
        return max(1, (usable + Metrics.GRID_SPACING) // cell)

    @staticmethod
    def _row_x_layout(
        *,
        width: int,
        column_count: int,
        column_index: int,
    ) -> int:
        base_margin = Metrics.GRID_SPACING
        base_gap = Metrics.GRID_SPACING

        if column_count <= 0:
            return base_margin

        inner_width = max(0, width - (base_margin * 2))
        min_content_width = (
            column_count * Metrics.GRID_ITEM_W
            + max(0, column_count - 1) * base_gap
        )
        extra_width = max(0, inner_width - min_content_width)

        edge_padding = base_margin + (extra_width / (column_count * 2))
        gap = base_gap + (extra_width / column_count) if column_count > 1 else 0.0
        return int(round(edge_padding + column_index * (Metrics.GRID_ITEM_W + gap)))

    @staticmethod
    def _compute_visible_range(
        *,
        count: int,
        columns: int,
        scroll_value: int,
        viewport_height: int,
        margin: int,
        row_pitch: int,
        row_buffer: int,
    ) -> tuple[int, int]:
        if count <= 0:
            return 0, 0

        total_rows = (count + columns - 1) // columns
        first_row = max(0, (scroll_value - margin) // row_pitch)
        last_row = min(
            total_rows - 1,
            (scroll_value + viewport_height - margin) // row_pitch,
        )
        first_row = max(0, first_row - row_buffer)
        last_row = min(total_rows - 1, last_row + row_buffer)
        start_index = first_row * columns
        end_index = min(count, (last_row + 1) * columns)
        return start_index, end_index

    def _acquire_widget(self) -> QWidget:
        if self._widget_pool:
            widget = self._widget_pool.pop()
            widget.setParent(self)
            return widget

        widget = self._create_pooled_widget()
        widget.setParent(self)
        self._connect_widget(widget)
        return widget

    def _release_widget(self, index: int) -> None:
        widget = self._visible_widgets.pop(index, None)
        if widget is None:
            return
        widget.hide()
        self._apply_widget_selection(widget, False)
        self._bound_widget_state.pop(widget, None)
        self._on_widget_released(widget)
        self._widget_pool.append(widget)

    def _recycle_all_visible_widgets(self) -> None:
        for index in list(self._visible_widgets.keys()):
            self._release_widget(index)

    def _destroy_pool_widgets(self) -> None:
        widgets = list(dict.fromkeys(self._widget_pool))
        self._widget_pool.clear()
        self._bound_widget_state.clear()
        for widget in widgets:
            widget.hide()
            widget.deleteLater()

    def _record_identity(self, record: Any) -> Hashable:
        raise NotImplementedError

    def _create_pooled_widget(self) -> QWidget:
        raise NotImplementedError

    def _connect_widget(self, widget: QWidget) -> None:
        """Hook for subclasses to connect widget signals once on creation."""

    def _bind_widget(self, widget: QWidget, record_index: int, record: Any) -> None:
        raise NotImplementedError

    def _apply_widget_selection(self, widget: QWidget, selected: bool) -> None:
        """Hook for subclasses whose widgets have selected-state visuals."""

    def _on_widget_released(self, widget: QWidget) -> None:
        """Hook for subclasses to clear transient widget state when recycled."""

    def _after_viewport_refresh(self) -> None:
        """Hook called after visible widgets have been refreshed."""
