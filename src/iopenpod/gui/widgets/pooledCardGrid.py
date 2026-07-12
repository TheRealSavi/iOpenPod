from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QWidget

from ..styles import Metrics
from .gridItem import GridImage, GridItem, GridItemModel

if TYPE_CHECKING:
    from iopenpod.application.services import SettingsService

_ROW_BUFFER = 2
_SCROLL_THROTTLE_MS = 16


@dataclass(frozen=True)
class PooledWidgetState:
    """Tracks which record is currently rendered by a pooled widget."""

    record_index: int
    record_identity: Hashable


_UNSET = object()


class PooledGridView(QFrame):
    """Keyed, pooled grid shared by every media browser."""

    currentIndexChanged = pyqtSignal(int)
    visibleIndicesChanged = pyqtSignal(object)
    itemActivated = pyqtSignal(object, int)
    checkedChanged = pyqtSignal(int, bool)
    contextRequested = pyqtSignal(object, int, QPoint)

    def __init__(
        self,
        *,
        checkable: bool = False,
        settings_service: SettingsService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._checkable = checkable
        self._settings_service = settings_service
        self._record_index_by_key: dict[Hashable, int] = {}
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
            self._record_index_by_key.clear()

        self.setMinimumHeight(0)
        self.visibleIndicesChanged.emit(tuple())

    def count(self) -> int:
        return len(self._viewport_records)

    def currentIndex(self) -> int:
        return self._current_index

    def setRecords(
        self,
        records: Sequence[GridItemModel],
        *,
        reset_scroll: bool = True,
        preserve_selection: bool = True,
        fallback_index: int = -1,
    ) -> None:
        keys = [self._record_identity(record) for record in records]
        if len(keys) != len(set(keys)):
            raise ValueError("Pooled grid record keys must be unique")
        self._record_index_by_key = {key: index for index, key in enumerate(keys)}
        self._set_viewport_records(
            records,
            reset_scroll=reset_scroll,
            preserve_selection=preserve_selection,
            fallback_index=fallback_index,
        )

    def recordAt(self, index: int) -> GridItemModel | None:
        record = self._record_for_index(index)
        return record if isinstance(record, GridItemModel) else None

    def setRecordArtwork(
        self,
        key: Hashable,
        image: GridImage | None,
        *,
        dominant_color: tuple[int, int, int] | None | object = _UNSET,
        album_colors: dict[str, Any] | None | object = _UNSET,
    ) -> None:
        index = self._record_index_by_key.get(key)
        if index is None:
            return
        record = self.recordAt(index)
        if record is None:
            return
        record.image = image
        if dominant_color is not _UNSET:
            record.dominant_color = cast(
                tuple[int, int, int] | None,
                dominant_color,
            )
        if album_colors is not _UNSET:
            record.album_colors = cast(dict[str, Any] | None, album_colors)
        widget = self._visible_widgets.get(index)
        if isinstance(widget, GridItem):
            widget.applyImageResult(
                image,
                record.dominant_color,
                record.album_colors,
            )

    def setRecordPixmap(
        self,
        key: Hashable,
        pixmap,
        *,
        dominant_color: tuple[int, int, int] | None | object = _UNSET,
    ) -> None:
        """Compatibility alias for photo-browser callers."""

        self.setRecordArtwork(
            key,
            pixmap,
            dominant_color=dominant_color,
        )

    def setRecordChecked(self, key: Hashable, checked: bool) -> None:
        index = self._record_index_by_key.get(key)
        if index is None:
            return
        record = self.recordAt(index)
        if record is None:
            return
        record.checked = bool(checked)
        widget = self._visible_widgets.get(index)
        if isinstance(widget, GridItem):
            widget.setChecked(record.checked)

    def setAllRecordsChecked(self, checked: bool) -> None:
        for record in self._viewport_records:
            if isinstance(record, GridItemModel):
                record.checked = bool(checked)
        for index, widget in self._visible_widgets.items():
            record = self.recordAt(index)
            if isinstance(widget, GridItem) and record is not None:
                widget.setChecked(record.checked)

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
        if self._scroll_area is None:
            parent = self.parentWidget()
            while parent is not None:
                if isinstance(parent, QScrollArea):
                    self.attachScrollArea(parent)
                    break
                parent = parent.parentWidget()
        self._schedule_viewport_refresh(force=True)

    def _set_viewport_records(
        self,
        records: Sequence[Any],
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
        # Keys preserve selection across refreshes, but a same-key record may
        # carry new title, check state, or artwork and must be rebound.
        self._bound_widget_state.clear()

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
        margin = int(getattr(Metrics, "GRID_MARGIN_Y", Metrics.GRID_SPACING))
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
        margin = int(getattr(Metrics, "GRID_MARGIN_X", Metrics.GRID_SPACING))
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
        base_margin = int(getattr(Metrics, "GRID_MARGIN_X", Metrics.GRID_SPACING))
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

    def refresh_artwork_appearance(self) -> None:
        rounded = self._rounded_artwork_enabled()
        for widget in list(self._visible_widgets.values()):
            if isinstance(widget, GridItem):
                widget.set_rounded_artwork(rounded)

    def _rounded_artwork_enabled(self) -> bool:
        if self._settings_service is None:
            return False
        try:
            return bool(
                self._settings_service.get_effective_settings().rounded_artwork
            )
        except Exception:
            return False

    def _record_identity(self, record: Any) -> Hashable:
        key = getattr(record, "key", None)
        return cast(Hashable, key if key is not None else id(record))

    def _create_pooled_widget(self) -> GridItem:
        return GridItem(checkable=self._checkable)

    def _connect_widget(self, widget: QWidget) -> None:
        if not isinstance(widget, GridItem):
            return
        widget.clicked.connect(lambda w=widget: self._on_item_clicked(w))
        widget.context_requested.connect(
            lambda global_pos, w=widget: self._on_item_context_requested(
                w,
                global_pos,
            )
        )
        if self._checkable:
            widget.checked_changed.connect(
                lambda checked, w=widget: self._on_item_checked(w, checked)
            )

    def _bind_widget(self, widget: QWidget, record_index: int, record: Any) -> None:
        if not isinstance(widget, GridItem) or not isinstance(record, GridItemModel):
            return
        widget.set_rounded_artwork(self._rounded_artwork_enabled())
        widget.setModel(record)

    def _apply_widget_selection(self, widget: QWidget, selected: bool) -> None:
        if isinstance(widget, GridItem):
            widget.setSelected(selected)

    def _on_item_clicked(self, widget: GridItem) -> None:
        record_index = self._record_index_for_widget(widget)
        if record_index is None:
            return
        self.setCurrentIndex(record_index)
        record = self._record_for_index(record_index)
        if record is not None:
            self.itemActivated.emit(self._record_identity(record), record_index)

    def _on_item_context_requested(
        self,
        widget: GridItem,
        global_pos: QPoint,
    ) -> None:
        record_index = self._record_index_for_widget(widget)
        if record_index is None:
            return
        record = self._record_for_index(record_index)
        if record is None:
            return
        self.setCurrentIndex(record_index)
        self.contextRequested.emit(
            self._record_identity(record),
            record_index,
            global_pos,
        )

    def _on_item_checked(self, widget: GridItem, checked: bool) -> None:
        record_index = self._record_index_for_widget(widget)
        if record_index is None:
            return
        record = self.recordAt(record_index)
        if record is None:
            return
        record.checked = checked
        self.checkedChanged.emit(record_index, checked)

    def _on_widget_released(self, widget: QWidget) -> None:
        """Hook for subclasses to clear transient widget state when recycled."""

    def _after_viewport_refresh(self) -> None:
        """Hook called after visible widgets have been refreshed."""


# Compatibility name for callers that imported the former abstract base.
PooledCardGrid = PooledGridView
