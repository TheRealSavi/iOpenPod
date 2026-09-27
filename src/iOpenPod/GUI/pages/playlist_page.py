"""Playlist browsing and session editing without database details or device I/O."""

from PySide6.QtCore import QCoreApplication, QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.models.track_table_model import TrackColumn, TrackTableModel
from iOpenPod.GUI.dialogs.playlist_editor import (
    PlaylistEditorDialog,
    kind_label,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import track_count_text
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.playlist_artwork_banner import PlaylistArtworkBanner
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import PlaylistKind, Track, validate_smart_playlist


class PlaylistPage(QWidget):
    """Show Playlist occurrences or recursive folder Tracks in the shared table."""

    trackActivated = Signal(object)
    queueRequested = Signal(object)
    playNextRequested = Signal(object)
    playlistSelected = Signal(object)
    playlistExportRequested = Signal(str, object)

    def __init__(
        self,
        workspace: LibraryWorkspace,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
        *,
        source_actions: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("playlistsPage")
        self._workspace = workspace
        self._source_actions = source_actions
        self._selected_id: int | None = None
        self._generation = workspace.generation
        self._query = ""
        # An occurrence projection holds references to the shared immutable Tracks;
        # a set-based filter would lose duplicate entries and playlist ordering.
        self._tracks = TrackTableModel(self)
        self._proxy = TrackFilterProxyModel(self._tracks, self)
        self._table = TrackTable(
            self._proxy,
            settings,
            theme_manager,
            artwork_provider,
            "playlists",
            self,
            context_columns=frozenset((TrackColumn.PLAYLIST_POSITION,)),
        )
        self._toolbar = LibraryToolbar(self)
        self._toolbar.set_namespace("playlists")
        self._toolbar.queryChanged.connect(self._set_query)
        self._table.trackActivated.connect(self.trackActivated.emit)

        self._heading = QLabel(self)
        self._heading.setObjectName("pageTitle")
        self._heading.setTextFormat(Qt.TextFormat.PlainText)
        self._heading.setWordWrap(True)
        self._summary = QLabel(self)
        self._summary.setObjectName("pageMeta")
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setTextFormat(Qt.TextFormat.PlainText)
        self._description.setWordWrap(True)

        self._edit = ActionButton(parent=self)
        self._edit.setObjectName("editPlaylist")
        self._edit.clicked.connect(lambda: self.edit_playlist(self._selected_id))
        self._evaluate = ActionButton(parent=self)
        self._evaluate.setObjectName("evaluateSmartPlaylist")
        self._evaluate.clicked.connect(
            lambda: self.evaluate_smart_playlist(self._selected_id)
        )
        self._remove = ActionButton(parent=self, kind=ActionButtonKind.DANGER)
        self._remove.setObjectName("removePlaylist")
        self._remove.clicked.connect(lambda: self.remove_playlist(self._selected_id))
        self._export = ActionButton(parent=self)
        self._export.setObjectName("exportPlaylist")
        self._export.clicked.connect(self._export_playlist)
        self._play_next = ActionButton(parent=self, glyph="play-next")
        self._play_next.setObjectName("playNextPlaylist")
        self._play_next.clicked.connect(self._play_next_tracks)
        self._queue = ActionButton(parent=self, glyph="play-last")
        self._queue.setObjectName("queuePlaylist")
        self._queue.clicked.connect(self._queue_tracks)
        actions = QHBoxLayout()
        actions.addWidget(self._edit)
        actions.addWidget(self._evaluate)
        actions.addWidget(self._remove)
        actions.addStretch(1)
        actions.addWidget(self._export)
        actions.addWidget(self._play_next)
        actions.addWidget(self._queue)

        self._banner = PlaylistArtworkBanner(
            theme_manager,
            artwork_provider,
            self,
        )
        header_layout = QVBoxLayout(self._banner)
        header_layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_md
        )
        header_layout.setSpacing(LAYOUT.space_xs)
        header_layout.addWidget(self._heading)
        header_layout.addWidget(self._summary)
        header_layout.addWidget(self._description)
        header_layout.addLayout(actions)

        self._empty = QLabel(self)
        self._empty.setObjectName("playlistEmpty")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._banner)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._empty, 1)
        workspace.changed.connect(self._refresh)
        self.retranslate_ui()

    @property
    def selected_playlist_id(self) -> int | None:
        return self._selected_id

    def set_sync_selection(self, selection: SyncSelection) -> None:
        """Share Sync membership across every occurrence of a Host Track."""

        self._tracks.set_sync_selection(selection)

    def select_playlist(self, playlist_id: object) -> None:
        if (
            not isinstance(playlist_id, int)
            or self._workspace.playlist(playlist_id) is None
        ):
            self._selected_id = None
        else:
            self._selected_id = playlist_id
        self._query = ""
        self._toolbar.set_query("")
        self._proxy.set_query("")
        self._table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self._refresh()
        self.playlistSelected.emit(self._selected_id)

    def create_playlist(self, kind: object) -> None:
        if self._workspace.locked:
            return
        if not isinstance(kind, PlaylistKind) or self._workspace.snapshot is None:
            return
        generation = self._workspace.generation
        revision = self._workspace.revision
        selected = (
            self._workspace.playlist(self._selected_id)
            if self._selected_id is not None
            else None
        )
        parent_id = (
            selected.playlist_id
            if selected and selected.kind is PlaylistKind.FOLDER
            else selected.parent_id
            if selected
            else None
        )
        dialog = PlaylistEditorDialog(
            kind,
            parent=self,
            playlists=self._workspace.playlists,
        )
        try:
            if (
                dialog.exec() != QDialog.DialogCode.Accepted
                or generation != self._workspace.generation
                or revision != self._workspace.revision
                or self._workspace.locked
            ):
                return
            playlist = self._workspace.create(
                kind,
                dialog.name.text(),
                parent_id,
                smart=dialog.smart,
                description=dialog.description.text(),
                sort_order=dialog.sort_order,
            )
            self.select_playlist(playlist.playlist_id)
        except ValueError as error:
            self._show_error(error)
        finally:
            dialog.deleteLater()

    def edit_playlist(self, playlist_id: object) -> None:
        if self._workspace.locked:
            return
        playlist = (
            self._workspace.playlist(playlist_id)
            if isinstance(playlist_id, int)
            else None
        )
        if playlist is None:
            return
        generation = self._workspace.generation
        revision = self._workspace.revision
        dialog = PlaylistEditorDialog(
            playlist.kind,
            playlist,
            self,
            playlists=self._workspace.playlists,
        )
        try:
            if (
                dialog.exec() != QDialog.DialogCode.Accepted
                or generation != self._workspace.generation
                or revision != self._workspace.revision
                or self._workspace.locked
            ):
                return
            self._workspace.update(
                playlist.playlist_id,
                name=dialog.name.text(),
                description=dialog.description.text(),
                smart=dialog.smart if dialog.smart != playlist.smart else None,
                sort_order=dialog.sort_order,
            )
        except ValueError as error:
            self._show_error(error)
        finally:
            dialog.deleteLater()

    def remove_playlist(self, playlist_id: object) -> None:
        if self._workspace.locked:
            return
        playlist = (
            self._workspace.playlist(playlist_id)
            if isinstance(playlist_id, int)
            else None
        )
        if playlist is None:
            return
        revision = self._workspace.edit_revision
        folder = playlist.kind is PlaylistKind.FOLDER
        consequence = (
            "\n\n"
            + self.tr(
                "Every Playlist and folder inside this folder will also be removed."
            )
            if folder and self._workspace.children_of(playlist.playlist_id)
            else ""
        )
        answer = QMessageBox.question(
            self,
            self.tr("Remove Folder") if folder else self.tr("Remove Playlist"),
            self.tr("Remove '%1'?").replace("%1", playlist.name) + consequence,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._workspace.remove_playlist(playlist.playlist_id, revision)
        except ValueError as error:
            self._show_error(error)

    def evaluate_smart_playlist(self, playlist_id: object) -> None:
        if self._workspace.locked:
            return
        playlist = (
            self._workspace.playlist(playlist_id)
            if isinstance(playlist_id, int)
            else None
        )
        if playlist is None or playlist.kind is not PlaylistKind.SMART:
            return
        try:
            self._workspace.evaluate_smart(playlist.playlist_id)
        except ValueError as error:
            self._show_error(error)

    def _set_query(self, query: str) -> None:
        self._query = query.strip().casefold()
        self._proxy.set_query(query)
        self._refresh_contents()

    def _refresh(self) -> None:
        previous_id = self._selected_id
        if self._generation != self._workspace.generation:
            self._generation = self._workspace.generation
            mapping = self._workspace.saved_playlist_ids
            self._selected_id = (
                mapping.get(self._selected_id, self._selected_id)
                if mapping is not None and self._selected_id is not None
                else None
            )
            self._query = ""
            self._toolbar.set_query("")
            self._proxy.set_query("")
        playlist = (
            self._workspace.playlist(self._selected_id)
            if self._selected_id is not None
            else None
        )
        if playlist is None:
            self._selected_id = None
        self._heading.setText(playlist.name if playlist else "")
        self._description.setText(playlist.description if playlist else "")
        self._description.setVisible(bool(self._description.text()))
        tracks = (
            () if playlist is None else self._workspace.tracks_for(playlist.playlist_id)
        )
        positions: tuple[int | None, ...] | None = None
        if playlist is not None and playlist.kind is not PlaylistKind.FOLDER:
            resolved = tuple(
                (track, entry.position)
                for entry in playlist.entries
                if (track := self._workspace.track(entry.track_id)) is not None
            )
            tracks = tuple(track for track, _position in resolved)
            positions = tuple(position for _track, position in resolved)
        self._tracks.replace_tracks(tracks, playlist_positions=positions)
        self._banner.set_tracks(
            tracks,
            playlist_id=playlist.playlist_id if playlist is not None else None,
        )
        if playlist is not None:
            minutes = sum(track.length_ms for track in tracks) / 60_000
            self._summary.setText(
                self.tr("%1 · %2 · %3 min")
                .replace("%1", kind_label(playlist.kind))
                .replace("%2", track_count_text(len(tracks)))
                .replace("%3", f"{minutes:,.0f}")
            )
        else:
            self._summary.clear()
        self._edit.setVisible(playlist is not None and self._source_actions)
        self._edit.setEnabled(not self._workspace.locked)
        evaluable = False
        if playlist is not None and playlist.kind is PlaylistKind.SMART:
            try:
                if playlist.smart is not None:
                    validate_smart_playlist(playlist.smart)
                    evaluable = True
            except ValueError:
                pass
        self._evaluate.setVisible(
            playlist is not None
            and playlist.kind is PlaylistKind.SMART
            and self._source_actions
        )
        self._evaluate.setEnabled(evaluable and not self._workspace.locked)
        self._evaluate.setToolTip(
            ""
            if evaluable
            else self.tr("These Smart Playlist rules cannot be evaluated by iOpenPod.")
        )
        self._remove.setVisible(playlist is not None and self._source_actions)
        self._remove.setEnabled(not self._workspace.locked)
        self._remove.setText(
            self.tr("Remove Folder…")
            if playlist is not None and playlist.kind is PlaylistKind.FOLDER
            else self.tr("Remove Playlist…")
        )
        self._export.setVisible(playlist is not None and self._source_actions)
        self._export.setEnabled(
            playlist is not None and self._source_actions and not self._workspace.locked
        )
        self._queue.setVisible(playlist is not None and self._source_actions)
        self._play_next.setVisible(playlist is not None and self._source_actions)
        self._refresh_contents()
        if previous_id != self._selected_id:
            self.playlistSelected.emit(self._selected_id)

    def _refresh_contents(self) -> None:
        self._table.playlist_id = self._selected_id
        playlist = (
            self._workspace.playlist(self._selected_id)
            if self._selected_id is not None
            else None
        )
        folder = playlist is not None and playlist.kind is PlaylistKind.FOLDER
        empty = self._proxy.rowCount() == 0
        self._table.setVisible(not empty)
        self._queue.setEnabled(not empty and self._source_actions)
        self._play_next.setEnabled(not empty and self._source_actions)
        self._empty.setVisible(empty)
        if playlist is None:
            message = self.tr("Choose a playlist or folder in the sidebar.")
        elif self._workspace.snapshot is None:
            message = self.tr("Connect and choose an iPod to browse its playlists.")
        elif self._query:
            message = self.tr("No matches. Try another search.")
        elif folder:
            message = self.tr("No tracks in this folder's playlists.")
        elif playlist and playlist.kind is PlaylistKind.SMART:
            message = self.tr(
                "No tracks in this Smart Playlist.\nUse Edit to review its rules."
            )
        else:
            message = self.tr(
                "No tracks in this playlist. Drag tracks from a library table onto this playlist in the sidebar."
            )
        self._empty.setText(message)

    def _queue_tracks(self) -> None:
        tracks: list[Track] = []
        for row in range(self._proxy.rowCount()):
            track = self._proxy.track_at(self._proxy.index(row, 0))
            if track is not None:
                tracks.append(track)
                self.trackActivated.emit(track)
        self.queueRequested.emit(tuple(tracks))

    def _play_next_tracks(self) -> None:
        tracks = tuple(
            track
            for row in range(self._proxy.rowCount())
            if (track := self._proxy.track_at(self._proxy.index(row, 0))) is not None
        )
        self.playNextRequested.emit(tracks)

    def _export_playlist(self) -> None:
        playlist = (
            self._workspace.playlist(self._selected_id)
            if self._selected_id is not None
            else None
        )
        if playlist is None or self._workspace.locked:
            return
        self.playlistExportRequested.emit(
            playlist.name,
            self._workspace.tracks_for(playlist.playlist_id),
        )

    def _show_error(self, error: ValueError) -> None:
        QMessageBox.information(
            self, self.tr("Could Not Update Playlist"), workflow_text(str(error))
        )

    def retranslate_ui(self) -> None:
        self._toolbar.retranslate_ui()
        self._toolbar.configure(
            grid_title=self.tr("Playlists"),
            grid_search_label=QCoreApplication.translate(
                "LibraryLabels", "Search Tracks"
            ),
            supports_list=False,
        )
        self._edit.setText(self.tr("Edit…"))
        self._evaluate.setText(self.tr("Evaluate now"))
        self._remove.setText(self.tr("Remove Playlist…"))
        self._export.setText(self.tr("Export…"))
        self._queue.setText(QCoreApplication.translate("CommonActions", "Add to Queue"))
        self._queue.setToolTip(self.tr("Add tracks to the end of the Queue"))
        self._play_next.setText(self.tr("Play Next"))
        self._play_next.setToolTip(self.tr("Add tracks to the top of the Queue"))
        self._refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
