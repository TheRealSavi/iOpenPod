"""Virtualized album grid built on Qt's item-view framework."""

from PySide6.QtCore import QEvent, QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QListView, QWidget

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.album_list_model import AlbumRole, AlbumSummary
from iOpenPod.app.models.library_filter_models import AlbumFilterProxyModel
from iOpenPod.app.models.track_order import album_track_sort_key
from iOpenPod.GUI.delegates.album_card_delegate import AlbumCardDelegate
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.library_drag_grid import LibraryDragGridView
from iPodDB.library import MediaKind, Track


class AlbumGridView(LibraryDragGridView):
    """Render a large album catalogue without one QWidget per card."""

    def __init__(
        self,
        model: AlbumFilterProxyModel,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme_manager, parent)
        self.setObjectName("albumGrid")
        self.setAccessibleName(self.tr("Albums"))
        self.setModel(model)
        self.setItemDelegate(AlbumCardDelegate(theme_manager, artwork_provider, self))
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
        theme_manager.effectiveThemeChanged.connect(self._theme_changed)
        theme_manager.colorfulModeChanged.connect(self._colorful_mode_changed)
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        artwork_provider.cleared.connect(self._artwork_cache_cleared)

    def _tracks_for_index(
        self,
        workspace: LibraryWorkspace,
        index: QModelIndex,
    ) -> tuple[Track, ...]:
        summary = index.data(AlbumRole.SUMMARY)
        if not isinstance(summary, AlbumSummary):
            return ()
        return tuple(
            sorted(
                (
                    track
                    for track in workspace.tracks
                    if track.media_kind is MediaKind.MUSIC
                    and track.album_key == summary.key
                ),
                key=album_track_sort_key,
            )
        )

    def _theme_changed(self, _theme: str) -> None:
        self.viewport().update()

    def _colorful_mode_changed(self, _enabled: bool) -> None:
        self.viewport().update()

    def _artwork_changed(self, _artwork_id: int) -> None:
        self.viewport().update()

    def _artwork_cache_cleared(self) -> None:
        self.viewport().update()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.setAccessibleName(self.tr("Albums"))
        super().changeEvent(event)
