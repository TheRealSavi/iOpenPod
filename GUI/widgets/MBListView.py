"""
MBListView.py - Track list view with filtering support.

This module provides a table view for displaying and filtering music tracks.
It handles incremental loading for large datasets and is designed to be
robust against rapid user interactions (spam-clicking).
"""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import Qt, QTimer, QSize, QEvent, QPoint
from PyQt6.QtGui import QFont, QPixmap, QImage, QIcon, QColor, QCursor, QKeyEvent, QWheelEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHeaderView,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from ..styles import Colors, FONT_FAMILY

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
    "_pl_pos": ("#", None),
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
NUMERIC_COLUMNS = frozenset({"year", "playCount", "skipCount", "trackNumber", "discNumber", "bpm", "_pl_pos"})

# Columns whose raw value should be stored in UserRole for correct numeric sorting.
# Includes all integer/float columns and formatted columns (size, bitrate, etc.).
SORTABLE_NUMERIC_KEYS = frozenset({
    "year", "playCount", "skipCount", "trackNumber", "discNumber", "bpm",
    "_pl_pos", "length", "rating", "bitrate", "size", "sampleRate",
    "dateAdded", "lastPlayed",
})

# Batch size for incremental population (rows per timer tick)
# Keep small to avoid blocking UI
BATCH_SIZE = 50

# Artwork thumbnail size in pixels for the track list
ART_THUMB_SIZE = 32


