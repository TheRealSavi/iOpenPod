import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_core.context import create_app_context
from app_core.controllers import (
    QuickWriteController,
    StartupDeviceRestoreController,
    StartupUpdateController,
)
from app_core.device_identity import (
    identify_ipod_at_root,
    refresh_device_disk_usage,
    resolve_device_image_filename,
)
from app_core.jobs import (
    BackSyncRequest,
    BackSyncWorker,
    DeviceRenameWorker,
    DropScanWorker,
    EjectDeviceWorker,
    PodcastPlanRequest,
    PodcastPlanWorker,
    SyncDiffRequest,
    SyncDiffWorker,
    SyncExecuteWorker,
    ToolDownloadWorker,
    build_imported_photo_edit_state,
    check_sync_tool_availability,
    collect_media_file_paths,
    is_media_drop_candidate,
)
from app_core.runtime import (
    ThreadPoolSingleton,
    same_device_path,
)
from app_core.sync_options import build_transcode_options
from app_core.sync_plan_builder import (
    build_filtered_sync_plan,
    build_removal_sync_plan,
)
from GUI.glyphs import glyph_pixmap
from GUI.notifications import Notifier
from GUI.styles import FONT_FAMILY, Colors, Metrics, btn_css
from GUI.widgets.backupBrowser import BackupBrowserWidget
from GUI.widgets.dropOverlay import DropOverlayWidget
from GUI.widgets.musicBrowser import MusicBrowser
from GUI.widgets.settingsPage import SettingsPage
from GUI.widgets.sidebar import Sidebar
from GUI.widgets.syncReview import (
    PCFolderDialog,
    SyncReviewWidget,
)

