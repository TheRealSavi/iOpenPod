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
from ..styles import Colors, FONT_FAMILY, Metrics, table_css

log = logging.getLogger(__name__)


# =============================================================================
# Formatters - Shared formatters + local display-specific ones
# =============================================================================

from .formatters import format_size, format_duration_mmss  # noqa: E402


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


def format_media_type(value: int) -> str:
    """Format media type bitmask as human-readable string."""
    from iTunesDB_Shared.constants import MEDIA_TYPE_MAP
    if value in MEDIA_TYPE_MAP:
        return MEDIA_TYPE_MAP[value]
    # Fallback: decode known bits
    names = []
    _BITS = {
        0x01: "Audio", 0x02: "Video", 0x04: "Podcast",
        0x06: "Video Podcast", 0x08: "Audiobook",
        0x20: "Music Video", 0x40: "TV Show",
        0x4000: "Ringtone",
    }
    for bit, name in _BITS.items():
        if value & bit:
            names.append(name)
    return " | ".join(names) if names else str(value) if value else ""


def format_volume(vol: int) -> str:
    """Format volume adjustment (-255 to +255) as a percentage string."""
    if not vol:
        return ""
    pct = round(vol / 255 * 100)
    return f"+{pct}%" if pct > 0 else f"{pct}%"


def format_explicit(flag: int) -> str:
    """Format explicit/clean flag (0=none, 1=explicit, 2=clean)."""
    if flag == 1:
        return "Explicit"
    if flag == 2:
        return "Clean"
    return ""


def format_checked(val: int) -> str:
    """Format the 'checked' field (0=checked, 1=unchecked — inverted)."""
    if val == 0:
        return "✓"
    return ""


def format_bool_flag(val: int) -> str:
    """Format a 0/1 flag as Yes/empty."""
    return "Yes" if val else ""


def format_compilation(val: int) -> str:
    """Format compilation flag."""
    return "Yes" if val else ""


def format_sound_check(val: int) -> str:
    """Format Sound Check value as dB gain."""
    if not val:
        return ""
    import math
    try:
        db = 10 * math.log10(val / 1000.0)
        return f"{db:+.1f} dB"
    except (ValueError, ZeroDivisionError):
        return str(val)


def format_rating(stars_x20: int) -> str:
    """Format rating (0-100, stars x 20) as star display."""
    if not stars_x20:
        return ""
    stars = stars_x20 // 20
    return "★" * stars + "☆" * (5 - stars)


def format_dbid(val: int) -> str:
    """Format 64-bit dbid as hex."""
    if not val:
        return ""
    return f"0x{val:016X}"


def format_samples(val: int) -> str:
    """Format large sample counts with comma separators."""
    if not val:
        return ""
    return f"{val:,}"


# =============================================================================
# Column Configuration
# =============================================================================

