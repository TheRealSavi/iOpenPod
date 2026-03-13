import logging
import os
import sys
import traceback
from pathlib import Path
from PyQt6.QtCore import QRunnable, pyqtSignal, pyqtSlot, QObject, QThreadPool, QThread, Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QHBoxLayout, QMessageBox, QStackedWidget,
    QDialog, QVBoxLayout, QLabel, QPushButton, QProgressBar,
)
from GUI.widgets.musicBrowser import MusicBrowser
from GUI.widgets.sidebar import Sidebar
from GUI.widgets.syncReview import SyncReviewWidget, SyncWorker, PCFolderDialog, SyncExecuteWorker
from GUI.widgets.settingsPage import SettingsPage
from GUI.widgets.backupBrowser import BackupBrowserWidget
from GUI.widgets.dropOverlay import DropOverlayWidget
from GUI.settings import get_settings
from GUI.notifications import Notifier
from GUI.styles import Colors, FONT_FAMILY, Metrics, btn_css
from GUI.glyphs import glyph_pixmap
import threading

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("iOpenPod")

        # Load users settings
        settings = get_settings()

        # Restore remembered window size
        self.resize(settings.window_width, settings.window_height)

        # Initialize system notifications
        self._notifier = Notifier.get_instance(self)

        # Drag-and-drop support
        self.setAcceptDrops(True)
        self._drop_worker = None

        # Sync worker reference
        self._sync_worker = None
        self._sync_execute_worker = None
        self._plan = None
        self._last_pc_folder = settings.music_folder or ""

        # Central widget with stacked layout for main/sync views
        self.centralStack = QStackedWidget()
        self.setCentralWidget(self.centralStack)

        # Build all child widgets and connect signals
        self._build_ui()

        # Drop overlay (created after _build_ui so it sits on top)
        self._drop_overlay = DropOverlayWidget(self)

        # Connect device manager to reload data when device changes
        DeviceManager.get_instance().device_changed.connect(self.onDeviceChanged)

        # Connect cache ready signal to refresh UI
        iTunesDBCache.get_instance().data_ready.connect(self.onDataReady)

        # Restore last device path if it still looks like a real iPod
        if settings.last_device_path:
            device_manager = DeviceManager.get_instance()
            if device_manager.is_valid_ipod_root(settings.last_device_path):
                # Run a quick scan so discovered_ipod is populated
                # (needed for FireWire GUID, model info, etc.)
                try:
                    from GUI.device_scanner import scan_for_ipods
                    found_ipod = False
                    for ipod in scan_for_ipods():
                        if os.path.normpath(ipod.path) == os.path.normpath(settings.last_device_path):
                            device_manager.discovered_ipod = ipod
                            device_manager.device_path = settings.last_device_path
                            found_ipod = True
                            break
                    if not found_ipod:
                        logger.warning("Last device path '%s' not discovered during auto-restore scan", settings.last_device_path)
                except Exception as e:
                    logger.warning("Auto-restore scan failed: %s", e)

    def _build_ui(self):
        """Create child widgets and wire up signals.

        Called once from ``__init__`` and again by ``_on_theme_changed``
        to rebuild the UI with fresh themed styles.
        """
        # Main browsing page
        self.mainWidget = QWidget()
        self.mainLayout = QHBoxLayout(self.mainWidget)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)

        self.musicBrowser = MusicBrowser()
        self.musicBrowser.podcastBrowser.podcast_sync_requested.connect(self._onPodcastSyncRequested)

        self.sidebar = Sidebar()
        self.sidebar.category_changed.connect(self.musicBrowser.updateCategory)
        self.sidebar.device_renamed.connect(self._onDeviceRenamed)
        self.sidebar.deviceButton.clicked.connect(self.selectDevice)
        self.sidebar.rescanButton.clicked.connect(self.resyncDevice)
        self.sidebar.syncButton.clicked.connect(self.startPCSync)
        self.sidebar.settingsButton.clicked.connect(self.showSettings)
        self.sidebar.backupButton.clicked.connect(self.showBackupBrowser)

        self.mainLayout.addWidget(self.sidebar)
        self.mainLayout.addWidget(self.musicBrowser)
        self.centralStack.addWidget(self.mainWidget)  # Index 0

        # Sync review page
        self.syncReview = SyncReviewWidget()
        self.syncReview.cancelled.connect(self.hideSyncReview)
        self.syncReview.sync_requested.connect(self.executeSyncPlan)
        self.centralStack.addWidget(self.syncReview)  # Index 1

        # Settings page
        self.settingsPage = SettingsPage()
        self.settingsPage.closed.connect(self.hideSettings)
        self.settingsPage.theme_changed.connect(self._on_theme_changed)
        self.centralStack.addWidget(self.settingsPage)  # Index 2

        # Backup browser page
        self.backupBrowser = BackupBrowserWidget()
        self.backupBrowser.closed.connect(self.hideBackupBrowser)
        self.centralStack.addWidget(self.backupBrowser)  # Index 3

    def _on_theme_changed(self):
        """Rebuild the entire UI after a live theme switch."""
        from GUI.styles import build_palette, app_stylesheet

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

        # Switch to settings page (where the user just changed the theme)
        self.settingsPage.load_from_settings()
        self.centralStack.setCurrentIndex(2)

        # If cache is loaded, reload UI from cache
        cache = iTunesDBCache.get_instance()
        if cache.get_tracks():
            self.onDataReady()

    def selectDevice(self):
        """Open device picker dialog to scan and select an iPod."""
        from GUI.widgets.devicePicker import DevicePickerDialog

        dialog = DevicePickerDialog(self)
        if dialog.exec() and dialog.selected_path:
            folder = dialog.selected_path
            device_manager = DeviceManager.get_instance()
            if device_manager.is_valid_ipod_root(folder):
                device_manager.discovered_ipod = dialog.selected_ipod
                device_manager.device_path = folder
                # Persist selection
                settings = get_settings()
                settings.last_device_path = folder
                settings.save()
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
        # Clear the thread pool of pending tasks
        thread_pool = ThreadPoolSingleton.get_instance()
        thread_pool.clear()

        self.musicBrowser.browserGrid.clearGrid()
        self.musicBrowser.browserTrack.clearTable()

        from .imgMaker import clear_artworkdb_cache
        clear_artworkdb_cache()

        if path:
            # Start loading data (will emit data_ready when done)
            iTunesDBCache.get_instance().start_loading()

    def resyncDevice(self):
        """Rebuild the cache from the current device."""
        device = DeviceManager.get_instance()
        if not device.device_path:
            return
        iTunesDBCache.get_instance().clear()
        self.onDeviceChanged(device.device_path)

    def onDataReady(self):
        """Called when iTunesDB data is loaded and ready."""
        cache = iTunesDBCache.get_instance()

        tracks = cache.get_tracks()
        albums = cache.get_albums()
        db_data = cache.get_data()
        classified = self._classify_tracks(tracks)

        from device_info import get_current_device
        from iTunesDB_Shared.constants import get_version_name
        dev = get_current_device()

        device_name = dev.ipod_name if dev else "Unk iPod"
        model = dev.display_name if dev else "Unk iPod"

        db_version_hex = db_data.get('VersionHex', '') if db_data else ''
        db_version_name = get_version_name(db_version_hex) if db_version_hex else ''
        db_id = db_data.get('DatabaseID', 0) if db_data else 0

        self.sidebar.updateDeviceInfo(
            name=device_name,
            model=model,
            tracks=len(tracks),
            albums=len(albums),
            size_bytes=sum(t.get("size", 0) for t in tracks),
            duration_ms=sum(t.get("length", 0) for t in tracks),
            db_version_hex=db_version_hex,
            db_version_name=db_version_name,
            db_id=db_id,
            videos=len(classified["video"]),
            podcasts=len(classified["podcast"]),
            audiobooks=len(classified["audiobook"]),
        )
        self._update_sidebar_visibility(classified)
        self._update_podcast_statuses()
        self.musicBrowser.onDataReady()

    @staticmethod
    def _classify_tracks(tracks: list) -> dict[str, list]:
        """Partition tracks by media type into audio/video/podcast/audiobook."""
        from iTunesDB_Shared.constants import (
            MEDIA_TYPE_AUDIO, MEDIA_TYPE_PODCAST, MEDIA_TYPE_AUDIOBOOK,
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
        from device_info import get_current_device
        dev = get_current_device()
        caps = dev.capabilities if dev else None

        has_video = len(classified["video"]) > 0
        has_podcast = len(classified["podcast"]) > 0

        self.sidebar.setVideoVisible(has_video or (caps.supports_video if caps else False))
        self.sidebar.setPodcastVisible(has_podcast or (caps.supports_podcast if caps else False))

    def _onDeviceRenamed(self, new_name: str):
        """Handle device rename from sidebar — update master playlist and write to iPod."""
        device = DeviceManager.get_instance()
        if not device.device_path:
            return

        cache = iTunesDBCache.get_instance()
        data = cache.get_data()
        if not data:
            return

        # Update DeviceInfo.ipod_name
        try:
            from device_info import get_current_device
            dev = get_current_device()
            if dev:
                dev.ipod_name = new_name
        except Exception:
            pass

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
        self._rename_worker = _DeviceRenameWorker(device.device_path, new_name)
        self._rename_worker.finished_ok.connect(self._onRenameDone)
        self._rename_worker.failed.connect(self._onRenameFailed)
        self._rename_worker.start()

    def _onRenameDone(self):
        """Device rename write completed."""
        logger.info("iPod renamed successfully")
        Notifier.get_instance().notify("iPod Renamed", "Device name updated successfully")
        # Reload the database to reflect changes
        cache = iTunesDBCache.get_instance()
        cache.clear()
        cache.start_loading()

    def _onRenameFailed(self, error_msg: str):
        """Device rename write failed."""
        logger.error("iPod rename failed: %s", error_msg)
        QMessageBox.critical(
            self, "Rename Failed",
            f"Failed to rename iPod:\n{error_msg}"
        )

    def startPCSync(self):
        """Start the PC to iPod sync process."""
        device = DeviceManager.get_instance()
        if not device.device_path:
            QMessageBox.warning(
                self,
                "No Device",
                "Please select an iPod device first."
            )
            return

        # Pre-flight: check for required external tools
        from SyncEngine.audio_fingerprint import is_fpcalc_available
        from SyncEngine.transcoder import is_ffmpeg_available
        from SyncEngine.dependency_manager import is_platform_supported

        missing_fpcalc = not is_fpcalc_available()
        missing_ffmpeg = not is_ffmpeg_available()

        if missing_fpcalc or missing_ffmpeg:
            names = []
            if missing_fpcalc:
                names.append("fpcalc (Chromaprint)")
            if missing_ffmpeg:
                names.append("FFmpeg")
            tool_list = " and ".join(names)

            if is_platform_supported():
                dlg = _MissingToolsDialog(self, tool_list, can_download=True)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    self._download_missing_tools_then_sync(missing_ffmpeg, missing_fpcalc)
                    return
                elif missing_fpcalc:
                    return
                # ffmpeg missing but user declined — let them continue with MP3/M4A only
            else:
                # Platform doesn't support auto-download
                lines = ""
                if missing_fpcalc:
                    lines += "fpcalc is required for sync.\nInstall from: https://acoustid.org/chromaprint\n\n"
                if missing_ffmpeg:
                    lines += "FFmpeg is needed for transcoding.\nInstall from: https://ffmpeg.org\n\n"
                lines += "You can also set custom paths in\nSettings → External Tools."

                dlg = _MissingToolsDialog(
                    self, tool_list, can_download=False, detail_lines=lines,
                )
                if not missing_fpcalc:
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
        settings = get_settings()
        settings.music_folder = dialog.selected_folder
        settings.save()

        # Switch to sync review view
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()

        # Check device video capability
        from device_info import get_current_device
        dev = get_current_device()
        caps = dev.capabilities if dev else None
        supports_video = bool(caps and caps.supports_video)
        supports_podcast = bool(caps and caps.supports_podcast)

        # Gather GUI state to pass forward (not pulled by SyncEngine)
        cache = iTunesDBCache.get_instance()
        ipod_tracks = cache.get_tracks()

        track_edits = cache.get_track_edits()
        try:
            sync_workers = settings.sync_workers
            rating_strategy = settings.rating_conflict_strategy
        except Exception:
            sync_workers = 0  # auto
            rating_strategy = "ipod_wins"

        device_manager = DeviceManager.get_instance()

        self._sync_worker = SyncWorker(
            pc_folder=self._last_pc_folder,
            ipod_tracks=ipod_tracks,
            ipod_path=device_manager.device_path or "",
            supports_video=supports_video,
            supports_podcast=supports_podcast,
            track_edits=track_edits,
            sync_workers=sync_workers,
            rating_strategy=rating_strategy,
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

        import threading

        def _do():
            from SyncEngine.dependency_manager import download_ffmpeg, download_fpcalc
            if need_fpcalc:
                download_fpcalc()
            if need_ffmpeg:
                download_ffmpeg()

            from PyQt6.QtCore import QMetaObject, Qt as QtCore_Qt
            QMetaObject.invokeMethod(
                self, "_on_tools_downloaded",
                QtCore_Qt.ConnectionType.QueuedConnection,
            )

        threading.Thread(target=_do, daemon=True).start()

    @pyqtSlot()
    def _on_tools_downloaded(self):
        """Called on main thread after tool downloads finish."""
        if hasattr(self, '_dl_progress') and self._dl_progress:
            self._dl_progress.close()
            self._dl_progress = None
        # Re-run sync now that tools should be available
        self.startPCSync()

    def _onPodcastSyncRequested(self, plan):
        """Handle podcast sync plan from PodcastBrowser.

        Receives a SyncPlan with podcast episodes as to_add items and
        sends it through the standard sync review pipeline.
        """
        self._plan = plan
        cache = iTunesDBCache.get_instance()
        self.syncReview._ipod_tracks_cache = cache.get_tracks() or []

        # Switch to sync review view and show the plan
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_plan(plan)

    def _onSyncDiffComplete(self, plan):
        """Called when sync diff calculation is complete."""
        self._plan = plan  # Store for executeSyncPlan to access matched_pc_paths
        # Provide iPod tracks cache so the review widget can list artwork-missing tracks
        cache = iTunesDBCache.get_instance()
        self.syncReview._ipod_tracks_cache = cache.get_tracks() or []

        # ── Populate playlist change info on the plan ──────────────
        self._populate_playlist_changes(plan, cache)

        self.syncReview.show_plan(plan)

    def _populate_playlist_changes(self, plan, cache: 'iTunesDBCache'):
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

    def hideSyncReview(self):
        """Return to the main browsing view, stopping any background scan."""
        # Request interruption so SyncWorker / SyncExecuteWorker can bail out
        if self._sync_worker is not None and self._sync_worker.isRunning():
            self._sync_worker.requestInterruption()
        if self._sync_execute_worker is not None and self._sync_execute_worker.isRunning():
            self._sync_execute_worker.requestInterruption()
        self.centralStack.setCurrentIndex(0)

    def showSettings(self):
        """Show the settings page."""
        self.settingsPage.load_from_settings()
        self.centralStack.setCurrentIndex(2)

    def hideSettings(self):
        """Return from settings to the main browsing view."""
        # Re-read persisted settings to pick up changes
        settings = get_settings()
        self._last_pc_folder = settings.music_folder or self._last_pc_folder
        self.centralStack.setCurrentIndex(0)

    def showBackupBrowser(self):
        """Show the backup browser page."""
        self.backupBrowser.refresh()
        self.centralStack.setCurrentIndex(3)

    def hideBackupBrowser(self):
        """Return from backup browser to the main browsing view."""
        self.centralStack.setCurrentIndex(0)

    def executeSyncPlan(self, selected_items):
        """Execute the selected sync actions."""
        from SyncEngine.fingerprint_diff_engine import SyncAction, SyncPlan

        # Get device path
        device_manager = DeviceManager.get_instance()
        if not device_manager.device_path:
            QMessageBox.warning(self, "No Device", "No iPod device selected.")
            return

        # Filter items by action type
        add_items = [s for s in selected_items if s.action == SyncAction.ADD_TO_IPOD]
        remove_items = [s for s in selected_items if s.action == SyncAction.REMOVE_FROM_IPOD]
        meta_items = [s for s in selected_items if s.action == SyncAction.UPDATE_METADATA]
        file_items = [s for s in selected_items if s.action == SyncAction.UPDATE_FILE]
        art_items = [s for s in selected_items if s.action == SyncAction.UPDATE_ARTWORK]
        playcount_items = [s for s in selected_items if s.action == SyncAction.SYNC_PLAYCOUNT]
        rating_items = [s for s in selected_items if s.action == SyncAction.SYNC_RATING]

        # Create filtered plan
        # Carry matched_pc_paths, artwork info, and playlist changes from the original plan
        original_plan = self._plan  # stored in _onSyncDiffComplete

        # Playlists: only include if the playlist card's checkbox is checked
        pl_card = getattr(self.syncReview, '_playlist_card', None)
        include_playlists = (
            pl_card is not None and pl_card._select_all_cb.isChecked()
        ) if pl_card else True  # default to True if no card exists

        filtered_plan = SyncPlan(
            to_add=add_items,
            to_remove=remove_items,
            to_update_metadata=meta_items,
            to_update_file=file_items,
            to_update_artwork=art_items,
            to_sync_playcount=playcount_items,
            to_sync_rating=rating_items,
            matched_pc_paths=original_plan.matched_pc_paths if original_plan else {},
            _stale_mapping_entries=original_plan._stale_mapping_entries if original_plan else [],
            mapping=original_plan.mapping if original_plan else None,
            playlists_to_add=original_plan.playlists_to_add if (original_plan and include_playlists) else [],
            playlists_to_edit=original_plan.playlists_to_edit if (original_plan and include_playlists) else [],
            playlists_to_remove=original_plan.playlists_to_remove if (original_plan and include_playlists) else [],
        )

        if not filtered_plan.has_changes:
            return

        # Show progress in sync review widget
        self.syncReview.show_executing()

        # Respect the user's pre-sync backup choice from the prompt
        skip_backup = getattr(self.syncReview, '_skip_presync_backup', False)

        # Gather GUI state to pass to executor (instead of it pulling from GUI)
        cache = iTunesDBCache.get_instance()
        user_playlists = cache.get_user_playlists()

        def _on_sync_complete():
            """Called by executor after successful DB write to clear pending state."""
            c = iTunesDBCache.get_instance()
            if c.has_pending_playlists():
                c._user_playlists.clear()
            if c.has_pending_track_edits():
                c.clear_track_edits()

        # Start sync execution worker
        self._sync_execute_worker = SyncExecuteWorker(
            ipod_path=device_manager.device_path,
            plan=filtered_plan,
            skip_backup=skip_backup,
            user_playlists=user_playlists,
            on_sync_complete=_on_sync_complete,
        )
        self._sync_execute_worker.progress.connect(self.syncReview.update_execute_progress)
        self._sync_execute_worker.finished.connect(self._onSyncExecuteComplete)
        self._sync_execute_worker.error.connect(self._onSyncExecuteError)
        # Allow the user to skip the in-progress backup from the progress screen
        self.syncReview.skip_backup_signal.connect(self._sync_execute_worker.request_skip_backup)
        self._sync_execute_worker.start()

    def _onSyncExecuteComplete(self, result):
        """Called when sync execution is complete."""
        self._disconnect_skip_signal()
        # Show styled results view instead of a plain message box
        self.syncReview.show_result(result)

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

            cache = iTunesDBCache.get_instance()
            ipod_tracks = cache.get_tracks() or []

            browser.reconcile_ipod_statuses(ipod_tracks)

            # Refresh the podcast browser episode table so status is visible
            browser.refresh_episodes()
        except Exception as e:
            logger.debug("Could not update podcast statuses: %s", e)

    def _rescanAfterSync(self):
        """Rescan the iPod database after a short post-write delay."""
        cache = iTunesDBCache.get_instance()
        # Use clear() (not invalidate()) to fully reset the cache state.
        # invalidate() does not reset _is_loading, so if a prior load is
        # still in-flight start_loading() would silently bail out and the
        # UI would never refresh.
        cache.clear()

        # Clear artwork cache — sync may have added/changed album art
        from .imgMaker import clear_artworkdb_cache
        clear_artworkdb_cache()

        # Clear UI so the reload starts from a clean slate
        self.musicBrowser.browserGrid.clearGrid()
        self.musicBrowser.browserTrack.clearTable()

        cache.start_loading()

    def _disconnect_skip_signal(self):
        """Disconnect skip_backup_signal from the finished worker."""
        try:
            self.syncReview.skip_backup_signal.disconnect()
        except TypeError:
            pass  # Already disconnected

    def _onSyncExecuteError(self, error_msg: str):
        """Called when sync execution fails."""
        self._disconnect_skip_signal()
        # Desktop notification if app is not focused
        if not self.isActiveWindow():
            self._notifier.notify_sync_error(error_msg)

        from .settings import get_settings
        settings = get_settings()

        msg = f"Sync failed:\n\n{error_msg}"
        if settings.backup_before_sync:
            msg += (
                "\n\nA backup was created before this sync. "
                "You can restore it from the Backups page."
            )

        QMessageBox.critical(self, "Sync Error", msg)
        self.hideSyncReview()

    # ── Drag-and-drop support ──────────────────────────────────────────────

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        if hasattr(self, '_drop_overlay') and self._drop_overlay.isVisible():
            self._drop_overlay.setGeometry(self.rect())

    def dragEnterEvent(self, a0):
        if a0 is None:
            return
        # Reject drops when no device is selected or sync is executing
        device = DeviceManager.get_instance()
        if not device.device_path:
            a0.ignore()
            return
        if self._sync_execute_worker and self._sync_execute_worker.isRunning():
            a0.ignore()
            return

        mime = a0.mimeData()
        if mime and mime.hasUrls():
            from SyncEngine.pc_library import MEDIA_EXTENSIONS
            for url in mime.urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.is_dir() or p.suffix.lower() in MEDIA_EXTENSIONS:
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
        from SyncEngine.pc_library import MEDIA_EXTENSIONS

        # Collect all file paths (recurse folders)
        file_paths: list[Path] = []
        for p in paths:
            if p.is_dir():
                for root, _, files in os.walk(p):
                    for fname in files:
                        fp = Path(root) / fname
                        if fp.suffix.lower() in MEDIA_EXTENSIONS:
                            file_paths.append(fp)
            elif p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS:
                file_paths.append(p)

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
        self._drop_worker = _DropScanWorker(file_paths)
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
            from GUI.settings import get_settings as _get_settings
            _s = _get_settings()
            _s.window_width = self.width()
            _s.window_height = self.height()
            _s.save()
        except Exception:
            pass

        # Clean up system tray notification icon
        Notifier.shutdown()

        # Request graceful stop for sync workers
        if self._sync_worker and self._sync_worker.isRunning():
            self._sync_worker.requestInterruption()
            self._sync_worker.wait(3000)
        if self._sync_execute_worker and self._sync_execute_worker.isRunning():
            self._sync_execute_worker.requestInterruption()
            self._sync_execute_worker.wait(3000)

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
        self.setFixedWidth((420))
        self.setStyleSheet(f"""
            QDialog {{
                background: {Colors.DIALOG_BG};
                color: {Colors.TEXT_PRIMARY};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins((28), (24), (28), (24))
        layout.setSpacing((10))

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

        layout.addSpacing((4))

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

        layout.addSpacing((12))

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing((12))

        if can_download:
            no_btn = QPushButton("Not Now")
            no_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            no_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            no_btn.setMinimumHeight((40))
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
            yes_btn.setMinimumHeight((40))
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
            ok_btn.setMinimumHeight((40))
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
            cont_btn.setMinimumHeight((40))
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
        layout.setSpacing((14))

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
        bar.setFixedHeight((6))
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


# ============================================================================
# Threading Utilities
# ============================================================================

class CancellationToken:
    """Thread-safe cancellation token for workers."""

    def __init__(self):
        self._cancelled = threading.Event()

    def cancel(self):
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def reset(self):
        self._cancelled.clear()


class ThreadPoolSingleton:
    _instance: QThreadPool | None = None

    @classmethod
    def get_instance(cls) -> QThreadPool:
        if cls._instance is None:
            cls._instance = QThreadPool.globalInstance()
        assert cls._instance is not None
        return cls._instance


class Worker(QRunnable):
    """Generic background worker with error recovery.

    Wraps a function to run in a thread pool with proper cancellation,
    error handling, and cleanup support.
    """

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        # Capture the current cancellation token at creation time
        self._cancellation_token = DeviceManager.get_instance().cancellation_token
        self._is_cancelled = False
        self._fn_name = getattr(fn, '__name__', str(fn))

    def is_cancelled(self) -> bool:
        """Check if this worker has been cancelled."""
        return self._is_cancelled or self._cancellation_token.is_cancelled()

    def cancel(self):
        """Mark this worker as cancelled."""
        self._is_cancelled = True

    @pyqtSlot()
    def run(self):
        # Check cancellation before starting
        if self.is_cancelled():
            logger.debug(f"Worker {self._fn_name} cancelled before start")
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass
            return

        try:
            result = self.fn(*self.args, **self.kwargs)
            # Check cancellation before emitting result
            if not self.is_cancelled():
                try:
                    self.signals.result.emit(result)
                except RuntimeError:
                    # Signal receiver was deleted
                    logger.debug(f"Worker {self._fn_name} result signal receiver deleted")
        except Exception as e:
            if not self.is_cancelled():
                logger.error(f"Worker {self._fn_name} failed: {e}", exc_info=True)
                exectype, value = sys.exc_info()[:2]
                try:
                    self.signals.error.emit((exectype, value, traceback.format_exc()))
                except RuntimeError:
                    logger.debug(f"Worker {self._fn_name} error signal receiver deleted")
        finally:
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(int)


# ============================================================================
# State Management
# ============================================================================

class DeviceManager(QObject):
    """Manages the currently selected iPod device path."""
    device_changed = pyqtSignal(str)  # Emits the new device path
    device_changing = pyqtSignal()  # Emitted before device change to trigger cleanup

    _instance = None

    def __init__(self):
        super().__init__()
        self._device_path = None
        self._discovered_ipod = None  # cached DeviceInfo from last scan
        self._cancellation_token = CancellationToken()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = DeviceManager()
        return cls._instance

    @property
    def cancellation_token(self) -> CancellationToken:
        return self._cancellation_token

    def cancel_all_operations(self):
        """Cancel all ongoing operations and create a new token."""
        self._cancellation_token.cancel()
        self._cancellation_token = CancellationToken()

    @property
    def device_path(self) -> str | None:
        return self._device_path

    @property
    def discovered_ipod(self):
        """Return the cached DeviceInfo from the last scan, if any."""
        return self._discovered_ipod

    @discovered_ipod.setter
    def discovered_ipod(self, ipod):
        self._discovered_ipod = ipod
        # Store in the centralised device info store
        self._sync_device_info(ipod)

    @device_path.setter
    def device_path(self, path: str | None):
        # Signal that device is changing (for cleanup)
        self.device_changing.emit()
        # Cancel all ongoing operations
        self.cancel_all_operations()
        # Clear the iTunesDB cache
        iTunesDBCache.get_instance().clear()
        self._device_path = path
        if path is None:
            self._discovered_ipod = None
            # Clear centralized device store
            from device_info import clear_current_device
            clear_current_device()
        self.device_changed.emit(path or "")

    @property
    def itunesdb_path(self) -> str | None:
        if not self._device_path:
            return None
        from device_info import resolve_itdb_path
        return resolve_itdb_path(self._device_path)

    @property
    def artworkdb_path(self) -> str | None:
        if not self._device_path:
            return None
        return os.path.join(self._device_path, "iPod_Control", "Artwork", "ArtworkDB")

    @property
    def artwork_folder_path(self) -> str | None:
        if not self._device_path:
            return None
        return os.path.join(self._device_path, "iPod_Control", "Artwork")

    def is_valid_ipod_root(self, path: str) -> bool:
        """Check if the given path looks like a valid iPod root."""
        ipod_control = os.path.join(path, "iPod_Control")
        itunes_folder = os.path.join(ipod_control, "iTunes")
        return os.path.isdir(ipod_control) and os.path.isdir(itunes_folder)

    @staticmethod
    def _sync_device_info(ipod) -> None:
        """Store a DeviceInfo (from scanner) in the centralised store.

        The scanner already calls ``enrich()`` so devices arrive
        fully populated — no conversion or re-probing needed.
        """
        from device_info import set_current_device, clear_current_device

        if ipod is None:
            clear_current_device()
            return

        set_current_device(ipod)


class iTunesDBCache(QObject):
    """Cache for parsed iTunesDB data. Loads once when device selected, all tabs consume."""
    data_ready = pyqtSignal()  # Emitted when data is loaded and ready
    _instance: "iTunesDBCache | None" = None

    playlists_changed = pyqtSignal()   # Emitted when user playlists are added/edited/removed
    tracks_changed = pyqtSignal()       # Emitted when track flags are modified (pending sync)

    def __init__(self):
        super().__init__()
        self._data: dict | None = None
        self._device_path: str | None = None
        self._is_loading: bool = False
        self._lock = threading.Lock()
        # Pre-computed indexes for fast lookups
        self._album_index: dict | None = None  # (album, artist) -> list of tracks
        self._album_only_index: dict | None = None  # album -> list of tracks
        self._artist_index: dict | None = None  # artist -> list of tracks
        self._genre_index: dict | None = None   # genre -> list of tracks
        self._track_id_index: dict | None = None  # trackID -> track dict
        # User-created/edited playlists (persisted in memory until sync)
        self._user_playlists: list[dict] = []
        # Pending track flag edits: db_id -> { field: (original, new), ... }
        # Originals are captured on first edit so the diff engine can
        # revert in-memory track dicts before comparing.
        self._track_edits: dict[int, dict[str, tuple]] = {}

    @classmethod
    def get_instance(cls) -> "iTunesDBCache":
        if cls._instance is None:
            cls._instance = iTunesDBCache()
        return cls._instance

    def clear(self):
        """Clear the cache (called when device changes)."""
        with self._lock:
            self._data = None
            self._device_path = None
            self._is_loading = False
            self._album_index = None
            self._album_only_index = None
            self._artist_index = None
            self._genre_index = None
            self._track_id_index = None
            self._user_playlists.clear()
            self._track_edits.clear()

    def invalidate(self):
        """Mark cached data stale so the next start_loading() re-parses."""
        with self._lock:
            self._data = None
            self._album_index = None
            self._album_only_index = None
            self._artist_index = None
            self._genre_index = None
            self._track_id_index = None

    def is_ready(self) -> bool:
        """Check if data is cached and ready."""
        device = DeviceManager.get_instance()
        with self._lock:
            return (self._data is not None and self._device_path == device.device_path and not self._is_loading)

    def is_loading(self) -> bool:
        """Check if data is currently being loaded."""
        with self._lock:
            return self._is_loading

    def get_data(self) -> dict | None:
        """Get cached data if available for current device."""
        device = DeviceManager.get_instance()
        with self._lock:
            if self._data is not None and self._device_path == device.device_path:
                return self._data
            return None

    def get_tracks(self) -> list:
        """Get tracks from cached data."""
        data = self.get_data()
        return list(data.get("mhlt", [])) if data else []

    def get_albums(self) -> list:
        """Get album list from cached data."""
        data = self.get_data()
        return list(data.get("mhla", [])) if data else []

    def get_album_index(self) -> dict:
        """Get pre-computed album index: (album, artist) -> list of tracks."""
        with self._lock:
            return self._album_index or {}

    def get_album_only_index(self) -> dict:
        """Get pre-computed album-only index: album -> list of tracks (fallback)."""
        with self._lock:
            return self._album_only_index or {}

    def get_artist_index(self) -> dict:
        """Get pre-computed artist index: artist -> list of tracks."""
        with self._lock:
            return self._artist_index or {}

    def get_genre_index(self) -> dict:
        """Get pre-computed genre index: genre -> list of tracks."""
        with self._lock:
            return self._genre_index or {}

    def get_track_id_index(self) -> dict:
        """Get pre-computed trackID index: trackID -> track dict."""
        with self._lock:
            return self._track_id_index or {}

    def get_playlists(self) -> list:
        """Get all playlists (regular + podcast + smart), tagged with _source.

        Deduplicates by playlistID since the podcast dataset (type 3) often
        contains the same playlists as the regular dataset (type 2).  The
        regular copy is preferred when duplicates exist.  Playlists from
        mhlp_podcast are only tagged as 'podcast' when their podcastFlag is
        set — otherwise they are just duplicates of regular playlists.

        Nano 5G+ / newer iTunes versions may omit dataset type 2 entirely,
        placing the master playlist and all user playlists in type 3 instead.
        In that case we honour isMaster from type 3 to avoid losing the
        master playlist.
        """
        data = self.get_data()
        if not data:
            return []

        seen_ids: set[int] = set()
        result: list[dict] = []

        # 1. Regular playlists (mhlp / dataset type 2) — always preferred
        has_type2_master = False
        for pl in data.get("mhlp", []):
            pl = {**pl, "_source": "regular"}
            pid = pl.get("playlist_id", 0)
            if pid not in seen_ids:
                seen_ids.add(pid)
                result.append(pl)
                if pl.get("master_flag"):
                    has_type2_master = True

        # 2. Podcast playlists (mhlp_podcast / dataset type 3)
        #    Only add if not already seen, and tag as podcast only when
        #    podcastFlag is actually set.
        #    When type 2 provided a master playlist, force master_flag=False
        #    on type 3 entries (they duplicate the master flag).  But when
        #    type 2 is absent (Nano 5G+, newer iTunes), honour master_flag
        #    from type 3 — that's where the master playlist actually lives.
        for pl in data.get("mhlp_podcast", []):
            pid = pl.get("playlist_id", 0)
            if pid in seen_ids:
                continue  # duplicate of a regular playlist
            source = "podcast" if pl.get("podcast_flag", 0) == 1 else "regular"
            pl = {**pl, "_source": source}
            if has_type2_master:
                pl["master_flag"] = 0
            seen_ids.add(pid)
            result.append(pl)

        # 3. Smart playlists (mhlp_smart / dataset type 5)
        #    master_flag is forced 0 — dataset 5 MHYP entries reuse the
        #    same type byte at offset 0x14 (1=master), but for dataset 5
        #    it denotes an iPod built-in category (Music, Movies, etc.),
        #    NOT the master playlist.  Only dataset 2 or 3 has the real master.
        for pl in data.get("mhlp_smart", []):
            pid = pl.get("playlist_id", 0)
            if pid in seen_ids:
                continue
            pl = {**pl, "_source": "smart", "master_flag": 0}
            seen_ids.add(pid)
            result.append(pl)

        # 4. User-created/edited playlists (from GUI, pending sync)
        with self._lock:
            for upl in self._user_playlists:
                pid = upl.get("playlist_id", 0)
                if pid in seen_ids:
                    # Replace the existing entry with the edited version
                    result = [upl if r.get("playlist_id") == pid else r for r in result]
                else:
                    seen_ids.add(pid)
                    result.append(upl)

        return result

    # ─────────────────────────────────────────────────────────────
    # User playlist management (in-memory, written at sync time)
    # ─────────────────────────────────────────────────────────────

    def save_user_playlist(self, playlist: dict) -> None:
        """Add or update a user-created/edited playlist in memory.

        If the playlist has a playlistID that matches an existing user
        playlist, the old entry is replaced.  Otherwise a new ID is generated.
        Emits playlists_changed so the UI can refresh.
        """
        import random

        with self._lock:
            pid = playlist.get("playlist_id", 0)

            # Assign a new playlist_id if this is a brand-new playlist
            if not pid:
                pid = random.getrandbits(64)
                playlist["playlist_id"] = pid

            # Replace existing or append
            replaced = False
            for i, upl in enumerate(self._user_playlists):
                if upl.get("playlist_id") == pid:
                    self._user_playlists[i] = playlist
                    replaced = True
                    break
            if not replaced:
                self._user_playlists.append(playlist)

        logger.info(
            "User playlist saved: '%s' (id=0x%016X, new=%s)",
            playlist.get("Title", "?"), pid, not replaced,
        )
        self.playlists_changed.emit()

    def remove_user_playlist(self, playlist_id: int) -> bool:
        """Remove a user playlist by playlist_id. Returns True if found."""
        with self._lock:
            before = len(self._user_playlists)
            self._user_playlists = [
                p for p in self._user_playlists
                if p.get("playlist_id") != playlist_id
            ]
            removed = len(self._user_playlists) < before
        if removed:
            self.playlists_changed.emit()
        return removed

    def get_user_playlists(self) -> list[dict]:
        """Get all user-created/edited playlists (pending sync)."""
        with self._lock:
            return list(self._user_playlists)

    def has_pending_playlists(self) -> bool:
        """Check if there are user playlists waiting to be synced."""
        with self._lock:
            return len(self._user_playlists) > 0

    # ─────────────────────────────────────────────────────────────
    # Track flag edits (in-memory, applied at sync time)
    # ─────────────────────────────────────────────────────────────

    def update_track_flags(self, tracks: list[dict], changes: dict) -> None:
        """Apply flag changes to one or more tracks.

        Updates the in-memory track dicts immediately (so the UI reflects
        the change) and records the edit as ``(original, new)`` so the diff
        engine can revert to the true iPod state before comparing.

        Args:
            tracks:  List of track dicts (from the parsed iTunesDB).
            changes: Field→value mapping, e.g.
                     ``{"skip_when_shuffling": 1, "compilation_flag": 0}``.
        """
        with self._lock:
            for track in tracks:
                db_id = track.get("db_id", 0)
                if not db_id:
                    continue
                edits = self._track_edits.setdefault(db_id, {})
                for key, value in changes.items():
                    if key in edits:
                        # Already edited — keep the *original* value, update new
                        orig, _ = edits[key]
                        edits[key] = (orig, value)
                    else:
                        # First edit for this field — snapshot original
                        edits[key] = (track.get(key), value)
                    # Apply to the in-memory dict so the UI sees it instantly
                    track[key] = value

        n = len(tracks)
        fields = ", ".join(f"{k}={v}" for k, v in changes.items())
        logger.info("Track flags updated on %d track(s): %s", n, fields)
        self.tracks_changed.emit()

    def get_track_edits(self) -> dict[int, dict[str, tuple]]:
        """Get all pending track flag edits: db_id → {field: (original, new)}."""
        with self._lock:
            return dict(self._track_edits)

    def has_pending_track_edits(self) -> bool:
        """Check if there are track edits waiting to be synced."""
        with self._lock:
            return len(self._track_edits) > 0

    def clear_track_edits(self) -> None:
        """Clear pending track edits (called after successful sync)."""
        with self._lock:
            self._track_edits.clear()

    def set_data(self, data: dict, device_path: str):
        """Set cached data, build indexes, and emit ready signal."""
        # Build indexes for fast lookups
        album_index = {}  # (album, artist) -> list of tracks
        album_only_index = {}  # album -> list of tracks (fallback when mhla lacks artist)
        artist_index = {}  # artist -> list of tracks
        genre_index = {}   # genre -> list of tracks

        track_id_index = {}  # trackID -> track dict

        tracks = list(data.get("mhlt", []))
        for track in tracks:
            tid = track.get("track_id")
            if tid is not None:
                track_id_index[tid] = track

            # Only include audio tracks in album/artist/genre indices.
            # Video, podcast, audiobook etc. tracks belong in their own
            # sidebar categories and should not pollute the music views.
            # media_type 0 ("Audio/Video") appears in both menus per iTunes.
            mt = track.get("media_type", 1)
            if mt != 0 and not (mt & 0x01):
                continue

            album = track.get("Album", "Unknown Album")
            artist = track.get("Artist", "Unknown Artist")
            # Use Album Artist for album grouping (matches mhla's "Artist (Used by Album Item)")
            album_artist = track.get("Album Artist") or artist
            genre = track.get("Genre", "Unknown Genre")

            # Album index (keyed by album + album_artist to match mhla)
            album_key = (album, album_artist)
            if album_key not in album_index:
                album_index[album_key] = []
            album_index[album_key].append(track)

            # Album-only index (fallback for mhla entries without artist)
            if album not in album_only_index:
                album_only_index[album] = []
            album_only_index[album].append(track)

            # Artist index
            if artist not in artist_index:
                artist_index[artist] = []
            artist_index[artist].append(track)

            # Genre index
            if genre not in genre_index:
                genre_index[genre] = []
            genre_index[genre].append(track)

        with self._lock:
            self._data = data
            self._device_path = device_path
            self._is_loading = False
            self._album_index = album_index
            self._album_only_index = album_only_index
            self._artist_index = artist_index
            self._genre_index = genre_index
            self._track_id_index = track_id_index
        # Emit signal outside lock to avoid deadlock
        self.data_ready.emit()

    def set_loading(self, loading: bool):
        """Set loading state."""
        with self._lock:
            self._is_loading = loading

    def start_loading(self):
        """Start loading data for the current device. Called once when device selected."""
        device = DeviceManager.get_instance()
        if not device.device_path:
            return

        with self._lock:
            if self._is_loading:
                return  # Already loading
            if self._data is not None and self._device_path == device.device_path:
                # Already have data for this device, just emit ready
                self.data_ready.emit()
                return
            self._is_loading = True

        # Start background load
        worker = Worker(self._load_data, device.device_path, device.itunesdb_path)
        worker.signals.result.connect(self._on_load_complete)
        ThreadPoolSingleton.get_instance().start(worker)

    def _load_data(self, device_path: str, itunesdb_path: str) -> tuple:
        """Background thread: parse the iTunesDB and merge Play Counts."""
        from iTunesDB_Parser.ipod_library import load_ipod_library

        data = load_ipod_library(itunesdb_path)
        return (data, device_path)

    def _on_load_complete(self, result: tuple):
        """Called when background load finishes."""
        data, device_path = result
        # Verify this is still the current device
        if device_path != DeviceManager.get_instance().device_path:
            self.set_loading(False)  # Reset so future loads aren't blocked
            return
        if data:
            self.set_data(data, device_path)
        else:
            self.set_loading(False)


# ============================================================================
# Data Transform (convert cached state data to UI-ready format)
# ============================================================================

def build_album_list(cache: iTunesDBCache) -> list:
    """Transform cached data into album list for grid display.

    Uses the pre-built album index for O(1) lookups instead of O(n*m) scan.
    Falls back to album-only lookup when mhia entry lacks artist info.
    """
    albums = cache.get_albums()
    album_index = cache.get_album_index()
    album_only_index = cache.get_album_only_index()

    items = []
    for album_entry in albums:
        artist = album_entry.get("Artist (Used by Album Item)")
        album = album_entry.get("Album (Used by Album Item)", "Unknown Album")

        # Try exact (album, artist) lookup first
        matching_tracks = []
        if artist:
            matching_tracks = album_index.get((album, artist), [])

        # Fallback: if no artist in mhia or no match, lookup by album name only
        if not matching_tracks:
            matching_tracks = album_only_index.get(album, [])
            # If we found tracks but had no artist, use the album artist from tracks
            if matching_tracks and not artist:
                artist = matching_tracks[0].get("Album Artist") or matching_tracks[0].get("Artist", "Unknown Artist")

        if not artist:
            artist = "Unknown Artist"

        mhiiLink = None
        track_count = len(matching_tracks)
        year = None
        total_length_ms = 0

        if track_count > 0:
            mhiiLink = matching_tracks[0].get("artwork_id_ref")
            # Get year from first track that has it
            year = next((t.get("year") for t in matching_tracks if t.get("year")), None)
            # Calculate total album duration
            total_length_ms = sum(t.get("length", 0) for t in matching_tracks)

        # Build subtitle: "Artist • Year • N tracks"
        subtitle_parts = [artist]
        if year and year > 0:
            subtitle_parts.append(str(year))
        subtitle_parts.append(f"{track_count} tracks")
        subtitle = " · ".join(subtitle_parts)

        # Skip albums that have no audio tracks (e.g. video-only albums)
        if track_count == 0:
            continue

        items.append({
            "title": album,
            "subtitle": subtitle,
            "album": album,
            "artist": artist,
            "year": year,
            "artwork_id_ref": mhiiLink,
            "category": "Albums",
            "filter_key": "Album",
            "filter_value": album,
            "track_count": track_count,
            "total_length_ms": total_length_ms
        })

    return sorted(items, key=lambda x: x["title"].lower())


def build_artist_list(cache: iTunesDBCache) -> list:
    """Transform cached data into artist list for grid display.

    Uses the pre-built artist index for O(1) lookups.
    """
    artist_index = cache.get_artist_index()

    items = []
    for artist, tracks in artist_index.items():
        track_count = len(tracks)
        # Get first available artwork
        mhiiLink = next((t.get("artwork_id_ref") for t in tracks if t.get("artwork_id_ref")), None)
        # Count unique albums
        album_count = len(set(t.get("Album", "") for t in tracks))
        # Total plays
        total_plays = sum(t.get("play_count_1", 0) for t in tracks)

        # Build subtitle: "N albums · M tracks" or add plays if any
        subtitle_parts = []
        if album_count > 1:
            subtitle_parts.append(f"{album_count} albums")
        subtitle_parts.append(f"{track_count} tracks")
        if total_plays > 0:
            subtitle_parts.append(f"{total_plays} plays")

        items.append({
            "title": artist,
            "subtitle": " · ".join(subtitle_parts),
            "artwork_id_ref": mhiiLink,
            "category": "Artists",
            "filter_key": "Artist",
            "filter_value": artist,
            "track_count": track_count,
            "album_count": album_count,
            "total_plays": total_plays
        })

    return sorted(items, key=lambda x: x["title"].lower())


def build_genre_list(cache: iTunesDBCache) -> list:
    """Transform cached data into genre list for grid display.

    Uses the pre-built genre index for O(1) lookups.
    """
    genre_index = cache.get_genre_index()

    items = []
    for genre, tracks in genre_index.items():
        track_count = len(tracks)
        # Get first available artwork
        mhiiLink = next((t.get("artwork_id_ref") for t in tracks if t.get("artwork_id_ref")), None)
        # Count unique artists
        artist_count = len(set(t.get("Artist", "") for t in tracks))
        # Total duration
        total_length_ms = sum(t.get("length", 0) for t in tracks)
        total_hours = total_length_ms / (1000 * 60 * 60)

        # Build subtitle: "N artists · M tracks · X.X hours"
        subtitle_parts = []
        if artist_count > 1:
            subtitle_parts.append(f"{artist_count} artists")
        subtitle_parts.append(f"{track_count} tracks")
        if total_hours >= 1:
            subtitle_parts.append(f"{total_hours:.1f} hours")

        items.append({
            "title": genre,
            "subtitle": " · ".join(subtitle_parts),
            "artwork_id_ref": mhiiLink,
            "category": "Genres",
            "filter_key": "Genre",
            "filter_value": genre,
            "track_count": track_count,
            "artist_count": artist_count,
            "total_length_ms": total_length_ms
        })

    return sorted(items, key=lambda x: x["title"].lower())


# _DeviceRenameWorker — background thread for iPod rename (full DB rewrite)
class _DeviceRenameWorker(QThread):
    """Rewrite the iTunesDB after renaming the iPod (master playlist title)."""

    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, ipod_path: str, new_name: str):
        super().__init__()
        self._ipod_path = ipod_path
        self._new_name = new_name

    def run(self):
        try:
            from SyncEngine.sync_executor import SyncExecutor, _SyncContext
            from SyncEngine.mapping import MappingFile

            executor = SyncExecutor(self._ipod_path)
            existing_db = executor._read_existing_database()
            existing_tracks_data = existing_db["tracks"]
            existing_playlists_raw = list(existing_db["playlists"])
            existing_smart_raw = list(existing_db["smart_playlists"])

            all_tracks = [
                executor._track_dict_to_info(t) for t in existing_tracks_data
            ]

            # Build a minimal context for _build_and_evaluate_playlists
            ctx = _SyncContext(
                plan=None,  # type: ignore[arg-type]
                mapping=MappingFile(),
                progress_callback=None,
                dry_run=False,
                aac_quality="normal",
                write_back_to_pc=False,
                _is_cancelled=None,
            )
            ctx.existing_tracks_data = existing_tracks_data
            ctx.existing_playlists_raw = existing_playlists_raw
            ctx.existing_smart_raw = existing_smart_raw

            _master_name, playlists, smart_playlists = executor._build_and_evaluate_playlists(
                ctx, all_tracks,
            )

            # Use the explicitly requested name, NOT the one read from disk.
            success = executor._write_database(
                tracks=all_tracks,
                playlists=playlists,
                smart_playlists=smart_playlists,
                master_playlist_name=self._new_name,
            )

            if success:
                self.finished_ok.emit()
            else:
                self.failed.emit("Database write returned False.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))


# _DropScanWorker - background thread for reading dropped files metadata
class _DropScanWorker(QThread):
    """Read metadata from dropped files and build a SyncPlan."""

    finished = pyqtSignal(object)  # SyncPlan
    error = pyqtSignal(str)

    def __init__(self, file_paths: list):
        super().__init__()
        self._file_paths = file_paths

    def run(self):
        try:
            from SyncEngine.pc_library import PCLibrary
            from SyncEngine.fingerprint_diff_engine import (
                SyncPlan, SyncItem, SyncAction, StorageSummary,
            )

            items: list[SyncItem] = []
            total_bytes = 0

            for fp in self._file_paths:
                if self.isInterruptionRequested():
                    return
                try:
                    # Use a temporary PCLibrary rooted at the file's parent
                    lib = PCLibrary(fp.parent)
                    track = lib._read_track(fp)
                    if track:
                        items.append(SyncItem(
                            action=SyncAction.ADD_TO_IPOD,
                            pc_track=track,
                            description=f"{track.artist} — {track.title}",
                        ))
                        total_bytes += track.size
                except Exception as e:
                    logger.warning("Failed to read dropped file %s: %s", fp, e)

            plan = SyncPlan(
                to_add=items,
                storage=StorageSummary(bytes_to_add=total_bytes),
            )
            self.finished.emit(plan)
        except Exception as e:
            self.error.emit(str(e))
