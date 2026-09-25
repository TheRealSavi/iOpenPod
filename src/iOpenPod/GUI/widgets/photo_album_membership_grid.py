"""Virtualized collection grid for Photo Album membership editing."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QAbstractItemView, QListView, QWidget

from iOpenPod.app.models.photo_album_membership_model import (
    PhotoAlbumMembershipModel,
)
from iOpenPod.GUI.delegates.photo_album_membership_delegate import (
    PhotoAlbumMembershipDelegate,
)
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView


class PhotoAlbumMembershipGrid(EqualizedGridView):
    """Render checked Photo Album collages without per-album widgets."""

    def __init__(
        self,
        model: PhotoAlbumMembershipModel,
        theme_manager: ThemeManager,
        photo_provider: PhotoPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("photoAlbumMembershipGrid")
        self.setProperty("collectionGrid", True)
        self.setAccessibleName(self.tr("Photo Albums"))
        self.setModel(model)
        self.setItemDelegate(
            PhotoAlbumMembershipDelegate(theme_manager, photo_provider, self)
        )
        self.synchronize_item_size()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(64)
        self.setUniformItemSizes(True)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        theme_manager.effectiveThemeChanged.connect(self._update_viewport)
        photo_provider.photoChanged.connect(self._update_viewport)
        photo_provider.cleared.connect(self._update_viewport)
        photo_provider.capacityAvailable.connect(self._update_viewport)
        self._refresh_tooltip()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.setAccessibleName(self.tr("Photo Albums"))
            self._refresh_tooltip()
        super().changeEvent(event)

    def _update_viewport(self, *_args: object) -> None:
        self.viewport().update()

    def _refresh_tooltip(self) -> None:
        self.setToolTip(
            self.tr("Click a Photo Album card to add or remove the selected Photos.")
        )


__all__ = ["PhotoAlbumMembershipGrid"]
