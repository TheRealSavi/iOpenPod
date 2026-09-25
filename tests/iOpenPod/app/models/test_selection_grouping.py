"""Tests for collapsible selection-state model sections."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel

from iOpenPod.app.models.selection_grouping import (
    SelectionGroup,
    SelectionGroupingProxyModel,
    SelectionGroupingRole,
)


def test_selection_grouping_inserts_ordered_headers_and_collapses_items() -> None:
    source = QStandardItemModel()
    source.appendRow(_item("Selected A", Qt.CheckState.Checked))
    source.appendRow(_item("Deselected", Qt.CheckState.Unchecked))
    source.appendRow(_item("Mixed", Qt.CheckState.PartiallyChecked))
    source.appendRow(_item("Selected B", Qt.CheckState.Checked))
    grouped = SelectionGroupingProxyModel(source)

    grouped.set_grouping_enabled(True)

    assert _presented_rows(grouped) == (
        ("header", "Selected"),
        ("item", "Selected A"),
        ("item", "Selected B"),
        ("header", "Mixed"),
        ("item", "Mixed"),
        ("header", "Deselected"),
        ("item", "Deselected"),
    )
    assert grouped.index(0, 0).data(SelectionGroupingRole.ITEM_COUNT) == 2
    assert grouped.mapFromSource(source.index(3, 0)).row() == 2

    grouped.toggle_group(SelectionGroup.SELECTED)

    assert grouped.index(0, 0).data(SelectionGroupingRole.EXPANDED) is False
    assert not grouped.mapFromSource(source.index(0, 0)).isValid()
    assert _presented_rows(grouped) == (
        ("header", "Selected"),
        ("header", "Mixed"),
        ("item", "Mixed"),
        ("header", "Deselected"),
        ("item", "Deselected"),
    )


def test_selection_grouping_moves_changed_items_and_omits_empty_groups() -> None:
    source = QStandardItemModel()
    source.appendRow(_item("First", Qt.CheckState.Checked))
    source.appendRow(_item("Second", Qt.CheckState.Unchecked))
    grouped = SelectionGroupingProxyModel(source)
    grouped.set_grouping_enabled(True)

    source.item(1).setCheckState(Qt.CheckState.Checked)

    assert _presented_rows(grouped) == (
        ("header", "Selected"),
        ("item", "First"),
        ("item", "Second"),
    )
    assert grouped.index(0, 0).data(SelectionGroupingRole.ITEM_COUNT) == 2
    assert grouped.first_item_index().data() == "First"


def _item(label: str, state: Qt.CheckState) -> QStandardItem:
    item = QStandardItem(label)
    item.setCheckable(True)
    item.setCheckState(state)
    return item


def _presented_rows(
    model: SelectionGroupingProxyModel,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            "header"
            if model.index(row, 0).data(SelectionGroupingRole.IS_HEADER)
            else "item",
            str(model.index(row, 0).data()),
        )
        for row in range(model.rowCount())
    )
