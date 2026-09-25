"""Cached artist, genre, and grouped-media projections."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
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
    from iPodDB.library import Track

_ROOT_INDEX = QModelIndex()
_UNKNOWN_ARTIST_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionListModel", "Unknown Artist"),
)
_UNKNOWN_GENRE_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionListModel", "Unknown Genre"),
)
_UNKNOWN_SHOW_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionListModel", "Unknown Show"),
)
_UNKNOWN_ALBUM_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionListModel", "Unknown Album"),
)


class CollectionKind(StrEnum):
    """Stable grouping dimensions used by library presentation."""

    ARTIST = "artist"
    GENRE = "genre"
    TV_SHOW = "tv_show"
    MUSIC_VIDEO_ALBUM = "music_video_album"


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    """One collection card with a deterministic four-tile collage."""

    kind: CollectionKind
    key: str
    title: str
    track_count: int
    item_count: int
    duration_ms: int
    artwork_ids: tuple[int, int, int, int]
    artwork_seed: int
    track_ids: tuple[int, ...] = ()

    @property
    def representative_artwork_id(self) -> int:
        """Return the first usable cover shared by collection presentation."""

        return next(
            (artwork_id for artwork_id in self.artwork_ids if artwork_id > 0),
            0,
        )


@dataclass(slots=True)
class _CollectionAccumulator:
    key: str
    title: str
    track_count: int = 0
    duration_ms: int = 0
    item_artwork: dict[str, int] = field(default_factory=dict[str, int])
    track_ids: list[int] = field(default_factory=list[int])


class CollectionRole(IntEnum):
    SUMMARY = Qt.ItemDataRole.UserRole.value + 1
    KIND = Qt.ItemDataRole.UserRole.value + 2
    KEY = Qt.ItemDataRole.UserRole.value + 3
    TITLE = Qt.ItemDataRole.UserRole.value + 4
    TRACK_COUNT = Qt.ItemDataRole.UserRole.value + 5
    ITEM_COUNT = Qt.ItemDataRole.UserRole.value + 6
    DURATION_MS = Qt.ItemDataRole.UserRole.value + 7
    ARTWORK_IDS = Qt.ItemDataRole.UserRole.value + 8
    ARTWORK_SEED = Qt.ItemDataRole.UserRole.value + 9
    SEARCH_TEXT = Qt.ItemDataRole.UserRole.value + 10


class CollectionListModel(QAbstractListModel):
    """Aggregate one collection dimension once per Track-model change."""

    def __init__(
        self,
        tracks: TrackTableModel,
        kind: CollectionKind,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._tracks = tracks
        self._kind = kind
        self._collections: tuple[CollectionSummary, ...] = ()
        self._search_texts: tuple[str, ...] = ()
        self._sync_selection: SyncSelection | None = None
        tracks.modelReset.connect(self._source_reset)
        tracks.dataChanged.connect(self._source_changed)
        tracks.rowsInserted.connect(self._source_changed)
        tracks.rowsRemoved.connect(self._source_changed)
        self._source_reset()

    @property
    def kind(self) -> CollectionKind:
        return self._kind

    def collection_at(self, row: int) -> CollectionSummary | None:
        if not 0 <= row < len(self._collections):
            return None
        return self._collections[row]

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
        return 0 if parent.isValid() else len(self._collections)

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
        if not index.isValid() or not 0 <= index.row() < len(self._collections):
            return None
        summary = self._collections[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and self._sync_selection is not None:
            return self._sync_selection.track_group_check_state(summary.track_ids)
        if role == Qt.ItemDataRole.DisplayRole:
            return summary.title or _unknown_title(summary.kind)
        if role == CollectionRole.SUMMARY:
            return summary
        if role == CollectionRole.KIND:
            return summary.kind.value
        if role == CollectionRole.KEY:
            return summary.key
        if role == CollectionRole.TITLE:
            return summary.title
        if role == CollectionRole.TRACK_COUNT:
            return summary.track_count
        if role == CollectionRole.ITEM_COUNT:
            return summary.item_count
        if role == CollectionRole.DURATION_MS:
            return summary.duration_ms
        if role == CollectionRole.ARTWORK_IDS:
            return summary.artwork_ids
        if role == CollectionRole.ARTWORK_SEED:
            return summary.artwork_seed
        if role == CollectionRole.SEARCH_TEXT:
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
        summary = self.collection_at(index.row())
        if summary is None:
            return False
        return self._sync_selection.set_tracks_checked(
            summary.track_ids,
            value == Qt.CheckState.Checked,
        )

    def retranslate(self) -> None:
        if self._collections:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._collections) - 1, 0),
                [Qt.ItemDataRole.DisplayRole.value],
            )

    def _project(self) -> tuple[CollectionSummary, ...]:
        accumulators: dict[str, _CollectionAccumulator] = {}
        for track in self._tracks.tracks:
            value = collection_value_for_track(track, self._kind)
            if value is None:
                continue
            key, title, item_key = value
            accumulator = accumulators.get(key)
            if accumulator is None:
                accumulator = _CollectionAccumulator(key=key, title=title)
                accumulators[key] = accumulator
            accumulator.track_count += 1
            accumulator.duration_ms += max(0, track.length_ms)
            accumulator.track_ids.append(track.track_id)
            retained_artwork = accumulator.item_artwork.get(item_key)
            if retained_artwork is None or (retained_artwork <= 0 < track.artwork_id):
                accumulator.item_artwork[item_key] = track.artwork_id

        return tuple(
            CollectionSummary(
                kind=self._kind,
                key=item.key,
                title=item.title,
                track_count=item.track_count,
                item_count=len(item.item_artwork),
                duration_ms=item.duration_ms,
                artwork_ids=_four_tiles(tuple(item.item_artwork.values())),
                artwork_seed=stable_artwork_seed(f"{self._kind.value}\x1f{item.key}"),
                track_ids=tuple(item.track_ids),
            )
            for item in accumulators.values()
        )

    def _commit(self, summaries: tuple[CollectionSummary, ...]) -> None:
        self._collections = summaries
        self._search_texts = tuple(item.title.casefold() for item in summaries)

    def _source_reset(self) -> None:
        self.beginResetModel()
        self._commit(self._project())
        self.endResetModel()

    def _source_changed(self, *_args: object) -> None:
        reconcile_keyed_rows(
            self,
            self._collections,
            self._project(),
            key=lambda collection: collection.key,
            commit=self._commit,
        )

    def _selection_changed(self) -> None:
        if not self._collections:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._collections) - 1, 0),
            [Qt.ItemDataRole.CheckStateRole.value],
        )


def collection_value_for_track(
    track: Track,
    kind: CollectionKind,
) -> tuple[str, str, str] | None:
    """Return normalized collection and collage-item keys for one Track."""

    if kind is CollectionKind.ARTIST:
        if track.media_kind is not MediaKind.MUSIC:
            return None
        return track.artist_key, track.artist, track.album_key
    if kind is CollectionKind.GENRE:
        if track.media_kind is not MediaKind.MUSIC:
            return None
        return track.genre_key, track.genre, track.album_key
    if kind is CollectionKind.TV_SHOW:
        if track.media_kind is not MediaKind.TV_SHOW:
            return None
        item_key = track.episode.casefold() or str(track.track_id)
        return track.show_key, track.show, item_key
    if track.media_kind is not MediaKind.MUSIC_VIDEO:
        return None
    return track.album_key, track.album, str(track.track_id)


def collection_key_for_track(track: Track, kind: CollectionKind) -> str | None:
    value = collection_value_for_track(track, kind)
    return value[0] if value is not None else None


def _four_tiles(values: tuple[int, ...]) -> tuple[int, int, int, int]:
    tiles = (*values[:4], 0, 0, 0, 0)
    return tiles[0], tiles[1], tiles[2], tiles[3]


def _unknown_title(kind: CollectionKind) -> str:
    source = {
        CollectionKind.ARTIST: _UNKNOWN_ARTIST_SOURCE,
        CollectionKind.GENRE: _UNKNOWN_GENRE_SOURCE,
        CollectionKind.TV_SHOW: _UNKNOWN_SHOW_SOURCE,
        CollectionKind.MUSIC_VIDEO_ALBUM: _UNKNOWN_ALBUM_SOURCE,
    }[kind]
    return QCoreApplication.translate("CollectionListModel", source)


__all__ = [
    "CollectionKind",
    "CollectionListModel",
    "CollectionRole",
    "CollectionSummary",
    "collection_key_for_track",
]