if TYPE_CHECKING:
    from app_core.context import AppContext
    from app_core.services import DeviceManagerLike, LibraryCacheLike

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, context: "AppContext | None" = None):
        super().__init__()

        self.context = context or create_app_context()
        self.settings_service = self.context.settings
        self.device_session_service = self.context.device_sessions
        self.library_service = self.context.libraries
        self.device_manager: DeviceManagerLike = self.device_session_service.manager()
        self.library_cache: LibraryCacheLike = self.library_service.cache()

        self.setWindowTitle("iOpenPod")

        # Load startup settings through the app-core service seam.
        settings = self.settings_service.get_global_snapshot()

        # Restore remembered window size
        self.resize(settings.window_width, settings.window_height)

        # Initialize system notifications
        self._notifier = Notifier.get_instance(self)

        # Drag-and-drop support
        self.setAcceptDrops(True)
        self._drop_worker = None

        # Sync worker reference
        self._sync_worker = None
        self._back_sync_worker = None
        self._podcast_plan_worker = None
        self._sync_execute_worker = None
        self._tool_download_worker = None
        self._keep_sync_results_visible_after_rescan = False
        self._plan = None
        self._last_pc_folder = settings.media_folder or ""
        self._last_device_path = settings.last_device_path or ""
        self._startup_restore = StartupDeviceRestoreController(
            self.device_manager,
            self._last_device_path,
            self,
        )
        self._startup_updates = StartupUpdateController(
            self._create_update_checker,
            self,
        )
        self._library_view_device_path: str | None = None

        # Eject worker (safe-unmount off the UI thread)
        self._eject_worker: EjectDeviceWorker | None = None

        self._quick_write_controller = QuickWriteController(
            self.device_manager,
            self.library_cache,
            self._is_sync_running,
            self,
        )

        # Defer expensive theme rebuilds (e.g., match-iPod accent) so device
        # load/UI hydration is not blocked on the same event-loop turn.
        self._pending_theme_rebuild = False
        self._theme_rebuild_restore_page = 0
        self._theme_rebuild_timer = QTimer(self)
        self._theme_rebuild_timer.setSingleShot(True)
        self._theme_rebuild_timer.setInterval(20)
        self._theme_rebuild_timer.timeout.connect(self._run_deferred_theme_rebuild)

        # Central widget with stacked layout for main/sync views
        self.centralStack = QStackedWidget()
        self.setCentralWidget(self.centralStack)

        # Build all child widgets and connect signals
        self._build_ui()
        self._quick_write_controller.save_status_changed.connect(
            self.sidebar.show_save_indicator
        )
        self._quick_write_controller.metadata_failed.connect(
            self._on_quick_meta_failed
        )

        # Drop overlay (created after _build_ui so it sits on top)
        self._drop_overlay = DropOverlayWidget(self)

        # Connect device manager to reload data when device changes
        device_manager = self.device_manager
        device_manager.device_changed.connect(self.onDeviceChanged)
        device_manager.device_settings_loaded.connect(self.onDeviceSettingsLoaded)
        device_manager.device_settings_failed.connect(self.onDeviceSettingsFailed)

        # Connect cache ready signal to refresh UI
        self.library_cache.data_ready.connect(self.onDataReady)
        self.musicBrowser.photoBrowser.bind_cache(self.library_cache)

        # Schedule an immediate write whenever track flags are edited in the UI
        self.library_cache.tracks_changed.connect(
            self._quick_write_controller.schedule_metadata_write
        )

        # Instant playlist sync whenever playlists are added/edited via context menu
        self.library_cache.playlist_quick_sync.connect(
            self._quick_write_controller.schedule_playlist_sync
        )

        self._show_default_page()
        self._startup_restore.start_later(100)
        self._startup_updates.update_available.connect(
            self.settingsPage._handle_update_result
        )
        self._startup_updates.start_later(2000)

    @staticmethod
    def _create_update_checker(parent):
        """Create the existing GUI update checker for the app-core controller."""
        from GUI.auto_updater import UpdateChecker

        return UpdateChecker(parent)

    def _build_ui(self):
        """Create child widgets and wire up signals.

        Called once from ``__init__`` and again by ``_on_theme_changed``
        to rebuild the UI with fresh themed styles.
        """
        # Main browsing page
        self.mainWidget = QWidget()
        self.mainLayout = QHBoxLayout(self.mainWidget)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)

        self.musicBrowser = MusicBrowser(
            settings_service=self.settings_service,
            device_sessions=self.device_session_service,
            libraries=self.library_service,
        )
        self.musicBrowser.podcastBrowser.podcast_sync_requested.connect(self._onPodcastSyncRequested)
        self.musicBrowser.browserTrack.remove_from_ipod_requested.connect(self._onRemoveFromIpod)
        self.musicBrowser.playlistBrowser.trackList.remove_from_ipod_requested.connect(self._onRemoveFromIpod)

        self.sidebar = Sidebar()
        self.sidebar.category_changed.connect(self.musicBrowser.updateCategory)
        self.sidebar.device_renamed.connect(self._onDeviceRenamed)
        self.sidebar.eject_requested.connect(self._onEjectDevice)
        self.sidebar.deviceButton.clicked.connect(self.selectDevice)
        self.sidebar.rescanButton.clicked.connect(self.resyncDevice)
        self.sidebar.syncButton.clicked.connect(self.startPCSync)
        self.sidebar.settingsButton.clicked.connect(self.showSettings)
        self.sidebar.backupButton.clicked.connect(self.showBackupBrowser)

        self.mainContentStack = QStackedWidget()

        self.mainLayout.addWidget(self.sidebar)
        self.mainLayout.addWidget(self.mainContentStack)
        self.centralStack.addWidget(self.mainWidget)  # Index 0

        # Sync review page
        self.syncReview = SyncReviewWidget(
            settings_service=self.settings_service,
            device_sessions=self.device_session_service,
        )
        self.syncReview.cancelled.connect(self._onSyncReviewCancelled)
        self.syncReview.sync_requested.connect(self.executeSyncPlan)
        self.centralStack.addWidget(self.syncReview)  # Index 1

        # Settings page
        self.settingsPage = SettingsPage(
            settings_service=self.settings_service,
            device_sessions=self.device_session_service,
        )
        self.settingsPage.closed.connect(self.hideSettings)
        self.settingsPage.theme_changed.connect(self._on_theme_changed)
        self.settingsPage.artwork_appearance_changed.connect(
            self._on_artwork_appearance_changed
        )
        self.centralStack.addWidget(self.settingsPage)  # Index 2

        # Backup browser page
        self.backupBrowser = BackupBrowserWidget(
            settings_service=self.settings_service,
            device_sessions=self.device_session_service,
            libraries=self.library_service,
        )
        self.backupBrowser.closed.connect(self.hideBackupBrowser)
        self.centralStack.addWidget(self.backupBrowser)  # Index 3

        # Selective sync browser page
        from GUI.widgets.selectiveSyncBrowser import SelectiveSyncBrowser
        self.selectiveSyncBrowser = SelectiveSyncBrowser(
            settings_service=self.settings_service,
            device_sessions=self.device_session_service,
        )
        self.selectiveSyncBrowser.selection_done.connect(self._onSelectiveSyncDone)
        self.selectiveSyncBrowser.cancelled.connect(self._onSelectiveSyncCancelled)
        self.centralStack.addWidget(self.selectiveSyncBrowser)  # Index 4

        # No-device placeholder section (shown in content area; sidebar stays visible)
        self.noDeviceWidget = QWidget()
        no_device_layout = QVBoxLayout(self.noDeviceWidget)
        no_device_layout.setContentsMargins((36), (36), (36), (36))
        no_device_layout.setSpacing(12)

        no_device_layout.addStretch(1)

        title = QLabel("Select an iPod to continue")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        no_device_layout.addWidget(title)

        subtitle = QLabel(
            "No device is currently selected.\n"
            "Choose an iPod to access your library and sync tools."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        subtitle.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        no_device_layout.addWidget(subtitle)

        select_btn = QPushButton("Select Device")
        select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        select_btn.setFixedWidth(170)
        select_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        select_btn.setStyleSheet(btn_css(
            bg=Colors.ACCENT,
            bg_hover=Colors.ACCENT_LIGHT,
            bg_press=Colors.ACCENT,
            fg=Colors.TEXT_ON_ACCENT,
            border="none",
            padding="8px 14px",
        ))
        select_btn.clicked.connect(self.selectDevice)

        select_row = QHBoxLayout()
        select_row.addStretch(1)
        select_row.addWidget(select_btn)
        select_row.addStretch(1)
        no_device_layout.addLayout(select_row)

        no_device_layout.addStretch(2)

        self.mainContentStack.addWidget(self.musicBrowser)   # Index 0
        self.mainContentStack.addWidget(self.noDeviceWidget)  # Index 1

        self.loadingDeviceWidget = QWidget()
        loading_layout = QVBoxLayout(self.loadingDeviceWidget)
        loading_layout.setContentsMargins((36), (36), (36), (36))
        loading_layout.setSpacing(12)
        loading_layout.addStretch(1)

        loading_title = QLabel("Loading iPod...")
        loading_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.DemiBold))
        loading_title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        loading_layout.addWidget(loading_title)

        loading_subtitle = QLabel("Reading library and device settings.")
        loading_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_subtitle.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        loading_subtitle.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        loading_layout.addWidget(loading_subtitle)
        loading_layout.addStretch(2)

        self.mainContentStack.addWidget(self.loadingDeviceWidget)  # Index 2

    def _show_default_page(self):
        """Show main page and switch content area by device selection state."""
        self._refresh_default_page_state()
        self.centralStack.setCurrentIndex(0)

    def _refresh_default_page_state(self):
        """Refresh the main browsing page state without changing pages."""
        has_device = bool(self.device_manager.device_path)
        self.sidebar.setLibraryTabsVisible(has_device)
        if has_device:
            ready = self.library_cache.is_ready()
            self.mainContentStack.setCurrentIndex(0 if ready else 2)
        else:
            self.mainContentStack.setCurrentIndex(1)

    def _is_sync_results_visible(self) -> bool:
        """Return whether the user is currently looking at sync results."""
        return (
            self.centralStack.currentWidget() is self.syncReview
            and self.syncReview.stack.currentIndex() == 3
        )

    def _should_show_default_page_on_data_ready(self) -> bool:
        """Only let library refreshes navigate when the main page is active."""
        return self.centralStack.currentIndex() == 0

    def _rebuild_themed_ui(self, restore_page: int | None = None):
        """Tear down and rebuild all widgets after a theme/accent change.

        Args:
            restore_page: Stack index to show after rebuild. ``None`` keeps
                          the current page index.
        """
        from GUI.styles import app_stylesheet, build_palette

        if restore_page is None:
            restore_page = self.centralStack.currentIndex()

        self.setUpdatesEnabled(False)
        try:
            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.setPalette(build_palette())
                app.setStyleSheet(app_stylesheet())

            # Tear down existing widgets
            while self.centralStack.count():
                w = self.centralStack.widget(0)
                if w is not None:
                    self.centralStack.removeWidget(w)
                    w.deleteLater()

            # Rebuild with newly set styles
            self._build_ui()
            self.musicBrowser.photoBrowser.bind_cache(self.library_cache)

            # Restore page and settings state
            self.settingsPage.load_from_settings()
            self.centralStack.setCurrentIndex(
                min(restore_page, self.centralStack.count() - 1)
            )

            # If cache is loaded, reload UI from cache.
            # Use get_data() rather than get_tracks() so device info still
            # repopulates for empty libraries / partial parser data.
            cache = self.library_cache
            if cache.get_data() is not None:
                self.onDataReady()
        finally:
            self.setUpdatesEnabled(True)

    def _reset_library_category_for_new_device(self, path: str) -> None:
        """Start each newly selected device on Albums without affecting refreshes."""
        if not path:
            self._library_view_device_path = None
            return
        if same_device_path(path, self._library_view_device_path):
            return
        self._library_view_device_path = path
        self.sidebar.resetLibraryCategory()

    def _on_theme_changed(self):
        """Rebuild the entire UI after a live theme switch (from settings)."""
        settings_scope = getattr(self.settingsPage, "_settings_scope", "global")
        self._rebuild_themed_ui(restore_page=2)
        if settings_scope == "device" and hasattr(self.settingsPage, "set_settings_scope"):
            self.settingsPage.set_settings_scope("device")

    def _on_artwork_appearance_changed(self):
        """Refresh visible artwork after UI-only artwork settings change."""
        self.musicBrowser.refresh_artwork_appearance()
        self.selectiveSyncBrowser.refresh_artwork_appearance()

    def selectDevice(self):
        """Open device picker dialog to scan and select an iPod."""
        from GUI.widgets.devicePicker import DevicePickerDialog

        self._startup_restore.cancel()
        dialog = DevicePickerDialog(self)
        if dialog.exec() and dialog.selected_path:
            folder = dialog.selected_path
            device_manager = self.device_manager
            if device_manager.is_valid_ipod_root(folder):
                selected_ipod = dialog.selected_ipod
                if selected_ipod is None:
                    selected_ipod = identify_ipod_at_root(folder)
                    if selected_ipod is None:
                        QMessageBox.warning(
                            self,
                            "Invalid iPod Folder",
                            "The selected folder could not be identified as an iPod.",
                        )
                        return
                    folder = selected_ipod.path or folder

                device_manager.discovered_ipod = selected_ipod
                device_manager.device_path = folder
                # Persist selection
                global_settings = self.settings_service.get_global_settings()
                global_settings.last_device_path = folder
                self.settings_service.save_global_settings(global_settings)
            else:
                QMessageBox.warning(
                    self,
                    "Invalid iPod Folder",
                    "The selected folder does not appear to be a valid iPod root.\n\n"
                    "Expected structure:\n"
                    "  <selected folder>/iPod_Control/iTunes/\n\n"
                    "Please select the root folder of your iPod."
                )

    def onDeviceChanged(self, path: str):
        """Handle device selection - start loading data."""
        # Cancel any pending style rebuild from a prior device before starting
        # a new load cycle.
        if self._theme_rebuild_timer.isActive():
            self._theme_rebuild_timer.stop()
        self._pending_theme_rebuild = False

        # Clear the thread pool of pending tasks
        thread_pool = ThreadPoolSingleton.get_instance()
        thread_pool.clear()

        from .imgMaker import clear_artwork_api
        clear_artwork_api()

        if self._apply_effective_theme():
            self._schedule_themed_rebuild(restore_page=0)

        self.musicBrowser.reloadData()
        self.sidebar.clearDeviceInfo()

        if path:
            self._reset_library_category_for_new_device(path)
            self._show_default_page()
            # Start loading data (will emit data_ready when done)
            self.library_cache.start_loading()
        else:
            self._reset_library_category_for_new_device("")
            self.sidebar.clearDeviceInfo()
            self._show_default_page()

    def onDeviceSettingsLoaded(self, path: str):
        """Apply UI updates after on-iPod settings finish loading."""
        if not same_device_path(path, self.device_manager.device_path):
            return

        try:
            self.settingsPage._sync_scope_availability()
        except Exception:
            logger.debug("Failed to refresh settings scope availability", exc_info=True)

        if self._apply_effective_theme():
            self._schedule_themed_rebuild(restore_page=self.centralStack.currentIndex())
        elif getattr(self.settingsPage, "_settings_scope", "global") == "device":
            self.settingsPage.load_from_settings()

    def onDeviceSettingsFailed(self, path: str, error: str):
        """Keep the UI on global settings if per-device settings cannot load."""
        if not same_device_path(path, self.device_manager.device_path):
            return
        logger.warning("Using global settings; device settings failed: %s", error)
        try:
            self.settingsPage._sync_scope_availability()
        except Exception:
            logger.debug("Failed to refresh settings scope availability", exc_info=True)
        if getattr(self.settingsPage, "_settings_scope", "global") == "device":
            self.settingsPage.load_from_settings()

    def resyncDevice(self):
        """Rebuild the cache from the current device."""
        device = self.device_manager
        if not device.device_path:
            return
        self.library_cache.clear()
        self.onDeviceChanged(device.device_path)

    def onDataReady(self):
        """Called when iTunesDB data is loaded and ready."""
        cache = self.library_cache
        keep_current_page_visible = (
            not self._should_show_default_page_on_data_ready()
            or (
                self._keep_sync_results_visible_after_rescan
                and self._is_sync_results_visible()
            )
        )
        self._keep_sync_results_visible_after_rescan = False
        if keep_current_page_visible:
            self._refresh_default_page_state()
        else:
            self._show_default_page()

        tracks = cache.get_tracks()
        albums = cache.get_albums()
        db_data = cache.get_data()
        classified = self._classify_tracks(tracks)

        from iTunesDB_Shared.constants import get_version_name
        session = self.device_session_service.current_session()
        device_identity = session.identity

        # If accent is "match-ipod", apply the device color and schedule a
        # deferred full rebuild so we do not block this load callback.
        if self._apply_match_ipod_accent(device_identity):
            self._schedule_themed_rebuild(restore_page=self.centralStack.currentIndex())

        # Refresh disk usage so the storage bar reflects post-sync changes
        refresh_device_disk_usage(self.device_manager.discovered_ipod)

        device_name = device_identity.ipod_name if device_identity else "Unk iPod"
        model = device_identity.display_name if device_identity else "Unk iPod"

        db_version_hex = db_data.get('VersionHex', '') if db_data else ''
        db_version_name = get_version_name(db_version_hex) if db_version_hex else ''
        database_id = db_data.get('DatabaseID', 0) if db_data else 0

        self.sidebar.updateDeviceInfo(
            name=device_name,
            model=model,
            tracks=len(tracks),
            albums=len(albums),
            size_bytes=sum(t.get("size", 0) for t in tracks),
            duration_ms=sum(t.get("length", 0) for t in tracks),
            db_version_hex=db_version_hex,
            db_version_name=db_version_name,
            db_id=database_id,
            videos=len(classified["video"]),
            podcasts=len(classified["podcast"]),
            audiobooks=len(classified["audiobook"]),
            device_info=self.device_manager.discovered_ipod,
        )
        self._update_sidebar_visibility(classified)
        self.musicBrowser.browserTrack.clearTable(clear_cache=True)
        self._update_podcast_statuses()
        self.musicBrowser.onDataReady()

    def _schedule_themed_rebuild(self, restore_page: int = 0) -> None:
        """Queue a deferred themed UI rebuild if one is not already pending."""
        self._theme_rebuild_restore_page = restore_page
        if self._pending_theme_rebuild:
            return
        self._pending_theme_rebuild = True
        self._theme_rebuild_timer.start()

    def _run_deferred_theme_rebuild(self) -> None:
        """Execute a previously scheduled themed rebuild."""
        self._pending_theme_rebuild = False
        self._rebuild_themed_ui(restore_page=self._theme_rebuild_restore_page)

    def _apply_effective_theme(self, dev=None) -> bool:
        """Apply the currently effective theme/accent and report visual changes."""
        from GUI.styles import Colors, Metrics, resolve_accent_color

        s = self.settings_service.get_effective_settings()
        if dev is None:
            dev = self.device_session_service.current_session().identity

        img = ""
        if s.accent_color == "match-ipod":
            img = resolve_device_image_filename(dev)

        old_accent = Colors.ACCENT
        accent_hex = resolve_accent_color(s.accent_color, img)
        Colors.apply_theme(s.theme, s.high_contrast, accent_hex)
        Metrics.apply_font_scale(s.font_scale)
        return Colors.ACCENT != old_accent

    def _apply_match_ipod_accent(self, dev=None):
        """Re-apply accent color when 'match-ipod' is active and device is known.

        Returns True if the accent actually changed (UI rebuild needed).
        """
        s = self.settings_service.get_effective_settings()
        if s.accent_color != "match-ipod":
            return False
        if dev is None:
            dev = self.device_session_service.current_session().identity

        img = resolve_device_image_filename(dev)

        from GUI.styles import Colors, resolve_accent_color
        accent_hex = resolve_accent_color("match-ipod", img)

        # Always apply the resolved accent, including "blue" fallback.
        # This ensures switching from a colorful device to a gray/white/black
        # device resets the UI back to the default accent.
        old_accent = Colors.ACCENT
        Colors.apply_theme(s.theme, s.high_contrast, accent_hex)
        return Colors.ACCENT != old_accent

    @staticmethod
    def _classify_tracks(tracks: list) -> dict[str, list]:
        """Partition tracks by media type into audio/video/podcast/audiobook."""
        from iTunesDB_Shared.constants import (
            MEDIA_TYPE_AUDIO,
            MEDIA_TYPE_AUDIOBOOK,
            MEDIA_TYPE_PODCAST,
            MEDIA_TYPE_VIDEO_MASK,
        )
        audio, video, podcast, audiobook = [], [], [], []
        for t in tracks:
            mt = t.get("media_type", 1)
            if mt == 0 or mt & MEDIA_TYPE_AUDIO:
                audio.append(t)
            if (mt & MEDIA_TYPE_VIDEO_MASK) and not (mt & MEDIA_TYPE_AUDIO) and mt != 0:
                video.append(t)
            if mt & MEDIA_TYPE_PODCAST:
                podcast.append(t)
            if mt & MEDIA_TYPE_AUDIOBOOK:
                audiobook.append(t)
        return {"audio": audio, "video": video, "podcast": podcast, "audiobook": audiobook}

    def _update_sidebar_visibility(self, classified: dict[str, list]) -> None:
        """Show/hide sidebar categories based on tracks and device capabilities."""
        caps = self.device_session_service.current_session().capabilities

        has_video = len(classified["video"]) > 0
        has_podcast = len(classified["podcast"]) > 0
        photodb = self.library_cache.get_photo_db()
        has_photos = bool(photodb and getattr(photodb, "photos", {}))

        self.sidebar.setVideoVisible(has_video or (caps.supports_video if caps else False))
        self.sidebar.setPodcastVisible(has_podcast or (caps.supports_podcast if caps else False))
        self.sidebar.setPhotoVisible(has_photos or (caps.supports_photo if caps else False))

    def _onDeviceRenamed(self, new_name: str):
        """Handle device rename from sidebar — update master playlist and write to iPod."""
        device = self.device_manager
        if not device.device_path:
            return

        cache = self.library_cache
        data = cache.get_data()
        if not data:
            return

        dev = device.discovered_ipod
        if dev is not None:
            from typing import cast
            cast(Any, dev).ipod_name = new_name

        # Update master playlist Title in the cache
        playlists = cache.get_playlists()
        master_pl = None
        for pl in playlists:
            if pl.get("master_flag"):
                pl["Title"] = new_name
                master_pl = pl
                break

        if not master_pl:
            logger.warning("Could not find master playlist to rename")
            return

        logger.info("Renaming iPod to '%s'", new_name)

        # Write the full database to persist the rename
        self._rename_worker = DeviceRenameWorker(device.device_path, new_name)
        self._rename_worker.finished_ok.connect(self._onRenameDone)
        self._rename_worker.failed.connect(self._onRenameFailed)
        self._rename_worker.start()

    def _onRenameDone(self):
        """Device rename write completed."""
        logger.info("iPod renamed successfully")
        Notifier.get_instance().notify("iPod Renamed", "Device name updated successfully")
        # Reload the database to reflect changes
        cache = self.library_cache
        cache.clear()
        cache.start_loading()

    def _onRenameFailed(self, error_msg: str):
        """Device rename write failed."""
        logger.error("iPod rename failed: %s", error_msg)
        QMessageBox.critical(
            self, "Rename Failed",
            f"Failed to rename iPod:\n{error_msg}"
        )

    # ── Eject ──────────────────────────────────────────────────────────

    def _flush_quick_writes_for_eject(self) -> bool:
        """Finish any queued quick database writes before ejecting."""
        QApplication.processEvents()
        ok, label = self._quick_write_controller.flush_before_eject()
        QApplication.processEvents()
        if not ok:
            QMessageBox.warning(
                self,
                "Save In Progress",
                f"iOpenPod is still saving {label} to the iPod. "
                "Try ejecting again when the save finishes.",
            )
            return False

        return self._settle_background_device_reads_for_eject()

    def _settle_background_device_reads_for_eject(self) -> bool:
        """Stop best-effort UI/background reads that can keep the drive open."""
        try:
            self.musicBrowser.reloadData()
        except Exception:
            logger.debug("Failed to clear music browser before eject", exc_info=True)

        try:
            from .imgMaker import clear_artwork_api
            clear_artwork_api()
        except Exception:
            logger.debug("Failed to clear artwork cache before eject", exc_info=True)

        self.device_manager.cancel_all_operations()
        pool = ThreadPoolSingleton.get_instance()
        pool.clear()
        if not pool.waitForDone(5000):
            QMessageBox.warning(
                self,
                "Still Reading iPod",
                "iOpenPod is still finishing background reads from the iPod. "
                "Try ejecting again in a moment.",
            )
            return False

        QApplication.processEvents()
        return True

    def _onEjectDevice(self):
        """Safely eject the current iPod from the OS."""
        device = self.device_manager
        path = device.device_path
        if not path:
            return

        if self._is_sync_running():
            QMessageBox.warning(
                self, "Sync In Progress",
                "Please wait for the current sync to finish before ejecting."
            )
            return

        # Flush any pending in-memory edits before pulling the volume out.
        if not self._flush_quick_writes_for_eject():
            return

        self.sidebar.device_card.eject_button.setEnabled(False)

        self._eject_worker = EjectDeviceWorker(path)
        self._eject_worker.finished_ok.connect(self._onEjectDone)
        self._eject_worker.failed.connect(self._onEjectFailed)
        self._eject_worker.start()

    def _onEjectDone(self, message: str):
        logger.info("iPod ejected: %s", message)
        if self._eject_worker is not None:
            self._eject_worker.deleteLater()
            self._eject_worker = None
        Notifier.get_instance().notify("iPod Ejected", message)
        self.device_manager.device_path = None
        # Forget the restored device so it doesn't auto-reconnect next launch.
        try:
            s = self.settings_service.get_global_settings()
            s.last_device_path = ""
            self.settings_service.save_global_settings(s)
        except Exception:
            logger.warning("Failed to clear last_device_path from settings", exc_info=True)

    def _onEjectFailed(self, error_msg: str):
        logger.error("iPod eject failed: %s", error_msg)
        if self._eject_worker is not None:
            self._eject_worker.deleteLater()
            self._eject_worker = None
        # Re-enable the button so the user can retry.
        has_device = bool(self.device_manager.device_path)
        self.sidebar.device_card.eject_button.setEnabled(has_device)
        try:
            if self.library_cache.is_ready():
                self.onDataReady()
        except Exception:
            logger.debug("Failed to restore UI after eject failure", exc_info=True)
        QMessageBox.critical(
            self, "Eject Failed",
            f"Failed to eject the iPod:\n{error_msg}"
        )

    def _is_sync_running(self) -> bool:
        return (
            (self._sync_worker is not None and self._sync_worker.isRunning())
            or (self._back_sync_worker is not None and self._back_sync_worker.isRunning())
            or (
                self._podcast_plan_worker is not None
                and self._podcast_plan_worker.isRunning()
            )
            or (self._sync_execute_worker is not None and self._sync_execute_worker.isRunning())
        )

    def _on_quick_meta_failed(self, error_msg: str):
        # Re-queue edits: they were already popped, so the worker's snapshot is
        # now lost.  Inform the user so they can re-edit or do a full sync.
        QMessageBox.warning(
            self, "Save Failed",
            f"Could not save track changes to iPod:\n{error_msg}\n\n"
            "Your edits are lost for this session. "
            "You can re-apply them and sync again."
        )

    def _create_back_sync_artwork_provider(self, ipod_path: str):
        """Build a GUI-side artwork provider for the app-core Back Sync job."""
        if not ipod_path:
            return None

        artworkdb_path = Path(ipod_path) / "iPod_Control" / "Artwork" / "ArtworkDB"
        artwork_folder = Path(ipod_path) / "iPod_Control" / "Artwork"
        if not artworkdb_path.exists() or not artwork_folder.exists():
            return None

        try:
            from GUI.imgMaker import configure_artwork_api, get_artwork

            configure_artwork_api(str(artworkdb_path), str(artwork_folder))
        except Exception:
            logger.debug("Back Sync artwork context unavailable", exc_info=True)
            return None

        def _track_artwork_id(track: dict) -> int | None:
            artwork_id = (
                track.get("artwork_id_ref")
                or track.get("mhii_link")
                or track.get("mhiiLink")
                or 0
            )
            if not artwork_id:
                return None
            try:
                return int(artwork_id)
            except (TypeError, ValueError):
                return None

        def _provider(track: dict) -> bytes | None:
            artwork_id = _track_artwork_id(track)
            if artwork_id is None:
                return None
            try:
                import io

                img = get_artwork(artwork_id, mode="image_only")
                if not img:
                    return None
                img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=90)
                return buf.getvalue()
            except Exception:
                logger.debug("Back Sync artwork extraction failed", exc_info=True)
                return None

        return _provider

    def startPCSync(self):
        """Start the PC to iPod sync process."""
        # If a quick metadata write is in progress, cancel the pending timer and
        # wait briefly for the worker to finish so we don't race on the DB.
        self._quick_write_controller.prepare_for_full_sync()

        device = self.device_manager
        if not device.device_path:
            QMessageBox.warning(
                self,
                "No Device",
                "Please select an iPod device first."
            )
            return

        settings = self.settings_service.get_effective_settings()
        tools = check_sync_tool_availability(settings)

        if tools.has_missing:
            if tools.can_download:
                dlg = _MissingToolsDialog(self, tools.tool_list, can_download=True)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    self._download_missing_tools_then_sync(
                        tools.missing_ffmpeg,
                        tools.missing_fpcalc,
                    )
                    return
                elif not tools.can_continue_without_download:
                    return
                # ffmpeg missing but user declined — let them continue with MP3/M4A only
            else:
                # Platform doesn't support auto-download
                dlg = _MissingToolsDialog(
                    self,
                    tools.tool_list,
                    can_download=False,
                    detail_lines=tools.install_help_text,
                )
                if tools.can_continue_without_download:
                    dlg.add_continue_option()

                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return
                # User clicked Continue Anyway (only possible when fpcalc is present)

        # Show folder selection dialog
        dialog = PCFolderDialog(self, self._last_pc_folder)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self._last_pc_folder = dialog.selected_folder
        # Persist the folder choice
        global_settings = self.settings_service.get_global_settings()
        global_settings.media_folder = dialog.selected_folder
        self.settings_service.save_global_settings(global_settings)
        settings = self.settings_service.get_effective_settings()

        # Branch: selective sync opens the PC library browser first
        if dialog.sync_mode == "selective":
            self.centralStack.setCurrentIndex(4)
            self.selectiveSyncBrowser.load(self._last_pc_folder)
            return

        # Branch: Back Sync runs outside the regular sync-plan flow.
        if dialog.sync_mode == "back_sync":
            self.centralStack.setCurrentIndex(1)
            self.syncReview.show_back_sync_loading()

            cache = self.library_cache
            ipod_tracks = cache.get_tracks()

            device_manager = self.device_manager
            self._back_sync_worker = BackSyncWorker(
                BackSyncRequest(
                    pc_folder=self._last_pc_folder,
                    ipod_tracks=ipod_tracks,
                    ipod_path=device_manager.device_path or "",
                ),
                artwork_provider=self._create_back_sync_artwork_provider(
                    device_manager.device_path or "",
                ),
            )
            self._back_sync_worker.progress.connect(self.syncReview.update_progress)
            self._back_sync_worker.finished.connect(self._onBackSyncComplete)
            self._back_sync_worker.error.connect(self._onSyncError)
            # Ensure worker reference is cleared on finish/error
            self._back_sync_worker.finished.connect(lambda _: setattr(self, '_back_sync_worker', None))
            self._back_sync_worker.error.connect(lambda _: setattr(self, '_back_sync_worker', None))
            self._back_sync_worker.start()
            return

        # Switch to sync review view
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()

        # Check device media capabilities through the app-core session seam.
        caps = self.device_session_service.current_session().capabilities
        supports_video = bool(caps and caps.supports_video)
        supports_podcast = bool(caps and caps.supports_podcast)

        # Gather GUI state to pass forward (not pulled by SyncEngine)
        cache = self.library_cache
        ipod_tracks = cache.get_tracks()

        track_edits = cache.get_track_edits()
        photo_edits = cache.get_photo_edits()
        try:
            sync_workers = settings.sync_workers
            rating_strategy = settings.rating_conflict_strategy
            fpcalc_path = settings.fpcalc_path
        except Exception:
            sync_workers = 0  # auto
            rating_strategy = "ipod_wins"
            fpcalc_path = ""

        device_manager = self.device_manager

        self._sync_worker = SyncDiffWorker(
            SyncDiffRequest(
                pc_folder=self._last_pc_folder,
                ipod_tracks=ipod_tracks,
                ipod_path=device_manager.device_path or "",
                supports_video=supports_video,
                supports_podcast=supports_podcast,
                track_edits=track_edits,
                photo_edits=photo_edits,
                sync_workers=sync_workers,
                rating_strategy=rating_strategy,
                fpcalc_path=fpcalc_path,
                photo_sync_settings={
                    "rotate_tall_photos_for_device": (
                        settings.rotate_tall_photos_for_device
                    ),
                    "fit_photo_thumbnails": settings.fit_photo_thumbnails,
                },
                transcode_options=build_transcode_options(settings),
            )
        )
        self._sync_worker.progress.connect(self.syncReview.update_progress)
        self._sync_worker.finished.connect(self._onSyncDiffComplete)
        self._sync_worker.error.connect(self._onSyncError)
        self._sync_worker.start()

    def _download_missing_tools_then_sync(self, need_ffmpeg: bool, need_fpcalc: bool):
        """Download missing tools in a background thread, then restart sync."""
        progress = _DownloadProgressDialog(self)
        progress.show()

        # Keep a reference so it isn't garbage collected
        self._dl_progress = progress

        worker = ToolDownloadWorker(
            need_ffmpeg=need_ffmpeg,
            need_fpcalc=need_fpcalc,
        )
        self._tool_download_worker = worker
        worker.completed.connect(self._on_tools_downloaded)
        worker.error.connect(self._on_tools_download_failed)
        worker.finished.connect(lambda: setattr(self, "_tool_download_worker", None))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    @pyqtSlot()
    def _on_tools_downloaded(self):
        """Called on main thread after tool downloads finish."""
        if hasattr(self, '_dl_progress') and self._dl_progress:
            self._dl_progress.close()
            self._dl_progress = None
        # Re-run sync now that tools should be available
        self.startPCSync()

    @pyqtSlot(str)
    def _on_tools_download_failed(self, error_msg: str):
        """Called on main thread if automatic tool download fails."""
        if hasattr(self, '_dl_progress') and self._dl_progress:
            self._dl_progress.close()
            self._dl_progress = None
        QMessageBox.critical(
            self,
            "Download Failed",
            f"Could not download sync tools:\n\n{error_msg}",
        )

    def _onPodcastSyncRequested(self, plan):
        """Handle podcast sync plan from PodcastBrowser.

        Receives a SyncPlan with podcast episodes as to_add items and
        sends it through the standard sync review pipeline.
        """
        self._plan = plan
        cache = self.library_cache
        self.syncReview._ipod_tracks_cache = cache.get_tracks() or []

        # Switch to sync review view and show the plan
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_plan(plan)

    def _onRemoveFromIpod(self, tracks: list):
        """Build a removal-only SyncPlan for the selected tracks and show sync review."""
        if not tracks:
            return

        plan = build_removal_sync_plan(tracks)
        self._plan = plan
        cache = self.library_cache
        self.syncReview._ipod_tracks_cache = cache.get_tracks() or []
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_plan(plan)

    def _onSyncDiffComplete(self, plan):
        """Called when sync diff calculation is complete."""
        self._plan = plan  # Store for executeSyncPlan to access matched_pc_paths
        # Provide iPod tracks cache so the review widget can list artwork-missing tracks
        cache = self.library_cache
        ipod_tracks = cache.get_tracks() or []
        self.syncReview._ipod_tracks_cache = ipod_tracks

        # ── Populate playlist change info on the plan ──────────────
        self._populate_playlist_changes(plan, cache)

        # ── Merge podcast managed plan ─────────────────────────────
        # This requires refreshing RSS feeds and possibly downloading
        # episodes, so it runs in the background.  The sync review is
        # shown after the podcast plan is merged (or immediately if
        # there are no podcast subscriptions).
        browser = self.musicBrowser.podcastBrowser
        store = browser._store
        feeds = store.get_feeds() if store else []

        if not feeds:
            self.syncReview.show_plan(plan)
            return

        self.syncReview.update_progress("podcast_sync", 0, 0, "Refreshing podcast feeds…")

        worker = PodcastPlanWorker(
            PodcastPlanRequest(
                feeds=feeds,
                ipod_tracks=ipod_tracks,
                store=store,
            )
        )
        self._podcast_plan_worker = worker
        worker.finished.connect(
            lambda podcast_plan: self._on_podcast_plan_ready(plan, podcast_plan),
        )
        worker.error.connect(
            lambda err: self._on_podcast_plan_error(plan, err),
        )
        worker.finished.connect(lambda _: setattr(self, '_podcast_plan_worker', None))
        worker.error.connect(lambda _: setattr(self, '_podcast_plan_worker', None))
        worker.start()

    def _on_podcast_plan_ready(self, plan, podcast_plan) -> None:
        """Podcast plan built — merge into music plan and show."""
        if podcast_plan.to_add:
            plan.to_add.extend(podcast_plan.to_add)
            plan.storage.bytes_to_add += podcast_plan.storage.bytes_to_add
        if podcast_plan.to_remove:
            plan.to_remove.extend(podcast_plan.to_remove)
            plan.storage.bytes_to_remove += podcast_plan.storage.bytes_to_remove
        self.syncReview.show_plan(plan)

    def _on_podcast_plan_error(self, plan, error_msg: str) -> None:
        """Podcast plan failed — show music-only plan."""
        logger.warning("Failed to build podcast plan: %s", error_msg)
        self.syncReview.show_plan(plan)

    def _populate_playlist_changes(self, plan, cache):
        """Compute playlist add/edit/remove lists for the sync plan.

        Compares user-created/edited playlists (pending in cache) against
        the existing iPod playlists to categorize changes.
        """
        user_playlists = cache.get_user_playlists()
        if not user_playlists:
            return

        # Build set of existing iPod playlist IDs (from parsed DB)
        existing_ids: set[int] = set()
        data = cache.get_data()
        if data:
            for pl in data.get("mhlp", []):
                pid = pl.get("playlist_id", 0)
                if pid:
                    existing_ids.add(pid)
            for pl in data.get("mhlp_podcast", []):
                pid = pl.get("playlist_id", 0)
                if pid:
                    existing_ids.add(pid)
            for pl in data.get("mhlp_smart", []):
                pid = pl.get("playlist_id", 0)
                if pid:
                    existing_ids.add(pid)

        for upl in user_playlists:
            pid = upl.get("playlist_id", 0)
            is_new = upl.get("_isNew", False)
            if is_new or pid not in existing_ids:
                plan.playlists_to_add.append(upl)
            else:
                plan.playlists_to_edit.append(upl)

    def _onSyncError(self, error_msg: str):
        """Called when sync diff fails."""
        self.syncReview.show_error(error_msg)

    def _onBackSyncComplete(self, result: dict):
        """Called when Back Sync export completes."""
        self._back_sync_worker = None

        exported = int(result.get("exported", 0) or 0)
        missing = int(result.get("missing_on_pc", 0) or 0)
        self.syncReview.show_back_sync_result(result)

        if not self.isActiveWindow():
            if missing:
                message = f"{exported:,} of {missing:,} missing track{'s' if missing != 1 else ''} exported"
            else:
                message = "No iPod-only tracks were found"
            self._notifier.notify("Back Sync Complete", message)

    def _onSelectiveSyncDone(self, folder: str, selected_paths):
        """User finished picking tracks in selective sync; run diff on selection."""
        self._last_pc_folder = folder
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()

        caps = self.device_session_service.current_session().capabilities
        supports_video = bool(caps and caps.supports_video)
        supports_podcast = bool(caps and caps.supports_podcast)

        cache = self.library_cache
        ipod_tracks = cache.get_tracks()
        track_edits = cache.get_track_edits()
        selected_track_paths = selected_paths
        selected_photo_imports = ()
        if isinstance(selected_paths, dict):
            selected_track_paths = frozenset(selected_paths.get("tracks", ()))
            selected_photo_imports = tuple(selected_paths.get("photos", ()))

        photo_edits = build_imported_photo_edit_state(selected_photo_imports)
        settings = self.settings_service.get_effective_settings()
        try:
            sync_workers = settings.sync_workers
            rating_strategy = settings.rating_conflict_strategy
            fpcalc_path = settings.fpcalc_path
        except Exception:
            sync_workers = 0
            rating_strategy = "ipod_wins"
            fpcalc_path = ""

        device_manager = self.device_manager
        self._sync_worker = SyncDiffWorker(
            SyncDiffRequest(
                pc_folder=folder,
                ipod_tracks=ipod_tracks,
                ipod_path=device_manager.device_path or "",
                supports_video=supports_video,
                supports_podcast=supports_podcast,
                track_edits=track_edits,
                photo_edits=photo_edits,
                sync_workers=sync_workers,
                rating_strategy=rating_strategy,
                fpcalc_path=fpcalc_path,
                photo_sync_settings={
                    "rotate_tall_photos_for_device": (
                        settings.rotate_tall_photos_for_device
                    ),
                    "fit_photo_thumbnails": settings.fit_photo_thumbnails,
                },
                transcode_options=build_transcode_options(settings),
                allowed_paths=frozenset(selected_track_paths),
            )
        )
        self._sync_worker.progress.connect(self.syncReview.update_progress)
        self._sync_worker.finished.connect(self._onSyncDiffComplete)
        self._sync_worker.error.connect(self._onSyncError)
        self._sync_worker.start()

    def _onSelectiveSyncCancelled(self):
        """User cancelled selective sync browser."""
        self._show_default_page()

    def _onSyncReviewCancelled(self) -> None:
        """Handle cancel from the sync review page.

        During sync execution we only request cancellation and keep the page
        visible so partial-save confirmation (save vs discard) can be shown.
        """
        if self._back_sync_worker is not None and self._back_sync_worker.isRunning():
            self._back_sync_worker.requestInterruption()
            return
        if (
            self._podcast_plan_worker is not None
            and self._podcast_plan_worker.isRunning()
        ):
            self._podcast_plan_worker.requestInterruption()
            return

        if self._sync_execute_worker is not None and self._sync_execute_worker.isRunning():
            self._sync_execute_worker.requestInterruption()
            return
        self.hideSyncReview()

    def hideSyncReview(self):
        """Return to the main browsing view, stopping any background work."""
        self._keep_sync_results_visible_after_rescan = False
        if self._sync_worker is not None and self._sync_worker.isRunning():
            self._sync_worker.requestInterruption()
        if self._back_sync_worker is not None and self._back_sync_worker.isRunning():
            self._back_sync_worker.requestInterruption()
        self._cleanup_podcast_plan_worker()
        self._cleanup_sync_execute_worker()
        self._show_default_page()

    def _cleanup_podcast_plan_worker(self):
        """Stop and detach any in-flight managed podcast planning worker."""
        w = self._podcast_plan_worker
        if w is None:
            return
        if w.isRunning():
            w.requestInterruption()
        for sig in (w.finished, w.error):
            try:
                sig.disconnect()
            except TypeError:
                pass
        self._podcast_plan_worker = None

    def _cleanup_sync_execute_worker(self):
        """Request interruption and disconnect all signals from the execute worker.

        The worker thread may continue running briefly (in-flight futures
        can't be force-killed), but with signals disconnected it can't
        affect the UI. Clearing the reference lets ``_is_sync_running``
        return False so a new sync can start cleanly.
        """
        w = self._sync_execute_worker
        if w is None:
            return
        if w.isRunning():
            w.requestInterruption()
        # Disconnect all signals so stale callbacks don't fire
        for sig in (w.progress, w.finished, w.error, w.confirm_partial_save):
            try:
                sig.disconnect()
            except TypeError:
                pass
        self._disconnect_skip_signal()
        self._sync_execute_worker = None

    def showSettings(self):
        """Show the settings page."""
        self.settingsPage.load_from_settings()
        self.centralStack.setCurrentIndex(2)

    def hideSettings(self):
        """Return from settings to the main browsing view."""
        # Re-read persisted settings to pick up changes
        settings = self.settings_service.get_global_settings()
        self._last_pc_folder = settings.media_folder or self._last_pc_folder
        self._show_default_page()

    def showBackupBrowser(self):
        """Show the backup browser page."""
        self.backupBrowser.refresh()
        self.centralStack.setCurrentIndex(3)

    def hideBackupBrowser(self):
        """Return from backup browser to the main browsing view."""
        self._show_default_page()

    def executeSyncPlan(self, selected_items):
        """Execute the selected sync actions."""
        # Get device path
        device_manager = self.device_manager
        if not device_manager.device_path:
            QMessageBox.warning(self, "No Device", "No iPod device selected.")
            return

        original_plan = self._plan  # stored in _onSyncDiffComplete

        # Playlists: only include if the playlist card's checkbox is checked
        pl_card = getattr(self.syncReview, '_playlist_card', None)
        include_playlists = (
            pl_card is not None and pl_card._select_all_cb.isChecked()
        ) if pl_card else True  # default to True if no card exists

        filtered_plan = build_filtered_sync_plan(
            original_plan,
            selected_items,
            include_playlists=include_playlists,
            selected_photo_plan=(
                self.syncReview.get_selected_photo_plan() if original_plan else None
            ),
        )

        if not filtered_plan.has_changes:
            return

        # Show progress in sync review widget
        self.syncReview.show_executing()

        # Respect the user's pre-sync backup choice from the prompt
        skip_backup = getattr(self.syncReview, '_skip_presync_backup', False)

        # Gather GUI state to pass to executor (instead of it pulling from GUI)
        cache = self.library_cache
        user_playlists = cache.get_user_playlists()

        def _on_sync_complete():
            """Called by executor after successful DB write to clear pending state."""
            self.library_cache.clear_pending_sync_state()

        # Start sync execution worker
        device_session = self.device_session_service.current_session()
        self._sync_execute_worker = SyncExecuteWorker(
            ipod_path=device_manager.device_path or "",
            plan=filtered_plan,
            settings=self.settings_service.get_effective_settings(),
            skip_backup=skip_backup,
            user_playlists=user_playlists,
            device_info=device_session.identity,
            on_sync_complete=_on_sync_complete,
        )
        self._sync_execute_worker.progress.connect(self.syncReview.update_execute_progress)
        self._sync_execute_worker.finished.connect(self._onSyncExecuteComplete)
        self._sync_execute_worker.error.connect(self._onSyncExecuteError)
        self._sync_execute_worker.confirm_partial_save.connect(self._onConfirmPartialSave)
        # Allow the user to skip the in-progress backup from the progress screen
        self.syncReview.skip_backup_signal.connect(self._sync_execute_worker.request_skip_backup)
        self.syncReview.give_up_scrobble_signal.connect(self._sync_execute_worker.request_give_up_scrobble)
        self._sync_execute_worker.start()

    def _onSyncExecuteComplete(self, result):
        """Called when sync execution is complete."""
        self._disconnect_skip_signal()
        # Show styled results view instead of a plain message box
        self.syncReview.show_result(result)
        self._keep_sync_results_visible_after_rescan = True

        # Desktop notification if app is not focused
        if not self.isActiveWindow():
            self._notifier.notify_sync_complete(
                added=getattr(result, 'tracks_added', 0),
                removed=getattr(result, 'tracks_removed', 0),
                updated=getattr(result, 'tracks_updated_metadata', 0) + getattr(result, 'tracks_updated_file', 0),
                errors=len(getattr(result, 'errors', [])),
            )

        # Reload the database to show changes (delay lets OS flush writes)
        QTimer.singleShot(500, self._rescanAfterSync)

    def _update_podcast_statuses(self):
        """Mark synced podcast episodes as 'on_ipod' in the subscription store."""
        try:
            browser = self.musicBrowser.podcastBrowser
            if not browser._store:
                return

            cache = self.library_cache
            ipod_tracks = cache.get_tracks() or []

            browser.reconcile_ipod_statuses(ipod_tracks)

            # Refresh the podcast browser episode table so status is visible
            browser.refresh_episodes()
        except Exception as e:
            logger.debug("Could not update podcast statuses: %s", e)

    def _rescanAfterSync(self):
        """Rescan the iPod database after a short post-write delay."""
        cache = self.library_cache
        # Use clear() (not invalidate()) to fully reset the cache state.
        # invalidate() does not reset _is_loading, so if a prior load is
        # still in-flight start_loading() would silently bail out and the
        # UI would never refresh.
        cache.clear()

        # Clear artwork cache — sync may have added/changed album art
        from .imgMaker import clear_artwork_api
        clear_artwork_api()

        # Clear UI so the reload starts from a clean slate
        self.musicBrowser.reloadData()

        cache.start_loading()

    def _disconnect_skip_signal(self):
        """Disconnect worker control signals from the finished worker."""
        try:
            self.syncReview.skip_backup_signal.disconnect()
        except TypeError:
            pass  # Already disconnected
        try:
            self.syncReview.give_up_scrobble_signal.disconnect()
        except TypeError:
            pass  # Already disconnected

    def _onSyncExecuteError(self, error_msg: str):
        """Called when sync execution fails."""
        self._disconnect_skip_signal()
        # Desktop notification if app is not focused
        if not self.isActiveWindow():
            self._notifier.notify_sync_error(error_msg)

        settings = self.settings_service.get_effective_settings()

        msg = f"Sync failed:\n\n{error_msg}"
        if settings.backup_before_sync:
            msg += (
                "\n\nA backup was created before this sync. "
                "You can restore it from the Backups page."
            )

        QMessageBox.critical(self, "Sync Error", msg)
        self.hideSyncReview()

    def _onConfirmPartialSave(self, n_added: int, n_skipped: int) -> None:
        """Called from the sync worker when the user cancels mid-sync with tracks already copied.
        Shows a dialog asking whether to save the partial database, then unblocks the worker."""
        worker = getattr(self, '_sync_execute_worker', None)
        if worker is None:
            return

        tracks_word = "track" if n_added == 1 else "tracks"
        skipped_line = (
            f"{n_skipped} more {'track was' if n_skipped == 1 else 'tracks were'} not copied."
            if n_skipped > 0 else ""
        )

        msg = QMessageBox(self)
        msg.setWindowTitle("Save Partial Sync?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            f"{n_added} {tracks_word} were successfully copied to your iPod before the sync was cancelled."
        )
        detail = "Would you like to save these tracks to your iPod's database?"
        if skipped_line:
            detail = skipped_line + "\n\n" + detail
        detail += (
            "\n\nIf you discard, the copied files will be cleaned up automatically the next time you sync."
        )
        msg.setInformativeText(detail)
        save_btn = msg.addButton("Save Partial Database", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton("Discard", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(save_btn)
        msg.exec()

        # Default to save if dialog was closed via X button (no explicit choice)
        save = (msg.clickedButton() != discard_btn)
        worker.respond_to_partial_save(save)

    # ── Drag-and-drop support ──────────────────────────────────────────────

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        if hasattr(self, '_drop_overlay') and self._drop_overlay.isVisible():
            self._drop_overlay.setGeometry(self.rect())

    def dragEnterEvent(self, a0):
        if a0 is None:
            return
        # Reject drops when no device is selected or sync is executing
        device = self.device_manager
        if not device.device_path:
            a0.ignore()
            return
        if self._sync_execute_worker and self._sync_execute_worker.isRunning():
            a0.ignore()
            return

        mime = a0.mimeData()
        if mime and mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    if is_media_drop_candidate(Path(url.toLocalFile())):
                        a0.acceptProposedAction()
                        self._drop_overlay.show_overlay()
                        return
        a0.ignore()

    def dragMoveEvent(self, a0):
        if a0:
            a0.acceptProposedAction()

    def dragLeaveEvent(self, a0):
        self._drop_overlay.hide_overlay()

    def dropEvent(self, a0):
        self._drop_overlay.hide_overlay()
        if a0 is None:
            return
        mime = a0.mimeData()
        if not mime or not mime.hasUrls():
            return

        paths: list[Path] = []
        for url in mime.urls():
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))

        if paths:
            a0.acceptProposedAction()
            self._on_files_dropped(paths)

    def _on_files_dropped(self, paths: list[Path]):
        """Process dropped files/folders in a background thread."""
        file_paths = collect_media_file_paths(paths)
        if not file_paths:
            return

        # Remember whether we already have a plan to merge into
        self._drop_merge = (
            self._plan is not None
            and self.centralStack.currentIndex() == 1
        )

        # Switch to sync review and show loading
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()
        self.syncReview.loading_label.setText("Reading dropped files...")

        # Run metadata reading in background thread
        self._drop_worker = DropScanWorker(file_paths)
        self._drop_worker.finished.connect(self._on_drop_scan_complete)
        self._drop_worker.error.connect(self._onSyncError)
        self._drop_worker.start()

    def _on_drop_scan_complete(self, plan):
        """Merge dropped-file plan into any existing plan, then show."""
        if self._drop_merge and self._plan is not None:
            self._plan.to_add.extend(plan.to_add)
            self._plan.storage.bytes_to_add += plan.storage.bytes_to_add
            self.syncReview.show_plan(self._plan)
        else:
            self._plan = plan
            self.syncReview.show_plan(plan)

    def closeEvent(self, a0):
        """Ensure all threads are stopped when the window is closed."""
        # Persist window dimensions
        try:
            _s = self.settings_service.get_global_settings()
            _s.window_width = self.width()
            _s.window_height = self.height()
            self.settings_service.save_global_settings(_s)
        except Exception:
            pass

        # Clean up system tray notification icon
        Notifier.shutdown()

        # Request graceful stop for sync workers
        self._startup_restore.stop(3000)
        self._startup_updates.stop(3000)
        if self._sync_worker and self._sync_worker.isRunning():
            self._sync_worker.requestInterruption()
            self._sync_worker.wait(3000)
        if self._podcast_plan_worker and self._podcast_plan_worker.isRunning():
            self._podcast_plan_worker.requestInterruption()
            self._podcast_plan_worker.wait(3000)
        if self._sync_execute_worker and self._sync_execute_worker.isRunning():
            self._sync_execute_worker.requestInterruption()
            self._sync_execute_worker.wait(3000)
        self._quick_write_controller.shutdown(3000)

        thread_pool = ThreadPoolSingleton.get_instance()
        if thread_pool:
            thread_pool.clear()  # Remove pending tasks
            thread_pool.waitForDone(3000)  # Wait up to 3 seconds for running tasks
        if a0:
            a0.accept()


