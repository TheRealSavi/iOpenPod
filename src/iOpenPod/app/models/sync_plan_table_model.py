"""Virtualized Qt projection and filters for one immutable Sync Plan."""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)

if TYPE_CHECKING:
    from iOpenPod.app.models.sync_selection import SyncSelection

_ROOT_INDEX = QModelIndex()
type _ModelIndex = QModelIndex | QPersistentModelIndex


class SyncPlanColumn(IntEnum):
    ACTION = 0
    MEDIA = 1
    NAME = 2
    HOST = 3
    IPOD = 4
    REASON = 5


class SyncPlanRole(IntEnum):
    ITEM = Qt.ItemDataRole.UserRole.value + 1
    SEARCH_TEXT = Qt.ItemDataRole.UserRole.value + 2
    SORT_VALUE = Qt.ItemDataRole.UserRole.value + 3


class SyncPlanTableModel(QAbstractTableModel):
    """Expose Sync Plan items without allocating one widget per row."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._plan = SyncPlan(())
        self._selection: SyncSelection | None = None

    @property
    def plan(self) -> SyncPlan:
        return self._plan

    def replace_plan(
        self,
        plan: SyncPlan | None,
        selection: SyncSelection | None = None,
    ) -> None:
        resolved = SyncPlan(()) if plan is None else plan
        if resolved == self._plan and selection is self._selection:
            return
        if self._selection is not None:
            self._selection.reviewSelectionChanged.disconnect(
                self._review_selection_changed
            )
        self.beginResetModel()
        self._plan = resolved
        self._selection = selection
        self.endResetModel()
        if selection is not None:
            selection.reviewSelectionChanged.connect(self._review_selection_changed)

    def rowCount(self, parent: _ModelIndex = _ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self._plan.items)

    def columnCount(self, parent: _ModelIndex = _ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(SyncPlanColumn)

    def flags(self, index: _ModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if (
            index.isValid()
            and index.column() == SyncPlanColumn.ACTION
            and self._selection is not None
            and self._selection.review_check_state(self._plan.items[index.row()])
            is not None
        ):
            return flags | Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(
        self,
        index: _ModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        if not index.isValid() or not 0 <= index.row() < len(self._plan.items):
            return None
        item = self._plan.items[index.row()]
        column = SyncPlanColumn(index.column())
        if (
            role == Qt.ItemDataRole.CheckStateRole
            and column is SyncPlanColumn.ACTION
            and self._selection is not None
        ):
            return self._selection.review_check_state(item)
        if role == Qt.ItemDataRole.DisplayRole:
            return _display_value(item, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip(item)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return (
                self.tr("%1, %2, %3")
                .replace("%1", _action_label(item.action))
                .replace("%2", _media_label(item.media_kind))
                .replace("%3", item.name)
            )
        if role == SyncPlanRole.ITEM:
            return item
        if role == SyncPlanRole.SEARCH_TEXT:
            return item.search_text
        if role == SyncPlanRole.SORT_VALUE:
            return _sort_value(item, column)
        return None

    def setData(
        self,
        index: _ModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole.value,
    ) -> bool:
        if (
            role != Qt.ItemDataRole.CheckStateRole
            or self._selection is None
            or not index.isValid()
            or not 0 <= index.row() < len(self._plan.items)
            or index.column() != SyncPlanColumn.ACTION
            or value
            not in (
                Qt.CheckState.Checked,
                Qt.CheckState.Unchecked,
                Qt.CheckState.Checked.value,
                Qt.CheckState.Unchecked.value,
            )
        ):
            return False
        return self._selection.set_review_items_checked(
            (self._plan.items[index.row()],),
            value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value),
        )

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        if (
            orientation is not Qt.Orientation.Horizontal
            or role != Qt.ItemDataRole.DisplayRole.value
            or not 0 <= section < len(SyncPlanColumn)
        ):
            return None
        return (
            self.tr("Plan"),
            self.tr("Type"),
            self.tr("Item"),
            self.tr("Host source"),
            self.tr("iPod source"),
            self.tr("Why"),
        )[section]

    def retranslate(self) -> None:
        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal,
            0,
            len(SyncPlanColumn) - 1,
        )
        if self._plan.items:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._plan.items) - 1, len(SyncPlanColumn) - 1),
                [
                    Qt.ItemDataRole.DisplayRole.value,
                    Qt.ItemDataRole.ToolTipRole.value,
                    Qt.ItemDataRole.AccessibleTextRole.value,
                ],
            )

    def _review_selection_changed(self) -> None:
        if not self._plan.items:
            return
        self.dataChanged.emit(
            self.index(0, SyncPlanColumn.ACTION),
            self.index(len(self._plan.items) - 1, SyncPlanColumn.ACTION),
            [Qt.ItemDataRole.CheckStateRole.value],
        )


class SyncPlanFilterModel(QSortFilterProxyModel):
    """Filter one plan by action, media family, and normalized search text."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._actions: frozenset[SyncPlanAction] | None = None
        self._media_kind: SyncPlanMediaKind | None = None
        self._query = ""
        self.setDynamicSortFilter(True)
        self.setSortRole(SyncPlanRole.SORT_VALUE)

    def set_actions(self, actions: frozenset[SyncPlanAction] | None) -> None:
        if actions == self._actions:
            return
        self.beginFilterChange()
        self._actions = actions
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_media_kind(self, media_kind: SyncPlanMediaKind | None) -> None:
        if media_kind is self._media_kind:
            return
        self.beginFilterChange()
        self._media_kind = media_kind
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_query(self, query: str) -> None:
        normalized = query.strip().casefold()
        if normalized == self._query:
            return
        self.beginFilterChange()
        self._query = normalized
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        source = self.sourceModel()
        item = source.index(source_row, 0, source_parent).data(SyncPlanRole.ITEM)
        if not isinstance(item, SyncPlanItem):
            return False
        if self._actions is not None and item.action not in self._actions:
            return False
        if self._media_kind is not None and item.media_kind is not self._media_kind:
            return False
        return not self._query or self._query in item.search_text