# Maps internal key -> (display_name, optional_formatter)
COLUMN_CONFIG: dict[str, tuple[str, Callable[[int], str] | None]] = {
    # ── Playlist position (synthetic) ──
    "_pl_pos": ("#", None),
    # ── Core metadata ──
    "Title": ("Title", None),
    "Artist": ("Artist", None),
    "Album": ("Album", None),
    "Album Artist": ("Album Artist", None),
    "Genre": ("Genre", None),
    "Composer": ("Composer", None),
    "Comment": ("Comment", None),
    "Grouping": ("Grouping", None),
    "year": ("Year", None),
    "track_number": ("Track #", None),
    "total_tracks": ("Track Total", None),
    "disc_number": ("Disc #", None),
    "total_discs": ("Disc Total", None),
    "compilation_flag": ("Compilation", format_compilation),
    "bpm": ("BPM", None),
    # ── Playback ──
    "length": ("Time", format_duration),
    "rating": ("Rating", format_rating),
    "play_count_1": ("Plays", None),
    "play_count_2": ("Plays (iPod)", None),
    "skip_count": ("Skips", None),
    "last_played": ("Last Played", format_date),
    "last_skipped": ("Last Skipped", format_date),
    "start_time": ("Start Time", format_duration),
    "stop_time": ("Stop Time", format_duration),
    "bookmark_time": ("Bookmark Time", format_duration),
    "checked_flag": ("Checked", format_checked),
    "not_played_flag": ("Played", format_bool_flag),
    "sound_check": ("Sound Check", format_sound_check),
    "volume": ("Volume Adj.", format_volume),
    # ── File / encoding info ──
    "filetype": ("Format", None),
    "bitrate": ("Bitrate", format_bitrate),
    "sample_rate_1": ("Sample Rate", format_sample_rate),
    "size": ("Size", format_size),
    "vbr_flag": ("VBR", format_bool_flag),
    "media_type": ("Media Type", format_media_type),
    "explicit_flag": ("Explicit", format_explicit),
    "encoder": ("Encoder", None),
    # ── Dates ──
    "date_added": ("Date Added", format_date),
    "last_modified": ("Date Modified", format_date),
    "date_released": ("Release Date", format_date),
    # ── Sort override fields ──
    "Sort Title": ("Sort Title", None),
    "Sort Artist": ("Sort Artist", None),
    "Sort Album": ("Sort Album", None),
    "Sort Album Artist": ("Sort Album Artist", None),
    "Sort Composer": ("Sort Composer", None),
    "Sort Show": ("Sort Show", None),
    # ── Video / TV Show ──
    "Show": ("Show", None),
    "season_number": ("Season", None),
    "episode_number": ("Episode #", None),
    "Episode": ("Episode ID", None),
    "TV Network": ("Network", None),
    "Description Text": ("Description", None),
    "Subtitle": ("Subtitle", None),
    # ── Podcast ──
    "Category": ("Category", None),
    "Podcast Enclosure URL": ("Enclosure URL", None),
    "Podcast RSS URL": ("RSS URL", None),
    "podcast_flag": ("Podcast", format_bool_flag),
    # ── Gapless ──
    "gapless_track_flag": ("Gapless", format_bool_flag),
    "gapless_album_flag": ("Gapless Album", format_bool_flag),
    "pregap": ("Pre-gap", format_samples),
    "postgap": ("Post-gap", format_samples),
    "sample_count": ("Sample Count", format_samples),
    "gapless_audio_payload_size": ("Gapless Payload", format_samples),
    # ── Flags ──
    "skip_when_shuffling": ("Skip Shuffle", format_bool_flag),
    "remember_position": ("Remember Pos.", format_bool_flag),
    "lyrics_flag": ("Has Lyrics", format_bool_flag),
    # ── Artwork ──
    "artwork_count": ("Art Count", None),
    "artwork_id_ref": ("Artwork Ref", None),
    # ── Identifiers (diagnostic) ──
    "track_id": ("Track ID", None),
    "db_id": ("DBID", format_dbid),
    "album_id": ("Album ID", None),
    "artist_id_ref": ("Artist Ref", None),
    "composer_id": ("Composer ID", None),
    # ── EQ ──
    "EQ Setting": ("Equalizer", None),
    # ── File path ──
    "Location": ("Location", None),
    # ── Extra string tags ──
    "Lyrics": ("Lyrics", None),
    "Track Keywords": ("Keywords", None),
    "Show Locale": ("Locale", None),
}

# Preferred column order — controls the order columns appear when auto-
# building the list AND the order they appear in the "Add Column" menu.
# Every key in COLUMN_CONFIG should appear here; anything omitted is
# appended at the end.
PREFERRED_COLUMN_ORDER = [
    # Core identity
    "Title", "Artist", "Album", "Album Artist", "Genre", "Composer",
    "year", "track_number", "total_tracks", "disc_number", "total_discs",
    "compilation_flag", "bpm",
    # Playback / stats
    "length", "rating", "play_count_1", "play_count_2", "skip_count",
    "last_played", "last_skipped", "checked_flag", "not_played_flag",
    # Audio quality
    "filetype", "bitrate", "sample_rate_1", "size", "vbr_flag", "encoder",
    # Volume / normalization
    "sound_check", "volume",
    # Dates
    "date_added", "last_modified", "date_released",
    # Tags
    "Comment", "Grouping", "explicit_flag",
    # Sort overrides
    "Sort Title", "Sort Artist", "Sort Album",
    "Sort Album Artist", "Sort Composer", "Sort Show",
    # Video / TV
    "media_type", "Show", "season_number", "episode_number",
    "Episode", "TV Network", "Description Text", "Subtitle",
    # Podcast
    "Category", "podcast_flag",
    "Podcast Enclosure URL", "Podcast RSS URL",
    # Playback range
    "start_time", "stop_time", "bookmark_time",
    # Gapless
    "gapless_track_flag", "gapless_album_flag",
    "pregap", "postgap", "sample_count", "gapless_audio_payload_size",
    # Flags
    "skip_when_shuffling", "remember_position", "lyrics_flag",
    # Artwork
    "artwork_count", "artwork_id_ref",
    # Identifiers
    "track_id", "db_id", "album_id", "artist_id_ref", "composer_id",
    # EQ
    "EQ Setting",
    # File path
    "Location",
    # Extra tags
    "Lyrics", "Track Keywords", "Show Locale",
]

