"""Reusable controls above library discovery views."""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)

from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.themed_buttons import IconButton

_ASCENDING_ACTION = "__sort_ascending__"
_DESCENDING_ACTION = "__sort_descending__"


@dataclass(frozen=True, slots=True)
class SortOption:
    """One translated sort label paired with a stable model value."""

    label: str
    value: str


class LibraryToolbar(PageHeader):
    """Own one route title plus search, sort, and view-mode controls."""

    queryChanged = Signal(str)
    sortModeChanged = Signal(str)
    sortDirectionChanged = Signal(object)
    viewModeChanged = Signal(str)
    selectionGroupingChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("libraryToolbar")
        self.setProperty("libraryToolbar", True)
        self._view_mode = "grid"
        self._grid_title = ""
        self._list_title = ""
        self._grid_search_label = ""
        self._list_search_label = ""
        self._supports_list = True
        self._supports_search = True
        self._supports_selection_grouping = False
        self._sort_accessible_name = ""
        self._sort_options: tuple[SortOption, ...] = ()
        self._sort_mode_value: str | None = None
        self._sort_direction = Qt.SortOrder.AscendingOrder

        self._title = self.title_label
        self._title.setObjectName("browserTitle")

        self._sort = AppComboBox(self)
        self._sort.setObjectName("albumSort")
        self._sort.setMinimumWidth(132)
        self._sort.setMaximumWidth(180)

        self._grid_button = IconButton(
            "grid",
            self.tr("Grid view"),
            self,
            checkable=True,
        )
        self._list_button = IconButton(
            "list",
            self.tr("List view"),
            self,
            checkable=True,
        )
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_group.addButton(self._grid_button)
        self._view_group.addButton(self._list_button)

        self._selection_grouping = IconButton(
            "check-circle",
            self.tr("Group by selection"),
            self,
            checkable=True,
        )
        self._selection_grouping.setObjectName("selectionGrouping")

        view_switch = QFrame(self)
        view_switch.setObjectName("segmentedControl")
        view_switch.setProperty("viewModes", True)
        view_switch.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        view_layout = QHBoxLayout(view_switch)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(0)
        view_layout.addWidget(self._grid_button)
        view_layout.addWidget(self._list_button)
        self._view_switch = view_switch

        self._search = SearchField(self)
        self._search.setObjectName("librarySearch")

        self.add_action(self._sort)
        self.add_action(self._selection_grouping)
        self.add_action(view_switch)
        self.add_action(self._search)

        self._sort.currentIndexChanged.connect(self._sort_changed)
        self._grid_button.clicked.connect(
            lambda _checked=False: self.viewModeChanged.emit("grid")
        )
        self._list_button.clicked.connect(
            lambda _checked=False: self.viewModeChanged.emit("list")
        )
        self._selection_grouping.toggled.connect(self.selectionGroupingChanged.emit)
        self._search.queryChanged.connect(self.queryChanged.emit)
        self.set_view_mode("grid")
        self.retranslate_ui()

    def configure(
        self,
        *,
        grid_title: str,
        grid_search_label: str,
        list_title: str | None = None,
        list_search_label: str | None = None,
        supports_list: bool = True,
        supports_search: bool = True,
        supports_selection_grouping: bool = False,
        sort_accessible_name: str = "",
        sort_options: tuple[SortOption, ...] = (),
    ) -> None:
        """Set page-specific copy and expose only meaningful controls."""

        self._grid_title = grid_title
        self._list_title = list_title or grid_title
        self._grid_search_label = grid_search_label
        self._list_search_label = list_search_label or grid_search_label
        self._supports_list = supports_list
        self._supports_search = supports_search
        self._supports_selection_grouping = supports_selection_grouping
        self._sort_accessible_name = sort_accessible_name
        self._sort_options = sort_options
        if not supports_list:
            self._view_mode = "grid"
        self._refresh_sort_options()
        self._refresh_mode_copy()

    def set_namespace(self, namespace: str) -> None:
        """Give controls stable unique names for one page instance."""

        self.setObjectName(f"{namespace}Toolbar")
        self._title.setObjectName(f"{namespace}Title")
        self._sort.setObjectName(f"{namespace}Sort")
        self._view_switch.setObjectName(f"{namespace}ViewModes")
        self._selection_grouping.setObjectName(f"{namespace}SelectionGrouping")
        self._search.setObjectName(f"{namespace}Search")

    def set_query(self, query: str) -> None:
        self._search.set_query(query)

    def set_view_mode(self, mode: str) -> None:
        self._view_mode = "list" if self._supports_list and mode == "list" else "grid"
        blocker_grid = QSignalBlocker(self._grid_button)
        blocker_list = QSignalBlocker(self._list_button)
        self._grid_button.setChecked(self._view_mode == "grid")
        self._list_button.setChecked(self._view_mode == "list")
        del blocker_list
        del blocker_grid
        self._refresh_mode_copy()

    def set_selection_grouping(self, enabled: bool) -> None:
        self._selection_grouping.setChecked(enabled)

    def retranslate_ui(self) -> None:
        self._refresh_mode_copy()
        self._grid_button.setAccessibleName(self.tr("Grid view"))
        self._grid_button.setToolTip(self.tr("Grid view"))
        self._list_button.setAccessibleName(self.tr("List view"))
        self._list_button.setToolTip(self.tr("List view"))
        self._selection_grouping.setAccessibleName(self.tr("Group by selection"))
        self._selection_grouping.setToolTip(
            self.tr("Group cards as Selected, Mixed, and Deselected")
        )
        self._refresh_sort_options()

    def _refresh_sort_options(self) -> None:
        blocker = QSignalBlocker(self._sort)
        self._sort.clear()
        for option in self._sort_options:
            self._sort.addItem(option.label, option.value)
        if self._sort_options:
            self._sort.insertSeparator(self._sort.count())
            self._sort.addItem(self.tr("Ascending"), _ASCENDING_ACTION)
            self._sort.addItem(self.tr("Descending"), _DESCENDING_ACTION)
        index = (
            self._sort.findData(self._sort_mode_value)
            if self._sort_mode_value is not None
            else -1
        )
        if index < 0 and self._sort_options:
            index = 0
        self._sort.setCurrentIndex(index)
        value = self._sort.currentData()
        self._sort_mode_value = value if isinstance(value, str) else None
        self._sort.setAccessibleName(self._sort_accessible_name)
        del blocker

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _sort_changed(self, index: int) -> None:
        value = self._sort.itemData(index)
        if value == _ASCENDING_ACTION:
            self._set_sort_direction(Qt.SortOrder.AscendingOrder)
            return
        if value == _DESCENDING_ACTION:
            self._set_sort_direction(Qt.SortOrder.DescendingOrder)
            return
        if not isinstance(value, str):
            return
        self._sort_mode_value = value
        self.sortModeChanged.emit(value)

    def _set_sort_direction(self, direction: Qt.SortOrder) -> None:
        if direction != self._sort_direction:
            self._sort_direction = direction
            self.sortDirectionChanged.emit(direction)
        blocker = QSignalBlocker(self._sort)
        self._sort.setCurrentIndex(self._sort.findData(self._sort_mode_value))
        del blocker

    def _refresh_mode_copy(self) -> None:
        if self._view_mode == "list":
            title = self._list_title or self.tr("Tracks")
            search_label = self._list_search_label or self.tr("Search Tracks")
        else:
            title = self._grid_title or self.tr("Albums")
            search_label = self._grid_search_label or self.tr("Search Albums")
        self.set_title(title)
        self._search.setPlaceholderText(search_label)
        self._search.setAccessibleName(search_label)
        self._sort.setVisible(bool(self._sort_options))
        self._selection_grouping.setVisible(self._supports_selection_grouping)
        self._view_switch.setVisible(self._supports_list)
        self._search.setVisible(self._supports_search)


__all__ = ["LibraryToolbar", "SortOption"]