def _display_value(
    item: SyncPlanItem,
    column: SyncPlanColumn,
) -> str:
    if column is SyncPlanColumn.ACTION:
        return _action_label(item.action)
    if column is SyncPlanColumn.MEDIA:
        return _media_label(item.media_kind)
    if column is SyncPlanColumn.NAME:
        return item.name if not item.detail else f"{item.name} — {item.detail}"
    if column is SyncPlanColumn.HOST:
        return item.host_path or "—"
    if column is SyncPlanColumn.IPOD:
        return item.ipod_path or "—"
    return _basis_label(item)


def _action_label(action: SyncPlanAction) -> str:
    return {
        SyncPlanAction.ADD: QCoreApplication.translate("SyncPlanTableModel", "Add"),
        SyncPlanAction.UPDATE: QCoreApplication.translate(
            "SyncPlanTableModel", "Update"
        ),
        SyncPlanAction.REMOVE: QCoreApplication.translate(
            "SyncPlanTableModel", "Remove"
        ),
        SyncPlanAction.UNCHANGED: QCoreApplication.translate(
            "SyncPlanTableModel", "In sync"
        ),
        SyncPlanAction.ATTENTION: QCoreApplication.translate(
            "SyncPlanTableModel", "Needs attention"
        ),
    }[action]


def _media_label(kind: SyncPlanMediaKind) -> str:
    return {
        SyncPlanMediaKind.TRACK: QCoreApplication.translate(
            "SyncPlanTableModel", "Track"
        ),
        SyncPlanMediaKind.PHOTO: QCoreApplication.translate(
            "SyncPlanTableModel", "Photo"
        ),
    }[kind]


def _basis_label(item: SyncPlanItem) -> str:
    if item.basis is SyncPlanBasis.HOST_FACTS_CHANGED:
        if item.host_size_changed and item.host_modified_changed:
            return QCoreApplication.translate(
                "SyncPlanTableModel", "Host size and modified time changed"
            )
        if item.host_size_changed:
            return QCoreApplication.translate("SyncPlanTableModel", "Host size changed")
        return QCoreApplication.translate(
            "SyncPlanTableModel", "Host modified time changed"
        )
    return {
        SyncPlanBasis.HOST_ONLY: QCoreApplication.translate(
            "SyncPlanTableModel", "Only in Host Media Library"
        ),
        SyncPlanBasis.IPOD_ONLY: QCoreApplication.translate(
            "SyncPlanTableModel", "Only on iPod"
        ),
        SyncPlanBasis.HOST_FACTS_MATCH: QCoreApplication.translate(
            "SyncPlanTableModel", "Host size and modified time still match"
        ),
        SyncPlanBasis.CONTENT_MATCH: QCoreApplication.translate(
            "SyncPlanTableModel", "Matching content identity"
        ),
        SyncPlanBasis.MISSING_IDENTITY: QCoreApplication.translate(
            "SyncPlanTableModel", "No safe content identity was available"
        ),
        SyncPlanBasis.AMBIGUOUS_IDENTITY: QCoreApplication.translate(
            "SyncPlanTableModel", "Content identity matched more than one item"
        ),
        SyncPlanBasis.CONFLICTING_IDENTITY: QCoreApplication.translate(
            "SyncPlanTableModel", "File facts match, but content identity differs"
        ),
        SyncPlanBasis.USER_DESELECTED: QCoreApplication.translate(
            "SyncPlanTableModel", "Deselected from the desired iPod contents"
        ),
        SyncPlanBasis.HOST_FACTS_CHANGED: "",
    }[item.basis]


def _tooltip(item: SyncPlanItem) -> str:
    lines = [_action_label(item.action) + " · " + _basis_label(item)]
    if item.host_path:
        lines.append(
            QCoreApplication.translate("SyncPlanTableModel", "Host: %1").replace(
                "%1", item.host_path
            )
        )
    if item.ipod_path:
        lines.append(
            QCoreApplication.translate("SyncPlanTableModel", "iPod: %1").replace(
                "%1", item.ipod_path
            )
        )
    return "\n".join(lines)


def _sort_value(item: SyncPlanItem, column: SyncPlanColumn) -> object:
    if column is SyncPlanColumn.ACTION:
        return {
            SyncPlanAction.ADD: 0,
            SyncPlanAction.UPDATE: 1,
            SyncPlanAction.REMOVE: 2,
            SyncPlanAction.ATTENTION: 3,
            SyncPlanAction.UNCHANGED: 4,
        }[item.action]
    if column is SyncPlanColumn.MEDIA:
        return item.media_kind.value
    if column is SyncPlanColumn.NAME:
        return item.name.casefold()
    if column is SyncPlanColumn.HOST:
        return (item.host_path or "").casefold()
    if column is SyncPlanColumn.IPOD:
        return (item.ipod_path or "").casefold()
    return item.basis.value


__all__ = [
    "SyncPlanColumn",
    "SyncPlanFilterModel",
    "SyncPlanRole",
    "SyncPlanTableModel",
]
