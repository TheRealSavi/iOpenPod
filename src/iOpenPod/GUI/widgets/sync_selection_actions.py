"""Bulk Sync Selection actions for highlighted Host Library items."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, QObject, QPoint, Qt, Slot
from PySide6.QtWidgets import QAbstractItemView, QMenu

from iOpenPod.app.models.album_list_model import AlbumRole, AlbumSummary
from iOpenPod.app.models.collection_list_model import CollectionRole, CollectionSummary
from iOpenPod.app.models.photo_list_model import PhotoRole
from iOpenPod.app.models.selection_grouping import SelectionGroupingRole
from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.photo_grid import PhotoGridView
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import Photo, Track

if TYPE_CHECKING:
    from iOpenPod.app.models.sync_selection import SyncSelection


class SyncSelectionActions(QObject):
    """Translate one highlighted selection into one batched membership change."""

    def __init__(self, selection: SyncSelection, parent: QObject) -> None:
        super().__init__(parent)
        self._selection = selection

    def install(self, view: QAbstractItemView) -> None:
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._menu_requested)

    @Slot(QPoint)
    def _menu_requested(self, point: QPoint) -> None:
        view = self.sender()
        if not isinstance(view, QAbstractItemView):
            return
        menu = self.build_menu(view, point)
        if menu is not None:
            menu.exec(view.viewport().mapToGlobal(point))
            menu.deleteLater()

    def build_menu(self, view: QAbstractItemView, point: QPoint) -> QMenu | None:
        index = view.indexAt(point)
        if (
            not index.isValid()
            or not index.flags() & Qt.ItemFlag.ItemIsSelectable
            or index.data(SelectionGroupingRole.IS_HEADER)
        ):
            return None
        highlighted = view.selectionModel()
        if not highlighted.isSelected(index):
            highlighted.setCurrentIndex(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )

        # Capture semantic identities before changing any checkbox: selection
        # grouping can rebuild the proxy rows as soon as membership changes.
        ids: set[int] = set()
        for selected in highlighted.selectedRows():
            if isinstance(view, TrackTable):
                track = selected.data(TrackRole.TRACK)
                if isinstance(track, Track):
                    ids.add(track.track_id)
            elif isinstance(view, AlbumGridView):
                album = selected.data(AlbumRole.SUMMARY)
                if isinstance(album, AlbumSummary):
                    ids.update(album.track_ids)
            elif isinstance(view, CollectionGridView):
                collection = selected.data(CollectionRole.SUMMARY)
                if isinstance(collection, CollectionSummary):
                    ids.update(collection.track_ids)
            elif isinstance(view, PhotoGridView):
                photo = selected.data(PhotoRole.PHOTO)
                if isinstance(photo, Photo):
                    ids.add(photo.photo_id)
        if not ids:
            return None

        set_checked = (
            self._selection.set_photos_checked
            if isinstance(view, PhotoGridView)
            else self._selection.set_tracks_checked
        )
        item_ids = tuple(sorted(ids))
        menu = QMenu(view)
        menu.setObjectName("syncSelectionContextMenu")
        for label, checked in (
            (self.tr("Select for Sync"), True),
            (self.tr("Deselect from Sync"), False),
        ):
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, value=checked: set_checked(item_ids, value)
            )
        return menu
