"""Sync context menus apply one explicit action to highlighted semantic items."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QItemSelectionModel, QPoint, Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.album_list_model import AlbumRole, AlbumSummary
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.models.collection_list_model import CollectionRole, CollectionSummary
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.photo_list_model import PhotoRole
from iOpenPod.app.models.selection_grouping import SelectionGroupingRole
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.models.track_table_model import TrackColumn, TrackRole
from iOpenPod.app.sync_plan import SyncPlan
from iOpenPod.GUI.host_library_browser import HostLibraryBrowser
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.photo_grid import PhotoGridView
from iOpenPod.GUI.widgets.sync_selection_actions import SyncSelectionActions
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import (
    LibrarySnapshot,
    Photo,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Playlist,
    PlaylistEntry,
    Track,
    TrackMetadata,
)


class _EmptyArtworkLoader:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        return None


@pytest.fixture
def sync_browser() -> Iterator[
    tuple[HostLibraryBrowser, SyncSelection, QStackedWidget]
]:
    library = HostMediaLibrary(
        LibrarySnapshot(
            tracks=tuple(
                Track(
                    track_id,
                    f"Track {track_id}",
                    group,
                    group,
                    1_000,
                    genre=group,
                    metadata=TrackMetadata(location=f"C:/Music/{track_id}.mp3"),
                )
                for track_id, group in ((1, "A"), (2, "A"), (3, "B"), (4, "C"))
            ),
            playlists=(
                Playlist(
                    10,
                    "Favorites",
                    entries=tuple(
                        PlaylistEntry(str(position), track_id)
                        for position, track_id in enumerate((1, 3, 1, 4, 2))
                    ),
                ),
            ),
            photos=PhotoLibrary(
                photos=tuple(
                    Photo(
                        photo_id,
                        representations=(
                            PhotoRepresentation(
                                PhotoRepresentationKind.FULL_RESOLUTION,
                                1,
                                f"C:/Photos/{photo_id}.jpg",
                                0,
                                100,
                                10,
                                10,
                            ),
                        ),
                    )
                    for photo_id in range(1, 5)
                )
            ),
        ),
        (),
        (),
        HostMediaCacheStats(inspected=8),
    )
    selection = SyncSelection()
    selection.reset(library, SyncPlan(()))
    selection.set_tracks_checked((1, 4), True)
    selection.set_photos_checked((1, 4), True)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    controller = ArtworkController(_EmptyArtworkLoader())
    provider = ArtworkPixmapProvider(controller)
    parent = QStackedWidget()
    workspace = LibraryWorkspace()
    workspace.set_locked(True)
    browser = HostLibraryBrowser(
        settings, theme, provider, workspace, parent, selection
    )
    browser.load(library)
    browser.playlist_page.select_playlist(10)
    for page in browser.pages:
        parent.addWidget(page)
    parent.resize(1100, 850)
    parent.show()
    try:
        yield browser, selection, parent
    finally:
        browser.shutdown()
        provider.shutdown()
        controller.shutdown()
        parent.close()
        theme.close()


_SURFACES = (
    (PageId.ALBUMS, AlbumGridView),
    (PageId.ARTISTS, CollectionGridView),
    (PageId.ARTISTS, AlbumGridView),
    (PageId.GENRES, CollectionGridView),
    (PageId.GENRES, AlbumGridView),
    (PageId.TRACKS, TrackTable),
    (PageId.PLAYLISTS, TrackTable),
    (PageId.PHOTOS, PhotoGridView),
)


def _item_id(view: QAbstractItemView, row: int) -> int | None:
    index = view.model().index(row, 0)
    if isinstance(view, TrackTable):
        track = index.data(TrackRole.TRACK)
        return track.track_id if isinstance(track, Track) else None
    if isinstance(view, PhotoGridView):
        photo = index.data(PhotoRole.PHOTO)
        return photo.photo_id if isinstance(photo, Photo) else None
    role = (
        AlbumRole.SUMMARY if isinstance(view, AlbumGridView) else CollectionRole.SUMMARY
    )
    summary = index.data(role)
    return (
        summary.track_ids[0]
        if isinstance(summary, (AlbumSummary, CollectionSummary))
        else None
    )


def _highlight(view: QAbstractItemView, item_ids: tuple[int, ...]) -> QPoint:
    view.clearSelection()
    first = None
    for row in range(view.model().rowCount()):
        if _item_id(view, row) in item_ids:
            index = view.model().index(row, 0)
            view.selectionModel().select(
                index,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            if first is None:
                first = index
    assert first is not None
    view.scrollTo(first)
    APPLICATION.processEvents()
    return view.visualRect(first).center()


@pytest.mark.parametrize(("page_id", "view_type"), _SURFACES)
def test_sync_context_menu_batches_highlighted_items_across_regrouping(
    sync_browser: tuple[HostLibraryBrowser, SyncSelection, QStackedWidget],
    page_id: PageId,
    view_type: type[QAbstractItemView],
) -> None:
    browser, selection, parent = sync_browser
    page = browser.page_widgets[page_id]
    parent.setCurrentWidget(page)
    APPLICATION.processEvents()
    view = page.findChild(view_type)
    assert view is not None
    if isinstance(view, TrackTable):
        view.sortByColumn(TrackColumn.TITLE, Qt.SortOrder.DescendingOrder)
    snapshot = browser.workspace.snapshot
    comparison = selection.comparison
    changes = QSignalSpy(selection.hostSelectionChanged)
    menu_labels: list[tuple[str, ...]] = []
    action_index = 0

    def choose_action() -> None:
        menu = APPLICATION.activePopupWidget()
        if isinstance(menu, QMenu):
            try:
                menu_labels.append(tuple(action.text() for action in menu.actions()))
                menu.actions()[action_index].trigger()
            finally:
                menu.close()

    point = _highlight(view, (1, 3))
    QTimer.singleShot(0, choose_action)
    view.customContextMenuRequested.emit(point)
    APPLICATION.processEvents()

    assert menu_labels == [("Select for Sync", "Deselect from Sync")]
    assert changes.count() == 1
    check_state = (
        selection.photo_check_state
        if page_id is PageId.PHOTOS
        else selection.track_check_state
    )
    target_ids = (
        (1, 2, 3) if view_type in (AlbumGridView, CollectionGridView) else (1, 3)
    )
    assert all(check_state(item_id) is Qt.CheckState.Checked for item_id in target_ids)
    assert check_state(4) is Qt.CheckState.Checked
    if 2 not in target_ids:
        assert check_state(2) is Qt.CheckState.Unchecked

    action_index = 1
    point = _highlight(view, (1, 3))
    QTimer.singleShot(0, choose_action)
    view.customContextMenuRequested.emit(point)
    APPLICATION.processEvents()
    assert changes.count() == 2
    assert all(
        check_state(item_id) is Qt.CheckState.Unchecked for item_id in target_ids
    )
    assert check_state(4) is Qt.CheckState.Checked
    assert browser.workspace.snapshot is snapshot
    assert selection.comparison is comparison
    assert not browser.workspace.dirty
    if page_id is PageId.PLAYLISTS:
        assert all(
            view.model()
            .index(row, TrackColumn.SYNC_SELECTION)
            .data(Qt.ItemDataRole.CheckStateRole)
            is Qt.CheckState.Unchecked
            for row in range(view.model().rowCount())
            if _item_id(view, row) == 1
        )


@pytest.mark.parametrize(("page_id", "view_type"), _SURFACES)
def test_sync_context_menu_retargets_unhighlighted_item_and_ignores_empty_space(
    sync_browser: tuple[HostLibraryBrowser, SyncSelection, QStackedWidget],
    page_id: PageId,
    view_type: type[QAbstractItemView],
) -> None:
    browser, selection, parent = sync_browser
    page = browser.page_widgets[page_id]
    parent.setCurrentWidget(page)
    APPLICATION.processEvents()
    view = page.findChild(view_type)
    actions = parent.findChild(SyncSelectionActions)
    assert view is not None and actions is not None
    _highlight(view, (1, 3))
    target = next(
        view.model().index(row, 0)
        for row in range(view.model().rowCount())
        if _item_id(view, row) == 4
    )
    view.scrollTo(target)
    APPLICATION.processEvents()
    point = view.visualRect(target).center()
    menu = actions.build_menu(view, point)
    assert menu is not None
    try:
        assert len(view.selectionModel().selectedRows()) == 1
        menu.actions()[1].trigger()
        assert selection.track_check_state(1) is Qt.CheckState.Checked
        assert selection.photo_check_state(1) is Qt.CheckState.Checked
        check_state = (
            selection.photo_check_state
            if page_id is PageId.PHOTOS
            else selection.track_check_state
        )
        assert check_state(4) is Qt.CheckState.Unchecked
        assert actions.build_menu(view, QPoint(-1, -1)) is None
        for row in range(view.model().rowCount()):
            index = view.model().index(row, 0)
            if index.data(SelectionGroupingRole.IS_HEADER):
                assert actions.build_menu(view, view.visualRect(index).center()) is None
                break
    finally:
        menu.deleteLater()


@pytest.mark.parametrize(
    "page_id",
    (PageId.ALBUMS, PageId.ARTISTS, PageId.GENRES, PageId.TRACKS, PageId.PLAYLISTS),
)
def test_sync_track_checkbox_toggles_the_sorted_filtered_track(
    sync_browser: tuple[HostLibraryBrowser, SyncSelection, QStackedWidget],
    page_id: PageId,
) -> None:
    browser, selection, parent = sync_browser
    page = browser.page_widgets[page_id]
    parent.setCurrentWidget(page)
    if page_id in (PageId.ALBUMS, PageId.ARTISTS, PageId.GENRES):
        grid = page.findChild(
            AlbumGridView if page_id is PageId.ALBUMS else CollectionGridView
        )
        assert grid is not None
        index = next(
            grid.model().index(row, 0)
            for row in range(grid.model().rowCount())
            if _item_id(grid, row) == 3
        )
        grid.clicked.emit(index)
    table = page.findChild(TrackTable)
    assert table is not None
    model = table.model()
    assert isinstance(model, TrackFilterProxyModel)
    table.sortByColumn(TrackColumn.TITLE, Qt.SortOrder.DescendingOrder)
    model.set_query("Track 3")
    APPLICATION.processEvents()
    assert not table.isColumnHidden(TrackColumn.SYNC_SELECTION)
    assert table.horizontalHeader().visualIndex(TrackColumn.SYNC_SELECTION) == 0
    index = model.index(0, TrackColumn.SYNC_SELECTION)
    assert index.data(TrackRole.TRACK_ID) == 3
    table.scrollTo(index)
    APPLICATION.processEvents()
    option = QStyleOptionViewItem()
    option.initFrom(table)
    delegate = table.itemDelegateForIndex(index)
    assert isinstance(delegate, QStyledItemDelegate)
    delegate.initStyleOption(option, index)
    option.rect = table.visualRect(index)
    indicator = table.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, table
    )
    assert not indicator.isEmpty()
    changes = QSignalSpy(selection.hostSelectionChanged)
    for state in (Qt.CheckState.Checked, Qt.CheckState.Unchecked):
        QTest.mouseClick(
            table.viewport(), Qt.MouseButton.LeftButton, pos=indicator.center()
        )
        assert selection.track_check_state(3) is state
        assert index.data(Qt.ItemDataRole.CheckStateRole) is state
        assert selection.track_check_state(1) is Qt.CheckState.Checked
        assert selection.track_check_state(2) is Qt.CheckState.Unchecked
        assert selection.track_check_state(4) is Qt.CheckState.Checked
    assert changes.count() == 2
    assert not browser.workspace.dirty


def test_filtered_track_menu_leaves_hidden_tracks_unchanged(
    sync_browser: tuple[HostLibraryBrowser, SyncSelection, QStackedWidget],
) -> None:
    browser, selection, parent = sync_browser
    page = browser.page_widgets[PageId.TRACKS]
    parent.setCurrentWidget(page)
    view = page.findChild(TrackTable)
    actions = parent.findChild(SyncSelectionActions)
    assert view is not None and actions is not None
    model = view.model()
    assert isinstance(model, TrackFilterProxyModel)
    model.set_query("Track 3")
    APPLICATION.processEvents()
    menu = actions.build_menu(view, _highlight(view, (3,)))
    assert menu is not None
    try:
        menu.actions()[0].trigger()
        assert selection.track_check_state(3) is Qt.CheckState.Checked
        assert selection.track_check_state(2) is Qt.CheckState.Unchecked
        assert selection.track_check_state(1) is Qt.CheckState.Checked
        assert selection.track_check_state(4) is Qt.CheckState.Checked
    finally:
        menu.deleteLater()
