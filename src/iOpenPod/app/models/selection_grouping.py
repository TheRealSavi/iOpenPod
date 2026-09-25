"""Collapsible selection-state sections for one flat Qt item model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import overload

from PySide6.QtCore import (
    QAbstractItemModel,
    QAbstractProxyModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)


class SelectionGroup(StrEnum):
    """Stable selection sections shown by Host Library card views."""

    SELECTED = "selected"
    MIXED = "mixed"
    DESELECTED = "deselected"


class SelectionGroupingRole(IntEnum):
    """Presentation roles exposed only for synthetic section rows."""

    IS_HEADER = Qt.ItemDataRole.UserRole.value + 1_000
    GROUP = Qt.ItemDataRole.UserRole.value + 1_001
    EXPANDED = Qt.ItemDataRole.UserRole.value + 1_002
    ITEM_COUNT = Qt.ItemDataRole.UserRole.value + 1_003


@dataclass(frozen=True, slots=True)
class _HeaderRow:
    group: SelectionGroup
    item_count: int


@dataclass(frozen=True, slots=True)
class _ItemRow:
    source_row: int


type _PresentedRow = _HeaderRow | _ItemRow
type _Index = QModelIndex | QPersistentModelIndex

_GROUP_ORDER = (
    SelectionGroup.SELECTED,
    SelectionGroup.MIXED,
    SelectionGroup.DESELECTED,
)
_ROOT_INDEX = QModelIndex()


class SelectionGroupingProxyModel(QAbstractProxyModel):
    """Insert collapsible section rows without creating per-item widgets."""

    def __init__(
        self,
        source: QAbstractItemModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._grouping_enabled = False
        self._expanded: dict[SelectionGroup, bool] = dict.fromkeys(_GROUP_ORDER, True)
        self._rows: tuple[_PresentedRow, ...] = ()
        self._proxy_rows_by_source_row: dict[int, int] = {}
        self.setSourceModel(source)
        source.modelReset.connect(self._source_changed)
        source.layoutChanged.connect(self._source_changed)
        source.rowsInserted.connect(self._source_changed)
        source.rowsRemoved.connect(self._source_changed)
        source.rowsMoved.connect(self._source_changed)
        source.dataChanged.connect(self._source_changed)
        self._rebuild_rows()

    @property
    def grouping_enabled(self) -> bool:
        return self._grouping_enabled

    def set_grouping_enabled(self, enabled: bool) -> None:
        """Show or remove selection section rows while preserving collapse state."""

        if enabled == self._grouping_enabled:
            return
        self.beginResetModel()
        self._grouping_enabled = enabled
        self._rebuild_rows()
        self.endResetModel()

    def retranslate(self) -> None:
        """Refresh translated section labels after a language change."""

        if not self._rows:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._rows) - 1, 0),
            [
                Qt.ItemDataRole.DisplayRole.value,
                Qt.ItemDataRole.AccessibleTextRole.value,
                Qt.ItemDataRole.ToolTipRole.value,
            ],
        )

    def is_expanded(self, group: SelectionGroup) -> bool:
        return self._expanded[group]

    def set_expanded(self, group: SelectionGroup, expanded: bool) -> None:
        if expanded == self._expanded[group]:
            return
        self.beginResetModel()
        self._expanded[group] = expanded
        self._rebuild_rows()
        self.endResetModel()

    def toggle_group(self, group: SelectionGroup) -> None:
        self.set_expanded(group, not self.is_expanded(group))

    def first_item_index(self) -> QModelIndex:
        """Return the first visible source item, skipping synthetic headers."""

        for row, presented in enumerate(self._rows):
            if isinstance(presented, _ItemRow):
                return self.index(row, 0)
        return QModelIndex()

    def mapToSource(
        self,
        proxy_index: _Index,
    ) -> QModelIndex:
        if not proxy_index.isValid() or not 0 <= proxy_index.row() < len(self._rows):
            return QModelIndex()
        presented = self._rows[proxy_index.row()]
        if isinstance(presented, _HeaderRow):
            return QModelIndex()
        source = self.sourceModel()
        return source.index(presented.source_row, proxy_index.column())

    def mapFromSource(
        self,
        source_index: _Index,
    ) -> QModelIndex:
        if not source_index.isValid() or source_index.model() is not self.sourceModel():
            return QModelIndex()
        proxy_row = self._proxy_rows_by_source_row.get(source_index.row())
        if proxy_row is None:
            return QModelIndex()
        return self.index(proxy_row, source_index.column())

    def index(
        self,
        row: int,
        column: int,
        parent: _Index = _ROOT_INDEX,
    ) -> QModelIndex:
        if parent.isValid() or not self.hasIndex(row, column, _ROOT_INDEX):
            return QModelIndex()
        return self.createIndex(row, column)

    @overload
    def parent(self) -> QObject | None: ...

    @overload
    def parent(self, index: _Index) -> QModelIndex: ...

    def parent(self, index: _Index | None = None) -> QObject | QModelIndex | None:
        if index is None:
            return super().parent()
        return QModelIndex()

    def rowCount(
        self,
        parent: _Index = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(
        self,
        parent: _Index = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else self.sourceModel().columnCount()

    def data(
        self,
        index: _Index,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        presented = self._rows[index.row()]
        if isinstance(presented, _ItemRow):
            return self.sourceModel().data(self.mapToSource(index), role)
        if role == SelectionGroupingRole.IS_HEADER:
            return True
        if role == SelectionGroupingRole.GROUP:
            return presented.group.value
        if role == SelectionGroupingRole.EXPANDED:
            return self._expanded[presented.group]
        if role == SelectionGroupingRole.ITEM_COUNT:
            return presented.item_count
        if role == Qt.ItemDataRole.DisplayRole:
            return self._group_label(presented.group)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            state = (
                self.tr("expanded")
                if self._expanded[presented.group]
                else self.tr("collapsed")
            )
            return (
                self.tr("%1, %n items, %2", None, presented.item_count)
                .replace("%1", self._group_label(presented.group))
                .replace("%2", state)
            )
        if role == Qt.ItemDataRole.ToolTipRole:
            action = (
                self.tr("Collapse")
                if self._expanded[presented.group]
                else self.tr("Expand")
            )
            return (
                self.tr("%1 %2 group")
                .replace("%1", action)
                .replace("%2", self._group_label(presented.group))
            )
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return None

    def setData(
        self,
        index: _Index,
        value: object,
        role: int = Qt.ItemDataRole.EditRole.value,
    ) -> bool:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return False
        presented = self._rows[index.row()]
        if isinstance(presented, _HeaderRow):
            if role != SelectionGroupingRole.EXPANDED:
                return False
            self.set_expanded(presented.group, bool(value))
            return True
        return self.sourceModel().setData(self.mapToSource(index), value, role)

    def flags(
        self,
        index: _Index,
    ) -> Qt.ItemFlag:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return Qt.ItemFlag.NoItemFlags
        if isinstance(self._rows[index.row()], _HeaderRow):
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return self.sourceModel().flags(self.mapToSource(index))

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object:
        return self.sourceModel().headerData(section, orientation, role)

    def _source_changed(self, *_args: object) -> None:
        self.beginResetModel()
        self._rebuild_rows()
        self.endResetModel()

    def _rebuild_rows(self) -> None:
        source = self.sourceModel()
        buckets: dict[SelectionGroup, list[int]] = {group: [] for group in _GROUP_ORDER}
        for source_row in range(source.rowCount()):
            index = source.index(source_row, 0)
            group = _group_for_check_state(
                source.data(index, Qt.ItemDataRole.CheckStateRole)
            )
            buckets[group].append(source_row)

        rows: list[_PresentedRow] = []
        if self._grouping_enabled:
            for group in _GROUP_ORDER:
                source_rows = buckets[group]
                if not source_rows:
                    continue
                rows.append(_HeaderRow(group, len(source_rows)))
                if self._expanded[group]:
                    rows.extend(_ItemRow(source_row) for source_row in source_rows)
        else:
            rows.extend(_ItemRow(source_row) for source_row in range(source.rowCount()))
        self._rows = tuple(rows)
        self._proxy_rows_by_source_row = {
            presented.source_row: proxy_row
            for proxy_row, presented in enumerate(self._rows)
            if isinstance(presented, _ItemRow)
        }

    def _group_label(self, group: SelectionGroup) -> str:
        return {
            SelectionGroup.SELECTED: self.tr("Selected"),
            SelectionGroup.MIXED: self.tr("Mixed"),
            SelectionGroup.DESELECTED: self.tr("Deselected"),
        }[group]


def _group_for_check_state(value: object) -> SelectionGroup:
    if value in {Qt.CheckState.Checked, Qt.CheckState.Checked.value}:
        return SelectionGroup.SELECTED
    if value in {
        Qt.CheckState.PartiallyChecked,
        Qt.CheckState.PartiallyChecked.value,
    }:
        return SelectionGroup.MIXED
    return SelectionGroup.DESELECTED


__all__ = [
    "SelectionGroup",
    "SelectionGroupingProxyModel",
    "SelectionGroupingRole",
]
