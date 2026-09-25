"""Virtualized fixed-cell grid for Artist, Genre, and media collections."""

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QListView, QWidget

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.collection_list_model import (
    CollectionRole,
    CollectionSummary,
    collection_key_for_track,
)
from iOpenPod.app.models.library_filter_models import CollectionFilterProxyModel
from iOpenPod.app.models.track_order import album_track_sort_key
from iOpenPod.GUI.delegates.collection_card_delegate import CollectionCardDelegate
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.library_drag_grid import LibraryDragGridView
from iPodDB.library import Track


class CollectionGridView(LibraryDragGridView):
    """Render collection collages without allocating a widget per card."""

    def __init__(
        self,
        model: CollectionFilterProxyModel,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        *,
        object_name: str,
        accessible_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme_manager, parent)
        self.setObjectName(object_name)
        self.setProperty("collectionGrid", True)
        self.setAccessibleName(accessible_name)
        self.setModel(model)
        self.setItemDelegate(
            CollectionCardDelegate(theme_manager, artwork_provider, self)
        )
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
        theme_manager.colorfulModeChanged.connect(self._update_viewport)
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        artwork_provider.cleared.connect(self._update_viewport)

    def _tracks_for_index(
        self,
        workspace: LibraryWorkspace,
        index: QModelIndex,
    ) -> tuple[Track, ...]:
        summary = index.data(CollectionRole.SUMMARY)
        if not isinstance(summary, CollectionSummary):
            return ()
        return tuple(
            sorted(
                (
                    track
                    for track in workspace.tracks
                    if collection_key_for_track(track, summary.kind) == summary.key
                ),
                key=album_track_sort_key,
            )
        )

    def _artwork_changed(self, _artwork_id: int) -> None:
        self._update_viewport()

    def _update_viewport(self, *_args: object) -> None:
        self.viewport().update()


__all__ = ["CollectionGridView"]
