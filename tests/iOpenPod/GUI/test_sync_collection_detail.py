"""Sync cards navigate to source-isolated collection pages without a Track splitter."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QLabel,
    QListView,
    QStackedWidget,
    QStyleOptionViewItem,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.album_list_model import AlbumRole
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.models.collection_list_model import CollectionRole
from iOpenPod.app.models.selection_grouping import (
    SelectionGroup,
    SelectionGroupingProxyModel,
)
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.models.track_table_model import TrackColumn, TrackRole
from iOpenPod.app.sync_plan import SyncPlan
from iOpenPod.GUI.host_library_browser import HostLibraryBrowser
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.collection_page import CollectionPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.selection_checkbox import library_card_checkbox_rect
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.collection_detail import CollectionDetailPage
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.sync_selection_actions import SyncSelectionActions
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from iOpenPod.GUI.widgets.track_list_header import LibrarySplitter, TrackListHeader
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import LibrarySnapshot, MediaType, Track, TrackMetadata


class _EmptyArtworkLoader:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        return None


type SyncBrowser = tuple[
    HostLibraryBrowser, SyncSelection, QStackedWidget, ThemeManager
]


@pytest.fixture
def browser() -> Iterator[SyncBrowser]:
    tracks = tuple(
        Track(
            offset + number,
            title,
            "Artist A" if number < 3 else "Artist B",
            "Album A" if number < 3 else "Album B",
            180_000,
            genre="Rock" if number < 3 else "Jazz",
            year=2018,
            size_bytes=4_000_000,
            media_types=media_types,
            show="Show A" if number < 3 else "Show B",
            metadata=TrackMetadata(location=f"C:/Media/{offset + number}.mp3"),
        )
        for offset, media_types in (
            (0, (MediaType.AUDIO,)),
            (10, (MediaType.TV_SHOW,)),
            (20, (MediaType.MUSIC_VIDEO,)),
        )
        for number, title in ((1, "First Song"), (2, "Second Song"), (3, "Elsewhere"))
    )
    library = HostMediaLibrary(
        LibrarySnapshot(tracks), (), (), HostMediaCacheStats(inspected=9)
    )
    selection = SyncSelection()
    selection.reset(library, SyncPlan(()))
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    controller = ArtworkController(_EmptyArtworkLoader())
    provider = ArtworkPixmapProvider(controller)
    parent = QStackedWidget()
    host = HostLibraryBrowser(
        settings, theme, provider, LibraryWorkspace(), parent, selection
    )
    host.load(library)
    for page in host.pages:
        parent.addWidget(page)
    parent.resize(1000, 760)
    parent.show()
    APPLICATION.processEvents()
    try:
        yield host, selection, parent, theme
    finally:
        host.shutdown()
        provider.shutdown()
        controller.shutdown()
        parent.close()
        theme.close()


def _card(grid: AlbumGridView | CollectionGridView, title: str) -> QModelIndex:
    role = AlbumRole.TITLE if isinstance(grid, AlbumGridView) else CollectionRole.TITLE
    return next(
        grid.model().index(row, 0)
        for row in range(grid.model().rowCount())
        if grid.model().index(row, 0).data(role) == title
    )


def _click_card(grid: AlbumGridView | CollectionGridView, title: str) -> None:
    index = _card(grid, title)
    grid.scrollTo(index)
    grid.doItemsLayout()
    APPLICATION.processEvents()
    QTest.mouseClick(
        grid.viewport(), Qt.MouseButton.LeftButton, pos=grid.visualRect(index).center()
    )
    APPLICATION.processEvents()


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
def test_card_opens_full_page_with_search_and_stable_sync_selection(
    browser: SyncBrowser, page_id: PageId, title: str, ids: set[int]
) -> None:
    host, selection, parent, _theme = browser
    page = host.page_widgets[page_id]
    parent.setCurrentWidget(page)
    APPLICATION.processEvents()
    grid = page.findChild(
        AlbumGridView if page_id is PageId.ALBUMS else CollectionGridView
    )
    detail = page.findChild(CollectionDetailPage)
    table = page.findChild(TrackTable)
    toolbar = page.findChild(LibraryToolbar)
    assert (
        isinstance(grid, AlbumGridView | CollectionGridView)
        and detail is not None
        and table is not None
        and toolbar is not None
    )
    assert grid.isVisible() and not table.isVisible()
    assert page.findChild(LibrarySplitter) is None
    assert page.findChild(TrackListHeader) is None
    snapshot = host.workspace.snapshot
    comparison = selection.comparison

    _click_card(grid, title)

    assert detail.isVisible() and table.isVisible()
    assert not grid.isVisible() and not toolbar.isVisible()
    heading = detail.findChild(QLabel, "pageTitle")
    assert heading is not None and heading.text() == title
    assert {
        table.model().index(row, 0).data(TrackRole.TRACK_ID)
        for row in range(table.model().rowCount())
    } == ids
    search = detail.findChild(SearchField)
    assert search is not None
    search.setText("Second Song")
    QTest.qWait(220)
    assert table.model().rowCount() == 1
    assert table.model().index(0, 0).data(TrackRole.TRACK_ID) == max(ids)

    changes = QSignalSpy(selection.hostSelectionChanged)
    for button_name, state in (
        ("collectionDetailSelectAll", Qt.CheckState.Checked),
        ("collectionDetailDeselectAll", Qt.CheckState.Unchecked),
    ):
        button = detail.findChild(ActionButton, button_name)
        assert button is not None
        button.click()
        APPLICATION.processEvents()
        assert all(selection.track_check_state(track_id) is state for track_id in ids)
        assert detail.isVisible() and table.model().rowCount() == 1
    assert changes.count() == 2
    assert selection.track_check_state(3) is Qt.CheckState.Unchecked
    assert host.workspace.snapshot is snapshot and selection.comparison is comparison

    actions = parent.findChild(SyncSelectionActions)
    assert actions is not None
    menu = actions.build_menu(
        table, table.visualRect(table.model().index(0, 0)).center()
    )
    assert menu is not None
    try:
        menu.actions()[0].trigger()
        assert selection.track_check_state(max(ids)) is Qt.CheckState.Checked
        assert selection.track_check_state(min(ids)) is Qt.CheckState.Unchecked
        menu.actions()[1].trigger()
        assert selection.track_check_state(max(ids)) is Qt.CheckState.Unchecked
        assert detail.isVisible() and table.model().rowCount() == 1
    finally:
        menu.deleteLater()

    index = table.model().index(0, TrackColumn.SYNC_SELECTION)
    assert table.model().setData(
        index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
    )
    assert selection.track_check_state(max(ids)) is Qt.CheckState.Checked
    assert detail.isVisible() and table.model().rowCount() == 1

    back = detail.findChild(ActionButton, "collectionDetailBack")
    assert back is not None
    back.click()
    assert grid.isVisible() and toolbar.isVisible() and not table.isVisible()
    _click_card(grid, title)
    assert detail.isVisible() and search.text() == "" and table.model().rowCount() == 2


def test_grid_checkbox_and_modified_click_do_not_navigate(browser: SyncBrowser) -> None:
    host, selection, parent, theme = browser
    page = host.page_widgets[PageId.ALBUMS]
    parent.setCurrentWidget(page)
    APPLICATION.processEvents()
    grid = page.findChild(AlbumGridView)
    detail = page.findChild(CollectionDetailPage)
    assert grid is not None and detail is not None
    index = _card(grid, "Album A")
    option = QStyleOptionViewItem()
    option.initFrom(grid)
    option.font = grid.font()
    option.rect = grid.visualRect(index)
    point = library_card_checkbox_rect(option, theme.typography).center().toPoint()
    QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, pos=point)
    APPLICATION.processEvents()
    assert selection.track_check_state(1) is Qt.CheckState.Checked
    assert grid.isVisible() and not detail.isVisible()
    index = _card(grid, "Album A")
    QTest.mouseClick(
        grid.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        grid.visualRect(index).center(),
    )
    assert grid.isVisible() and not detail.isVisible()
    grid.setCurrentIndex(index)
    grid.setFocus()
    QTest.keyClick(grid, Qt.Key.Key_Return)
    assert detail.isVisible()


def test_back_retains_grid_query_and_new_scan_closes_detail(
    browser: SyncBrowser,
) -> None:
    host, _selection, parent, _theme = browser
    page = host.page_widgets[PageId.ALBUMS]
    parent.setCurrentWidget(page)
    toolbar = page.findChild(LibraryToolbar)
    grid = page.findChild(AlbumGridView)
    detail = page.findChild(CollectionDetailPage)
    assert toolbar is not None and grid is not None and detail is not None
    search = toolbar.findChild(SearchField)
    assert search is not None
    search.setText("Album A")
    QTest.qWait(220)
    _click_card(grid, "Album A")
    detail.backRequested.emit()
    assert search.text() == "Album A" and grid.isVisible()
    _click_card(grid, "Album A")
    assert host.library is not None
    host.load(host.library)
    assert grid.isVisible() and not detail.isVisible()


@pytest.mark.parametrize("checked", (False, True))
@pytest.mark.parametrize("album_count, target", ((30, 16), (240, 160)))
def test_grouped_album_checkbox_preserves_scroll_position(
    browser: SyncBrowser, checked: bool, album_count: int, target: int
) -> None:
    host, selection, parent, theme = browser
    assert host.library is not None
    library = replace(
        host.library,
        snapshot=LibrarySnapshot(
            tuple(
                replace(
                    host.library.snapshot.tracks[0],
                    track_id=number,
                    album=f"Album {number:03}",
                )
                for number in range(album_count)
            )
        ),
    )
    selection.reset(library, SyncPlan(()))
    if checked:
        selection.set_tracks_checked(tuple(range(album_count)), True)
    host.load(library)
    parent.setCurrentWidget(host.page_widgets[PageId.ALBUMS])
    grid = host.page_widgets[PageId.ALBUMS].findChild(AlbumGridView)
    assert grid is not None and grid.sectioned_layout
    QTest.qWait(100)
    index = _card(grid, f"Album {target:03}")
    grid.scrollTo(index, QListView.ScrollHint.PositionAtCenter)
    APPLICATION.processEvents()
    scrollbar = grid.verticalScrollBar()
    before = scrollbar.value()
    assert before > 0
    option = QStyleOptionViewItem()
    option.initFrom(grid)
    option.font = grid.font()
    option.rect = grid.visualRect(index)
    point = library_card_checkbox_rect(option, theme.typography).center().toPoint()
    assert grid.viewport().rect().contains(point)
    QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.qWait(30)
    assert selection.track_check_state(target) is (
        Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
    )
    assert scrollbar.value() == before

    # Preserve only the temporary batch range, never a range the content has
    # actually outgrown: collapsing both groups must still return to the top.
    model = grid.model()
    assert isinstance(model, SelectionGroupingProxyModel)
    model.set_expanded(SelectionGroup.SELECTED, False)
    model.set_expanded(SelectionGroup.DESELECTED, False)
    QTest.qWait(30)
    assert scrollbar.maximum() == 0
    assert scrollbar.value() == 0


@pytest.mark.parametrize("page_id", (PageId.ARTISTS, PageId.GENRES))
def test_list_browser_album_opens_detail_and_returns_to_list(
    browser: SyncBrowser, page_id: PageId
) -> None:
    host, _selection, parent, _theme = browser
    page = host.page_widgets[page_id]
    assert isinstance(page, CollectionPage)
    parent.setCurrentWidget(page)
    page.set_view_mode("list")
    rail = page.findChild(QListView, f"{page_id.value}CollectionList")
    grid = page.findChild(AlbumGridView)
    detail = page.findChild(CollectionDetailPage)
    assert rail is not None and grid is not None and detail is not None
    index = next(
        rail.model().index(row, 0)
        for row in range(rail.model().rowCount())
        if rail.model().index(row, 0).data(CollectionRole.TITLE) in ("Artist A", "Rock")
    )
    rail.setCurrentIndex(index)
    APPLICATION.processEvents()
    _click_card(grid, "Album A")
    assert detail.isVisible() and not rail.isVisible()
    detail.backRequested.emit()
    assert grid.isVisible() and rail.isVisible()


def test_genre_album_bulk_selection_respects_its_scoped_tracks(
    browser: SyncBrowser,
) -> None:
    host, selection, parent, _theme = browser
    assert host.library is not None
    library = replace(
        host.library,
        snapshot=LibrarySnapshot(
            tuple(
                replace(track, genre="Other") if track.track_id == 2 else track
                for track in host.library.snapshot.tracks
            )
        ),
    )
    selection.reset(library, SyncPlan(()))
    host.load(library)
    page = host.page_widgets[PageId.GENRES]
    assert isinstance(page, CollectionPage)
    parent.setCurrentWidget(page)
    page.set_view_mode("list")
    rail = page.findChild(QListView, "genresCollectionList")
    grid = page.findChild(AlbumGridView)
    detail = page.findChild(CollectionDetailPage)
    assert rail is not None and grid is not None and detail is not None
    rail.setCurrentIndex(
        next(
            rail.model().index(row, 0)
            for row in range(rail.model().rowCount())
            if rail.model().index(row, 0).data(CollectionRole.TITLE) == "Rock"
        )
    )
    APPLICATION.processEvents()
    _click_card(grid, "Album A")
    table = detail.findChild(TrackTable)
    select_all = detail.findChild(ActionButton, "collectionDetailSelectAll")
    assert table is not None and table.model().rowCount() == 1
    assert select_all is not None
    select_all.click()
    assert selection.track_check_state(1) is Qt.CheckState.Checked
    assert selection.track_check_state(2) is Qt.CheckState.Unchecked


def _detail_rect(widget: QWidget, detail: CollectionDetailPage) -> QRect:
    return QRect(widget.mapTo(detail, QPoint()), widget.size())


def _artwork_quadrants(art: ArtworkView) -> tuple[str, ...]:
    rendered = art.grab().toImage()
    return tuple(
        rendered.pixelColor(
            rendered.width() * column // 4, rendered.height() * row // 4
        ).name()
        for row in (1, 3)
        for column in (1, 3)
    )


class _PaintObserver(QObject):
    paints = 0

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Paint:
            self.paints += 1
        return False


@pytest.mark.parametrize("page_id", (PageId.ARTISTS, PageId.GENRES))
@pytest.mark.parametrize("item_count", (1, 2, 4))
def test_opened_collection_preserves_all_four_artwork_tiles(
    browser: SyncBrowser,
    monkeypatch: pytest.MonkeyPatch,
    page_id: PageId,
    item_count: int,
) -> None:
    host, selection, parent, theme = browser
    assert host.library is not None
    colors = ("#ff0000", "#00ff00", "#0000ff", "#ffff00")
    covers: dict[int, QPixmap] = {}
    for artwork_id, color in enumerate(colors, 1):
        cover = QPixmap(16, 16)
        cover.fill(QColor(color))
        covers[artwork_id] = cover

    def pixmap(
        _provider: ArtworkPixmapProvider,
        artwork_id: int,
        _logical_size: int,
        _device_pixel_ratio: float,
    ) -> QPixmap | None:
        return covers.get(artwork_id)

    monkeypatch.setattr(ArtworkPixmapProvider, "pixmap", pixmap)
    library = replace(
        host.library,
        snapshot=LibrarySnapshot(
            tuple(
                replace(
                    host.library.snapshot.tracks[0],
                    track_id=number,
                    album=f"Album {number}",
                    artwork_id=number,
                )
                for number in range(1, item_count + 1)
            )
        ),
    )
    selection.reset(library, SyncPlan(()))
    host.load(library)
    page = host.page_widgets[page_id]
    assert isinstance(page, CollectionPage)
    parent.setCurrentWidget(page)
    grid = page.findChild(CollectionGridView)
    detail = page.findChild(CollectionDetailPage)
    assert grid is not None and detail is not None
    title = "Artist A" if page_id is PageId.ARTISTS else "Rock"
    index = _card(grid, title)
    assert index.data(CollectionRole.ARTWORK_IDS) == tuple(range(1, item_count + 1)) + (
        0,
    ) * (4 - item_count)
    _click_card(grid, title)
    art = detail.findChild(ArtworkView)
    assert art is not None
    expected = colors[:item_count] + (theme.tokens.surface_alt.lower(),) * (
        4 - item_count
    )
    assert _artwork_quadrants(art) == expected
    assert art.accessibleName() == "Collection artwork"

    # A newly available non-leading tile must repaint without another navigation.
    APPLICATION.processEvents()
    observer = _PaintObserver()
    art.installEventFilter(observer)
    covers[item_count].fill(QColor("#00ffff"))
    host.artwork_provider.artworkChanged.emit(item_count)
    QTest.qWait(20)
    assert observer.paints > 0
    changed = list(expected)
    changed[item_count - 1] = "#00ffff"
    assert _artwork_quadrants(art) == tuple(changed)

    # The shared detail instance must return to a single cover for an Album.
    detail.backRequested.emit()
    page.set_view_mode("list")
    albums = page.findChild(AlbumGridView)
    assert albums is not None
    _click_card(albums, "Album 1")
    assert _artwork_quadrants(art) == (covers[1].toImage().pixelColor(0, 0).name(),) * 4
    assert art.accessibleName() == "Album artwork"

    detail.backRequested.emit()
    page.set_view_mode("grid")
    _click_card(grid, title)
    assert _artwork_quadrants(art) == tuple(changed)


@pytest.mark.parametrize(
    "direction", (Qt.LayoutDirection.LeftToRight, Qt.LayoutDirection.RightToLeft)
)
def test_detail_header_uses_shared_edges_and_one_track_toolbar(
    browser: SyncBrowser, direction: Qt.LayoutDirection
) -> None:
    host, _selection, parent, _theme = browser
    page = host.page_widgets[PageId.ALBUMS]
    parent.setCurrentWidget(page)
    page.setLayoutDirection(direction)
    grid = page.findChild(AlbumGridView)
    detail = page.findChild(CollectionDetailPage)
    assert grid is not None and detail is not None
    _click_card(grid, "Album A")
    art = detail.findChild(ArtworkView)
    back = detail.findChild(ActionButton, "collectionDetailBack")
    select = detail.findChild(ActionButton, "collectionDetailSelectAll")
    search = detail.findChild(SearchField)
    table = detail.findChild(TrackTable)
    assert all(widget is not None for widget in (art, back, select, search, table))
    assert art is not None and back is not None and select is not None
    assert search is not None and table is not None
    art_rect, back_rect, select_rect, search_rect, table_rect = (
        _detail_rect(widget, detail) for widget in (art, back, select, search, table)
    )
    assert table_rect.left() == LAYOUT.space_lg
    assert detail.width() - table_rect.right() - 1 == LAYOUT.space_lg
    if direction is Qt.LayoutDirection.LeftToRight:
        assert (
            art_rect.left()
            == back_rect.left()
            == select_rect.left()
            == table_rect.left()
        )
        assert search_rect.right() == table_rect.right()
    else:
        assert (
            art_rect.right()
            == back_rect.right()
            == select_rect.right()
            == table_rect.right()
        )
        assert search_rect.left() == table_rect.left()
    assert abs(select_rect.center().y() - search_rect.center().y()) <= 1
    assert select_rect.top() > art_rect.bottom()
    assert table_rect.top() > max(select_rect.bottom(), search_rect.bottom())


@pytest.mark.parametrize("width", (320, 375, 414, 768))
def test_detail_header_reflows_long_text_without_clipping(
    browser: SyncBrowser, width: int
) -> None:
    host, _selection, parent, _theme = browser
    page = host.page_widgets[PageId.ALBUMS]
    parent.setCurrentWidget(page)
    grid = page.findChild(AlbumGridView)
    detail = page.findChild(CollectionDetailPage)
    assert grid is not None and detail is not None
    _click_card(grid, "Album A")
    title = detail.findChild(QLabel, "pageTitle")
    table = detail.findChild(TrackTable)
    search = detail.findChild(SearchField)
    assert title is not None and table is not None and search is not None
    title.setText("An Album Title Long Enough to Wrap Across Several Lines")
    title_font = title.font()
    title_font.setPointSizeF(title_font.pointSizeF() * 1.5)
    title.setFont(title_font)
    original_parent = detail.parentWidget()
    detail.setParent(None)
    try:
        detail.resize(width, 1400)
        detail.show()
        QTest.qWait(10)
        assert detail.width() == width
        header_controls: list[QWidget] = [*detail.findChildren(ActionButton), search]
        for widget in header_controls:
            rect = _detail_rect(widget, detail)
            assert rect.left() >= LAYOUT.space_lg
            assert rect.right() < width - LAYOUT.space_lg
            assert rect.bottom() < table.y()
            assert widget.width() >= widget.minimumSizeHint().width()
        labels = [label for label in detail.findChildren(QLabel) if label.wordWrap()]
        for label in labels:
            assert label.height() >= label.heightForWidth(label.width())
        for index, first in enumerate(header_controls):
            assert all(
                not _detail_rect(first, detail).intersects(_detail_rect(second, detail))
                for second in header_controls[index + 1 :]
            )
        detail.resize(1200, 900)
        QTest.qWait(10)
        select = detail.findChild(ActionButton, "collectionDetailSelectAll")
        assert select is not None
        assert (
            abs(
                _detail_rect(select, detail).center().y()
                - search.geometry().center().y()
            )
            <= 1
        )
    finally:
        detail.close()
        detail.setParent(original_parent)
