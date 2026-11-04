"""Virtualized artwork grid sharing the ordinary Track table's model and actions."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QAbstractItemView, QListView, QWidget

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.track_table_model import TrackColumn, TrackRole
from iOpenPod.GUI.delegates.track_card_delegate import TrackCardDelegate
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.track_drag import TrackDragController
from iOpenPod.GUI.widgets.selection_grid import SelectionGridView
from iPodDB.library import Track


class TrackGridView(SelectionGridView):
    """Single clicks select cards; explicit activation uses existing Track actions."""

    def __init__(
        self,
        model: TrackFilterProxyModel,
        theme: ThemeManager,
        artwork: ArtworkPixmapProvider,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setProperty("collectionGrid", True)
        self.setModel(model)
        self.setModelColumn(TrackColumn.TITLE)
        self.setItemDelegate(TrackCardDelegate(theme, artwork, self))
        self.synchronize_item_size()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(64)
        self.setUniformItemSizes(True)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._drag_controller = TrackDragController(self, theme, artwork)
        theme.effectiveThemeChanged.connect(self._update_viewport)
        theme.colorfulModeChanged.connect(self._update_viewport)
        artwork.artworkChanged.connect(self._update_viewport)
        artwork.cleared.connect(self._update_viewport)

    def set_library_workspace(self, workspace: LibraryWorkspace) -> None:
        self._drag_controller.set_library_workspace(workspace)

    def startDrag(self, _supported_actions: Qt.DropAction) -> None:
        tracks = tuple(
            track
            for index in sorted(self.selectedIndexes(), key=lambda index: index.row())
            if isinstance(track := index.data(TrackRole.TRACK), Track)
        )
        self._drag_controller.start(tracks)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                self.doubleClicked.emit(index)
            event.accept()
            return
        super().keyPressEvent(event)

    def _update_viewport(self, *_args: object) -> None:
        self.viewport().update()
