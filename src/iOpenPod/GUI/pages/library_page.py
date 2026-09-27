"""Primary iPod Library page for album discovery and Track browsing."""

from PySide6.QtCore import QCoreApplication, QEvent, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget

from iOpenPod.app.core.settings.definitions import (
    LIBRARY_SPLITTER_STATE,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.models.album_list_model import AlbumListModel, AlbumRole, AlbumSummary
from iOpenPod.app.models.library_filter_models import (
    AlbumFilterProxyModel,
    AlbumSortMode,
    TrackFilterProxyModel,
)
from iOpenPod.app.models.selection_grouping import SelectionGroupingProxyModel
from iOpenPod.app.models.track_table_model import TrackColumn, TrackTableModel
from iOpenPod.GUI.delegates.selection_group_delegate import SelectionGroupDelegate
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.library_content import LibraryContent
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar, SortOption
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import MediaKind


class LibraryPage(QWidget):
    """Compose one shared model into a virtualized grid and Track table."""

    currentTrackChanged = Signal(object)
    trackActivated = Signal(object)

    def __init__(
        self,
        tracks: TrackTableModel,
        albums: AlbumListModel,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
        *,
        selection_mode: bool = False,
        follow_ipod_view_mode: bool = True,
    ) -> None:
        super().__init__(parent)
        self._selected_album: AlbumSummary | None = None
        self._album_query = ""
        self._selection_mode = selection_mode

        self._album_proxy = AlbumFilterProxyModel(albums, self)
        self._album_grouping = (
            SelectionGroupingProxyModel(self._album_proxy, self)
            if selection_mode
            else None
        )
        self._track_proxy = TrackFilterProxyModel(tracks, self)
        self._track_proxy.set_media_kinds((MediaKind.MUSIC,))

        self._toolbar = LibraryToolbar(self)
        self._configure_toolbar()
        self._grid = AlbumGridView(
            self._album_proxy,
            theme_manager,
            artwork_provider,
            self,
        )
        if self._album_grouping is not None:
            album_delegate = self._grid.itemDelegate()
            self._grid.setModel(self._album_grouping)
            self._grid.setItemDelegate(
                SelectionGroupDelegate(album_delegate, theme_manager, self._grid)
            )
        self._table = TrackTable(
            self._track_proxy,
            settings,
            theme_manager,
            artwork_provider,
            "albums-tracks",
            self,
            default_sort_column=TrackColumn.ALBUM,
        )

        grid_panel = QFrame(self)
        grid_panel.setObjectName("albumGridPanel")
        grid_layout = QVBoxLayout(grid_panel)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(0)
        grid_layout.addWidget(self._grid)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)
        self._content = LibraryContent(
            grid_panel,
            self._table,
            self._track_proxy,
            self._toolbar,
            settings,
            theme_manager,
            artwork_provider,
            self,
            selection_mode=selection_mode,
            follow_ipod_view_mode=follow_ipod_view_mode,
            splitter_setting=LIBRARY_SPLITTER_STATE,
        )
        layout.addWidget(self._content, 1)
        self._content.backRequested.connect(self._show_browser)
        self._grid.clicked.connect(self._open_album)
        self._grid.activated.connect(self._open_album)
        self._grid.selectionModel().currentChanged.connect(self._browser_album_selected)

        self._toolbar.queryChanged.connect(self._set_browser_query)
        self._toolbar.sortModeChanged.connect(self._set_album_sort)
        self._toolbar.sortDirectionChanged.connect(self._album_proxy.set_sort_direction)
        self._toolbar.selectionGroupingChanged.connect(self._set_selection_grouping)
        self._table.currentTrackChanged.connect(self.currentTrackChanged.emit)
        self._table.trackActivated.connect(self.trackActivated.emit)
        tracks.modelReset.connect(self._library_reset)

        self._refresh_track_context()
        self._toolbar.set_selection_grouping(selection_mode)

    def show_all_tracks(self) -> None:
        self._show_browser()
        self._selected_album = None
        self._grid.clearSelection()
        self._grid.setCurrentIndex(QModelIndex())
        self._track_proxy.set_album_key(None)
        self._refresh_track_context()

    def retranslate_ui(self) -> None:
        if self._album_grouping is not None:
            self._album_grouping.retranslate()
        self._toolbar.retranslate_ui()
        self._configure_toolbar()
        self._content.retranslate_ui()
        self._refresh_track_context()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _browser_album_selected(
        self, current: QModelIndex, previous: QModelIndex
    ) -> None:
        if not self._content.whole_page_table:
            self._album_selected(current, previous)

    def _album_selected(
        self,
        current: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        if not current.isValid():
            self._selected_album = None
            self._track_proxy.set_album_key(None)
            self._refresh_track_context()
            return
        summary = current.data(AlbumRole.SUMMARY)
        if not isinstance(summary, AlbumSummary):
            return
        self._selected_album = summary
        self._track_proxy.set_album_key(summary.key)
        self._refresh_track_context()

    def _open_album(self, index: QModelIndex) -> None:
        if not self._content.whole_page_table:
            return
        if QApplication.keyboardModifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            return
        summary = index.data(AlbumRole.SUMMARY)
        if not isinstance(summary, AlbumSummary):
            return
        self._album_selected(index, QModelIndex())
        self._content.open_detail(summary)

    def _show_browser(self) -> None:
        self._content.show_browser()
        if self._content.whole_page_table:
            self._grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_browser_query(self, query: str) -> None:
        self._album_query = query
        self._album_proxy.set_query(query)

    def _set_album_sort(self, value: str) -> None:
        self._album_proxy.set_sort_mode(AlbumSortMode(value))

    def _set_selection_grouping(self, enabled: bool) -> None:
        if self._album_grouping is None:
            return
        self._album_proxy.set_group_by_selection(enabled)
        self._album_grouping.set_grouping_enabled(enabled)
        self._grid.set_sectioned_layout(enabled)

    def _library_reset(self) -> None:
        self.show_all_tracks()

    def _refresh_track_context(self) -> None:
        title = None
        if self._selected_album is not None:
            title = self._selected_album.title or QCoreApplication.translate(
                "LibraryLabels", "Unknown Album"
            )
        artwork_id = (
            self._selected_album.artwork_id if self._selected_album is not None else 0
        )
        self._content.set_track_context(title, artwork_id)

    def _configure_toolbar(self) -> None:
        self._toolbar.configure(
            grid_title=self.tr("Albums"),
            grid_search_label=self.tr("Search Albums"),
            supports_list=False,
            supports_selection_grouping=self._selection_mode,
            sort_accessible_name=self.tr("Sort albums"),
            sort_options=(
                SortOption(self.tr("Album title"), AlbumSortMode.TITLE.value),
                SortOption(self.tr("Artist"), AlbumSortMode.ARTIST.value),
                SortOption(self.tr("Year"), AlbumSortMode.YEAR.value),
            ),
        )
