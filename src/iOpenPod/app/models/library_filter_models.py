"""Filtering and sorting projections for library item views."""

from enum import StrEnum

from PySide6.QtCore import (
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from iOpenPod.app.models.album_list_model import AlbumListModel, AlbumRole
from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionListModel,
    CollectionRole,
    collection_key_for_track,
)
from iOpenPod.app.models.filter_compat import end_rows_filter_change
from iOpenPod.app.models.track_order import album_track_sort_key
from iOpenPod.app.models.track_table_model import (
    TrackColumn,
    TrackRole,
    TrackTableModel,
)
from iPodDB.library import MediaKind, Track


class AlbumSortMode(StrEnum):
    """Stable album sorting choices; display labels remain translated."""

    TITLE = "title"
    ARTIST = "artist"
    YEAR = "year"


class CollectionSortMode(StrEnum):
    """Stable aggregate sorting choices for collection browsers."""

    TITLE = "title"
    ITEM_COUNT = "item_count"
    TRACK_COUNT = "track_count"
    DURATION = "duration"


class TrackFilterProxyModel(QSortFilterProxyModel):
    """Filter one Track model by album and cached search text."""

    def __init__(
        self,
        source: TrackTableModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._query = ""
        self._album_key: str | None = None
        self._collection_kind: CollectionKind | None = None
        self._collection_key: str | None = None
        self._media_kinds: frozenset[MediaKind] | None = None
        self.setSourceModel(source)
        self.setSortRole(TrackRole.SORT_VALUE)
        self.setDynamicSortFilter(False)

    def set_query(self, query: str) -> None:
        normalized = query.strip().casefold()
        if normalized == self._query:
            return
        self.beginFilterChange()
        self._query = normalized
        end_rows_filter_change(self)
        # Dynamic sorting is disabled; rebuild the ordering when rows return.
        self.invalidate()

    def set_album_key(self, album_key: str | None) -> None:
        if album_key == self._album_key:
            return
        self.beginFilterChange()
        self._album_key = album_key
        end_rows_filter_change(self)
        self.invalidate()

    def set_collection_key(
        self,
        kind: CollectionKind | None,
        key: str | None,
    ) -> None:
        normalized_kind = kind if key is not None else None
        normalized_key = key if kind is not None else None
        if (
            normalized_kind is self._collection_kind
            and normalized_key == self._collection_key
        ):
            return
        self.beginFilterChange()
        self._collection_kind = normalized_kind
        self._collection_key = normalized_key
        end_rows_filter_change(self)
        self.invalidate()

    def set_media_kinds(self, kinds: tuple[MediaKind, ...] | None) -> None:
        normalized = frozenset(kinds) if kinds is not None else None
        if normalized == self._media_kinds:
            return
        self.beginFilterChange()
        self._media_kinds = normalized
        end_rows_filter_change(self)

    def track_at(self, index: QModelIndex) -> Track | None:
        if not index.isValid():
            return None
        return self._source.track_at(self.mapToSource(index).row())

    def lessThan(
        self,
        left: QModelIndex | QPersistentModelIndex,
        right: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if left.column() == TrackColumn.ALBUM:
            left_track = self._source.track_at(left.row())
            right_track = self._source.track_at(right.row())
            if left_track is not None and right_track is not None:
                return album_track_sort_key(left_track) < album_track_sort_key(
                    right_track
                )
        return super().lessThan(left, right)

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        index = self._source.index(source_row, 0, source_parent)
        track = self._source.track_at(source_row)
        if track is None:
            return False
        if self._media_kinds is not None and track.media_kind not in self._media_kinds:
            return False
        if (
            self._collection_kind is not None
            and self._collection_key is not None
            and collection_key_for_track(track, self._collection_kind)
            != self._collection_key
        ):
            return False
        if self._album_key is not None:
            album_key = self._source.data(index, TrackRole.ALBUM_KEY)
            if album_key != self._album_key:
                return False
        if self._query:
            search_text = self._source.data(index, TrackRole.SEARCH_TEXT)
            return isinstance(search_text, str) and self._query in search_text
        return True


class AlbumFilterProxyModel(QSortFilterProxyModel):
    """Filter and sort album summaries without rebuilding grid items."""

    def __init__(
        self,
        source: AlbumListModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._query = ""
        self._sort_mode = AlbumSortMode.TITLE
        self._sort_direction = Qt.SortOrder.AscendingOrder
        self._collection_kind: CollectionKind | None = None
        self._collection_key: str | None = None
        self._group_by_selection = False
        self.setSourceModel(source)
        self.setDynamicSortFilter(False)
        source.dataChanged.connect(self._selection_data_changed)
        self.sort(0, self._sort_direction)

    def set_query(self, query: str) -> None:
        normalized = query.strip().casefold()
        if normalized == self._query:
            return
        self.beginFilterChange()
        self._query = normalized
        end_rows_filter_change(self)
        # Dynamic sorting is disabled; rebuild the ordering when rows return.
        self.invalidate()

    def set_sort_mode(self, mode: AlbumSortMode) -> None:
        if mode is self._sort_mode:
            return
        self._sort_mode = mode
        self.invalidate()
        self.sort(0, self._sort_direction)

    def set_sort_direction(self, direction: Qt.SortOrder) -> None:
        if direction == self._sort_direction:
            return
        self._sort_direction = direction
        self.sort(0, direction)

    def set_group_by_selection(self, enabled: bool) -> None:
        if enabled == self._group_by_selection:
            return
        self._group_by_selection = enabled
        self.invalidate()
        self.sort(0, self._sort_direction)

    def album_key_at(self, index: QModelIndex) -> str | None:
        if not index.isValid():
            return None
        source_index = self.mapToSource(index)
        value = self._source.data(source_index, AlbumRole.KEY)
        return value if isinstance(value, str) else None

    def set_collection_key(
        self,
        kind: CollectionKind | None,
        key: str | None,
    ) -> None:
        if kind not in {None, CollectionKind.ARTIST, CollectionKind.GENRE}:
            raise ValueError(
                "Album filtering supports only Artist or Genre collections"
            )
        normalized_kind = kind if key is not None else None
        normalized_key = key if kind is not None else None
        if (
            normalized_kind is self._collection_kind
            and normalized_key == self._collection_key
        ):
            return
        self.beginFilterChange()
        self._collection_kind = normalized_kind
        self._collection_key = normalized_key
        end_rows_filter_change(self)

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        index = self._source.index(source_row, 0, source_parent)
        if self._collection_kind is CollectionKind.ARTIST:
            artist_key = self._source.data(index, AlbumRole.ARTIST_KEY)
            if artist_key != self._collection_key:
                return False
        elif self._collection_kind is CollectionKind.GENRE:
            genre_keys = self._source.data(index, AlbumRole.GENRE_KEYS)
            if (
                not isinstance(genre_keys, frozenset)
                or self._collection_key not in genre_keys
            ):
                return False
        if not self._query:
            return True
        search_text = self._source.data(index, AlbumRole.SEARCH_TEXT)
        return isinstance(search_text, str) and self._query in search_text

    def lessThan(
        self,
        left: QModelIndex | QPersistentModelIndex,
        right: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        selection_order = self._selection_less_than(left, right)
        if selection_order is not None:
            return selection_order
        role = {
            AlbumSortMode.TITLE: AlbumRole.TITLE,
            AlbumSortMode.ARTIST: AlbumRole.ARTIST,
            AlbumSortMode.YEAR: AlbumRole.YEAR,
        }[self._sort_mode]
        left_value = self._source.data(left, role)
        right_value = self._source.data(right, role)
        if isinstance(left_value, str) and isinstance(right_value, str):
            return left_value.casefold() < right_value.casefold()
        if isinstance(left_value, int) and isinstance(right_value, int):
            return left_value < right_value
        return str(left_value) < str(right_value)

    def _selection_less_than(
        self,
        left: QModelIndex | QPersistentModelIndex,
        right: QModelIndex | QPersistentModelIndex,
    ) -> bool | None:
        if not self._group_by_selection:
            return None
        left_rank = _selection_rank(
            self._source.data(left, Qt.ItemDataRole.CheckStateRole)
        )
        right_rank = _selection_rank(
            self._source.data(right, Qt.ItemDataRole.CheckStateRole)
        )
        if left_rank == right_rank:
            return None
        return (
            left_rank < right_rank
            if self._sort_direction is Qt.SortOrder.AscendingOrder
            else left_rank > right_rank
        )

    def _selection_data_changed(self) -> None:
        if self._group_by_selection:
            self.invalidate()
            self.sort(0, self._sort_direction)


class CollectionFilterProxyModel(QSortFilterProxyModel):
    """Filter collection summaries without rebuilding their collage data."""

    def __init__(
        self,
        source: CollectionListModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._query = ""
        self._sort_mode = CollectionSortMode.TITLE
        self._sort_direction = Qt.SortOrder.AscendingOrder
        self._group_by_selection = False
        self.setSourceModel(source)
        self.setDynamicSortFilter(False)
        source.dataChanged.connect(self._selection_data_changed)
        self.sort(0, self._sort_direction)

    @property
    def kind(self) -> CollectionKind:
        return self._source.kind

    def set_query(self, query: str) -> None:
        normalized = query.strip().casefold()
        if normalized == self._query:
            return
        self.beginFilterChange()
        self._query = normalized
        end_rows_filter_change(self)
        # Dynamic sorting is disabled; rebuild the ordering when rows return.
        self.invalidate()

    def set_sort_mode(self, mode: CollectionSortMode) -> None:
        if mode is self._sort_mode:
            return
        self._sort_mode = mode
        self.invalidate()
        self.sort(0, self._sort_direction)

    def set_sort_direction(self, direction: Qt.SortOrder) -> None:
        if direction == self._sort_direction:
            return
        self._sort_direction = direction
        self.sort(0, direction)

    def set_group_by_selection(self, enabled: bool) -> None:
        if enabled == self._group_by_selection:
            return
        self._group_by_selection = enabled
        self.invalidate()
        self.sort(0, self._sort_direction)

    def collection_key_at(self, index: QModelIndex) -> str | None:
        if not index.isValid():
            return None
        value = self._source.data(self.mapToSource(index), CollectionRole.KEY)
        return value if isinstance(value, str) else None

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if not self._query:
            return True
        index = self._source.index(source_row, 0, source_parent)
        search_text = self._source.data(index, CollectionRole.SEARCH_TEXT)
        return isinstance(search_text, str) and self._query in search_text

    def lessThan(
        self,
        left: QModelIndex | QPersistentModelIndex,
        right: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if self._group_by_selection:
            left_rank = _selection_rank(
                self._source.data(left, Qt.ItemDataRole.CheckStateRole)
            )
            right_rank = _selection_rank(
                self._source.data(right, Qt.ItemDataRole.CheckStateRole)
            )
            if left_rank != right_rank:
                return (
                    left_rank < right_rank
                    if self._sort_direction is Qt.SortOrder.AscendingOrder
                    else left_rank > right_rank
                )
        role = {
            CollectionSortMode.TITLE: CollectionRole.TITLE,
            CollectionSortMode.ITEM_COUNT: CollectionRole.ITEM_COUNT,
            CollectionSortMode.TRACK_COUNT: CollectionRole.TRACK_COUNT,
            CollectionSortMode.DURATION: CollectionRole.DURATION_MS,
        }[self._sort_mode]
        left_value = self._source.data(left, role)
        right_value = self._source.data(right, role)
        if (
            self._sort_mode is not CollectionSortMode.TITLE
            and isinstance(left_value, int)
            and isinstance(right_value, int)
            and left_value != right_value
        ):
            return left_value > right_value

        left_title = self._source.data(left, CollectionRole.TITLE)
        right_title = self._source.data(right, CollectionRole.TITLE)
        return str(left_title).casefold() < str(right_title).casefold()

    def _selection_data_changed(self) -> None:
        if self._group_by_selection:
            self.invalidate()
            self.sort(0, self._sort_direction)


def _selection_rank(value: object) -> int:
    if value == Qt.CheckState.Checked:
        return 0
    if value == Qt.CheckState.PartiallyChecked:
        return 1
    return 2
