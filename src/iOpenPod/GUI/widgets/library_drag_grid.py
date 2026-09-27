"""Shared Track drag behavior for Library card grids."""

from PySide6.QtCore import QEvent, QModelIndex, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractItemView, QWidget

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.GUI.presentation.i18n.text import track_count_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.track_drag_preview import (
    drag_preview_hot_spot,
    render_count_drag_preview,
)
from iOpenPod.GUI.widgets.selection_grid import SelectionGridView
from iPodDB.library import Track


class LibraryDragGridView(SelectionGridView):
    """Resolve Library cards for Track drags and double-click activation."""

    tracksActivated = Signal(object)

    def __init__(
        self,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._library_workspace: LibraryWorkspace | None = None
        self.doubleClicked.connect(self._activated)

    def _activated(self, index: QModelIndex) -> None:
        workspace = self._library_workspace
        if workspace is None or not index.isValid():
            return
        tracks = self._tracks_for_index(workspace, index)
        if tracks:
            self.tracksActivated.emit(tracks)

    def set_library_workspace(self, workspace: LibraryWorkspace) -> None:
        self._library_workspace = workspace
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._refresh_drag_tooltip()

    def startDrag(self, _supported_actions: Qt.DropAction) -> None:
        workspace = self._library_workspace
        if workspace is None or workspace.locked:
            return
        revision = workspace.edit_revision
        tracks_by_id: dict[int, Track] = {}
        for index in sorted(
            self.selectionModel().selectedIndexes(), key=lambda i: i.row()
        ):
            for track in self._tracks_for_index(workspace, index):
                tracks_by_id.setdefault(track.track_id, track)
        tracks = tuple(tracks_by_id.values())
        if not tracks or revision != workspace.edit_revision or workspace.locked:
            return

        pixmap = render_count_drag_preview(
            track_count_text(len(tracks)),
            base_font=self.font(),
            tokens=self._theme_manager.tokens,
            device_pixel_ratio=self.devicePixelRatioF(),
        )
        drag = QDrag(self)
        drag.setMimeData(
            TrackSelectionMimeData(
                workspace,
                tuple(track.track_id for track in tracks),
            )
        )
        drag.setPixmap(pixmap)
        drag.setHotSpot(drag_preview_hot_spot(pixmap))
        drag.exec(Qt.DropAction.CopyAction)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh_drag_tooltip()
        super().changeEvent(event)

    def _tracks_for_index(
        self,
        workspace: LibraryWorkspace,
        index: QModelIndex,
    ) -> tuple[Track, ...]:
        raise NotImplementedError

    def _refresh_drag_tooltip(self) -> None:
        if self._library_workspace is not None:
            self.setToolTip(
                self.tr(
                    "Drag selected cards to a Playlist, the Queue, or the Player. "
                    "Hold Shift while dragging empty space to box select."
                )
            )


__all__ = ["LibraryDragGridView"]
