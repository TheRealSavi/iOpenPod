"""Main application-shell composition for the QWidget prototype."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListView,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.artwork_controller import ArtworkLoadFailure
from iOpenPod.app.backups import BackupProgress
from iOpenPod.app.chaptered_conversion_controller import ChapteredConversionController
from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import (
    PLAYER_POSITION,
    WINDOW_GEOMETRY,
    PlayerPosition,
)
from iOpenPod.app.core.status import StatusAction, StatusProgress
from iOpenPod.app.device_controller import (
    DeviceEjectCompletion,
    DeviceOperation,
    DeviceOperationFailure,
)
from iOpenPod.app.display_text import source_text
from iOpenPod.app.host_media_folders import HostMediaFolder
from iOpenPod.app.host_media_library import (
    HostMediaLibrary,
    HostMediaScanProgress,
    PlaylistExternalReference,
)
from iOpenPod.app.library_export import (
    ExportProgress,
    ExportResult,
    PhotoExportResult,
)
from iOpenPod.app.library_export_controller import LibraryExportController
from iOpenPod.app.library_sync_helper import (
    IPodMediaLibrary,
    IPodMediaScanProgress,
)
from iOpenPod.app.library_workspace import TrackUpdate
from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.library_write_controller import PreparationState
from iOpenPod.app.media_tools_controller import MediaToolsController
from iOpenPod.app.models.device import ActiveIPod, DeviceDiscovery
from iOpenPod.app.photo_controller import PhotoLoadFailure
from iOpenPod.app.playback.backend import PlaybackFailure
from iOpenPod.app.podcasts.sync import PodcastSyncRequest
from iOpenPod.app.scrobbling.controller import create_scrobbling
from iOpenPod.app.scrobbling.models import ScrobbleResult
from iOpenPod.app.scrobbling.settings import configured_accounts
from iOpenPod.app.services.media_tools import MediaToolSetup
from iOpenPod.app.sync_controller import SyncController
from iOpenPod.app.sync_execution import (
    SyncExecutionResult,
    SyncExecutionStatus,
    SyncExecutor,
    preview_playlist_sync,
)
from iOpenPod.app.sync_plan import prepare_sync_plan
from iOpenPod.app.synesthesia import AnalysisProgress, TrackAnalysis
from iOpenPod.app.tag_normalization_controller import TagNormalizationController
from iOpenPod.app.tag_normalizer import tag_profile
from iOpenPod.app.updates.controller import UpdateController
from iOpenPod.app.updates.platform import create_update_provider
from iOpenPod.GUI.dialogs.device_picker import DevicePickerDialog
from iOpenPod.GUI.dialogs.external_playlist_files import (
    ExternalPlaylistFilesDialog,
)
from iOpenPod.GUI.dialogs.library_review import LibraryReviewDialog
from iOpenPod.GUI.dialogs.media_folders import (
    MediaFoldersDialog,
    MediaFolderSettingsDialog,
)
from iOpenPod.GUI.dialogs.media_tools_setup import MediaToolsSetupDialog
from iOpenPod.GUI.dialogs.playlist_export import PlaylistExportDialog
from iOpenPod.GUI.dialogs.scrobble_report import show_scrobble_report
from iOpenPod.GUI.dialogs.tag_normalizer import TagNormalizerDialog
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.backup_page import BackupPage
from iOpenPod.GUI.pages.collection_page import CollectionPage
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.pages.photo_page import PhotoPage
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.pages.podcast_page import PodcastPage
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.pages.synesthesia_page import SynesthesiaPage
from iOpenPod.GUI.pages.track_page import TrackPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import (
    device_count_text,
    english_count_fallback,
    planned_change_count_text,
    track_count_text,
)
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.presentation.podcast_artwork_provider import (
    PodcastArtworkPixmapProvider,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.sync_workspace import SyncStage, SyncWorkspace
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.host_media_drop import HostMediaDropTarget
from iOpenPod.GUI.widgets.playback_pane import PlaybackPane, PlaybackPaneHost
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.status_controls import StatusBarControls
from iOpenPod.GUI.widgets.status_list import StatusListButton
from iOpenPod.GUI.widgets.track_actions import TrackActions
from iPodDB.library import MediaKind, Photo, Track, TrackFieldEdit
from storage import HostPath

logger = logging.getLogger(__name__)

_BACKUP_STATUS_SOURCE = "backup-progress"
_SYNESTHESIA_PROGRESS_STATUS_SOURCE = "synesthesia-progress"
_SYNESTHESIA_NOTICE_STATUS_SOURCE = "synesthesia-notice"
_EJECT_STATUS_SOURCE = "device-eject"
_LIBRARY_WRITE_STATUS_SOURCE = "library-write"
_CHAPTERED_PROGRESS_STATUS_SOURCE = "chaptered-conversion-progress"
_CHAPTERED_NOTICE_STATUS_SOURCE = "chaptered-conversion-notice"


@dataclass(frozen=True)
class _SynesthesiaWindowState:
    geometry: QByteArray
    minimum_size: QSize
    visible_chrome: tuple[QWidget, ...]


class MainWindow(QMainWindow):
    """Own persistent player/status chrome around the replaceable workspaces."""

    def __init__(
        self,
        context: AppContext,
        *,
        auto_discover: bool = True,
    ) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._context = context
        self._update_reserved = False
        self._updates = UpdateController(
            context.status,
            lambda: create_update_provider(int(self.winId())),
            self._prepare_app_update,
            self._finish_app_update,
            self,
        )
        self._synesthesia_window_state: _SynesthesiaWindowState | None = None
        self._normalization = TagNormalizationController(
            context.library_workspace, self
        )
        self._normalizer_dialog = TagNormalizerDialog(self._normalization, self)
        self._normalizer_dialog.finished.connect(self._normalizer_closed)
        self._device_picker = DevicePickerDialog(self)
        self._export_controller = LibraryExportController(
            context.device_coordinator,
            context.device_controller,
            self,
        )
        self._export_progress: QProgressDialog | None = None
        self._chaptered_controller = ChapteredConversionController(
            context.library_workspace,
            context.device_controller,
            context.device_coordinator,
            self,
        )
        self._chaptered_controller.progressChanged.connect(
            self._chaptered_progress_changed
        )
        self._chaptered_controller.finished.connect(self._chaptered_finished)
        self._chaptered_controller.failed.connect(self._chaptered_failed)
        self._chaptered_controller.changed.connect(self._chaptered_availability_changed)
        self._export_controller.progressChanged.connect(self._export_progress_changed)
        self._export_controller.finished.connect(self._export_finished)
        self._export_controller.failed.connect(self._export_failed)
        self._export_controller.cancelled.connect(self._export_cancelled)
        self._pending_host_media_library: HostMediaLibrary | None = None
        self._review_host: HostMediaLibrary | None = None
        self._review_ipod: IPodMediaLibrary | None = None
        self._review_active: ActiveIPod | None = None
        scrobbler, self._scrobbling = create_scrobbling(
            context.device_coordinator,
            context.settings,
            context.device_controller,
            self,
        )
        self._scrobbling.message.connect(self._scrobble_message)
        self._scrobbling.finished.connect(self._scrobble_finished)
        self._sync_controller = SyncController(
            SyncExecutor(context.device_coordinator, scrobbler=scrobbler),
            context.library_workspace,
            context.device_controller,
            context.settings,
            self,
            recovery=context.device_coordinator.recover_sync_journal,
            keep_contents=context.device_coordinator.keep_sync_contents,
            cleanup=context.device_coordinator.cleanup_sync_journal,
        )
        context.host_media_controller.progressChanged.connect(
            self._media_scan_progress_changed
        )
        context.host_media_controller.externalReferencesFound.connect(
            self._review_external_playlist_files
        )
        context.host_media_controller.finished.connect(self._media_scan_finished)
        context.host_media_controller.failed.connect(self._media_scan_failed)
        context.host_media_controller.cancelled.connect(self._media_scan_cancelled)
        context.ipod_media_controller.progressChanged.connect(
            self._media_scan_progress_changed
        )
        context.ipod_media_controller.finished.connect(self._ipod_media_scan_finished)
        context.ipod_media_controller.failed.connect(self._ipod_media_scan_failed)
        context.ipod_media_controller.cancelled.connect(self._media_scan_cancelled)
        self._artwork_provider = ArtworkPixmapProvider(
            context.artwork_controller,
            self,
        )
        self._podcast_artwork_provider = PodcastArtworkPixmapProvider(
            context.podcast_artwork_controller,
            self,
        )
        self._photo_provider = PhotoPixmapProvider(context.photo_controller, self)

        shell = QWidget(self)
        shell.setObjectName("appShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self._shell_layout = shell_layout

        self._player = PlayerBar(
            context.theme_manager,
            self._artwork_provider,
            shell,
            workspace=context.library_workspace,
        )
        shell_layout.addWidget(self._player)

        body = QFrame(shell)
        body.setObjectName("appBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self._workspaces = QStackedWidget(body)
        self._workspaces.setObjectName("workspaceStack")
        self._library_browser = QWidget(self._workspaces)
        library_layout = QHBoxLayout(self._library_browser)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.setSpacing(0)

        self._sidebar = Sidebar(
            body,
            playlists=context.library_workspace,
        )
        self._normalization.changed.connect(self._normalization_changed)
        self._library_review = LibraryReviewDialog(
            context.library_write_controller, self
        )
        self._library_review.recordRequested.connect(self._review_record_requested)
        self._sidebar.reviewChangesRequested.connect(self._review_changes)
        self._sidebar.syncRequested.connect(self._open_sync_workspace)
        context.library_write_controller.changed.connect(
            self._review_availability_changed
        )
        context.library_write_controller.automaticSaveFailed.connect(
            self._show_library_review
        )
        context.library_write_controller.automaticSaveWarning.connect(
            self._show_library_review
        )
        self._pages = QStackedWidget(body)
        self._pages.setObjectName("pageStack")
        self._playback_pane = PlaybackPane(
            context.playback_controller,
            context.lyrics_controller,
            context.theme_manager,
            self._artwork_provider,
            body,
        )
        self._playback_pane_host = PlaybackPaneHost(self._playback_pane, body)
        self._library_page = LibraryPage(
            context.track_model,
            context.album_model,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            self._pages,
        )
        tracks_page = TrackPage(
            context.track_model,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            PageId.TRACKS,
            "tracks",
            None,
            self._pages,
        )
        artists_page = CollectionPage(
            context.track_model,
            context.artist_model,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            page_id=PageId.ARTISTS,
            table_id="artists-tracks",
            albums=context.album_model,
            parent=self._pages,
        )
        genres_page = CollectionPage(
            context.track_model,
            context.genre_model,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            page_id=PageId.GENRES,
            table_id="genres-tracks",
            albums=context.album_model,
            parent=self._pages,
        )
        audiobooks_page = TrackPage(
            context.track_model,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            PageId.AUDIOBOOKS,
            "audiobooks",
            (MediaKind.AUDIOBOOK,),
            self._pages,
        )
        movies_page = TrackPage(
            context.track_model,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            PageId.MOVIES,
            "movies",
            (MediaKind.MOVIE,),
            self._pages,
        )
        tv_shows_page = CollectionPage(
            context.track_model,
            context.tv_show_model,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            page_id=PageId.TV_SHOWS,
            table_id="tv-shows-tracks",
            parent=self._pages,
        )
        music_videos_page = CollectionPage(
            context.track_model,
            context.music_video_model,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            page_id=PageId.MUSIC_VIDEOS,
            table_id="music-videos-tracks",
            parent=self._pages,
        )
        videos_page = TrackPage(
            context.track_model,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            PageId.VIDEOS,
            "videos",
            (MediaKind.MOVIE, MediaKind.TV_SHOW, MediaKind.MUSIC_VIDEO),
            self._pages,
        )
        self._settings_page = SettingsPage(
            context.settings,
            context.theme_manager,
            context.i18n_manager,
            self._pages,
            scrobbling=self._scrobbling,
        )
        self._media_tools = MediaToolsController(self)
        self._media_tools_dialog = MediaToolsSetupDialog(self._media_tools, self)
        self._media_tools_prompt_pending = False
        self._media_tools.checked.connect(self._media_tools_checked)
        self._media_tools.changed.connect(self._media_tools_status_changed)
        self._settings_page.mediaToolsRequested.connect(self._open_media_tools)
        self._settings_page.mediaToolsCheckRequested.connect(self._media_tools.check)
        self._settings_page.appUpdatesRequested.connect(self._updates.check_now)
        self._updates.changed.connect(self._app_update_status_changed)
        self._app_update_status_changed()
        self._sidebar.scrobbleRequested.connect(self._scrobble_now)
        self._scrobbling.changed.connect(self._scrobbling_changed)
        self._sidebar.set_scrobble_available(self._scrobbling.can_scrobble)
        self._settings_page.set_active_ipod(context.device_controller.active_ipod)
        self._backup_page = BackupPage(
            context.backup_controller,
            context.device_controller,
            context.settings,
            context.theme_manager,
            self._pages,
        )
        self._playlist_page = PlaylistPage(
            context.library_workspace,
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            self._pages,
        )
        self._photo_page = PhotoPage(
            context.library_workspace,
            context.settings,
            context.theme_manager,
            self._photo_provider,
            self._pages,
        )
        self._track_actions = TrackActions(
            context.library_workspace,
            context.playback_controller,
            self,
            settings=context.settings,
            device_controller=context.device_controller,
            artwork_provider=self._artwork_provider,
        )
        self._podcast_page = PodcastPage(
            context.podcast_controller,
            context.status,
            context.theme_manager,
            self._podcast_artwork_provider,
            self._pages,
            device_artwork_provider=self._artwork_provider,
            track_actions=self._track_actions,
        )
        self._synesthesia_page = SynesthesiaPage(
            context.synesthesia_controller,
            context.playback_controller,
            self._pages,
        )
        self._synesthesia_page.failure.connect(self._synesthesia_render_failed)
        for key in (Qt.Key.Key_F, Qt.Key.Key_F11):
            shortcut = QShortcut(QKeySequence(key), self._synesthesia_page)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(self._toggle_synesthesia_fullscreen)
        exit_fullscreen = QShortcut(
            QKeySequence(Qt.Key.Key_Escape), self._synesthesia_page
        )
        exit_fullscreen.setAutoRepeat(False)
        exit_fullscreen.activated.connect(self._exit_synesthesia_fullscreen)
        self._page_widgets: dict[PageId, QWidget] = {
            PageId.ALBUMS: self._library_page,
            PageId.ARTISTS: artists_page,
            PageId.GENRES: genres_page,
            PageId.TRACKS: tracks_page,
            PageId.AUDIOBOOKS: audiobooks_page,
            PageId.MOVIES: movies_page,
            PageId.TV_SHOWS: tv_shows_page,
            PageId.MUSIC_VIDEOS: music_videos_page,
            PageId.VIDEOS: videos_page,
            PageId.BACKUPS: self._backup_page,
            PageId.SETTINGS: self._settings_page,
            PageId.PLAYLISTS: self._playlist_page,
            PageId.PODCASTS: self._podcast_page,
            PageId.PHOTOS: self._photo_page,
            PageId.SYNESTHESIA: self._synesthesia_page,
        }
        self._library_pages = (
            self._library_page,
            artists_page,
            genres_page,
            tracks_page,
            audiobooks_page,
            movies_page,
            tv_shows_page,
            music_videos_page,
            videos_page,
            self._playlist_page,
            self._podcast_page,
        )

        for page in self._library_pages:
            self._pages.addWidget(page)
        self._pages.addWidget(self._photo_page)
        self._pages.addWidget(self._backup_page)
        self._pages.addWidget(self._synesthesia_page)
        self._pages.addWidget(self._settings_page)

        library_layout.addWidget(self._sidebar)
        library_layout.addWidget(self._pages, stretch=1)
        self._workspaces.addWidget(self._library_browser)
        body_layout.addWidget(self._workspaces, stretch=1)
        body_layout.addWidget(self._playback_pane_host)
        shell_layout.addWidget(body, stretch=1)
        self._sync_workspace = SyncWorkspace(
            context.settings,
            context.theme_manager,
            self._artwork_provider,
            self._workspaces,
        )
        self._workspaces.addWidget(self._sync_workspace)
        self._host_drop = HostMediaDropTarget(self._pages, self._can_drop_host_media)
        self._host_drop.pathsDropped.connect(self._drop_host_media)
        self._pages.currentChanged.connect(self._host_drop.clear)
        self._workspaces.currentChanged.connect(self._host_drop.clear)
        self._pages.currentChanged.connect(self._exit_synesthesia_fullscreen)
        self._workspaces.currentChanged.connect(self._exit_synesthesia_fullscreen)
        self.setCentralWidget(shell)
        # Window chrome stays outside both stacks for every page and workspace.
        status_bar = QStatusBar(self)
        status_bar.setObjectName("appStatusBar")
        status_bar.setSizeGripEnabled(False)
        status_bar.setContentsMargins(LAYOUT.space_sm, 0, LAYOUT.space_sm, 0)
        self.setStatusBar(status_bar)
        self._sync_workspace.scanCancelRequested.connect(self._cancel_media_scans)
        self._sync_workspace.exitRequested.connect(self._exit_sync_workspace)
        self._sync_workspace.executeRequested.connect(self._execute_sync)
        self._sync_workspace.executionCancelRequested.connect(
            self._sync_controller.cancel
        )
        self._sync_controller.progressChanged.connect(self._sync_progress_changed)
        self._sync_controller.finished.connect(self._sync_finished)
        self._sync_workspace.execution.recoveryRequested.connect(self._recover_sync)
        self._sync_workspace.execution.keepContentsRequested.connect(
            self._keep_sync_contents
        )
        self._sync_controller.changed.connect(self._refresh_sync_availability)
        context.podcast_controller.changed.connect(self._refresh_sync_availability)
        context.podcast_controller.syncRequested.connect(self._execute_podcast_sync)
        self._sync_controller.podcastStateInvalidated.connect(
            context.podcast_controller.reload
        )
        self._sync_workspace.selection.changed.connect(self._refresh_playlist_preview)
        self._sync_workspace.playlistReconciliationChanged.connect(
            self._refresh_sync_availability
        )
        context.library_workspace.changed.connect(self._refresh_sync_availability)
        self._player_position: PlayerPosition | None = None
        self._apply_player_position(
            PlayerPosition(context.settings.get(PLAYER_POSITION))
        )

        from iOpenPod.GUI.widgets.track_table import TrackTable

        for table in self._library_browser.findChildren(TrackTable):
            table.set_library_workspace(context.library_workspace)
        self._track_actions.playlistCreated.connect(self._playlist_selected)
        self._track_actions.trackExportRequested.connect(self._track_export_requested)
        self._track_actions.chapteredConversionRequested.connect(
            self._chaptered_conversion_requested
        )
        self._player.trackContextMenuRequested.connect(self._track_actions.show_track)
        self._playback_pane.trackContextMenuRequested.connect(
            self._track_actions.show_track
        )
        for table in self._library_browser.findChildren(TrackTable):
            self._track_actions.install(table)
        for grid in (
            *self._library_browser.findChildren(AlbumGridView),
            *self._library_browser.findChildren(CollectionGridView),
        ):
            grid.set_library_workspace(context.library_workspace)
            self._track_actions.install(grid)
        for name in ("artistsCollectionList", "genresCollectionList"):
            collection_list = self._library_browser.findChild(QListView, name)
            if collection_list is not None:
                self._track_actions.install(collection_list)
        context.library_workspace.changed.connect(self.retranslate_ui)
        self._sidebar.pageRequested.connect(self._navigate_page)
        playlist_tree = self._sidebar.playlist_tree
        if playlist_tree is not None:
            playlist_tree.selected.connect(self._playlist_selected)
            playlist_tree.createRequested.connect(self._playlist_page.create_playlist)
            playlist_tree.editRequested.connect(self._playlist_page.edit_playlist)
            playlist_tree.removeRequested.connect(self._playlist_page.remove_playlist)
            self._playlist_page.playlistSelected.connect(
                self._playlist_selection_changed
            )
            self._playlist_page.playlistExportRequested.connect(
                self._playlist_export_requested
            )
        self._photo_page.photoExportRequested.connect(self._photo_export_requested)
        self._photo_page.photoAlbumExportRequested.connect(
            self._photo_album_export_requested
        )
        self._sidebar.chooseDeviceRequested.connect(self._open_device_picker)
        self._sidebar.ejectRequested.connect(self._eject_active_ipod)
        self._device_picker.refreshRequested.connect(
            context.device_controller.refresh_devices
        )
        self._device_picker.deviceSelected.connect(
            context.device_controller.select_device
        )
        context.device_controller.discoveryChanged.connect(
            self._device_discovery_changed
        )
        context.device_controller.activeIPodChanged.connect(self._active_ipod_changed)
        context.device_controller.busyChanged.connect(self._device_busy_changed)
        context.device_controller.searchingChanged.connect(
            self._device_picker.set_searching
        )
        context.device_controller.discoveryErrorChanged.connect(
            self._device_picker.set_search_error
        )
        context.device_controller.operationFailed.connect(self._device_operation_failed)
        context.device_controller.deviceWritesAllowedChanged.connect(
            self._sidebar.set_eject_available
        )
        context.device_controller.ejectStarted.connect(self._eject_started)
        context.device_controller.ejectCompleted.connect(self._eject_completed)
        context.artwork_controller.artworkFailed.connect(self._artwork_load_failed)
        context.photo_controller.photoFailed.connect(self._photo_load_failed)
        self._connect_playback()
        context.track_model.modelReset.connect(self._library_replaced)
        context.track_model.dataChanged.connect(self._library_changed)
        context.track_model.rowsInserted.connect(self._library_changed)
        context.track_model.rowsRemoved.connect(self._library_changed)
        context.i18n_manager.languageChanged.connect(self._language_changed)
        context.settings.settingChanged.connect(self._setting_changed)
        self._review_availability_changed()
        status_bar.addPermanentWidget(StatusBarControls(context.status, status_bar))
        status_bar.addPermanentWidget(StatusListButton(context.status, status_bar))
        context.status.messageChanged.connect(status_bar.showMessage)
        context.status.actionRequested.connect(self._status_action_requested)
        status_bar.showMessage(context.status.current_message)
        context.backup_controller.progressChanged.connect(self._backup_progress_changed)
        context.backup_controller.busyChanged.connect(self._backup_busy_changed)

        self.setMinimumSize(960, 620)
        geometry = context.settings.get(WINDOW_GEOMETRY)
        if geometry.isEmpty() or not self.restoreGeometry(geometry):
            self.resize(1360, 820)

        self._show_page(PageId.ALBUMS.value)
        self._sidebar.set_device_discovery(context.device_controller.discovery)
        self._sidebar.set_active_ipod(context.device_controller.active_ipod)
        self._monitor_normalization(context.device_controller.active_ipod)
        self._sidebar.set_eject_available(
            context.device_controller.device_writes_allowed
        )
        self.retranslate_ui()
        if self._sync_controller.needs_recovery or self._sync_controller.needs_cleanup:
            QTimer.singleShot(0, self._open_sync_workspace)
        if auto_discover:
            self._device_picker.visibilityChanged.connect(
                self._device_picker_visibility_changed
            )
            QTimer.singleShot(0, context.device_controller.restore_previous_device)

    def retranslate_ui(self) -> None:
        for status in self._context.status.active_messages:
            if status.source == _CHAPTERED_PROGRESS_STATUS_SOURCE:
                self._context.status.show(
                    status.source,
                    status.message,
                    progress=status.progress,
                    action=self._chaptered_cancel_action(),
                )
                break
        if self._workspaces.currentWidget() is self._sync_workspace:
            self.setWindowTitle(self.tr("Sync with Host — iOpenPod"))
            self._context.status.set_default(self._default_status_message())
            return
        active_ipod = self._context.device_controller.active_ipod
        if active_ipod is not None:
            self.setWindowTitle(
                self.tr("%1 — iOpenPod").replace(
                    "%1",
                    (
                        self._context.library_workspace.device_name
                        or active_ipod.display_name
                    ),
                )
            )
        else:
            self.setWindowTitle(self.tr("iOpenPod"))
        self._context.status.set_default(self._default_status_message())

    def _default_status_message(self) -> str:
        plan = self._sync_workspace.plan
        if (
            self._workspaces.currentWidget() is self._sync_workspace
            and self._sync_workspace.stage is SyncStage.REVIEW
            and plan is not None
        ):
            changes = planned_change_count_text(plan.change_count)
            if plan.attention_count:
                attention = (
                    self.tr("1 item needs attention")
                    if plan.attention_count == 1
                    else self.tr("%1 items need attention").replace(
                        "%1", f"{plan.attention_count:,}"
                    )
                )
                return (
                    self.tr("%1 · %2").replace("%1", changes).replace("%2", attention)
                )
            return changes
        if self._workspaces.currentWidget() is self._sync_workspace:
            if self._sync_workspace.stage is SyncStage.SYNC:
                return (
                    self.tr("Sync in progress — keep the iPod connected")
                    if self._sync_controller.busy
                    else self.tr("Sync result")
                )
            if self._sync_workspace.stage is SyncStage.SELECT:
                count = self._sync_workspace.selection.selected_host_count
                return self.tr("Host items selected for Sync: %n", None, count)
            if self._sync_workspace.stage is SyncStage.SCANNING:
                return self.tr("Scanning the Host Media Library…")
            return self.tr("Configure Sync with Host")
        count = self._context.track_model.track_count
        count_text = track_count_text(count)
        active_ipod = self._context.device_controller.active_ipod
        if active_ipod is not None:
            message = (
                self.tr("%1 · %2")
                .replace("%1", count_text)
                .replace("%2", active_ipod.profile.display_name)
            )
        elif (
            self._context.device_controller.busy
            and not self._context.device_controller.searching
        ):
            message = self.tr("Loading iPod…")
        else:
            candidate_count = len(self._context.device_controller.discovery.candidates)
            devices = device_count_text(candidate_count)
            message = self.tr("No Active iPod · %1").replace("%1", devices)
        return message

    def _backup_progress_changed(self, value: object) -> None:
        if not isinstance(value, BackupProgress):
            return
        if value.total_bytes > 0:
            progress = StatusProgress(
                value.completed_bytes, value.total_bytes, value.current_file
            )
        elif value.total <= 0:
            progress = StatusProgress(detail=value.current_file)
        else:
            progress = StatusProgress(value.current, value.total, value.current_file)
        self._context.status.show(
            _BACKUP_STATUS_SOURCE, workflow_text(value.message), progress=progress
        )

    def _backup_busy_changed(self, busy: bool) -> None:
        if busy:
            return
        self._context.status.clear(_BACKUP_STATUS_SOURCE)

    def _review_availability_changed(self) -> None:
        controller = self._context.library_write_controller
        self._sidebar.set_review_visible(controller.draft_all_changes)
        self._sidebar.set_review_available(
            controller.can_prepare or controller.review is not None
        )
        messages = {
            PreparationState.PREPARING: self.tr("Preparing Library changes…"),
            PreparationState.SAVING: self.tr(
                "Saving Library changes… Keep the iPod connected until verification finishes."
            ),
        }
        message = messages.get(controller.state)
        if message is not None:
            self._context.status.show(_LIBRARY_WRITE_STATUS_SOURCE, message)
        else:
            self._context.status.clear(_LIBRARY_WRITE_STATUS_SOURCE)

    def _show_library_review(self) -> None:
        self._library_review.show()
        self._library_review.raise_()

    def _review_changes(self) -> None:
        self._show_library_review()
        controller = self._context.library_write_controller
        if not controller.can_save:
            controller.prepare()

    def _review_record_requested(self, subject: str, record_id: object) -> None:
        mapping = self._context.library_workspace.saved_playlist_ids
        if subject == "playlist" and isinstance(record_id, int) and mapping is not None:
            record_id = mapping.get(record_id, record_id)
        if (
            subject == "playlist"
            and isinstance(record_id, int)
            and self._context.library_workspace.playlist(record_id) is not None
        ):
            self._playlist_selected(record_id)
        elif subject == "track" and isinstance(record_id, int):
            self._show_page(PageId.TRACKS.value)
            page = self._page_widgets[PageId.TRACKS]
            if isinstance(page, TrackPage):
                page.select_track(record_id)

    def _connect_playback(self) -> None:
        controller = self._context.playback_controller
        for page in self._library_pages:
            if isinstance(page, PodcastPage):
                page.trackActivated.connect(controller.enqueue)
            if isinstance(page, PlaylistPage):
                page.queueRequested.connect(self._queue_group_tracks)
                page.playNextRequested.connect(controller.play_next)
        controller.currentTrackChanged.connect(self._player.set_track)
        controller.playingChanged.connect(self._player.set_playing)
        controller.positionChanged.connect(self._player.update_position)
        controller.seeked.connect(self._player.set_position)
        controller.volumeChanged.connect(self._player.set_volume)
        controller.playbackFailed.connect(self._playback_failed)
        self._player.playPauseRequested.connect(controller.toggle_play_pause)
        self._player.previousRequested.connect(controller.previous)
        self._player.nextRequested.connect(controller.next)
        self._player.seekRequested.connect(controller.seek)
        self._player.volumeChanged.connect(controller.set_volume)
        self._player.tracksDropped.connect(controller.play_now)
        self._player.queueVisibilityRequested.connect(self._playback_pane_host.set_open)
        self._player.clearQueueRequested.connect(controller.clear_queue)
        controller.queue_model.rowsInserted.connect(self._refresh_player_queue_count)
        controller.queue_model.rowsRemoved.connect(self._refresh_player_queue_count)
        controller.queue_model.modelReset.connect(self._refresh_player_queue_count)
        self._refresh_player_queue_count()
        self._player.visualizerRequested.connect(self._open_synesthesia)
        self._player.trackRatingRequested.connect(self._set_player_track_rating)
        self._playback_pane.visibilityChanged.connect(self._player.set_queue_visible)
        synesthesia = self._context.synesthesia_controller
        synesthesia.progressChanged.connect(self._synesthesia_progress_changed)
        synesthesia.analysisChanged.connect(self._synesthesia_analysis_changed)
        synesthesia.busyChanged.connect(self._synesthesia_busy_changed)
        synesthesia.cancelled.connect(self._synesthesia_cancelled)
        synesthesia.failed.connect(self._synesthesia_failed)
        self._player.set_track(controller.current_track)
        self._player.set_playing(controller.playing)
        self._player.set_position(controller.position_ms)
        self._player.set_volume(controller.volume_percent)

    def _refresh_player_queue_count(self) -> None:
        self._player.set_queue_count(
            self._context.playback_controller.queue_model.rowCount()
        )

    def _queue_group_tracks(self, tracks: tuple[Track, ...]) -> None:
        controller = self._context.playback_controller
        controller.insert_tracks(tracks, controller.queue_model.rowCount())

    def _set_player_track_rating(self, track_id: int, rating: int) -> None:
        workspace = self._context.library_workspace
        current = self._context.playback_controller.current_track
        if (
            current is None
            or current.track_id != track_id
            or workspace.track(track_id) != current
        ):
            return
        try:
            workspace.apply_track_edits(
                (TrackUpdate(track_id, (TrackFieldEdit("rating", rating),)),),
                workspace.edit_revision,
            )
        except ValueError as error:
            QMessageBox.warning(
                self, self.tr("Library action unavailable"), workflow_text(str(error))
            )

    def _open_synesthesia(self) -> None:
        if self._context.playback_controller.current_track is None:
            return
        self._show_page(PageId.SYNESTHESIA.value)
        self._playlist_page.select_playlist(None)
        self._synesthesia_page.activate_current()

    def _synesthesia_progress_changed(self, value: object) -> None:
        if isinstance(value, AnalysisProgress):
            self._context.status.show(
                _SYNESTHESIA_PROGRESS_STATUS_SOURCE,
                workflow_text(value.detail),
            )

    def _toggle_synesthesia_fullscreen(self) -> None:
        if self._synesthesia_window_state is not None:
            self._exit_synesthesia_fullscreen()
            return
        if not self._synesthesia_page.isVisible():
            return
        chrome = (
            self._player,
            self._sidebar,
            self._playback_pane_host,
            self.statusBar(),
        )
        self._synesthesia_window_state = _SynesthesiaWindowState(
            self.saveGeometry(),
            self.minimumSize(),
            tuple(widget for widget in chrome if not widget.isHidden()),
        )
        for widget in chrome:
            widget.hide()
        # The normal shell's minimum size must not constrain smaller displays.
        self.setMinimumSize(0, 0)
        self.showFullScreen()

    def _exit_synesthesia_fullscreen(self) -> None:
        state = self._synesthesia_window_state
        if state is None:
            return
        self._synesthesia_window_state = None
        # Clear fullscreen explicitly before restoring a maximized window on Windows.
        self.showNormal()
        self.setMinimumSize(state.minimum_size)
        self.restoreGeometry(state.geometry)
        for widget in state.visible_chrome:
            widget.show()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and not self.isFullScreen():
            self._exit_synesthesia_fullscreen()

    def _synesthesia_analysis_changed(self, value: object) -> None:
        if not isinstance(value, TrackAnalysis):
            self._context.status.clear(_SYNESTHESIA_NOTICE_STATUS_SOURCE)
            return
        self._context.status.clear(_SYNESTHESIA_PROGRESS_STATUS_SOURCE)
        self._context.status.show(
            _SYNESTHESIA_NOTICE_STATUS_SOURCE,
            self.tr("Visualizer synchronized with the current Track."),
            timeout_ms=4_000,
        )

    def _synesthesia_busy_changed(self, busy: bool) -> None:
        if busy:
            self._context.status.show(
                _SYNESTHESIA_PROGRESS_STATUS_SOURCE,
                self.tr("Analyzing the current Track for the visualizer…"),
            )
            return
        self._context.status.clear(_SYNESTHESIA_PROGRESS_STATUS_SOURCE)

    def _synesthesia_cancelled(self) -> None:
        self._context.status.clear(_SYNESTHESIA_PROGRESS_STATUS_SOURCE)

    def _synesthesia_failed(self, detail: str) -> None:
        self._context.status.clear(_SYNESTHESIA_PROGRESS_STATUS_SOURCE)
        self._context.status.show(
            _SYNESTHESIA_NOTICE_STATUS_SOURCE,
            self.tr("Visualizer analysis failed: %1").replace("%1", detail),
            timeout_ms=8_000,
        )

    def _synesthesia_render_failed(self, detail: str) -> None:
        self._context.status.show(
            _SYNESTHESIA_NOTICE_STATUS_SOURCE,
            self.tr("The visualizer graphics could not start: %1").replace(
                "%1", detail
            ),
            timeout_ms=8_000,
        )

    def check_app_updates(self) -> None:
        self._updates.start()

    def _app_update_status_changed(self) -> None:
        self._settings_page.set_app_update_status(
            self._updates.channel,
            busy=self._updates.busy,
            message=self._updates.message,
        )

    def close_app_updates(self) -> None:
        self._updates.close()

    def _prepare_app_update(self) -> str:
        context = self._context
        if context.library_workspace.dirty:
            return self.tr(
                "Save or discard the Library Draft before updating iOpenPod."
            )
        if QApplication.activeModalWidget() is not None or any(
            dialog.isVisible() for dialog in self.findChildren(QDialog)
        ):
            return self.tr("Close the open dialog before updating iOpenPod.")
        if (
            context.library_workspace.locked
            or context.device_controller.busy
            or context.backup_controller.busy
            or context.host_media_controller.busy
            or context.ipod_media_controller.busy
            or context.podcast_controller.busy
            or context.library_write_controller.state
            in (PreparationState.PREPARING, PreparationState.SAVING)
            or self._sync_controller.busy
            or self._sync_controller.needs_recovery
            or self._sync_controller.needs_cleanup
            or self._export_controller.busy
            or self._chaptered_controller.busy
            or self._media_tools.busy
            or self._scrobbling.busy
            or self._workspaces.currentWidget() is self._sync_workspace
        ):
            return self.tr(
                "Finish the current work and close Sync before updating iOpenPod."
            )
        if not context.device_controller.begin_recovery_operation():
            return self.tr(
                "Wait for the current iPod operation before updating iOpenPod."
            )
        self._update_reserved = True
        try:
            context.settings.set_global(WINDOW_GEOMETRY, self.saveGeometry())
            context.settings.sync()
            context.playback_controller.pause()
            context.library_workspace.set_locked(True)
            central = self.centralWidget()
            if central is not None:
                central.setEnabled(False)
        except Exception:
            self._finish_app_update()
            raise
        return ""

    def _finish_app_update(self) -> None:
        if self._update_reserved:
            self._update_reserved = False
            self._context.library_workspace.set_locked(False)
            self._context.device_controller.finish_exclusive_operation()
            central = self.centralWidget()
            if central is not None:
                central.setEnabled(True)

    def check_media_tools(self) -> None:
        """Make one startup check after the application window is shown."""
        self._media_tools_prompt_pending = True
        self._media_tools.check()

    def _media_tools_checked(self, value: object) -> None:
        if not self._media_tools_prompt_pending:
            return
        self._media_tools_prompt_pending = False
        if isinstance(value, MediaToolSetup) and not value.ready:
            self._media_tools_dialog.open()

    def _media_tools_status_changed(self) -> None:
        self._settings_page.set_media_tools_status(
            self._media_tools.setup,
            checking=self._media_tools.checking,
            busy=self._media_tools.busy,
            message=self._media_tools.message,
        )

    def _open_media_tools(self) -> None:
        self._media_tools_prompt_pending = False
        self._media_tools_dialog.open()
        self._media_tools.check()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._updates.installing:
            event.ignore()
            return
        if self._media_tools.installing:
            self._media_tools.stop_after_current()
            self._media_tools_dialog.open()
            event.ignore()
            return
        self.close_app_updates()
        self._host_drop.shutdown()
        self._media_tools.shutdown()
        self._scrobbling.shutdown()
        self._exit_synesthesia_fullscreen()
        self._sync_controller.shutdown()
        self._normalization.shutdown()
        self._export_controller.shutdown()
        self._chaptered_controller.shutdown()
        self._artwork_provider.shutdown()
        self._photo_provider.shutdown()
        self._sync_workspace.shutdown()
        self._podcast_artwork_provider.shutdown()
        self._context.settings.set_global(WINDOW_GEOMETRY, self.saveGeometry())
        self._context.settings.sync()
        super().closeEvent(event)

    def _playlist_export_requested(self, name: str, value: object) -> None:
        tracks = _tracks_from_signal(value)
        if tracks is None:
            return
        if not self._export_controller.can_start:
            self._show_export_unavailable()
            return
        dialog = PlaylistExportDialog(len(tracks), self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            directory = self._choose_export_directory(
                self.tr("Choose Playlist Export Folder")
            )
            if directory is None:
                return
            if self._export_controller.start_playlist(
                name,
                tracks,
                directory,
                dialog.selected_file_type,
                dialog.mode,
            ):
                self._show_export_progress(self.tr("Preparing Playlist export…"))
        finally:
            dialog.deleteLater()

    def _track_export_requested(self, value: object) -> None:
        tracks = _tracks_from_signal(value)
        if not tracks:
            return
        if not self._export_controller.can_start:
            self._show_export_unavailable()
            return
        directory = self._choose_export_directory(self.tr("Choose Track Export Folder"))
        if directory is None:
            return
        if self._export_controller.start_tracks(tracks, directory):
            self._show_export_progress(self.tr("Preparing Track export…"))

    def _chaptered_conversion_requested(self, value: object) -> None:
        tracks = _tracks_from_signal(value)
        if not tracks:
            return
        try:
            started = self._chaptered_controller.start(tracks)
        except ValueError as error:
            self._chaptered_failed(str(error))
            return
        if not started:
            self._chaptered_failed(
                self.tr("Album conversion is unavailable right now.")
            )
            return
        self._context.status.clear(_CHAPTERED_NOTICE_STATUS_SOURCE)
        self._context.status.show(
            _CHAPTERED_PROGRESS_STATUS_SOURCE,
            self.tr("Preparing chaptered Album…"),
            progress=StatusProgress(),
            action=self._chaptered_cancel_action(),
        )

    def _chaptered_progress_changed(self, message: str) -> None:
        self._context.status.show(
            _CHAPTERED_PROGRESS_STATUS_SOURCE,
            workflow_text(message),
            progress=StatusProgress(),
            action=self._chaptered_cancel_action(),
        )

    def _chaptered_availability_changed(self) -> None:
        if not self._chaptered_controller.busy:
            self._stop_chaptered_status()

    def _stop_chaptered_status(self) -> None:
        self._context.status.clear(_CHAPTERED_PROGRESS_STATUS_SOURCE)

    @staticmethod
    def _chaptered_cancel_action() -> StatusAction:
        return StatusAction(
            "cancel", QCoreApplication.translate("CommonActions", "Cancel")
        )

    def _status_action_requested(self, source: str, key: str) -> None:
        if source == "scrobbling" and key == "cancel":
            self._scrobbling.cancel()
        if source == "scrobbling" and key == "details":
            result = self._scrobbling.last_result
            if result is not None:
                show_scrobble_report(result, self)
        if source == _CHAPTERED_PROGRESS_STATUS_SOURCE and key == "cancel":
            self._cancel_chaptered_conversion()

    def _cancel_chaptered_conversion(self) -> None:
        self._chaptered_controller.cancel()
        self._context.status.show(
            _CHAPTERED_NOTICE_STATUS_SOURCE,
            self.tr("Album conversion cancelled."),
            timeout_ms=8_000,
        )

    def _chaptered_finished(self) -> None:
        self._stop_chaptered_status()
        self._context.status.show(
            _CHAPTERED_NOTICE_STATUS_SOURCE,
            self.tr("Chaptered Album prepared for Library save."),
            timeout_ms=8_000,
        )

    def _chaptered_failed(self, detail: str) -> None:
        if not self._chaptered_controller.busy:
            self._stop_chaptered_status()
        title = self.tr("Album conversion failed")
        self._context.status.show(
            _CHAPTERED_NOTICE_STATUS_SOURCE,
            f"{title}: {workflow_text(detail)}",
            timeout_ms=15_000,
        )

    def _photo_export_requested(self, value: object) -> None:
        photos = _photos_from_signal(value)
        if not photos:
            return
        if not self._export_controller.can_start:
            self._show_export_unavailable()
            return
        directory = self._choose_export_directory(self.tr("Choose Photo Export Folder"))
        if directory is None:
            return
        if self._export_controller.start_photos(photos, directory):
            self._show_export_progress(self.tr("Preparing Photo export…"))

    def _photo_album_export_requested(self, name: str, value: object) -> None:
        photos = _photos_from_signal(value)
        if not photos:
            return
        if not self._export_controller.can_start:
            self._show_export_unavailable()
            return
        directory = self._choose_export_directory(
            self.tr("Choose Photo Album Export Location")
        )
        if directory is None:
            return
        if self._export_controller.start_photo_album(name, photos, directory):
            self._show_export_progress(self.tr("Preparing Photo Album export…"))

    def _choose_export_directory(self, caption: str) -> HostPath | None:
        selected = QFileDialog.getExistingDirectory(self, caption, "")
        return HostPath(Path(selected)) if selected else None

    def _show_export_progress(self, label: str) -> None:
        progress = QProgressDialog(
            label, QCoreApplication.translate("CommonActions", "Cancel"), 0, 0, self
        )
        progress.setObjectName("libraryExportProgress")
        progress.setWindowTitle(self.tr("Exporting"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self._export_controller.cancel)
        self._export_progress = progress
        progress.show()

    def _export_progress_changed(self, value: object) -> None:
        if not isinstance(value, ExportProgress) or self._export_progress is None:
            return
        self._export_progress.setLabelText(workflow_text(value.message))
        self._export_progress.setRange(0, max(1, value.total))
        self._export_progress.setValue(min(value.completed, value.total))

    def _export_finished(self, value: object) -> None:
        self._close_export_progress()
        if isinstance(value, PhotoExportResult):
            detail = english_count_fallback(
                "Exported %n Photo(s) into individual folders.",
                self.tr(
                    "Exported %n Photo(s) into individual folders.",
                    None,
                    len(value.photo_directories),
                ),
                len(value.photo_directories),
            )
            detail += "\n" + english_count_fallback(
                "Wrote %n image file(s).",
                self.tr("Wrote %n image file(s).", None, len(value.photo_files)),
                len(value.photo_files),
            )
            if value.album_directory is not None:
                detail += "\n" + self.tr("Created %1").replace(
                    "%1", value.album_directory.path.name
                )
        elif isinstance(value, ExportResult) and value.playlist_file is not None:
            detail = self.tr("Created %1").replace("%1", value.playlist_file.path.name)
            if value.track_files:
                detail += "\n" + english_count_fallback(
                    "Exported %n Track file(s) beside it.",
                    self.tr(
                        "Exported %n Track file(s) beside it.",
                        None,
                        len(value.track_files),
                    ),
                    len(value.track_files),
                )
        elif isinstance(value, ExportResult):
            detail = english_count_fallback(
                "Exported %n Track file(s).",
                self.tr("Exported %n Track file(s).", None, len(value.track_files)),
                len(value.track_files),
            )
        else:
            return
        QMessageBox.information(
            self,
            self.tr("Export Complete"),
            detail,
        )

    def _export_failed(self, detail: object) -> None:
        if not isinstance(detail, str):
            return
        self._close_export_progress()
        QMessageBox.warning(
            self,
            self.tr("Export Failed"),
            self.tr("The export could not be completed.")
            + "\n\n"
            + workflow_text(detail)
            + "\n\n"
            + self.tr(
                "Any completed copies were left in the selected folder. Existing "
                "files were not replaced."
            ),
        )

    def _export_cancelled(self) -> None:
        self._close_export_progress()
        QMessageBox.information(
            self,
            self.tr("Export Cancelled"),
            self.tr(
                "Export stopped. Any completed copies were left in the "
                "selected folder. Existing files were not replaced."
            ),
        )

    def _close_export_progress(self) -> None:
        progress, self._export_progress = self._export_progress, None
        if progress is not None:
            progress.close()
            progress.deleteLater()

    def _show_export_unavailable(self) -> None:
        QMessageBox.information(
            self,
            self.tr("Export Unavailable"),
            self.tr("Select an Active iPod and wait for the current export to finish."),
        )

    def _scrobble_now(self) -> None:
        if not configured_accounts(self._context.settings):
            self._show_page(PageId.SETTINGS.value)
            self._settings_page.show_sync_settings()
        self._scrobbling.scrobble_now()

    def _scrobbling_changed(self) -> None:
        self._sidebar.set_scrobble_available(self._scrobbling.can_scrobble)

    def _scrobble_message(self, message: str) -> None:
        running = self._scrobbling.submitting
        self._context.status.show(
            "scrobbling",
            message,
            progress=StatusProgress() if running else None,
            action=StatusAction(
                "cancel", QCoreApplication.translate("CommonActions", "Cancel")
            )
            if running
            else None,
            timeout_ms=0 if running else 20_000,
        )

    def _scrobble_finished(self, result: ScrobbleResult) -> None:
        message = result.summary
        if result.cancelled:
            message = (
                QCoreApplication.translate(
                    "ScrobbleController",
                    "Scrobbling cancelled. Pending listens are saved.",
                )
                + " "
                + message
            )
        self._context.status.show(
            "scrobbling",
            message,
            action=StatusAction("details", self.tr("Details")),
            timeout_ms=0 if result.issues else 20_000,
        )

    def _navigate_page(self, page_value: str) -> None:
        if page_value == PageId.NORMALIZE_TAGS.value:
            active = self._context.device_controller.active_ipod
            if active is not None:
                profile = active.profile
                self._normalizer_dialog.start(
                    tag_profile(
                        profile.family,
                        profile.generation,
                        uses_sqlite=profile.capabilities.database.uses_sqlite_database,
                    )
                )
            return
        if page_value == PageId.PLAYLISTS.value:
            return
        self._show_page(page_value)
        self._playlist_page.select_playlist(None)

    def _normalizer_closed(self, _result: int) -> None:
        self._sidebar.set_current_page(self._current_page_id())

    def _normalization_changed(self) -> None:
        self._sidebar.set_normalization_count(self._normalization.pending_count)

    def _monitor_normalization(self, active: ActiveIPod | None) -> None:
        self._normalization.monitor(
            tag_profile(
                active.profile.family,
                active.profile.generation,
                uses_sqlite=active.profile.capabilities.database.uses_sqlite_database,
            )
            if active is not None
            else None
        )
        self._normalization_changed()

    def _show_page(self, page_value: str) -> None:
        page_id = PageId(page_value)
        if (
            page_id is not PageId.SYNESTHESIA
            and self._pages.currentWidget() is self._synesthesia_page
        ):
            self._synesthesia_page.deactivate()
        self._pages.setCurrentWidget(self._page_widgets[page_id])
        self._sidebar.set_current_page(page_id)

    def _current_page_id(self) -> PageId:
        current = self._pages.currentWidget()
        return next(
            (
                page_id
                for page_id, widget in self._page_widgets.items()
                if widget is current
            ),
            PageId.ALBUMS,
        )

    def _playlist_selected(self, playlist_id: object) -> None:
        page = self._playlist_page
        if playlist_id != page.selected_playlist_id:
            page.select_playlist(playlist_id)

    def _playlist_selection_changed(self, playlist_id: object) -> None:
        tree = self._sidebar.playlist_tree
        if isinstance(playlist_id, int):
            self._show_page(PageId.PLAYLISTS.value)
            if tree is not None:
                tree.select_playlist(playlist_id)
        else:
            if tree is not None:
                tree.clear_selection()
            if self._pages.currentWidget() is self._playlist_page:
                self._show_page(PageId.ALBUMS.value)

    def _language_changed(self, _language_tag: str) -> None:
        self.retranslate_ui()
        self._sidebar.retranslate_ui()
        for page in self._library_pages:
            page.retranslate_ui()
        self._photo_page.retranslate_ui()
        self._sync_workspace.retranslate_ui()

    def _setting_changed(self, key: str, value: object) -> None:
        if key != PLAYER_POSITION.key or not isinstance(value, str):
            return
        self._apply_player_position(PlayerPosition(value))

    def _apply_player_position(self, position: PlayerPosition) -> None:
        if position is self._player_position:
            return
        self._shell_layout.removeWidget(self._player)
        target_index = (
            0 if position is PlayerPosition.TOP else self._shell_layout.count()
        )
        self._shell_layout.insertWidget(target_index, self._player)
        self._player.setProperty("playerPosition", position.value)
        style = self._player.style()
        style.unpolish(self._player)
        style.polish(self._player)
        self._player.update()
        self._player_position = position

    def _library_changed(self, *_args: object) -> None:
        self._context.playback_controller.reconcile_library(
            self._context.track_model.tracks
        )
        self.retranslate_ui()

    def _library_replaced(self) -> None:
        self._context.playback_controller.clear_session()
        self.retranslate_ui()

    def _open_device_picker(self) -> None:
        controller = self._context.device_controller
        self._device_picker.set_discovery(controller.discovery)
        self._device_picker.set_searching(controller.searching)
        self._device_picker.set_search_error(controller.discovery_error)
        self._device_picker.set_busy(controller.busy)
        self._device_picker.show()
        self._device_picker.raise_()
        self._device_picker.activateWindow()

    def _device_picker_visibility_changed(self, visible: bool) -> None:
        controller = self._context.device_controller
        if visible:
            controller.start_auto_refresh()
        else:
            controller.stop_auto_refresh()

    def _open_sync_workspace(self) -> None:
        if self._sync_controller.busy:
            return
        if (
            self._sync_controller.needs_recovery or self._sync_controller.needs_cleanup
        ) and self._sync_controller.result is not None:
            self._workspaces.setCurrentWidget(self._sync_workspace)
            self._sync_workspace.show_execution()
            self._sync_workspace.execution.show_result(self._sync_controller.result)
            return
        dialog = MediaFoldersDialog(self._context.settings, self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            folders = dialog.folders
        finally:
            dialog.deleteLater()
        self._start_host_sync(folders)

    def _can_drop_host_media(self) -> bool:
        return (
            self._workspaces.currentWidget() is self._library_browser
            and self._current_page_id()
            not in (
                PageId.SETTINGS,
                PageId.BACKUPS,
                PageId.SYNESTHESIA,
                PageId.PODCASTS,
            )
            and self._context.device_controller.active_ipod is not None
            and not self._context.device_controller.busy
            and not self._context.backup_controller.busy
            and not self._context.library_workspace.locked
            and not self._context.host_media_controller.busy
            and not self._context.ipod_media_controller.busy
            and not self._sync_controller.busy
            and not self._sync_controller.needs_recovery
            and not self._sync_controller.needs_cleanup
            and QApplication.activeModalWidget() is None
        )

    def _drop_host_media(self, value: object) -> None:
        if not self._can_drop_host_media() or not isinstance(value, tuple):
            return
        items = cast("tuple[object, ...]", value)
        paths = tuple(item for item in items if isinstance(item, Path))
        if not paths or len(paths) != len(items):
            return
        folders: list[HostMediaFolder] = []
        files: list[HostPath] = []
        active = self._context.device_controller.active_ipod
        for path in paths:
            if path.is_dir():
                dialog = MediaFolderSettingsDialog(
                    HostMediaFolder(HostPath(path)), self
                )
                try:
                    if dialog.exec() != QDialog.DialogCode.Accepted:
                        return
                    folders.append(dialog.folder)
                finally:
                    dialog.deleteLater()
            else:
                files.append(HostPath(path))
        if (
            self._can_drop_host_media()
            and self._context.device_controller.active_ipod is active
        ):
            self._start_host_sync(tuple(folders), files=tuple(files))

    def _start_host_sync(
        self, folders: tuple[HostMediaFolder, ...], *, files: tuple[HostPath, ...] = ()
    ) -> None:
        controller = self._context.host_media_controller
        started = (
            controller.start(folders, files=files)
            if files
            else controller.start(folders)
        )
        if not started:
            return
        available = frozenset(
            page_id
            for page_id in self._sync_workspace.library_page_ids
            if page_id is PageId.PLAYLISTS or self._sidebar.page_available(page_id)
        )
        self._sync_workspace.set_available_pages(available)
        self._workspaces.setCurrentWidget(self._sync_workspace)
        self._show_media_scan_progress(
            source_text("Finding selected media…")
            if files
            else source_text("Finding media in the selected folders…")
        )
        self.retranslate_ui()

    def _exit_sync_workspace(self) -> None:
        if self._workspaces.currentWidget() is not self._sync_workspace:
            return
        if self._sync_controller.busy:
            return
        cancel_scans = self._sync_workspace.stage is SyncStage.SCANNING
        self._sync_workspace.stop_scan()
        self._pending_host_media_library = None
        self._review_host = None
        self._review_ipod = None
        self._review_active = None
        self._refresh_sync_availability()
        self._workspaces.setCurrentWidget(self._library_browser)
        self.retranslate_ui()
        if cancel_scans:
            self._cancel_media_scans()

    def _show_media_scan_progress(self, label: str) -> None:
        self._sync_workspace.show_scan(label)

    def _media_scan_progress_changed(self, value: object) -> None:
        if not isinstance(value, (HostMediaScanProgress, IPodMediaScanProgress)):
            return
        if self._sync_workspace.stage is not SyncStage.SCANNING:
            self._show_media_scan_progress(value.message)
        path = ""
        if value.path is not None:
            path = (
                value.path.path.name
                if isinstance(value, HostMediaScanProgress)
                else value.path.name
            )
        self._sync_workspace.update_scan(
            value.message,
            path=path,
            completed=value.completed,
            total=value.total,
            phase=f"{type(value).__name__}:{value.stage.value}",
        )

    def _review_external_playlist_files(self, value: object) -> None:
        references = _playlist_external_references(value)
        if references is None:
            return
        self._sync_workspace.stop_scan()
        dialog = ExternalPlaylistFilesDialog(references, self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self._context.host_media_controller.cancel()
                return
            if self._context.host_media_controller.resolve_external(
                dialog.accepted_paths
            ):
                self._show_media_scan_progress(
                    source_text("Reading accepted playlist files…")
                )
        finally:
            dialog.deleteLater()

    def _media_scan_finished(self, value: object) -> None:
        if not isinstance(value, HostMediaLibrary):
            return
        if self._context.device_controller.active_ipod is not None:
            self._pending_host_media_library = value
            if self._context.ipod_media_controller.start():
                self._show_media_scan_progress(
                    source_text("Comparing the iPod media with its Sync helper…")
                )
                return
            self._pending_host_media_library = None
        self._finish_media_scan(value, None)

    def _ipod_media_scan_finished(self, value: object) -> None:
        host, self._pending_host_media_library = (
            self._pending_host_media_library,
            None,
        )
        if host is None or not isinstance(value, IPodMediaLibrary):
            return
        self._finish_media_scan(host, value)

    def _finish_media_scan(
        self,
        value: HostMediaLibrary,
        ipod: IPodMediaLibrary | None,
    ) -> None:
        if ipod is not None:
            active_ipod = self._context.device_controller.active_ipod
            if active_ipod is not None:
                plan = prepare_sync_plan(value, ipod, active_ipod.library)
                self._sync_workspace.load_comparison(value, plan, active_ipod, ipod)
                self._review_host = value
                self._review_ipod = ipod
                self._review_active = active_ipod
                self._refresh_playlist_preview()
                self._refresh_sync_availability()
                self.retranslate_ui()
                return
        self._exit_sync_workspace()
        QMessageBox.information(
            self,
            self.tr("Sync Comparison Unavailable"),
            self.tr("Select an Active iPod before building a Sync selection."),
        )

    def _ipod_media_scan_failed(self, detail: str) -> None:
        self._pending_host_media_library = None
        self._exit_sync_workspace()
        QMessageBox.warning(
            self,
            self.tr("iPod Media Scan Failed"),
            self.tr("The iPod files could not be scanned for Sync.") + "\n\n" + detail,
        )

    def _media_scan_failed(self, detail: str) -> None:
        self._pending_host_media_library = None
        self._exit_sync_workspace()
        QMessageBox.warning(
            self,
            self.tr("Host Media Scan Failed"),
            self.tr("The Host Media Library could not be scanned.") + "\n\n" + detail,
        )

    def _media_scan_cancelled(self) -> None:
        self._pending_host_media_library = None
        self._exit_sync_workspace()

    def _cancel_media_scans(self) -> None:
        self._context.host_media_controller.cancel()
        self._context.ipod_media_controller.cancel()

    def _refresh_playlist_preview(self) -> None:
        host, ipod, active = self._review_host, self._review_ipod, self._review_active
        changes = (
            preview_playlist_sync(
                self._sync_workspace.selection.selected_plan, host, ipod, active
            )
            if host is not None and ipod is not None and active is not None
            else ()
        )
        self._sync_workspace.set_playlist_preview(changes)

    def _refresh_sync_availability(self) -> None:
        podcasts = self._context.podcast_controller
        self._sync_workspace.set_podcast_count(
            len(podcasts.snapshot.subscriptions) if podcasts.snapshot.writable else 0
        )
        self._sync_workspace.set_execution_available(
            not self._sync_controller.busy
            and self._review_host is not None
            and self._review_ipod is not None
            and self._review_active is self._context.device_controller.active_ipod
            and self._context.device_controller.device_writes_allowed
            and not self._context.library_workspace.dirty
            and not self._context.library_workspace.locked
            and not podcasts.busy
        )

    def _execute_sync(self) -> None:
        host, ipod, active = self._review_host, self._review_ipod, self._review_active
        if host is None or ipod is None or active is None:
            return
        if not self._sync_controller.start(
            self._sync_workspace.selection.selected_plan,
            host,
            ipod,
            active,
            reconcile_playlists=self._sync_workspace.reconcile_playlists,
            podcasts=(
                self._context.podcast_controller.sync_request()
                if self._context.podcast_controller.snapshot.writable
                and self._context.podcast_controller.snapshot.subscriptions
                else None
            ),
        ):
            QMessageBox.warning(
                self, self.tr("Sync Unavailable"), self._sync_controller.last_error
            )
            return
        self._sync_workspace.show_execution()
        self.retranslate_ui()

    def _execute_podcast_sync(self, value: object) -> None:
        active = self._context.device_controller.active_ipod
        if not isinstance(value, PodcastSyncRequest) or active is None:
            return
        if not self._sync_controller.start_podcasts(value, active):
            QMessageBox.warning(
                self, self.tr("Sync Unavailable"), self._sync_controller.last_error
            )
            return
        self._review_host = None
        self._review_ipod = None
        self._review_active = None
        self._workspaces.setCurrentWidget(self._sync_workspace)
        self._sync_workspace.show_execution(podcasts=True)
        self.retranslate_ui()

    def _sync_progress_changed(self, value: object) -> None:
        if isinstance(value, WriteProgress):
            self._sync_workspace.execution.update_progress(value)

    def _sync_finished(self, value: object) -> None:
        if not isinstance(value, SyncExecutionResult):
            return
        self._review_host = None
        self._review_ipod = None
        self._review_active = None
        self._refresh_sync_availability()
        if (
            value.status is SyncExecutionStatus.RECOVERY_REQUIRED
            and self._sync_workspace.stage is not SyncStage.SYNC
        ):
            self._device_picker.close()
            self._workspaces.setCurrentWidget(self._sync_workspace)
            self._sync_workspace.show_execution()
        self._sync_workspace.execution.show_result(value)
        self.retranslate_ui()

    def _recover_sync(self) -> None:
        cleanup = self._sync_controller.needs_cleanup
        if (
            self._sync_controller.cleanup()
            if cleanup
            else self._sync_controller.recover()
        ):
            self._sync_workspace.execution.begin_recovery(cleanup=cleanup)
        else:
            QMessageBox.warning(
                self, self.tr("Recovery Unavailable"), self._sync_controller.last_error
            )

    def _keep_sync_contents(self) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("Keep Current iPod Contents?"),
            self.tr(
                "Keep the iPod's media and databases exactly as they are and stop offering "
                "this recovery? An interrupted Sync may have left missing files or incomplete "
                "Library changes. Recovery copies will remain on the iPod for manual recovery, "
                "but automatic restoration of this transaction will no longer be offered."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._sync_controller.keep_current_contents():
            self._sync_workspace.execution.begin_keep_contents()
        else:
            QMessageBox.warning(
                self, self.tr("Recovery Unavailable"), self._sync_controller.last_error
            )

    def _eject_active_ipod(self) -> None:
        controller = self._context.device_controller
        active = controller.active_ipod
        if active is None:
            return
        if self._context.library_workspace.dirty:
            answer = QMessageBox.question(
                self,
                self.tr("Eject Without Saving Changes?"),
                self.tr("Eject the iPod without saving changes?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if not controller.eject_active_ipod():
            QMessageBox.information(
                self,
                self.tr("Eject Unavailable"),
                self.tr(
                    "Wait for the current iPod operation to finish, then try again."
                ),
            )

    def _eject_started(self) -> None:
        self._context.status.show(
            _EJECT_STATUS_SOURCE,
            self.tr("Safely ejecting the Active iPod…"),
        )

    def _eject_completed(self, value: object) -> None:
        if not isinstance(value, DeviceEjectCompletion):
            return
        self._context.status.clear(_EJECT_STATUS_SOURCE)
        QMessageBox.information(
            self,
            self.tr("iPod Ejected"),
            self.tr("%1 is safe to disconnect.").replace("%1", value.display_name)
            + "\n\n"
            + workflow_text(value.detail),
        )

    def _device_discovery_changed(self, value: object) -> None:
        if not isinstance(value, DeviceDiscovery):
            return
        self._sidebar.set_device_discovery(value)
        self._device_picker.set_discovery(value)
        self.retranslate_ui()

    def _active_ipod_changed(self, value: object) -> None:
        active_ipod = value if isinstance(value, ActiveIPod) else None
        self._settings_page.set_active_ipod(active_ipod)
        sync_was_visible = self._workspaces.currentWidget() is self._sync_workspace
        retain_sync = (
            self._sync_controller.busy
            or self._sync_controller.needs_recovery
            or self._sync_controller.needs_cleanup
        )
        if sync_was_visible and not retain_sync:
            self._exit_sync_workspace()
        if not retain_sync:
            self._sync_workspace.clear()
        self._refresh_sync_availability()
        self._sidebar.set_active_ipod(active_ipod)
        self._monitor_normalization(active_ipod)
        current = self._current_page_id()
        if not self._sidebar.page_available(current):
            self._show_page(PageId.ALBUMS.value)
        self.retranslate_ui()

    def _device_busy_changed(self, busy: bool) -> None:
        self._sidebar.set_device_busy(
            busy and not self._context.device_controller.searching
        )
        self._device_picker.set_busy(busy)
        self._refresh_sync_availability()
        self.retranslate_ui()

    def _device_operation_failed(self, value: object) -> None:
        if not isinstance(value, DeviceOperationFailure):
            return
        logger.error(
            "Device %s failed (%s): %s",
            value.operation.value,
            value.error_type,
            value.message,
        )
        if value.operation is DeviceOperation.EJECT:
            self._context.status.clear(_EJECT_STATUS_SOURCE)
        QMessageBox.warning(
            self,
            (
                self.tr("Could Not Safely Eject iPod")
                if value.operation is DeviceOperation.EJECT
                else self.tr("Could Not Load iPod")
            ),
            workflow_text(value.message),
        )

    def _artwork_load_failed(self, value: object) -> None:
        if not isinstance(value, ArtworkLoadFailure):
            return
        logger.warning(
            "Artwork %s failed (%s): %s",
            value.artwork_id,
            value.error_type,
            value.message,
        )

    def _photo_load_failed(self, value: object) -> None:
        if not isinstance(value, PhotoLoadFailure):
            return
        logger.warning(
            "Photo %s format %s failed (%s): %s",
            value.photo_id,
            value.format_id,
            value.error_type,
            value.message,
        )

    def _playback_failed(self, value: object) -> None:
        if not isinstance(value, PlaybackFailure):
            return
        logger.warning(
            "Playback for Track %s failed (%s): %s",
            value.track_id,
            value.error_type,
            value.message,
        )
        self._context.status.show(
            "playback", workflow_text(value.message), timeout_ms=8_000
        )


def _tracks_from_signal(value: object) -> tuple[Track, ...] | None:
    if not isinstance(value, tuple):
        return None
    items = cast("tuple[object, ...]", value)
    tracks: list[Track] = []
    for item in items:
        if not isinstance(item, Track):
            return None
        tracks.append(item)
    return tuple(tracks)


def _photos_from_signal(value: object) -> tuple[Photo, ...] | None:
    if not isinstance(value, tuple):
        return None
    items = cast("tuple[object, ...]", value)
    photos: list[Photo] = []
    for item in items:
        if not isinstance(item, Photo):
            return None
        photos.append(item)
    return tuple(photos)


def _playlist_external_references(
    value: object,
) -> tuple[PlaylistExternalReference, ...] | None:
    if not isinstance(value, tuple):
        return None
    items = cast("tuple[object, ...]", value)
    references: list[PlaylistExternalReference] = []
    for item in items:
        if not isinstance(item, PlaylistExternalReference):
            return None
        references.append(item)
    return tuple(references)