class _SortableItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically when UserRole data is set."""

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        my_val = self.data(Qt.ItemDataRole.UserRole)
        other_val = other.data(Qt.ItemDataRole.UserRole)
        if my_val is not None and other_val is not None:
            try:
                return float(my_val) < float(other_val)
            except (TypeError, ValueError):
                pass
        # Fall back to text comparison
        return (self.text() or "") < (other.text() or "")


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
        self._layout.setSpacing(0)

        # Table widget
        self.table = QTableWidget()
        self._layout.addWidget(self.table)
        self._setup_table()

        # Status bar (track count)
        self._status_label = QLabel()
        self._status_label.setFont(QFont(FONT_FAMILY, 9))
        self._status_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; padding: 3px 8px;"
        )
        self._layout.addWidget(self._status_label)

        # Data state
        self._all_tracks: list[dict] = []      # Complete track list from device
        self._tracks: list[dict] = []          # Currently displayed (filtered) tracks
        self._columns: list[str] = DEFAULT_COLUMNS.copy()
        self._current_filter: dict | None = None
        self._is_playlist_mode: bool = False   # True when showing a playlist in order
        self._current_playlist: dict | None = None  # The playlist dict when in playlist mode

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
        self._font = QFont(FONT_FAMILY, 10)

        # Column visibility state: keys the user has explicitly hidden
        self._hidden_columns: set[str] = set()
        # Column widths the user has set (col_key → pixels)
        self._user_col_widths: dict[str, int] = {}
        # Column visual order set by user (logical index list)
        self._user_col_order: list[str] | None = None

        # Middle-mouse grab-scroll state
        self._grab_scrolling = False
        self._grab_origin = QPoint()
        self._grab_h_value = 0
        self._grab_v_value = 0

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
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        t.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)

        # Right-click context menu on track rows
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._on_track_context_menu)

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

        vh = t.verticalHeader()
        if vh:
            vh.setVisible(False)

        header = t.horizontalHeader()
        if header:
            header.setSectionsMovable(True)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.setStretchLastSection(True)
            header.setDefaultSectionSize(150)
            header.setMinimumSectionSize(40)
            vp = header.viewport()
            if vp:
                vp.installEventFilter(self)

        # Install event filter on table viewport for scroll enhancements
        table_vp = t.viewport()
        if table_vp:
            table_vp.installEventFilter(self)
            t.setMouseTracking(True)

        t.setSortingEnabled(True)

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
        self._is_playlist_mode = False
        self._tracks = self._all_tracks
        self._setup_columns()
        self._populate_table()

    def clearFilter(self) -> None:
        """Clear the current filter without reloading data."""
        self._current_filter = None
        self._is_playlist_mode = False

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

    def filterByPlaylist(self, track_ids: list[int], track_id_index: dict[int, dict],
                         playlist: dict | None = None) -> None:
        """Show tracks belonging to a playlist, in playlist order.

        Args:
            track_ids: Ordered list of trackIDs from MHIP items.
            track_id_index: Mapping of trackID -> full track dict.
            playlist: The playlist dict (stored for context menu actions).
        """
        self._current_filter = {"type": "playlist"}
        self._is_playlist_mode = True
        self._current_playlist = playlist
        # Resolve trackIDs to track dicts, preserving playlist order
        self._tracks = []
        for tid in track_ids:
            track = track_id_index.get(tid)
            if track:
                self._tracks.append(track)
        self._setup_columns()
        self._populate_table()

    def clearTable(self) -> None:
        """Clear the table completely, cancelling any pending population."""
        self._cancel_population()
        self._all_tracks = []
        self._tracks = []
        self._current_filter = None
        self._is_playlist_mode = False
        self._current_playlist = None
        self._art_cache.clear()
        self._art_pending.clear()

        try:
            self.table.setUpdatesEnabled(False)
            self.table.clearContents()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.table.setUpdatesEnabled(True)
            self._status_label.setText("")
        except RuntimeError:
            pass  # Widget deleted

    # -------------------------------------------------------------------------
    # Internal - Column Setup
    # -------------------------------------------------------------------------

    def _ensure_tracks_loaded(self) -> None:
        """Ensure tracks are loaded before filtering (without populating table)."""
        if not self._all_tracks:
            from ..app import iTunesDBCache

            cache = iTunesDBCache.get_instance()
            if cache.is_ready():
                self._all_tracks = cache.get_tracks()

    def _setup_columns(self) -> None:
        """Determine which columns to display based on available data."""
        if not self._tracks:
            self._columns = [c for c in DEFAULT_COLUMNS if c not in self._hidden_columns]
            return

        # Sample tracks to find available keys
        available_keys = set()
        for track in self._tracks[:100]:
            available_keys.update(track.keys())

        # If user has a saved column order, respect it (filtering out unavailable)
        if self._user_col_order is not None:
            base = [k for k in self._user_col_order
                    if k in available_keys and k not in self._hidden_columns]
        else:
            # Build column order: preferred columns first (if data exists)
            base = [k for k in PREFERRED_COLUMN_ORDER
                    if k in available_keys and k not in self._hidden_columns]

            # Add any remaining known columns that aren't hidden
            for key in COLUMN_CONFIG:
                if key in available_keys and key not in base and key not in self._hidden_columns:
                    base.append(key)

        self._columns = base

        # Prepend playlist position column when in playlist mode
        if self._is_playlist_mode and "_pl_pos" not in self._columns and "_pl_pos" not in self._hidden_columns:
            self._columns.insert(0, "_pl_pos")

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

            # Capture current column state before clearing (preserves drag order & widths)
            if self.table.columnCount() > 0:
                self._save_user_widths()

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
            # Playlist position is synthetic — not from track dict
            if key == "_pl_pos":
                display = str(row + 1)
                raw_value: int | float | str = row + 1
            else:
                raw_value = track.get(key, "")
                display = self._format_value(key, raw_value)

            item = _SortableItem(display)
            item.setFont(self._font)

            # Store raw numeric value for correct sorting
            if key in SORTABLE_NUMERIC_KEYS:
                numeric = raw_value if isinstance(raw_value, (int, float)) else 0
                item.setData(Qt.ItemDataRole.UserRole, numeric)

            if key == "rating" and display:
                item.setForeground(QColor(Colors.STAR))
            if key in NUMERIC_COLUMNS:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.table.setItem(row, col + col_offset, item)

        # Store the original track index on the first data column so we can
        # recover the correct track dict even after the table is sorted.
        first_data_col = col_offset  # 0 or 1 depending on art column
        anchor = self.table.item(row, first_data_col)
        if anchor:
            anchor.setData(Qt.ItemDataRole.UserRole + 1, row)

    def _finish_population(self) -> None:
        """Complete table population - enable sorting, apply column widths, load art."""
        try:
            self.table.setSortingEnabled(True)

            # Defensively re-hide vertical header (row numbers) — Qt can
            # re-show it after setSortingEnabled / insertRow cycles.
            vh = self.table.verticalHeader()
            if vh:
                vh.setVisible(False)

            header = self.table.horizontalHeader()
            if header and self._columns:
                start_col = 1 if self._show_art else 0
                total_cols = self.table.columnCount()

                # Art column: fixed width
                if self._show_art and total_cols > 0:
                    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
                    self.table.setColumnWidth(0, ART_THUMB_SIZE + 8)

                # Data columns: interactive (user-resizable)
                for i in range(start_col, total_cols):
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

                # Re-apply header interaction properties (defensive — survives
                # column-count changes and setSortingEnabled toggling)
                header.setSectionsMovable(True)

                # Apply saved column widths, or auto-size columns that have none
                for i in range(start_col, total_cols):
                    col_key = self._col_key_at(i)
                    if col_key and col_key in self._user_col_widths:
                        self.table.setColumnWidth(i, self._user_col_widths[col_key])
                    else:
                        self.table.resizeColumnToContents(i)

                # Restore saved visual column order (from user drag-reorder)
                if self._user_col_order:
                    # Build a map from column key → current logical index
                    key_to_logical: dict[str, int] = {}
                    for li in range(start_col, total_cols):
                        k = self._col_key_at(li)
                        if k:
                            key_to_logical[k] = li
                    # Move sections to match the saved visual order
                    for target_vis, key in enumerate(self._user_col_order):
                        logical = key_to_logical.get(key)
                        if logical is None:
                            continue
                        current_vis = header.visualIndex(logical)
                        if current_vis != target_vis + start_col:
                            header.moveSection(current_vis, target_vis + start_col)

                # Stretch the last column
                header.setStretchLastSection(True)

                # Re-install event filter (defensive — survives population)
                vp = header.viewport()
                if vp:
                    vp.installEventFilter(self)

            # Kick off async artwork loading
            if self._show_art:
                self._load_art_async()

            self._update_status()

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

    def _load_art_batch(self, links: list[int]) -> dict[int, tuple[int, int, bytes] | None]:
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

    def _update_status(self) -> None:
        """Update the status label with track count info."""
        shown = len(self._tracks)
        total = len(self._all_tracks)
        if total == 0:
            self._status_label.setText("")
        elif shown == total or self._current_filter is None:
            self._status_label.setText(f"{total:,} track{'s' if total != 1 else ''}")
        else:
            self._status_label.setText(
                f"{shown:,} of {total:,} track{'s' if total != 1 else ''}"
            )

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

    def _col_key_at(self, visual_col: int) -> str | None:
        """Return the column key for a given visual column index."""
        offset = 1 if self._show_art else 0
        logical = visual_col - offset
        if 0 <= logical < len(self._columns):
            return self._columns[logical]
        return None

    # -------------------------------------------------------------------------
    # Event Filter — catch right-click on header viewport
    # -------------------------------------------------------------------------

    def eventFilter(self, obj, event):  # type: ignore[override]
        """Intercept events on header viewport (right-click menu) and
        table viewport (shift+scroll horizontal, middle-mouse grab scroll)."""
        header = self.table.horizontalHeader()

        # ── Header viewport: right-click context menu ──
        if header and obj is header.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.RightButton:
                    self._on_header_context_menu(event.pos())
                    return True

        # ── Table viewport: scroll & grab ──
        table_vp = self.table.viewport()
        if table_vp and obj is table_vp:
            etype = event.type()

            # Shift + wheel → horizontal scroll
            if etype == QEvent.Type.Wheel:
                we: QWheelEvent = event  # type: ignore[assignment]
                if we.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    hbar = self.table.horizontalScrollBar()
                    if hbar:
                        delta = we.angleDelta().y() or we.angleDelta().x()
                        hbar.setValue(hbar.value() - delta)
                    return True

                # Normal wheel → scroll exactly one row per notch
                vbar = self.table.verticalScrollBar()
                if vbar:
                    delta_y = we.angleDelta().y()
                    if delta_y > 0:
                        vbar.setValue(vbar.value() - 1)
                    elif delta_y < 0:
                        vbar.setValue(vbar.value() + 1)
                return True

            # Middle-mouse press → start grab scroll
            if etype == QEvent.Type.MouseButtonPress:
                me: QMouseEvent = event  # type: ignore[assignment]
                if me.button() == Qt.MouseButton.MiddleButton:
                    self._grab_scrolling = True
                    self._grab_origin = me.pos()
                    hbar = self.table.horizontalScrollBar()
                    vbar = self.table.verticalScrollBar()
                    self._grab_h_value = hbar.value() if hbar else 0
                    self._grab_v_value = vbar.value() if vbar else 0
                    self.table.setCursor(Qt.CursorShape.ClosedHandCursor)
                    return True

            # Middle-mouse move → drag scroll
            if etype == QEvent.Type.MouseMove and self._grab_scrolling:
                me = event  # type: ignore[assignment]
                delta = me.pos() - self._grab_origin
                hbar = self.table.horizontalScrollBar()
                vbar = self.table.verticalScrollBar()
                if hbar:
                    hbar.setValue(self._grab_h_value - delta.x())
                if vbar:
                    vbar.setValue(self._grab_v_value - delta.y())
                return True

            # Middle-mouse release → stop grab scroll
            if etype == QEvent.Type.MouseButtonRelease:
                me = event  # type: ignore[assignment]
                if me.button() == Qt.MouseButton.MiddleButton and self._grab_scrolling:
                    self._grab_scrolling = False
                    self.table.unsetCursor()
                    return True

        return super().eventFilter(obj, event)

    # -------------------------------------------------------------------------
    # Header Context Menu — hide / show / reorder columns
    # -------------------------------------------------------------------------

    def _on_header_context_menu(self, pos) -> None:
        """Show context menu when right-clicking a column header."""
        header = self.table.horizontalHeader()
        if not header:
            return

        clicked_visual = header.logicalIndexAt(pos)
        clicked_key = self._col_key_at(clicked_visual)

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                padding: 4px 0;
            }}
            QMenu::item {{
                padding: 6px 24px 6px 12px;
            }}
            QMenu::item:selected {{
                background: {Colors.ACCENT_DIM};
            }}
            QMenu::separator {{
                height: 1px;
                background: {Colors.BORDER_SUBTLE};
                margin: 4px 8px;
            }}
        """)

        # ── "Hide <column>" action ──
        if clicked_key and clicked_key in COLUMN_CONFIG:
            display_name = COLUMN_CONFIG[clicked_key][0]
            hide_act = menu.addAction(f"Hide \"{display_name}\"")
            if hide_act:
                hide_act.triggered.connect(lambda _=False, k=clicked_key: self._hide_column(k))
            menu.addSeparator()

        # ── "Add Column" cascade ──
        add_menu = menu.addMenu("Add Column")
        if add_menu:
            add_menu.setStyleSheet(menu.styleSheet())

            # Gather columns that are currently hidden or not shown
            shown = set(self._columns)
            available = []
            for key in PREFERRED_COLUMN_ORDER:
                if key not in shown and key in COLUMN_CONFIG:
                    available.append(key)
            for key in COLUMN_CONFIG:
                if key not in shown and key not in available:
                    available.append(key)

            if available:
                for key in available:
                    display_name = COLUMN_CONFIG[key][0]
                    # Disambiguate duplicate display names
                    label = f"{display_name}  ({key})" if key != display_name else display_name
                    act = add_menu.addAction(label)
                    if act:
                        act.triggered.connect(lambda _=False, k=key: self._show_column(k))
            else:
                no_act = add_menu.addAction("(all columns shown)")
                if no_act:
                    no_act.setEnabled(False)

        # ── "Reset Columns" ──
        menu.addSeparator()
        reset_act = menu.addAction("Reset Columns")
        if reset_act:
            reset_act.triggered.connect(self._reset_columns)

        menu.exec(QCursor.pos())

    def _hide_column(self, key: str) -> None:
        """Hide a column by key."""
        # Don't allow hiding the last visible column
        if len(self._columns) <= 1:
            return
        self._save_user_widths()
        self._hidden_columns.add(key)
        if key in self._columns:
            self._columns.remove(key)
        self._repopulate_keeping_state()

    def _show_column(self, key: str) -> None:
        """Show a previously hidden column."""
        self._save_user_widths()
        self._hidden_columns.discard(key)
        # Insert at end (user can drag to reorder)
        if key not in self._columns:
            self._columns.append(key)
        self._repopulate_keeping_state()

    def _reset_columns(self) -> None:
        """Reset to default column set and widths."""
        self._hidden_columns.clear()
        self._user_col_widths.clear()
        self._user_col_order = None
        self._setup_columns()
        self._populate_table()

    def _save_user_widths(self) -> None:
        """Snapshot current column widths and visual order before repopulating."""
        header = self.table.horizontalHeader()
        if not header:
            return
        offset = 1 if self._show_art else 0
        col_count = self.table.columnCount()

        # Save widths
        for i in range(offset, col_count):
            key = self._col_key_at(i)
            if key:
                self._user_col_widths[key] = header.sectionSize(i)

        # Save visual order (the order the user sees after dragging)
        visual_keys: list[str] = []
        for vis in range(offset, col_count):
            logical = header.logicalIndex(vis)
            key = self._col_key_at(logical)
            if key:
                visual_keys.append(key)
        if visual_keys:
            self._user_col_order = visual_keys

    def _repopulate_keeping_state(self) -> None:
        """Re-populate using the current self._columns (already adjusted)."""
        self._populate_table()

    # -------------------------------------------------------------------------
    # Track Context Menu (right-click on rows)
    # -------------------------------------------------------------------------

    def _get_selected_tracks(self) -> list[dict]:
        """Return track dicts for all currently selected rows."""
        selected_rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not selected_rows:
            return []

        first_data_col = 1 if self._show_art else 0
        tracks: list[dict] = []
        for row in selected_rows:
            item = self.table.item(row, first_data_col)
            if item is None:
                continue
            orig_idx = item.data(Qt.ItemDataRole.UserRole + 1)
            if orig_idx is not None and 0 <= orig_idx < len(self._tracks):
                tracks.append(self._tracks[orig_idx])
        return tracks

    def _on_track_context_menu(self, pos) -> None:
        """Show context menu when right-clicking on track rows."""
        selected = self._get_selected_tracks()
        if not selected:
            return

        from ..app import iTunesDBCache

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                padding: 4px 0;
            }}
            QMenu::item {{
                padding: 6px 24px 6px 12px;
            }}
            QMenu::item:selected {{
                background: {Colors.ACCENT_DIM};
            }}
            QMenu::separator {{
                height: 1px;
                background: {Colors.BORDER_SUBTLE};
                margin: 4px 8px;
            }}
        """)

        # ── "Add to Playlist >" cascade ──
        cache = iTunesDBCache.get_instance()
        if cache.is_ready():
            playlists = cache.get_playlists()

            # Filter to regular (non-master, non-smart, non-podcast) playlists
            regular = [
                pl for pl in playlists
                if not pl.get("isMaster") and not pl.get("isSmartPlaylist") and pl.get("_source") != "smart" and pl.get("podcastFlag", 0) != 1 and pl.get("_source") != "podcast"
            ]

            add_menu = menu.addMenu("Add to Playlist")
            if add_menu:
                add_menu.setStyleSheet(menu.styleSheet())

                if regular:
                    for pl in regular:
                        title = pl.get("Title", "Untitled")
                        act = add_menu.addAction(f"📋  {title}")
                        if act:
                            act.triggered.connect(
                                lambda _=False, p=pl: self._add_selected_to_playlist(p)
                            )
                else:
                    no_act = add_menu.addAction("(no playlists)")
                    if no_act:
                        no_act.setEnabled(False)

        vp = self.table.viewport()
        global_pos = vp.mapToGlobal(pos) if vp else QCursor.pos()

        # ── "Remove from Playlist" (only for editable regular playlists) ──
        if (self._is_playlist_mode and self._current_playlist
                and not self._current_playlist.get("isMaster")
                and not self._current_playlist.get("isSmartPlaylist")
                and self._current_playlist.get("_source") not in ("smart", "podcast")
                and self._current_playlist.get("podcastFlag", 0) != 1):
            menu.addSeparator()
            n = len(selected)
            label = f"Remove {n} Track{'s' if n != 1 else ''} from Playlist"
            remove_act = menu.addAction(label)
            if remove_act:
                remove_act.triggered.connect(self._remove_selected_from_playlist)

        menu.exec(global_pos)

    def _add_selected_to_playlist(self, playlist: dict) -> None:
        """Add all selected tracks to the given playlist and save it."""
        from ..app import iTunesDBCache

        selected = self._get_selected_tracks()
        if not selected:
            return

        cache = iTunesDBCache.get_instance()
        if not cache.is_ready():
            return

        # Gather existing trackIDs in the playlist to avoid duplicates
        items = list(playlist.get("items", []))
        existing_ids = {item.get("trackID", 0) for item in items}

        added = 0
        for track in selected:
            tid = track.get("trackID")
            if tid is not None and tid not in existing_ids:
                items.append({"trackID": tid})
                existing_ids.add(tid)
                added += 1

        if added == 0:
            log.info("No new tracks to add (all already in playlist '%s')",
                     playlist.get("Title", "?"))
            return

        playlist["items"] = items
        # Ensure it's tagged as a regular user playlist
        playlist.setdefault("_source", "regular")

        cache.save_user_playlist(playlist)

        title = playlist.get("Title", "Untitled")
        log.info("Added %d track(s) to playlist '%s' (id=0x%X)",
                 added, title, playlist.get("playlistID", 0))

    def _remove_selected_from_playlist(self) -> None:
        """Remove selected tracks from the current playlist and save it."""
        from ..app import iTunesDBCache

        playlist = self._current_playlist
        if not playlist:
            return

        selected = self._get_selected_tracks()
        if not selected:
            return

        cache = iTunesDBCache.get_instance()
        if not cache.is_ready():
            return

        remove_ids = {t.get("trackID") for t in selected}
        items = list(playlist.get("items", []))
        new_items = [item for item in items if item.get("trackID") not in remove_ids]
        removed = len(items) - len(new_items)

        if removed == 0:
            return

        playlist["items"] = new_items
        playlist.setdefault("_source", "regular")
        cache.save_user_playlist(playlist)

        # Refresh the displayed track list
        track_id_index = cache.get_track_id_index()
        track_ids = [item.get("trackID", 0) for item in new_items]
        self._current_filter = {"type": "playlist"}
        self._is_playlist_mode = True
        self._current_playlist = playlist
        self._tracks = []
        for tid in track_ids:
            track = track_id_index.get(tid)
            if track:
                self._tracks.append(track)
        self._setup_columns()
        self._populate_table()

        title = playlist.get("Title", "Untitled")
        log.info("Removed %d track(s) from playlist '%s' (id=0x%X)",
                 removed, title, playlist.get("playlistID", 0))

    # -------------------------------------------------------------------------
    # Keyboard Shortcuts
    # -------------------------------------------------------------------------

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        """Handle keyboard shortcuts (Ctrl+C to copy selected rows)."""
        if a0 and a0.key() == Qt.Key.Key_C and a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._copy_selection()
            return
        super().keyPressEvent(a0)

    def _copy_selection(self) -> None:
        """Copy selected rows as tab-separated text to clipboard."""
        selected_rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not selected_rows:
            return

        header = self.table.horizontalHeader()
        if not header:
            return

        offset = 1 if self._show_art else 0
        col_count = self.table.columnCount()

        # Build visual-order column indices (skip art column)
        vis_cols = []
        for vis in range(offset, col_count):
            vis_cols.append(header.logicalIndex(vis))

        # Header line
        headers = []
        for logical in vis_cols:
            h_item = self.table.horizontalHeaderItem(logical)
            headers.append(h_item.text() if h_item else "")
        lines = ["\t".join(headers)]

        # Data lines
        for row in selected_rows:
            cells = []
            for logical in vis_cols:
                item = self.table.item(row, logical)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText("\n".join(lines))
