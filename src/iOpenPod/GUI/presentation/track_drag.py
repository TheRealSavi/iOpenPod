"""Shared Track drag payloads and previews for Library item views."""

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Qt, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractItemView

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import track_count_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.presentation.track_drag_preview import (
    drag_preview_hot_spot,
    render_single_track_drag_preview,
    render_track_count_drag_preview,
)
from iPodDB.library import Track

_ARTWORK_WAIT_MS = 150


class TrackDragController(QObject):
    """Keep ordinary and inline Track views on the same Library drag contract."""

    def __init__(
        self,
        view: QAbstractItemView,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
    ) -> None:
        super().__init__(view)
        self._view = view
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self._workspace: LibraryWorkspace | None = None

    def set_library_workspace(self, workspace: LibraryWorkspace) -> None:
        self._workspace = workspace
        self._view.setDragEnabled(True)
        self._view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def start(self, tracks: tuple[Track, ...]) -> None:
        workspace = self._workspace
        if workspace is None or workspace.locked or not tracks:
            return
        workspace_revision = (workspace.generation, workspace.revision)
        ratio = self._view.devicePixelRatioF()
        if len(tracks) == 1:
            track = tracks[0]
            self._await_artwork(track.artwork_id, ratio)
            if (
                workspace is not self._workspace
                or workspace.locked
                or workspace_revision != (workspace.generation, workspace.revision)
            ):
                return
            pixmap = render_single_track_drag_preview(
                track,
                title=track.title
                or QCoreApplication.translate("LibraryLabels", "Untitled Track"),
                artist=track.artist
                or QCoreApplication.translate("LibraryLabels", "Unknown Artist"),
                album=track.album
                or QCoreApplication.translate("LibraryLabels", "Unknown Album"),
                base_font=self._view.font(),
                tokens=self._theme_manager.tokens,
                artwork_provider=self._artwork_provider,
                device_pixel_ratio=ratio,
            )
        else:
            pixmap = render_track_count_drag_preview(
                track_count_text(len(tracks)),
                base_font=self._view.font(),
                tokens=self._theme_manager.tokens,
                device_pixel_ratio=ratio,
            )
        drag = QDrag(self._view)
        drag.setMimeData(
            TrackSelectionMimeData(workspace, tuple(track.track_id for track in tracks))
        )
        drag.setPixmap(pixmap)
        drag.setHotSpot(drag_preview_hot_spot(pixmap))
        drag.exec(Qt.DropAction.CopyAction)

    def _await_artwork(self, artwork_id: int, device_pixel_ratio: float) -> None:
        """Give the first drag the ordinary short window for its cover decode."""

        if artwork_id <= 0:
            return
        loop = QEventLoop(self)

        def artwork_changed(changed_id: int) -> None:
            if changed_id == artwork_id:
                loop.quit()

        self._artwork_provider.artworkChanged.connect(artwork_changed)
        try:
            if (
                self._artwork_provider.pixmap(
                    artwork_id,
                    LAYOUT.playback_row_artwork_size,
                    device_pixel_ratio,
                )
                is not None
            ):
                return
            timeout = QTimer(loop)
            timeout.setSingleShot(True)
            timeout.setInterval(_ARTWORK_WAIT_MS)
            timeout.timeout.connect(loop.quit)
            timeout.start()
            loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        finally:
            self._artwork_provider.artworkChanged.disconnect(artwork_changed)


__all__ = ["TrackDragController"]
