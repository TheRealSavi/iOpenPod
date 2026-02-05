import os
import sys
import traceback
from PyQt6.QtCore import QRunnable, pyqtSignal, pyqtSlot, QObject, QThreadPool
from PyQt6.QtWidgets import QWidget, QMainWindow, QHBoxLayout, QFileDialog, QMessageBox, QStackedWidget
from GUI.widgets.musicBrowser import MusicBrowser
from GUI.widgets.sidebar import Sidebar
from GUI.widgets.syncReview import SyncReviewWidget, SyncWorker, PCFolderDialog
import threading

# Paths relative to project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPINNER_PATH = os.path.join(os.path.dirname(__file__), "spinner.svg")


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


class DeviceManager(QObject):
    """Manages the currently selected iPod device path."""
    device_changed = pyqtSignal(str)  # Emits the new device path
    device_changing = pyqtSignal()  # Emitted before device change to trigger cleanup

    _instance = None

    def __init__(self):
        super().__init__()
        self._device_path = None
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

    @device_path.setter
    def device_path(self, path: str | None):
        # Signal that device is changing (for cleanup)
        self.device_changing.emit()
        # Cancel all ongoing operations
        self.cancel_all_operations()
        # Clear the iTunesDB cache
        iTunesDBCache.get_instance().clear()
        self._device_path = path
        self.device_changed.emit(path or "")

    @property
    def itunesdb_path(self) -> str | None:
        if not self._device_path:
            return None
        return os.path.join(self._device_path, "iPod_Control", "iTunes", "iTunesDB")

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


class ThreadPoolSingleton:
    _instance: QThreadPool | None = None

    @classmethod
    def get_instance(cls) -> QThreadPool:
        if cls._instance is None:
            cls._instance = QThreadPool.globalInstance()
        assert cls._instance is not None
        return cls._instance


class iTunesDBCache(QObject):
    """Cache for parsed iTunesDB data. Loads once when device selected, all tabs consume."""
    data_ready = pyqtSignal()  # Emitted when data is loaded and ready
    _instance: "iTunesDBCache | None" = None

    def __init__(self):
        super().__init__()
        self._data: dict | None = None
        self._device_path: str | None = None
        self._is_loading: bool = False
        self._lock = threading.Lock()
        # Pre-computed indexes for fast lookups
        self._album_index: dict | None = None  # (album, artist) -> list of tracks
        self._artist_index: dict | None = None  # artist -> list of tracks
        self._genre_index: dict | None = None   # genre -> list of tracks

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

    def set_data(self, data: dict, device_path: str):
        """Set cached data, build indexes, and emit ready signal."""
        # Build indexes for fast lookups
        album_index = {}  # (album, artist) -> list of tracks
        album_only_index = {}  # album -> list of tracks (fallback when mhla lacks artist)
        artist_index = {}  # artist -> list of tracks
        genre_index = {}   # genre -> list of tracks

        tracks = list(data.get("mhlt", []))
        for track in tracks:
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
        """Background thread: parse the iTunesDB."""
        from iTunesDB_Parser.parser import parse_itunesdb
        if not itunesdb_path or not os.path.exists(itunesdb_path):
            return (None, device_path)
        try:
            data = parse_itunesdb(itunesdb_path)
            return (data, device_path)
        except Exception as e:
            print(f"Error parsing iTunesDB: {e}")
            return (None, device_path)

    def _on_load_complete(self, result: tuple):
        """Called when background load finishes."""
        data, device_path = result
        # Verify this is still the current device
        if device_path != DeviceManager.get_instance().device_path:
            return  # Device changed, ignore
        if data:
            self.set_data(data, device_path)
        else:
            self.set_loading(False)