# ── Per-media-type default column sets ────────────────────────────────────────

# Music (default)
DEFAULT_COLUMNS = [
    "Title", "Artist", "Album", "Genre", "year",
    "track_number", "length", "rating", "play_count_1",
    "date_added",
]

# Music videos / Movies
DEFAULT_VIDEO_COLUMNS = [
    "Title", "Artist", "Album", "length",
    "media_type", "size", "bitrate", "date_added",
    "rating", "play_count_1",
]

# Podcasts
DEFAULT_PODCAST_COLUMNS = [
    "Title", "Artist", "Album", "length",
    "date_released", "play_count_1", "not_played_flag",
    "Description Text", "date_added",
]

# Audiobooks
DEFAULT_AUDIOBOOK_COLUMNS = [
    "Title", "Artist", "Album", "length",
    "bookmark_time", "play_count_1", "rating", "date_added",
]

# Columns that should be right-aligned (numeric)
NUMERIC_COLUMNS = frozenset({
    "_pl_pos", "year", "track_number", "total_tracks", "disc_number", "total_discs",
    "bpm", "play_count_1", "play_count_2", "skip_count", "volume",
    "season_number", "episode_number", "artwork_count", "artwork_id_ref",
    "track_id", "album_id", "artist_id_ref", "composer_id",
    "pregap", "postgap", "sample_count", "gapless_audio_payload_size",
})

