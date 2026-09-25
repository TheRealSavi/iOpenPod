"""Search must preserve the active ordering of Library cards and Track rows."""

import pytest
from PySide6.QtCore import Qt

from iOpenPod.app.models.album_list_model import AlbumListModel, AlbumRole
from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionListModel,
    CollectionRole,
)
from iOpenPod.app.models.library_filter_models import (
    AlbumFilterProxyModel,
    AlbumSortMode,
    CollectionFilterProxyModel,
    CollectionSortMode,
    TrackFilterProxyModel,
)
from iOpenPod.app.models.track_table_model import (
    TrackColumn,
    TrackRole,
    TrackTableModel,
)
from iPodDB.library import Track


@pytest.fixture
def tracks() -> TrackTableModel:
    model = TrackTableModel()
    model.replace_tracks(
        (
            Track(1, "Gamma", "Beta", "Gamma", 300, year=2000, size_bytes=300),
            Track(2, "Alpha", "Gamma", "Alpha", 100, year=2020, size_bytes=100),
            Track(3, "Beta", "Alpha", "Beta", 200, year=2010, size_bytes=200),
            Track(4, "Delta", "Beta", "Delta", 300, year=2000, size_bytes=300),
            Track(5, "Gamma reprise", "Beta", "Gamma", 300, year=2000, size_bytes=300),
        )
    )
    return model


@pytest.mark.parametrize("direction", tuple(Qt.SortOrder))
@pytest.mark.parametrize("mode", tuple(AlbumSortMode))
def test_album_search_preserves_sort_order(
    tracks: TrackTableModel, mode: AlbumSortMode, direction: Qt.SortOrder
) -> None:
    albums = AlbumListModel(tracks)
    proxy = AlbumFilterProxyModel(albums)
    proxy.set_sort_mode(mode)
    proxy.set_sort_direction(direction)

    _assert_search_preserves_order(proxy, AlbumRole.SEARCH_TEXT)


@pytest.mark.parametrize("direction", tuple(Qt.SortOrder))
@pytest.mark.parametrize("mode", tuple(CollectionSortMode))
def test_collection_search_preserves_sort_order(
    tracks: TrackTableModel, mode: CollectionSortMode, direction: Qt.SortOrder
) -> None:
    collections = CollectionListModel(tracks, CollectionKind.ARTIST)
    proxy = CollectionFilterProxyModel(collections)
    proxy.set_sort_mode(mode)
    proxy.set_sort_direction(direction)

    _assert_search_preserves_order(proxy, CollectionRole.SEARCH_TEXT)


@pytest.mark.parametrize("direction", tuple(Qt.SortOrder))
@pytest.mark.parametrize(
    "column", (-1, TrackColumn.TITLE, TrackColumn.ARTIST, TrackColumn.SIZE)
)
def test_track_search_preserves_sort_order(
    tracks: TrackTableModel, column: int, direction: Qt.SortOrder
) -> None:
    proxy = TrackFilterProxyModel(tracks)
    # The table reads the initial rows before the user chooses a column sort.
    assert proxy.rowCount() == tracks.rowCount()
    proxy.sort(column, direction)

    _assert_search_preserves_order(proxy, TrackRole.SEARCH_TEXT)


def _assert_search_preserves_order(
    proxy: AlbumFilterProxyModel | CollectionFilterProxyModel | TrackFilterProxyModel,
    search_role: int,
) -> None:
    original = tuple(
        (
            proxy.mapToSource(proxy.index(row, 0)).row(),
            str(proxy.index(row, 0).data(search_role)),
        )
        for row in range(proxy.rowCount())
    )
    column, direction = proxy.sortColumn(), proxy.sortOrder()

    # Exercise narrowing, broadening, clearing, and returning from no matches.
    for query in ("gamma", "a", "", "no matching item", "", "alpha", ""):
        proxy.set_query(query)

        assert tuple(
            proxy.mapToSource(proxy.index(row, 0)).row()
            for row in range(proxy.rowCount())
        ) == tuple(row for row, text in original if query in text), query
        assert (proxy.sortColumn(), proxy.sortOrder()) == (column, direction)
