"""
MBListView.py - Track list view with filtering support.

This module provides a table view for displaying and filtering music tracks.
It handles incremental loading for large datasets and is designed to be
robust against rapid user interactions (spam-clicking).
"""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QPixmap, QImage, QIcon, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from ..styles import Colors

log = logging.getLogger(__name__)


# =============================================================================
# Formatters - Shared formatters + local display-specific ones
# =============================================================================

from .formatters import format_size, format_duration_mmss, format_rating  # noqa: E402


def format_duration(ms: int) -> str:
    """Format milliseconds as M:SS or H:MM:SS (empty string for 0)."""
    if not ms or ms <= 0:
        return ""
    return format_duration_mmss(ms)


def format_bitrate(bitrate: int) -> str:
    """Format bitrate with kbps suffix."""
    if not bitrate or bitrate <= 0:
        return ""
    return f"{bitrate} kbps"


def format_sample_rate(rate: int) -> str:
    """Format sample rate in kHz."""
    if not rate or rate <= 0:
        return ""
    return f"{rate / 1000:.1f} kHz"


def format_date(unix_timestamp: int) -> str:
    """Format Unix timestamp as YYYY-MM-DD."""
    if not unix_timestamp or unix_timestamp <= 0:
        return ""
    from datetime import datetime
    try:
        return datetime.fromtimestamp(unix_timestamp).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return ""


# =============================================================================
# Column Configuration
# =============================================================================

# Maps internal key -> (display_name, optional_formatter)
COLUMN_CONFIG: dict[str, tuple[str, Callable[[int], str] | None]] = {
    "Title": ("Title", None),
    "Artist": ("Artist", None),
    "Album": ("Album", None),
    "Album Artist": ("Album Artist", None),
    "Genre": ("Genre", None),
    "year": ("Year", None),
    "length": ("Time", format_duration),
    "rating": ("Rating", format_rating),
    "playCount": ("Plays", None),
    "skipCount": ("Skips", None),
    "bitrate": ("Bitrate", format_bitrate),
    "size": ("Size", format_size),
    "sampleRate": ("Sample Rate", format_sample_rate),
    "trackNumber": ("#", None),
    "discNumber": ("Disc", None),
    "dateAdded": ("Added", format_date),
    "lastPlayed": ("Last Played", format_date),
    "bpm": ("BPM", None),
    "Composer": ("Composer", None),
    "filetype": ("Format", None),
}

# Preferred column order when displaying tracks
PREFERRED_COLUMN_ORDER = [
    "Title", "Artist", "Album", "Album Artist", "Genre",
    "year", "length", "rating", "playCount", "skipCount",
    "trackNumber", "discNumber", "bitrate", "dateAdded", "lastPlayed",
]

# Default columns shown when no specific selection
DEFAULT_COLUMNS = ["Title", "Artist", "Album", "Genre", "length", "rating", "playCount"]

# Columns that should be right-aligned (numeric)
NUMERIC_COLUMNS = frozenset({"year", "playCount", "skipCount", "trackNumber", "discNumber", "bpm"})

# Batch size for incremental population (rows per timer tick)
# Keep small to avoid blocking UI
BATCH_SIZE = 50

# Artwork thumbnail size in pixels for the track list
ART_THUMB_SIZE = 32


# =============================================================================
# MusicBrowserList - Main Table Widget
# =============================================================================

