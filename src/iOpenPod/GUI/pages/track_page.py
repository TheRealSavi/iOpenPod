"""Reusable filtered Track-table pages with optional artwork browsing."""

from PySide6.QtCore import QEvent, QItemSelectionModel, Signal
from PySide6.QtWidgets import QAbstractItemView, QStackedWidget, QVBoxLayout, QWidget

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.GUI.navigation import PageId, page_label
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.track_grid import TrackGridView
from iOpenPod.GUI.widgets.track_media_switch import TrackMediaSwitch
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import MediaKind


class TrackPage(QWidget):
    """Present a media subset in its configurable table and optional card grid."""

    currentTrackChanged = Signal(object)
    trackActivated = Signal(object)

    def __init__(
        self,
        tracks: TrackTableModel,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        page_id: PageId,
        table_id: str,
        media_kinds: tuple[MediaKind, ...] | None,
        parent: QWidget | None = None,
        *,
        show_media_switch: bool = False,
        show_grid: bool = False,
    ) -> None:
        super().__init__(parent)
        self._page_id = page_id
        self.setObjectName(f"{page_id.value}Page")

        self._proxy = TrackFilterProxyModel(tracks, self)
        self._proxy.set_media_kinds(media_kinds)
        self._toolbar = LibraryToolbar(self)
        self._toolbar.set_namespace(page_id.value)
        self._media_switch: TrackMediaSwitch | None = None
        if show_media_switch:
            self._media_switch = TrackMediaSwitch(self)
            self._toolbar.add_filter(self._media_switch)
            self._media_switch.allMediaChanged.connect(self._set_all_media)
            self._set_all_media(False)
        self._table = TrackTable(
            self._proxy,
            settings,
            theme_manager,
            artwork_provider,
            table_id,
            self,
        )
        self._grid: TrackGridView | None = None
        self._views: QStackedWidget | None = None
        if show_grid:
            self._grid = TrackGridView(
                self._proxy, theme_manager, artwork_provider, self
            )
            self._grid.setObjectName(f"{page_id.value}TrackGrid")
            self._views = QStackedWidget(self)
            self._views.addWidget(self._grid)
            self._views.addWidget(self._table)
            self._toolbar.viewModeChanged.connect(self.set_view_mode)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._views if self._views is not None else self._table, 1)

        self._toolbar.queryChanged.connect(self._proxy.set_query)
        self._table.currentTrackChanged.connect(self.currentTrackChanged.emit)
        self._table.trackActivated.connect(self.trackActivated.emit)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        label = page_label(self._page_id)
        self._toolbar.retranslate_ui()
        self._toolbar.configure(
            grid_title=label,
            grid_search_label=self.tr("Search %1").replace("%1", label),
            supports_list=self._grid is not None,
        )
        if self._grid is not None:
            self._grid.setAccessibleName(label)

    def set_view_mode(self, mode: str) -> None:
        """Switch presentation without opening a detail view or replacing the table."""
        if self._grid is None or self._views is None:
            return
        target = self._table if mode == "list" else self._grid
        current = self._views.currentWidget()
        if target is not current and isinstance(current, QAbstractItemView):
            selection = target.selectionModel()
            selected_rows = sorted({index.row() for index in current.selectedIndexes()})
            selection.clearSelection()
            flags = QItemSelectionModel.SelectionFlag.Select
            if target is self._table:
                flags |= QItemSelectionModel.SelectionFlag.Rows
            for row in selected_rows:
                selection.select(
                    self._proxy.index(row, self._grid.modelColumn()), flags
                )
            selection.setCurrentIndex(
                current.currentIndex().siblingAtColumn(self._grid.modelColumn()),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        self._views.setCurrentWidget(target)
        self._toolbar.set_view_mode(mode)
        if target.currentIndex().isValid():
            target.scrollTo(target.currentIndex())

    def select_track(self, track_id: int) -> bool:
        """Reveal a diagnostic's Track using the existing table and inspector."""
        self._toolbar.set_query("")
        self._proxy.set_query("")
        if self._media_switch is not None:
            source = self._proxy.sourceModel()
            if isinstance(source, TrackTableModel):
                for source_track in source.tracks:
                    if source_track.track_id == track_id:
                        if source_track.media_kind is not MediaKind.MUSIC:
                            self._media_switch.set_all_media(True)
                        break
        for row in range(self._proxy.rowCount()):
            index = self._proxy.index(row, 0)
            track = self._proxy.track_at(index)
            if track is not None and track.track_id == track_id:
                self.set_view_mode("list")
                self._table.selectRow(row)
                self._table.scrollTo(index)
                self._table.setFocus()
                return True
        return False

    def _set_all_media(self, enabled: bool) -> None:
        self._proxy.set_media_kinds(None if enabled else (MediaKind.MUSIC,))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


__all__ = ["TrackPage"]
