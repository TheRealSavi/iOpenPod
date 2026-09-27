"""Collection browsers for Artists, Genres, TV Shows, and Music Videos."""

from PySide6.QtCore import QCoreApplication, QEvent, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListView,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.models.album_list_model import AlbumListModel, AlbumRole, AlbumSummary
from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionListModel,
    CollectionRole,
    CollectionSummary,
)
from iOpenPod.app.models.library_filter_models import (
    AlbumFilterProxyModel,
    CollectionFilterProxyModel,
    CollectionSortMode,
    TrackFilterProxyModel,
)
from iOpenPod.app.models.selection_grouping import (
    SelectionGroupingProxyModel,
    SelectionGroupingRole,
)
from iOpenPod.app.models.track_order import album_track_sort_key
from iOpenPod.app.models.track_table_model import TrackColumn, TrackTableModel
from iOpenPod.GUI.delegates.collection_list_delegate import CollectionListDelegate
from iOpenPod.GUI.delegates.selection_group_delegate import SelectionGroupDelegate
from iOpenPod.GUI.navigation import PageId, page_label
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.browser_chrome import SourceListPanel
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.library_content import LibraryContent
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar, SortOption
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import MediaKind


class CollectionPage(QWidget):
    """Browse a cached collection projection and its Tracks or Albums."""

    currentTrackChanged = Signal(object)
    trackActivated = Signal(object)
    tracksActivated = Signal(object)

    def __init__(
        self,
        tracks: TrackTableModel,
        collections: CollectionListModel,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        *,
        page_id: PageId,
        table_id: str,
        albums: AlbumListModel | None = None,
        parent: QWidget | None = None,
        selection_mode: bool = False,
        follow_ipod_view_mode: bool = True,
    ) -> None:
        super().__init__(parent)
        self._page_id = page_id
        self._source_tracks = tracks
        self._kind = collections.kind
        self._supports_list = albums is not None
        self._selection_mode = selection_mode
        self._selected_collection: CollectionSummary | None = None
        self._selected_album: AlbumSummary | None = None
        self.setObjectName(f"{page_id.value}Page")

        self._collection_proxy = CollectionFilterProxyModel(collections, self)
        self._collection_grouping = (
            SelectionGroupingProxyModel(self._collection_proxy, self)
            if selection_mode
            else None
        )
        self._track_proxy = TrackFilterProxyModel(tracks, self)
        self._track_proxy.set_media_kinds((_media_kind(collections.kind),))
        self._album_proxy = (
            AlbumFilterProxyModel(albums, self) if albums is not None else None
        )
        self._album_grouping = (
            SelectionGroupingProxyModel(self._album_proxy, self)
            if self._album_proxy is not None and selection_mode
            else None
        )

        self._toolbar = LibraryToolbar(self)
        self._toolbar.set_namespace(page_id.value)
        self._collection_grid = CollectionGridView(
            self._collection_proxy,
            theme_manager,
            artwork_provider,
            object_name=f"{page_id.value}CollectionGrid",
            accessible_name=page_label(page_id),
            parent=self,
        )
        if self._collection_grouping is not None:
            collection_delegate = self._collection_grid.itemDelegate()
            self._collection_grid.setModel(self._collection_grouping)
            self._collection_grid.setItemDelegate(
                SelectionGroupDelegate(
                    collection_delegate,
                    theme_manager,
                    self._collection_grid,
                )
            )
        self._browser_stack = QStackedWidget(self)
        self._browser_stack.setObjectName(f"{page_id.value}BrowserStack")
        self._browser_stack.addWidget(self._collection_grid)

        self._collection_list: QListView | None = None
        self._collection_panel: SourceListPanel | None = None
        self._album_grid: AlbumGridView | None = None
        if self._album_proxy is not None:
            list_browser = QSplitter(Qt.Orientation.Horizontal, self)
            list_browser.setObjectName("collectionListBrowser")
            list_browser.setProperty("sourceListBrowser", True)
            list_browser.setHandleWidth(LAYOUT.source_list_splitter_handle_width)
            list_browser.setChildrenCollapsible(False)
            collection_panel = SourceListPanel(
                LAYOUT.source_list_width,
                list_browser,
                minimum_width=LAYOUT.source_list_minimum_width,
            )
            collection_panel.setObjectName(f"{page_id.value}CollectionPanel")
            collection_panel.setMaximumWidth(LAYOUT.source_list_maximum_width)
            collection_panel.title_label.setObjectName(
                f"{page_id.value}CollectionHeading"
            )
            collection_panel.count_label.setObjectName(
                f"{page_id.value}CollectionCount"
            )
            collection_list = QListView(collection_panel)
            collection_list.setObjectName(f"{page_id.value}CollectionList")
            collection_list.setProperty("collectionList", True)
            collection_list.setModel(
                self._collection_grouping or self._collection_proxy
            )
            collection_delegate = CollectionListDelegate(
                theme_manager,
                collection_list,
            )
            collection_list.setItemDelegate(
                SelectionGroupDelegate(
                    collection_delegate,
                    theme_manager,
                    collection_list,
                )
                if self._collection_grouping is not None
                else collection_delegate
            )
            collection_list.setViewMode(QListView.ViewMode.ListMode)
            collection_list.setFlow(QListView.Flow.TopToBottom)
            collection_list.setWrapping(False)
            collection_list.setResizeMode(QListView.ResizeMode.Adjust)
            collection_list.setMovement(QListView.Movement.Static)
            collection_list.setUniformItemSizes(True)
            collection_list.setMouseTracking(True)
            collection_list.setEditTriggers(
                QAbstractItemView.EditTrigger.NoEditTriggers
            )
            collection_panel.set_view(collection_list, standard_items=False)
            album_grid = AlbumGridView(
                self._album_proxy,
                theme_manager,
                artwork_provider,
                list_browser,
            )
            if self._album_grouping is not None:
                album_delegate = album_grid.itemDelegate()
                album_grid.setModel(self._album_grouping)
                album_grid.setItemDelegate(
                    SelectionGroupDelegate(album_delegate, theme_manager, album_grid)
                )
            album_grid.setObjectName(f"{page_id.value}AlbumGrid")
            list_browser.addWidget(collection_panel)
            list_browser.addWidget(album_grid)
            list_browser.setCollapsible(0, False)
            list_browser.setCollapsible(1, False)
            list_browser.setStretchFactor(0, 0)
            list_browser.setStretchFactor(1, 1)
            list_browser.setSizes([LAYOUT.source_list_width, 700])
            self._browser_stack.addWidget(list_browser)
            self._collection_panel = collection_panel
            self._collection_list = collection_list
            self._album_grid = album_grid

        self._table = TrackTable(
            self._track_proxy,
            settings,
            theme_manager,
            artwork_provider,
            table_id,
            self,
            default_sort_column=TrackColumn.ALBUM,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)
        self._content = LibraryContent(
            self._browser_stack,
            self._table,
            self._track_proxy,
            self._toolbar,
            settings,
            theme_manager,
            artwork_provider,
            self,
            selection_mode=selection_mode,
            follow_ipod_view_mode=follow_ipod_view_mode,
            splitter_name=f"{page_id.value}LibrarySplitter",
        )
        layout.addWidget(self._content, 1)
        self._content.backRequested.connect(self._show_browser)
        self._collection_grid.clicked.connect(self._open_collection)
        self._collection_grid.activated.connect(self._open_collection)
        self._collection_grid.selectionModel().currentChanged.connect(
            self._browser_collection_selected
        )
        if self._album_grid is not None:
            self._album_grid.clicked.connect(self._open_album)
            self._album_grid.activated.connect(self._open_album)
            self._album_grid.selectionModel().currentChanged.connect(
                self._browser_album_selected
            )

        self._toolbar.queryChanged.connect(self._collection_proxy.set_query)
        self._toolbar.sortModeChanged.connect(self._set_collection_sort)
        self._toolbar.sortDirectionChanged.connect(
            self._collection_proxy.set_sort_direction
        )
        self._toolbar.viewModeChanged.connect(self.set_view_mode)
        self._toolbar.selectionGroupingChanged.connect(self._set_selection_grouping)
        self._table.currentTrackChanged.connect(self.currentTrackChanged.emit)
        self._table.trackActivated.connect(self.trackActivated.emit)
        if self._collection_list is not None:
            self._collection_list.selectionModel().currentChanged.connect(
                self._collection_selected
            )
            self._collection_list.doubleClicked.connect(self._collection_activated)
        collections.modelReset.connect(self.show_all)
        self._collection_proxy.rowsInserted.connect(self._refresh_collection_count)
        self._collection_proxy.rowsRemoved.connect(self._refresh_collection_count)
        self._collection_proxy.modelReset.connect(self._refresh_collection_count)
        self.set_view_mode("grid")
        self.retranslate_ui()
        self._refresh_collection_count()
        self._refresh_track_context()
        self._toolbar.set_selection_grouping(selection_mode)

    def set_view_mode(self, mode: str) -> None:
        normalized = "list" if self._supports_list and mode == "list" else "grid"
        self._browser_stack.setCurrentIndex(1 if normalized == "list" else 0)
        self._toolbar.set_view_mode(normalized)

    def show_all(self) -> None:
        self._show_browser()
        self._selected_collection = None
        self._selected_album = None
        self._track_proxy.set_album_key(None)
        self._track_proxy.set_collection_key(None, None)
        if self._album_proxy is not None:
            self._album_proxy.set_collection_key(None, None)
        self._collection_grid.clearSelection()
        self._collection_grid.setCurrentIndex(QModelIndex())
        if self._collection_list is not None:
            self._collection_list.clearSelection()
            self._collection_list.setCurrentIndex(QModelIndex())
        if self._album_grid is not None:
            self._album_grid.clearSelection()
            self._album_grid.setCurrentIndex(QModelIndex())
        self._refresh_track_context()

    def retranslate_ui(self) -> None:
        label = page_label(self._page_id)
        if self._collection_grouping is not None:
            self._collection_grouping.retranslate()
        if self._album_grouping is not None:
            self._album_grouping.retranslate()
        self._collection_grid.setAccessibleName(label)
        if self._collection_panel is not None:
            self._collection_panel.set_title(label)
        self._toolbar.retranslate_ui()
        self._toolbar.configure(
            grid_title=label,
            grid_search_label=self.tr("Search %1").replace("%1", label),
            list_title=label,
            list_search_label=self.tr("Search %1").replace("%1", label),
            supports_list=self._supports_list,
            supports_selection_grouping=self._selection_mode,
            sort_accessible_name=self.tr("Sort %1").replace("%1", label),
            sort_options=self._sort_options(),
        )
        self._content.retranslate_ui()
        self._refresh_track_context()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _browser_collection_selected(
        self, current: QModelIndex, previous: QModelIndex
    ) -> None:
        if not self._content.whole_page_table:
            self._collection_selected(current, previous)

    def _browser_album_selected(
        self, current: QModelIndex, previous: QModelIndex
    ) -> None:
        if not self._content.whole_page_table:
            self._album_selected(current, previous)

    def _collection_selected(
        self,
        current: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        if self._content.detail_open:
            return
        if current.data(SelectionGroupingRole.IS_HEADER):
            return
        self._synchronize_collection_current(current)
        summary = current.data(CollectionRole.SUMMARY) if current.isValid() else None
        if not isinstance(summary, CollectionSummary):
            self._selected_collection = None
            self._selected_album = None
            self._track_proxy.set_album_key(None)
            self._track_proxy.set_collection_key(None, None)
            if self._album_proxy is not None:
                self._album_proxy.set_collection_key(None, None)
            self._refresh_track_context()
            return
        self._selected_collection = summary
        self._selected_album = None
        self._track_proxy.set_album_key(None)
        self._track_proxy.set_collection_key(self._kind, summary.key)
        if self._album_proxy is not None:
            self._album_proxy.set_collection_key(self._kind, summary.key)
        if self._album_grid is not None:
            self._album_grid.clearSelection()
            self._album_grid.setCurrentIndex(QModelIndex())
        self._refresh_track_context()

    def _collection_activated(self, index: QModelIndex) -> None:
        summary = index.data(CollectionRole.SUMMARY)
        if not isinstance(summary, CollectionSummary):
            return
        track_ids = set(summary.track_ids)
        tracks = tuple(
            sorted(
                (
                    track
                    for track in self._source_tracks.tracks
                    if track.track_id in track_ids
                ),
                key=album_track_sort_key,
            )
        )
        if tracks:
            self.tracksActivated.emit(tracks)

    def _synchronize_collection_current(self, current: QModelIndex) -> None:
        for view in (self._collection_grid, self._collection_list):
            if view is not None and view.currentIndex() != current:
                view.setCurrentIndex(current)

    def _refresh_collection_count(self, *_args: object) -> None:
        if self._collection_panel is not None:
            self._collection_panel.set_count(self._collection_proxy.rowCount())

    def _album_selected(
        self,
        current: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        if current.data(SelectionGroupingRole.IS_HEADER):
            return
        summary = current.data(AlbumRole.SUMMARY) if current.isValid() else None
        self._selected_album = summary if isinstance(summary, AlbumSummary) else None
        self._track_proxy.set_album_key(
            self._selected_album.key if self._selected_album is not None else None
        )
        self._refresh_track_context()

    def _set_collection_sort(self, value: str) -> None:
        self._collection_proxy.set_sort_mode(CollectionSortMode(value))

    def _open_collection(self, index: QModelIndex) -> None:
        summary = index.data(CollectionRole.SUMMARY)
        if not isinstance(summary, CollectionSummary) or not self._can_open_detail():
            return
        self._collection_selected(index, QModelIndex())
        self._show_detail(summary)

    def _open_album(self, index: QModelIndex) -> None:
        summary = index.data(AlbumRole.SUMMARY)
        if not isinstance(summary, AlbumSummary) or not self._can_open_detail():
            return
        self._album_selected(index, QModelIndex())
        self._show_detail(summary)

    def _can_open_detail(self) -> bool:
        return self._content.whole_page_table and not bool(
            QApplication.keyboardModifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        )

    def _show_detail(self, summary: AlbumSummary | CollectionSummary) -> None:
        self._content.open_detail(summary)

    def _show_browser(self) -> None:
        self._content.show_browser()
        if self._content.whole_page_table:
            view = (
                self._album_grid
                if self._browser_stack.currentIndex() == 1
                else self._collection_grid
            )
            if view is not None:
                view.setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_selection_grouping(self, enabled: bool) -> None:
        if self._collection_grouping is None:
            return
        self._collection_proxy.set_group_by_selection(enabled)
        self._collection_grouping.set_grouping_enabled(enabled)
        self._collection_grid.set_sectioned_layout(enabled)
        if self._album_proxy is not None:
            self._album_proxy.set_group_by_selection(enabled)
        if self._album_grouping is not None:
            self._album_grouping.set_grouping_enabled(enabled)
        if self._album_grid is not None:
            self._album_grid.set_sectioned_layout(enabled)

    def _sort_options(self) -> tuple[SortOption, ...]:
        title = CollectionSortMode.TITLE.value
        items = CollectionSortMode.ITEM_COUNT.value
        tracks = CollectionSortMode.TRACK_COUNT.value
        duration = CollectionSortMode.DURATION.value
        if self._kind is CollectionKind.ARTIST:
            return (
                SortOption(self.tr("Artist name"), title),
                SortOption(self.tr("Most albums"), items),
                SortOption(self.tr("Most tracks"), tracks),
            )
        if self._kind is CollectionKind.GENRE:
            return (
                SortOption(self.tr("Genre name"), title),
                SortOption(self.tr("Most albums"), items),
                SortOption(self.tr("Most tracks"), tracks),
            )
        if self._kind is CollectionKind.TV_SHOW:
            return (
                SortOption(self.tr("Show name"), title),
                SortOption(self.tr("Most episodes"), items),
                SortOption(self.tr("Longest duration"), duration),
            )
        return (
            SortOption(self.tr("Album title"), title),
            SortOption(self.tr("Most videos"), tracks),
            SortOption(self.tr("Longest duration"), duration),
        )

    def _refresh_track_context(self) -> None:
        title = None
        if self._selected_album is not None:
            title = self._selected_album.title or QCoreApplication.translate(
                "LibraryLabels", "Unknown Album"
            )
        elif self._selected_collection is not None:
            title = self._selected_collection.title or QCoreApplication.translate(
                "LibraryLabels", "Unknown Collection"
            )
        artwork_id = 0
        if self._selected_album is not None:
            artwork_id = self._selected_album.artwork_id
        elif self._selected_collection is not None:
            artwork_id = self._selected_collection.representative_artwork_id
        self._content.set_track_context(title, artwork_id)


def _media_kind(kind: CollectionKind) -> MediaKind:
    return {
        CollectionKind.ARTIST: MediaKind.MUSIC,
        CollectionKind.GENRE: MediaKind.MUSIC,
        CollectionKind.TV_SHOW: MediaKind.TV_SHOW,
        CollectionKind.MUSIC_VIDEO_ALBUM: MediaKind.MUSIC_VIDEO,
    }[kind]


__all__ = ["CollectionPage"]
