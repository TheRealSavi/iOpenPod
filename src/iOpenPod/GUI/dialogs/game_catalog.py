"""Browse the bundled games compatible with the current authorization target."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.filter_compat import end_rows_filter_change
from iOpenPod.GUI.delegates.game_card_delegate import TITLE_ROLE
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.game_grid import GameGridView
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from PySide6.QtGui import QCloseEvent

    from iOpenPod.app.services.game_library import InstalledGame
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager


class _AvailableGamesFilter(QSortFilterProxyModel):
    """Installed identities remain excluded independently of the search query."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._installed: frozenset[str] | None = frozenset()
        self.setFilterRole(TITLE_ROLE)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_installed_games(self, games: tuple[InstalledGame, ...] | None) -> None:
        identifiers = (
            frozenset(
                (game.identifier or game.directory).strip().casefold() for game in games
            )
            if games is not None
            else None
        )
        if identifiers == self._installed:
            return
        self.beginFilterChange()
        self._installed = identifiers
        end_rows_filter_change(self)

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        source = self.sourceModel()
        if self._installed is None:
            return False
        identifier: object = source.index(source_row, 0, source_parent).data(
            Qt.ItemDataRole.UserRole
        )
        return (
            isinstance(identifier, str)
            and identifier.strip().casefold() not in self._installed
            and super().filterAcceptsRow(source_row, source_parent)
        )


class GameCatalogDialog(QDialog):
    """Retain the browser's native surface and artwork between visits."""

    installRequested = Signal(object)

    def __init__(
        self,
        games: tuple[InstalledGame, ...],
        parent: QWidget | None = None,
        *,
        theme_manager: ThemeManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("gameCatalogDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(920, 640)
        self._header = PageHeader(self)
        self._search = SearchField(self)
        self._search.setObjectName("gameCatalogSearch")
        self._header.add_action(self._search)
        self._status = QLabel(self)
        self._status.setObjectName("pageDescription")
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        self._status.hide()
        self._status.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_sm
        )
        self._can_install = False
        self._installing = False
        self._grid = GameGridView(theme_manager, self, checkable=True)
        self._grid.setObjectName("availableGamesGrid")
        self._grid.set_games(games)
        self._filter = _AvailableGamesFilter(self)
        self._filter.setSourceModel(self._grid.model())
        self._grid.model().dataChanged.connect(self._update_add)
        self._grid.setModel(self._filter)
        self._search.queryChanged.connect(self._set_query)
        self._empty = QLabel(self)
        self._empty.setObjectName("gameCatalogEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body = QStackedWidget(self)
        self._body.setObjectName("gameCatalogBody")
        self._body.addWidget(self._grid)
        self._body.addWidget(self._empty)
        self._filter.rowsInserted.connect(self._update_empty)
        self._filter.rowsRemoved.connect(self._update_empty)
        self._filter.modelReset.connect(self._update_empty)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        self._add = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._add.setObjectName("addGames")
        self._add.setAutoDefault(False)
        self._add.clicked.connect(self._request_install)
        buttons.addButton(self._add, QDialogButtonBox.ButtonRole.ActionRole)
        self._select_all = ActionButton(self.tr("Select all"), self)
        self._select_all.setObjectName("selectAllGames")
        self._select_all.setAutoDefault(False)
        self._select_all.clicked.connect(self._select_all_games)
        footer = QHBoxLayout()
        footer.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_sm
        )
        footer.addWidget(self._select_all)
        footer.addStretch(1)
        footer.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._status)
        layout.addWidget(self._body, 1)
        layout.addLayout(footer)
        self._retranslate()

    def set_status(self, message: str) -> None:
        self._status.setText(message)
        self._status.setVisible(bool(message))

    def set_installed_games(self, games: tuple[InstalledGame, ...] | None) -> None:
        if games is not None:
            self._grid.uncheck_installed(
                frozenset(
                    (game.identifier or game.directory).strip().casefold()
                    for game in games
                )
            )
        self._filter.set_installed_games(games)
        self._update_empty()

    def set_installation_state(self, *, available: bool, installing: bool) -> None:
        self._can_install = available
        self._installing = installing
        self._grid.setEnabled(not installing)
        self._update_add()

    def _update_add(self) -> None:
        self._add.setText(self.tr("Adding…") if self._installing else self.tr("Add"))
        self._add.setEnabled(
            self._can_install and bool(self._grid.checked_identifiers())
        )
        self._update_select_all()

    def _update_select_all(self) -> None:
        self._select_all.setEnabled(
            not self._installing and self._filter.rowCount() > 0
        )

    def _select_all_games(self) -> None:
        if not self._select_all.isEnabled():
            return
        for row in range(self._filter.rowCount()):
            self._filter.setData(
                self._filter.index(row, 0),
                Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )

    def _request_install(self) -> None:
        if self._add.isEnabled():
            self.installRequested.emit(self._grid.checked_identifiers())

    def _set_query(self, query: str) -> None:
        self._filter.setFilterFixedString(query.strip())
        self._update_empty()

    def _update_empty(self) -> None:
        self._body.setCurrentWidget(
            self._empty if self._filter.rowCount() == 0 else self._grid
        )
        self._update_select_all()

    def done(self, result: int) -> None:
        # QDialog.done() closes the native window even without DeleteOnClose.
        # Hiding keeps its backing surface ready for the next visit.
        self.setResult(result)
        self.hide()
        if result == QDialog.DialogCode.Accepted:
            self.accepted.emit()
        elif result == QDialog.DialogCode.Rejected:
            self.rejected.emit()
        self.finished.emit(result)

    def closeEvent(self, event: QCloseEvent) -> None:
        # The window-manager close action must follow the same hide-only path
        # as the Close button and Escape, rather than destroy the surface.
        event.ignore()
        self.reject()

    def _retranslate(self) -> None:
        title = self.tr("Available games")
        self.setWindowTitle(title)
        self._header.set_title(title)
        self._grid.setAccessibleName(title)
        self._search.setPlaceholderText(self.tr("Search games"))
        self._search.setAccessibleName(self.tr("Search games"))
        self._empty.setText(self.tr("No available games"))
        self._select_all.setText(self.tr("Select all"))
        self._update_add()
        self._update_empty()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() is QEvent.Type.LanguageChange:
            self._retranslate()
        super().changeEvent(event)
