"""Virtualized Photo grid using the Library card-grid system."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractItemView, QListView, QWidget

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import PhotoSelectionMimeData
from iOpenPod.app.models.photo_list_model import (
    PhotoFilterProxyModel,
    PhotoListModel,
    PhotoRole,
)
from iOpenPod.app.models.selection_grouping import SelectionGroupingProxyModel
from iOpenPod.GUI.delegates.photo_card_delegate import PhotoCardDelegate
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.track_drag_preview import (
    drag_preview_hot_spot,
    render_count_drag_preview,
)
from iOpenPod.GUI.widgets.selection_grid import SelectionGridView


class PhotoGridView(SelectionGridView):
    """Render large Photo collections with the Album grid's virtualized geometry."""

    def __init__(
        self,
        model: PhotoListModel | PhotoFilterProxyModel,
        theme_manager: ThemeManager,
        photo_provider: PhotoPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("photoGrid")
        self.setAccessibleName(self.tr("Photos"))
        self._theme_manager = theme_manager
        self._library_workspace: LibraryWorkspace | None = None
        self._photo_model = model
        self.setModel(model)
        self.setItemDelegate(PhotoCardDelegate(theme_manager, photo_provider, self))
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
        theme_manager.effectiveThemeChanged.connect(self._update_viewport)
        photo_provider.photoChanged.connect(self._photo_changed)
        photo_provider.cleared.connect(self._update_viewport)
        photo_provider.capacityAvailable.connect(self._update_viewport)

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
        photo_ids = tuple(
            dict.fromkeys(
                photo.photo_id
                for index in sorted(
                    self.selectionModel().selectedIndexes(), key=lambda i: i.row()
                )
                if (photo := index.data(PhotoRole.PHOTO)) is not None
            )
        )
        if not photo_ids or revision != workspace.edit_revision or workspace.locked:
            return

        pixmap = render_count_drag_preview(
            self.tr("%n Photos", None, len(photo_ids)),
            base_font=self.font(),
            tokens=self._theme_manager.tokens,
            device_pixel_ratio=self.devicePixelRatioF(),
        )
        drag = QDrag(self)
        drag.setMimeData(PhotoSelectionMimeData(workspace, photo_ids))
        drag.setPixmap(pixmap)
        drag.setHotSpot(drag_preview_hot_spot(pixmap))
        drag.exec(Qt.DropAction.CopyAction)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.setAccessibleName(self.tr("Photos"))
            self._refresh_drag_tooltip()
        super().changeEvent(event)

    def _photo_changed(self, photo_id: int) -> None:
        viewport = self.viewport()
        visible_rect = viewport.rect()
        presentation_model = self.model()
        for source_index in self._photo_model.indexes_for_photo(photo_id):
            index = (
                presentation_model.mapFromSource(source_index)
                if isinstance(presentation_model, SelectionGroupingProxyModel)
                else source_index
            )
            photo_rect = self.visualRect(index)
            if photo_rect.isValid() and photo_rect.intersects(visible_rect):
                viewport.update(photo_rect)

    def _update_viewport(self, *_args: object) -> None:
        self.viewport().update()

    def _refresh_drag_tooltip(self) -> None:
        if self._library_workspace is not None:
            self.setToolTip(
                self.tr(
                    "Drag selected Photos to a Photo Album in the sidebar. "
                    "Hold Shift while dragging empty space to box select."
                )
            )


__all__ = ["PhotoGridView"]
