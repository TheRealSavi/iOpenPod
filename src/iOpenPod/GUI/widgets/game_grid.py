"""Shared equalized game cards for installed and available game catalogs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QCoreApplication,
    QEvent,
    QIODevice,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QIcon,
    QImageReader,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import QAbstractItemView, QFrame, QListView, QWidget

from iOpenPod.GUI.delegates.game_card_delegate import (
    TITLE_ROLE,
    VERSION_ROLE,
    GameCardDelegate,
)
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.widgets.selection_grid import SelectionGridView

if TYPE_CHECKING:
    from iOpenPod.app.services.game_library import InstalledGame
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager


class GameGridView(SelectionGridView):
    def __init__(
        self,
        theme_manager: ThemeManager | None,
        parent: QWidget | None = None,
        *,
        checkable: bool = False,
    ) -> None:
        super().__init__(parent)
        self._games: tuple[InstalledGame, ...] = ()
        self._checkable = checkable
        self._items = QStandardItemModel(self)
        self.setModel(self._items)
        self.setObjectName("gamesGrid")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        delegate = GameCardDelegate(theme_manager, self)
        self.setItemDelegate(delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(64)
        self.setIconSize(QSize(192, 144))
        self.synchronize_item_size()
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        if checkable:
            self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        if theme_manager is not None:
            theme_manager.effectiveThemeChanged.connect(self._theme_changed)

    def set_games(self, games: tuple[InstalledGame, ...]) -> None:
        checked = self.checked_identifiers()
        self._games = games
        self._items.clear()
        for game in games:
            version = (
                QCoreApplication.translate("GamesPage", "Version {version}").format(
                    version=game.version
                )
                if game.version
                else QCoreApplication.translate("GamesPage", "Version unavailable")
            )
            item = QStandardItem(self._cover(game.artwork), f"{game.title}\n{version}")
            item.setEditable(False)
            if self._checkable:
                item.setCheckable(True)
                item.setData(
                    Qt.CheckState.Checked
                    if game.directory in checked
                    else Qt.CheckState.Unchecked,
                    Qt.ItemDataRole.CheckStateRole,
                )
            item.setToolTip(f"{game.title}\n{version}")
            item.setData(game.directory, Qt.ItemDataRole.UserRole)
            item.setData(game.title, TITLE_ROLE)
            item.setData(version, VERSION_ROLE)
            self._items.appendRow(item)

    def checked_identifiers(self) -> tuple[str, ...]:
        return tuple(
            str(self._items.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self._items.rowCount())
            if self._items.item(row).checkState() == Qt.CheckState.Checked
        )

    def uncheck_installed(self, identifiers: frozenset[str]) -> None:
        for row in range(self._items.rowCount()):
            item = self._items.item(row)
            if (
                str(item.data(Qt.ItemDataRole.UserRole)).strip().casefold()
                in identifiers
            ):
                item.setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)

    def _theme_changed(self, _theme: str) -> None:
        self.set_games(self._games)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() is QEvent.Type.LanguageChange:
            self.set_games(self._games)
        super().changeEvent(event)

    def _cover(self, data: bytes) -> QIcon:
        buffer = QBuffer(self)
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        size = reader.size()
        if size.isValid() and size.width() <= 4096 and size.height() <= 4096:
            reader.setScaledSize(
                size.scaled(QSize(192, 144), Qt.AspectRatioMode.KeepAspectRatio)
            )
            image = reader.read()
            if not image.isNull():
                buffer.deleteLater()
                return QIcon(QPixmap.fromImage(image))
        buffer.deleteLater()
        return glyph_icon("games", 96, self.palette().text().color())