class MusicBrowserList(QFrame):
    """
    Track list view with filtering support.

    Handles display of music tracks in a sortable, filterable table.
    Uses incremental loading for large datasets (>500 tracks) to maintain
    UI responsiveness. Robust against rapid user interactions.
    """

    def __init__(self):
        super().__init__()

        # Layout
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Table widget
        self.table = QTableWidget()
        self._layout.addWidget(self.table)
        self._setup_table()

        # Data state
        self._all_tracks: list[dict] = []      # Complete track list from device
        self._tracks: list[dict] = []          # Currently displayed (filtered) tracks
        self._columns: list[str] = DEFAULT_COLUMNS.copy()
        self._current_filter: dict | None = None

        # Population state - used for incremental loading and cancellation
        self._load_id = 0           # Incremented on each load; invalidates pending work
        self._current_load_id = 0   # Load ID when current population started
        self._pending_rows: list[int] = []
        self._is_populating = False

        # Artwork state
        self._show_art = False      # Controlled by settings
        self._art_cache: dict[int, QPixmap] = {}   # mhiiLink → scaled QPixmap
        self._art_pending: set[int] = set()         # mhiiLinks currently being loaded

        # Shared resources (created once, reused)
        self._font = QFont("Segoe UI", 10)

    # -------------------------------------------------------------------------
    # Properties for backwards compatibility
    # -------------------------------------------------------------------------

    @property
    def all_tracks(self) -> list[dict]:
        return self._all_tracks

    @all_tracks.setter
    def all_tracks(self, value: list[dict]):
        self._all_tracks = value

    @property
    def tracks(self) -> list[dict]:
        return self._tracks

    @tracks.setter
    def tracks(self, value: list[dict]):
        self._tracks = value

    @property
    def final_column_order(self) -> list[str]:
        return self._columns

    @final_column_order.setter
    def final_column_order(self, value: list[str]):
        self._columns = value

    # -------------------------------------------------------------------------
    # Table Setup
    # -------------------------------------------------------------------------

    def _setup_table(self) -> None:
        """Configure table appearance and behavior."""
        t = self.table
        t.setSortingEnabled(True)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)

        t.setStyleSheet(f"""
            QTableWidget {{
                background-color: rgba(0,0,0,20);
                alternate-background-color: rgba(255,255,255,4);
                border: none;
                color: {Colors.TEXT_PRIMARY};
                gridline-color: {Colors.GRIDLINE};
                selection-background-color: {Colors.SELECTION};
                outline: none;
            }}
            QTableWidget::item {{
                padding: 6px 8px;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
            QTableWidget::item:selected {{
                background-color: {Colors.SELECTION};
            }}
            QTableWidget::item:hover {{
                background-color: rgba(255,255,255,6);
            }}
            QHeaderView::section {{
                background-color: {Colors.SURFACE_ALT};
                color: {Colors.TEXT_SECONDARY};
                padding: 6px 8px;
                border: none;
                border-bottom: 1px solid {Colors.BORDER};
                font-weight: 600;
                font-size: 11px;
            }}
            QHeaderView::section:hover {{
                background-color: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_PRIMARY};
            }}
            QHeaderView::section:pressed {{
                background-color: {Colors.SURFACE_ACTIVE};
            }}
            /* Corner button (top-left) */
            QTableCornerButton::section {{
                background-color: {Colors.SURFACE_ALT};
                border: none;
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)

        header = t.horizontalHeader()
        if header:
            header.setSectionsMovable(True)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.setStretchLastSection(True)
            header.setDefaultSectionSize(150)

    # -------------------------------------------------------------------------
    # Public API - Loading and Filtering
    # -------------------------------------------------------------------------

    def loadTracks(self) -> None:
        """Load all tracks from the cache and apply current filter."""
        from ..app import iTunesDBCache

        cache = iTunesDBCache.get_instance()
        if not cache.is_ready():
            return

        self._all_tracks = cache.get_tracks()

        if self._current_filter:
            self.applyFilter(self._current_filter)
        else:
            self.showAllTracks()

    def showAllTracks(self) -> None:
        """Display all tracks without filtering."""
        self._current_filter = None
        self._tracks = self._all_tracks
        self._setup_columns()
        self._populate_table()

    def clearFilter(self) -> None:
        """Clear the current filter without reloading data."""
        self._current_filter = None

    def filterByAlbum(self, album: str, artist: str | None = None) -> None:
        """Filter to show only tracks from a specific album."""
        self._ensure_tracks_loaded()
        self._current_filter = {"type": "album", "album": album, "artist": artist}

        if artist:
            self._tracks = [t for t in self._all_tracks
                            if t.get("Album") == album and t.get("Artist") == artist]
        else:
            self._tracks = [t for t in self._all_tracks if t.get("Album") == album]

        self._setup_columns()
        self._populate_table()

    def filterByArtist(self, artist: str) -> None:
        """Filter to show only tracks from a specific artist."""
        self._ensure_tracks_loaded()
        self._current_filter = {"type": "artist", "artist": artist}
        self._tracks = [t for t in self._all_tracks if t.get("Artist") == artist]
        self._setup_columns()
        self._populate_table()

    def filterByGenre(self, genre: str) -> None:
        """Filter to show only tracks of a specific genre."""
        self._ensure_tracks_loaded()
        self._current_filter = {"type": "genre", "genre": genre}
        self._tracks = [t for t in self._all_tracks if t.get("Genre") == genre]
        self._setup_columns()
        self._populate_table()

    def applyFilter(self, filter_data: dict) -> None:
        """Apply a filter from grid item selection."""
        self._ensure_tracks_loaded()

        filter_key = filter_data.get("filter_key")
        filter_value = filter_data.get("filter_value")

        if filter_key and filter_value:
            self._current_filter = filter_data
            self._tracks = [t for t in self._all_tracks if t.get(filter_key) == filter_value]
            self._setup_columns()
            self._populate_table()

    def clearTable(self) -> None:
        """Clear the table completely, cancelling any pending population."""
        self._cancel_population()
        self._all_tracks = []
        self._tracks = []
        self._current_filter = None
        self._art_cache.clear()
        self._art_pending.clear()

        try:
            self.table.setUpdatesEnabled(False)
            self.table.clearContents()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.table.setUpdatesEnabled(True)
        except RuntimeError:
            pass  # Widget deleted

    # -------------------------------------------------------------------------
    # Internal - Column Setup
    # -------------------------------------------------------------------------

    def _ensure_tracks_loaded(self) -> None:
        """Ensure tracks are loaded before filtering."""
        if not self._all_tracks:
            self.loadTracks()

    def _setup_columns(self) -> None:
        """Determine which columns to display based on available data."""
        if not self._tracks:
            self._columns = DEFAULT_COLUMNS.copy()
            return

        # Sample tracks to find available keys
        available_keys = set()
        for track in self._tracks[:100]:
            available_keys.update(track.keys())

        # Build column order: preferred columns first (if data exists)
        self._columns = [k for k in PREFERRED_COLUMN_ORDER if k in available_keys]

        # Add any remaining known columns
        for key in COLUMN_CONFIG:
            if key in available_keys and key not in self._columns:
                self._columns.append(key)

    # -------------------------------------------------------------------------
    # Internal - Table Population
    # -------------------------------------------------------------------------

    def _cancel_population(self) -> None:
        """Cancel any in-progress population."""
        old_id = self._load_id
        self._load_id += 1
        self._pending_rows = []
        self._is_populating = False
        log.debug(f"_cancel_population: {old_id} -> {self._load_id}")

    def _populate_table(self) -> None:
        """Populate the table with current tracks."""
        try:
            self._cancel_population()

            # Check artwork setting
            from ..settings import get_settings
            self._show_art = get_settings().show_art_in_tracklist

            # Capture state for this load
            load_id = self._load_id
            tracks = self._tracks
            columns = self._columns

            log.debug(f"_populate_table: load_id={load_id}, tracks={len(tracks)}")

            # Minimal setup - no setRowCount to avoid blocking!
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)  # Clear existing rows (fast when going to 0)

            # Build header list — prepend art column if enabled
            if self._show_art:
                col_count = 1 + len(columns)
                headers = [""] + [self._get_header(k) for k in columns]
            else:
                col_count = len(columns)
                headers = [self._get_header(k) for k in columns]

            self.table.setColumnCount(col_count)
            self.table.setHorizontalHeaderLabels(headers)

            if self._show_art:
                self.table.setColumnWidth(0, ART_THUMB_SIZE + 8)
                self.table.setIconSize(QSize(ART_THUMB_SIZE, ART_THUMB_SIZE))

            # Always use incremental population to keep UI responsive
            self._pending_rows = list(range(len(tracks)))
            self._current_load_id = load_id
            self._is_populating = True

            # Start population on next event loop iteration
            QTimer.singleShot(0, self._populate_next_batch)

        except RuntimeError:
            log.debug("_populate_table: RuntimeError (widget deleted)")
            pass  # Widget deleted

    def _populate_next_batch(self) -> None:
        """Populate the next batch of rows. Called via QTimer for incremental loading."""
        try:
            # Check for cancellation FIRST
            if self._current_load_id != self._load_id:
                log.debug(f"_populate_next_batch: cancelled (current={self._current_load_id}, load={self._load_id})")
                self._is_populating = False
                return

            if not self._pending_rows:
                log.debug("_populate_next_batch: no pending rows, finishing")
                self._is_populating = False
                self._finish_population()
                return

            # Capture state at start of batch
            tracks = self._tracks
            columns = self._columns
            load_id = self._current_load_id

            # Process batch - use small batches to stay responsive
            batch = self._pending_rows[:BATCH_SIZE]
            self._pending_rows = self._pending_rows[BATCH_SIZE:]

            self.table.setUpdatesEnabled(False)

            for row_idx in batch:
                # Re-check cancellation during batch
                if self._load_id != load_id:
                    self.table.setUpdatesEnabled(True)
                    self._is_populating = False
                    return

                if row_idx < len(tracks):
                    # Insert row and populate - insertRow(row) is faster than setRowCount
                    self.table.insertRow(row_idx)
                    self._populate_row(row_idx, tracks[row_idx], columns)

            self.table.setUpdatesEnabled(True)

            # Schedule next batch or finish - check cancellation again
            if self._pending_rows and self._load_id == load_id:
                QTimer.singleShot(1, self._populate_next_batch)  # 1ms delay for UI responsiveness
            else:
                self._is_populating = False
                if self._load_id == load_id:
                    self._finish_population()

        except RuntimeError as e:
            log.debug(f"_populate_next_batch: RuntimeError: {e}")
            self._is_populating = False
            self._pending_rows = []
        except Exception as e:
            log.debug(f"_populate_next_batch: Exception: {e}")
            self._is_populating = False
            self._pending_rows = []

    def _populate_row(self, row: int, track: dict, columns: list[str]) -> None:
        """Populate a single row with track data."""
        col_offset = 0

        if self._show_art:
            col_offset = 1
            # Set row height to fit the thumbnail
            self.table.setRowHeight(row, ART_THUMB_SIZE + 4)
            # Place a placeholder; actual art is loaded async after population
            art_item = QTableWidgetItem()
            art_item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable/editable
            self.table.setItem(row, 0, art_item)

            # Request artwork load for this track's mhiiLink
            mhii_link = track.get("mhiiLink")
            if mhii_link is not None:
                if mhii_link in self._art_cache:
                    art_item.setIcon(QIcon(self._art_cache[mhii_link]))
                else:
                    # Remember row for async backfill
                    art_item.setData(Qt.ItemDataRole.UserRole, mhii_link)

        for col, key in enumerate(columns):
            value = track.get(key, "")
            display = self._format_value(key, value)

            item = QTableWidgetItem(display)
            item.setFont(self._font)

            if key == "rating" and display:
                item.setForeground(QColor(Colors.STAR))
            if key in NUMERIC_COLUMNS:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.table.setItem(row, col + col_offset, item)

    def _finish_population(self) -> None:
        """Complete table population - enable sorting, resize columns, load art."""
        try:
            self.table.setSortingEnabled(True)

            header = self.table.horizontalHeader()
            if header and self._columns:
                start_col = 1 if self._show_art else 0
                total_cols = self.table.columnCount()
                # Art column: fixed width
                if self._show_art and total_cols > 0:
                    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
                    self.table.setColumnWidth(0, ART_THUMB_SIZE + 8)
                # Data columns: resize to contents, stretch last
                for i in range(start_col, total_cols - 1):
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
                if total_cols > 0:
                    header.setSectionResizeMode(total_cols - 1, QHeaderView.ResizeMode.Stretch)

            # Kick off async artwork loading
            if self._show_art:
                self._load_art_async()

        except RuntimeError:
            pass  # Widget deleted

    # -------------------------------------------------------------------------
    # Internal - Async Artwork Loading
    # -------------------------------------------------------------------------

    def _load_art_async(self) -> None:
        """Scan rows for missing artwork and load in background batches."""
        from ..app import Worker, ThreadPoolSingleton

        # Collect unique mhiiLinks that need loading
        links_to_load: set[int] = set()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            link = item.data(Qt.ItemDataRole.UserRole)
            if link is not None and link not in self._art_cache and link not in self._art_pending:
                links_to_load.add(link)

        if not links_to_load:
            return

        self._art_pending |= links_to_load
        load_id = self._load_id

        # Load in a single background worker
        worker = Worker(self._load_art_batch, list(links_to_load))
        worker.signals.result.connect(
            lambda result, lid=load_id: self._on_art_loaded(result, lid))
        ThreadPoolSingleton.get_instance().start(worker)

    def _load_art_batch(self, links: list[int]) -> dict[int, bytes | None]:
        """Background worker: decode artwork for a batch of mhiiLinks.

        Returns dict mapping mhiiLink -> (width, height, rgba_bytes) or None.
        """
        from ..app import DeviceManager
        from ..imgMaker import find_image_by_imgId, get_artworkdb_cached
        import os

        device = DeviceManager.get_instance()
        if not device.device_path:
            return {}

        artworkdb_path = device.artworkdb_path
        artwork_folder = device.artwork_folder_path
        if not artworkdb_path or not os.path.exists(artworkdb_path):
            return {}

        artworkdb_data, imgid_index = get_artworkdb_cached(artworkdb_path)
        results: dict[int, tuple[int, int, bytes] | None] = {}

        for link in links:
            if device.cancellation_token.is_cancelled():
                break
            result = find_image_by_imgId(artworkdb_data, artwork_folder, link, imgid_index)
            if result is not None:
                pil_img, _dcol = result
                pil_img = pil_img.convert("RGBA")
                results[link] = (pil_img.width, pil_img.height, pil_img.tobytes("raw", "RGBA"))
            else:
                results[link] = None

        return results

    def _on_art_loaded(self, results: dict | None, load_id: int) -> None:
        """Main-thread callback: apply loaded artwork to table rows."""
        if results is None or self._load_id != load_id:
            return

        try:
            # Convert to QPixmaps and cache
            for link, data in results.items():
                self._art_pending.discard(link)
                if data is None:
                    continue
                w, h, rgba = data
                qimg = QImage(rgba, w, h, QImage.Format.Format_RGBA8888).copy()
                pixmap = QPixmap.fromImage(qimg).scaled(
                    ART_THUMB_SIZE, ART_THUMB_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._art_cache[link] = pixmap

            # Backfill rows
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is None:
                    continue
                link = item.data(Qt.ItemDataRole.UserRole)
                if link is not None and link in self._art_cache:
                    item.setIcon(QIcon(self._art_cache[link]))
                    item.setData(Qt.ItemDataRole.UserRole, None)  # Clear pending marker

        except RuntimeError:
            pass  # Widget deleted

    # -------------------------------------------------------------------------
    # Internal - Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _get_header(key: str) -> str:
        """Get display name for a column key."""
        if key in COLUMN_CONFIG:
            return COLUMN_CONFIG[key][0]
        return key

    @staticmethod
    def _format_value(key: str, value) -> str:
        """Format a value for display based on column type."""
        if value is None or value == "":
            return ""

        config = COLUMN_CONFIG.get(key)
        if config:
            _, formatter = config
            if formatter and isinstance(value, (int, float)):
                return formatter(int(value))

        return str(value)