# ============================================================================
# Dialogs
# ============================================================================

class _MissingToolsDialog(QDialog):
    """Dark-themed dialog prompting the user to download missing tools."""

    def __init__(
        self,
        parent: QWidget,
        tool_list: str,
        can_download: bool,
        detail_lines: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Missing Tools")
        self.setFixedWidth(420)
        self.setStyleSheet(f"""
            QDialog {{
                background: {Colors.DIALOG_BG};
                color: {Colors.TEXT_PRIMARY};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins((28), (24), (28), (24))
        layout.setSpacing(10)

        # Icon + title row
        icon_label = QLabel()
        _warnpx = glyph_pixmap("warning-triangle", Metrics.FONT_ICON_MD, Colors.WARNING)
        if _warnpx:
            icon_label.setPixmap(_warnpx)
        else:
            icon_label.setText("△")
            icon_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_MD))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        title = QLabel(f"{tool_list} Not Found")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        layout.addSpacing(4)

        if can_download:
            body = QLabel(
                "iOpenPod can download these automatically (~80 MB).\n"
                "Download now?"
            )
        else:
            body = QLabel(detail_lines)
        body.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        body.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        layout.addWidget(body)

        layout.addSpacing(12)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        if can_download:
            no_btn = QPushButton("Not Now")
            no_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            no_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            no_btn.setMinimumHeight(40)
            no_btn.setStyleSheet(btn_css(
                bg=Colors.SURFACE_RAISED,
                bg_hover=Colors.SURFACE_HOVER,
                bg_press=Colors.SURFACE_ACTIVE,
                border=f"1px solid {Colors.BORDER_SUBTLE}",
                padding="8px 24px",
            ))
            no_btn.clicked.connect(self.reject)
            btn_row.addWidget(no_btn)

            yes_btn = QPushButton("Download")
            yes_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            yes_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            yes_btn.setMinimumHeight(40)
            yes_btn.setStyleSheet(btn_css(
                bg=Colors.ACCENT_DIM,
                bg_hover=Colors.ACCENT_HOVER,
                bg_press=Colors.ACCENT_PRESS,
                border=f"1px solid {Colors.ACCENT_BORDER}",
                padding="8px 24px",
            ))
            yes_btn.clicked.connect(self.accept)
            btn_row.addWidget(yes_btn)
        else:
            ok_btn = QPushButton("OK")
            ok_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            ok_btn.setMinimumHeight(40)
            ok_btn.setStyleSheet(btn_css(
                bg=Colors.SURFACE_RAISED,
                bg_hover=Colors.SURFACE_HOVER,
                bg_press=Colors.SURFACE_ACTIVE,
                border=f"1px solid {Colors.BORDER_SUBTLE}",
                padding="8px 24px",
            ))
            ok_btn.clicked.connect(self.reject)
            btn_row.addWidget(ok_btn)

            # If only ffmpeg is missing, offer to continue
            self._continue_btn: QPushButton | None = None

        layout.addLayout(btn_row)

    def add_continue_option(self):
        """Add a 'Continue Anyway' button (for ffmpeg-only missing)."""
        btn_layout = self.layout()
        assert isinstance(btn_layout, QVBoxLayout)
        # Get the last item which is the btn_row layout
        btn_row_item = btn_layout.itemAt(btn_layout.count() - 1)
        row_layout = btn_row_item.layout() if btn_row_item else None
        if row_layout is not None:
            cont_btn = QPushButton("Continue Anyway")
            cont_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            cont_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cont_btn.setMinimumHeight(40)
            cont_btn.setStyleSheet(btn_css(
                bg=Colors.ACCENT_DIM,
                bg_hover=Colors.ACCENT_HOVER,
                bg_press=Colors.ACCENT_PRESS,
                border=f"1px solid {Colors.ACCENT_BORDER}",
                padding="8px 24px",
            ))
            cont_btn.clicked.connect(self.accept)
            row_layout.addWidget(cont_btn)


class _DownloadProgressDialog(QDialog):
    """Dark-themed modal progress dialog for downloading tools."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Downloading")
        self.setFixedSize((380), (180))
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowCloseButtonHint  # type: ignore[operator]
        )
        self.setStyleSheet(f"""
            QDialog {{
                background: {Colors.DIALOG_BG};
                color: {Colors.TEXT_PRIMARY};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins((28), (24), (28), (24))
        layout.setSpacing(14)

        title = QLabel("Downloading Tools…")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._status = QLabel("Preparing download…")
        self._status.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._status.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        bar = QProgressBar()
        bar.setRange(0, 0)  # indeterminate
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        bar.setStyleSheet(f"""
            QProgressBar {{
                background: {Colors.SURFACE};
                border: none;
                border-radius: {(3)}px;
            }}
            QProgressBar::chunk {{
                background: {Colors.ACCENT};
                border-radius: {(3)}px;
            }}
        """)
        layout.addWidget(bar)

        layout.addStretch()

    def set_status(self, text: str):
        """Update the status label (must be called from the main thread)."""
        self._status.setText(text)
