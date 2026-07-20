# ruff: noqa: I001
import logging
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Keep this before PyQt imports so Qt Multimedia logging rules are installed
# before any Qt module can initialize multimedia plugins.
from iopenpod.application.qt_runtime import quiet_native_stderr

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSlot
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

from iopenpod.application.context import create_app_context
from iopenpod.application.controllers import (
    QuickWriteController,
    StartupDeviceRestoreController,
    StartupUpdateController,
)
from iopenpod.application.database_storage import analyze_database_storage
from iopenpod.application.device_access import DeviceWriteAccessResult, check_ipod_write_access
from iopenpod.application.device_identity import (
    identify_ipod_at_root,
    refresh_device_disk_usage,
    resolve_device_image_filename,
)
from iopenpod.device.recovery import (
    LinuxFilesystemRecoveryPlan,
    linux_filesystem_recovery_plan,
)
from iopenpod.application.dropped_files import collect_import_file_paths, is_media_drop_candidate
from iopenpod.application.jobs import (
    AlbumConversionRequest,
    AlbumConversionWorker,
    BackSyncRequest,
    BackSyncWorker,
    ChapterSplitRequest,
    ChapterSplitWorker,
    check_sync_tool_availability,
    DropScanWorker,
    EjectDeviceWorker,
    QuickWriteWorker,
    SyncToolAvailability,
    ToolDownloadWorker,
)
from iopenpod.application.runtime import (
    ThreadPoolSingleton,
    Worker,
    build_album_list,
    same_device_path,
)
from iopenpod.application.sync_plan_builder import build_removal_sync_plan
from iopenpod.application.sync_plan_merge import merge_additional_sync_plan
from iopenpod.application.sync_session import (
    PodcastPlanningInput,
    SyncExecutionIntent,
    SyncPlanningIntent,
    SyncSessionBlocked,
    SyncSessionController,
    SyncSessionMissingTools,
)
from iopenpod.device import has_exact_model_number
from iopenpod.gui.device_warnings import show_unidentified_ipod_warning
from iopenpod.gui.glyphs import glyph_pixmap
from iopenpod.gui.internal_drag import is_iopenpod_export_drag
from iopenpod.gui.notifications import Notifier
from iopenpod.gui.styles import FONT_FAMILY, Colors, Metrics, accent_btn_css, button_css, progress_bar_css
from iopenpod.gui.widgets.backupBrowser import BackupBrowserWidget
from iopenpod.gui.widgets.databaseStorageBrowser import DatabaseStorageBrowser
from iopenpod.gui.widgets.dropOverlay import DropOverlayWidget
from iopenpod.gui.widgets.formatters import format_size
from iopenpod.gui.widgets.musicBrowser import MusicBrowser
from iopenpod.gui.widgets.musicPlayer import MusicPlayerBar
from iopenpod.gui.widgets.settingsPage import SettingsPage
from iopenpod.gui.widgets.sidebar import Sidebar
from iopenpod.gui.widgets.syncReview import (
    PCFolderDialog,
    SyncReviewWidget,
)
from iopenpod.infrastructure.media_folders import (
    media_folder_entries_to_settings,
    media_folder_paths,
)
from iopenpod.infrastructure.settings_schema import (
    PLAYER_POSITION_TOP,
    normalize_player_position,
)
from iopenpod.sync.contracts import (
    SYNC_UNTIL_FULL_RESERVE_BYTES,
    SyncPlan,
    sync_plan_required_free_bytes,
)
from iopenpod.sync.review_selection import build_filtered_sync_plan

if TYPE_CHECKING:
    from iopenpod.application.context import AppContext
    from iopenpod.application.services import (
        DeviceManagerLike,
        DeviceStorageSnapshot,
        LibraryCacheLike,
    )

logger = logging.getLogger(__name__)

_DATABASE_STORAGE_PAGE_INDEX = 5


def _database_file_size_bytes(
    path: str | None,
    *,
    uses_sqlite_db: bool = False,
) -> int:
    if not path:
        return 0
    try:
        data = Path(path).read_bytes()
    except OSError:
        return 0
    if uses_sqlite_db:
        return len(data)
    from iopenpod.itunesdb_parser.parser import decompress_itunescdb

    return len(decompress_itunescdb(data))


