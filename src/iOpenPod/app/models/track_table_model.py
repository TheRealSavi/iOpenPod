"""Read-only Qt model for Tracks in the Active iPod Library."""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)

from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.app.models.track_columns import (
    TrackColumn,
    track_column_count,
    track_column_display_value,
    track_column_header,
    track_column_is_right_aligned,
    track_column_sort_value,
)

if TYPE_CHECKING:
    from iOpenPod.app.models.sync_selection import SyncSelection
    from iPodDB.library import Track

__all__ = ("TrackColumn", "TrackRole", "TrackTableModel")

_ROOT_INDEX = QModelIndex()


class TrackRole(IntEnum):
    """Non-display roles shared by library views and proxy models."""

    TRACK = Qt.ItemDataRole.UserRole.value + 1
    TRACK_ID = Qt.ItemDataRole.UserRole.value + 2
    ALBUM_KEY = Qt.ItemDataRole.UserRole.value + 3
    SEARCH_TEXT = Qt.ItemDataRole.UserRole.value + 4
    SORT_VALUE = Qt.ItemDataRole.UserRole.value + 5
    ARTWORK_SEED = Qt.ItemDataRole.UserRole.value + 6
    ARTWORK_ID = Qt.ItemDataRole.UserRole.value + 7


class TrackTableModel(QAbstractTableModel):
    """Expose immutable Track data to Qt item views."""

    syncSelectionEnabledChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tracks: tuple[Track, ...] = ()
        self._playlist_positions: tuple[int | None, ...] = ()
        self._search_texts: tuple[str, ...] = ()
        self._sync_selection: SyncSelection | None = None

    @property
    def track_count(self) -> int:
        return len(self._tracks)

    @property
    def tracks(self) -> tuple[Track, ...]:
        """Return the current immutable Track snapshot."""

        return self._tracks

    @property
    def sync_selection_enabled(self) -> bool:
        return self._sync_selection is not None

    def replace_tracks(
        self,
        tracks: tuple[Track, ...],
        *,
        playlist_positions: tuple[int | None, ...] | None = None,
    ) -> None:
        """Publish Tracks with optional occurrence positions aligned by row."""

        positions = (
            (None,) * len(tracks) if playlist_positions is None else playlist_positions
        )
        if len(positions) != len(tracks):
            raise ValueError("Playlist positions must align one-to-one with Tracks.")
        if tracks == self._tracks and positions == self._playlist_positions:
            return

        old_count = len(self._tracks)
        new_count = len(tracks)
        common_count = min(old_count, new_count)
        same_identity_order = all(
            self._tracks[row].track_id == tracks[row].track_id
            for row in range(common_count)
        )
        same_shared_values = (
            self._tracks[:common_count] == tracks[:common_count]
            and self._playlist_positions[:common_count] == positions[:common_count]
        )

        if same_identity_order and old_count == new_count:
            changed_rows = tuple(
                row
                for row, (old, new) in enumerate(zip(self._tracks, tracks, strict=True))
                if old != new or self._playlist_positions[row] != positions[row]
            )
            self._tracks = tracks
            self._playlist_positions = positions
            self._search_texts = tuple(_search_text(track) for track in tracks)
            self._emit_changed_rows(changed_rows)
            return

        if same_shared_values and new_count > old_count:
            self.beginInsertRows(_ROOT_INDEX, old_count, new_count - 1)
            self._tracks = tracks
            self._playlist_positions = positions
            self._search_texts = tuple(_search_text(track) for track in tracks)
            self.endInsertRows()
            return

        if same_shared_values and new_count < old_count:
            self.beginRemoveRows(_ROOT_INDEX, new_count, old_count - 1)
            self._tracks = tracks
            self._playlist_positions = positions
            self._search_texts = tuple(_search_text(track) for track in tracks)
            self.endRemoveRows()
            return

        self.beginResetModel()
        self._tracks = tracks
        self._playlist_positions = positions
        self._search_texts = tuple(_search_text(track) for track in tracks)
        self.endResetModel()

    def reset_tracks(self, tracks: tuple[Track, ...]) -> None:
        """Publish one whole-Library snapshot with exactly one model reset."""

        self.beginResetModel()
        self._tracks = tracks
        self._playlist_positions = (None,) * len(tracks)
        self._search_texts = tuple(_search_text(track) for track in tracks)
        self.endResetModel()

    def track_at(self, row: int) -> Track | None:
        """Return one Track without exposing model internals to a view."""

        if not 0 <= row < len(self._tracks):
            return None
        return self._tracks[row]

    def set_sync_selection(self, selection: SyncSelection | None) -> None:
        """Expose desired-device membership through standard Qt check-state roles."""

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
        self.syncSelectionEnabledChanged.emit(self.sync_selection_enabled)

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._tracks)

    def columnCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else track_column_count()

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if not index.isValid():
            return flags
        if (
            self._sync_selection is not None
            and index.column() == TrackColumn.SYNC_SELECTION
        ):
            return flags | Qt.ItemFlag.ItemIsUserCheckable
        if self._sync_selection is None:
            return flags | Qt.ItemFlag.ItemIsDragEnabled
        return flags

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        if not index.isValid() or not 0 <= index.row() < len(self._tracks):
            return None

        track = self._tracks[index.row()]
        position = self._playlist_positions[index.row()]
        if (
            role == Qt.ItemDataRole.CheckStateRole
            and self._sync_selection is not None
            and index.column() == TrackColumn.SYNC_SELECTION
        ):
            return self._sync_selection.track_check_state(track.track_id)
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == TrackColumn.PLAYLIST_POSITION:
                return "" if position is None else str(position + 1)
            return track_column_display_value(track, index.column())
        if role == TrackRole.TRACK:
            return track
        if role == TrackRole.TRACK_ID:
            return track.track_id
        if role == TrackRole.ALBUM_KEY:
            return track.album_key
        if role == TrackRole.SEARCH_TEXT:
            return self._search_texts[index.row()]
        if role == TrackRole.SORT_VALUE:
            if index.column() == TrackColumn.SYNC_SELECTION:
                return (
                    self._sync_selection.track_check_state(track.track_id).value
                    if self._sync_selection is not None
                    else None
                )
            if index.column() == TrackColumn.PLAYLIST_POSITION:
                return position
            return track_column_sort_value(track, index.column())
        if role == TrackRole.ARTWORK_SEED:
            return stable_artwork_seed(track.album_key)
        if role == TrackRole.ARTWORK_ID:
            return track.artwork_id
        if role == Qt.ItemDataRole.TextAlignmentRole and track_column_is_right_aligned(
            index.column()
        ):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
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
            or index.column() != TrackColumn.SYNC_SELECTION
        ):
            return False
        track = self.track_at(index.row())
        if track is None:
            return False
        return self._sync_selection.set_tracks_checked(
            (track.track_id,),
            value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value),
        )

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and 0 <= section < track_column_count()
        ):
            return track_column_header(section)
        return None

    def retranslate(self) -> None:
        """Notify attached views that translated labels may have changed."""

        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal,
            0,
            track_column_count() - 1,
        )
        if self._tracks:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._tracks) - 1, track_column_count() - 1),
                [Qt.ItemDataRole.DisplayRole.value],
            )

    def _emit_changed_rows(self, rows: tuple[int, ...]) -> None:
        if not rows:
            return
        start = rows[0]
        end = start
        for row in rows[1:]:
            if row == end + 1:
                end = row
                continue
            self.dataChanged.emit(
                self.index(start, 0),
                self.index(end, track_column_count() - 1),
                [],
            )
            start = end = row
        self.dataChanged.emit(
            self.index(start, 0),
            self.index(end, track_column_count() - 1),
            [],
        )

    def _selection_changed(self) -> None:
        if not self._tracks:
            return
        self.dataChanged.emit(
            self.index(0, TrackColumn.SYNC_SELECTION),
            self.index(len(self._tracks) - 1, TrackColumn.SYNC_SELECTION),
            [Qt.ItemDataRole.CheckStateRole.value, TrackRole.SORT_VALUE],
        )


def _search_text(track: Track) -> str:
    return "\x1f".join(
        (
            track.title,
            track.artist,
            track.album,
            track.genre,
            str(track.year) if track.year else "",
        )
    ).casefold()
