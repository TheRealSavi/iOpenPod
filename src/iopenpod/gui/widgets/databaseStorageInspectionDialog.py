"""Field-level inspection dialog for iPod database storage."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from iopenpod.application import database_storage

from ..styles import (
    FONT_FAMILY,
    MONO_FONT_FAMILY,
    Metrics,
    _parse_color,
    accent_btn_css,
    button_css,
    paint_css,
    table_css,
)

_ROOT_INDEX = QModelIndex()


@dataclass(frozen=True)
class FieldSizeSummary:
    """Five-number summary for the byte counts in one field."""

    minimum: float
    first_quartile: float
    median: float
    third_quartile: float
    maximum: float

    @classmethod
    def from_sizes(cls, sizes: list[int]) -> FieldSizeSummary | None:
        if not sizes:
            return None
        ordered = sorted(sizes)
        return cls(
            minimum=float(ordered[0]),
            first_quartile=_percentile(ordered, 0.25),
            median=_percentile(ordered, 0.5),
            third_quartile=_percentile(ordered, 0.75),
            maximum=float(ordered[-1]),
        )


@dataclass(frozen=True)
class HistogramBin:
    """A size range and the number of values that fit inside it."""

    start: float
    end: float
    count: int


def _percentile(ordered: list[int], percentile: float) -> float:
    position = (len(ordered) - 1) * percentile
    lower = floor(position)
    upper = ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def automatically_binned_histogram(sizes: list[int]) -> tuple[HistogramBin, ...]:
    """Build a bounded Freedman-Diaconis histogram for field byte counts."""

    if not sizes:
        return ()
    minimum = min(sizes)
    maximum = max(sizes)
    if minimum == maximum:
        return (HistogramBin(float(minimum), float(maximum), len(sizes)),)

    summary = FieldSizeSummary.from_sizes(sizes)
    assert summary is not None
    iqr = summary.third_quartile - summary.first_quartile
    if iqr > 0:
        width = 2 * iqr / len(sizes) ** (1 / 3)
        bin_count = ceil((maximum - minimum) / width) if width else 1
    else:
        bin_count = ceil(len(sizes) ** 0.5)
    bin_count = max(1, min(24, bin_count))
    width = (maximum - minimum) / bin_count
    counts = [0] * bin_count
    for size in sizes:
        index = min(bin_count - 1, int((size - minimum) / width))
        counts[index] += 1
    return tuple(
        HistogramBin(
            minimum + index * width,
            maximum if index == bin_count - 1 else minimum + (index + 1) * width,
            count,
        )
        for index, count in enumerate(counts)
    )


class FieldSizeDistributionWidget(QWidget):
    """Compact histogram and box plot rendered without extra dependencies."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sizes: list[int] = []
        self.setMinimumHeight(250)

    def set_sizes(self, sizes: list[int]) -> None:
        self._sizes = list(sizes)
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _parse_color(paint_css("surface.default")))
        if not self._sizes:
            painter.setPen(_parse_color(paint_css("text.tertiary")))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No field values found")
            return

        left_margin = 56
        right_margin = 24
        chart_left = left_margin
        width = max(1, self.width() - left_margin - right_margin)
        histogram_top = 28
        histogram_height = max(70, self.height() // 2 - 40)
        bins = automatically_binned_histogram(self._sizes)
        maximum_count = max(bin.count for bin in bins)
        bin_width = bins[0].end - bins[0].start

        painter.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        painter.setPen(_parse_color(paint_css("text.secondary")))
        painter.drawText(
            chart_left,
            18,
            f"Histogram · {len(bins)} automatic bin{'s' if len(bins) != 1 else ''} · {_byte_label(bin_width)}/bin",
        )
        painter.setPen(QPen(_parse_color(paint_css("border.subtle"))))
        baseline = histogram_top + histogram_height
        painter.drawLine(chart_left, baseline, chart_left + width, baseline)
        painter.drawLine(chart_left, histogram_top, chart_left, baseline)

        tick_count = min(4, maximum_count)
        painter.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_XS))
        for tick_index in range(tick_count + 1):
            count = round(maximum_count * tick_index / tick_count) if tick_count else 0
            tick_y = baseline - histogram_height * tick_index / max(1, tick_count)
            painter.setPen(QPen(_parse_color(paint_css("border.grid"))))
            painter.drawLine(chart_left, int(tick_y), chart_left + width, int(tick_y))
            painter.setPen(_parse_color(paint_css("text.tertiary")))
            text = str(count)
            painter.drawText(
                chart_left - 8 - painter.fontMetrics().horizontalAdvance(text),
                int(tick_y + painter.fontMetrics().ascent() / 2),
                text,
            )

        painter.save()
        painter.translate(14, histogram_top + histogram_height / 2)
        painter.rotate(-90)
        painter.setPen(_parse_color(paint_css("text.tertiary")))
        painter.drawText(-painter.fontMetrics().horizontalAdvance("Occurrences") // 2, 0, "Occurrences")
        painter.restore()

        gap = 3
        bar_area_left = chart_left + 4
        bar_width = max(2, (width - 4 - gap * (len(bins) - 1)) / len(bins))
        for index, bin_data in enumerate(bins):
            height = 0 if maximum_count == 0 else histogram_height * bin_data.count / maximum_count
            left = bar_area_left + index * (bar_width + gap)
            painter.fillRect(
                int(left),
                int(histogram_top + histogram_height - height),
                max(1, int(bar_width)),
                max(1, int(height)),
                _parse_color(paint_css("data.accent.fill")),
            )

        painter.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_XS))
        painter.setPen(_parse_color(paint_css("text.tertiary")))
        painter.drawText(chart_left, histogram_top + histogram_height + 18, _byte_label(min(self._sizes)))
        maximum_text = _byte_label(max(self._sizes))
        painter.drawText(
            chart_left + width - painter.fontMetrics().horizontalAdvance(maximum_text),
            histogram_top + histogram_height + 18,
            maximum_text,
        )

        summary = FieldSizeSummary.from_sizes(self._sizes)
        assert summary is not None
        box_top = histogram_top + histogram_height + 58
        painter.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        painter.setPen(_parse_color(paint_css("text.secondary")))
        painter.drawText(chart_left, box_top - 16, "Box plot")
        scale_min = summary.minimum
        scale_max = summary.maximum

        def x_for(value: float) -> int:
            if scale_min == scale_max:
                return chart_left + width // 2
            return int(chart_left + (value - scale_min) / (scale_max - scale_min) * width)

        center_y = box_top + 24
        painter.setPen(QPen(_parse_color(paint_css("text.secondary")), 2))
        painter.drawLine(x_for(summary.minimum), center_y, x_for(summary.maximum), center_y)
        painter.drawLine(x_for(summary.minimum), center_y - 8, x_for(summary.minimum), center_y + 8)
        painter.drawLine(x_for(summary.maximum), center_y - 8, x_for(summary.maximum), center_y + 8)
        left = x_for(summary.first_quartile)
        right = x_for(summary.third_quartile)
        painter.fillRect(
            left,
            center_y - 14,
            max(2, right - left),
            28,
            _parse_color(paint_css("data.accent.subtle_fill")),
        )
        painter.setPen(QPen(_parse_color(paint_css("data.accent.border")), 2))
        painter.drawRect(left, center_y - 14, max(2, right - left), 28)
        median_x = x_for(summary.median)
        painter.drawLine(median_x, center_y - 14, median_x, center_y + 14)


