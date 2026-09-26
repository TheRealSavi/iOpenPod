"""Album projection for the Active iPod Library."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QAbstractListModel,
    QCoreApplication,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.app.models.keyed_projection import reconcile_keyed_rows
from iPodDB.library import MediaKind

if TYPE_CHECKING:
    from iOpenPod.app.models.sync_selection import SyncSelection
    from iOpenPod.app.models.track_table_model import TrackTableModel

_ROOT_INDEX = QModelIndex()
_UNKNOWN_ALBUM_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("AlbumListModel", "Unknown Album"),
)


@dataclass(frozen=True, slots=True)
class AlbumSummary:
    """Immutable summary rendered by an album item view."""

    key: str
    title: str
    artist: str
    year: int
    track_count: int
    duration_ms: int
    artwork_id: int
    artwork_seed: int
    artist_key: str
    genre_keys: frozenset[str]
    track_ids: tuple[int, ...] = ()


@dataclass(slots=True)
class _AlbumAccumulator:
    key: str
    title: str
    artist: str
    year: int
    track_count: int
    duration_ms: int
    artwork_id: int
    artwork_seed: int
    artist_key: str
    genre_keys: set[str] = field(default_factory=set[str])
    track_ids: list[int] = field(default_factory=list[int])


class AlbumRole(IntEnum):
    """Roles consumed by album proxies and delegates."""

    SUMMARY = Qt.ItemDataRole.UserRole.value + 1
    KEY = Qt.ItemDataRole.UserRole.value + 2
    TITLE = Qt.ItemDataRole.UserRole.value + 3
    ARTIST = Qt.ItemDataRole.UserRole.value + 4
    YEAR = Qt.ItemDataRole.UserRole.value + 5
    TRACK_COUNT = Qt.ItemDataRole.UserRole.value + 6
    DURATION_MS = Qt.ItemDataRole.UserRole.value + 7
    SEARCH_TEXT = Qt.ItemDataRole.UserRole.value + 8
    ARTWORK_SEED = Qt.ItemDataRole.UserRole.value + 9
    ARTWORK_ID = Qt.ItemDataRole.UserRole.value + 10
    ARTIST_KEY = Qt.ItemDataRole.UserRole.value + 11
    GENRE_KEYS = Qt.ItemDataRole.UserRole.value + 12


class AlbumListModel(QAbstractListModel):
    """Aggregate albums once whenever the Track snapshot changes."""

    def __init__(
        self,
        tracks: TrackTableModel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._tracks = tracks
        self._albums: tuple[AlbumSummary, ...] = ()
        self._search_texts: tuple[str, ...] = ()
        self._sync_selection: SyncSelection | None = None
        tracks.modelReset.connect(self._source_reset)
        tracks.dataChanged.connect(self._source_changed)
        tracks.rowsInserted.connect(self._source_changed)
        tracks.rowsRemoved.connect(self._source_changed)
        self._source_reset()

    @property
    def album_count(self) -> int:
        return len(self._albums)

    def album_at(self, row: int) -> AlbumSummary | None:
        if not 0 <= row < len(self._albums):
            return None
        return self._albums[row]

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

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._albums)

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
        if not index.isValid() or not 0 <= index.row() < len(self._albums):
            return None

        album = self._albums[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and self._sync_selection is not None:
            return self._sync_selection.track_group_check_state(album.track_ids)
        if role == Qt.ItemDataRole.DisplayRole:
            return album.title or _translate(_UNKNOWN_ALBUM_SOURCE)
        if role == AlbumRole.SUMMARY:
            return album
        if role == AlbumRole.KEY:
            return album.key
        if role == AlbumRole.TITLE:
            return album.title
        if role == AlbumRole.ARTIST:
            return album.artist
        if role == AlbumRole.YEAR:
            return album.year
        if role == AlbumRole.TRACK_COUNT:
            return album.track_count
        if role == AlbumRole.DURATION_MS:
            return album.duration_ms
        if role == AlbumRole.SEARCH_TEXT:
            return self._search_texts[index.row()]
        if role == AlbumRole.ARTWORK_SEED:
            return album.artwork_seed
        if role == AlbumRole.ARTWORK_ID:
            return album.artwork_id
        if role == AlbumRole.ARTIST_KEY:
            return album.artist_key
        if role == AlbumRole.GENRE_KEYS:
            return album.genre_keys
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
        album = self.album_at(index.row())
        if album is None:
            return False
        return self._sync_selection.set_tracks_checked(
            album.track_ids,
            value == Qt.CheckState.Checked,
        )

    def retranslate(self) -> None:
        if not self._albums:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._albums) - 1, 0),
            [Qt.ItemDataRole.DisplayRole.value],
        )

    def _project(self) -> tuple[AlbumSummary, ...]:
        accumulators: dict[str, _AlbumAccumulator] = {}
        for track in self._tracks.tracks:
            if track.media_kind is not MediaKind.MUSIC:
                continue
            album = accumulators.get(track.album_key)
            if album is None:
                accumulators[track.album_key] = _AlbumAccumulator(
                    key=track.album_key,
                    title=track.album,
                    artist=track.effective_album_artist,
                    year=track.year,
                    track_count=1,
                    duration_ms=max(0, track.length_ms),
                    artwork_id=track.artwork_id,
                    artwork_seed=stable_artwork_seed(track.album_key),
                    artist_key=track.artist_key,
                    genre_keys={track.genre_key} if track.genre_key else set(),
                    track_ids=[track.track_id],
                )
                continue
            album.track_count += 1
            album.duration_ms += max(0, track.length_ms)
            if album.year <= 0 and track.year > 0:
                album.year = track.year
            if album.artwork_id <= 0 and track.artwork_id > 0:
                album.artwork_id = track.artwork_id
            if track.genre_key:
                album.genre_keys.add(track.genre_key)
            album.track_ids.append(track.track_id)

        return tuple(
            AlbumSummary(
                key=album.key,
                title=album.title,
                artist=album.artist,
                year=album.year,
                track_count=album.track_count,
                duration_ms=album.duration_ms,
                artwork_id=album.artwork_id,
                artwork_seed=album.artwork_seed,
                artist_key=album.artist_key,
                genre_keys=frozenset(album.genre_keys),
                track_ids=tuple(album.track_ids),
            )
            for album in accumulators.values()
        )

    def _commit(self, summaries: tuple[AlbumSummary, ...]) -> None:
        self._albums = summaries
        self._search_texts = tuple(
            "\x1f".join((album.title, album.artist, str(album.year))).casefold()
            for album in summaries
        )

    def _source_reset(self) -> None:
        self.beginResetModel()
        self._commit(self._project())
        self.endResetModel()

    def _source_changed(self, *_args: object) -> None:
        reconcile_keyed_rows(
            self,
            self._albums,
            self._project(),
            key=lambda album: album.key,
            commit=self._commit,
        )

    def _selection_changed(self) -> None:
        if not self._albums:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._albums) - 1, 0),
            [Qt.ItemDataRole.CheckStateRole.value],
        )


def _translate(source_text: str) -> str:
    return QCoreApplication.translate("AlbumListModel", source_text)
