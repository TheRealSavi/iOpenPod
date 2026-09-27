"""Typed Qt models for the runtime Playback Queue and Playback History."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QCoreApplication,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import (
    PLAYLIST_MIME_TYPE,
    TRACK_MIME_TYPE,
    TrackSelectionMimeData,
    dropped_tracks,
)
from iPodDB.library import Track

_ROOT_INDEX = QModelIndex()
QUEUE_ENTRY_MIME_TYPE = "application/x-iopenpod-playback-entry"


class PlaybackRole(IntEnum):
    """Application roles shared by playback list views."""

    ENTRY_ID = Qt.ItemDataRole.UserRole.value + 1
    TRACK = Qt.ItemDataRole.UserRole.value + 2
    ARTIST = Qt.ItemDataRole.UserRole.value + 3
    ALBUM = Qt.ItemDataRole.UserRole.value + 4
    IS_CURRENT = Qt.ItemDataRole.UserRole.value + 5


@dataclass(frozen=True, slots=True)
class PlaybackEntry:
    """One unique runtime occurrence of a Track."""

    entry_id: int
    track: Track


class _PlaybackListModel(QAbstractListModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[PlaybackEntry] = []
        self._current_entry_id: int | None = None

    @property
    def entries(self) -> tuple[PlaybackEntry, ...]:
        return tuple(self._entries)

    def entry_at(self, row: int) -> PlaybackEntry | None:
        if not 0 <= row < len(self._entries):
            return None
        return self._entries[row]

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        entry = self.entry_at(index.row()) if index.isValid() else None
        if entry is None:
            return None
        track = entry.track
        if role == Qt.ItemDataRole.DisplayRole:
            return track.title or QCoreApplication.translate(
                "LibraryLabels", "Untitled Track"
            )
        if role == Qt.ItemDataRole.AccessibleTextRole:
            title = track.title or QCoreApplication.translate(
                "LibraryLabels", "Untitled Track"
            )
            return (
                self.tr("%1 — %2 — %3")
                .replace("%1", title)
                .replace(
                    "%2",
                    track.artist
                    or QCoreApplication.translate("LibraryLabels", "Unknown Artist"),
                )
                .replace(
                    "%3",
                    track.album
                    or QCoreApplication.translate("LibraryLabels", "Unknown Album"),
                )
            )
        if role == PlaybackRole.ENTRY_ID:
            return entry.entry_id
        if role == PlaybackRole.TRACK:
            return track
        if role == PlaybackRole.ARTIST:
            return track.artist or QCoreApplication.translate(
                "LibraryLabels", "Unknown Artist"
            )
        if role == PlaybackRole.ALBUM:
            return track.album or QCoreApplication.translate(
                "LibraryLabels", "Unknown Album"
            )
        if role == PlaybackRole.IS_CURRENT:
            return entry.entry_id == self._current_entry_id
        return None

    def retranslate(self, _language_tag: str) -> None:
        """Notify views that translated display and accessibility data changed."""

        if not self._entries:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._entries) - 1, 0),
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.AccessibleTextRole,
                Qt.ItemDataRole.AccessibleDescriptionRole,
                PlaybackRole.ARTIST,
                PlaybackRole.ALBUM,
            ],
        )

    def reconcile_tracks(self, tracks_by_id: dict[int, Track]) -> None:
        updated = [
            PlaybackEntry(entry.entry_id, replacement)
            for entry in self._entries
            if (replacement := tracks_by_id.get(entry.track.track_id)) is not None
        ]
        if updated == self._entries:
            return
        same_occurrences = len(updated) == len(self._entries) and all(
            old.entry_id == new.entry_id
            for old, new in zip(self._entries, updated, strict=True)
        )
        if not same_occurrences:
            self.beginResetModel()
            self._entries = updated
            if self.row_for_entry_id(self._current_entry_id) is None:
                self._current_entry_id = None
            self.endResetModel()
            return
        changed_rows = tuple(
            row
            for row, (old, new) in enumerate(zip(self._entries, updated, strict=True))
            if old != new
        )
        self._entries = updated
        for row in changed_rows:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, [])

    def row_for_entry_id(self, entry_id: int | None) -> int | None:
        if entry_id is None:
            return None
        return next(
            (
                row
                for row, entry in enumerate(self._entries)
                if entry.entry_id == entry_id
            ),
            None,
        )


class PlaybackQueueModel(_PlaybackListModel):
    """Ordered pending Tracks that have not started yet."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        workspace: LibraryWorkspace | None = None,
        insert_tracks: Callable[[tuple[Track, ...], int], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._insert_tracks = insert_tracks

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        entry = self.entry_at(index.row()) if index.isValid() else None
        if role == Qt.ItemDataRole.AccessibleDescriptionRole and entry is not None:
            title = entry.track.title or QCoreApplication.translate(
                "LibraryLabels", "Untitled Track"
            )
            return self.tr("Remove {title} from Playback Queue").format(title=title)
        return super().data(index, role)

    def append_entry(self, entry: PlaybackEntry) -> None:
        self.insert_entries(len(self._entries), (entry,))

    def insert_entries(
        self,
        row: int,
        entries: tuple[PlaybackEntry, ...],
    ) -> None:
        if not entries:
            return
        row = min(max(0, row), len(self._entries))
        self.beginInsertRows(_ROOT_INDEX, row, row + len(entries) - 1)
        self._entries[row:row] = entries
        self.endInsertRows()

    def flags(
        self,
        index: QModelIndex | QPersistentModelIndex,
    ) -> Qt.ItemFlag:
        default_flags = super().flags(index)
        if index.isValid():
            return default_flags | Qt.ItemFlag.ItemIsDragEnabled
        return default_flags | Qt.ItemFlag.ItemIsDropEnabled

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [QUEUE_ENTRY_MIME_TYPE, TRACK_MIME_TYPE, PLAYLIST_MIME_TYPE]

    def mimeData(
        self,
        indexes: Sequence[QModelIndex],
    ) -> QMimeData:
        entry = self.entry_at(indexes[0].row()) if indexes else None
        if entry is None:
            return QMimeData()
        mime_data: QMimeData
        if self._workspace is None:
            mime_data = QMimeData()
        else:
            mime_data = TrackSelectionMimeData(
                self._workspace,
                (entry.track.track_id,),
            )
        mime_data.setData(
            QUEUE_ENTRY_MIME_TYPE,
            QByteArray(str(entry.entry_id).encode("ascii")),
        )
        return mime_data

    def canDropMimeData(
        self,
        data: QMimeData,
        action: Qt.DropAction,
        row: int,
        column: int,
        parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if action is Qt.DropAction.IgnoreAction:
            return True
        if column > 0 or row < -1 or row > len(self._entries):
            return False
        if data.hasFormat(QUEUE_ENTRY_MIME_TYPE):
            return (
                action is Qt.DropAction.MoveAction
                and self._queue_entry_id(data) is not None
            )
        if action not in (Qt.DropAction.CopyAction, Qt.DropAction.MoveAction):
            return False
        workspace = self._workspace
        return (
            workspace is not None
            and self._insert_tracks is not None
            and dropped_tracks(data, workspace) is not None
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
        if action is Qt.DropAction.IgnoreAction:
            return True
        destination_child = self._destination_row(row, parent)
        if data.hasFormat(QUEUE_ENTRY_MIME_TYPE):
            entry_id = self._queue_entry_id(data)
            source_row = self.row_for_entry_id(entry_id)
            if source_row is None:
                return False
            if source_row <= destination_child <= source_row + 1:
                return True
            return self.moveRows(
                _ROOT_INDEX,
                source_row,
                1,
                _ROOT_INDEX,
                destination_child,
            )
        workspace = self._workspace
        insert_tracks = self._insert_tracks
        if workspace is None or insert_tracks is None:
            return False
        tracks = dropped_tracks(data, workspace)
        return tracks is not None and insert_tracks(tracks, destination_child)

    def _destination_row(
        self,
        row: int,
        parent: QModelIndex | QPersistentModelIndex,
    ) -> int:
        if row < 0:
            row = parent.row() if parent.isValid() else len(self._entries)
        return min(max(0, row), len(self._entries))

    def _queue_entry_id(self, data: QMimeData) -> int | None:
        if not data.hasFormat(QUEUE_ENTRY_MIME_TYPE):
            return None
        try:
            raw_entry_id = data.data(QUEUE_ENTRY_MIME_TYPE).data()
            entry_id = int(bytes(raw_entry_id).decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            return None
        return entry_id if self.row_for_entry_id(entry_id) is not None else None

    def take_first(self) -> PlaybackEntry | None:
        if not self._entries:
            return None
        self.beginRemoveRows(_ROOT_INDEX, 0, 0)
        entry = self._entries.pop(0)
        self.endRemoveRows()
        return entry

    def remove_entry(self, entry_id: int) -> bool:
        row = self.row_for_entry_id(entry_id)
        if row is None:
            return False
        self.beginRemoveRows(_ROOT_INDEX, row, row)
        del self._entries[row]
        self.endRemoveRows()
        return True

    def clear(self) -> None:
        if not self._entries:
            return
        self.beginRemoveRows(_ROOT_INDEX, 0, len(self._entries) - 1)
        self._entries.clear()
        self.endRemoveRows()

    def move_entry(self, source_row: int, destination_row: int) -> bool:
        if not 0 <= destination_row < len(self._entries):
            return False
        destination_child = (
            destination_row if destination_row < source_row else destination_row + 1
        )
        return self.moveRows(
            _ROOT_INDEX,
            source_row,
            1,
            _ROOT_INDEX,
            destination_child,
        )

    def moveRows(
        self,
        source_parent: QModelIndex | QPersistentModelIndex,
        source_row: int,
        count: int,
        destination_parent: QModelIndex | QPersistentModelIndex,
        destination_child: int,
    ) -> bool:
        row_count = len(self._entries)
        if (
            source_parent.isValid()
            or destination_parent.isValid()
            or count <= 0
            or source_row < 0
            or source_row + count > row_count
            or destination_child < 0
            or destination_child > row_count
            or source_row <= destination_child <= source_row + count
        ):
            return False
        if not self.beginMoveRows(
            _ROOT_INDEX,
            source_row,
            source_row + count - 1,
            _ROOT_INDEX,
            destination_child,
        ):
            return False
        moving = self._entries[source_row : source_row + count]
        del self._entries[source_row : source_row + count]
        insertion_row = (
            destination_child - count
            if destination_child > source_row
            else destination_child
        )
        self._entries[insertion_row:insertion_row] = moving
        self.endMoveRows()
        return True


class PlaybackHistoryModel(_PlaybackListModel):
    """Newest-first record of Tracks that started during this run."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        workspace: LibraryWorkspace | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace

    def flags(
        self,
        index: QModelIndex | QPersistentModelIndex,
    ) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.model() is self and self._workspace is not None:
            return flags | Qt.ItemFlag.ItemIsDragEnabled
        return flags

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.IgnoreAction

    def dropMimeData(
        self,
        data: QMimeData,
        action: Qt.DropAction,
        row: int,
        column: int,
        parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        return False

    def mimeTypes(self) -> list[str]:
        return [TRACK_MIME_TYPE]

    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:
        workspace = self._workspace
        if workspace is None:
            return QMimeData()
        rows = sorted(
            {
                index.row()
                for index in indexes
                if index.isValid() and index.model() is self
            }
        )
        track_ids: list[int] = []
        for row in rows:
            entry = self.entry_at(row)
            if entry is None or workspace.track(entry.track.track_id) != entry.track:
                return QMimeData()
            track_ids.append(entry.track.track_id)
        if not track_ids:
            return QMimeData()
        return TrackSelectionMimeData(workspace, tuple(track_ids))

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        if role == Qt.ItemDataRole.AccessibleDescriptionRole and bool(
            super().data(index, PlaybackRole.IS_CURRENT)
        ):
            return self.tr("Current Playback History entry")
        return super().data(index, role)

    def record(self, entry: PlaybackEntry) -> None:
        self.beginInsertRows(_ROOT_INDEX, 0, 0)
        self._entries.insert(0, entry)
        self.endInsertRows()
        self.set_current_entry(entry.entry_id)

    def set_current_entry(self, entry_id: int | None) -> None:
        if entry_id == self._current_entry_id:
            return
        previous = self.row_for_entry_id(self._current_entry_id)
        current = self.row_for_entry_id(entry_id)
        self._current_entry_id = entry_id
        for row in (previous, current):
            if row is not None:
                index = self.index(row, 0)
                self.dataChanged.emit(
                    index,
                    index,
                    [
                        PlaybackRole.IS_CURRENT,
                        Qt.ItemDataRole.AccessibleDescriptionRole,
                    ],
                )

    def clear(self) -> None:
        self.set_current_entry(None)
        if not self._entries:
            return
        self.beginRemoveRows(_ROOT_INDEX, 0, len(self._entries) - 1)
        self._entries.clear()
        self.endRemoveRows()


__all__ = [
    "QUEUE_ENTRY_MIME_TYPE",
    "PlaybackEntry",
    "PlaybackHistoryModel",
    "PlaybackQueueModel",
    "PlaybackRole",
]
