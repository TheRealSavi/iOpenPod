from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QSpinBox, QTableView, QTabWidget

from iopenpod.application.database_storage import (
    DatabaseStorageFieldInspection,
    DatabaseStorageFieldValue,
)
from iopenpod.gui.styles import Colors, _parse_color
from iopenpod.gui.widgets import databaseStorageInspectionDialog


def test_field_size_summary_and_histogram_use_the_stored_byte_sizes() -> None:
    summary = databaseStorageInspectionDialog.FieldSizeSummary.from_sizes([10, 20, 30, 40, 50])
    histogram = databaseStorageInspectionDialog.automatically_binned_histogram([10, 20, 30, 40, 50])

    assert summary is not None
    assert summary.minimum == 10
    assert summary.first_quartile == 20
    assert summary.median == 30
    assert summary.third_quartile == 40
    assert summary.maximum == 50
    assert sum(bin_data.count for bin_data in histogram) == 5


def test_chart_theme_colors_support_css_rgba_values() -> None:
    color = _parse_color(Colors.ACCENT_MUTED)

    assert color.isValid()
    assert color.alpha() > 0


def test_field_inspector_shows_stats_and_filters_values_by_byte_count(qtbot) -> None:
    dialog = databaseStorageInspectionDialog.DatabaseStorageFieldInspectorDialog(
        10,
        "Lyrics",
    )
    qtbot.addWidget(dialog)
    dialog.load_inspection(
        DatabaseStorageFieldInspection(
            10,
            (
                DatabaseStorageFieldValue("small", 4),
                DatabaseStorageFieldValue("middle", 12),
                DatabaseStorageFieldValue("large", 20),
            ),
        )
    )

    tabs = dialog.findChild(QTabWidget, "databaseStorageInspectionTabs")
    table = dialog.findChild(QTableView, "databaseStorageInspectionValuesTable")
    minimum = dialog.findChild(QSpinBox, "databaseStorageInspectionMinimumSize")
    truncate_button = dialog.findChild(QPushButton, "databaseStorageInspectionTruncateButton")

    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == ["Stats", "Values"]
    assert table is not None
    table_model = table.model()
    assert table_model is not None
    assert table_model.rowCount() == 3
    assert table_model.index(0, 1).data() == "20 bytes"
    table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    assert table_model.index(0, 1).data() == "4 bytes"
    table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    assert minimum is not None
    minimum.setValue(12)
    minimum.setFocus()
    with qtbot.waitSignal(minimum.editingFinished):
        qtbot.keyClick(minimum, Qt.Key.Key_Return)
    assert table_model.rowCount() == 1
    assert table_model.index(0, 2).data() == "large"
    assert truncate_button is not None


def test_field_inspector_applies_spinbox_filter_when_enter_is_pressed(qtbot) -> None:
    dialog = databaseStorageInspectionDialog.DatabaseStorageFieldInspectorDialog(
        10,
        "Lyrics",
    )
    qtbot.addWidget(dialog)
    dialog.load_inspection(
        DatabaseStorageFieldInspection(
            10,
            (
                DatabaseStorageFieldValue("small", 4),
                DatabaseStorageFieldValue("middle", 12),
                DatabaseStorageFieldValue("large", 20),
            ),
        )
    )
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    qtbot.waitUntil(dialog.isVisible)

    table = dialog.findChild(QTableView, "databaseStorageInspectionValuesTable")
    minimum = dialog.findChild(QSpinBox, "databaseStorageInspectionMinimumSize")

    assert table is not None
    assert minimum is not None
    table_model = table.model()
    assert table_model is not None
    for _ in range(5):
        minimum.stepUp()
    assert table_model.rowCount() == 3

    minimum.setFocus()
    with qtbot.waitSignal(minimum.editingFinished):
        qtbot.keyClick(minimum, Qt.Key.Key_Return)
    assert table_model.rowCount() == 2
    assert dialog.isVisible()
