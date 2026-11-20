"""Native Genius browsing with explicit genre Mix management."""

from dataclasses import replace

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from device_registry import FeatureSupport
from iOpenPod.app.core.settings.definitions import DRAFT_ALL_CHANGES
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.genius_mixes import (
    GENIUS_MIX_POLICY,
    MIX_CATALOG,
    MixPolicy,
    mix_limit,
    propose_mixes,
    supports_mix_creation,
)
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.device import ActiveIPod, DeviceCandidateId
from iOpenPod.GUI.delegates.genius_collection_delegate import (
    DETAIL_ROLE,
    HEADER_WIDGET_ROLE,
    SECTION_ROLE,
    GeniusCollectionDelegate,
)
from iOpenPod.GUI.dialogs.genius_mixes import (
    AddGeniusMixesDialog,
    GeniusMixSettingsDialog,
)
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import (
    mix_starting_track_count_text,
    track_count_text,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import IconButton, IconButtonKind
from iPodDB.library import PlaylistKind, Track
from iPodDB.library.genius import GeniusBrowse, GeniusCollection, GeniusCollectionKind


class GeniusPage(PlaylistPage):
    """Browse native collections and stage manual Mix additions."""

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
        self._settings = settings
        self._theme_manager = theme_manager
        self._active: ActiveIPod | None = None
        self._mix_buttons: tuple[IconButton, ...] = ()
        self._candidate_id: DeviceCandidateId | None = None
        self._browse = GeniusBrowse()
        self._visible_removals: frozenset[str] = frozenset()
        self._visible_additions: tuple[str, ...] = ()
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
        workspace.changed.connect(self._workspace_changed)
        settings.deviceStateChanged.connect(self._refresh_mix_actions)
        self.retranslate_ui()

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        self._active = active
        candidate_id = active.candidate.id if active is not None else None
        if candidate_id != self._candidate_id:
            self._selected_collection_id = None
        self._candidate_id = candidate_id
        self._browse = active.genius if active is not None else GeniusBrowse()
        tracks = (
            self._workspace.tracks
            if active is not None and self._workspace.snapshot is active.library
            else active.library.tracks
            if active is not None
            else ()
        )
        self._library_tracks = {track.track_id: track for track in tracks}
        self._browse = self._draft_browse()
        self._rebuild_collections()

    def _draft_browse(self) -> GeniusBrowse:
        """Display the remaining draft members without changing captured evidence."""
        active = self._active
        if active is None:
            return GeniusBrowse()
        if self._workspace.snapshot is not active.library:
            return active.genius
        canonical = {
            p.playlist_id
            for p in active.library.playlists
            if p.kind is PlaylistKind.GENIUS
        }
        persistent = {
            t.ipod.db_track_id: t.track_id
            for t in self._library_tracks.values()
            if t.ipod is not None
        }
        collections: list[GeniusCollection] = []
        for collection in active.genius.collections:
            if collection.native_playlist_id in canonical:
                playlist = self._workspace.playlist(collection.native_playlist_id)
                if playlist is None:
                    continue
                members = playlist.track_ids
                seed = persistent.get(playlist.genius_seed_persistent_id or 0)
            else:
                members = tuple(
                    i for i in collection.track_ids if i in self._library_tracks
                )
                if collection.track_ids and not members:
                    continue
                seed = collection.seed_track_id
                if seed is not None and seed not in self._library_tracks:
                    seed = (
                        members[0]
                        if members and collection.kind is GeniusCollectionKind.PLAYLIST
                        else None
                    )
            collections.append(
                replace(collection, track_ids=members, seed_track_id=seed)
            )
        return replace(active.genius, collections=tuple(collections))

    def retranslate_ui(self) -> None:
        super().retranslate_ui()
        self._panel.set_title(self.tr("Genius"))
        self._collections.setAccessibleName(self.tr("Genius collections"))
        self._rebuild_collections()

    def _rebuild_collections(self) -> None:
        self._mix_buttons = ()
        self._collections.blockSignals(True)
        self._collections.clear()
        selected: QTreeWidgetItem | None = None
        pending_removals = set(self._workspace.genius_collection_removals)
        self._visible_removals = frozenset(pending_removals)
        displayed = self._displayed_collections()
        self._visible_additions = (
            self._workspace.genius_mix_additions
            if self._active is not None
            and self._workspace.snapshot is self._active.library
            else ()
        )
        visible_native_ids = {c.native_playlist_id for c in displayed}
        promotions = (
            {
                entry.definition_key: entry.container_id
                for entry in self._active.genius_mix_state.entries
                if entry.definition_key in self._visible_additions
                and entry.container_id in visible_native_ids
            }
            if self._active is not None
            else {}
        )
        pending = tuple(
            definition
            for definition in MIX_CATALOG
            if definition.key in self._visible_additions
            and definition.key not in promotions
            and self._mixes_supported()
        )
        for kind, label in (
            (GeniusCollectionKind.PLAYLIST, self.tr("Genius Playlists")),
            (GeniusCollectionKind.MIX, self.tr("Genius Mixes")),
        ):
            if kind is GeniusCollectionKind.MIX and not self._mixes_supported():
                continue
            items = tuple(item for item in displayed if item.kind is kind)
            if not items and (
                kind is not GeniusCollectionKind.MIX or self._active is None
            ):
                continue
            section = QTreeWidgetItem(self._collections, [label])
            section.setFlags(section.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            section.setData(0, SECTION_ROLE, True)
            font = section.font(0)
            font.setBold(True)
            section.setFont(0, font)
            section.setExpanded(True)
            if kind is GeniusCollectionKind.MIX:
                section.setData(0, HEADER_WIDGET_ROLE, True)
                header = QWidget(self._collections)
                header.setAutoFillBackground(True)
                layout = QHBoxLayout(header)
                layout.setContentsMargins(LAYOUT.space_sm, 0, 0, 0)
                layout.setSpacing(0)
                heading = QLabel(label, header)
                heading.setObjectName("geniusMixSectionTitle")
                layout.addWidget(heading, 1)
                configure = IconButton(
                    "settings-sliders",
                    self.tr("Genius Mix settings"),
                    header,
                    kind=IconButtonKind.QUIET,
                )
                configure.setObjectName("geniusMixSettings")
                configure.clicked.connect(self._configure_mixes)
                add = IconButton(
                    "plus",
                    self.tr("Add Genius Mixes"),
                    header,
                    kind=IconButtonKind.QUIET,
                )
                add.setObjectName("addGeniusMixes")
                add.clicked.connect(self._add_mixes)
                layout.addWidget(configure)
                layout.addWidget(add)
                self._mix_buttons = (configure, add)
                self._collections.setItemWidget(section, 0, header)
            for collection in items:
                item = QTreeWidgetItem(section, [collection.name])
                item.setData(0, Qt.ItemDataRole.UserRole, collection.collection_id)
                item.setData(
                    0,
                    DETAIL_ROLE,
                    self.tr("Pending save")
                    if collection.native_playlist_id in promotions.values()
                    else mix_starting_track_count_text(len(collection.track_ids))
                    if kind is GeniusCollectionKind.MIX
                    else track_count_text(len(collection.track_ids)),
                )
                if collection.collection_id == self._selected_collection_id:
                    selected = item
            if kind is GeniusCollectionKind.MIX:
                for definition in pending:
                    item = QTreeWidgetItem(
                        section,
                        [QCoreApplication.translate("GeniusMixNames", definition.name)],
                    )
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    item.setData(0, DETAIL_ROLE, self.tr("Pending save"))
                    item.setToolTip(
                        0,
                        self.tr(
                            "This Mix will appear on your iPod after your changes are saved."
                        ),
                    )
        if selected is not None:
            self._collections.setCurrentItem(selected)
        self._collections.blockSignals(False)
        self._panel.set_count(len(displayed) + len(pending))
        if selected is None:
            self._selected_collection_id = None
        messages = [issue.detail for issue in self._browse.issues]
        if self._active is not None and self._active.genius_mix_state.error:
            messages.append(self._active.genius_mix_state.error)
        self._issues.setText("\n".join(messages))
        self._issues.setVisible(bool(messages))
        self._refresh_collection()
        self._refresh_mix_actions()

    def _mixes_supported(self) -> bool:
        return (
            self._active is not None
            and self._active.profile.capabilities.genius.mixes
            is FeatureSupport.SUPPORTED
        )

    def _displayed_collections(self) -> tuple[GeniusCollection, ...]:
        return tuple(
            collection
            for collection in self._browse.collections
            if collection.collection_id
            not in self._workspace.genius_collection_removals
            and (
                collection.kind is not GeniusCollectionKind.MIX
                or self._mixes_supported()
            )
        )

    def _workspace_changed(self) -> None:
        browse = self._browse
        if (
            self._active is not None
            and self._workspace.snapshot is self._active.library
        ):
            tracks = {track.track_id: track for track in self._workspace.tracks}
            if tracks != self._library_tracks:
                self._library_tracks = tracks
                self.update_genius_tracks(tuple(tracks.values()))
        self._browse = self._draft_browse()
        if (
            frozenset(self._workspace.genius_collection_removals)
            != self._visible_removals
            or self._workspace.genius_mix_additions != self._visible_additions
            or self._browse != browse
        ):
            self._rebuild_collections()
        else:
            self._refresh_mix_actions()

    def _refresh_mix_actions(self) -> None:
        active = self._active
        writer_available = active is not None and supports_mix_creation(active.profile)
        enabled = (
            active is not None
            and writer_available
            and not active.genius_mix_state.error
            and self._workspace.snapshot is active.library
            and not self._workspace.locked
            and self._settings.device_writable
        )
        disabled_reason = (
            self.tr(
                "This firmware supports Genius Mixes, but iOpenPod cannot create Mixes for this iPod yet."
            )
            if self._mixes_supported() and not writer_available
            else self.tr("Choose a supported iPod that is available for writing.")
        )
        for button in self._mix_buttons:
            button.setEnabled(enabled)
            button.setToolTip(button.accessibleName() if enabled else disabled_reason)
        collection = self._selected_collection()
        can_remove = (
            active is not None
            and collection is not None
            and not self._workspace.locked
            and self._workspace.snapshot is active.library
            and self._settings.device_writable
            and (
                collection.kind is GeniusCollectionKind.PLAYLIST
                or (
                    supports_mix_creation(active.profile)
                    and not active.genius_mix_state.error
                )
            )
        )
        self._remove.setEnabled(can_remove)
        self._remove.setText(
            self.tr("Remove Mix…")
            if collection is not None and collection.kind is GeniusCollectionKind.MIX
            else self.tr("Remove Playlist…")
        )

    def remove_playlist(self, playlist_id: object) -> None:
        """The inherited remove button targets the selected native collection."""
        active = self._active
        collection = self._selected_collection()
        if active is None or collection is None or not self._remove.isEnabled():
            return
        revision = self._workspace.edit_revision
        answer = QMessageBox.question(
            self,
            self.tr("Remove Genius Mix")
            if collection.kind is GeniusCollectionKind.MIX
            else self.tr("Remove Genius Playlist"),
            self.tr("Remove '%1'?").replace("%1", collection.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes or not self._accept_dialog_source(
            active
        ):
            return
        try:
            self._workspace.remove_genius_collection(collection, revision)
        except ValueError as error:
            QMessageBox.warning(
                self, self.tr("Could not remove Genius collection"), str(error)
            )

    def _add_mixes(self) -> None:
        active = self._active
        if (
            active is None
            or not self._mix_buttons
            or not self._mix_buttons[-1].isEnabled()
        ):
            return
        revision = self._workspace.edit_revision
        native_ids = {
            collection.native_playlist_id for collection in active.genius.collections
        }
        manual = {
            entry.definition_key
            for entry in active.genius_mix_state.entries
            if entry.added_at is None
            and entry.container_id in native_ids
            and f"genius-mix:{entry.container_id:016x}"
            not in self._workspace.genius_collection_removals
        }
        manual.update(self._workspace.genius_mix_additions)
        limit = mix_limit(active.profile)
        retained_mix_ids = {
            c.native_playlist_id
            for c in self._displayed_collections()
            if c.kind is GeniusCollectionKind.MIX
        }
        retained_keys = frozenset(
            e.definition_key
            for e in active.genius_mix_state.entries
            if e.container_id in retained_mix_ids
        )
        pending_new = set(self._workspace.genius_mix_additions) - retained_keys
        slots = (
            None
            if limit is None
            else max(0, limit - len(retained_mix_ids) - len(pending_new))
        )
        proposals = tuple(
            proposal
            for proposal in propose_mixes(
                self._workspace.desired_snapshot(), preview=True
            )
            if proposal.definition.key not in manual
        )
        dialog = AddGeniusMixesDialog(
            proposals,
            self,
            theme_manager=self._theme_manager,
            available_slots=slots,
            retained_keys=retained_keys,
        )
        try:
            if (
                dialog.exec() == QDialog.DialogCode.Accepted
                and dialog.selected_keys
                and self._accept_dialog_source(active)
            ):
                self._workspace.add_genius_mixes(dialog.selected_keys, revision)
        except ValueError as error:
            QMessageBox.warning(self, self.tr("Could not add Genius Mixes"), str(error))
        finally:
            dialog.deleteLater()

    def _configure_mixes(self) -> None:
        active = self._active
        if (
            active is None
            or not self._mix_buttons
            or not self._mix_buttons[0].isEnabled()
        ):
            return
        value, overridden = self._settings.device_edit_value(GENIUS_MIX_POLICY)
        policy = MixPolicy.decode(value) if overridden else MixPolicy()
        dialog = GeniusMixSettingsDialog(
            policy, self, max_count=mix_limit(active.profile)
        )
        try:
            if (
                dialog.exec() == QDialog.DialogCode.Accepted
                and self._accept_dialog_source(active)
            ):
                self._settings.set_device(GENIUS_MIX_POLICY, dialog.policy.encode())
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(
                self, self.tr("Could not save Genius Mix settings"), str(error)
            )
        finally:
            dialog.deleteLater()

    def _accept_dialog_source(self, source: ActiveIPod) -> bool:
        """Status refreshes may replace ActiveIPod without replacing its Library."""
        current = self._active
        valid = (
            current is not None
            and current.candidate.id == source.candidate.id
            and current.library is source.library
            and self._workspace.snapshot is source.library
            and current.database_name == source.database_name
            and current.database_fingerprint == source.database_fingerprint
            and current.profile == source.profile
            and current.genius == source.genius
            and current.genius_mix_state == source.genius_mix_state
            and not self._workspace.locked
            and self._settings.device_writable
        )
        if not valid:
            QMessageBox.warning(
                self,
                self.tr("iPod changed"),
                self.tr(
                    "The iPod or its library changed. Reopen the dialog and try again."
                ),
            )
        return valid

    def _collection_selected(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        value = (
            current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        )
        self._selected_collection_id = value if isinstance(value, str) else None
        self._refresh_collection()
        self._refresh_mix_actions()

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
        elif bool(self._visible_additions) and self._settings.get(DRAFT_ALL_CHANGES):
            empty_message = self.tr(
                "Mixes are pending. Open Review Changes to save them to your iPod."
            )
        elif self._visible_additions:
            empty_message = self.tr(
                "New Mixes are pending until your changes are saved."
            )
        elif not self._displayed_collections():
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
