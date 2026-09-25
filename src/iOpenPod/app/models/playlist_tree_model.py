"""A hierarchical Playlist projection with session-scoped internal moves."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import overload
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractItemModel,
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
    PlaylistSelectionMimeData,
    TrackSelectionMimeData,
)
from iPodDB.library import Playlist, PlaylistKind

_ROOT_INDEX = QModelIndex()
_MIME_TYPE = "application/x-iopenpod-playlist-move"
type _Index = QModelIndex | QPersistentModelIndex


class PlaylistRole(IntEnum):
    PLAYLIST = Qt.ItemDataRole.UserRole.value + 1
    KIND = Qt.ItemDataRole.UserRole.value + 2


@dataclass(frozen=True, slots=True)
class _Node:
    playlist: Playlist
    row: int
    token: int


class PlaylistTreeModel(QAbstractItemModel):
    """Present arbitrary folder depth without recursive tree construction.

    An internal drag identifies this model and its exact revision. A reset,
    another view, or a changed Active iPod therefore cannot reuse a stale drag.
    Moving changes only the Application Layer's temporary Library Workspace.
    """

    def __init__(
        self,
        workspace: LibraryWorkspace,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._identity = uuid4().hex
        self._revision = 0
        self._next_token = 0
        self._nodes: dict[int, _Node] = {}
        self._tokens: dict[int, _Node] = {}
        self._children: dict[int | None, list[_Node]] = {}
        workspace.changed.connect(self._reset)
        self._reset()

    def index(
        self,
        row: int,
        column: int,
        parent: _Index = _ROOT_INDEX,
    ) -> QModelIndex:
        if column != 0 or row < 0 or (parent.isValid() and parent.column() != 0):
            return QModelIndex()
        parent_node = self._node(parent)
        if parent.isValid() and parent_node is None:
            return QModelIndex()
        parent_id = parent_node.playlist.playlist_id if parent_node else None
        children = self._children.get(parent_id, [])
        if row >= len(children):
            return QModelIndex()
        return self.createIndex(row, column, children[row].token)

    @overload
    def parent(self) -> QObject | None: ...

    @overload
    def parent(self, index: _Index) -> QModelIndex: ...

    def parent(self, index: _Index | None = None) -> QObject | QModelIndex | None:
        if index is None:
            return super().parent()
        node = self._node(index)
        if node is None or node.playlist.parent_id is None:
            return QModelIndex()
        return self.index_for_id(node.playlist.parent_id)

    def rowCount(self, parent: _Index = _ROOT_INDEX) -> int:
        if parent.isValid() and parent.column() != 0:
            return 0
        node = self._node(parent)
        if parent.isValid() and node is None:
            return 0
        parent_id = node.playlist.playlist_id if node else None
        return len(self._children.get(parent_id, []))

    def columnCount(self, parent: _Index = _ROOT_INDEX) -> int:
        del parent
        return 1

    def data(
        self,
        index: _Index,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        node = self._node(index)
        if node is None:
            return None
        playlist = node.playlist
        if role in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
            Qt.ItemDataRole.AccessibleTextRole,
        ):
            return playlist.name or self.tr("Untitled Playlist")
        if role == PlaylistRole.PLAYLIST:
            # QVariant coerces a bare Python int to signed int64. iPod Playlist
            # identities occupy uint64, so retain them inside the semantic value.
            return playlist
        if role == PlaylistRole.KIND:
            return playlist.kind.value
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        node = self._node(index)
        if node is None:
            return Qt.ItemFlag.NoItemFlags
        flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )
        if not self._workspace.locked and node.playlist.kind in (
            PlaylistKind.FOLDER,
            PlaylistKind.PLAYLIST,
        ):
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        return flags

    def index_for_id(self, playlist_id: int) -> QModelIndex:
        node = self._nodes.get(playlist_id)
        if node is None:
            return QModelIndex()
        return self.createIndex(node.row, 0, node.token)

    def playlist_id(self, index: _Index) -> int | None:
        node = self._node(index)
        return node.playlist.playlist_id if node else None

    def mimeTypes(self) -> list[str]:
        return [_MIME_TYPE, TRACK_MIME_TYPE, PLAYLIST_MIME_TYPE]

    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:
        ids = {self.playlist_id(index) for index in indexes}
        if len(ids) != 1 or None in ids:
            return QMimeData()
        playlist_id = ids.pop()
        assert playlist_id is not None
        mime = PlaylistSelectionMimeData(self._workspace, playlist_id)
        payload = f"{self._identity}:{self._revision}:{playlist_id}"
        mime.setData(_MIME_TYPE, payload.encode("ascii"))
        return mime

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def canDropMimeData(
        self,
        data: QMimeData,
        action: Qt.DropAction,
        row: int,
        column: int,
        parent: _Index,
    ) -> bool:
        if isinstance(data, TrackSelectionMimeData):
            node = self._node(parent)
            return (
                action is Qt.DropAction.CopyAction
                and row == -1
                and column in (-1, 0)
                and node is not None
                and node.playlist.kind is PlaylistKind.PLAYLIST
                and data.belongs_to(self._workspace)
            )
        if action != Qt.DropAction.MoveAction or column not in (-1, 0):
            return False
        if row < -1 or row > self.rowCount(parent):
            return False
        playlist_id = self._dragged_id(data)
        if playlist_id is None:
            return False
        parent_node = self._node(parent)
        if parent.isValid() and parent_node is None:
            return False
        parent_id = parent_node.playlist.playlist_id if parent_node else None
        return self._workspace.can_move(playlist_id, parent_id)

    def dropMimeData(
        self,
        data: QMimeData,
        action: Qt.DropAction,
        row: int,
        column: int,
        parent: _Index,
    ) -> bool:
        if not self.canDropMimeData(data, action, row, column, parent):
            return False
        if isinstance(data, TrackSelectionMimeData):
            node = self._node(parent)
            assert node is not None
            try:
                self._workspace.set_tracks(
                    node.playlist.playlist_id,
                    (*node.playlist.track_ids, *data.track_ids),
                )
            except ValueError:
                return False
            return True
        playlist_id = self._dragged_id(data)
        if playlist_id is None:
            return False
        return self._workspace.move(playlist_id, self.playlist_id(parent))

    def _node(self, index: _Index) -> _Node | None:
        if not index.isValid() or index.model() is not self or index.column() != 0:
            return None
        return self._tokens.get(index.internalId())

    def _dragged_id(self, data: QMimeData) -> int | None:
        if not data.hasFormat(_MIME_TYPE):
            return None
        raw = bytes(data.data(_MIME_TYPE).data())
        if len(raw) > 128:
            return None
        try:
            identity, revision, playlist_id = raw.decode("ascii").split(":")
            if identity != self._identity or revision != str(self._revision):
                return None
            parsed_id = int(playlist_id)
        except (UnicodeError, ValueError):
            return None
        return parsed_id if parsed_id in self._nodes else None

    def _reset(self) -> None:
        self.beginResetModel()
        self._revision += 1
        self._nodes = {}
        self._tokens = {}
        self._children = {}
        for playlist in self._workspace.playlists:
            if playlist.system_managed:
                continue
            children = self._children.setdefault(playlist.parent_id, [])
            self._next_token += 1
            node = _Node(playlist, len(children), self._next_token)
            children.append(node)
            self._nodes[playlist.playlist_id] = node
            self._tokens[node.token] = node
        self.endResetModel()


__all__ = ["PlaylistRole", "PlaylistTreeModel"]
