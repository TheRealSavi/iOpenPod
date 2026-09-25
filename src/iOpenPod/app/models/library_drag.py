"""In-process Library drags bound to one unchanged Library Workspace."""

from PySide6.QtCore import QMimeData

from iOpenPod.app.library_workspace import LibraryWorkspace
from iPodDB.library import Photo, PlaylistKind, Track

TRACK_MIME_TYPE = "application/x-iopenpod-track-selection"
PLAYLIST_MIME_TYPE = "application/x-iopenpod-playlist-selection"
PHOTO_MIME_TYPE = "application/x-iopenpod-photo-selection"


class _LibraryMimeData(QMimeData):
    """Keep semantic selections private to this process and Library revision."""

    def __init__(self, workspace: LibraryWorkspace) -> None:
        super().__init__()
        self._workspace = workspace
        self._revision = workspace.edit_revision

    def belongs_to(
        self,
        workspace: LibraryWorkspace,
        *,
        require_editable: bool = True,
    ) -> bool:
        return (
            workspace is self._workspace
            and self._revision == workspace.edit_revision
            and (not require_editable or not workspace.locked)
        )


class TrackSelectionMimeData(_LibraryMimeData):
    """One or more Track occurrences sharing the Library Track drag interface."""

    def __init__(self, workspace: LibraryWorkspace, track_ids: tuple[int, ...]) -> None:
        super().__init__(workspace)
        self.track_ids = track_ids
        self.setData(TRACK_MIME_TYPE, b"selection")

    def belongs_to(
        self,
        workspace: LibraryWorkspace,
        *,
        require_editable: bool = True,
    ) -> bool:
        return bool(self.track_ids) and super().belongs_to(
            workspace,
            require_editable=require_editable,
        )


class PlaylistSelectionMimeData(_LibraryMimeData):
    """One saved Playlist whose ordered Track occurrences can be resolved on drop."""

    def __init__(self, workspace: LibraryWorkspace, playlist_id: int) -> None:
        super().__init__(workspace)
        self.playlist_id = playlist_id
        self.setData(PLAYLIST_MIME_TYPE, b"selection")


class PhotoSelectionMimeData(_LibraryMimeData):
    """One or more Photos sharing the Photo Album drop interface."""

    def __init__(self, workspace: LibraryWorkspace, photo_ids: tuple[int, ...]) -> None:
        super().__init__(workspace)
        self.photo_ids = photo_ids
        self.setData(PHOTO_MIME_TYPE, b"selection")

    def belongs_to(
        self,
        workspace: LibraryWorkspace,
        *,
        require_editable: bool = True,
    ) -> bool:
        return bool(self.photo_ids) and super().belongs_to(
            workspace,
            require_editable=require_editable,
        )


def dropped_tracks(
    data: QMimeData,
    workspace: LibraryWorkspace,
    *,
    require_editable: bool = False,
) -> tuple[Track, ...] | None:
    """Resolve a current Track or Playlist drag through one shared interface."""

    if isinstance(data, TrackSelectionMimeData):
        if not data.belongs_to(workspace, require_editable=require_editable):
            return None
        tracks = tuple(workspace.track(track_id) for track_id in data.track_ids)
        if any(track is None for track in tracks):
            return None
        return tuple(track for track in tracks if track is not None)
    if isinstance(data, PlaylistSelectionMimeData):
        if not data.belongs_to(workspace, require_editable=require_editable):
            return None
        playlist = workspace.playlist(data.playlist_id)
        if playlist is None or playlist.kind is PlaylistKind.FOLDER:
            return None
        tracks = workspace.tracks_for(playlist.playlist_id)
        return tracks or None
    return None


def dropped_photos(
    data: QMimeData,
    workspace: LibraryWorkspace,
    *,
    require_editable: bool = False,
) -> tuple[Photo, ...] | None:
    """Resolve a current Photo drag for a compatible drop target."""

    if not isinstance(data, PhotoSelectionMimeData) or not data.belongs_to(
        workspace,
        require_editable=require_editable,
    ):
        return None
    library = workspace.photos
    if library is None:
        return None
    by_id = {photo.photo_id: photo for photo in library.photos}
    photos = tuple(by_id.get(photo_id) for photo_id in data.photo_ids)
    if any(photo is None for photo in photos):
        return None
    return tuple(photo for photo in photos if photo is not None)


__all__ = [
    "PHOTO_MIME_TYPE",
    "PLAYLIST_MIME_TYPE",
    "TRACK_MIME_TYPE",
    "PhotoSelectionMimeData",
    "PlaylistSelectionMimeData",
    "TrackSelectionMimeData",
    "dropped_photos",
    "dropped_tracks",
]
