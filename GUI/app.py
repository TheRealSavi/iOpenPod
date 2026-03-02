import logging
import os
import sys
import traceback
from PyQt6.QtCore import QRunnable, pyqtSignal, pyqtSlot, QObject, QThreadPool, QThread, Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QMainWindow, QHBoxLayout, QMessageBox, QStackedWidget,
    QDialog, QVBoxLayout, QLabel, QPushButton, QProgressBar,
)
from GUI.widgets.musicBrowser import MusicBrowser
from GUI.widgets.sidebar import Sidebar
from GUI.widgets.syncReview import SyncReviewWidget, SyncWorker, PCFolderDialog, SyncExecuteWorker
from GUI.widgets.settingsPage import SettingsPage
from GUI.widgets.backupBrowser import BackupBrowserWidget
from GUI.settings import get_settings
from GUI.notifications import Notifier
from GUI.styles import Colors, FONT_FAMILY, btn_css
import threading

logger = logging.getLogger(__name__)

# Paths relative to project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Styled Dialogs ──────────────────────────────────────────────────────────

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
                background: #222233;
                color: white;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        # Icon + title row
        icon_label = QLabel("⚠️")
        icon_label.setFont(QFont(FONT_FAMILY, 22))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        title = QLabel(f"{tool_list} Not Found")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Weight.Bold))
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
        body.setFont(QFont(FONT_FAMILY, 10))
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
            no_btn.setFont(QFont(FONT_FAMILY, 11))
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
            yes_btn.setFont(QFont(FONT_FAMILY, 11))
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
            ok_btn.setFont(QFont(FONT_FAMILY, 11))
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
            cont_btn.setFont(QFont(FONT_FAMILY, 11))
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
        self.setFixedSize(380, 180)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowCloseButtonHint  # type: ignore[operator]
        )
        self.setStyleSheet(f"""
            QDialog {{
                background: #222233;
                color: white;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("Downloading Tools…")
        title.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._status = QLabel("Preparing download…")
        self._status.setFont(QFont(FONT_FAMILY, 10))
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
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {Colors.ACCENT};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(bar)

        layout.addStretch()

    def set_status(self, text: str):
        """Update the status label (must be called from the main thread)."""
        self._status.setText(text)


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
        # Pending track flag edits: dbid -> { field: value, ... }
        # Merged into track dicts at sync time by sync_executor.
        self._track_edits: dict[int, dict] = {}

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
        """
        data = self.get_data()
        if not data:
            return []

        seen_ids: set[int] = set()
        result: list[dict] = []

        # 1. Regular playlists (mhlp / dataset type 2) — always preferred
        for pl in data.get("mhlp", []):
            pl["_source"] = "regular"
            pid = pl.get("playlistID", 0)
            if pid not in seen_ids:
                seen_ids.add(pid)
                result.append(pl)

        # 2. Podcast playlists (mhlp_podcast / dataset type 3)
        #    Only add if not already seen, and tag as podcast only when
        #    podcastFlag is actually set.
        for pl in data.get("mhlp_podcast", []):
            pid = pl.get("playlistID", 0)
            if pid in seen_ids:
                continue  # duplicate of a regular playlist
            pl["_source"] = "podcast" if pl.get("podcastFlag", 0) == 1 else "regular"
            seen_ids.add(pid)
            result.append(pl)

        # 3. Smart playlists (mhsp / dataset type 5)
        for pl in data.get("mhsp", []):
            pid = pl.get("playlistID", 0)
            if pid in seen_ids:
                continue
            pl["_source"] = "smart"
            seen_ids.add(pid)
            result.append(pl)

        # 4. User-created/edited playlists (from GUI, pending sync)
        with self._lock:
            for upl in self._user_playlists:
                pid = upl.get("playlistID", 0)
                if pid in seen_ids:
                    # Replace the existing entry with the edited version
                    result = [upl if r.get("playlistID") == pid else r for r in result]
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
            pid = playlist.get("playlistID", 0)

            # Assign a new playlistID if this is a brand-new playlist
            if not pid:
                pid = random.getrandbits(64)
                playlist["playlistID"] = pid

            # Replace existing or append
            replaced = False
            for i, upl in enumerate(self._user_playlists):
                if upl.get("playlistID") == pid:
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
        """Remove a user playlist by playlistID. Returns True if found."""
        with self._lock:
            before = len(self._user_playlists)
            self._user_playlists = [
                p for p in self._user_playlists
                if p.get("playlistID") != playlist_id
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
        the change) and records the edit so it persists through the next
        sync/database write.

        Args:
            tracks:  List of track dicts (from the parsed iTunesDB).
            changes: Field→value mapping, e.g.
                     ``{"skipWhenShuffling": 1, "compilation": 0}``.
        """
        with self._lock:
            for track in tracks:
                dbid = track.get("dbid", 0)
                if not dbid:
                    continue
                # Apply to the in-memory dict so the UI sees it instantly
                for key, value in changes.items():
                    track[key] = value
                # Store the pending edit for sync time
                self._track_edits.setdefault(dbid, {}).update(changes)

        n = len(tracks)
        fields = ", ".join(f"{k}={v}" for k, v in changes.items())
        logger.info("Track flags updated on %d track(s): %s", n, fields)
        self.tracks_changed.emit()

    def get_track_edits(self) -> dict[int, dict]:
        """Get all pending track flag edits: dbid -> {field: value}."""
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
            tid = track.get("trackID")
            if tid is not None:
                track_id_index[tid] = track

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
        from iTunesDB_Parser.parser import parse_itunesdb
        if not itunesdb_path or not os.path.exists(itunesdb_path):
            return (None, device_path)
        try:
            data = parse_itunesdb(itunesdb_path)

            # Merge Play Counts file so the GUI shows accurate play/skip
            # counts (the iPod firmware records deltas there, not in the
            # iTunesDB itself).
            try:
                from iTunesDB_Parser.playcounts import parse_playcounts, merge_playcounts
                pc_path = os.path.join(os.path.dirname(itunesdb_path), "Play Counts")
                entries = parse_playcounts(pc_path)
                if entries is not None:
                    tracks = data.get("mhlt", [])
                    merge_playcounts(tracks, entries)
            except Exception as e:
                logger.debug("Play Counts merge skipped: %s", e)

            return (data, device_path)
        except Exception as e:
            logger.error("Error parsing iTunesDB: %s", e)
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

        # Settings view
        self.settingsPage = SettingsPage()
        self.settingsPage.closed.connect(self.hideSettings)
        self.centralStack.addWidget(self.settingsPage)  # Index 2

        # Backup browser view
        self.backupBrowser = BackupBrowserWidget()
        self.backupBrowser.closed.connect(self.hideBackupBrowser)
        self.centralStack.addWidget(self.backupBrowser)  # Index 3

        # Sync worker reference
        self._sync_worker = None
        self._sync_execute_worker = None
        self._plan = None

        # Initialize system notifications
        self._notifier = Notifier.get_instance(self)

        # Load persisted settings
        settings = get_settings()
        self._last_pc_folder = settings.music_folder or os.path.join(os.path.expanduser("~"), "Music")

        self.sidebar.category_changed.connect(
            self.musicBrowser.updateCategory)  # Connect the signal to the slot

        # Connect device rename
        self.sidebar.device_renamed.connect(self._onDeviceRenamed)

        # Connect device button to folder picker
        self.sidebar.deviceButton.clicked.connect(self.selectDevice)

        # Connect rescan button to rebuild cache
        self.sidebar.rescanButton.clicked.connect(self.resyncDevice)

        # Connect sync button to PC sync
        self.sidebar.syncButton.clicked.connect(self.startPCSync)

        # Connect settings button
        self.sidebar.settingsButton.clicked.connect(self.showSettings)

        # Connect backup button
        self.sidebar.backupButton.clicked.connect(self.showBackupBrowser)

        # Connect device manager to reload data when device changes
        DeviceManager.get_instance().device_changed.connect(self.onDeviceChanged)

        # Connect cache ready signal to refresh UI
        iTunesDBCache.get_instance().data_ready.connect(self.onDataReady)

        # Restore last device path — only if it still looks like a real
        # iPod (not a leftover project test-data folder, etc.).
        if settings.last_device_path:
            device_manager = DeviceManager.get_instance()
            if device_manager.is_valid_ipod_root(settings.last_device_path):
                # Sanity-check: reject paths inside this project directory.
                # ipodTestData passes is_valid_ipod_root but isn't a device.
                try:
                    import pathlib
                    saved = pathlib.Path(settings.last_device_path).resolve()
                    project = pathlib.Path(__file__).resolve().parent.parent
                    if saved == project or project in saved.parents:
                        logger.info(
                            "Ignoring last_device_path inside project dir: %s",
                            settings.last_device_path,
                        )
                        settings.last_device_path = ""
                        settings.save()
                        device_manager = None  # skip restore
                except Exception:
                    pass  # resolve() can fail on vanished drives; fall through

                if device_manager is not None:
                    # Run a quick scan so discovered_ipod is populated
                    # (needed for FireWire GUID, model info, etc.)
                    try:
                        from GUI.device_scanner import scan_for_ipods
                        for ipod in scan_for_ipods():
                            if os.path.normpath(ipod.path) == os.path.normpath(settings.last_device_path):
                                device_manager.discovered_ipod = ipod
                                break
                    except Exception as e:
                        logger.warning("Auto-restore scan failed: %s", e)
                    device_manager.device_path = settings.last_device_path
                    self.sidebar.updateDeviceButton(
                        os.path.basename(settings.last_device_path) or settings.last_device_path
                    )

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
                self.sidebar.updateDeviceButton(os.path.basename(folder) or folder)
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

        # Get device name from master playlist title (the iPod's user name)
        device_name = ""
        playlists = cache.get_playlists()
        for pl in playlists:
            if pl.get("isMaster"):
                device_name = pl.get("Title", "")
                break
        if not device_name:
            device_name = os.path.basename(device.device_path) if device.device_path else "iPod"

        # Store iPod name in centralized DeviceInfo
        try:
            from device_info import get_current_device
            dev = get_current_device()
            if dev and not dev.ipod_name:
                dev.ipod_name = device_name
        except Exception:
            pass

        # Get model name from centralised DeviceInfo store
        model = "iPod"  # Default
        try:
            from device_info import get_current_device
            dev = get_current_device()
            if dev:
                model = dev.display_name
        except Exception as e:
            logger.warning("Could not get device info: %s", e)

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
            if pl.get("isMaster"):
                pl["Title"] = new_name
                master_pl = pl
                break

        if not master_pl:
            logger.warning("Could not find master playlist to rename")
            return

        logger.info("Renaming iPod to '%s'", new_name)

        # Write the full database to persist the rename
        self._rename_worker = _DeviceRenameWorker(device.device_path)
        self._rename_worker.finished_ok.connect(self._onRenameDone)
        self._rename_worker.failed.connect(self._onRenameFailed)
        self._rename_worker.start()

    def _onRenameDone(self):
        """Device rename write completed."""
        logger.info("iPod renamed successfully")
        Notifier.get_instance().notify("iPod Renamed", "Device name updated successfully")
        # Reload the database to reflect changes
        cache = iTunesDBCache.get_instance()
        cache.invalidate()
        cache.start_loading()

    def _onRenameFailed(self, error_msg: str):
        """Device rename write failed."""
        logger.error("iPod rename failed: %s", error_msg)
        QMessageBox.critical(
            self, "Rename Failed",
            f"Failed to rename iPod:\n{error_msg}"
        )

    @pyqtSlot()
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

        # Get iPod tracks from cache
        cache = iTunesDBCache.get_instance()
        ipod_tracks = cache.get_tracks()

        # Start background worker
        device_manager = DeviceManager.get_instance()
        self._sync_worker = SyncWorker(
            pc_folder=self._last_pc_folder,
            ipod_tracks=ipod_tracks,
            ipod_path=device_manager.device_path or ""
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
                pid = pl.get("playlistID", 0)
                if pid:
                    existing_ids.add(pid)
            for pl in data.get("mhlp_podcast", []):
                pid = pl.get("playlistID", 0)
                if pid:
                    existing_ids.add(pid)
            for pl in data.get("smart_playlists", []):
                pid = pl.get("playlistID", 0)
                if pid:
                    existing_ids.add(pid)

        for upl in user_playlists:
            pid = upl.get("playlistID", 0)
            is_new = upl.get("_isNew", False)
            if is_new or pid not in existing_ids:
                plan.playlists_to_add.append(upl)
            else:
                plan.playlists_to_edit.append(upl)

    def _onSyncError(self, error_msg: str):
        """Called when sync diff fails."""
        self.syncReview.show_error(error_msg)

    def hideSyncReview(self):
        """Return to the main browsing view."""
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
            artwork_needs_sync=original_plan.artwork_needs_sync if original_plan else False,
            artwork_missing_count=original_plan.artwork_missing_count if original_plan else 0,
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

        # Start sync execution worker
        self._sync_execute_worker = SyncExecuteWorker(
            ipod_path=device_manager.device_path,
            plan=filtered_plan,
            skip_backup=skip_backup,
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

    def _rescanAfterSync(self):
        """Rescan the iPod database after a short post-write delay."""
        cache = iTunesDBCache.get_instance()
        cache.invalidate()
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

    def closeEvent(self, a0):
        """Ensure all threads are stopped when the window is closed."""
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


# =============================================================================
# _DeviceRenameWorker — background thread for iPod rename (full DB rewrite)
# =============================================================================

class _DeviceRenameWorker(QThread):
    """Rewrite the iTunesDB after renaming the iPod (master playlist title)."""

    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, ipod_path: str):
        super().__init__()
        self._ipod_path = ipod_path

    def run(self):
        try:
            from SyncEngine.sync_executor import SyncExecutor

            executor = SyncExecutor(self._ipod_path)
            existing_db = executor._read_existing_database()
            existing_tracks_data = existing_db["tracks"]
            existing_playlists_raw = list(existing_db["playlists"])
            existing_smart_raw = list(existing_db["smart_playlists"])

            all_tracks = [
                executor._track_dict_to_info(t) for t in existing_tracks_data
            ]

            playlists, smart_playlists = executor._build_and_evaluate_playlists(
                existing_tracks_data, all_tracks,
                existing_playlists_raw, existing_smart_raw,
            )

            success = executor._write_database(
                all_tracks,
                playlists=playlists,
                smart_playlists=smart_playlists,
            )

            if success:
                self.finished_ok.emit()
            else:
                self.failed.emit("Database write returned False.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))
