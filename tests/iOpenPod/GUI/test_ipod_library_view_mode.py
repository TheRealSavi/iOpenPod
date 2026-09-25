"""The iPod view preference reuses full-page browsing and existing Track actions."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent, QModelIndex, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel, QListView
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    IPodLibraryViewMode,
)
from iOpenPod.app.models.album_list_model import AlbumRole
from iOpenPod.app.models.collection_list_model import CollectionRole
from iOpenPod.app.models.track_table_model import TrackColumn, TrackRole
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.collection_page import CollectionPage
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.collection_detail import CollectionDetailPage
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from iOpenPod.GUI.widgets.track_list_header import LibrarySplitter
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import MediaType, Track


@pytest.fixture
def context() -> Iterator[AppContext]:
    context = build_context()
    context.track_model.reset_tracks(
        tuple(
            Track(
                offset + number,
                title,
                "Artist A" if number < 3 else "Artist B",
                "Album A" if number < 3 else "Album B",
                180_000,
                genre="Rock" if number < 3 else "Jazz",
                show="Show A" if number < 3 else "Show B",
                media_types=media_types,
            )
            for offset, media_types in (
                (0, (MediaType.AUDIO,)),
                (10, (MediaType.TV_SHOW,)),
                (20, (MediaType.MUSIC_VIDEO,)),
            )
            for number, title in (
                (1, "First Song"),
                (2, "Second Song"),
                (3, "Elsewhere"),
            )
        )
    )
    yield context
    context.shutdown()


def _page(context: AppContext, page_id: PageId) -> LibraryPage | CollectionPage:
    provider = ArtworkPixmapProvider(context.artwork_controller)
    page: LibraryPage | CollectionPage
    if page_id is PageId.ALBUMS:
        page = LibraryPage(
            context.track_model,
            context.album_model,
            context.settings,
            context.theme_manager,
            provider,
        )
    else:
        collections = {
            PageId.ARTISTS: context.artist_model,
            PageId.GENRES: context.genre_model,
            PageId.TV_SHOWS: context.tv_show_model,
            PageId.MUSIC_VIDEOS: context.music_video_model,
        }
        page = CollectionPage(
            context.track_model,
            collections[page_id],
            context.settings,
            context.theme_manager,
            provider,
            page_id=page_id,
            table_id=f"{page_id.value}-view-mode-test",
            albums=context.album_model
            if page_id in (PageId.ARTISTS, PageId.GENRES)
            else None,
        )
    provider.setParent(page)
    page.resize(1000, 760)
    page.show()
    APPLICATION.processEvents()
    return page


def _card(grid: AlbumGridView | CollectionGridView, title: str) -> QModelIndex:
    role = AlbumRole.TITLE if isinstance(grid, AlbumGridView) else CollectionRole.TITLE
    return next(
        index
        for row in range(grid.model().rowCount())
        if (index := grid.model().index(row, 0)).data(role) == title
    )


def _click(grid: AlbumGridView | CollectionGridView, title: str) -> None:
    index = _card(grid, title)
    grid.scrollTo(index)
    grid.doItemsLayout()
    APPLICATION.processEvents()
    QTest.mouseClick(
        grid.viewport(), Qt.MouseButton.LeftButton, pos=grid.visualRect(index).center()
    )
    APPLICATION.processEvents()


def _ids(table: TrackTable) -> set[int]:
    return {
        table.model().index(row, 0).data(TrackRole.TRACK_ID)
        for row in range(table.model().rowCount())
    }


@pytest.mark.parametrize("saved", (False, True))
@pytest.mark.parametrize(
    ("page_id", "title", "ids"),
    (
        (PageId.ALBUMS, "Album A", {1, 2}),
        (PageId.ARTISTS, "Artist A", {1, 2}),
        (PageId.GENRES, "Rock", {1, 2}),
        (PageId.TV_SHOWS, "Show A", {11, 12}),
        (PageId.MUSIC_VIDEOS, "Album A", {21, 22}),
    ),
)
def test_saved_and_live_modes_keep_table_search_navigation_and_activation(
    context: AppContext, saved: bool, page_id: PageId, title: str, ids: set[int]
) -> None:
    if saved:
        context.settings.set_global(
            IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
        )
    page = _page(context, page_id)
    grid = page.findChild(
        AlbumGridView if page_id is PageId.ALBUMS else CollectionGridView
    )
    table = page.findChild(TrackTable)
    toolbar = page.findChild(LibraryToolbar)
    assert isinstance(grid, (AlbumGridView, CollectionGridView))
    assert table is not None and toolbar is not None
    activated = QSignalSpy(page.trackActivated)
    table.setColumnWidth(TrackColumn.TITLE, 321)
    table.sortByColumn(TrackColumn.TITLE, Qt.SortOrder.DescendingOrder)
    if not saved:
        assert grid.isVisible() and table.isVisible()
        _click(grid, title)
        assert _ids(table) == ids and grid.isVisible()
        context.settings.set_global(
            IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
        )
    APPLICATION.processEvents()
    assert grid.isVisible() and not table.isVisible()
    browser_search = toolbar.findChild(SearchField)
    assert browser_search is not None
    browser_search.setText(title)
    QTest.qWait(220)
    for visit in range(2):
        _click(grid, title)
        detail = page.findChild(CollectionDetailPage)
        assert detail is not None and detail.isVisible()
        assert detail.findChild(TrackTable) is table
        assert not grid.isVisible() and not toolbar.isVisible()
        assert _ids(table) == ids
        assert table.isColumnHidden(TrackColumn.SYNC_SELECTION)
        assert table.columnWidth(TrackColumn.TITLE) == 321
        assert (
            table.horizontalHeader().sortIndicatorOrder()
            is Qt.SortOrder.DescendingOrder
        )
        for name in ("collectionDetailSelectAll", "collectionDetailDeselectAll"):
            button = detail.findChild(ActionButton, name)
            assert button is not None and not button.isVisible()
        search = detail.findChild(SearchField)
        assert search is not None and search.text() == ""
        search.setText("Second Song")
        QTest.qWait(220)
        assert _ids(table) == {max(ids)}
        table.doubleClicked.emit(table.model().index(0, TrackColumn.TITLE))
        assert activated.count() > 0
        if visit == 0:
            detail.backRequested.emit()
            assert grid.isVisible() and browser_search.text() == title
            assert not table.isVisible()
        context.settings.reset_global(IPOD_LIBRARY_VIEW_MODE)
        APPLICATION.processEvents()
        assert grid.isVisible() and table.isVisible() and not detail.isVisible()
        assert _ids(table) == ids
        splitter = page.findChild(LibrarySplitter)
        assert splitter is not None and splitter.isVisible()
        header_search = splitter.track_header.findChild(SearchField)
        assert header_search is not None and header_search.text() == ""
        context.settings.set_global(
            IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
        )
        APPLICATION.processEvents()
    _click(grid, title)
    context.track_model.reset_tracks(context.track_model.tracks)
    APPLICATION.processEvents()
    assert grid.isVisible() and not table.isVisible()
    page.close()


@pytest.mark.parametrize("page_id", (PageId.ARTISTS, PageId.GENRES))
def test_list_view_album_navigation_retains_source_rail(
    context: AppContext, page_id: PageId
) -> None:
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
    )
    page = _page(context, page_id)
    assert isinstance(page, CollectionPage)
    page.set_view_mode("list")
    source = page.findChild(QListView, f"{page_id.value}CollectionList")
    grid = page.findChild(AlbumGridView)
    assert source is not None and grid is not None
    title = "Artist A" if page_id is PageId.ARTISTS else "Rock"
    index = next(
        source.model().index(row, 0)
        for row in range(source.model().rowCount())
        if source.model().index(row, 0).data(CollectionRole.TITLE) == title
    )
    source.setCurrentIndex(index)
    _click(grid, "Album A")
    detail = page.findChild(CollectionDetailPage)
    table = page.findChild(TrackTable)
    assert detail is not None and table is not None
    assert detail.isVisible() and _ids(table) == {1, 2}
    detail.backRequested.emit()
    assert source.isVisible() and grid.isVisible() and source.currentIndex() == index
    grid.setCurrentIndex(_card(grid, "Album A"))
    grid.setFocus()
    QTest.keyClick(grid, Qt.Key.Key_Return)
    assert detail.isVisible()
    page.close()


def test_settings_offer_exact_modes_and_preserve_choice_on_retranslation(
    context: AppContext,
) -> None:
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    combo = page.findChild(AppComboBox, "ipodLibraryViewModeCombo")
    assert combo is not None
    assert any(
        label.text() == "iPod Library View Mode" for label in page.findChildren(QLabel)
    )
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Split Table",
        "Whole Page Table",
    ]
    assert combo.currentData() == IPodLibraryViewMode.SPLIT_TABLE.value
    combo.setCurrentIndex(1)
    assert (
        context.settings.get(IPOD_LIBRARY_VIEW_MODE)
        == IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
    )
    APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
    assert combo.currentData() == IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
    context.settings.reset_global(IPOD_LIBRARY_VIEW_MODE)
    assert combo.currentData() == IPodLibraryViewMode.SPLIT_TABLE.value
    page.close()
