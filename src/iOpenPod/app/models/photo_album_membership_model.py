"""Qt projection for editing selected-Photo membership in user Photo Albums."""

from dataclasses import dataclass
from enum import IntEnum

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)

from iOpenPod.app.library_workspace import LibraryWorkspace
from iPodDB.library import PhotoAlbumKind

_ROOT_INDEX = QModelIndex()


@dataclass(frozen=True, slots=True)
class PhotoAlbumMembershipSummary:
    """One user Photo Album card and its selected-Photo membership state."""

    album_id: int
    name: str
    photo_count: int
    preview_photo_ids: tuple[int, int, int, int]
    check_state: Qt.CheckState


class PhotoAlbumMembershipRole(IntEnum):
    """Roles consumed by the Photo Album membership card delegate."""

    SUMMARY = Qt.ItemDataRole.UserRole.value + 1
    ID = Qt.ItemDataRole.UserRole.value + 2
    NAME = Qt.ItemDataRole.UserRole.value + 3
    PHOTO_COUNT = Qt.ItemDataRole.UserRole.value + 4
    PREVIEW_PHOTO_IDS = Qt.ItemDataRole.UserRole.value + 5


class PhotoAlbumMembershipModel(QAbstractListModel):
    """Project user Photo Albums and apply check-state changes to the draft."""

    membershipEditFailed = Signal(str)

    def __init__(
        self,
        workspace: LibraryWorkspace,
        photo_ids: tuple[int, ...],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._generation = workspace.generation
        self._photo_ids = tuple(dict.fromkeys(photo_ids))
        self._albums: tuple[PhotoAlbumMembershipSummary, ...] = ()
        workspace.photosChanged.connect(self._source_changed)
        self._reset()

    @property
    def photo_ids(self) -> tuple[int, ...]:
        return self._photo_ids

    def album_at(self, row: int) -> PhotoAlbumMembershipSummary | None:
        if not 0 <= row < len(self._albums):
            return None
        return self._albums[row]

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._albums)

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if not index.isValid() or self._workspace.locked:
            return flags
        return flags | Qt.ItemFlag.ItemIsUserCheckable

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
        if role == Qt.ItemDataRole.CheckStateRole:
            return album.check_state
        if role == PhotoAlbumMembershipRole.SUMMARY:
            return album
        if role == PhotoAlbumMembershipRole.ID:
            return album.album_id
        if role == PhotoAlbumMembershipRole.NAME:
            return album.name
        if role == PhotoAlbumMembershipRole.PHOTO_COUNT:
            return album.photo_count
        if role == PhotoAlbumMembershipRole.PREVIEW_PHOTO_IDS:
            return album.preview_photo_ids
        return None

    def setData(
        self,
        index: QModelIndex | QPersistentModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole.value,
    ) -> bool:
        if (
            role != Qt.ItemDataRole.CheckStateRole
            or not index.isValid()
            or not 0 <= index.row() < len(self._albums)
            or self._generation != self._workspace.generation
        ):
            return False
        try:
            checked = Qt.CheckState(value) is Qt.CheckState.Checked
        except (TypeError, ValueError):
            return False
        album = self._albums[index.row()]
        try:
            self._workspace.set_photo_album_membership(
                album.album_id,
                self._photo_ids,
                included=checked,
                expected=self._workspace.edit_revision,
            )
        except ValueError as error:
            self.membershipEditFailed.emit(str(error))
            return False
        return True

    def _project(self) -> tuple[PhotoAlbumMembershipSummary, ...]:
        library = self._workspace.photos
        if library is None or self._generation != self._workspace.generation:
            return ()
        selected = frozenset(self._photo_ids)
        available = {photo.photo_id for photo in library.photos}
        return tuple(
            PhotoAlbumMembershipSummary(
                album_id=album.album_id,
                name=album.name,
                photo_count=len(album.photo_ids),
                preview_photo_ids=_four_photo_tiles(album.photo_ids, available),
                check_state=_membership_state(album.photo_ids, selected),
            )
            for album in library.albums
            if album.kind is not PhotoAlbumKind.MASTER
        )

    def _source_changed(self, _photos: object) -> None:
        self._reset()

    def _reset(self) -> None:
        self.beginResetModel()
        self._albums = self._project()
        self.endResetModel()


def _membership_state(
    album_photo_ids: tuple[int, ...],
    selected: frozenset[int],
) -> Qt.CheckState:
    membership = frozenset(album_photo_ids)
    included = len(selected & membership)
    if included == len(selected) and selected:
        return Qt.CheckState.Checked
    if included:
        return Qt.CheckState.PartiallyChecked
    return Qt.CheckState.Unchecked


def _four_photo_tiles(
    photo_ids: tuple[int, ...],
    available: set[int],
) -> tuple[int, int, int, int]:
    usable = tuple(dict.fromkeys(i for i in photo_ids if i in available))
    tiles = (*usable[:4], 0, 0, 0, 0)
    return tiles[0], tiles[1], tiles[2], tiles[3]


__all__ = [
    "PhotoAlbumMembershipModel",
    "PhotoAlbumMembershipRole",
    "PhotoAlbumMembershipSummary",
]