class _FieldValuesTableModel(QAbstractTableModel):
    """The unfiltered field values shown by the inspection dialog."""

    _HEADERS = ("#", "Size", "Value")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: tuple[database_storage.DatabaseStorageFieldValue, ...] = ()

    def set_values(
        self,
        values: tuple[database_storage.DatabaseStorageFieldValue, ...],
    ) -> None:
        self.beginResetModel()
        self._values = values
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = _ROOT_INDEX) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._values)

    def columnCount(self, parent: QModelIndex = _ROOT_INDEX) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._HEADERS)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):  # type: ignore[override]
        if not index.isValid() or not 0 <= index.row() < len(self._values):
            return None
        value = self._values[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return str(index.row() + 1)
            if index.column() == 1:
                return f"{value.byte_count:,} bytes"
            if index.column() == 2:
                return value.value
        if role == Qt.ItemDataRole.UserRole:
            if index.column() == 0:
                return index.row() + 1
            if index.column() == 1:
                return value.byte_count
            if index.column() == 2:
                return value.value
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 2:
            return value.value
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ):  # type: ignore[override]
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._HEADERS[section] if 0 <= section < len(self._HEADERS) else None
        return None


class _MinimumSizeFilterProxyModel(QSortFilterProxyModel):
    """Filters storage values without mutating the table's source rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum_bytes = 0
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setDynamicSortFilter(True)

    def set_minimum_bytes(self, minimum_bytes: int) -> None:
        value = max(0, int(minimum_bytes))
        if value == self._minimum_bytes:
            return
        self.beginFilterChange()
        self._minimum_bytes = value
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex,
    ) -> bool:  # type: ignore[override]
        model = self.sourceModel()
        if model is None:
            return False
        size_index = model.index(source_row, 1, source_parent)
        byte_count = model.data(size_index, Qt.ItemDataRole.UserRole)
        return isinstance(byte_count, int) and byte_count > self._minimum_bytes


class DatabaseStorageFieldInspectorDialog(QDialog):
    """Inspect one optional field before applying a byte-length limit."""

    truncate_requested = pyqtSignal(int, int)

    def __init__(self, mhod_type: int, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mhod_type = mhod_type
        self._label = label
        self._inspection: database_storage.DatabaseStorageFieldInspection | None = None
        self.setObjectName("databaseStorageFieldInspector")
        self.setWindowTitle(f"Inspect {label}")
        self.setMinimumSize(760, 580)
        self.resize(900, 680)
        self._build_ui()
        self.set_loading()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel(f"Inspect {self._label}", self)
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XL, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {paint_css('text.primary')};")
        root.addWidget(title)

        self.status_label = QLabel(self)
        self.status_label.setObjectName("databaseStorageInspectionStatus")
        self.status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.status_label.setStyleSheet(f"color: {paint_css('text.tertiary')};")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("databaseStorageInspectionTabs")
        self.tabs.addTab(self._build_stats_tab(), "Stats")
        self.tabs.addTab(self._build_values_tab(), "Values")
        root.addWidget(self.tabs, 1)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addStretch(1)
        close_button = QPushButton("Close", self)
        close_button.setObjectName("databaseStorageInspectionCloseButton")
        close_button.setAutoDefault(False)
        close_button.setDefault(False)
        close_button.setStyleSheet(button_css("secondary", "md"))
        close_button.clicked.connect(self.reject)
        controls.addWidget(close_button)
        self.truncate_button = QPushButton("Truncate…", self)
        self.truncate_button.setObjectName("databaseStorageInspectionTruncateButton")
        self.truncate_button.setAutoDefault(False)
        self.truncate_button.setDefault(False)
        self.truncate_button.setStyleSheet(accent_btn_css("md"))
        self.truncate_button.clicked.connect(self._request_truncation)
        controls.addWidget(self.truncate_button)
        root.addLayout(controls)

    def _build_stats_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        self.distribution = FieldSizeDistributionWidget(tab)
        self.distribution.setObjectName("databaseStorageFieldDistribution")
        layout.addWidget(self.distribution, 1)

        summary_frame = QFrame(tab)
        summary_frame.setObjectName("databaseStorageFiveNumberSummary")
        summary_frame.setStyleSheet(
            f"background: {paint_css('surface.default')}; "
            f"border: 1px solid {paint_css('border.subtle')}; "
            f"border-radius: {Metrics.BORDER_RADIUS_SM}px;"
        )
        summary_layout = QFormLayout(summary_frame)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setHorizontalSpacing(20)
        summary_layout.setVerticalSpacing(6)
        self._summary_values: dict[str, QLabel] = {}
        for key, title in (
            ("minimum", "Minimum"),
            ("first_quartile", "First quartile"),
            ("median", "Median"),
            ("third_quartile", "Third quartile"),
            ("maximum", "Maximum"),
        ):
            value = QLabel("—", summary_frame)
            value.setObjectName(f"databaseStorageSummary{key.title().replace('_', '')}")
            value.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
            value.setStyleSheet(f"color: {paint_css('text.primary')};")
            summary_layout.addRow(f"{title}:", value)
            self._summary_values[key] = value
        layout.addWidget(summary_frame)
        return tab

    def _build_values_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(QLabel("Show values larger than", tab))
        self.minimum_size_input = QSpinBox(tab)
        self.minimum_size_input.setObjectName("databaseStorageInspectionMinimumSize")
        self.minimum_size_input.setRange(0, 2**31 - 1)
        self.minimum_size_input.setKeyboardTracking(False)
        self.minimum_size_input.editingFinished.connect(self._apply_minimum_size_filter)
        filter_row.addWidget(self.minimum_size_input)
        filter_row.addWidget(QLabel("bytes", tab))
        filter_row.addStretch(1)
        self.values_count_label = QLabel("", tab)
        self.values_count_label.setObjectName("databaseStorageInspectionValuesCount")
        self.values_count_label.setStyleSheet(f"color: {paint_css('text.tertiary')};")
        filter_row.addWidget(self.values_count_label)
        layout.addLayout(filter_row)

        self._values_model = _FieldValuesTableModel(tab)
        self._values_proxy = _MinimumSizeFilterProxyModel(tab)
        self._values_proxy.setSourceModel(self._values_model)
        self.values_table = QTableView(tab)
        self.values_table.setObjectName("databaseStorageInspectionValuesTable")
        self.values_table.setStyleSheet(table_css().replace("QTableWidget", "QTableView"))
        self.values_table.setModel(self._values_proxy)
        self.values_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.values_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.values_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.values_table.setAlternatingRowColors(True)
        self.values_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.values_table.setSortingEnabled(True)
        vertical_header = self.values_table.verticalHeader()
        if vertical_header is not None:
            vertical_header.hide()
        header = self.values_table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.values_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        layout.addWidget(self.values_table, 1)
        return tab

    def set_loading(self) -> None:
        self.status_label.setText("Loading field values…")
        self.tabs.setEnabled(False)
        self.truncate_button.setEnabled(False)

    def load_inspection(
        self,
        inspection: database_storage.DatabaseStorageFieldInspection,
    ) -> None:
        self._inspection = inspection
        sizes = [value.byte_count for value in inspection.values]
        self.distribution.set_sizes(sizes)
        self.tabs.setEnabled(True)
        self.truncate_button.setEnabled(True)
        if inspection.note:
            self.status_label.setText(inspection.note)
        else:
            self.status_label.setText(f"{len(inspection.values):,} occurrence{'s' if len(inspection.values) != 1 else ''} · {sum(sizes):,} stored bytes")
        summary = FieldSizeSummary.from_sizes(sizes)
        for key, label in self._summary_values.items():
            label.setText("—" if summary is None else _byte_label(getattr(summary, key)))
        self._values_model.set_values(inspection.values)
        self._apply_minimum_size_filter()

    def show_error(self, message: str) -> None:
        self.status_label.setText(message)
        self.tabs.setEnabled(False)
        self.truncate_button.setEnabled(False)

    def _apply_minimum_size_filter(self) -> None:
        self._values_proxy.set_minimum_bytes(self.minimum_size_input.value())
        self.values_count_label.setText(
            f"{self._values_proxy.rowCount():,} of {self._values_model.rowCount():,} values"
        )

    def _request_truncation(self) -> None:
        max_bytes, accepted = QInputDialog.getInt(
            self,
            f"Truncate {self._label}",
            f"Maximum bytes per {self._label} value (0 removes the field):",
            2048,
            0,
            2**31 - 1,
        )
        if accepted:
            self.truncate_requested.emit(self._mhod_type, max_bytes)
            self.accept()


def _byte_label(value: float | int) -> str:
    if float(value).is_integer():
        return f"{int(value):,} bytes"
    return f"{value:,.1f} bytes"