def _mhsd5_type_value(playlist: dict) -> int:
    try:
        return int(playlist.get("mhsd5_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


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


def _linux_recovery_guidance(plan: LinuxFilesystemRecoveryPlan) -> str:
    """Render conservative recovery copy from device-layer mount facts."""
    lines = [
        "On Linux, reconnect the iPod first. If it remains read-only, do not "
        "force or remount it read-write; that can worsen filesystem damage.",
        "",
    ]
    if plan.source or plan.filesystem:
        lines.extend([
            "Detected mount: "
            f"{plan.source or 'unknown device'} "
            f"({plan.filesystem or 'unknown filesystem'}).",
            "",
        ])
    lines.extend([
        "Unmount it before running any filesystem check:",
        f"  {plan.unmount_command}",
        "",
    ])

    if not plan.source or not plan.filesystem:
        lines.extend([
            "Identify the exact device and filesystem before choosing a checker:",
            f"  {plan.identify_command}",
            "",
        ])

    if plan.kind == "fat":
        if plan.checker_command:
            lines.extend([
                "For FAT, start with a read-only check:",
                f"  {plan.checker_command}",
                "Review the result and back up recoverable data before choosing a repair mode.",
            ])
        else:
            lines.append(
                "For FAT, use fsck.fat only after substituting the exact unmounted device; "
                "start with its non-writing (-n) mode."
            )
    elif plan.kind == "exfat":
        if plan.checker_command:
            lines.extend([
                "For exFAT, start with a read-only check:",
                f"  {plan.checker_command}",
                "Review the result and back up recoverable data before choosing a repair mode.",
            ])
        else:
            lines.append(
                "For exFAT, identify the exact unmounted device and start with "
                "fsck.exfat's non-writing (-n) mode."
            )
    elif plan.kind == "mac":
        lines.append(
            "This is a Mac-formatted iPod. Do not run a FAT checker or force Linux "
            "write access; check or repair it on macOS with Disk Utility First Aid."
        )
    elif plan.kind == "ntfs":
        lines.append(
            "For NTFS, keep it unmounted on Linux and use Windows drive Error Checking "
            "or chkdsk after backing up recoverable data."
        )
    else:
        lines.append(
            "Use only the checker that matches the detected filesystem and exact device. "
            "Do not run a checker while the iPod is mounted."
        )

    return "\n".join(lines)


def _filesystem_recovery_guidance(
    mount_path: str,
    *,
    filesystem: str = "",
    source: str = "",
) -> str:
    """Render conservative recovery steps for the host operating system."""
    if sys.platform.startswith("linux"):
        return _linux_recovery_guidance(
            linux_filesystem_recovery_plan(
                mount_path,
                filesystem=filesystem,
                source=source,
            )
        )

    detected = ""
    if filesystem or source:
        detected = (
            "\n\nDetected volume: "
            f"{source or mount_path} ({filesystem or 'unknown filesystem'})."
        )

    if sys.platform == "darwin":
        return (
            "On macOS, reconnect the iPod first. If it remains read-only or "
            "reports I/O errors, stop syncing and do not force it to mount "
            "read-write."
            f"{detected}\n\n"
            "Use Disk Utility First Aid on the exact iPod volume. Back up any "
            "recoverable data first, and keep iOpenPod and other media apps "
            "closed while the check runs."
        )

    if sys.platform == "win32":
        return (
            "On Windows, reconnect the iPod first. If it remains read-only or "
            "reports I/O errors, stop syncing and do not format the volume as "
            "a shortcut."
            f"{detected}\n\n"
            "Run Windows drive Error Checking (Properties > Tools) against the "
            "exact iPod drive, with iOpenPod and iTunes closed. If the iPod "
            "database or filesystem cannot be recovered, back up what you can "
            "before using iTunes Restore."
        )

    return (
        "Reconnect the iPod first. If it remains read-only or reports I/O "
        "errors, stop syncing and do not force write access."
        f"{detected}\n\n"
        "Use only your operating system's filesystem checker for the exact "
        "iPod volume, after backing up any recoverable data."
    )


def _device_write_access_failure_message(access: DeviceWriteAccessResult) -> str:
    mount_path = access.mount_path or "the iPod mount"
    filesystem = access.mount.filesystem if access.mount is not None else ""
    source = access.mount.source if access.mount is not None else ""
    lines = [
        "iOpenPod cannot use this iPod because it is not writable.",
        "",
        f"Mount path: {mount_path}",
    ]
    if access.mount is not None:
        lines.append(f"Mount: {access.mount.summary}")
    lines.extend([
        f"System error: {access.reason or 'write access check failed'}",
        "",
        _filesystem_recovery_guidance(
            mount_path,
            filesystem=filesystem,
            source=source,
        ),
    ])
    return "\n".join(lines)


def _coerce_positive_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value) or None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        result = int(value)
        return result if result > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            result = int(text)
        except ValueError:
            return None
        return result if result > 0 else None
    return None


def _track_artwork_id(track: dict) -> int | None:
    for key in ("artwork_id_ref", "mhii_link", "mhiiLink"):
        artwork_id = _coerce_positive_int(track.get(key))
        if artwork_id is not None:
            return artwork_id
    return None


def _playback_track_path_for_session(session: object, track: dict) -> str:
    ipod_root = str(getattr(session, "device_path", "") or "")
    if not ipod_root:
        return ""

    from iopenpod.sync.ipod_track_paths import existing_ipod_track_file_path

    path = existing_ipod_track_file_path(
        ipod_root,
        track,
        allow_music_filename_fallback=True,
    )
    return str(path) if path is not None else ""


def _sync_execute_failure_message(result: Any, mount_path: str = "") -> str | None:
    """Return the message that should be shown for a failed sync result."""
    if getattr(result, "success", True) or getattr(result, "partial_save", False):
        return None

    errors = list(getattr(result, "errors", []) or [])
    if not errors:
        return "Sync failed before making changes."

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
    if prioritized is not None:
        mount = mount_path.strip() or "the iPod mount"
        return (
            "iOpenPod cannot write to this iPod.\n\n"
            f"Mount path: {mount}\n"
            f"System error: {text or 'write access check failed'}\n\n"
            + _filesystem_recovery_guidance(mount)
        )
    return text or "Sync failed before making changes."


def _library_load_failure_message(mount_path: str, error_msg: str) -> str:
    error_text = error_msg.strip() or "Unknown error"
    if not _looks_like_device_access_error(error_text):
        return f"iOpenPod could not load this iPod library.\n\n{error_text}"

    mount = mount_path.strip() or "the iPod mount"
    return (
        "iOpenPod could not read this iPod cleanly.\n\n"
        f"Mount path: {mount}\n"
        f"System error: {error_text}\n\n"
        + _filesystem_recovery_guidance(mount)
    )


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
        self._back_sync_worker = None
        self._back_sync_workers = []
        self._cancelled_workers = []
        self._podcast_plan_worker = None
        self._subsonic_plan_worker = None
        self._pending_tool_sync_intent: SyncPlanningIntent | None = None
        self._pending_tool_download_callback: Callable[[], None] | None = None
        self._album_conversion_worker = None
        self._chapter_split_worker = None
        self._tool_download_worker = None
        self._media_player: Any | None = None
        self._audio_output: Any | None = None
        self._multimedia_unavailable_logged = False
        self._playback_tracks: list[dict] = []
        self._playback_index = -1
        self._player_artwork_token = 0
        self._player_artwork_worker: Any | None = None
        self._keep_sync_results_visible_after_rescan = False
        self._normalize_tags_after_sync_pending = False
        self._tag_fix_scan_generation = 0
        self._tag_fix_scan_worker: Worker | None = None
        self._plan: SyncPlan | None = None
        self._last_pc_folder_entries = _media_folder_entries_from_settings(settings)
        self._last_pc_folders = media_folder_paths(self._last_pc_folder_entries)
        self._last_device_path = settings.last_device_path or ""
        self._startup_restore = StartupDeviceRestoreController(
            self.device_manager,
            self._last_device_path,
            self,
        )
        self._startup_restore.identification_rejected.connect(
            self._on_unidentified_ipod
        )
        self._startup_updates = StartupUpdateController(
            self._create_update_checker,
            self,
        )
        self._library_view_device_path: str | None = None

        # Eject worker (safe-unmount off the UI thread)
        self._eject_worker: EjectDeviceWorker | None = None
        self._eject_only_device_path: str | None = None
        self._eject_only_device_storage: DeviceStorageSnapshot | None = None

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

        self._tag_fix_scan_timer = QTimer(self)
        self._tag_fix_scan_timer.setSingleShot(True)
        self._tag_fix_scan_timer.setInterval(120)
        self._tag_fix_scan_timer.timeout.connect(self._start_tag_fix_scan)

        # Root shell: current app stack plus a dockable player bar.
        self.appShell = QWidget()
        self.appShellLayout = QVBoxLayout(self.appShell)
        self.appShellLayout.setContentsMargins(0, 0, 0, 0)
        self.appShellLayout.setSpacing(0)

        self.centralStack = QStackedWidget()
        self.appShellLayout.addWidget(self.centralStack, 1)

        self.musicPlayer = MusicPlayerBar()
        self.musicPlayer.close_requested.connect(lambda: self.setPlayerActive(False))
        self.musicPlayer.play_pause_requested.connect(self._onPlayerPlayPauseRequested)
        self.musicPlayer.previous_requested.connect(self._playPreviousTrack)
        self.musicPlayer.next_requested.connect(self._playNextTrack)
        self.musicPlayer.seek_requested.connect(self._seekPlayer)
        self.musicPlayer.rating_changed.connect(self._onPlayerRatingChanged)
        self.musicPlayer.volume_changed.connect(self._onPlayerVolumeChanged)
        self.musicPlayer.setVisible(False)
        self.appShellLayout.addWidget(self.musicPlayer, 0)
        self._apply_player_position()

        self.setCentralWidget(self.appShell)

        # Build all child widgets and connect signals
        self._build_ui()
        self._sync_session = SyncSessionController(
            self.device_manager,
            self.library_cache,
            self.settings_service,
            self.device_session_service,
            self._quick_write_controller,
            podcast_input_provider=self._current_podcast_planning_input,
            parent=self,
        )
        self._sync_session.blocked.connect(self._on_sync_session_blocked)
        self._sync_session.missing_tools.connect(self._on_sync_session_missing_tools)
        self._sync_session.planning_started.connect(
            self._on_sync_session_planning_started
        )
        self._connect_sync_session_review_signals()
        self._sync_session.plan_ready.connect(self._onSyncDiffComplete)
        self._sync_session.plan_failed.connect(self._onSyncError)
        self._sync_session.execution_complete.connect(self._onSyncExecuteComplete)
        self._sync_session.execution_failed.connect(self._onSyncExecuteError)
        self._sync_session.partial_save_requested.connect(self._onConfirmPartialSave)
        self.syncReview.skip_backup_signal.connect(self._sync_session.request_skip_backup)
        self.syncReview.give_up_scrobble_signal.connect(
            self._sync_session.request_give_up_scrobble
        )
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
        self.library_cache.tracks_changed.connect(self._schedule_tag_fix_scan)

        # Instant playlist sync whenever playlists are added/edited via context menu
        self.library_cache.playlist_quick_sync.connect(
            self._quick_write_controller.schedule_playlist_sync
        )

        self._show_default_page()
        self._startup_restore.start_later(100)
        self._startup_updates.update_available.connect(
            self._handle_startup_update_result
        )
        self._startup_updates.start_later(2000)

    @pyqtSlot(object)
    def _handle_startup_update_result(self, result: object) -> None:
        """Route startup results to the current, potentially rebuilt settings page."""

        self.settingsPage._handle_update_result(result)

    @staticmethod
    def _create_update_checker(parent):
        """Create the existing GUI update checker for the app-core controller."""
        from iopenpod.gui.auto_updater import UpdateChecker

        return UpdateChecker(parent)

    @staticmethod
    def _device_name_from_playlists(playlists: list[dict]) -> str:
        for playlist in playlists:
            if playlist.get("master_flag") and not _is_ipod_category_playlist(playlist):
                return str(playlist.get("Title") or "").strip()
        return ""

    def _current_podcast_planning_input(self) -> PodcastPlanningInput | None:
        browser = self.musicBrowser.podcastBrowser
        store = browser._store
        feeds = store.get_feeds() if store else []
        if not store or not feeds:
            return None
        return PodcastPlanningInput(feeds=tuple(feeds), store=store)

    def _on_sync_session_blocked(self, blocked: SyncSessionBlocked) -> None:
        if blocked.reason == "quick_changes_saving":
            label = blocked.label or "quick changes"
            QMessageBox.warning(
                self,
                "Quick Changes Still Saving",
                (
                    "iOpenPod is still saving pending quick changes. "
                    f"Please wait for {label} to finish before starting a full sync."
                ),
            )
            return
        if blocked.reason == "library_loading":
            QMessageBox.information(
                self,
                "Library Loading",
                "Please wait for the iPod library to finish loading.",
            )
            return
        if blocked.reason == "no_device":
            QMessageBox.warning(self, "No Device", "No iPod device selected.")
            return
        if blocked.reason == "busy":
            QMessageBox.information(
                self,
                "Sync Running",
                "Please wait for the current sync to finish.",
            )

    def _on_sync_session_missing_tools(
        self,
        missing: SyncSessionMissingTools,
    ) -> None:
        tools = missing.availability
        if tools.can_download:
            dlg = _MissingToolsDialog(self, tools.tool_list, can_download=True)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                execution_intent = missing.execution_intent
                if execution_intent is not None:
                    def resume_execution() -> None:
                        self._sync_session.start_execution(execution_intent)

                    self._download_missing_tools_then_sync(
                        tools.missing_ffmpeg,
                        tools.missing_fpcalc,
                        completion_callback=resume_execution,
                    )
                    return
                self._download_missing_tools_then_sync(
                    tools.missing_ffmpeg,
                    tools.missing_fpcalc,
                    missing.planning_intent,
                )
            return

        dlg = _MissingToolsDialog(
            self,
            tools.tool_list,
            can_download=False,
            detail_lines=tools.install_help_text,
        )
        dlg.exec()

    def _on_sync_session_planning_started(self) -> None:
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()

    def _connect_sync_session_review_signals(self) -> None:
        """Route session updates to whichever review widget is currently active."""

        self._sync_session.planning_progress.connect(
            self._on_sync_session_planning_progress
        )
        self._sync_session.execution_started.connect(
            self._on_sync_session_execution_started
        )
        self._sync_session.execution_progress.connect(
            self._on_sync_session_execution_progress
        )

    def _on_sync_session_planning_progress(
        self,
        stage: str,
        current: int,
        total: int,
        message: str,
    ) -> None:
        self.syncReview.update_progress(stage, current, total, message)

    def _on_sync_session_execution_started(self) -> None:
        self.syncReview.show_executing()

    def _on_sync_session_execution_progress(self, progress: object) -> None:
        self.syncReview.update_execute_progress(progress)

    def _build_ui(self):
        """Create child widgets and wire up signals.

        Called once from ``__init__`` and again by ``_on_theme_changed``
        to rebuild the UI with fresh themed styles.
        """
        s = self.settings_service.get_effective_settings()
        Metrics.apply_grid_item_scale(getattr(s, "grid_item_size", "large"))

        # Main browsing page
        self.mainWidget = QWidget()
        self.mainLayout = QHBoxLayout(self.mainWidget)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        self.musicBrowser = MusicBrowser(
            settings_service=self.settings_service,
            device_sessions=self.device_session_service,
            libraries=self.library_service,
        )
        self.musicBrowser.podcastBrowser.podcast_sync_requested.connect(self._onPodcastSyncRequested)
        self.musicBrowser.album_conversion_requested.connect(self._onAlbumConversionRequested)
        self.musicBrowser.playback_requested.connect(self._onTrackPlaybackRequested)
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
        self.sidebar.subsonicSyncButton.clicked.connect(self.startSubsonicSync)
        self.sidebar.settingsButton.clicked.connect(self.showSettings)
        self.sidebar.backupButton.clicked.connect(self.showBackupBrowser)
        self.sidebar.tag_fixes_requested.connect(self._onIpodTagFixesRequested)
        self.sidebar.manage_storage_requested.connect(self.showDatabaseStorage)

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
        self.settingsPage.player_position_changed.connect(self._apply_player_position)
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
        from iopenpod.gui.widgets.selectiveSyncBrowser import SelectiveSyncBrowser
        self.selectiveSyncBrowser = SelectiveSyncBrowser(
            settings_service=self.settings_service,
            device_sessions=self.device_session_service,
        )
        self.selectiveSyncBrowser.selection_done.connect(self._onSelectiveSyncDone)
        self.selectiveSyncBrowser.cancelled.connect(self._onSelectiveSyncCancelled)
        self.selectiveSyncBrowser.plan_selection_done.connect(self._onPlanSelectionDone)
        self.selectiveSyncBrowser.plan_selection_cancelled.connect(self._onPlanSelectionCancelled)
        self.centralStack.addWidget(self.selectiveSyncBrowser)  # Index 4

        # Database storage page
        self.databaseStorageBrowser = DatabaseStorageBrowser()
        self.databaseStorageBrowser.closed.connect(self.hideDatabaseStorage)
        self.centralStack.addWidget(self.databaseStorageBrowser)  # Index 5

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
        select_btn.setStyleSheet(accent_btn_css("lg"))
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

    def _current_player_position(self) -> str:
        try:
            settings = self.settings_service.get_effective_settings()
        except Exception:
            return PLAYER_POSITION_TOP
        return normalize_player_position(
            getattr(settings, "player_position", PLAYER_POSITION_TOP)
        )

    def _apply_player_position(self) -> None:
        position = self._current_player_position()
        if self.appShellLayout.indexOf(self.musicPlayer) >= 0:
            self.appShellLayout.removeWidget(self.musicPlayer)
        if hasattr(self.musicPlayer, "setDockPosition"):
            self.musicPlayer.setDockPosition(position)
        insert_at = 0 if position == PLAYER_POSITION_TOP else self.appShellLayout.count()
        self.appShellLayout.insertWidget(insert_at, self.musicPlayer, 0)

    def setPlayerActive(self, active: bool) -> None:
        self.musicPlayer.setVisible(bool(active))
        if not active:
            self._stopPlayback()

    def _onTrackPlaybackRequested(
        self,
        track: dict,
        tracks: list,
        index: int,
    ) -> None:
        playback_tracks = [
            candidate
            for candidate in tracks
            if isinstance(candidate, dict)
        ] or [track]
        if not (0 <= index < len(playback_tracks)):
            try:
                index = playback_tracks.index(track)
            except ValueError:
                index = 0
        self._playback_tracks = playback_tracks
        self._playTrackAtIndex(index)

    def _ensureMediaPlayer(self) -> bool:
        if self._media_player is not None:
            return True

        try:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError as exc:
            if not self._multimedia_unavailable_logged:
                logger.warning("QtMultimedia is unavailable: %s", exc)
                self._multimedia_unavailable_logged = True
            self._notifyPlaybackIssue(
                "Playback unavailable",
                "This iOpenPod build does not include Qt multimedia playback.",
            )
            self.musicPlayer.setPlaying(False)
            return False

        try:
            self._audio_output = QAudioOutput(self)
            self._audio_output.setVolume(self.musicPlayer.volumePercent() / 100)
            self._media_player = QMediaPlayer(self)
            self._media_player.setAudioOutput(self._audio_output)
            self._media_player.positionChanged.connect(self.musicPlayer.setPosition)
            self._media_player.durationChanged.connect(self.musicPlayer.setDuration)
            self._media_player.playbackStateChanged.connect(self._onPlayerStateChanged)
            self._media_player.mediaStatusChanged.connect(self._onPlayerMediaStatusChanged)
            self._media_player.errorOccurred.connect(self._onPlayerError)
            return True
        except Exception as exc:
            logger.warning("Failed to initialize Qt multimedia playback: %s", exc)
            self._media_player = None
            self._audio_output = None
            self._notifyPlaybackIssue(
                "Playback unavailable",
                "iOpenPod could not initialize local playback for this session.",
            )
            self.musicPlayer.setPlaying(False)
            return False

    def _playTrackAtIndex(self, index: int) -> None:
        if not (0 <= index < len(self._playback_tracks)):
            return

        track = self._playback_tracks[index]
        if self._media_player is not None:
            self._media_player.stop()
        self._playback_index = index
        self.musicPlayer.setTrack(track)
        self._refreshPlayerQueueControls()
        self.setPlayerActive(True)
        self._loadPlayerArtwork(track)

        try:
            session = self.device_session_service.current_session()
        except Exception:
            session = None
        path = _playback_track_path_for_session(session, track) if session else ""
        if not path:
            self.musicPlayer.setPlaying(False)
            self._notifyPlaybackIssue(
                "Track file not found",
                "iOpenPod could not find this track's audio file on the iPod.",
            )
            return

        if not self._ensureMediaPlayer():
            return

        player = self._media_player
        if player is None:
            return
        try:
            with quiet_native_stderr():
                player.setSource(QUrl.fromLocalFile(path))
            player.play()
        except Exception as exc:
            self.musicPlayer.setPlaying(False)
            logger.warning("Playback could not start for %s: %s", path, exc)
            self._notifyPlaybackIssue(
                "Playback failed",
                "iOpenPod could not start playback for the selected track.",
            )

    def _refreshPlayerQueueControls(self) -> None:
        self.musicPlayer.setTransportAvailability(
            self._playback_index > 0,
            0 <= self._playback_index < len(self._playback_tracks) - 1,
        )
        self.musicPlayer.setQueueContext(
            self._playback_index,
            len(self._playback_tracks),
        )

    def _onPlayerPlayPauseRequested(self, should_play: bool) -> None:
        if should_play:
            if self._media_player is None:
                if 0 <= self._playback_index < len(self._playback_tracks):
                    self._playTrackAtIndex(self._playback_index)
                else:
                    self.musicPlayer.setPlaying(False)
                return
            self._media_player.play()
            return

        if self._media_player is not None:
            self._media_player.pause()

    def _seekPlayer(self, position_ms: int) -> None:
        if self._media_player is not None:
            self._media_player.setPosition(max(0, int(position_ms)))

    def _onPlayerRatingChanged(self, rating: int) -> None:
        if not (0 <= self._playback_index < len(self._playback_tracks)):
            return

        track = self._playback_tracks[self._playback_index]
        if not isinstance(track, dict):
            return

        cache = self.library_cache
        if not cache.is_ready():
            return

        cache.update_track_flags([track], {"rating": max(0, min(100, int(rating)))})

    def _onPlayerVolumeChanged(self, percent: int) -> None:
        if self._audio_output is None:
            return
        volume = max(0, min(100, int(percent))) / 100
        self._audio_output.setVolume(volume)

    def _playPreviousTrack(self) -> None:
        if self._playback_index > 0:
            self._playTrackAtIndex(self._playback_index - 1)

    def _playNextTrack(self) -> None:
        if self._playback_index < len(self._playback_tracks) - 1:
            self._playTrackAtIndex(self._playback_index + 1)

    def _stopPlayback(self) -> None:
        if self._media_player is not None:
            self._media_player.stop()
            self._media_player.setSource(QUrl())
        self.musicPlayer.setPlaying(False)

    def _onPlayerStateChanged(self, state) -> None:
        try:
            from PyQt6.QtMultimedia import QMediaPlayer

            playing = state == QMediaPlayer.PlaybackState.PlayingState
        except ImportError:
            playing = str(state).endswith("PlayingState")
        self.musicPlayer.setPlaying(playing)

    def _onPlayerMediaStatusChanged(self, status) -> None:
        try:
            from PyQt6.QtMultimedia import QMediaPlayer

            ended = status == QMediaPlayer.MediaStatus.EndOfMedia
        except ImportError:
            ended = str(status).endswith("EndOfMedia")
        if ended:
            if self._playback_index < len(self._playback_tracks) - 1:
                self._playNextTrack()
            else:
                self.musicPlayer.setPlaying(False)

    def _onPlayerError(self, error, error_string: str = "") -> None:
        try:
            from PyQt6.QtMultimedia import QMediaPlayer

            if error == QMediaPlayer.Error.NoError:
                return
        except ImportError:
            if str(error).endswith("NoError"):
                return

        self.musicPlayer.setPlaying(False)
        message = error_string or "The selected track could not be played."
        logger.warning("Playback failed: %s", message)
        self._notifyPlaybackIssue("Playback failed", message)

    def _loadPlayerArtwork(self, track: dict) -> None:
        self._player_artwork_token += 1
        token = self._player_artwork_token
        artwork_id = _track_artwork_id(track)
        if artwork_id is None:
            self.musicPlayer.setArtworkData(None)
            return

        try:
            session = self.device_session_service.current_session()
            artworkdb_path = session.artworkdb_path or ""
            artwork_folder = session.artwork_folder_path or ""
        except Exception:
            self.musicPlayer.setArtworkData(None)
            return

        if not artworkdb_path or not artwork_folder:
            self.musicPlayer.setArtworkData(None)
            return

        sharpen = bool(
            getattr(self.settings_service.get_effective_settings(), "sharpen_artwork", True)
        )
        worker = Worker(
            self._loadPlayerArtworkData,
            artwork_id,
            artworkdb_path,
            artwork_folder,
            sharpen,
        )
        self._player_artwork_worker = worker
        worker.signals.result.connect(
            lambda result, request_token=token: self._onPlayerArtworkLoaded(
                result,
                request_token,
            )
        )
        worker.signals.error.connect(
            lambda _error, request_token=token: self._onPlayerArtworkLoaded(
                None,
                request_token,
            )
        )
        ThreadPoolSingleton.get_instance().start(worker)

    @staticmethod
    def _loadPlayerArtworkData(
        artwork_id: int,
        artworkdb_path: str,
        artwork_folder: str,
        sharpen: bool,
    ) -> tuple[int, int, bytes] | None:
        if not Path(artworkdb_path).exists() or not Path(artwork_folder).exists():
            return None

        from iopenpod.gui.artwork_rendering import enhance_artwork_image
        from iopenpod.gui.imgMaker import configure_artwork_api, get_artwork

        configure_artwork_api(artworkdb_path, artwork_folder)
        image = get_artwork(int(artwork_id), mode="image_only")
        if image is None:
            return None
        image = enhance_artwork_image(image, enabled=sharpen).convert("RGBA")
        return image.width, image.height, image.tobytes("raw", "RGBA")

    def _onPlayerArtworkLoaded(
        self,
        result: tuple[int, int, bytes] | None,
        request_token: int,
    ) -> None:
        if request_token != self._player_artwork_token:
            return
        self.musicPlayer.setArtworkData(result)

    def _notifyPlaybackIssue(self, title: str, message: str) -> None:
        """Surface a playback problem without blocking the UI."""
        notifier = getattr(self, "_notifier", None)
        if notifier is not None:
            try:
                notifier.notify(title, message)
                return
            except Exception:
                logger.debug("Playback notification failed", exc_info=True)
        logger.warning("%s: %s", title, message)

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
        from iopenpod.gui.styles import app_stylesheet, build_palette

        if restore_page is None:
            restore_page = self.centralStack.currentIndex()

        self.setUpdatesEnabled(False)
        try:
            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
                app.setPalette(build_palette())
                app.setStyleSheet(app_stylesheet())
            self.musicPlayer.refreshStyle()

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
            if self._eject_only_device_path:
                self.sidebar.setEjectAvailable(True)
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
        from iopenpod.gui.widgets.devicePicker import DevicePickerDialog

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

                if not has_exact_model_number(selected_ipod):
                    self._on_unidentified_ipod(folder, selected_ipod)
                    return

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
                    "Invalid iPod Folder",
                    "The selected folder does not appear to be a valid iPod root.\n\n"
                    "Expected structure:\n"
                    "  <selected folder>/iPod_Control/iTunes/\n\n"
                    "Please select the root folder of your iPod."
                )

    @pyqtSlot(str, object)
    def _on_unidentified_ipod(self, _path: str, ipod: object) -> None:
        """Warn without activating an iPod whose exact model is unknown."""
        show_unidentified_ipod_warning(self, ipod)

    def onDeviceChanged(self, path: str):
        """Handle device selection - start loading data."""
        if not path or same_device_path(path, self.device_manager.device_path):
            self._eject_only_device_path = None
            self._eject_only_device_storage = None
        self._normalize_tags_after_sync_pending = False
        self._invalidate_tag_fix_scan()
        # Cancel any pending style rebuild from a prior device before starting
        # a new load cycle.
        if hasattr(self, "setPlayerActive"):
            self.setPlayerActive(False)
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
                message = _device_write_access_failure_message(access)
                logger.error("Selected iPod is not writable: %s", access.reason)
                if same_device_path(path, self.device_manager.device_path):
                    eject_storage = self.device_session_service.current_session().storage
                    # Keep this mount only as an eject candidate. Clearing the
                    # active device prevents every library and write action;
                    # DeviceManager synchronously emits onDeviceChanged("") here.
                    self.device_manager.device_path = None
                    self._eject_only_device_path = path
                    self._eject_only_device_storage = eject_storage
                    self.sidebar.setEjectAvailable(True)
                QMessageBox.critical(self, "iPod Not Writable", message)
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
        self._notifier.notify(
            "Device Settings Not Loaded",
            f"iOpenPod left the on-iPod settings file unchanged. {error}",
        )
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

        from iopenpod.itunesdb_shared.constants import get_version_name
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
            or "Unk iPod"
        )
        model = device_identity.display_name if device_identity else "Unk iPod"

        db_version_hex = db_data.get('VersionHex', '') if db_data else ''
        db_version_name = get_version_name(db_version_hex) if db_version_hex else ''
        database_id = db_data.get('DatabaseID', 0) if db_data else 0
        database_path = getattr(session, "itunesdb_path", None)
        capabilities = getattr(session, "capabilities", None)

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
            database_size_bytes=_database_file_size_bytes(
                database_path,
                uses_sqlite_db=bool(
                    getattr(capabilities, "uses_sqlite_db", False)
                ),
            ),
            max_database_bytes=int(
                getattr(capabilities, "max_database_bytes", 0) or 0
            ),
            database_path=database_path or "",
        )
        self.sidebar.setTagFixesAvailable(bool(tracks))
        self._update_sidebar_visibility(classified)
        self.musicBrowser.browserTrack.clearTable(clear_cache=True)
        self._update_podcast_statuses()
        self.musicBrowser.onDataReady()
        self._schedule_tag_fix_scan()

    def onDataLoadFailed(self, error_msg: str):
        """Show device library load failures that would otherwise live only in logs."""
        self._normalize_tags_after_sync_pending = False
        device_path = self.device_manager.device_path or ""
        logger.error("iPod library load failed: %s", error_msg)
        QMessageBox.critical(
            self,
            "Could Not Load iPod",
            _library_load_failure_message(device_path, error_msg),
        )

    def _onIpodTagFixesRequested(self) -> None:
        cache = self.library_cache
        if not cache.is_ready():
            QMessageBox.information(
                self,
                "Normalize iPod Tags",
                "Load an iPod library before running tag normalization.",
            )
            return

        tracks = cache.get_tracks()
        if not tracks:
            QMessageBox.information(
                self,
                "Normalize iPod Tags",
                "No tracks were found in this iPod library.",
            )
            return

        from iopenpod.gui.widgets.ipodTagFixDialog import IpodLibraryTagFixDialog
        from iopenpod.gui.widgets.ipodTagNormalizer import suggest_ipod_library_tag_fixes

        profile = self._current_ipod_tag_profile()
        suggestion = suggest_ipod_library_tag_fixes(tracks, profile=profile)
        if not suggestion.changes_by_track:
            QMessageBox.information(
                self,
                "Normalize iPod Tags",
                "No iPod-specific metadata fixes were found for this library.",
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

    def _current_ipod_tag_profile(self):
        from iopenpod.gui.widgets.ipodTagNormalizer import ipod_tag_profile

        session = self.device_session_service.current_session()
        identity = session.identity
        capabilities = session.capabilities
        return ipod_tag_profile(
            family=str(getattr(identity, "model_family", "") or ""),
            generation=str(getattr(identity, "generation", "") or ""),
            uses_sqlite_db=bool(getattr(capabilities, "uses_sqlite_db", False)),
            is_shuffle=bool(getattr(capabilities, "is_shuffle", False)),
        )

    @staticmethod
    def _scan_ipod_tag_fixes(track_snapshot: list[dict], profile):
        from iopenpod.gui.widgets.ipodTagNormalizer import (
            index_ipod_library_tag_fixes,
        )

        return index_ipod_library_tag_fixes(track_snapshot, profile=profile)

    def _invalidate_tag_fix_scan(self) -> None:
        self._tag_fix_scan_generation = getattr(
            self,
            "_tag_fix_scan_generation",
            0,
        ) + 1
        timer = getattr(self, "_tag_fix_scan_timer", None)
        if timer is not None:
            timer.stop()
        worker = getattr(self, "_tag_fix_scan_worker", None)
        if worker is not None:
            worker.cancel()
            self._tag_fix_scan_worker = None
        sidebar = getattr(self, "sidebar", None)
        if sidebar is not None:
            sidebar.setTagFixCount(0)

    def _schedule_tag_fix_scan(self) -> None:
        timer = getattr(self, "_tag_fix_scan_timer", None)
        if timer is None:
            return
        self._tag_fix_scan_generation += 1
        worker = self._tag_fix_scan_worker
        if worker is not None:
            worker.cancel()
            self._tag_fix_scan_worker = None
        timer.start()

    def _start_tag_fix_scan(self) -> None:
        cache = self.library_cache
        if not cache.is_ready():
            self.sidebar.setTagFixCount(0)
            return
        tracks = cache.get_tracks()
        if not tracks:
            self._normalize_tags_after_sync_pending = False
            self.sidebar.setTagFixCount(0)
            return

        settings = self.settings_service.get_effective_settings()
        apply_after_scan = bool(
            self._normalize_tags_after_sync_pending
            and getattr(settings, "normalize_tags_after_sync", False)
        )
        if self._normalize_tags_after_sync_pending and not apply_after_scan:
            self._normalize_tags_after_sync_pending = False

        from iopenpod.gui.widgets.ipodTagNormalizer import (
            build_ipod_tag_scan_snapshot,
        )

        generation = self._tag_fix_scan_generation
        track_count = len(tracks)
        track_snapshot = build_ipod_tag_scan_snapshot(tracks)
        worker = Worker(
            self._scan_ipod_tag_fixes,
            track_snapshot,
            self._current_ipod_tag_profile(),
        )
        self._tag_fix_scan_worker = worker
        worker.signals.result.connect(
            lambda result, token=generation, count=track_count, apply=apply_after_scan: (
                self._on_tag_fix_scan_ready(result, token, count, apply)
            )
        )
        worker.signals.error.connect(
            lambda error, token=generation: self._on_tag_fix_scan_failed(
                error,
                token,
            )
        )
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_tag_fix_scan_ready(
        self,
        result,
        generation: int,
        scanned_track_count: int,
        apply_after_scan: bool,
    ) -> None:
        if generation != self._tag_fix_scan_generation:
            return
        self._tag_fix_scan_worker = None
        self.sidebar.setTagFixCount(
            result.changed_field_count,
            result.changed_track_count,
        )
        if not apply_after_scan:
            return

        settings = self.settings_service.get_effective_settings()
        if not getattr(settings, "normalize_tags_after_sync", False):
            self._normalize_tags_after_sync_pending = False
            return

        tracks = self.library_cache.get_tracks()
        if len(tracks) != scanned_track_count:
            self._schedule_tag_fix_scan()
            return

        self._normalize_tags_after_sync_pending = False
        if not result.changes_by_index:
            return
        changes_by_track = {
            id(tracks[index]): changes
            for index, changes in result.changes_by_index.items()
            if 0 <= index < len(tracks)
        }
        self.library_cache.update_track_flags_by_track(tracks, changes_by_track)
        logger.info(
            "Applied silent post-sync tag normalization: %d fields across %d tracks",
            result.changed_field_count,
            result.changed_track_count,
        )

    def _on_tag_fix_scan_failed(self, error: object, generation: int) -> None:
        if generation != self._tag_fix_scan_generation:
            return
        self._tag_fix_scan_worker = None
        self._normalize_tags_after_sync_pending = False
        self.sidebar.setTagFixCount(0)
        logger.warning("Tag normalization scan failed: %s", error)

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
        from iopenpod.gui.styles import Colors, Metrics, resolve_accent_color

        s = self.settings_service.get_effective_settings()
        if dev is None:
            dev = self.device_session_service.current_session().identity

        img = ""
        if s.accent_color == "match-ipod":
            img = resolve_device_image_filename(dev)

        old_accent = Colors.ACCENT
        accent_hex = resolve_accent_color(s.accent_color, img)
        Colors.apply_theme_selection(
            s.theme_mode, s.light_theme, s.dark_theme, s.high_contrast, accent_hex
        )
        Metrics.apply_font_scale(s.font_scale)
        Metrics.apply_grid_item_scale(getattr(s, "grid_item_size", "large"))
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

        from iopenpod.gui.styles import Colors, resolve_accent_color
        accent_hex = resolve_accent_color("match-ipod", img)

        # Always apply the resolved accent, including "blue" fallback.
        # This ensures switching from a colorful device to a gray/white/black
        # device resets the UI back to the default accent.
        old_accent = Colors.ACCENT
        Colors.apply_theme_selection(
            s.theme_mode, s.light_theme, s.dark_theme, s.high_contrast, accent_hex
        )
        return Colors.ACCENT != old_accent

    @staticmethod
    def _classify_tracks(tracks: list) -> dict[str, list]:
        """Partition tracks by media type into audio/video/podcast/audiobook."""
        from iopenpod.itunesdb_shared.constants import (
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

        session = self.device_session_service.current_session()
        self._rename_worker = QuickWriteWorker(
            device.device_path,
            cache,
            device_storage=session.storage,
        )
        self._rename_worker.completed.connect(self._onRenameDone)
        self._rename_worker.error.connect(self._onRenameFailed)
        self._rename_worker.start()

    def _onRenameDone(self, result):
        """Device rename write completed."""
        if not result.success:
            self._onRenameFailed(result.error or "Database write failed.")
            return
        logger.info("iPod renamed successfully")
        Notifier.get_instance().notify("iPod Renamed", "Device name updated successfully")

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
        self.setPlayerActive(False)
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
        active_path = device.device_path
        path = active_path or self._eject_only_device_path
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

        self.sidebar.setEjectAvailable(False)

        if active_path:
            device_storage = self.device_session_service.current_session().storage
        else:
            device_storage = self._eject_only_device_storage
        self._eject_worker = EjectDeviceWorker(
            path,
            device_storage=device_storage,
        )
        self._eject_worker.finished_ok.connect(self._onEjectDone)
        self._eject_worker.failed.connect(self._onEjectFailed)
        self._eject_worker.start()

    def _onEjectDone(self, message: str):
        logger.info("iPod ejected: %s", message)
        if self._eject_worker is not None:
            self._eject_worker.deleteLater()
            self._eject_worker = None
        Notifier.get_instance().notify("iPod Ejected", message)
        self._eject_only_device_path = None
        self._eject_only_device_storage = None
        self.device_manager.device_path = None
        self.sidebar.setEjectAvailable(False)
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
        has_device = bool(
            self.device_manager.device_path or self._eject_only_device_path
        )
        self.sidebar.setEjectAvailable(has_device)
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
        sync_session = getattr(self, "_sync_session", None)
        return (
            (sync_session is not None and sync_session.is_running())
            or (self._back_sync_worker is not None and self._back_sync_worker.isRunning())
            or (
                self._podcast_plan_worker is not None
                and self._podcast_plan_worker.isRunning()
            )
            or (
                self._subsonic_plan_worker is not None
                and self._subsonic_plan_worker.isRunning()
            )
            or (
                self._album_conversion_worker is not None
                and self._album_conversion_worker.isRunning()
            )
            or (
                self._chapter_split_worker is not None
                and self._chapter_split_worker.isRunning()
            )
        )

    def _on_quick_meta_failed(self, error_msg: str):
        QMessageBox.warning(
            self, "Save Failed",
            f"Could not save quick changes to iPod:\n{error_msg}\n\n"
            "iOpenPod is reloading the device view from the iPod."
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
            from iopenpod.gui.imgMaker import configure_artwork_api, get_artwork

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

        self._sync_session.start_planning(
            SyncPlanningIntent(
                mode="full",
                folder_entries=tuple(self._last_pc_folder_entries),
            )
        )

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

    def _download_missing_tools_then_sync(
        self,
        need_ffmpeg: bool,
        need_fpcalc: bool,
        planning_intent: SyncPlanningIntent | None = None,
        completion_callback: Callable[[], None] | None = None,
    ):
        """Download missing tools in a background thread, then resume sync."""
        progress = _DownloadProgressDialog(self)
        progress.show()

        # Keep a reference so it isn't garbage collected
        self._dl_progress = progress
        self._pending_tool_sync_intent = planning_intent
        self._pending_tool_download_callback = completion_callback

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
        planning_intent = getattr(self, "_pending_tool_sync_intent", None)
        self._pending_tool_sync_intent = None
        completion_callback = getattr(self, "_pending_tool_download_callback", None)
        self._pending_tool_download_callback = None
        if completion_callback is not None:
            completion_callback()
            return
        if planning_intent is not None:
            self._sync_session.start_planning(planning_intent)
            return
        self.startPCSync()

    @pyqtSlot(str)
    def _on_tools_download_failed(self, error_msg: str):
        """Called on main thread if automatic tool download fails."""
        if hasattr(self, '_dl_progress') and self._dl_progress:
            self._dl_progress.close()
            self._dl_progress = None
        self._pending_tool_sync_intent = None
        self._pending_tool_download_callback = None
        QMessageBox.critical(
            self,
            "Download Failed",
            f"Could not download sync tools:\n\n{error_msg}",
        )

    def _show_sync_plan(self, plan: SyncPlan) -> None:
        """Show a prepared sync plan in the review page."""

        self._plan = plan
        self.syncReview._ipod_tracks_cache = self.library_cache.get_tracks() or []
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_plan(plan)

    def _onPodcastSyncRequested(self, plan):
        """Handle podcast sync plan from PodcastBrowser.

        Receives a SyncPlan with podcast episodes as to_add items and
        sends it through the standard sync review pipeline.
        """
        caps = self.device_session_service.current_session().capabilities
        if caps is not None and not caps.supports_podcast and getattr(plan, "to_add", None):
            QMessageBox.warning(
                self,
                "Unsupported iPod",
                "This iPod does not support podcasts.",
            )
            return
        self._show_sync_plan(plan)

    def _onAlbumConversionRequested(self, album_items: list[dict]) -> None:
        """Prepare a chaptered-album conversion plan from an Albums grid item."""
        if not album_items:
            return
        if self._is_sync_running():
            QMessageBox.information(
                self,
                "Sync Running",
                "Please wait for the current sync to finish before converting an album.",
            )
            return

        device_manager = self.device_manager
        if not device_manager.device_path:
            QMessageBox.warning(self, "No Device", "Please select an iPod device first.")
            return

        cache = self.library_cache
        if not cache.is_ready():
            QMessageBox.information(self, "Library Loading", "Please wait for the iPod library to finish loading.")
            return

        album_item = dict(album_items[0])
        try:
            from iopenpod.sync.album_chapters import resolve_album_tracks

            album_tracks = resolve_album_tracks(album_item, cache.get_tracks())
        except Exception as exc:
            logger.debug("Album track resolution failed", exc_info=True)
            QMessageBox.warning(self, "Album Conversion", str(exc))
            return

        if len(album_tracks) < 2:
            QMessageBox.information(
                self,
                "Album Conversion",
                "Choose an album with at least two tracks.",
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
        self._show_sync_plan(result.plan)
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
                "Sync Running",
                "Please wait for the current sync to finish before splitting chapters.",
            )
            return

        device_manager = self.device_manager
        if not device_manager.device_path:
            QMessageBox.warning(self, "No Device", "Please select an iPod device first.")
            return

        cache = self.library_cache
        if not cache.is_ready():
            QMessageBox.information(
                self,
                "Library Loading",
                "Please wait for the iPod library to finish loading.",
            )
            return

        track = dict(tracks[0])
        try:
            from iopenpod.sync.album_chapters import build_chapter_split_segments

            segments = build_chapter_split_segments(track)
        except Exception as exc:
            logger.debug("Chapter split validation failed", exc_info=True)
            QMessageBox.warning(self, "Chapter Split", str(exc))
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
        self._show_sync_plan(result.plan)
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
        self._show_sync_plan(plan)

    def _onSyncDiffComplete(self, plan, worker=None):
        """Called when sync diff calculation is complete."""
        self._show_sync_plan(plan)

    # ── Subsonic sync ──────────────────────────────────────────────────────

    def startSubsonicSync(self) -> None:
        """Plan a sync from the configured Subsonic-compatible server.

        Builds an ADD-only plan (starred songs + named playlists) in a
        background worker, then routes it through the same sync-review /
        execute pipeline as a PC sync.  Track bytes are streamed during
        execution (see ``SyncExecutor._fetch_subsonic_tracks``).
        """
        if self._is_sync_running():
            QMessageBox.information(
                self, "Sync In Progress",
                "A sync is already running. Please wait for it to finish.",
            )
            return

        device = self.device_manager
        if not device.device_path:
            QMessageBox.information(
                self, "No Device",
                "Select an iPod before syncing from Subsonic.",
            )
            return

        # Finish queued quick writes so planning reads committed state.
        quick_ready, blocked_label = (
            self._quick_write_controller.prepare_for_full_sync()
        )
        if not quick_ready:
            label = blocked_label or "quick changes"
            QMessageBox.warning(
                self, "Quick Changes Still Saving",
                f"iOpenPod is still saving pending {label}. Please wait.",
            )
            return
        if self.library_cache.is_loading():
            QMessageBox.information(
                self, "Library Loading",
                "Please wait for the iPod library to finish loading.",
            )
            return

        settings = self.settings_service.get_effective_settings()
        if not (settings.subsonic_url and settings.subsonic_username):
            QMessageBox.information(
                self, "Subsonic Not Configured",
                "Configure a Subsonic server in Settings → Subsonic first.",
            )
            return

        ipod_tracks = self.library_cache.get_tracks() or []
        cache_dir = settings.transcode_cache_dir or ""

        ipod_playlists = self.library_cache.get_playlists() or []

        # Resolve the Subsonic playlist mapping.  When the user has selected
        # playlists, fetch their names so we can show a mapping dialog (New vs
        # merge into an existing iPod playlist) before planning.
        playlist_ids = list(settings.subsonic_playlist_ids or ())
        mappings: dict[str, int] = dict(settings.subsonic_playlist_mappings or {})

        if playlist_ids:
            subsonic_playlists = self._fetch_subsonic_playlist_names(
                settings.subsonic_url,
                settings.subsonic_username,
                settings.subsonic_password,
                playlist_ids,
            )
            if subsonic_playlists is not None:
                from iopenpod.gui.widgets.syncReview import SubsonicPlaylistMappingDialog

                ipod_pairs = [
                    (
                        int(p.get("playlist_id") or p.get("Playlist ID") or 0),
                        p.get("Title") or p.get("name") or "",
                    )
                    for p in ipod_playlists
                    if (p.get("playlist_id") or p.get("Playlist ID"))
                    and not p.get("master_flag")
                ]
                dlg = SubsonicPlaylistMappingDialog(
                    self,
                    subsonic_playlists,
                    ipod_pairs,
                    saved_mappings=mappings,
                )
                if dlg.exec() != dlg.DialogCode.Accepted:
                    return  # user cancelled
                mappings = dlg.mappings
                # Persist the choice so it's remembered next time.
                s = self.settings_service.get_global_settings()
                s.subsonic_playlist_mappings = mappings
                self.settings_service.save_global_settings(s)

        from iopenpod.application.jobs import SubsonicPlanRequest, SubsonicPlanWorker

        worker = SubsonicPlanWorker(
            SubsonicPlanRequest(
                url=settings.subsonic_url,
                username=settings.subsonic_username,
                password=settings.subsonic_password,
                ipod_tracks=ipod_tracks,
                cache_dir=cache_dir,
                playlist_ids=tuple(playlist_ids),
                playlist_mappings=tuple(mappings.items()),
                ipod_playlists=tuple(ipod_playlists),
            )
        )
        self._subsonic_plan_worker = worker
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()
        worker.finished.connect(
            lambda plan, w=worker: self._on_subsonic_plan_ready(plan, w)
        )
        worker.error.connect(
            lambda err, w=worker: self._on_subsonic_plan_error(err, w)
        )
        worker.start()

    def _fetch_subsonic_playlist_names(
        self, url: str, username: str, password: str, playlist_ids: list[str]
    ) -> list[tuple[str, str]] | None:
        """Fetch (id, name) pairs for the named Subsonic playlists.

        Runs the network call off the UI thread with a wait cursor so the
        mapping dialog can show real names.  Returns None on failure (the
        caller then skips the dialog and falls back to saved mappings).
        """
        import threading

        from PyQt6.QtCore import QCoreApplication, Qt
        from PyQt6.QtGui import QGuiApplication

        result: list[list] = [[]]  # mutable holder
        done = threading.Event()

        def _work():
            try:
                from iopenpod.subsonic.client import SubsonicClient

                client = SubsonicClient(url, username, password)
                pairs: list[tuple[str, str]] = []
                for pid in playlist_ids:
                    pid = (pid or "").strip()
                    if not pid:
                        continue
                    try:
                        pl = client.get_playlist(pid)
                        pairs.append((pid, str(pl.get("name") or pid)))
                    except Exception:
                        pairs.append((pid, pid))
                result[0] = pairs
            except Exception:
                result[0] = []
            finally:
                done.set()

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        t = threading.Thread(target=_work, daemon=True)
        t.start()
        # Spin the event loop while waiting so the UI stays responsive.
        deadline_loops = 0
        while not done.is_set() and deadline_loops < 2000:
            QCoreApplication.processEvents()
            t.join(0.01)
            deadline_loops += 1
        QGuiApplication.restoreOverrideCursor()
        fetched = result[0]
        return fetched if fetched is not None else None

    def _on_subsonic_plan_ready(self, plan, worker=None) -> None:
        """Subsonic plan built — show it for review."""
        if worker is not None:
            if self._subsonic_plan_worker is not worker:
                return
            self._subsonic_plan_worker = None
        else:
            self._subsonic_plan_worker = None
        self._plan = plan
        self.syncReview.show_plan(plan)

    def _on_subsonic_plan_error(self, error_msg: str, worker=None) -> None:
        """Subsonic plan failed — surface the error."""
        if worker is not None:
            if self._subsonic_plan_worker is not worker:
                return
            self._subsonic_plan_worker = None
        else:
            self._subsonic_plan_worker = None
        logger.warning("Failed to build Subsonic plan: %s", error_msg)
        self.syncReview.show_error(error_msg)

    def _onSyncError(self, error_msg: str):
        """Called when sync diff fails."""
        self.syncReview.show_error(error_msg)

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
        """Detach and interrupt a background worker."""

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
        self._sync_session.start_planning(
            SyncPlanningIntent(
                mode="selective",
                folder_entries=tuple(selected_folder_entries),
                selected_paths=selected_paths,
            )
        )

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
        if self._sync_session.is_executing():
            self._sync_session.request_execution_cancel()
            return
        self.hideSyncReview()

    def hideSyncReview(self):
        """Return to the main browsing view, stopping any background work."""
        self._keep_sync_results_visible_after_rescan = False
        self._sync_session.cancel()
        self._cleanup_back_sync_worker()
        self._cleanup_album_conversion_worker()
        self._cleanup_chapter_split_worker()
        self._show_default_page()

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

    def showDatabaseStorage(self):
        """Show the database storage breakdown page."""
        session = self.device_session_service.current_session()
        capabilities = getattr(session, "capabilities", None)
        report = analyze_database_storage(
            getattr(session, "itunesdb_path", None),
            ipod_root=getattr(self.device_manager, "device_path", None),
            uses_sqlite_db=bool(getattr(capabilities, "uses_sqlite_db", False)),
        )
        self.databaseStorageBrowser.load_report(
            report,
            max_database_bytes=int(
                getattr(capabilities, "max_database_bytes", 0) or 0
            ),
        )
        self.centralStack.setCurrentIndex(_DATABASE_STORAGE_PAGE_INDEX)

    def hideDatabaseStorage(self):
        """Return from database storage management to the main browsing view."""
        self._show_default_page()

    def executeSyncPlan(self, selected_items):
        """Execute the selected sync actions."""
        # Get device path
        device_manager = self.device_manager
        if not device_manager.device_path:
            QMessageBox.warning(self, "No Device", "No iPod device selected.")
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

        # Respect the user's pre-sync backup choice from the prompt
        skip_backup = getattr(self.syncReview, '_skip_presync_backup', False)

        self._sync_session.start_execution(
            SyncExecutionIntent(
                plan=filtered_plan,
                skip_backup=skip_backup,
                sync_until_full=sync_until_full,
            )
        )

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
        message = (
            "This sync is estimated to need more space than is available on "
            "the iPod.\n\n"
            f"Available: {format_size(disk.free) or '0 B'}\n"
            f"Estimated needed: {format_size(required) or '0 B'}\n"
            f"Estimated shortfall: {format_size(shortage) or '0 B'}\n\n"
            "Sync Until Full will copy files in order until the next file would "
            f"leave less than {reserve_label} free, then save the database with "
            "the items that actually synced."
        )

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Not Enough Space")
        dialog.setText("The selected sync is larger than the iPod's free space.")
        dialog.setInformativeText(message)
        cancel_btn = dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        sync_btn = dialog.addButton(
            "Sync Until Full",
            QMessageBox.ButtonRole.AcceptRole,
        )
        dialog.setDefaultButton(cancel_btn)
        dialog.exec()
        return True if dialog.clickedButton() is sync_btn else None

    def _onSyncExecuteComplete(self, result):
        """Called when sync execution is complete."""
        # Show styled results view instead of a plain message box
        self.syncReview.show_result(result)
        self._keep_sync_results_visible_after_rescan = True
        device_manager = getattr(self, "device_manager", None)
        failure_message = _sync_execute_failure_message(
            result,
            getattr(device_manager, "device_path", "") or "",
        )
        settings = self.settings_service.get_effective_settings()
        self._normalize_tags_after_sync_pending = bool(
            not failure_message
            and getattr(settings, "normalize_tags_after_sync", False)
        )
        if failure_message:
            QMessageBox.critical(self, "Sync Failed", failure_message)

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
        self._invalidate_tag_fix_scan()
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

    def _onSyncExecuteError(self, error_msg: str):
        """Called when sync execution fails."""
        self._normalize_tags_after_sync_pending = False
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
        self._sync_session.respond_to_partial_save(save)

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
        if self._sync_session.is_executing():
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

        if dropped_files.track_paths or dropped_files.playlist_paths:
            settings = self.settings_service.get_effective_settings()
            tools = check_sync_tool_availability(settings)
            if tools.has_missing:
                self._show_missing_tools_for_drop(tools, paths)
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

    def _show_missing_tools_for_drop(
        self,
        tools: SyncToolAvailability,
        paths: list[Path],
    ) -> None:
        """Offer tool setup before a dropped import reaches media probing."""
        if tools.can_download:
            dialog = _MissingToolsDialog(self, tools.tool_list, can_download=True)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._download_missing_tools_then_sync(
                    tools.missing_ffmpeg,
                    tools.missing_fpcalc,
                    completion_callback=lambda: self._on_files_dropped(paths),
                )
            return

        dialog = _MissingToolsDialog(
            self,
            tools.tool_list,
            can_download=False,
            detail_lines=tools.install_help_text,
        )
        dialog.exec()

    def _on_drop_scan_complete(self, plan: SyncPlan) -> None:
        """Merge dropped-file plan into any existing plan, then show."""
        if self._drop_merge and self._plan is not None:
            merge_additional_sync_plan(self._plan, plan)
            self._show_sync_plan(self._plan)
        else:
            self._show_sync_plan(plan)

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
        self._sync_session.shutdown(3000)
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
        if self._album_conversion_worker and self._album_conversion_worker.isRunning():
            self._album_conversion_worker.requestInterruption()
            self._album_conversion_worker.wait(3000)
        if self._chapter_split_worker and self._chapter_split_worker.isRunning():
            self._chapter_split_worker.requestInterruption()
            self._chapter_split_worker.wait(3000)
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
    """Clear, focused setup prompt for external sync tools."""

    def __init__(
        self,
        parent: QWidget,
        tool_list: str,
        can_download: bool,
        detail_lines: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Set Up Sync Tools")
        self.setFixedWidth(460)
        _apply_dialog_background(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins((32), (28), (32), (28))
        layout.setSpacing(12)

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

        title = QLabel("Set up Sync Tools")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        tools_label = QLabel(tool_list)
        tools_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        tools_label.setStyleSheet(_label_css(Colors.WARNING))
        tools_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tools_label.setWordWrap(True)
        layout.addWidget(tools_label)

        layout.addSpacing(2)

        if can_download:
            body = QLabel(
                "iOpenPod needs these tools to prepare and sync your media.\n"
                "Download them automatically now? (~80 MB)"
            )
        else:
            body = QLabel(detail_lines)
        body.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        body.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        body.setAlignment(
            Qt.AlignmentFlag.AlignCenter
            if can_download
            else Qt.AlignmentFlag.AlignLeft
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        layout.addSpacing(16)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        if can_download:
            no_btn = QPushButton("Not now")
            no_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            no_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            no_btn.setMinimumHeight(40)
            no_btn.setStyleSheet(button_css("secondary", "lg"))
            no_btn.clicked.connect(self.reject)
            btn_row.addWidget(no_btn)

            yes_btn = QPushButton("Download tools")
            yes_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            yes_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            yes_btn.setMinimumHeight(40)
            yes_btn.setStyleSheet(accent_btn_css("lg"))
            yes_btn.setDefault(True)
            yes_btn.clicked.connect(self.accept)
            btn_row.addWidget(yes_btn)
        else:
            ok_btn = QPushButton("OK")
            ok_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            ok_btn.setMinimumHeight(40)
            ok_btn.setStyleSheet(button_css("secondary", "lg"))
            ok_btn.clicked.connect(self.reject)
            btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)


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
        _apply_dialog_background(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins((28), (24), (28), (24))
        layout.setSpacing(14)

        title = QLabel("Downloading Tools…")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.Bold))
        title.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._status = QLabel("Preparing download…")
        self._status.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._status.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        bar = QProgressBar()
        bar.setRange(0, 0)  # indeterminate
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        bar.setStyleSheet(progress_bar_css(height=6, radius=3, bg=Colors.SURFACE))
        layout.addWidget(bar)

        layout.addStretch()

    def set_status(self, text: str):
        """Update the status label (must be called from the main thread)."""
        self._status.setText(text)
