"""Qt list projections for Photos and Photo Albums in the Library Workspace."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QAbstractListModel,
    QCoreApplication,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from iOpenPod.app.models.filter_compat import end_rows_filter_change
from iOpenPod.app.models.library_drag import (
    PHOTO_MIME_TYPE,
    PhotoSelectionMimeData,
    dropped_photos,
)
from iPodDB.library import Photo, PhotoAlbumKind

if TYPE_CHECKING:
    from iOpenPod.app.library_workspace import LibraryWorkspace
    from iOpenPod.app.models.sync_selection import SyncSelection

_ROOT_INDEX = QModelIndex()
_ALL_PHOTOS_SOURCE = cast("str", QT_TRANSLATE_NOOP("PhotoAlbumListModel", "All Photos"))


@dataclass(frozen=True, slots=True)
class PhotoAlbumSummary:
    """One source-list row; ``album_id`` is absent only for All Photos."""

    album_id: int | None
    name: str
    photo_count: int
    is_all_photos: bool = False


class PhotoRole(IntEnum):
    """Roles consumed by the Photo grid and its delegate."""

    PHOTO = Qt.ItemDataRole.UserRole.value + 1
    ID = Qt.ItemDataRole.UserRole.value + 2
    RATING = Qt.ItemDataRole.UserRole.value + 3
    ORIGINAL_DATE = Qt.ItemDataRole.UserRole.value + 4
    TAKEN_DATE = Qt.ItemDataRole.UserRole.value + 5
    FORMAT_COUNT = Qt.ItemDataRole.UserRole.value + 6
    SOURCE_SIZE = Qt.ItemDataRole.UserRole.value + 7
    SEARCH_TEXT = Qt.ItemDataRole.UserRole.value + 8


class PhotoSortMode(StrEnum):
    """Stable Photo sorting choices; display labels remain translated."""

    SOURCE_ORDER = "source_order"
    DATE_TAKEN = "date_taken"
    RATING = "rating"
    SOURCE_SIZE = "source_size"


class PhotoAlbumRole(IntEnum):
    """Roles consumed by the Photo Album source list."""

    SUMMARY = Qt.ItemDataRole.UserRole.value + 1
    ID = Qt.ItemDataRole.UserRole.value + 2
    NAME = Qt.ItemDataRole.UserRole.value + 3
    PHOTO_COUNT = Qt.ItemDataRole.UserRole.value + 4
    IS_ALL_PHOTOS = Qt.ItemDataRole.UserRole.value + 5


class PhotoAlbumListModel(QAbstractListModel):
    """Project All Photos and retained user Photo Albums without copying Photos."""

    def __init__(
        self,
        workspace: LibraryWorkspace,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._albums: tuple[PhotoAlbumSummary, ...] = ()
        workspace.photosChanged.connect(self._source_changed)
        self._reset()

    def album_at(self, row: int) -> PhotoAlbumSummary | None:
        if not 0 <= row < len(self._albums):
            return None
        return self._albums[row]

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._albums)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        if not index.isValid() or not 0 <= index.row() < len(self._albums):
            return None
        album = self._albums[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return album.name
        if role == PhotoAlbumRole.SUMMARY:
            return album
        if role == PhotoAlbumRole.ID:
            return album.album_id
        if role == PhotoAlbumRole.NAME:
            return album.name
        if role == PhotoAlbumRole.PHOTO_COUNT:
            return album.photo_count
        if role == PhotoAlbumRole.IS_ALL_PHOTOS:
            return album.is_all_photos
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if self._drop_album_id(index) is not None:
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        return flags

    def mimeTypes(self) -> list[str]:
        return [PHOTO_MIME_TYPE]

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction

    def canDropMimeData(
        self,
        data: QMimeData,
        action: Qt.DropAction,
        row: int,
        column: int,
        parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        return (
            action == Qt.DropAction.CopyAction
            and row == -1
            and column in (-1, 0)
            and self._drop_album_id(parent) is not None
            and dropped_photos(data, self._workspace, require_editable=True) is not None
        )

    def dropMimeData(
        self,
        data: QMimeData,
        action: Qt.DropAction,
        row: int,
        column: int,
        parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if not self.canDropMimeData(data, action, row, column, parent):
            return False
        album_id = self._drop_album_id(parent)
        assert album_id is not None and isinstance(data, PhotoSelectionMimeData)
        try:
            self._workspace.set_photo_album_membership(
                album_id,
                data.photo_ids,
                included=True,
                expected=self._workspace.edit_revision,
            )
        except ValueError:
            return False
        return True

    def _drop_album_id(self, index: QModelIndex | QPersistentModelIndex) -> int | None:
        if (
            self._workspace.locked
            or not index.isValid()
            or index.model() is not self
            or index.column() != 0
        ):
            return None
        summary = self.album_at(index.row())
        if summary is None or summary.album_id is None:
            return None
        album = self._workspace.photo_album(summary.album_id)
        if album is None or album.kind is PhotoAlbumKind.MASTER:
            return None
        return album.album_id

    def retranslate(self) -> None:
        self._reset()

    def _project(self) -> tuple[PhotoAlbumSummary, ...]:
        library = self._workspace.photos
        if library is None:
            return ()
        return (
            PhotoAlbumSummary(
                None,
                QCoreApplication.translate(
                    "PhotoAlbumListModel",
                    _ALL_PHOTOS_SOURCE,
                ),
                len(library.photos),
                True,
            ),
            *(
                PhotoAlbumSummary(
                    album.album_id,
                    album.name,
                    len(album.photo_ids),
                )
                for album in library.albums
                if album.kind is not PhotoAlbumKind.MASTER
            ),
        )

    def _source_changed(self, _photos: object) -> None:
        self._reset()

    def _reset(self) -> None:
        self.beginResetModel()
        self._albums = self._project()
        self.endResetModel()


class PhotoListModel(QAbstractListModel):
    """Expose Photos in source or selected-Album order for a virtualized grid."""

    def __init__(
        self,
        workspace: LibraryWorkspace,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._album_id: int | None = None
        self._photos: tuple[Photo, ...] = ()
        self._search_texts: tuple[str, ...] = ()
        self._rows_by_photo_id: dict[int, tuple[int, ...]] = {}
        self._sync_selection: SyncSelection | None = None
        workspace.photosChanged.connect(self._source_changed)
        self._reset()

    @property
    def album_id(self) -> int | None:
        return self._album_id

    def set_album_id(self, album_id: int | None) -> None:
        if album_id == self._album_id:
            return
        self._album_id = album_id
        self._reset()

    def photo_at(self, row: int) -> Photo | None:
        if not 0 <= row < len(self._photos):
            return None
        return self._photos[row]

    def set_sync_selection(self, selection: SyncSelection | None) -> None:
        if selection is self._sync_selection:
            return
        if self._sync_selection is not None:
            self._sync_selection.hostSelectionChanged.disconnect(
                self._selection_changed
            )
        self._sync_selection = selection
        if selection is not None:
            selection.hostSelectionChanged.connect(self._selection_changed)
        self._selection_changed()

    def rows_for_photo(self, photo_id: int) -> tuple[int, ...]:
        """Return every projected occurrence without scanning the Photo rows."""

        return self._rows_by_photo_id.get(photo_id, ())

    def indexes_for_photo(self, photo_id: int) -> tuple[QModelIndex, ...]:
        """Return fresh model indexes for every projected Photo occurrence."""

        return tuple(self.index(row, 0) for row in self.rows_for_photo(photo_id))

    def index_for_photo(self, photo_id: int) -> QModelIndex:
        rows = self.rows_for_photo(photo_id)
        return self.index(rows[0], 0) if rows else QModelIndex()

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._photos)

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if not index.isValid():
            return flags
        if self._sync_selection is not None:
            return flags | Qt.ItemFlag.ItemIsUserCheckable
        return flags | Qt.ItemFlag.ItemIsDragEnabled

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        if not index.isValid() or not 0 <= index.row() < len(self._photos):
            return None
        photo = self._photos[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and self._sync_selection is not None:
            return self._sync_selection.photo_check_state(photo.photo_id)
        if role == Qt.ItemDataRole.DisplayRole:
            return QCoreApplication.translate("LibraryLabels", "Photo %1").replace(
                "%1", str(photo.photo_id)
            )
        if role == PhotoRole.PHOTO:
            return photo
        if role == PhotoRole.ID:
            return photo.photo_id
        if role == PhotoRole.RATING:
            return photo.rating
        if role == PhotoRole.ORIGINAL_DATE:
            return photo.original_date
        if role == PhotoRole.TAKEN_DATE:
            return photo.taken_date
        if role == PhotoRole.FORMAT_COUNT:
            return len(photo.representations)
        if role == PhotoRole.SOURCE_SIZE:
            return photo.source_size_bytes
        if role == PhotoRole.SEARCH_TEXT:
            return self._search_texts[index.row()]
        return None

    def setData(
        self,
        index: QModelIndex | QPersistentModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole.value,
    ) -> bool:
        if (
            role != Qt.ItemDataRole.CheckStateRole
            or self._sync_selection is None
            or not index.isValid()
        ):
            return False
        photo = self.photo_at(index.row())
        if photo is None:
            return False
        return self._sync_selection.set_photos_checked(
            (photo.photo_id,),
            value == Qt.CheckState.Checked,
        )

    def retranslate(self) -> None:
        if self._photos:
            self._search_texts = tuple(
                self._search_text(photo) for photo in self._photos
            )
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._photos) - 1, 0),
                [
                    Qt.ItemDataRole.DisplayRole.value,
                    PhotoRole.SEARCH_TEXT,
                ],
            )

    def _project(self) -> tuple[Photo, ...]:
        library = self._workspace.photos
        if library is None:
            return ()
        if self._album_id is None:
            return library.photos
        album = next(
            (
                candidate
                for candidate in library.albums
                if candidate.album_id == self._album_id
            ),
            None,
        )
        if album is None:
            return ()
        by_id = {photo.photo_id: photo for photo in library.photos}
        return tuple(
            photo
            for photo_id in album.photo_ids
            if (photo := by_id.get(photo_id)) is not None
        )

    def _source_changed(self, _photos: object) -> None:
        self._reset()

    def _reset(self) -> None:
        self.beginResetModel()
        self._photos = self._project()
        self._search_texts = tuple(self._search_text(photo) for photo in self._photos)
        mutable_rows: dict[int, list[int]] = {}
        for row, photo in enumerate(self._photos):
            mutable_rows.setdefault(photo.photo_id, []).append(row)
        self._rows_by_photo_id = {
            photo_id: tuple(rows) for photo_id, rows in mutable_rows.items()
        }
        self.endResetModel()

    def _selection_changed(self) -> None:
        if not self._photos:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._photos) - 1, 0),
            [Qt.ItemDataRole.CheckStateRole.value],
        )

    def _search_text(self, photo: Photo) -> str:
        label = QCoreApplication.translate("LibraryLabels", "Photo %1").replace(
            "%1", str(photo.photo_id)
        )
        paths = (item.relative_path for item in photo.representations)
        return " ".join((label, str(photo.photo_id), *paths)).casefold()


class PhotoFilterProxyModel(QSortFilterProxyModel):
    """Filter and sort Photos while retaining the source model's Photo helpers."""

    def __init__(
        self,
        source: PhotoListModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._query = ""
        self._sort_mode = PhotoSortMode.SOURCE_ORDER
        self._sort_direction = Qt.SortOrder.AscendingOrder
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

    def set_sort_mode(self, mode: PhotoSortMode) -> None:
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

    def photo_at(self, row: int) -> Photo | None:
        index = self.index(row, 0)
        if not index.isValid():
            return None
        return self._source.photo_at(self.mapToSource(index).row())

    def indexes_for_photo(self, photo_id: int) -> tuple[QModelIndex, ...]:
        return tuple(
            proxy_index
            for source_index in self._source.indexes_for_photo(photo_id)
            if (proxy_index := self.mapFromSource(source_index)).isValid()
        )

    def index_for_photo(self, photo_id: int) -> QModelIndex:
        indexes = self.indexes_for_photo(photo_id)
        return indexes[0] if indexes else QModelIndex()

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if not self._query:
            return True
        index = self._source.index(source_row, 0, source_parent)
        search_text = self._source.data(index, PhotoRole.SEARCH_TEXT)
        return isinstance(search_text, str) and self._query in search_text

    def lessThan(
        self,
        left: QModelIndex | QPersistentModelIndex,
        right: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if self._group_by_selection:
            left_rank = _photo_selection_rank(
                self._source.data(left, Qt.ItemDataRole.CheckStateRole)
            )
            right_rank = _photo_selection_rank(
                self._source.data(right, Qt.ItemDataRole.CheckStateRole)
            )
            if left_rank != right_rank:
                return (
                    left_rank < right_rank
                    if self._sort_direction is Qt.SortOrder.AscendingOrder
                    else left_rank > right_rank
                )
        left_photo = self._source.photo_at(left.row())
        right_photo = self._source.photo_at(right.row())
        if left_photo is None or right_photo is None:
            return left.row() < right.row()
        left_value = self._sort_value(left_photo)
        right_value = self._sort_value(right_photo)
        if left_value != right_value:
            return left_value > right_value
        return left.row() < right.row()

    def _sort_value(self, photo: Photo) -> int:
        if self._sort_mode is PhotoSortMode.DATE_TAKEN:
            return photo.taken_date or photo.original_date
        if self._sort_mode is PhotoSortMode.RATING:
            return photo.rating
        if self._sort_mode is PhotoSortMode.SOURCE_SIZE:
            return photo.source_size_bytes
        return 0

    def _selection_data_changed(self) -> None:
        if self._group_by_selection:
            self.invalidate()
            self.sort(0, self._sort_direction)


def _photo_selection_rank(value: object) -> int:
    return 0 if value == Qt.CheckState.Checked else 1


__all__ = [
    "PhotoAlbumListModel",
    "PhotoAlbumRole",
    "PhotoAlbumSummary",
    "PhotoFilterProxyModel",
    "PhotoListModel",
    "PhotoRole",
    "PhotoSortMode",
]
