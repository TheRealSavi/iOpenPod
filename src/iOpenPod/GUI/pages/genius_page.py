"""Read-only browsing of native Genius collections captured from the Active iPod."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.models.device import ActiveIPod, DeviceCandidateId
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.track_table_model import TrackColumn, TrackTableModel
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import track_count_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import Track
from iPodDB.library.genius import GeniusBrowse, GeniusCollection, GeniusCollectionKind


class GeniusPage(QWidget):
    """Show saved members and Mix seed candidates without editing or generating."""

    playRequested = Signal(object)
    queueRequested = Signal(object)
    playNextRequested = Signal(object)

    def __init__(
        self,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("geniusPage")
        self._candidate_id: DeviceCandidateId | None = None
        self._browse = GeniusBrowse()
        self._library_tracks: dict[int, Track] = {}
        self._selected_id: str | None = None
        self._tracks = TrackTableModel(self)
        self._proxy = TrackFilterProxyModel(self._tracks, self)
        self._toolbar = LibraryToolbar(self)
        self._toolbar.set_namespace("genius")
        self._toolbar.queryChanged.connect(self._proxy.set_query)
        self._collections = QTreeWidget(self)
        self._collections.setObjectName("geniusCollections")
        self._collections.setHeaderHidden(True)
        self._collections.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._collections.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._collections.currentItemChanged.connect(self._collection_selected)
        self._table = TrackTable(
            self._proxy,
            settings,
            theme_manager,
            artwork_provider,
            "genius",
            self,
            context_columns=frozenset((TrackColumn.PLAYLIST_POSITION,)),
        )
        self._table.trackActivated.connect(self._activate_track)
        self._table.selectionModel().selectionChanged.connect(self._refresh_actions)
        self._heading = QLabel(self)
        self._heading.setObjectName("pageTitle")
        self._heading.setTextFormat(Qt.TextFormat.PlainText)
        self._summary = QLabel(self)
        self._summary.setObjectName("pageMeta")
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setTextFormat(Qt.TextFormat.PlainText)
        self._description.setWordWrap(True)
        self._issues = QLabel(self)
        self._issues.setObjectName("geniusIssues")
        self._issues.setTextFormat(Qt.TextFormat.PlainText)
        self._issues.setWordWrap(True)
        self._empty = QLabel(self)
        self._empty.setObjectName("geniusEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._play = ActionButton(parent=self, glyph="play")
        self._play.setObjectName("playSelectedGeniusTracks")
        self._play.clicked.connect(lambda: self._emit_selected("play"))
        self._play_next = ActionButton(parent=self, glyph="play-next")
        self._play_next.setObjectName("playNextGeniusTracks")
        self._play_next.clicked.connect(lambda: self._emit_selected("next"))
        self._queue = ActionButton(parent=self, glyph="play-last")
        self._queue.setObjectName("queueSelectedGeniusTracks")
        self._queue.clicked.connect(lambda: self._emit_selected("queue"))
        actions = QHBoxLayout()
        actions.addWidget(self._play)
        actions.addWidget(self._play_next)
        actions.addWidget(self._queue)
        actions.addStretch(1)
        detail = QWidget(self)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(
            LAYOUT.space_md, LAYOUT.space_md, LAYOUT.space_md, 0
        )
        detail_layout.addWidget(self._heading)
        detail_layout.addWidget(self._summary)
        detail_layout.addWidget(self._description)
        detail_layout.addLayout(actions)
        detail_layout.addWidget(self._table, 1)
        detail_layout.addWidget(self._empty, 1)
        split = QSplitter(self)
        split.addWidget(self._collections)
        split.addWidget(detail)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._issues)
        layout.addWidget(split, 1)
        self.retranslate_ui()

    @property
    def track_table(self) -> TrackTable:
        """Identify the table that must remain outside mutable Track actions."""
        return self._table

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        candidate_id = active.candidate.id if active is not None else None
        if candidate_id != self._candidate_id:
            self._selected_id = None
            self._toolbar.set_query("")
            self._proxy.set_query("")
        self._candidate_id = candidate_id
        self._browse = active.genius if active is not None else GeniusBrowse()
        self._library_tracks = (
            {track.track_id: track for track in active.library.tracks}
            if active is not None
            else {}
        )
        self._rebuild_collections()

    def retranslate_ui(self) -> None:
        self._toolbar.retranslate_ui()
        self._toolbar.configure(
            grid_title=self.tr("Genius"),
            grid_search_label=self.tr("Search Genius Tracks"),
            supports_list=False,
        )
        self._collections.setAccessibleName(self.tr("Genius collections"))
        self._play.setText(self.tr("Play selected"))
        self._play_next.setText(self.tr("Play next"))
        self._queue.setText(self.tr("Add to queue"))
        self._rebuild_collections()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

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
            font = section.font(0)
            font.setBold(True)
            section.setFont(0, font)
            section.setExpanded(True)
            for collection in items:
                item = QTreeWidgetItem(section, [collection.name])
                item.setData(0, Qt.ItemDataRole.UserRole, collection.collection_id)
                if collection.collection_id == self._selected_id:
                    selected = item
        if selected is not None:
            self._collections.setCurrentItem(selected)
        self._collections.blockSignals(False)
        if selected is None:
            self._selected_id = None
        self._issues.setText("\n".join(issue.detail for issue in self._browse.issues))
        self._issues.setVisible(bool(self._browse.issues))
        self._refresh_collection()

    def _collection_selected(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        value = (
            current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        )
        self._selected_id = value if isinstance(value, str) else None
        self._toolbar.set_query("")
        self._proxy.set_query("")
        self._table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self._refresh_collection()

    def _selected_collection(self) -> GeniusCollection | None:
        return next(
            (
                item
                for item in self._browse.collections
                if item.collection_id == self._selected_id
            ),
            None,
        )

    def _refresh_collection(self) -> None:
        collection = self._selected_collection()
        occurrences = (
            tuple(
                (position, self._library_tracks[identity])
                for position, identity in enumerate(collection.track_ids)
                if identity in self._library_tracks
            )
            if collection is not None
            else ()
        )
        self._tracks.replace_tracks(
            tuple(track for _position, track in occurrences),
            playlist_positions=tuple(position for position, _track in occurrences),
        )
        self._heading.setText(collection.name if collection else self.tr("Genius"))
        self._summary.setText(track_count_text(len(occurrences)) if collection else "")
        self._description.setText(
            self.tr(
                "Mix tracks are possible starting songs; the iPod generates the mix when you play it."
            )
            if collection is not None and collection.kind is GeniusCollectionKind.MIX
            else self.tr("Tracks saved in this Genius Playlist.")
            if collection is not None
            else ""
        )
        self._description.setVisible(collection is not None)
        self._table.setVisible(bool(occurrences))
        self._empty.setVisible(not occurrences)
        self._empty.setText(
            self.tr("Connect and choose an iPod to browse its Genius collections.")
            if self._candidate_id is None
            else self.tr("No Genius collections were found on this iPod.")
            if not self._browse.collections
            else self.tr("Choose a Genius Playlist or Mix.")
            if collection is None
            else self.tr("No available Tracks in this Genius collection.")
        )
        self._refresh_actions()

    def _selected_tracks(self) -> tuple[Track, ...]:
        return tuple(
            track
            for index in sorted(
                self._table.selectionModel().selectedRows(),
                key=lambda index: index.row(),
            )
            if (track := self._proxy.track_at(index)) is not None
        )

    def _refresh_actions(self, *_args: object) -> None:
        enabled = bool(self._selected_tracks())
        self._play.setEnabled(enabled)
        self._play_next.setEnabled(enabled)
        self._queue.setEnabled(enabled)

    def _emit_selected(self, action: str) -> None:
        tracks = self._selected_tracks()
        if tracks:
            if action == "play":
                self.playRequested.emit(tracks)
            elif action == "next":
                self.playNextRequested.emit(tracks)
            else:
                self.queueRequested.emit(tracks)

    def _activate_track(self, value: object) -> None:
        if isinstance(value, Track):
            self.playRequested.emit((value,))