# Columns whose raw value should be stored in UserRole for correct numeric sorting.
# Includes all integer/float columns and formatted columns (size, bitrate, etc.).
SORTABLE_NUMERIC_KEYS = frozenset({
    "_pl_pos",
    # Core numeric
    "year", "track_number", "total_tracks", "disc_number", "total_discs",
    "bpm", "compilation_flag",
    # Playback stats
    "length", "rating", "play_count_1", "play_count_2", "skip_count",
    "start_time", "stop_time", "bookmark_time",
    "checked_flag", "not_played_flag", "sound_check", "volume",
    # File info
    "bitrate", "size", "sample_rate_1", "vbr_flag",
    "media_type", "explicit_flag",
    # Dates
    "date_added", "last_played", "last_modified", "last_skipped", "date_released",
    # Video/Podcast
    "season_number", "episode_number", "podcast_flag",
    # Gapless
    "gapless_track_flag", "gapless_album_flag",
    "pregap", "postgap", "sample_count", "gapless_audio_payload_size",
    # Flags
    "skip_when_shuffling", "remember_position", "lyrics_flag",
    # Artwork / IDs
    "artwork_count", "artwork_id_ref",
    "track_id", "db_id", "album_id", "artist_id_ref", "composer_id",
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
        self._status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._status_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; padding: 3px 8px;"
        )
        self._layout.addWidget(self._status_label)

        # Data state
        self._all_tracks: list[dict] = []      # Complete track list from device
        self._tracks: list[dict] = []          # Currently displayed (filtered) tracks
        self._columns: list[str] = DEFAULT_COLUMNS.copy()
        self._current_filter: dict | None = None
        self._media_type_filter: int | None = None  # Persisted from loadTracks()
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
        self._font = QFont(FONT_FAMILY, Metrics.FONT_MD)

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

        t.setStyleSheet(table_css())

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

    def loadTracks(self, media_type_filter: int | None = None) -> None:
        """Load all tracks from the cache and apply current filter.

        Args:
            media_type_filter: If set, only include tracks whose mediaType
                               has this bit set (bitwise AND).  mediaType 0
                               ("Audio/Video") passes both audio and video
                               filters, matching iTunes behaviour.
        """
        from ..app import iTunesDBCache

        cache = iTunesDBCache.get_instance()
        if not cache.is_ready():
            return

        self._media_type_filter = media_type_filter
        self._all_tracks = cache.get_tracks()

        if media_type_filter is not None:
            self._all_tracks = [
                t for t in self._all_tracks
                if t.get("media_type", 1) == 0  # type 0 = "Audio/Video", shows everywhere
                or (t.get("media_type", 1) & media_type_filter)
            ]

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
        self._media_type_filter = None
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
        """Ensure tracks are loaded before filtering (without populating table).

        Respects the media type filter set by the most recent loadTracks() call
        so that filterByAlbum/Artist/Genre don't reintroduce excluded tracks.
        """
        if not self._all_tracks:
            from ..app import iTunesDBCache

            cache = iTunesDBCache.get_instance()
            if cache.is_ready():
                self._all_tracks = cache.get_tracks()
                mf = getattr(self, "_media_type_filter", None)
                if mf is not None:
                    self._all_tracks = [
                        t for t in self._all_tracks
                        if t.get("media_type", 1) == 0
                        or (t.get("media_type", 1) & mf)
                    ]

    def _setup_columns(self) -> None:
        """Determine which columns to display based on available data."""
        # Choose appropriate defaults based on media type filter
        mf = getattr(self, "_media_type_filter", None)
        is_video = mf is not None and (mf & 0x62) and not (mf & 0x01)
        is_podcast = mf is not None and (mf & 0x04) != 0 and not is_video
        is_audiobook = mf is not None and (mf & 0x08) != 0 and not is_video
        if is_video:
            defaults = DEFAULT_VIDEO_COLUMNS
        elif is_podcast:
            defaults = DEFAULT_PODCAST_COLUMNS
        elif is_audiobook:
            defaults = DEFAULT_AUDIOBOOK_COLUMNS
        else:
            defaults = DEFAULT_COLUMNS

        if not self._tracks:
            self._columns = [c for c in defaults if c not in self._hidden_columns]
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
            # Show only the media-type defaults (user can add more via header menu)
            base = [k for k in defaults
                    if k in available_keys and k not in self._hidden_columns]

        self._columns = base

        # Prepend playlist position column when in playlist mode
        if self._is_playlist_mode and "_pl_pos" not in self._columns and "_pl_pos" not in self._hidden_columns:
            self._columns.insert(0, "_pl_pos")

    # -------------------------------------------------------------------------
    # Internal - Table Population
    # -------------------------------------------------------------------------

    def _cancel_population(self) -> None:
        """Cancel any in-progress population."""
        self._load_id += 1
        self._pending_rows = []
        self._is_populating = False

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

            # Store column keys in header items' UserRole so that
            # _refresh_visible_rows can map columns back to track dict keys.
            col_offset = 1 if self._show_art else 0
            for ci, key in enumerate(columns):
                h_item = self.table.horizontalHeaderItem(ci + col_offset)
                if h_item:
                    h_item.setData(Qt.ItemDataRole.UserRole, key)

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
            pass  # Widget deleted

    def _populate_next_batch(self) -> None:
        """Populate the next batch of rows. Called via QTimer for incremental loading."""
        try:
            # Check for cancellation FIRST
            if self._current_load_id != self._load_id:
                self._is_populating = False
                return

            if not self._pending_rows:
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
            log.warning(f"_populate_next_batch: RuntimeError: {e}")
            self._is_populating = False
            self._pending_rows = []
        except Exception as e:
            log.warning(f"_populate_next_batch: Exception: {e}")
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

            # Request artwork load for this track's artwork_id_ref
            mhii_link = track.get("artwork_id_ref")
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
                pil_img, _dcol, _album_colors = result
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
                dpr = self.table.devicePixelRatio()
                phys = round(ART_THUMB_SIZE * dpr)
                pixmap = QPixmap.fromImage(qimg).scaled(
                    phys, phys,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                pixmap.setDevicePixelRatio(dpr)
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
        # Determine context-appropriate noun from media type filter
        mf = getattr(self, "_media_type_filter", None)
        if mf is not None and mf & 0x62 and not (mf & 0x01):
            noun = "video"
        elif mf is not None and mf == 0x04:
            noun = "episode"  # Podcast episodes
        elif mf is not None and mf == 0x08:
            noun = "audiobook"
        elif mf is not None and mf == 0x01:
            noun = "song"
        else:
            noun = "track"
        noun_pl = noun + "s" if total != 1 else noun
        shown_pl = noun + "s" if shown != 1 else noun
        if total == 0:
            self._status_label.setText("")
        elif shown == total or self._current_filter is None:
            self._status_label.setText(f"{total:,} {noun_pl}")
        else:
            self._status_label.setText(
                f"{shown:,} of {total:,} {shown_pl}"
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

            # Wheel events: horizontal trackpad swipe, shift+wheel, normal wheel
            if etype == QEvent.Type.Wheel:
                we: QWheelEvent = event  # type: ignore[assignment]
                dx = we.angleDelta().x()
                dy = we.angleDelta().y()

                # Shift + wheel → horizontal scroll (mouse wheel users)
                if we.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    hbar = self.table.horizontalScrollBar()
                    if hbar:
                        delta = dy or dx
                        hbar.setValue(hbar.value() - delta)
                    return True

                # Trackpad horizontal swipe (dx dominant, dy near zero)
                # Let it through to both scrollbars naturally
                hbar = self.table.horizontalScrollBar()
                vbar = self.table.verticalScrollBar()
                if hbar and dx != 0:
                    hbar.setValue(hbar.value() - dx)
                # Vertical: scroll exactly one row per notch
                if vbar and dy != 0:
                    if dy > 0:
                        vbar.setValue(vbar.value() - 1)
                    else:
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
                background: {Colors.MENU_BG};
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

        # ── "Add Column" cascade with grouped sub-menus ──
        add_menu = menu.addMenu("Add Column")
        if add_menu:
            add_menu.setStyleSheet(menu.styleSheet())

            shown = set(self._columns)

            # Groups map column keys to a human-readable category.
            # Order here controls the sub-menu order.
            _COLUMN_GROUPS: list[tuple[str, list[str]]] = [
                ("Core Metadata", [
                    "Title", "Artist", "Album", "Album Artist",
                    "Genre", "Composer", "Comment", "Grouping",
                    "year", "track_number", "total_tracks",
                    "disc_number", "total_discs", "compilation_flag", "bpm",
                ]),
                ("Playback & Stats", [
                    "length", "rating", "play_count_1", "play_count_2",
                    "skip_count", "last_played", "last_skipped",
                    "checked_flag", "not_played_flag",
                    "start_time", "stop_time", "bookmark_time",
                ]),
                ("Audio Quality", [
                    "filetype", "bitrate", "sample_rate_1", "size",
                    "vbr_flag", "encoder", "sound_check", "volume",
                ]),
                ("Dates", [
                    "date_added", "last_modified", "date_released",
                ]),
                ("Sort Overrides", [
                    "Sort Title", "Sort Artist", "Sort Album",
                    "Sort Album Artist", "Sort Composer", "Sort Show",
                ]),
                ("Video & TV", [
                    "media_type", "Show", "season_number",
                    "episode_number", "Episode", "TV Network",
                    "Description Text", "Subtitle",
                ]),
                ("Podcast", [
                    "Category", "podcast_flag",
                    "Podcast Enclosure URL", "Podcast RSS URL",
                ]),
                ("Gapless", [
                    "gapless_track_flag", "gapless_album_flag",
                    "pregap", "postgap", "sample_count",
                    "gapless_audio_payload_size",
                ]),
                ("Flags", [
                    "skip_when_shuffling", "remember_position",
                    "lyrics_flag", "explicit_flag",
                ]),
                ("Artwork", [
                    "artwork_count", "artwork_id_ref",
                ]),
                ("Identifiers", [
                    "track_id", "db_id", "album_id",
                    "artist_id_ref", "composer_id",
                ]),
                ("Other", [
                    "EQ Setting", "Location", "Lyrics",
                    "Track Keywords", "Show Locale", "_pl_pos",
                ]),
            ]

            any_available = False
            grouped_keys: set[str] = set()
            for group_name, keys in _COLUMN_GROUPS:
                avail = [k for k in keys if k not in shown and k in COLUMN_CONFIG]
                grouped_keys.update(keys)
                if not avail:
                    continue
                any_available = True
                sub = add_menu.addMenu(group_name)
                if sub:
                    sub.setStyleSheet(menu.styleSheet())
                    for key in avail:
                        display_name = COLUMN_CONFIG[key][0]
                        act = sub.addAction(display_name)
                        if act:
                            act.triggered.connect(lambda _=False, k=key: self._show_column(k))

            # Catch any columns not listed in a group (future-proofing)
            ungrouped = [
                k for k in COLUMN_CONFIG
                if k not in shown and k not in grouped_keys
            ]
            if ungrouped:
                any_available = True
                sub = add_menu.addMenu("Other")
                if sub:
                    sub.setStyleSheet(menu.styleSheet())
                    for key in ungrouped:
                        display_name = COLUMN_CONFIG[key][0]
                        act = sub.addAction(display_name)
                        if act:
                            act.triggered.connect(lambda _=False, k=key: self._show_column(k))

            if not any_available:
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
        menu_style = f"""
            QMenu {{
                background: {Colors.MENU_BG};
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
        """
        menu.setStyleSheet(menu_style)

        cache = iTunesDBCache.get_instance()

        # ── "Add to Playlist >" cascade ──
        if cache.is_ready():
            playlists = cache.get_playlists()

            # Filter to regular (non-master, non-smart, non-podcast) playlists
            regular = [
                pl for pl in playlists
                if not pl.get("master_flag") and not pl.get("smart_playlist_data") and pl.get("_source") != "smart" and pl.get("podcast_flag", 0) != 1 and pl.get("_source") != "podcast"  # smart_playlist_data was smartPlaylistData
            ]

            add_menu = menu.addMenu("Add to Playlist")
            if add_menu:
                add_menu.setStyleSheet(menu_style)

                if regular:
                    for pl in regular:
                        title = pl.get("Title", "Untitled")
                        act = add_menu.addAction(title)
                        if act:
                            act.triggered.connect(
                                lambda _=False, p=pl: self._add_selected_to_playlist(p)
                            )
                else:
                    no_act = add_menu.addAction("(no playlists)")
                    if no_act:
                        no_act.setEnabled(False)

        # ── "Remove from Playlist" (only for editable regular playlists) ──
        if (self._is_playlist_mode and self._current_playlist
                and not self._current_playlist.get("master_flag")
                and not self._current_playlist.get("smart_playlist_data")  # was smartPlaylistData
                and self._current_playlist.get("_source") not in ("smart", "podcast")
                and self._current_playlist.get("podcast_flag", 0) != 1):
            menu.addSeparator()
            n = len(selected)
            label = f"Remove {n} Track{'s' if n != 1 else ''} from Playlist"
            remove_act = menu.addAction(label)
            if remove_act:
                remove_act.triggered.connect(self._remove_selected_from_playlist)

        # ── Track Flags ──
        menu.addSeparator()
        self._build_flag_menu(menu, menu_style, selected, cache)

        # ── Rating ──
        self._build_rating_menu(menu, menu_style, selected, cache)

        # ── Volume Adjustment ──
        self._build_volume_menu(menu, menu_style, selected)

        # ── Start/Stop Time ──
        self._build_start_stop_menu(menu, menu_style, selected)

        vp = self.table.viewport()
        global_pos = vp.mapToGlobal(pos) if vp else QCursor.pos()
        menu.exec(global_pos)

    # ── Flag & Rating Sub-menus ──────────────────────────────────────────

    def _build_flag_menu(self, menu: QMenu, style: str, selected: list[dict], cache) -> None:
        """Add boolean flag toggle actions to the context menu.

        Each flag shows a check mark (✓) when ALL selected tracks have it
        enabled, a dash (–) for mixed state, or blank when all disabled.
        Clicking toggles: all-on → off, otherwise → on.
        """
        # Standard boolean flags (0=off, 1=on)
        FLAG_DEFS: list[tuple[str, str, str]] = [
            # (track_dict_key, menu_label, description)
            ("compilation_flag", "Compilation", "Part of a compilation album"),
            ("skip_when_shuffling", "Skip When Shuffling", "Skip this track in shuffle mode"),
            ("remember_position", "Remember Playback Position", "Resume from last position (audiobooks)"),
            ("gapless_track_flag", "Gapless Track", "Enable gapless playback for this track"),
            ("gapless_album_flag", "Gapless Album", "Enable gapless playback for this album"),
        ]

        for key, label, _tip in FLAG_DEFS:
            on_count = sum(1 for t in selected if t.get(key, 0))
            total = len(selected)

            if on_count == total:
                prefix = "✓  "
                new_val = 0  # toggle off
            elif on_count == 0:
                prefix = "    "
                new_val = 1  # toggle on
            else:
                prefix = "–  "
                new_val = 1  # mixed → on

            act = menu.addAction(f"{prefix}{label}")
            if act:
                act.triggered.connect(
                    lambda _=False, k=key, v=new_val: self._set_track_flag(k, v)
                )

        # ── Inverted flag: 'checked' (0=checked, 1=unchecked) ──
        checked_count = sum(1 for t in selected if t.get("checked", 0) == 0)
        total = len(selected)
        if checked_count == total:
            prefix = "✓  "
            new_val = 1  # uncheck
        elif checked_count == 0:
            prefix = "    "
            new_val = 0  # check
        else:
            prefix = "–  "
            new_val = 0  # mixed → check
        act = menu.addAction(f"{prefix}Checked")
        if act:
            act.triggered.connect(
                lambda _=False, v=new_val: self._set_track_flag("checked", v)
            )

        # ── Played Mark (for podcasts: 0=not played, 2=played) ──
        played_count = sum(1 for t in selected if t.get("not_played_flag", 0) != 0)  # was playedMark
        if played_count == total:
            prefix = "✓  "
            new_val = 0  # mark as unplayed
        elif played_count == 0:
            prefix = "    "
            new_val = 2  # mark as played
        else:
            prefix = "–  "
            new_val = 2  # mixed → played
        act = menu.addAction(f"{prefix}Mark as Played")
        if act:
            act.triggered.connect(
                lambda _=False, v=new_val: self._set_track_flag("not_played_flag", v)  # was playedMark
            )

    def _build_rating_menu(self, menu: QMenu, style: str, selected: list[dict], cache) -> None:
        """Add a Rating submenu with 0-5 star options."""
        rating_menu = menu.addMenu("Rating")
        if not rating_menu:
            return
        rating_menu.setStyleSheet(style)

        # Current rating (show check for unanimous value)
        current_ratings = {t.get("rating", 0) for t in selected}
        unanimous = current_ratings.pop() if len(current_ratings) == 1 else None

        stars = [
            (0, "No Rating"),
            (20, "★"),
            (40, "★★"),
            (60, "★★★"),
            (80, "★★★★"),
            (100, "★★★★★"),
        ]
        for value, label in stars:
            prefix = "✓ " if unanimous == value else "   "
            act = rating_menu.addAction(f"{prefix}{label}")
            if act:
                act.triggered.connect(
                    lambda _=False, v=value: self._set_track_flag("rating", v)
                )

    def _build_volume_menu(self, menu: QMenu, style: str, selected: list[dict]) -> None:
        """Add a Volume Adjustment submenu with common presets (-100% to +100%)."""
        vol_menu = menu.addMenu("Volume Adjustment")
        if not vol_menu:
            return
        vol_menu.setStyleSheet(style)

        # Current volume (show check for unanimous value)
        current_vols = {t.get("volume", 0) for t in selected}
        unanimous = current_vols.pop() if len(current_vols) == 1 else None

        # iPod volume range: -255 to +255.  Show as percentage.
        presets = [
            (-255, "−100%"),
            (-191, "−75%"),
            (-128, "−50%"),
            (-64, "−25%"),
            (0, "None (0%)"),
            (64, "+25%"),
            (128, "+50%"),
            (191, "+75%"),
            (255, "+100%"),
        ]
        for value, label in presets:
            prefix = "✓ " if unanimous == value else "   "
            act = vol_menu.addAction(f"{prefix}{label}")
            if act:
                act.triggered.connect(
                    lambda _=False, v=value: self._set_track_flag("volume", v)
                )

    def _build_start_stop_menu(self, menu: QMenu, style: str, selected: list[dict]) -> None:
        """Add Start/Stop Time submenu with Set and Clear actions."""
        menu.addSeparator()

        # ── Start Time ────────────────────────────────────────────────
        start_menu = menu.addMenu("Start Time")
        if start_menu:
            start_menu.setStyleSheet(style)
            # Current value display (if unanimous across selection)
            start_vals = {t.get("start_time", 0) for t in selected}  # was startTime
            if len(start_vals) == 1:
                val = start_vals.pop()
                if val:
                    info_act = start_menu.addAction(f"Current: {format_duration(val)}")
                    if info_act:
                        info_act.setEnabled(False)

            act_set = start_menu.addAction("Set Start Time…")
            if act_set:
                act_set.triggered.connect(
                    lambda _=False: self._prompt_time("start_time", selected)  # was startTime
                )
            has_start = any(t.get("start_time", 0) for t in selected)  # was startTime
            if has_start:
                act_clear = start_menu.addAction("Clear Start Time")
                if act_clear:
                    act_clear.triggered.connect(
                        lambda _=False: self._set_track_flag("start_time", 0)  # was startTime
                    )

        # ── Stop Time ─────────────────────────────────────────────────
        stop_menu = menu.addMenu("Stop Time")
        if stop_menu:
            stop_menu.setStyleSheet(style)
            stop_vals = {t.get("stop_time", 0) for t in selected}  # was stopTime
            if len(stop_vals) == 1:
                val = stop_vals.pop()
                if val:
                    info_act = stop_menu.addAction(f"Current: {format_duration(val)}")
                    if info_act:
                        info_act.setEnabled(False)

            act_set = stop_menu.addAction("Set Stop Time…")
            if act_set:
                act_set.triggered.connect(
                    lambda _=False: self._prompt_time("stop_time", selected)  # was stopTime
                )
            has_stop = any(t.get("stop_time", 0) for t in selected)  # was stopTime
            if has_stop:
                act_clear = stop_menu.addAction("Clear Stop Time")
                if act_clear:
                    act_clear.triggered.connect(
                        lambda _=False: self._set_track_flag("stop_time", 0)  # was stopTime
                    )

    def _prompt_time(self, key: str, selected: list[dict]) -> None:
        """Show a dialog to set start or stop time in mm:ss format."""
        from PyQt6.QtWidgets import QInputDialog

        label = "Start Time" if key == "start_time" else "Stop Time"  # was startTime/stopTime

        # Pre-fill with current value if all selected tracks agree
        vals = {t.get(key, 0) for t in selected}
        default_text = ""
        if len(vals) == 1:
            ms = vals.pop()
            if ms:
                total_sec = ms // 1000
                m, s = divmod(total_sec, 60)
                default_text = f"{m}:{s:02d}"

        text, ok = QInputDialog.getText(
            self, f"Set {label}",
            f"Enter {label.lower()} (m:ss or mm:ss):",
            text=default_text,
        )
        if not ok or not text.strip():
            return

        # Parse mm:ss or m:ss or just seconds
        text = text.strip()
        try:
            if ":" in text:
                parts = text.split(":")
                minutes = int(parts[0])
                seconds = int(parts[1])
            else:
                minutes = 0
                seconds = int(text)
            ms = (minutes * 60 + seconds) * 1000
            if ms < 0:
                return
        except (ValueError, IndexError):
            return

        self._set_track_flag(key, ms)

    def _set_track_flag(self, key: str, value: int) -> None:
        """Apply a flag/field change to all selected tracks via the cache."""
        from ..app import iTunesDBCache

        selected = self._get_selected_tracks()
        if not selected:
            return

        cache = iTunesDBCache.get_instance()
        if not cache.is_ready():
            return

        cache.update_track_flags(selected, {key: value})

        # Refresh visible rows so the change is immediately visible
        # (rating column, or future flag columns)
        self._refresh_visible_rows()

    def _refresh_visible_rows(self) -> None:
        """Re-populate currently visible rows from their track dicts.

        Lightweight alternative to a full repopulate — only touches the
        cells that are already on screen.  Useful after in-place edits to
        track dicts (flags, ratings, etc.).
        """
        if not self._tracks:
            return

        first_data_col = 1 if self._show_art else 0
        col_count = self.table.columnCount()
        row_count = self.table.rowCount()

        for row in range(row_count):
            item = self.table.item(row, first_data_col)
            if item is None:
                continue
            orig_idx = item.data(Qt.ItemDataRole.UserRole + 1)
            if orig_idx is None or orig_idx < 0 or orig_idx >= len(self._tracks):
                continue
            track = self._tracks[orig_idx]

            for col in range(first_data_col, col_count):
                h_item = self.table.horizontalHeaderItem(col)
                if h_item is None:
                    continue
                key = h_item.data(Qt.ItemDataRole.UserRole)
                if key is None:
                    continue

                raw = track.get(key, "")
                cfg = COLUMN_CONFIG.get(key)
                formatter = cfg[1] if cfg else None

                # Use the same formatting logic as _format_value():
                # skip only None/"", let 0 through to the formatter
                # (0 is meaningful for fields like 'checked', 'explicitFlag')
                if raw is None or raw == "":
                    display_text = ""
                elif formatter and isinstance(raw, (int, float)):
                    try:
                        display_text = formatter(int(raw))
                    except Exception:
                        display_text = str(raw)
                else:
                    display_text = str(raw)

                cell = self.table.item(row, col)
                if cell is not None:
                    cell.setText(display_text)
                    if key in SORTABLE_NUMERIC_KEYS:
                        cell.setData(Qt.ItemDataRole.UserRole, raw if raw else 0)

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
        existing_ids = {item.get("track_id", 0) for item in items}

        added = 0
        for track in selected:
            tid = track.get("track_id")
            if tid is not None and tid not in existing_ids:
                items.append({"track_id": tid})
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
                 added, title, playlist.get("playlist_id", 0))

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

        remove_ids = {t.get("track_id") for t in selected}
        items = list(playlist.get("items", []))
        new_items = [item for item in items if item.get("track_id") not in remove_ids]
        removed = len(items) - len(new_items)

        if removed == 0:
            return

        playlist["items"] = new_items
        playlist.setdefault("_source", "regular")
        cache.save_user_playlist(playlist)

        # Refresh the displayed track list
        track_id_index = cache.get_track_id_index()
        track_ids = [item.get("track_id", 0) for item in new_items]
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
                 removed, title, playlist.get("playlist_id", 0))

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
