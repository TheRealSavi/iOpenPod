"""Installed game covers and metadata, with explicit authorization preparation."""

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEvent,
    QPoint,
    Qt,
)
from PySide6.QtGui import (
    QShowEvent,
)
from PySide6.QtWidgets import (
    QLabel,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.games_controller import GamesController
from iOpenPod.GUI.dialogs.game_catalog import GameCatalogDialog
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.game_grid import GameGridView
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.game_library import GameCatalog, InstalledGame


class GamesPage(QWidget):
    def __init__(
        self,
        controller: GamesController,
        parent: QWidget | None = None,
        *,
        theme_manager: ThemeManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("gamesPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._controller = controller
        self._header = PageHeader(self)
        self._button = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._button.setObjectName("gimmeGames")
        self._button.clicked.connect(self._gimme_games)
        self._theme_manager = theme_manager
        self._dialog: GameCatalogDialog | None = None
        self._dialog_target: ActiveIPod | None = None
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setObjectName("pageDescription")
        self._header.add_action(self._button)
        self._grid = GameGridView(theme_manager, self)
        self._grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._grid.customContextMenuRequested.connect(self._show_game_menu)
        self._game_menu = QMenu(self._grid)
        self._game_menu.setObjectName("gameContextMenu")
        self._uninstall = self._game_menu.addAction("")
        self._uninstall.setObjectName("uninstallGame")
        self._uninstall.triggered.connect(self._uninstall_game)
        self._uninstall_target: tuple[ActiveIPod, InstalledGame] | None = None
        self._shown_catalog: GameCatalog | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._status.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_sm
        )
        body.addWidget(self._status)
        body.addWidget(self._grid, 1)
        layout.addLayout(body, 1)
        controller.changed.connect(self._refresh)
        controller.catalogRequested.connect(self._open_game_catalog)
        self._refresh()

    def _refresh(self) -> None:
        self._header.set_title(self.tr("Games"))
        self._button.setText(self.tr("Gimme Games"))
        self._button.setEnabled(self._controller.available)
        self._status.setText(self._controller.message)
        self._status.setVisible(bool(self._controller.message))
        self._grid.setAccessibleName(self.tr("Installed games"))
        self._uninstall.setText(self.tr("Uninstall"))
        self._uninstall.setEnabled(self._controller.can_uninstall)
        catalog = self._controller.catalog
        if self._uninstall_target is not None and (
            self._uninstall_target[0] is not self._controller.active_ipod
            or self._uninstall_target[1] not in catalog.games
        ):
            self._uninstall_target = None
            self._game_menu.hide()
        if self._shown_catalog is not catalog:
            self._shown_catalog = catalog
            self._grid.set_games(catalog.games)
        if self._dialog is not None:
            if self._controller.active_ipod is not self._dialog_target:
                self._discard_dialog()
            else:
                self._update_dialog()
        if self.isVisible():
            self._controller.load_games()

    def _show_game_menu(self, point: QPoint) -> None:
        self._uninstall_target = None
        index = self._grid.indexAt(point)
        active = self._controller.active_ipod
        if not index.isValid() or active is None:
            self._game_menu.hide()
            return
        directory: object = index.data(Qt.ItemDataRole.UserRole)
        game = next(
            (
                game
                for game in self._controller.catalog.games
                if game.directory == directory
            ),
            None,
        )
        if game is None:
            return
        self._grid.setCurrentIndex(index)
        self._uninstall_target = (active, game)
        self._uninstall.setEnabled(self._controller.can_uninstall)
        self._game_menu.popup(self._grid.viewport().mapToGlobal(point))

    def _uninstall_game(self) -> None:
        target = self._uninstall_target
        self._uninstall_target = None
        if (
            target is None
            or target[0] is not self._controller.active_ipod
            or not self._controller.can_uninstall
        ):
            return
        confirmation = QMessageBox(self)
        confirmation.setObjectName("uninstallGameConfirmation")
        confirmation.setWindowTitle(self.tr("Uninstall game?"))
        confirmation.setIcon(QMessageBox.Icon.Warning)
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        confirmation.setText(
            self.tr('Uninstall "{title}"?').format(title=target[1].title)
        )
        confirmation.setInformativeText(
            self.tr(
                "The game, its saved progress, and its statistics will be deleted from this iPod."
            )
        )
        uninstall = confirmation.addButton(
            self.tr("Uninstall"), QMessageBox.ButtonRole.DestructiveRole
        )
        confirmation.addButton(QMessageBox.StandardButton.Cancel)
        confirmation.setDefaultButton(QMessageBox.StandardButton.Cancel)
        confirmation.setEscapeButton(QMessageBox.StandardButton.Cancel)
        confirmation.exec()
        accepted = confirmation.clickedButton() is uninstall
        confirmation.deleteLater()
        if accepted and target[0] is self._controller.active_ipod:
            self._controller.uninstall(target[1])

    def _gimme_games(self) -> None:
        self._controller.start()

    def _open_game_catalog(self) -> None:
        target = self._controller.active_ipod
        if target is None:
            return
        if self._dialog is not None and target is self._dialog_target:
            # Keep the native window and decoded covers while preparation runs.
            self._update_dialog()
            self._dialog.show()
            return
        try:
            games = self._controller.offered_games()
        except (ValueError, OSError) as error:
            QMessageBox.warning(
                self,
                self.tr("Games"),
                self.tr("The game catalog could not be loaded: {detail}").format(
                    detail=str(error)
                ),
            )
            return
        dialog = GameCatalogDialog(games, self, theme_manager=self._theme_manager)
        dialog.installRequested.connect(self._controller.install)
        self._dialog = dialog
        self._dialog_target = target
        self._update_dialog()
        dialog.show()

    def _update_dialog(self) -> None:
        if self._dialog is None:
            return
        ready = self._controller.catalog_ready
        self._dialog.set_installed_games(
            self._controller.catalog.games if ready else None
        )
        self._dialog.set_status(self._controller.message)
        self._dialog.set_installation_state(
            available=self._controller.can_install,
            installing=self._controller.installing,
        )

    def _discard_dialog(self) -> None:
        dialog = self._dialog
        self._dialog = None
        self._dialog_target = None
        if dialog is not None:
            dialog.reject()
            dialog.deleteLater()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._controller.load_games()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() is QEvent.Type.LanguageChange:
            self._shown_catalog = None
            self._refresh()
        super().changeEvent(event)
