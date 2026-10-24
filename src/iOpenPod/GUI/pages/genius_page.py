"""Read-only Genius browsing as a specialized Playlist page."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.device import ActiveIPod, DeviceCandidateId
from iOpenPod.GUI.delegates.genius_collection_delegate import (
    DETAIL_ROLE,
    SECTION_ROLE,
    GeniusCollectionDelegate,
)
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import track_count_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import Track
from iPodDB.library.genius import GeniusBrowse, GeniusCollection, GeniusCollectionKind


class GeniusPage(PlaylistPage):
    """Show captured Genius Playlists and Mix candidates without editing."""

    def __init__(
        self,
        workspace: LibraryWorkspace,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            workspace,
            settings,
            theme_manager,
            artwork_provider,
            parent,
            genius_browse=True,
        )
        self.setObjectName("geniusPage")
        self._candidate_id: DeviceCandidateId | None = None
        self._browse = GeniusBrowse()
        self._library_tracks: dict[int, Track] = {}
        self._selected_collection_id: str | None = None
        collections = self._genius_collections
        issues = self._genius_issues
        assert collections is not None and issues is not None
        self._collections: QTreeWidget = collections
        self._issues: QLabel = issues
        panel = self._genius_panel
        assert panel is not None
        self._panel = panel
        self._collections.setHeaderHidden(True)
        self._collections.setRootIsDecorated(False)
        self._collections.setIndentation(0)
        self._collections.setItemsExpandable(False)
        self._collections.setMouseTracking(True)
        self._collections.setItemDelegate(
            GeniusCollectionDelegate(theme_manager, self._collections)
        )
        self._collections.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._collections.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._collections.currentItemChanged.connect(self._collection_selected)
        self.track_table.trackActivated.connect(self._activate_track)
        self.retranslate_ui()

    @property
    def read_only_tables(self) -> tuple[TrackTable, ...]:
        return (self.track_table,)

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        candidate_id = active.candidate.id if active is not None else None
        if candidate_id != self._candidate_id:
            self._selected_collection_id = None
        self._candidate_id = candidate_id
        self._browse = active.genius if active is not None else GeniusBrowse()
        self._library_tracks = (
            {track.track_id: track for track in active.library.tracks}
            if active is not None
            else {}
        )
        self._rebuild_collections()

    def retranslate_ui(self) -> None:
        super().retranslate_ui()
        self._panel.set_title(self.tr("Genius"))
        self._collections.setAccessibleName(self.tr("Genius collections"))
        self._rebuild_collections()

    def _rebuild_collections(self) -> None:
        self._collections.blockSignals(True)
        self._collections.clear()
        selected: QTreeWidgetItem | None = None
        for kind, label in (
            (GeniusCollectionKind.PLAYLIST, self.tr("Genius Playlists")),
            (GeniusCollectionKind.MIX, self.tr("Genius Mixes")),
        ):
            items = tuple(
                item for item in self._browse.collections if item.kind is kind
            )
            if not items:
                continue
            section = QTreeWidgetItem(self._collections, [label])
            section.setFlags(section.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            section.setData(0, SECTION_ROLE, True)
            font = section.font(0)
            font.setBold(True)
            section.setFont(0, font)
            section.setExpanded(True)
            for collection in items:
                item = QTreeWidgetItem(section, [collection.name])
                item.setData(0, Qt.ItemDataRole.UserRole, collection.collection_id)
                item.setData(
                    0, DETAIL_ROLE, track_count_text(len(collection.track_ids))
                )
                if collection.collection_id == self._selected_collection_id:
                    selected = item
        if selected is not None:
            self._collections.setCurrentItem(selected)
        self._collections.blockSignals(False)
        self._panel.set_count(len(self._browse.collections))
        if selected is None:
            self._selected_collection_id = None
        self._issues.setText("\n".join(issue.detail for issue in self._browse.issues))
        self._issues.setVisible(bool(self._browse.issues))
        self._refresh_collection()

    def _collection_selected(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        value = (
            current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        )
        self._selected_collection_id = value if isinstance(value, str) else None
        self._refresh_collection()

    def _selected_collection(self) -> GeniusCollection | None:
        return next(
            (
                item
                for item in self._browse.collections
                if item.collection_id == self._selected_collection_id
            ),
            None,
        )

    def _refresh_collection(self) -> None:
        collection = self._selected_collection()
        if self._candidate_id is None:
            empty_message = self.tr(
                "Connect and choose an iPod to browse its Genius collections."
            )
        elif not self._browse.collections:
            empty_message = self.tr("No Genius collections were found on this iPod.")
        else:
            empty_message = self.tr("Choose a Genius Playlist or Mix.")
        self.show_genius_collection(
            collection,
            tuple(self._library_tracks.values()),
            empty_message=empty_message,
        )

    def _activate_track(self, value: object) -> None:
        if isinstance(value, Track):
            self.playRequested.emit((value,))
