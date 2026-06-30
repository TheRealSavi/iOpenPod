import logging
import shlex
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QPalette
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
from app_core.device_access import check_ipod_write_access
from app_core.device_identity import (
    identify_ipod_at_root,
    refresh_device_disk_usage,
    resolve_device_image_filename,
)
from app_core.dropped_files import collect_import_file_paths, is_media_drop_candidate
from app_core.jobs import (
    AlbumConversionRequest,
    AlbumConversionWorker,
    BackSyncRequest,
    BackSyncWorker,
    ChapterSplitRequest,
    ChapterSplitWorker,
    DropScanWorker,
    EjectDeviceWorker,
    PodcastPlanRequest,
    PodcastPlanWorker,
    QuickWriteWorker,
    SyncDiffRequest,
    SyncDiffWorker,
    SyncExecuteWorker,
    ToolDownloadWorker,
    build_imported_photo_edit_state,
    check_sync_tool_availability,
)
from app_core.runtime import (
    ThreadPoolSingleton,
    build_album_list,
    same_device_path,
)
from app_core.sync_options import build_transcode_options
from app_core.sync_plan_builder import build_removal_sync_plan
from app_core.sync_plan_merge import merge_additional_sync_plan
from GUI.glyphs import glyph_pixmap
from GUI.internal_drag import is_iopenpod_export_drag
from GUI.notifications import Notifier
from GUI.styles import FONT_FAMILY, Colors, Metrics, btn_css
from GUI.widgets.backupBrowser import BackupBrowserWidget
from GUI.widgets.dropOverlay import DropOverlayWidget
from GUI.widgets.formatters import format_size
from GUI.widgets.musicBrowser import MusicBrowser
from GUI.widgets.settingsPage import SettingsPage
from GUI.widgets.sidebar import Sidebar
from GUI.widgets.syncReview import (
    PCFolderDialog,
    SyncReviewWidget,
)
from infrastructure.i18n import tr as _
from infrastructure.media_folders import (
    media_folder_entries_to_settings,
    media_folder_paths,
)
from SyncEngine.contracts import (
    SYNC_UNTIL_FULL_RESERVE_BYTES,
    sync_plan_required_free_bytes,
)
from SyncEngine.review_selection import build_filtered_sync_plan

if TYPE_CHECKING:
    from app_core.context import AppContext
    from app_core.services import DeviceManagerLike, LibraryCacheLike

logger = logging.getLogger(__name__)


