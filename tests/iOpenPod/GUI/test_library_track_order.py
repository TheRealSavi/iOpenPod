"""Default Track ordering across Album and collection browsers."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QModelIndex, Qt
from tests.iOpenPod.GUI.application_shell_test_support import build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.models.album_list_model import AlbumRole
from iOpenPod.app.models.collection_list_model import CollectionRole
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.track_table_model import TrackColumn, TrackRole
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.collection_page import CollectionPage
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import Track, TrackMetadata

type _Browsers = tuple[AppContext, LibraryPage, CollectionPage]


@pytest.fixture
def browsers() -> Iterator[_Browsers]:
    context = build_context()
    provider = ArtworkPixmapProvider(context.artwork_controller)
    albums = LibraryPage(
        context.track_model,
        context.album_model,
        context.settings,
        context.theme_manager,
        provider,
    )
    artists = CollectionPage(
        context.track_model,
        context.artist_model,
        context.settings,
        context.theme_manager,
        provider,
        page_id=PageId.ARTISTS,
        table_id="artists-order-test",
        albums=context.album_model,
    )
    # Reverse source order exposes every tie-breaker, numeric ordering, and casing.
    context.track_model.reset_tracks(
        tuple(
            Track(
                track_id,
                title,
                "Other" if track_id == 9 else "Artist",
                album,
                1_000,
                track_number=number,
                metadata=TrackMetadata(disc_number=disc),
            )
            for track_id, album, disc, number, title in reversed(
                (
                    (1, "", 0, 0, ""),
                    (2, "alpha", 0, 0, "Missing numbers"),
                    (3, "alpha", 1, 2, "alpha"),
                    (4, "ALPHA", 1, 2, "Zulu"),
                    (5, "alpha", 1, 10, "Early"),
                    (6, "alpha", 2, 1, "Start"),
                    (7, "alpha", 10, 1, "Start"),
                    (8, "Zulu", 0, 0, "First"),
                    (9, "Zulu", 1, 1, "Last"),
                )
            )
        )
    )
    try:
        yield context, albums, artists
    finally:
        albums.close()
        artists.close()
        provider.shutdown()
        context.shutdown()


def test_album_tracks_follow_disc_number_track_number_then_title(
    browsers: _Browsers,
) -> None:
    context, albums, _artists = browsers
    table = _table(albums)
    grid = albums.findChild(AlbumGridView)
    assert grid is not None

    assert _track_ids(table) == tuple(range(1, 10))
    grid.setCurrentIndex(_album_index(grid, "alpha"))
    assert _track_ids(table) == (2, 3, 4, 5, 6, 7)
    grid.setCurrentIndex(_album_index(grid, "Zulu"))
    assert _track_ids(table) == (8,)
    albums.show_all_tracks()
    assert _track_ids(table) == tuple(range(1, 10))
    assert tuple(track.track_id for track in context.track_model.tracks) == tuple(
        range(9, 0, -1)
    )


def test_collection_tracks_keep_album_order_through_filter_changes(
    browsers: _Browsers,
) -> None:
    _context, _albums, artists = browsers
    table = _table(artists)
    grid = artists.findChild(CollectionGridView)
    album_grid = artists.findChild(AlbumGridView)
    assert grid is not None and album_grid is not None

    assert _track_ids(table) == tuple(range(1, 10))
    artist = grid.model().index(0, 0)
    assert artist.data(CollectionRole.TITLE) == "Artist"
    grid.setCurrentIndex(artist)
    assert _track_ids(table) == tuple(range(1, 9))
    album_grid.setCurrentIndex(_album_index(album_grid, "alpha"))
    assert _track_ids(table) == (2, 3, 4, 5, 6, 7)
    album_grid.setCurrentIndex(QModelIndex())
    assert _track_ids(table) == tuple(range(1, 9))
    artists.show_all()
    assert _track_ids(table) == tuple(range(1, 10))

    proxy = table.model()
    assert isinstance(proxy, TrackFilterProxyModel)
    proxy.set_query("Zulu")
    assert _track_ids(table) == (4, 8, 9)
    proxy.set_query("")
    assert _track_ids(table) == tuple(range(1, 10))


@pytest.mark.parametrize("retained_column", [-1, TrackColumn.TITLE])
def test_saved_sort_overrides_default_and_reset_restores_album_order(
    browsers: _Browsers, retained_column: int
) -> None:
    context, albums, _artists = browsers
    original = _table(albums)
    original.sortByColumn(retained_column, Qt.SortOrder.DescendingOrder)
    original.setColumnWidth(TrackColumn.TITLE, 321)
    original.save_layout()
    provider = ArtworkPixmapProvider(context.artwork_controller)
    restored = LibraryPage(
        context.track_model,
        context.album_model,
        context.settings,
        context.theme_manager,
        provider,
    )
    try:
        table = _table(restored)
        header = table.horizontalHeader()
        assert table.columnWidth(TrackColumn.TITLE) == 321
        if retained_column == -1:
            assert header.sortIndicatorSection() == TrackColumn.ALBUM
            assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
            assert _track_ids(table) == tuple(range(1, 10))
        else:
            assert header.sortIndicatorSection() == TrackColumn.TITLE
            assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
            assert _track_ids(table)[0] == 4
        table.sortByColumn(TrackColumn.ALBUM, Qt.SortOrder.DescendingOrder)
        assert _track_ids(table) == tuple(range(9, 0, -1))
        table.reset_layout()
        assert _track_ids(table) == tuple(range(1, 10))
    finally:
        restored.close()
        provider.shutdown()


def _table(page: LibraryPage | CollectionPage) -> TrackTable:
    table = page.findChild(TrackTable)
    assert table is not None
    return table


def _track_ids(table: TrackTable) -> tuple[int, ...]:
    model = table.model()
    return tuple(
        model.index(row, 0).data(TrackRole.TRACK_ID) for row in range(model.rowCount())
    )


def _album_index(grid: AlbumGridView, title: str) -> QModelIndex:
    model = grid.model()
    return next(
        index
        for row in range(model.rowCount())
        if (index := model.index(row, 0)).data(AlbumRole.TITLE) == title
        and index.data(AlbumRole.ARTIST) == "Artist"
    )