category_glyphs = {
    "Albums": "💿",
    "Artists": "🧑‍🎤",
    "Tracks": "🎵",
    "Playlists": "📂",
    "Genres": "📜"}


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        # Capture the current cancellation token at creation time
        self._cancellation_token = DeviceManager.get_instance().cancellation_token
        self._is_cancelled = False

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
            self.signals.finished.emit()
            return

        try:
            result = self.fn(*self.args, **self.kwargs)
            # Check cancellation before emitting result
            if not self.is_cancelled():
                try:
                    self.signals.result.emit(result)
                except RuntimeError:
                    # Signal receiver was deleted
                    pass
        except Exception:
            if not self.is_cancelled():
                traceback.print_exc()
                exectype, value = sys.exc_info()[:2]
                try:
                    self.signals.error.emit((exectype, value, traceback.format_exc()))
                except RuntimeError:
                    pass
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
# Data Transform Functions (convert cached data to UI-ready format)
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
            mhiiLink = matching_tracks[0].get("mhiiLink")
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

        items.append({
            "title": album,
            "subtitle": subtitle,
            "album": album,
            "artist": artist,
            "year": year,
            "mhiiLink": mhiiLink,
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
        mhiiLink = next((t.get("mhiiLink") for t in tracks if t.get("mhiiLink")), None)
        # Count unique albums
        album_count = len(set(t.get("Album", "") for t in tracks))
        # Total plays
        total_plays = sum(t.get("playCount", 0) for t in tracks)

        # Build subtitle: "N albums · M tracks" or add plays if any
        subtitle_parts = []
        if album_count > 1:
            subtitle_parts.append(f"{album_count} albums")
        subtitle_parts.append(f"{track_count} tracks")
        if total_plays > 0:
            subtitle_parts.append(f"{total_plays} plays")
        subtitle = " · ".join(subtitle_parts)

        items.append({
            "title": artist,
            "subtitle": subtitle,
            "mhiiLink": mhiiLink,
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
        mhiiLink = next((t.get("mhiiLink") for t in tracks if t.get("mhiiLink")), None)
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
            "mhiiLink": mhiiLink,
            "category": "Genres",
            "filter_key": "Genre",
            "filter_value": genre,
            "track_count": track_count,
            "artist_count": artist_count,
            "total_length_ms": total_length_ms
        })

    return sorted(items, key=lambda x: x["title"].lower())


def ensure_readable_color(r, g, b, text_color=(255, 255, 255)):
    """
    Adjusts the background color to ensure at least 4.5:1 contrast with text.
    """
    def relative_luminance(rgb):
        """Calculate luminance as per WCAG formula."""
        def to_linear(c):
            c /= 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = [to_linear(c) for c in rgb]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    bg_lum = relative_luminance((r, g, b))
    text_lum = relative_luminance(text_color)

    # Ensure L_light > L_dark for ratio calculation
    L1, L2 = max(bg_lum, text_lum), min(bg_lum, text_lum)
    contrast = (L1 + 0.05) / (L2 + 0.05)

    # If contrast is too low, adjust brightness
    while contrast < 4.5:
        r, g, b = [min(255, c * 1.1) for c in (r, g, b)]  # Lighten
        bg_lum = relative_luminance((r, g, b))
        L1, L2 = max(bg_lum, text_lum), min(bg_lum, text_lum)
        contrast = (L1 + 0.05) / (L2 + 0.05)

        if contrast >= 4.5:
            break

        r, g, b = [max(0, c * 0.9) for c in (r, g, b)]  # Darken
        bg_lum = relative_luminance((r, g, b))
        L1, L2 = max(bg_lum, text_lum), min(bg_lum, text_lum)
        contrast = (L1 + 0.05) / (L2 + 0.05)

    return (int(r), int(g), int(b))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("iOpenPod")
        self.setGeometry(100, 100, 1280, 720)

        # Central widget with stacked layout for main/sync views
        self.centralStack = QStackedWidget()
        self.setCentralWidget(self.centralStack)

        # Main browsing view
        self.mainWidget = QWidget()
        self.mainLayout = QHBoxLayout(self.mainWidget)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)

        self.sidebar = Sidebar()
        self.mainLayout.addWidget(self.sidebar)

        self.musicBrowser = MusicBrowser()
        self.mainLayout.addWidget(self.musicBrowser)

        self.centralStack.addWidget(self.mainWidget)  # Index 0

        # Sync review view
        self.syncReview = SyncReviewWidget()
        self.syncReview.cancelled.connect(self.hideSyncReview)
        self.syncReview.sync_requested.connect(self.executeSyncPlan)
        self.centralStack.addWidget(self.syncReview)  # Index 1

        # Sync worker reference
        self._sync_worker = None
        self._last_pc_folder = os.path.join(os.path.expanduser("~"), "Music")

        self.sidebar.category_changed.connect(
            self.musicBrowser.updateCategory)  # Connect the signal to the slot

        # Connect device button to folder picker
        self.sidebar.deviceButton.clicked.connect(self.selectDevice)

        # Connect rescan button to rebuild cache
        self.sidebar.rescanButton.clicked.connect(self.resyncDevice)

        # Connect sync button to PC sync
        self.sidebar.syncButton.clicked.connect(self.startPCSync)

        # Connect device manager to reload data when device changes
        DeviceManager.get_instance().device_changed.connect(self.onDeviceChanged)

        # Connect cache ready signal to refresh UI
        iTunesDBCache.get_instance().data_ready.connect(self.onDataReady)

    def selectDevice(self):
        """Open folder picker dialog to select iPod root folder."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select iPod Root Folder",
            "",
            QFileDialog.Option.ShowDirsOnly
        )

        if folder:
            device_manager = DeviceManager.get_instance()
            if device_manager.is_valid_ipod_root(folder):
                device_manager.device_path = folder
                self.sidebar.updateDeviceButton(os.path.basename(folder) or folder)
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

        # Clear artwork cache when device changes
        from .imgMaker import clear_artworkdb_cache
        clear_artworkdb_cache()

        # Clear UI immediately
        self.musicBrowser.browserGrid.clearGrid()
        self.musicBrowser.browserTrack.clearTable()

        if path:
            # Start loading data (will emit data_ready when done)
            iTunesDBCache.get_instance().start_loading()

    def onDataReady(self):
        """Called when iTunesDB data is loaded and ready."""
        # Update sidebar with device stats
        cache = iTunesDBCache.get_instance()
        device = DeviceManager.get_instance()

        tracks = cache.get_tracks()
        albums = cache.get_albums()
        db_data = cache.get_data()

        total_size = sum(t.get("size", 0) for t in tracks)
        total_duration = sum(t.get("length", 0) for t in tracks)

        # Get device name from folder
        device_name = os.path.basename(device.device_path) if device.device_path else "iPod"

        # Get actual device info from SysInfo if available
        device_info = None
        model = "iPod"  # Default
        try:
            from iTunesDB_Writer.device import get_device_info
            if device.device_path:
                device_info = get_device_info(device.device_path)
                if 'friendly_name' in device_info:
                    model = device_info['friendly_name']
                elif 'model_name' in device_info:
                    model = device_info['model_name']
        except Exception as e:
            print(f"Could not get device info: {e}")

        # Get database version info
        db_version_hex = ""
        db_version_name = ""
        db_id = 0
        if db_data:
            db_version_hex = db_data.get('VersionHex', '')
            db_id = db_data.get('DatabaseID', 0)
            if db_version_hex:
                try:
                    from iTunesDB_Parser.constants import get_version_name
                    db_version_name = get_version_name(db_version_hex)
                except Exception:
                    db_version_name = "Unknown"

        self.sidebar.updateDeviceInfo(
            name=device_name,
            model=model,
            tracks=len(tracks),
            albums=len(albums),
            size_bytes=total_size,
            duration_ms=total_duration,
            device_info=device_info,
            db_version_hex=db_version_hex,
            db_version_name=db_version_name,
            db_id=db_id
        )

        # Refresh the current view with the loaded data
        self.musicBrowser.onDataReady()

    def resyncDevice(self):
        """Rebuild the cache from the current device."""
        device = DeviceManager.get_instance()
        if not device.device_path:
            return

        # Clear cache and reload
        cache = iTunesDBCache.get_instance()
        cache.clear()

        # Clear artwork cache
        from .imgMaker import clear_artworkdb_cache
        clear_artworkdb_cache()

        # Clear UI
        self.musicBrowser.browserGrid.clearGrid()
        self.musicBrowser.browserTrack.clearTable()

        # Start loading (will emit data_ready when done)
        cache.start_loading()

    def startPCSync(self):
        """Start the PC ↔ iPod sync process."""
        device = DeviceManager.get_instance()
        if not device.device_path:
            QMessageBox.warning(
                self,
                "No Device",
                "Please select an iPod device first."
            )
            return

        # Show folder selection dialog
        dialog = PCFolderDialog(self, self._last_pc_folder)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self._last_pc_folder = dialog.selected_folder

        # Switch to sync review view
        self.centralStack.setCurrentIndex(1)
        self.syncReview.show_loading()

        # Get iPod tracks from cache
        cache = iTunesDBCache.get_instance()
        ipod_tracks = cache.get_tracks()

        # Start background worker
        self._sync_worker = SyncWorker(
            pc_folder=self._last_pc_folder,
            ipod_tracks=ipod_tracks
        )
        self._sync_worker.progress.connect(self.syncReview.update_progress)
        self._sync_worker.finished.connect(self._onSyncDiffComplete)
        self._sync_worker.error.connect(self._onSyncError)
        self._sync_worker.start()

    def _onSyncDiffComplete(self, plan):
        """Called when sync diff calculation is complete."""
        self.syncReview.show_plan(plan)

    def _onSyncError(self, error_msg: str):
        """Called when sync diff fails."""
        self.syncReview.show_error(error_msg)

    def hideSyncReview(self):
        """Return to the main browsing view."""
        self.centralStack.setCurrentIndex(0)

    def executeSyncPlan(self, selected_items):
        """Execute the selected sync actions.

        NOTE: This is a placeholder - the actual writer implementation
        comes later. For now we just show what would happen.
        """
        from SyncEngine.diff_engine import SyncAction

        add_count = sum(1 for s in selected_items if s.action == SyncAction.ADD_TO_IPOD)
        remove_count = sum(1 for s in selected_items if s.action == SyncAction.REMOVE_FROM_IPOD)

        QMessageBox.information(
            self,
            "Sync Preview (Writer Not Implemented)",
            f"The sync would:\n\n"
            f"• Add {add_count} tracks to iPod\n"
            f"• Remove {remove_count} tracks from iPod\n\n"
            f"iTunesDB writer is not yet implemented.\n"
            f"This preview shows what WILL happen once the writer is complete."
        )

        # Return to main view
        self.hideSyncReview()

    def closeEvent(self, a0):
        """Ensure all threads are stopped when the window is closed."""
        # Stop sync worker if running
        if self._sync_worker and self._sync_worker.isRunning():
            self._sync_worker.terminate()
            self._sync_worker.wait(1000)

        thread_pool = ThreadPoolSingleton.get_instance()
        if thread_pool:
            thread_pool.clear()  # Remove pending tasks
            thread_pool.waitForDone(3000)  # Wait up to 3 seconds for running tasks
        if a0:
            a0.accept()