def _mhsd5_type_value(playlist: dict) -> int:
    try:
        return int(playlist.get("mhsd5_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _existing_playlist_rows_for_sync(cache) -> tuple[dict, ...]:
    data = cache.get_data() if cache else None
    if not data:
        return ()
    rows: list[dict] = []
    for key in ("mhlp", "mhlp_podcast", "mhlp_smart"):
        for playlist in data.get(key, []):
            if isinstance(playlist, dict):
                rows.append(dict(playlist))
    return tuple(rows)


def _is_ipod_category_playlist(playlist: dict) -> bool:
    try:
        dataset_type = int(playlist.get("_mhsd_dataset_type", 0) or 0)
    except (TypeError, ValueError):
        dataset_type = 0
    if dataset_type:
        return dataset_type == 5
    return playlist.get("_source") == "category" or bool(_mhsd5_type_value(playlist))


def _label_css(color: str) -> str:
    return f"color: {color}; background: transparent; border: none;"


def _apply_dialog_background(dialog: QDialog) -> None:
    dialog.setAutoFillBackground(True)
    palette = dialog.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(Colors.DIALOG_BG))
    dialog.setPalette(palette)


def _normalize_media_folder_settings(*folder_groups: object) -> list[dict[str, object]]:
    return media_folder_entries_to_settings(*folder_groups)


def _media_folder_entries_from_settings(settings: Any) -> list[dict[str, object]]:
    entries = _normalize_media_folder_settings(getattr(settings, "media_folders", ()))
    if entries:
        return entries
    return _normalize_media_folder_settings(getattr(settings, "media_folder", ""))


_DEVICE_ACCESS_ERROR_MARKERS = (
    "permission denied",
    "read-only file system",
    "[errno 13]",
    "[errno 30]",
    "input/output error",
)


def _looks_like_device_access_error(text: object) -> bool:
    lowered = str(text).lower()
    return any(marker in lowered for marker in _DEVICE_ACCESS_ERROR_MARKERS)


def _sync_execute_failure_message(result: Any) -> str | None:
    """Return the message that should be shown for a failed sync result."""
    if getattr(result, "success", True) or getattr(result, "partial_save", False):
        return None

    errors = list(getattr(result, "errors", []) or [])
    if not errors:
        return _("Sync failed before making changes.")

    prioritized = None
    for desc, msg in errors:
        if str(desc).lower() in {"read-only", "permission"}:
            prioritized = (desc, msg)
            break
        if _looks_like_device_access_error(f"{desc} {msg}"):
            prioritized = (desc, msg)
            break

    desc, msg = prioritized or errors[0]
    text = str(msg).strip() or str(desc).strip()
    return text or "Sync failed before making changes."


def _library_load_failure_message(mount_path: str, error_msg: str) -> str:
    error_text = error_msg.strip() or "Unknown error"
    if not _looks_like_device_access_error(error_text):
        return _("iOpenPod could not load this iPod library.\n\n{error}").format(error=error_text)

    mount = mount_path.strip() or "the iPod mount"
    quoted_mount = shlex.quote(mount) if mount_path.strip() else "<mount-path>"
    return _(
        "iOpenPod could not read this iPod cleanly.\n\n"
        "Mount path: {mount}\n"
        "System error: {error}\n\n"
        "On Linux, this usually means the iPod mount is not accessible, "
        "the FAT filesystem is dirty, or the current user does not have "
        "permission to the mount.\n\n"
        "Try reconnecting the iPod. If it still fails, try remounting it "
        "read-write:\n"
        "  sudo mount -o remount,rw {quoted_mount}\n\n"
        "If the filesystem is dirty, unmount it before repairing it:\n"
        "  sudo umount {quoted_mount}\n"
        "  sudo fsck.vfat -a /dev/sdXN\n\n"
        "Replace /dev/sdXN with the iPod partition. Do not run fsck while "
        "the iPod is mounted."
    ).format(mount=mount, error=error_text, quoted_mount=quoted_mount)


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
        self._back_sync_workers = []
        self._cancelled_workers = []
        self._podcast_plan_worker = None
        self._album_conversion_worker = None
        self._chapter_split_worker = None
        self._sync_execute_worker = None
        self._tool_download_worker = None
        self._keep_sync_results_visible_after_rescan = False
        self._plan = None
        self._last_pc_folder_entries = _media_folder_entries_from_settings(settings)
        self._last_pc_folders = media_folder_paths(self._last_pc_folder_entries)
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
        self._quick_write_controller.playlist_failed.connect(
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
        load_failed = getattr(self.library_cache, "load_failed", None)
        if load_failed is not None:
            load_failed.connect(self.onDataLoadFailed)
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

    @staticmethod
    def _device_name_from_playlists(playlists: list[dict]) -> str:
        for playlist in playlists:
            if playlist.get("master_flag") and not _is_ipod_category_playlist(playlist):
                return str(playlist.get("Title") or "").strip()
        return ""

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
        self.musicBrowser.album_conversion_requested.connect(self._onAlbumConversionRequested)
        self.musicBrowser.browserTrack.split_chapters_requested.connect(self._onChapterSplitRequested)
        self.musicBrowser.browserTrack.remove_from_ipod_requested.connect(self._onRemoveFromIpod)
        self.musicBrowser.playlistBrowser.trackList.split_chapters_requested.connect(self._onChapterSplitRequested)
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
        self.sidebar.tag_fixes_requested.connect(self._onIpodTagFixesRequested)

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
        self.syncReview.edit_selection_requested.connect(self._onSyncReviewEditSelection)
        self.centralStack.addWidget(self.syncReview)  # Index 1

        # Settings page
        self.settingsPage = SettingsPage(
            settings_service=self.settings_service,
            device_sessions=self.device_session_service,
        )
        self.settingsPage.closed.connect(self.hideSettings)
        self.settingsPage.theme_changed.connect(self._on_theme_changed)
        self.settingsPage.language_changed.connect(self._on_language_changed)
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
        self.selectiveSyncBrowser.plan_selection_done.connect(self._onPlanSelectionDone)
        self.selectiveSyncBrowser.plan_selection_cancelled.connect(self._onPlanSelectionCancelled)
        self.centralStack.addWidget(self.selectiveSyncBrowser)  # Index 4

        # No-device placeholder section (shown in content area; sidebar stays visible)
        self.noDeviceWidget = QWidget()
        no_device_layout = QVBoxLayout(self.noDeviceWidget)
        no_device_layout.setContentsMargins((36), (36), (36), (36))
        no_device_layout.setSpacing(12)

        no_device_layout.addStretch(1)

        title = QLabel(_("Select an iPod to continue"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        no_device_layout.addWidget(title)

        subtitle = QLabel(
            _(
                "No device is currently selected.\n"
                "Choose an iPod to access your library and sync tools."
            )
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        subtitle.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        no_device_layout.addWidget(subtitle)

        select_btn = QPushButton(_("Select Device"))
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

        loading_title = QLabel(_("Loading iPod..."))
        loading_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.DemiBold))
        loading_title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        loading_layout.addWidget(loading_title)

        loading_subtitle = QLabel(_("Reading library and device settings."))
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
        self.sidebar.setTagFixesAvailable(has_device and self.library_cache.is_ready())
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

    def _on_language_changed(self):
        """Rebuild the entire UI after a live language switch."""
        self._rebuild_themed_ui(restore_page=2)

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
                            _("Invalid iPod Folder"),
                            _("The selected folder could not be identified as an iPod."),
                        )
                        return
                    folder = selected_ipod.path or folder

                device_manager.discovered_ipod = selected_ipod
                device_manager.device_path = folder
                if same_device_path(device_manager.device_path, folder):
                    # Persist selection only after the access preflight keeps it.
                    global_settings = self.settings_service.get_global_settings()
                    global_settings.last_device_path = folder
                    self.settings_service.save_global_settings(global_settings)
            else:
                QMessageBox.warning(
                    self,
                    _("Invalid iPod Folder"),
                    _(
                        "The selected folder does not appear to be a valid iPod root.\n\n"
                        "Expected structure:\n"
                        "  <selected folder>/iPod_Control/iTunes/\n\n"
                        "Please select the root folder of your iPod."
                    )
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
            access = check_ipod_write_access(path)
            if not access.writable:
                logger.error("Selected iPod is not writable: %s", access.message)
                QMessageBox.critical(self, _("iPod Not Writable"), access.message)
                if same_device_path(path, self.device_manager.device_path):
                    self.device_manager.device_path = None
                return
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
        albums = build_album_list(cache)
        playlists = cache.get_playlists()
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

        device_name = (
            MainWindow._device_name_from_playlists(playlists)
            or (device_identity.ipod_name if device_identity else "")
            or _("Unknown iPod")
        )
        model = device_identity.display_name if device_identity else _("Unknown iPod")

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
        self.sidebar.setTagFixesAvailable(bool(tracks))
        self._update_sidebar_visibility(classified)
        self.musicBrowser.browserTrack.clearTable(clear_cache=True)
        self._update_podcast_statuses()
        self.musicBrowser.onDataReady()

    def onDataLoadFailed(self, error_msg: str):
        """Show device library load failures that would otherwise live only in logs."""
        device_path = self.device_manager.device_path or ""
        logger.error("iPod library load failed: %s", error_msg)
        QMessageBox.critical(
            self,
            _("Could Not Load iPod"),
            _library_load_failure_message(device_path, error_msg),
        )

    def _onIpodTagFixesRequested(self) -> None:
        cache = self.library_cache
        if not cache.is_ready():
            QMessageBox.information(
                self,
                _("Normalize iPod Tags"),
                _("Load an iPod library before running tag normalization."),
            )
            return

        tracks = cache.get_tracks()
        if not tracks:
            QMessageBox.information(
                self,
                _("Normalize iPod Tags"),
                _("No tracks were found in this iPod library."),
            )
            return

        from GUI.widgets.ipodTagFixDialog import IpodLibraryTagFixDialog
        from GUI.widgets.ipodTagNormalizer import (
            ipod_tag_profile,
            suggest_ipod_library_tag_fixes,
        )

        session = self.device_session_service.current_session()
        identity = session.identity
        capabilities = session.capabilities
        profile = ipod_tag_profile(
            family=str(getattr(identity, "model_family", "") or ""),
            generation=str(getattr(identity, "generation", "") or ""),
            uses_sqlite_db=bool(getattr(capabilities, "uses_sqlite_db", False)),
            is_shuffle=bool(getattr(capabilities, "is_shuffle", False)),
        )
        suggestion = suggest_ipod_library_tag_fixes(tracks, profile=profile)
        if not suggestion.changes_by_track:
            QMessageBox.information(
                self,
                _("Normalize iPod Tags"),
                _("No iPod-specific metadata fixes were found for this library."),
            )
            return

        dialog = IpodLibraryTagFixDialog(tracks, suggestion, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        cache.update_track_flags_by_track(tracks, suggestion.changes_by_track)
        changed_tracks = len(suggestion.changes_by_track)
        changed_fields = sum(len(changes) for changes in suggestion.changes_by_track.values())
        self._notifier.notify(
            "iPod Tags Normalized",
            f"Staged {changed_fields:,} field edit{'s' if changed_fields != 1 else ''} "
            f"across {changed_tracks:,} track{'s' if changed_tracks != 1 else ''}.",
        )

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

        if not cache.rename_master_playlist(new_name):
            logger.warning("Could not find master playlist to rename")
            return

        logger.info("Renaming iPod to '%s'", new_name)

        self._rename_worker = QuickWriteWorker(device.device_path, cache)
        self._rename_worker.completed.connect(self._onRenameDone)
        self._rename_worker.error.connect(self._onRenameFailed)
        self._rename_worker.start()

    def _onRenameDone(self, result):
        """Device rename write completed."""
        if not result.success:
            self._onRenameFailed(result.error or _("Database write failed."))
            return
        logger.info("iPod renamed successfully")
        Notifier.get_instance().notify(_("iPod Renamed"), _("Device name updated successfully"))

    def _onRenameFailed(self, error_msg: str):
        """Device rename write failed."""
        logger.error("iPod rename failed: %s", error_msg)
        QMessageBox.critical(
            self,
            _("Rename Failed"),
            _("Failed to rename iPod:\n{error}").format(error=error_msg),
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
                _("Save In Progress"),
                _(
                    "iOpenPod is still saving {label} to the iPod. "
                    "Try ejecting again when the save finishes."
                ).format(label=label),
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
                _("Still Reading iPod"),
                _(
                    "iOpenPod is still finishing background reads from the iPod. "
                    "Try ejecting again in a moment."
                ),
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
                self,
                _("Sync In Progress"),
                _("Please wait for the current sync to finish before ejecting."),
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
        Notifier.get_instance().notify(_("iPod Ejected"), message)
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
            self,
            _("Eject Failed"),
            _("Failed to eject the iPod:\n{error}").format(error=error_msg),
        )

    def _is_sync_running(self) -> bool:
        return (
            (self._sync_worker is not None and self._sync_worker.isRunning())
            or (self._back_sync_worker is not None and self._back_sync_worker.isRunning())
            or (
                self._podcast_plan_worker is not None
                and self._podcast_plan_worker.isRunning()
            )
            or (
                self._album_conversion_worker is not None
                and self._album_conversion_worker.isRunning()
            )
            or (
                self._chapter_split_worker is not None
                and self._chapter_split_worker.isRunning()
            )
            or (self._sync_execute_worker is not None and self._sync_execute_worker.isRunning())
        )

    def _on_quick_meta_failed(self, error_msg: str):
        QMessageBox.warning(
            self,
            _("Save Failed"),
            _(
                "Could not save quick changes to iPod:\n{error}\n\n"
                "iOpenPod is reloading the device view from the iPod."
            ).format(error=error_msg),
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
        device = self.device_manager
        has_device = bool(device.device_path)
        if has_device:
            # Finish queued quick writes before planning so full sync only reads
            # committed iPod state.
            quick_ready, blocked_label = (
                self._quick_write_controller.prepare_for_full_sync()
            )
            if not quick_ready:
                label = blocked_label or _("quick changes")
                QMessageBox.warning(
                    self,
                    _("Quick Changes Still Saving"),
                    _(
                        "iOpenPod is still saving pending quick changes. "
                        "Please wait for {label} to finish before starting a full sync."
                    ).format(label=label),
                )
                return
            if self.library_cache.is_loading():
                QMessageBox.information(
                    self,
                    _("Library Loading"),
                    _("Please wait for the iPod library to finish loading."),
                )
                return

        settings = self.settings_service.get_effective_settings()
        if has_device:
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
                    return
                else:
                    dlg = _MissingToolsDialog(
                        self,
                        tools.tool_list,
                        can_download=False,
                        detail_lines=tools.install_help_text,
                    )
                    dlg.exec()
                    return

        # Show folder selection dialog
        dialog = PCFolderDialog(
            self,
            self._last_pc_folder_entries,
            sync_available=has_device,
        )
        dialog.foldersChanged.connect(self._persist_pc_folder_entries)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self._persist_pc_folder_entries(dialog.selected_folder_entries)
        primary_pc_folder = dialog.selected_folder
        settings = self.settings_service.get_effective_settings()

        if not has_device:
            return

        # Branch: selective sync opens the PC library browser first
        if dialog.sync_mode == "selective":
            self.centralStack.setCurrentIndex(4)
            self.selectiveSyncBrowser.load(self._last_pc_folder_entries)
            return

        # Branch: Back Sync runs outside the regular sync-plan flow.
        if dialog.sync_mode == "back_sync":
            self.centralStack.setCurrentIndex(1)
            self.syncReview.show_back_sync_loading()

            cache = self.library_cache
            ipod_tracks = cache.get_tracks()

            device_manager = self.device_manager
            worker = BackSyncWorker(
                BackSyncRequest(
                    pc_folder=primary_pc_folder,
                    pc_folders=tuple(self._last_pc_folder_entries),
                    ipod_tracks=ipod_tracks,
                    ipod_path=device_manager.device_path or "",
                ),
                artwork_provider=self._create_back_sync_artwork_provider(
                    device_manager.device_path or "",
                ),
            )
            self._back_sync_worker = worker
            self._retain_back_sync_worker(worker)
            worker.progress.connect(self.syncReview.update_progress)
            worker.finished.connect(
                lambda result, w=worker: self._onBackSyncComplete(result, w)
            )
            worker.error.connect(
                lambda error, w=worker: self._onBackSyncError(error, w)
            )
            worker.start()
            return

        # Switch to sync review view
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()

        # Check device media capabilities through the app-core session seam.
        caps = self.device_session_service.current_session().capabilities
        supports_video = bool(caps and caps.supports_video)
        supports_podcast = bool(caps and caps.supports_podcast)
        supports_photo = bool(caps and caps.supports_photo)

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
                pc_folder=primary_pc_folder,
                pc_folders=tuple(self._last_pc_folder_entries),
                ipod_tracks=ipod_tracks,
                ipod_path=device_manager.device_path or "",
                supports_video=supports_video,
                supports_podcast=supports_podcast,
                supports_photo=supports_photo,
                track_edits=track_edits,
                photo_edits=photo_edits,
                sync_workers=sync_workers,
                rating_strategy=rating_strategy,
                existing_playlists=_existing_playlist_rows_for_sync(cache),
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
        worker = self._sync_worker
        worker.progress.connect(self.syncReview.update_progress)
        worker.finished.connect(
            lambda plan, w=worker: self._onSyncDiffComplete(plan, w)
        )
        worker.error.connect(
            lambda error, w=worker: self._onWorkerSyncError("_sync_worker", w, error)
        )
        worker.start()

    def _persist_pc_folder_entries(self, folder_entries: object) -> None:
        """Persist PC media-folder settings immediately after dialog edits."""

        entries = _normalize_media_folder_settings(folder_entries)
        self._last_pc_folder_entries = entries
        self._last_pc_folders = media_folder_paths(entries)
        global_settings = self.settings_service.get_global_settings()
        global_settings.media_folder = (
            self._last_pc_folders[0] if self._last_pc_folders else ""
        )
        global_settings.media_folders = list(entries)
        self.settings_service.save_global_settings(global_settings)

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
            _("Download Failed"),
            _("Could not download sync tools:\n\n{error}").format(error=error_msg),
        )

    def _onPodcastSyncRequested(self, plan):
        """Handle podcast sync plan from PodcastBrowser.

        Receives a SyncPlan with podcast episodes as to_add items and
        sends it through the standard sync review pipeline.
        """
        caps = self.device_session_service.current_session().capabilities
        if caps is not None and not caps.supports_podcast and getattr(plan, "to_add", None):
            QMessageBox.warning(
                self,
                _("Unsupported iPod"),
                _("This iPod does not support podcasts."),
            )
            return
        self._plan = plan
        cache = self.library_cache
        self.syncReview._ipod_tracks_cache = cache.get_tracks() or []

        # Switch to sync review view and show the plan
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_plan(plan)

    def _onAlbumConversionRequested(self, album_items: list[dict]) -> None:
        """Prepare a chaptered-album conversion plan from an Albums grid item."""
        if not album_items:
            return
        if self._is_sync_running():
            QMessageBox.information(
                self,
                _("Sync Running"),
                _("Please wait for the current sync to finish before converting an album."),
            )
            return

        device_manager = self.device_manager
        if not device_manager.device_path:
            QMessageBox.warning(self, _("No Device"), _("Please select an iPod device first."))
            return

        cache = self.library_cache
        if not cache.is_ready():
            QMessageBox.information(self, _("Library Loading"), _("Please wait for the iPod library to finish loading."))
            return

        album_item = dict(album_items[0])
        try:
            from SyncEngine.album_chapters import resolve_album_tracks

            album_tracks = resolve_album_tracks(album_item, cache.get_tracks())
        except Exception as exc:
            logger.debug("Album track resolution failed", exc_info=True)
            QMessageBox.warning(self, _("Album Conversion"), str(exc))
            return

        if len(album_tracks) < 2:
            QMessageBox.information(
                self,
                _("Album Conversion"),
                _("Choose an album with at least two tracks."),
            )
            return

        settings = self.settings_service.get_effective_settings()
        pc_folders = tuple(self._last_pc_folder_entries)
        if not pc_folders:
            pc_folders = tuple(_media_folder_entries_from_settings(settings))

        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()
        self.syncReview.update_progress(
            "album_conversion",
            0,
            len(album_tracks),
            "Preparing chaptered album...",
        )

        worker = AlbumConversionWorker(
            AlbumConversionRequest(
                album_item=album_item,
                album_tracks=album_tracks,
                pc_folders=pc_folders,
                ipod_path=device_manager.device_path or "",
                settings=settings,
                artwork_bytes=self._album_conversion_artwork_bytes(
                    album_item,
                    album_tracks,
                ),
            )
        )
        self._album_conversion_worker = worker
        worker.progress.connect(self.syncReview.update_progress)
        worker.finished.connect(
            lambda result, w=worker: self._onAlbumConversionComplete(result, w)
        )
        worker.error.connect(
            lambda error, w=worker: self._onAlbumConversionError(error, w)
        )
        worker.start()

    def _album_conversion_artwork_bytes(
        self,
        album_item: dict,
        album_tracks: list[dict],
    ) -> bytes | None:
        artwork_id = album_item.get("artwork_id_ref")
        if not artwork_id:
            artwork_id = next(
                (
                    track.get("artwork_id_ref")
                    for track in album_tracks
                    if track.get("artwork_id_ref")
                ),
                None,
            )
        return self._artwork_bytes_for_id(artwork_id, "album conversion")

    def _track_artwork_bytes(self, track: dict) -> bytes | None:
        artwork_id = (
            track.get("artwork_id_ref")
            or track.get("mhii_link")
            or track.get("mhiiLink")
        )
        return self._artwork_bytes_for_id(artwork_id, "chapter split")

    def _artwork_bytes_for_id(self, artwork_id: object, context: str) -> bytes | None:
        if artwork_id is None:
            return None
        artwork_int: int | None = None
        if isinstance(artwork_id, int):
            artwork_int = artwork_id
        elif isinstance(artwork_id, (str, bytes, bytearray)):
            try:
                artwork_int = int(artwork_id)
            except (TypeError, ValueError):
                return None
        if not artwork_int:
            return None
        try:
            import io

            from .imgMaker import get_artwork

            image = get_artwork(artwork_int, mode="image_only")
            if image is None:
                return None
            image = image.convert("RGB")
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=90)
            return buf.getvalue()
        except Exception:
            logger.debug("Could not read %s artwork", context, exc_info=True)
            return None

    def _onAlbumConversionComplete(self, result, worker=None) -> None:
        if worker is not None:
            if self._album_conversion_worker is not worker:
                return
            self._album_conversion_worker = None
        else:
            self._album_conversion_worker = None
        self._plan = result.plan
        self.syncReview._ipod_tracks_cache = self.library_cache.get_tracks() or []
        self.syncReview.show_plan(result.plan)
        warnings = getattr(result, "warnings", ()) or ()
        if warnings:
            logger.debug(
                "Album conversion used iPod source files for %d tracks",
                len(warnings),
            )

    def _onAlbumConversionError(self, error_msg: str, worker=None) -> None:
        if worker is not None:
            if self._album_conversion_worker is not worker:
                return
            self._album_conversion_worker = None
        else:
            self._album_conversion_worker = None
        self.syncReview.show_error(error_msg)

    def _onChapterSplitRequested(self, tracks: list[dict]) -> None:
        """Prepare a chapter-split sync plan from one chaptered track."""
        if not tracks:
            return
        if self._is_sync_running():
            QMessageBox.information(
                self,
                _("Sync Running"),
                _("Please wait for the current sync to finish before splitting chapters."),
            )
            return

        device_manager = self.device_manager
        if not device_manager.device_path:
            QMessageBox.warning(self, _("No Device"), _("Please select an iPod device first."))
            return

        cache = self.library_cache
        if not cache.is_ready():
            QMessageBox.information(
                self,
                _("Library Loading"),
                _("Please wait for the iPod library to finish loading."),
            )
            return

        track = dict(tracks[0])
        try:
            from SyncEngine.album_chapters import build_chapter_split_segments

            segments = build_chapter_split_segments(track)
        except Exception as exc:
            logger.debug("Chapter split validation failed", exc_info=True)
            QMessageBox.warning(self, _("Chapter Split"), str(exc))
            return

        settings = self.settings_service.get_effective_settings()
        pc_folders = tuple(self._last_pc_folder_entries)
        if not pc_folders:
            pc_folders = tuple(_media_folder_entries_from_settings(settings))

        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()
        self.syncReview.update_progress(
            "chapter_split",
            0,
            len(segments),
            "Preparing chapter split...",
        )

        worker = ChapterSplitWorker(
            ChapterSplitRequest(
                track=track,
                pc_folders=pc_folders,
                ipod_path=device_manager.device_path or "",
                settings=settings,
                artwork_bytes=self._track_artwork_bytes(track),
            )
        )
        self._chapter_split_worker = worker
        worker.progress.connect(self.syncReview.update_progress)
        worker.finished.connect(
            lambda result, w=worker: self._onChapterSplitComplete(result, w)
        )
        worker.error.connect(
            lambda error, w=worker: self._onChapterSplitError(error, w)
        )
        worker.start()

    def _onChapterSplitComplete(self, result, worker=None) -> None:
        if worker is not None:
            if self._chapter_split_worker is not worker:
                return
            self._chapter_split_worker = None
        else:
            self._chapter_split_worker = None
        self._plan = result.plan
        self.syncReview._ipod_tracks_cache = self.library_cache.get_tracks() or []
        self.syncReview.show_plan(result.plan)
        warnings = getattr(result, "warnings", ()) or ()
        if warnings:
            logger.debug(
                "Chapter split used iPod source file for %d tracks",
                len(warnings),
            )

    def _onChapterSplitError(self, error_msg: str, worker=None) -> None:
        if worker is not None:
            if self._chapter_split_worker is not worker:
                return
            self._chapter_split_worker = None
        else:
            self._chapter_split_worker = None
        self.syncReview.show_error(error_msg)

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

    def _onSyncDiffComplete(self, plan, worker=None):
        """Called when sync diff calculation is complete."""
        if worker is not None:
            if self._sync_worker is not worker:
                return
            self._sync_worker = None
        else:
            self._sync_worker = None
        self._plan = plan  # Store for executeSyncPlan to access matched_pc_paths
        # Provide iPod tracks cache so the review widget can list artwork-missing tracks
        cache = self.library_cache
        ipod_tracks = cache.get_tracks() or []
        self.syncReview._ipod_tracks_cache = ipod_tracks

        # ── Merge podcast managed plan ─────────────────────────────
        # This requires refreshing RSS feeds and possibly downloading
        # episodes, so it runs in the background.  The sync review is
        # shown after the podcast plan is merged (or immediately if
        # there are no podcast subscriptions).
        browser = self.musicBrowser.podcastBrowser
        store = browser._store
        feeds = store.get_feeds() if store else []
        caps = self.device_session_service.current_session().capabilities
        supports_podcast = bool(caps and caps.supports_podcast)

        if not feeds or not supports_podcast:
            self.syncReview.show_plan(plan)
            return

        self.syncReview.update_progress("podcast_sync", 0, 0, "Refreshing podcast feeds…")

        worker = PodcastPlanWorker(
            PodcastPlanRequest(
                feeds=feeds,
                ipod_tracks=ipod_tracks,
                store=store,
                supports_podcast=supports_podcast,
            )
        )
        self._podcast_plan_worker = worker
        worker.finished.connect(
            lambda podcast_plan, w=worker: self._on_podcast_plan_ready(plan, podcast_plan, w),
        )
        worker.error.connect(
            lambda err, w=worker: self._on_podcast_plan_error(plan, err, w),
        )
        worker.start()

    def _on_podcast_plan_ready(self, plan, podcast_plan, worker=None) -> None:
        """Podcast plan built — merge into music plan and show."""
        if worker is not None:
            if self._podcast_plan_worker is not worker:
                return
            self._podcast_plan_worker = None
        else:
            self._podcast_plan_worker = None
        if podcast_plan.to_add:
            plan.to_add.extend(podcast_plan.to_add)
            plan.storage.bytes_to_add += podcast_plan.storage.bytes_to_add
        if podcast_plan.to_remove:
            plan.to_remove.extend(podcast_plan.to_remove)
            plan.storage.bytes_to_remove += podcast_plan.storage.bytes_to_remove
        self.syncReview.show_plan(plan)

    def _on_podcast_plan_error(self, plan, error_msg: str, worker=None) -> None:
        """Podcast plan failed — show music-only plan."""
        if worker is not None:
            if self._podcast_plan_worker is not worker:
                return
            self._podcast_plan_worker = None
        else:
            self._podcast_plan_worker = None
        logger.warning("Failed to build podcast plan: %s", error_msg)
        self.syncReview.show_plan(plan)

    def _onSyncError(self, error_msg: str):
        """Called when sync diff fails."""
        self.syncReview.show_error(error_msg)

    def _onWorkerSyncError(self, attr_name: str, worker, error_msg: str) -> None:
        if worker is not None:
            if getattr(self, attr_name, None) is not worker:
                return
            setattr(self, attr_name, None)
        self._onSyncError(error_msg)

    def _onBackSyncComplete(self, result: dict, worker=None):
        """Called when Back Sync export completes."""
        if worker is not None:
            if self._back_sync_worker is not worker:
                return
            self._clear_back_sync_worker(worker)
        else:
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

    def _onBackSyncError(self, error_msg: str, worker=None) -> None:
        if worker is not None:
            if self._back_sync_worker is not worker:
                return
            self._clear_back_sync_worker(worker)
        else:
            self._back_sync_worker = None
        self._onSyncError(error_msg)

    def _retain_back_sync_worker(self, worker) -> None:
        """Keep a Back Sync thread alive until Qt reports it has stopped."""

        if not hasattr(self, "_back_sync_workers"):
            self._back_sync_workers = []
        if worker in self._back_sync_workers:
            return

        self._back_sync_workers.append(worker)
        try:
            QThread.finished.__get__(worker, type(worker)).connect(
                lambda w=worker: self._reap_back_sync_worker(w)
            )
        except Exception:
            # Tests may use lightweight worker fakes that are not QThreads.
            pass

    def _clear_back_sync_worker(self, worker) -> None:
        if self._back_sync_worker is worker:
            self._back_sync_worker = None

    def _reap_back_sync_worker(self, worker) -> None:
        self._clear_back_sync_worker(worker)
        try:
            self._back_sync_workers.remove(worker)
        except (AttributeError, ValueError):
            pass
        try:
            worker.deleteLater()
        except (AttributeError, RuntimeError):
            pass

    def _retain_cancelled_worker(self, worker) -> None:
        """Keep a detached worker alive until its thread has stopped."""

        if not hasattr(self, "_cancelled_workers"):
            self._cancelled_workers = []
        if worker in self._cancelled_workers:
            return

        self._cancelled_workers.append(worker)
        try:
            QThread.finished.__get__(worker, type(worker)).connect(
                lambda w=worker: self._reap_cancelled_worker(w)
            )
        except Exception:
            pass

    def _clear_worker_reference(self, worker) -> None:
        for attr_name in (
            "_sync_worker",
            "_podcast_plan_worker",
            "_album_conversion_worker",
            "_chapter_split_worker",
        ):
            if getattr(self, attr_name, None) is worker:
                setattr(self, attr_name, None)

    def _reap_cancelled_worker(self, worker) -> None:
        self._clear_worker_reference(worker)
        try:
            self._cancelled_workers.remove(worker)
        except (AttributeError, ValueError):
            pass
        try:
            worker.deleteLater()
        except (AttributeError, RuntimeError):
            pass

    def _cleanup_worker(self, attr_name: str, signal_names: tuple[str, ...]) -> None:
        """Detach and interrupt a worker used by the sync review planning page."""

        worker = getattr(self, attr_name, None)
        if worker is None:
            return

        if worker.isRunning():
            worker.requestInterruption()
        for signal_name in signal_names:
            try:
                getattr(worker, signal_name).disconnect()
            except (AttributeError, TypeError, RuntimeError):
                pass

        setattr(self, attr_name, None)
        if worker.isRunning():
            self._retain_cancelled_worker(worker)
        else:
            self._reap_cancelled_worker(worker)

    def _cleanup_back_sync_worker(self) -> None:
        """Detach a cancelled Back Sync worker from the UI without destroying it."""

        worker = self._back_sync_worker
        if worker is None:
            return

        if worker.isRunning():
            worker.requestInterruption()
        for sig in (worker.progress, worker.finished, worker.error):
            try:
                sig.disconnect()
            except (TypeError, RuntimeError):
                pass

        self._clear_back_sync_worker(worker)
        if worker.isRunning():
            self._retain_back_sync_worker(worker)
        else:
            self._reap_back_sync_worker(worker)

    def _cleanup_sync_diff_worker(self) -> None:
        self._cleanup_worker("_sync_worker", ("progress", "finished", "error"))

    def _cleanup_album_conversion_worker(self) -> None:
        self._cleanup_worker(
            "_album_conversion_worker",
            ("progress", "finished", "error"),
        )

    def _cleanup_chapter_split_worker(self) -> None:
        self._cleanup_worker(
            "_chapter_split_worker",
            ("progress", "finished", "error"),
        )

    def _onSelectiveSyncDone(self, folder: object, selected_paths):
        """User finished picking tracks in selective sync; run diff on selection."""
        selected_folder_entries = _normalize_media_folder_settings(folder)
        selected_folders = media_folder_paths(selected_folder_entries)
        self._last_pc_folder_entries = selected_folder_entries
        self._last_pc_folders = selected_folders
        primary_pc_folder = selected_folders[0] if selected_folders else ""
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()

        caps = self.device_session_service.current_session().capabilities
        supports_video = bool(caps and caps.supports_video)
        supports_podcast = bool(caps and caps.supports_podcast)
        supports_photo = bool(caps and caps.supports_photo)

        cache = self.library_cache
        ipod_tracks = cache.get_tracks()
        track_edits = cache.get_track_edits()
        selected_track_paths = selected_paths
        selected_photo_imports = ()
        selected_playlist_paths = None
        if isinstance(selected_paths, dict):
            selected_track_paths = frozenset(selected_paths.get("tracks", ()))
            selected_photo_imports = tuple(selected_paths.get("photos", ()))
            selected_playlist_paths = frozenset(selected_paths.get("playlists", ()))

        photo_edits = (
            build_imported_photo_edit_state(selected_photo_imports)
            if supports_photo
            else None
        )
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
                pc_folder=primary_pc_folder,
                pc_folders=tuple(selected_folder_entries),
                ipod_tracks=ipod_tracks,
                ipod_path=device_manager.device_path or "",
                supports_video=supports_video,
                supports_podcast=supports_podcast,
                supports_photo=supports_photo,
                track_edits=track_edits,
                photo_edits=photo_edits,
                sync_workers=sync_workers,
                rating_strategy=rating_strategy,
                existing_playlists=_existing_playlist_rows_for_sync(cache),
                fpcalc_path=fpcalc_path,
                photo_sync_settings={
                    "rotate_tall_photos_for_device": (
                        settings.rotate_tall_photos_for_device
                    ),
                    "fit_photo_thumbnails": settings.fit_photo_thumbnails,
                },
                transcode_options=build_transcode_options(settings),
                allowed_paths=frozenset(selected_track_paths),
                selected_playlist_paths=selected_playlist_paths,
            )
        )
        worker = self._sync_worker
        worker.progress.connect(self.syncReview.update_progress)
        worker.finished.connect(
            lambda plan, w=worker: self._onSyncDiffComplete(plan, w)
        )
        worker.error.connect(
            lambda error, w=worker: self._onWorkerSyncError("_sync_worker", w, error)
        )
        worker.start()

    def _onSelectiveSyncCancelled(self):
        """User cancelled selective sync browser."""
        self._show_default_page()

    def _onSyncReviewEditSelection(self, selection_state: object) -> None:
        """Open the selective-sync shell as an alternate sync-plan editor."""

        if self._plan is None:
            return
        self.centralStack.setCurrentIndex(4)
        self.selectiveSyncBrowser.load_sync_plan(self._plan, selection_state)

    def _onPlanSelectionDone(self, selection_state: object) -> None:
        """Apply alternate plan-editor checks back to the sync review."""

        self.syncReview.apply_selection_state(selection_state)
        self.centralStack.setCurrentIndex(1)

    def _onPlanSelectionCancelled(self) -> None:
        """Return from alternate plan editor without changing review checks."""

        self.centralStack.setCurrentIndex(1)

    def _onSyncReviewCancelled(self) -> None:
        """Handle cancel from the sync review page.

        During sync execution we only request cancellation and keep the page
        visible so partial-save confirmation (save vs discard) can be shown.
        """
        if self._sync_execute_worker is not None and self._sync_execute_worker.isRunning():
            self._sync_execute_worker.requestInterruption()
            return
        self.hideSyncReview()

    def hideSyncReview(self):
        """Return to the main browsing view, stopping any background work."""
        self._keep_sync_results_visible_after_rescan = False
        self._cleanup_sync_diff_worker()
        self._cleanup_back_sync_worker()
        self._cleanup_podcast_plan_worker()
        self._cleanup_album_conversion_worker()
        self._cleanup_chapter_split_worker()
        self._cleanup_sync_execute_worker()
        self._show_default_page()

    def _cleanup_podcast_plan_worker(self):
        """Stop and detach any in-flight managed podcast planning worker."""
        self._cleanup_worker("_podcast_plan_worker", ("finished", "error"))

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
        entries = _media_folder_entries_from_settings(settings)
        if entries:
            self._last_pc_folder_entries = entries
            self._last_pc_folders = media_folder_paths(entries)
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
            QMessageBox.warning(self, _("No Device"), _("No iPod device selected."))
            return

        original_plan = self._plan  # stored in _onSyncDiffComplete

        selected_playlists = (
            self.syncReview.get_selected_playlist_changes()
            if original_plan
            else None
        )

        filtered_plan = build_filtered_sync_plan(
            original_plan,
            selected_items,
            selected_playlists=selected_playlists,
            selected_photo_plan=(
                self.syncReview.get_selected_photo_plan() if original_plan else None
            ),
        )

        if not filtered_plan.has_changes:
            return

        sync_until_full = self._confirm_sync_until_full_if_needed(
            filtered_plan,
            device_manager.device_path,
        )
        if sync_until_full is None:
            return

        # Show progress in sync review widget
        self.syncReview.show_executing()

        # Respect the user's pre-sync backup choice from the prompt
        skip_backup = getattr(self.syncReview, '_skip_presync_backup', False)

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
            backup_device_name=MainWindow._device_name_from_playlists(
                self.library_cache.get_playlists()
            ),
            device_info=device_session.identity,
            device_capabilities=device_session.capabilities,
            on_sync_complete=_on_sync_complete,
            sync_until_full=sync_until_full,
        )
        self._sync_execute_worker.progress.connect(self.syncReview.update_execute_progress)
        self._sync_execute_worker.finished.connect(self._onSyncExecuteComplete)
        self._sync_execute_worker.error.connect(self._onSyncExecuteError)
        self._sync_execute_worker.confirm_partial_save.connect(self._onConfirmPartialSave)
        # Allow the user to skip the in-progress backup from the progress screen
        self.syncReview.skip_backup_signal.connect(self._sync_execute_worker.request_skip_backup)
        self.syncReview.give_up_scrobble_signal.connect(self._sync_execute_worker.request_give_up_scrobble)
        self._sync_execute_worker.start()

    def _confirm_sync_until_full_if_needed(self, plan: Any, ipod_path: str) -> bool | None:
        """Return True for sync-until-full, False for normal sync, None to cancel."""

        try:
            disk = shutil.disk_usage(ipod_path)
        except OSError as exc:
            logger.warning("Could not check iPod free space before sync: %s", exc)
            return False

        required = sync_plan_required_free_bytes(plan)
        if required <= disk.free:
            return False

        shortage = max(0, required - disk.free)
        reserve_label = format_size(SYNC_UNTIL_FULL_RESERVE_BYTES) or "1 MB"
        message = _(
            "This sync is estimated to need more space than is available on "
            "the iPod.\n\n"
            "Available: {available}\n"
            "Estimated needed: {required}\n"
            "Estimated shortfall: {shortage}\n\n"
            "Sync Until Full will copy files in order until the next file would "
            "leave less than {reserve} free, then save the database with "
            "the items that actually synced."
        ).format(
            available=format_size(disk.free) or "0 B",
            required=format_size(required) or "0 B",
            shortage=format_size(shortage) or "0 B",
            reserve=reserve_label,
        )

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle(_("Not Enough Space"))
        dialog.setText(_("The selected sync is larger than the iPod's free space."))
        dialog.setInformativeText(message)
        cancel_btn = dialog.addButton(_("Cancel"), QMessageBox.ButtonRole.RejectRole)
        sync_btn = dialog.addButton(
            _("Sync Until Full"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        dialog.setDefaultButton(cancel_btn)
        dialog.exec()
        return True if dialog.clickedButton() is sync_btn else None

    def _onSyncExecuteComplete(self, result):
        """Called when sync execution is complete."""
        self._disconnect_skip_signal()
        # Show styled results view instead of a plain message box
        self.syncReview.show_result(result)
        self._keep_sync_results_visible_after_rescan = True
        failure_message = _sync_execute_failure_message(result)
        if failure_message:
            QMessageBox.critical(self, _("Sync Failed"), failure_message)

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

        QMessageBox.critical(self, _("Sync Error"), msg)
        self.hideSyncReview()

    def _onConfirmPartialSave(self, n_added: int, n_skipped: int) -> None:
        """Called from the sync worker when the user cancels mid-sync with tracks already copied.
        Shows a dialog asking whether to save the partial database, then unblocks the worker."""
        worker = getattr(self, '_sync_execute_worker', None)
        if worker is None:
            return

        tracks_word = _("track") if n_added == 1 else _("tracks")
        skipped_line = (
            (
                _("{count} more track was not copied.")
                if n_skipped == 1
                else _("{count} more tracks were not copied.")
            ).format(count=n_skipped)
            if n_skipped > 0 else ""
        )

        msg = QMessageBox(self)
        msg.setWindowTitle(_("Save Partial Sync?"))
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            _(
                "{count} {tracks_word} were successfully copied to your iPod "
                "before the sync was cancelled."
            ).format(count=n_added, tracks_word=tracks_word)
        )
        detail = _("Would you like to save these tracks to your iPod's database?")
        if skipped_line:
            detail = skipped_line + "\n\n" + detail
        detail += _(
            "\n\nIf you discard, the copied files will be cleaned up automatically the next time you sync."
        )
        msg.setInformativeText(detail)
        save_btn = msg.addButton(_("Save Partial Database"), QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton(_("Discard"), QMessageBox.ButtonRole.RejectRole)
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
        mime = a0.mimeData()
        if is_iopenpod_export_drag(mime):
            self._drop_overlay.hide_overlay()
            a0.ignore()
            return
        # Reject drops when no device is selected or sync is executing
        device = self.device_manager
        if not device.device_path:
            a0.ignore()
            return
        if self._sync_execute_worker and self._sync_execute_worker.isRunning():
            a0.ignore()
            return

        if mime and mime.hasUrls():
            caps = self.device_session_service.current_session().capabilities
            include_video = bool(caps.supports_video) if caps is not None else True
            include_photo = bool(caps.supports_photo) if caps is not None else True
            for url in mime.urls():
                if url.isLocalFile():
                    if is_media_drop_candidate(
                        Path(url.toLocalFile()),
                        include_video=include_video,
                        include_photo=include_photo,
                    ):
                        a0.acceptProposedAction()
                        self._drop_overlay.show_overlay()
                        return
        a0.ignore()

    def dragMoveEvent(self, a0):
        if a0 and is_iopenpod_export_drag(a0.mimeData()):
            self._drop_overlay.hide_overlay()
            a0.ignore()
        elif a0 and self._drop_overlay.isVisible():
            a0.acceptProposedAction()
        elif a0:
            a0.ignore()

    def dragLeaveEvent(self, a0):
        self._drop_overlay.hide_overlay()

    def dropEvent(self, a0):
        self._drop_overlay.hide_overlay()
        if a0 is None:
            return
        mime = a0.mimeData()
        if is_iopenpod_export_drag(mime):
            a0.ignore()
            return
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
        caps = self.device_session_service.current_session().capabilities
        supports_video = bool(caps.supports_video) if caps is not None else True
        supports_podcast = bool(caps.supports_podcast) if caps is not None else True
        supports_photo = bool(caps.supports_photo) if caps is not None else True
        dropped_files = collect_import_file_paths(
            paths,
            include_video=supports_video,
            include_photo=supports_photo,
            include_playlist=True,
        )
        if not dropped_files.has_files:
            return

        # Remember whether we already have a plan to merge into
        self._drop_merge = (
            self._plan is not None
            and self.centralStack.currentIndex() == 1
        )

        # Switch to sync review and show loading
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()
        self.syncReview.loading_label.setText(_("Reading dropped files..."))
        settings = self.settings_service.get_effective_settings()
        device_manager = self.device_manager

        # Run metadata reading in background thread
        self._drop_worker = DropScanWorker(
            list(dropped_files.track_paths),
            photo_imports=dropped_files.photo_imports,
            playlist_paths=dropped_files.playlist_paths,
            ipod_path=device_manager.device_path or "",
            supports_video=supports_video,
            supports_podcast=supports_podcast,
            supports_photo=supports_photo,
            photo_sync_settings={
                "rotate_tall_photos_for_device": (
                    settings.rotate_tall_photos_for_device
                ),
                "fit_photo_thumbnails": settings.fit_photo_thumbnails,
            },
        )
        self._drop_worker.finished.connect(self._on_drop_scan_complete)
        self._drop_worker.error.connect(self._onSyncError)
        self._drop_worker.start()

    def _on_drop_scan_complete(self, plan):
        """Merge dropped-file plan into any existing plan, then show."""
        if self._drop_merge and self._plan is not None:
            merge_additional_sync_plan(self._plan, plan)
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
        back_sync_workers = list(getattr(self, "_back_sync_workers", []))
        if (
            self._back_sync_worker is not None
            and self._back_sync_worker not in back_sync_workers
        ):
            back_sync_workers.append(self._back_sync_worker)
        for worker in back_sync_workers:
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(3000)
        if self._podcast_plan_worker and self._podcast_plan_worker.isRunning():
            self._podcast_plan_worker.requestInterruption()
            self._podcast_plan_worker.wait(3000)
        if self._album_conversion_worker and self._album_conversion_worker.isRunning():
            self._album_conversion_worker.requestInterruption()
            self._album_conversion_worker.wait(3000)
        if self._chapter_split_worker and self._chapter_split_worker.isRunning():
            self._chapter_split_worker.requestInterruption()
            self._chapter_split_worker.wait(3000)
        if self._sync_execute_worker and self._sync_execute_worker.isRunning():
            self._sync_execute_worker.requestInterruption()
            self._sync_execute_worker.wait(3000)
        for worker in list(getattr(self, "_cancelled_workers", [])):
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(3000)
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
        self.setWindowTitle(_("Missing Tools"))
        self.setFixedWidth(420)
        _apply_dialog_background(self)

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

        title = QLabel(_("{tools} Not Found").format(tools=tool_list))
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        layout.addSpacing(4)

        if can_download:
            body = QLabel(
                _(
                    "iOpenPod can download these automatically (~80 MB).\n"
                    "Download now?"
                )
            )
        else:
            body = QLabel(detail_lines)
        body.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        body.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        layout.addWidget(body)

        layout.addSpacing(12)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        if can_download:
            no_btn = QPushButton(_("Not Now"))
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

            yes_btn = QPushButton(_("Download"))
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
            ok_btn = QPushButton(_("OK"))
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

        layout.addLayout(btn_row)


class _DownloadProgressDialog(QDialog):
    """Dark-themed modal progress dialog for downloading tools."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle(_("Downloading"))
        self.setFixedSize((380), (180))
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowCloseButtonHint  # type: ignore[operator]
        )
        _apply_dialog_background(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins((28), (24), (28), (24))
        layout.setSpacing(14)

        title = QLabel(_("Downloading Tools…"))
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.Bold))
        title.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._status = QLabel(_("Preparing download…"))
        self._status.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._status.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
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
