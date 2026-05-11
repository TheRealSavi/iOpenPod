"""
MBListView.py - Track list view with filtering support.

This module provides a table view for displaying and filtering music tracks.
It handles incremental loading for large datasets and is designed to be
robust against rapid user interactions (spam-clicking).
"""

from __future__ import annotations

import logging
import random
import sys as _sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QIcon, QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap, QWheelEvent
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
    QWidget,
)

from ..artwork_rendering import (
    enhance_artwork_image,
    nested_artwork_radius,
    rounded_artwork_pixmap,
)
from ..glyphs import glyph_icon
from ..hidpi import scale_pixmap_for_display
from ..styles import FONT_FAMILY, Colors, Metrics, table_css
from .formatters import format_duration_mmss, format_size

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app_core.services import (
        DeviceSessionService,
        LibraryCacheLike,
        SettingsService,
    )

# Platform-correct modifier key labels for menu shortcut hints.
_CTRL = "⌘" if _sys.platform == "darwin" else "Ctrl"
_ALT = "⌥" if _sys.platform == "darwin" else "Alt"
del _sys


# =============================================================================
# Formatters - Shared formatters + local display-specific ones
# =============================================================================


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


def format_db_track_id(val: int) -> str:
    """Format 64-bit db_track_id as hex."""
    if not val:
        return ""
    return f"0x{val:016X}"


def format_samples(val: int) -> str:
    """Format large sample counts with comma separators."""
    if not val:
        return ""
    return f"{val:,}"


def _named_qcolor(value: str) -> QColor:
    """Build a QColor from a CSS-style color string in a type-checker-friendly way."""
    color = QColor()
    color.setNamedColor(value)
    return color


def build_new_regular_playlist(
    selected_tracks: list[dict],
    *,
    title: str = "New Playlist",
) -> dict | None:
    """Build a new regular playlist payload from selected tracks."""
    items: list[dict[str, int]] = []
    for track in selected_tracks:
        track_id = track.get("track_id")
        if track_id:
            items.append({"track_id": int(track_id)})

    if not items:
        return None

    return {
        "Title": title,
        "playlist_id": random.getrandbits(64),
        "_isNew": True,
        "_source": "regular",
        "items": items,
    }


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
    "db_track_id": ("db_track_id", format_db_track_id),
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
    "track_id", "db_track_id", "album_id", "artist_id_ref", "composer_id",
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
    "track_id", "db_track_id", "album_id", "artist_id_ref", "composer_id",
})

# Batch size for incremental population (rows per timer tick)
# Keep small to avoid blocking UI
BATCH_SIZE = 50
ART_LOAD_BATCH_SIZE = 20

# Artwork thumbnail size in pixels for the track list
ART_THUMB_SIZE = 32
ART_THUMB_COLUMN_PADDING = 12
COLUMN_LAYOUT_SAVE_DELAY_MS = 150


def _art_column_width() -> int:
    """Return the fixed artwork column width with enough room for Qt icon insets."""
    return ART_THUMB_SIZE + ART_THUMB_COLUMN_PADDING


def _column_width_map(value: object) -> dict[str, int]:
    """Normalize a persisted compact column layout."""
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, raw in value.items():
        if isinstance(key, str) and isinstance(raw, int) and not isinstance(raw, bool):
            normalized[key] = raw
    return normalized


def _normalize_column_layouts(value: object) -> dict[str, dict[str, int]]:
    """Return compact per-content column layouts from settings."""
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, dict[str, int]] = {}
    for content_key, raw_layout in value.items():
        if not isinstance(content_key, str) or not isinstance(raw_layout, dict):
            continue

        layout = _column_width_map(raw_layout)
        if layout:
            normalized[content_key] = layout
    return normalized


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
# _DragProgressWidget — floating overlay showing per-track prep progress
# =============================================================================

class _DragProgressWidget(QWidget):
    """Small frameless popup that tracks prep state for each exported file."""

    def __init__(self, tracks: list[dict]) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._rows: list[QLabel] = []
        self._done = 0
        n = len(tracks)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._container = QFrame()
        self._container.setObjectName("dpWrap")
        inner = QVBoxLayout(self._container)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(3)

        self._header = QLabel(f"Preparing {n} file{'s' if n != 1 else ''}…")
        self._header.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
        inner.addWidget(self._header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        inner.addWidget(sep)

        for track in tracks:
            title = track.get("Title") or "Unknown"
            artist = track.get("Artist") or track.get("Album Artist") or ""
            text = f"{artist} – {title}" if artist else title
            if len(text) > 44:
                text = text[:41] + "…"
            lbl = QLabel(f"  ○  {text}")
            lbl.setFont(QFont(FONT_FAMILY, 9))
            inner.addWidget(lbl)
            self._rows.append(lbl)

        outer.addWidget(self._container)
        self._apply_style()

    def _apply_style(self) -> None:
        self._container.setStyleSheet(f"""
            QFrame#dpWrap {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
            }}
            QLabel {{
                color: {Colors.TEXT_PRIMARY};
                background: transparent;
            }}
            QFrame[frameShape="4"] {{
                color: {Colors.BORDER_SUBTLE};
                background: transparent;
            }}
        """)

    def mark_done(self, idx: int) -> None:
        if 0 <= idx < len(self._rows):
            lbl = self._rows[idx]
            lbl.setText(lbl.text().replace("  ○  ", "  ✓  "))
            lbl.setStyleSheet(f"color: {Colors.ACCENT_LIGHT}; background: transparent;")
            self._done += 1
            if self._done == len(self._rows):
                self._header.setText("Starting drag…")
                self._header.setStyleSheet(
                    f"color: {Colors.ACCENT_LIGHT}; background: transparent;"
                )


# =============================================================================
# _FilePrepThread — background file copy + artwork embed for Alt+drag export
# =============================================================================

class _FilePrepThread(QThread):
    """Copies selected iPod tracks to a temp dir, embeds artwork, emits URLs."""

    files_ready = pyqtSignal(list)   # list[QUrl]
    prep_failed = pyqtSignal(str)
    track_done = pyqtSignal(int)    # index in tracks list, emitted as each finishes

    def __init__(self, tracks: list, ipod_root: str, artworkdb_path: str,
                 artwork_folder: str, temp_dir: str) -> None:
        super().__init__()
        self._tracks = tracks
        self._ipod_root = ipod_root
        self._artworkdb_path = artworkdb_path
        self._artwork_folder = artwork_folder
        self._temp_dir = temp_dir

    def run(self) -> None:
        import io
        import os
        import re
        import shutil
        from concurrent.futures import ThreadPoolExecutor

        from PyQt6.QtCore import QUrl

        try:
            if os.path.isfile(self._artworkdb_path):
                from ..imgMaker import configure_artwork_api
                configure_artwork_api(self._artworkdb_path, self._artwork_folder)

            def _safe(s: str) -> str:
                return re.sub(r'[\\/:*?"<>|]', "_", s).strip() or "Unknown"

            def _prep_one(idx: int, track: dict) -> QUrl | None:
                """Copy one track and embed its artwork. Returns QUrl or None."""
                location = track.get("Location", "")
                if not location:
                    return None
                relative = location.replace(":", "/").lstrip("/")
                src = os.path.join(self._ipod_root, relative)
                if not os.path.isfile(src):
                    return None
                ext = os.path.splitext(src)[1].lower() or ".m4a"
                artist = track.get("Artist") or track.get("Album Artist") or "Unknown Artist"
                title = track.get("Title") or "Unknown Title"
                # Include index so same-named tracks don't clobber each other
                base = f"{_safe(artist)} - {_safe(title)}"
                dest = os.path.join(self._temp_dir,
                                    f"{base}{ext}" if idx == 0 else f"{base} ({idx + 1}){ext}")
                shutil.copy2(src, dest)

                artwork_id = MusicBrowserList._track_artwork_id(track)
                if artwork_id is not None:
                    try:
                        from ..imgMaker import get_artwork
                        pil_img = get_artwork(artwork_id, mode="image_only")
                        if pil_img is not None:
                            buf = io.BytesIO()
                            pil_img.convert("RGB").save(buf, format="JPEG", quality=90)
                            _embed_artwork(dest, ext, buf.getvalue())
                    except Exception:
                        pass  # artwork failure is non-fatal

                return QUrl.fromLocalFile(dest)

            from concurrent.futures import as_completed
            n_workers = min(len(self._tracks), 8)
            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                futures = [executor.submit(_prep_one, i, t)
                           for i, t in enumerate(self._tracks)]
                future_to_idx = {f: i for i, f in enumerate(futures)}
                for done in as_completed(future_to_idx):
                    self.track_done.emit(future_to_idx[done])
                # All futures complete by here (executor.__exit__ ensures it)
                urls = [r for f in futures for r in (f.result(),) if r is not None]

            if urls:
                self.files_ready.emit(urls)
            else:
                self.prep_failed.emit("No valid files to export")
        except Exception as exc:
            self.prep_failed.emit(str(exc))


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

    remove_from_ipod_requested = pyqtSignal(list)

    def __init__(
        self,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
        *,
        library_cache: LibraryCacheLike | None = None,
        show_art_override: bool | None = None,
        content_type_override: str | None = None,
    ):
        super().__init__()
        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._library_cache = library_cache
        self._show_art_override = show_art_override
        self._content_type_override = content_type_override

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
            f" border-top: 1px solid {Colors.BORDER_SUBTLE};"
            " background: transparent;"
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
        self._art_cache: dict[int, QPixmap] = {}   # artwork_id -> scaled source pixmap
        self._art_display_cache: dict[tuple[int, bool], QPixmap] = {}
        self._art_pending: set[int] = set()        # artwork_ids currently being loaded

        # Shared resources (created once, reused)
        self._font = QFont(FONT_FAMILY, Metrics.FONT_MD)
        self._advisory_icon_cache: dict[tuple[int, int], QIcon] = {}

        # Column widths the user has set (col_key → pixels)
        self._user_col_widths: dict[str, int] = {}
        # Column visual order set by user (logical index list)
        self._user_col_order: list[str] | None = None
        self._column_layouts = _normalize_column_layouts(
            getattr(
                self._settings_service.get_global_settings(),
                "track_list_columns_by_content",
                {},
            )
        )
        self._active_column_content_key: str | None = None
        self._applying_column_layout = False
        self._column_layout_dirty = False
        self._header_interaction_signature: tuple[tuple[str, ...], tuple[tuple[str, int], ...]] | None = None
        self._column_layout_save_timer = QTimer(self)
        self._column_layout_save_timer.setSingleShot(True)
        self._column_layout_save_timer.timeout.connect(
            self.flush_pending_column_changes
        )
        # Separate debounce timer for width resizes (prevents spamming during drag)
        self._width_resize_debounce_timer = QTimer(self)
        self._width_resize_debounce_timer.setSingleShot(True)
        self._width_resize_debounce_timer.timeout.connect(
            self._on_width_resize_debounce_timeout
        )

        # Middle-mouse grab-scroll state
        self._grab_scrolling = False
        self._grab_origin = QPoint()
        self._grab_h_value = 0
        self._grab_v_value = 0

        # Left-mouse drag-to-OS state
        self._drag_start_pos: QPoint | None = None
        self._drag_start_tracks: list[dict] = []   # snapshot taken before table clears selection
        self._drag_prep_thread: _FilePrepThread | None = None
        self._drag_orphan_threads: list[_FilePrepThread] = []  # cancelled threads kept alive until done
        self._drag_progress_widget: _DragProgressWidget | None = None

        # Ctrl+Alt+C clipboard-copy-as-files state
        self._clip_prep_thread: _FilePrepThread | None = None
        self._clip_orphan_threads: list[_FilePrepThread] = []
        self._clip_progress_widget: _DragProgressWidget | None = None

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
    # Playlist reorder helpers
    # -------------------------------------------------------------------------

    def _is_reorderable_playlist(self) -> bool:
        """True when showing a regular playlist with manual sort order."""
        if not self._is_playlist_mode or not self._current_playlist:
            return False
        pl = self._current_playlist
        if pl.get("master_flag"):
            return False
        if pl.get("smart_playlist_data") or pl.get("_source") in ("smart", "podcast"):
            return False
        if pl.get("podcast_flag", 0) == 1:
            return False
        # Only allow manual reorder when sort_order is Manual (1) or Default (0)
        sort_order = pl.get("sort_order", 0)
        if sort_order not in (0, 1):
            return False
        return True

    def _move_selected_rows(self, direction: int) -> None:
        """Move selected rows up (-1) or down (+1) within a reorderable playlist.

        Swaps table cells in-place (no full repopulate), updates ``_tracks``
        and the playlist items list, then schedules a debounced quick sync.
        """
        if not self._is_reorderable_playlist():
            return

        selected_rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not selected_rows:
            return

        n = self.table.rowCount()
        if direction < 0 and selected_rows[0] <= 0:
            return  # already at top
        if direction > 0 and selected_rows[-1] >= n - 1:
            return  # already at bottom

        # Process in the right order so swaps don't collide
        if direction < 0:
            for row in selected_rows:
                self._swap_adjacent_rows(row, row - 1)
        else:
            for row in reversed(selected_rows):
                self._swap_adjacent_rows(row, row + 1)

        # Update selection to follow the moved rows
        new_rows = [r + direction for r in selected_rows]
        self.table.clearSelection()
        for r in new_rows:
            if 0 <= r < n:
                self.table.selectRow(r)

        self._commit_playlist_reorder()

    def _swap_adjacent_rows(self, row_a: int, row_b: int) -> None:
        """Swap two adjacent rows in both the table widget and _tracks list."""
        n = len(self._tracks)
        if not (0 <= row_a < n and 0 <= row_b < n):
            return

        # Swap in _tracks
        self._tracks[row_a], self._tracks[row_b] = self._tracks[row_b], self._tracks[row_a]

        # Swap every cell in the table
        col_count = self.table.columnCount()
        for col in range(col_count):
            item_a = self.table.takeItem(row_a, col)
            item_b = self.table.takeItem(row_b, col)
            if item_a:
                self.table.setItem(row_b, col, item_a)
            if item_b:
                self.table.setItem(row_a, col, item_b)

        # Swap row heights (matters when artwork column is shown)
        ha = self.table.rowHeight(row_a)
        hb = self.table.rowHeight(row_b)
        if ha != hb:
            self.table.setRowHeight(row_a, hb)
            self.table.setRowHeight(row_b, ha)

        # Update _pl_pos cells and original-index anchors
        first_data_col = 1 if self._show_art else 0
        pl_pos_col = self._pl_pos_column()
        for row in (row_a, row_b):
            if pl_pos_col >= 0:
                cell = self.table.item(row, pl_pos_col)
                if cell:
                    cell.setText(str(row + 1))
                    cell.setData(Qt.ItemDataRole.UserRole, row + 1)
            anchor = self.table.item(row, first_data_col)
            if anchor:
                anchor.setData(Qt.ItemDataRole.UserRole + 1, row)

    def _pl_pos_column(self) -> int:
        """Return the visual column index of _pl_pos, or -1 if absent."""
        col_offset = 1 if self._show_art else 0
        for i, key in enumerate(self._columns):
            if key == "_pl_pos":
                return i + col_offset
        return -1

    def _commit_playlist_reorder(self) -> None:
        """Persist the current _tracks order into the playlist and schedule sync."""
        playlist = self._current_playlist
        if not playlist:
            return

        old_items = playlist.get("items", [])
        tid_to_item: dict[int, dict] = {}
        for item in old_items:
            tid = item.get("track_id", 0)
            if tid:
                tid_to_item[tid] = item

        playlist["items"] = [
            tid_to_item.get(t.get("track_id", 0), {"track_id": t.get("track_id")})
            for t in self._tracks
            if t.get("track_id") is not None
        ]
        playlist.setdefault("_source", "regular")

        cache = self._library_cache
        if cache is None:
            return
        cache.save_user_playlist(playlist)
        cache.playlist_quick_sync.emit()

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
            header.sectionMoved.connect(self._on_header_section_moved)
            header.sectionResized.connect(self._on_header_section_resized)
            header.installEventFilter(self)
            vp = header.viewport()
            if vp:
                vp.installEventFilter(self)

        # Install event filter on table viewport for scroll enhancements,
        # and on the table itself to catch key events (table holds focus, not the frame)
        table_vp = t.viewport()
        if table_vp:
            table_vp.installEventFilter(self)
            t.setMouseTracking(True)
        t.installEventFilter(self)

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
        cache = self._library_cache
        if cache is None:
            return
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
        """Show tracks belonging to a playlist, sorted by its sort_order.

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

        # Apply sort order (Manual / Default leave the list as-is)
        if playlist:
            sort_order = playlist.get("sort_order", 0)
            if sort_order not in (0, 1):
                from SyncEngine._playlist_builder import sort_tracks_by_order
                self._tracks = sort_tracks_by_order(self._tracks, sort_order)

        self._setup_columns()
        self._populate_table()

    def clearTable(self, clear_cache: bool = False) -> None:
        """Clear the table completely, cancelling any pending population."""
        if (
            self._active_column_content_key
            and (
                self._column_layout_dirty
                or self._width_resize_debounce_timer.isActive()
                or self._column_layout_save_timer.isActive()
            )
        ):
            self._store_current_column_layout(self._active_column_content_key)
        self._cancel_population()
        self._all_tracks = []
        self._tracks = []
        self._current_filter = None
        self._media_type_filter = None
        self._is_playlist_mode = False
        self._current_playlist = None
        if clear_cache:
            self._art_cache.clear()
            self._art_display_cache.clear()
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
            cache = self._library_cache
            if cache is None:
                return
            if cache.is_ready():
                self._all_tracks = cache.get_tracks()
                mf = getattr(self, "_media_type_filter", None)
                if mf is not None:
                    self._all_tracks = [
                        t for t in self._all_tracks
                        if t.get("media_type", 1) == 0
                        or (t.get("media_type", 1) & mf)
                    ]

    def _content_type_key(self) -> str:
        """Return the current logical content type for column persistence."""
        if self._content_type_override:
            return self._content_type_override
        if self._is_playlist_mode:
            return "playlist"

        mf = getattr(self, "_media_type_filter", None)
        is_video = mf is not None and (mf & 0x62) and not (mf & 0x01)
        is_podcast = mf is not None and (mf & 0x04) != 0 and not is_video
        is_audiobook = mf is not None and (mf & 0x08) != 0 and not is_video

        if is_video:
            return "video"
        if is_podcast:
            return "podcast"
        if is_audiobook:
            return "audiobook"
        return "music"

    def _apply_saved_column_layout(self, content_key: str) -> None:
        """Load the persisted ordered column widths for one content type."""
        layout = self._column_layouts.get(content_key, {})
        self._user_col_order = list(layout) or None
        self._user_col_widths = dict(layout)

    def _store_current_column_layout(self, content_key: str | None) -> None:
        """Capture the current table layout into the per-content settings map."""
        if not content_key:
            return

        if self.table.columnCount() > 0:
            self._save_user_widths()

        layout: dict[str, int] = {}
        for key in list(self._user_col_order or self._columns):
            width = self._user_col_widths.get(key)
            if isinstance(width, int) and width > 0:
                layout[key] = int(width)
        self._column_layouts[content_key] = layout

    def _ensure_column_layout_for_current_content(self) -> None:
        """Swap in the saved layout when the list changes content type."""
        content_key = self._content_type_key()
        if content_key == self._active_column_content_key:
            return

        if (
            self._active_column_content_key
            and (
                self._column_layout_dirty
                or self._width_resize_debounce_timer.isActive()
                or self._column_layout_save_timer.isActive()
            )
        ):
            self.flush_pending_column_changes()
        self._apply_saved_column_layout(content_key)
        self._active_column_content_key = content_key

    def _queue_column_layout_save(self) -> None:
        """Persist per-content column settings on the next event loop."""
        if self._applying_column_layout:
            return
        self._column_layout_dirty = True
        self._column_layout_save_timer.start(COLUMN_LAYOUT_SAVE_DELAY_MS)

    def _current_column_header_signature(
        self,
    ) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...]]:
        """Return the user-visible column order and widths for change detection."""
        header = self.table.horizontalHeader()
        if header is None:
            return (), ()

        visible_order: list[str] = []
        widths: dict[str, int] = {}
        for visual_index in range(self.table.columnCount()):
            logical_index = header.logicalIndex(visual_index)
            key = self._col_key_for_logical(logical_index)
            if key is None:
                continue
            visible_order.append(key)
            widths[key] = header.sectionSize(logical_index)

        return tuple(visible_order), tuple(sorted(widths.items()))

    def _begin_header_interaction(self) -> None:
        """Snapshot header state before a real mouse-driven reorder/resize."""
        if self._applying_column_layout:
            return
        self._header_interaction_signature = self._current_column_header_signature()

    def _finish_header_interaction(self) -> None:
        """Queue persistence after a real header mouse interaction settles."""
        if self._applying_column_layout:
            self._header_interaction_signature = None
            return

        previous = self._header_interaction_signature
        self._header_interaction_signature = None
        if previous is None or previous != self._current_column_header_signature():
            self._queue_column_layout_save()

    def flush_pending_column_changes(self, *, force: bool = False) -> None:
        """Immediately save any pending column layout changes.

        Call this before the view is destroyed or hidden to ensure
        all column changes are persisted to settings.
        """
        if self._applying_column_layout:
            return

        should_persist = force or self._column_layout_dirty

        # Stop the debounce timer and process any pending resize changes
        if self._width_resize_debounce_timer.isActive():
            self._width_resize_debounce_timer.stop()
            self._save_user_widths()
            should_persist = True
        # Force the layout save timer to fire immediately
        if self._column_layout_save_timer.isActive():
            self._column_layout_save_timer.stop()
            should_persist = True
        if not should_persist:
            return
        self._persist_column_layout_settings()
        self._column_layout_dirty = False

    def _persist_column_layout_settings(self) -> None:
        """Write per-content column layouts into the global settings payload."""
        self._store_current_column_layout(self._active_column_content_key)
        settings = self._settings_service.get_global_settings()
        settings.track_list_columns_by_content = {
            content_key: {
                key: int(width)
                for key, width in layout.items()
                if isinstance(width, int) and width > 0
            }
            for content_key, layout in self._column_layouts.items()
            if layout
        }
        self._settings_service.save_global_settings(settings)

    def _on_header_section_moved(
        self,
        _logical_index: int,
        _old_visual: int,
        _new_visual: int,
    ) -> None:
        """Persist user-driven header reordering."""
        if self._applying_column_layout:
            return
        # Stop any pending width resize debounce and process it first
        if self._width_resize_debounce_timer.isActive():
            self._width_resize_debounce_timer.stop()
            self._save_user_widths()
        self._queue_column_layout_save()

    def _on_header_section_resized(
        self,
        _logical_index: int,
        old_size: int,
        new_size: int,
    ) -> None:
        """Debounce user-driven header width changes (prevents spam during drag)."""
        if self._applying_column_layout or old_size == new_size:
            return
        # Restart debounce timer to batch resize events while dragging
        self._width_resize_debounce_timer.start(50)  # 50ms to catch rapid resizes

    def _on_width_resize_debounce_timeout(self) -> None:
        """After resize drag finishes, save widths and queue settings update."""
        self._save_user_widths()
        self._queue_column_layout_save()

    def _setup_columns(self) -> None:
        """Determine which columns to display based on available data."""
        self._ensure_column_layout_for_current_content()

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

        using_saved_layout = self._user_col_order is not None

        if not self._tracks:
            self._columns = list(self._user_col_order or defaults)
            return

        # Sample tracks to find available keys
        available_keys = set()
        for track in self._tracks[:100]:
            available_keys.update(track.keys())

        # If the user has a saved compact layout, its keys are the visible columns.
        if using_saved_layout:
            base = [
                k for k in self._user_col_order or []
                if k in available_keys or (self._is_playlist_mode and k == "_pl_pos")
            ]
        else:
            # Show only the media-type defaults (user can add more via header menu)
            base = [k for k in defaults if k in available_keys]

        self._columns = base

        # Prepend playlist position column when in playlist mode
        if not using_saved_layout and self._is_playlist_mode and "_pl_pos" not in self._columns:
            self._columns.insert(0, "_pl_pos")

    # -------------------------------------------------------------------------
    # Internal - Table Population
    # -------------------------------------------------------------------------

    def _cancel_population(self) -> None:
        """Cancel any in-progress population."""
        self._load_id += 1
        self._pending_rows = []
        self._is_populating = False
        self._art_pending.clear()

    def _populate_table(self) -> None:
        """Populate the table with current tracks."""
        try:
            self._cancel_population()

            # Capture current column state before clearing (preserves drag order & widths)
            if self.table.columnCount() > 0:
                self._save_user_widths()

            # Check artwork setting, with callers able to force list-only modes.
            if self._show_art_override is None:
                self._show_art = (
                    self._settings_service
                    .get_effective_settings()
                    .show_art_in_tracklist
                )
            else:
                self._show_art = self._show_art_override

            # Capture state for this load
            load_id = self._load_id
            tracks = self._tracks
            columns = self._columns

            # Minimal setup - no setRowCount to avoid blocking!
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)  # Clear existing rows (fast when going to 0)
            self._link_to_rows = {}  # Cache artwork links to row indices for fast batch processing

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
                self.table.setColumnWidth(0, _art_column_width())
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

            artwork_id = self._track_artwork_id(track)
            if artwork_id is not None:
                art_item.setData(Qt.ItemDataRole.UserRole + 2, artwork_id)
                self._link_to_rows.setdefault(artwork_id, []).append(row)
                pixmap = self._thumbnail_for_artwork_id(artwork_id)
                if pixmap is not None:
                    art_item.setIcon(QIcon(pixmap))
                else:
                    # Remember row for async backfill.
                    art_item.setData(Qt.ItemDataRole.UserRole, artwork_id)

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
                item.setForeground(_named_qcolor(Colors.STAR))
            if key == "explicit_flag":
                self._apply_explicit_cell_visuals(item, raw_value)
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
            # Reorderable playlists: keep sorting OFF so rows stay in manual order
            self.table.setSortingEnabled(not self._is_reorderable_playlist())

            # Defensively re-hide vertical header (row numbers) — Qt can
            # re-show it after setSortingEnabled / insertRow cycles.
            vh = self.table.verticalHeader()
            if vh:
                vh.setVisible(False)

            header = self.table.horizontalHeader()
            if header and self._columns:
                start_col = 1 if self._show_art else 0
                total_cols = self.table.columnCount()
                self._applying_column_layout = True
                try:
                    # Art column: fixed width
                    if self._show_art and total_cols > 0:
                        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
                        self.table.setColumnWidth(0, _art_column_width())

                    # Data columns: interactive (user-resizable)
                    for i in range(start_col, total_cols):
                        header.setSectionResizeMode(
                            i, QHeaderView.ResizeMode.Interactive
                        )

                    # Re-apply header interaction properties (defensive — survives
                    # column-count changes and setSortingEnabled toggling)
                    header.setSectionsMovable(True)

                    # Apply saved column widths, or auto-size columns that have none
                    for i in range(start_col, total_cols):
                        col_key = self._col_key_for_logical(i)
                        if col_key and col_key in self._user_col_widths:
                            self.table.setColumnWidth(i, self._user_col_widths[col_key])
                        else:
                            self.table.resizeColumnToContents(i)

                    # Restore saved visual column order (from user drag-reorder)
                    if self._user_col_order:
                        # Build a map from column key → current logical index
                        key_to_logical: dict[str, int] = {}
                        for li in range(start_col, total_cols):
                            k = self._col_key_for_logical(li)
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
                    else:
                        if self._show_art and total_cols > 0 and header.visualIndex(0) != 0:
                            header.moveSection(header.visualIndex(0), 0)
                        for logical in range(start_col, total_cols):
                            current_vis = header.visualIndex(logical)
                            if current_vis != logical:
                                header.moveSection(current_vis, logical)

                    # Stretch the last column
                    header.setStretchLastSection(True)

                    # Re-install event filter (defensive — survives population)
                    header.installEventFilter(self)
                    vp = header.viewport()
                    if vp:
                        vp.installEventFilter(self)
                finally:
                    self._applying_column_layout = False

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
        from app_core.runtime import ThreadPoolSingleton, Worker

        # Collect unique artwork IDs that need loading.
        artwork_ids_to_load: set[int] = set()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            artwork_id = item.data(Qt.ItemDataRole.UserRole)
            if artwork_id:
                try:
                    artwork_id = int(artwork_id)
                except (ValueError, TypeError):
                    continue
                if artwork_id not in self._art_cache and artwork_id not in self._art_pending:
                    artwork_ids_to_load.add(artwork_id)

        if not artwork_ids_to_load:
            return

        session = self._device_sessions.current_session()
        if not session.device_path or not session.artworkdb_path:
            return
        artwork_folder = session.artwork_folder_path or ""
        cancellation_token = self._device_sessions.manager().cancellation_token

        self._art_pending |= artwork_ids_to_load
        load_id = self._load_id

        artwork_id_list = list(artwork_ids_to_load)
        pool = ThreadPoolSingleton.get_instance()

        for i in range(0, len(artwork_id_list), ART_LOAD_BATCH_SIZE):
            chunk = artwork_id_list[i:i + ART_LOAD_BATCH_SIZE]
            worker = Worker(
                self._load_art_batch,
                chunk,
                session.artworkdb_path,
                artwork_folder,
                cancellation_token,
            )
            # Use default arguments correctly to capture the current load_id
            worker.signals.result.connect(
                lambda result, lid=load_id: self._on_art_loaded(result, lid)
            )
            pool.start(worker)

    def _load_art_batch(
        self,
        artwork_ids: list[int],
        artworkdb_path: str,
        artwork_folder: str,
        cancellation_token: Any,
    ) -> dict[int, tuple[int, int, bytes] | None]:
        """Background worker: decode artwork for a batch of artwork IDs.

        Returns dict mapping artwork_id -> (width, height, rgba_bytes) or None.
        Uses image-only decoding (no color extraction) since the list view
        only needs the thumbnail pixmap.
        """
        import os

        from ..imgMaker import configure_artwork_api, get_artwork

        if not artworkdb_path or not os.path.exists(artworkdb_path):
            return {}

        configure_artwork_api(artworkdb_path, artwork_folder)
        results: dict[int, tuple[int, int, bytes] | None] = {}

        for artwork_id in artwork_ids:
            if cancellation_token.is_cancelled():
                break
            pil_img = get_artwork(int(artwork_id), mode="image_only")
            if pil_img is not None:
                pil_img = enhance_artwork_image(
                    pil_img,
                    enabled=self._sharpen_artwork_enabled(),
                )
                pil_img = pil_img.convert("RGBA")
                results[artwork_id] = (
                    pil_img.width,
                    pil_img.height,
                    pil_img.tobytes("raw", "RGBA"),
                )
            else:
                results[artwork_id] = None

        return results

    def _on_art_loaded(self, results: dict | None, load_id: int) -> None:
        """Main-thread callback: apply loaded artwork to table rows."""
        if results is None:
            return

        if self._load_id != load_id:
            return

        try:
            # Convert to QPixmaps and cache
            new_artwork_ids: set[int] = set()
            for artwork_id, data in results.items():
                self._art_pending.discard(artwork_id)
                if data is None:
                    continue
                w, h, rgba = data
                qimg = QImage(rgba, w, h, QImage.Format.Format_RGBA8888).copy()
                pixmap = scale_pixmap_for_display(
                    QPixmap.fromImage(qimg),
                    ART_THUMB_SIZE,
                    ART_THUMB_SIZE,
                    widget=self.table,
                    aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
                    transform_mode=Qt.TransformationMode.SmoothTransformation,
                )
                self._art_cache[artwork_id] = pixmap
                self._invalidate_art_display_cache(artwork_id)
                new_artwork_ids.add(artwork_id)

            if not new_artwork_ids:
                return

            # Use cached row-index instead of scanning all rows (O(K) where K = matched rows)
            # Only process rows with artwork links that were just loaded
            for artwork_id in new_artwork_ids:
                if artwork_id not in self._link_to_rows:
                    continue
                rows = self._link_to_rows[artwork_id]
                pixmap = self._display_thumbnail_for_artwork_id(artwork_id)
                if pixmap is None:
                    continue
                icon = QIcon(pixmap)
                for row in rows:
                    item = self.table.item(row, 0)
                    if item is not None:
                        item.setIcon(icon)
                        item.setData(Qt.ItemDataRole.UserRole, None)

            # Single repaint after all icons are set
            vp = self.table.viewport()
            if vp:
                vp.update()

        except RuntimeError:
            pass  # Widget deleted

    # -------------------------------------------------------------------------
    # Internal - Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _coerce_explicit_flag(value) -> int:
        """Normalize advisory values to iPod semantics (0/1/2)."""
        try:
            iv = int(value)
        except (TypeError, ValueError):
            return 0
        return iv if iv in (1, 2) else 0

    @staticmethod
    def _track_artwork_id(track: dict[str, Any]) -> int | None:
        """Return the normalized artwork ID for a track, if available."""
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

    def _thumbnail_for_artwork_id(self, artwork_id: int) -> QPixmap | None:
        """Return a cached/scaled thumbnail for *artwork_id* when available."""
        pixmap = self._display_thumbnail_for_artwork_id(artwork_id)
        if pixmap is not None:
            return pixmap

        try:
            from ..imgMaker import get_artwork
        except Exception:
            return None

        cached = get_artwork(artwork_id, mode="cache_only")
        if cached is None:
            return None

        pil_img, _dominant_color, _album_colors = cached
        pil_img = enhance_artwork_image(
            pil_img,
            enabled=self._sharpen_artwork_enabled(),
        )
        qimg = QImage(
            pil_img.convert("RGBA").tobytes("raw", "RGBA"),
            pil_img.width,
            pil_img.height,
            QImage.Format.Format_RGBA8888,
        ).copy()
        pixmap = scale_pixmap_for_display(
            QPixmap.fromImage(qimg),
            ART_THUMB_SIZE,
            ART_THUMB_SIZE,
            widget=self.table,
            aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
            transform_mode=Qt.TransformationMode.SmoothTransformation,
        )
        self._art_cache[artwork_id] = pixmap
        self._invalidate_art_display_cache(artwork_id)
        return self._display_thumbnail_for_artwork_id(artwork_id)

    def _display_thumbnail_for_artwork_id(self, artwork_id: int) -> QPixmap | None:
        """Return the UI-rendered thumbnail for *artwork_id*."""
        raw_pixmap = self._art_cache.get(artwork_id)
        if raw_pixmap is None:
            return None

        rounded = self._rounded_artwork_enabled()
        cache_key = (artwork_id, rounded)
        cached = self._art_display_cache.get(cache_key)
        if cached is not None:
            return cached

        pixmap = raw_pixmap
        if rounded:
            pixmap = rounded_artwork_pixmap(
                raw_pixmap,
                nested_artwork_radius(Metrics.BORDER_RADIUS_SM, 4),
            )
        self._art_display_cache[cache_key] = pixmap
        return pixmap

    def _rounded_artwork_enabled(self) -> bool:
        try:
            return bool(self._settings_service.get_effective_settings().rounded_artwork)
        except Exception:
            return False

    def _sharpen_artwork_enabled(self) -> bool:
        try:
            return bool(self._settings_service.get_effective_settings().sharpen_artwork)
        except Exception:
            return True

    def _invalidate_art_display_cache(self, artwork_id: int) -> None:
        for key in list(self._art_display_cache):
            if key[0] == artwork_id:
                self._art_display_cache.pop(key, None)

    def refresh_artwork_appearance(self) -> None:
        """Refresh the track list's artwork column for current appearance settings."""
        desired_show_art = (
            self._show_art_override
            if self._show_art_override is not None
            else bool(self._settings_service.get_effective_settings().show_art_in_tracklist)
        )
        self._art_display_cache.clear()

        if desired_show_art != self._show_art:
            self._populate_table()
            return

        if not self._show_art:
            return

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            artwork_id = item.data(Qt.ItemDataRole.UserRole + 2)
            if not artwork_id:
                continue
            try:
                art_id = int(artwork_id)
            except (TypeError, ValueError):
                continue
            pixmap = self._display_thumbnail_for_artwork_id(art_id)
            if pixmap is None:
                continue
            item.setIcon(QIcon(pixmap))

        viewport = self.table.viewport()
        if viewport is not None:
            viewport.update()

    def _advisory_badge_icon(self, flag: int, size: int = 14) -> QIcon | None:
        """Create a compact badge icon for explicit/clean advisory values."""
        if flag not in (1, 2):
            return None

        cache_key = (flag, size)
        cached = self._advisory_icon_cache.get(cache_key)
        if cached is not None:
            return cached

        if flag == 1:
            svg_name = "advisory-explicit"
            svg_color = Colors.DANGER
        else:
            svg_name = "advisory-clean"
            svg_color = Colors.SUCCESS

        svg_icon = glyph_icon(svg_name, size, color=svg_color)
        if svg_icon is not None:
            self._advisory_icon_cache[cache_key] = svg_icon
            return svg_icon

        if flag == 1:
            bg = _named_qcolor(Colors.DANGER)
            border = _named_qcolor(Colors.DANGER_BORDER)
            glyph = "E"
        else:
            bg = _named_qcolor(Colors.SUCCESS)
            border = _named_qcolor(Colors.SUCCESS_BORDER)
            glyph = "C"

        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.transparent)

        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = px.rect().adjusted(1, 1, -1, -1)
        painter.setPen(border)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 4, 4)

        font = QFont(FONT_FAMILY, max(7, size - 6), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(_named_qcolor(Colors.TEXT_ON_ACCENT))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph)
        painter.end()

        icon = QIcon(px)
        self._advisory_icon_cache[cache_key] = icon
        return icon

    def _apply_explicit_cell_visuals(self, cell: QTableWidgetItem, raw_value) -> None:
        """Apply badge icon + semantic color for the explicit column."""
        flag = self._coerce_explicit_flag(raw_value)
        cell.setIcon(QIcon())
        cell.setToolTip("")

        if flag == 1:
            icon = self._advisory_badge_icon(1)
            if icon is not None:
                cell.setIcon(icon)
            cell.setForeground(_named_qcolor(Colors.DANGER))
            cell.setToolTip("Content Advisory: Explicit")
            return

        if flag == 2:
            icon = self._advisory_badge_icon(2)
            if icon is not None:
                cell.setIcon(icon)
            cell.setForeground(_named_qcolor(Colors.SUCCESS))
            cell.setToolTip("Content Advisory: Clean")
            return

        cell.setForeground(_named_qcolor(Colors.TEXT_TERTIARY))

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

    def _col_key_for_logical(self, logical_col: int) -> str | None:
        """Return the column key for a logical header section index."""
        header_item = self.table.horizontalHeaderItem(logical_col)
        if header_item is not None:
            key = header_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(key, str):
                return key

        offset = 1 if self._show_art else 0
        column_index = logical_col - offset
        if 0 <= column_index < len(self._columns):
            return self._columns[column_index]
        return None

    def _col_key_at(self, visual_col: int) -> str | None:
        """Return the column key for a visual column index."""
        header = self.table.horizontalHeader()
        if header is None:
            return None
        logical_col = header.logicalIndex(visual_col)
        if logical_col < 0:
            return None
        return self._col_key_for_logical(logical_col)

    # -------------------------------------------------------------------------
    # Event Filter — catch right-click on header viewport
    # -------------------------------------------------------------------------

    def eventFilter(self, obj, event):  # type: ignore[override]
        """Intercept events on header viewport (right-click menu) and
        table viewport (shift+scroll horizontal, middle-mouse grab scroll)."""
        header = self.table.horizontalHeader()

        # ── Table widget: key shortcuts (table holds focus, not the parent frame) ──
        if obj is self.table and event.type() == QEvent.Type.KeyPress:
            ke: QKeyEvent = event  # type: ignore[assignment]
            ctrl = Qt.KeyboardModifier.ControlModifier
            alt = Qt.KeyboardModifier.AltModifier
            if ke.modifiers() == (ctrl | alt) and ke.key() == Qt.Key.Key_C:
                self._copy_files_to_clipboard()
                return True
            if ke.modifiers() == ctrl and ke.key() == Qt.Key.Key_C:
                self._copy_selection()
                return True
            if ke.modifiers() == ctrl and ke.key() == Qt.Key.Key_Up:
                self._move_selected_rows(-1)
                return True
            if ke.modifiers() == ctrl and ke.key() == Qt.Key.Key_Down:
                self._move_selected_rows(1)
                return True

        # ── Header: context menu and human drag/resize persistence ──
        header_vp = header.viewport() if header else None
        if header and (obj is header or obj is header_vp):
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress:
                me: QMouseEvent = event  # type: ignore[assignment]
                if me.button() == Qt.MouseButton.RightButton:
                    self._on_header_context_menu(me.pos())
                    return True
                if me.button() == Qt.MouseButton.LeftButton:
                    self._begin_header_interaction()
            elif etype == QEvent.Type.MouseMove:
                me = event  # type: ignore[assignment]
                if (
                    me.buttons() & Qt.MouseButton.LeftButton
                    and self._header_interaction_signature is None
                ):
                    self._begin_header_interaction()
            elif etype == QEvent.Type.MouseButtonRelease:
                me = event  # type: ignore[assignment]
                if me.button() == Qt.MouseButton.LeftButton:
                    self._finish_header_interaction()
            elif etype in {QEvent.Type.FocusOut, QEvent.Type.Hide}:
                self._finish_header_interaction()

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

            # Left-mouse press → record position + snapshot selection before
            # QTableWidget processes the event and potentially clears it
            if etype == QEvent.Type.MouseButtonPress:
                me: QMouseEvent = event  # type: ignore[assignment]
                if me.button() == Qt.MouseButton.LeftButton:
                    self._drag_start_pos = me.pos()
                    self._drag_start_tracks = self._get_selected_tracks()

            # Left-mouse move + Alt → start OS file drag if threshold exceeded
            if etype == QEvent.Type.MouseMove and self._drag_start_pos is not None:
                me = event  # type: ignore[assignment]
                if me.buttons() & Qt.MouseButton.LeftButton:
                    if me.modifiers() & Qt.KeyboardModifier.AltModifier:
                        dist = (me.pos() - self._drag_start_pos).manhattanLength()
                        if dist >= QApplication.startDragDistance():
                            self._drag_start_pos = None
                            self._start_file_drag()
                            return True
                else:
                    self._drag_start_pos = None

            # Middle-mouse press → start grab scroll
            if etype == QEvent.Type.MouseButtonPress:
                me = event  # type: ignore[assignment]
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

            # Mouse release → clear drag start pos; stop grab scroll
            if etype == QEvent.Type.MouseButtonRelease:
                me = event  # type: ignore[assignment]
                if me.button() == Qt.MouseButton.LeftButton:
                    self._drag_start_pos = None
                    self._drag_start_tracks = []
                    if self._drag_prep_thread is not None:
                        self._cleanup_drag_prep()
                if me.button() == Qt.MouseButton.MiddleButton and self._grab_scrolling:
                    self._grab_scrolling = False
                    self.table.unsetCursor()
                    return True

        return super().eventFilter(obj, event)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        """Flush pending column changes when view is hidden."""
        self.flush_pending_column_changes()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Flush pending column changes when view is closed."""
        self.flush_pending_column_changes()
        super().closeEvent(event)

    # -------------------------------------------------------------------------
    # Header Context Menu — hide / show / reorder columns
    # -------------------------------------------------------------------------

    def _on_header_context_menu(self, pos) -> None:
        """Show context menu when right-clicking a column header."""
        header = self.table.horizontalHeader()
        if not header:
            return

        clicked_logical = header.logicalIndexAt(pos)
        clicked_key = self._col_key_for_logical(clicked_logical)

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
                ("Playback && Stats", [
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
                ("Video && TV", [
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
                    "track_id", "db_track_id", "album_id",
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
        if key in self._columns:
            self._columns.remove(key)
        self._user_col_order = list(self._columns)
        self._queue_column_layout_save()
        self._repopulate_keeping_state()

    def _show_column(self, key: str) -> None:
        """Show a column by adding it to the explicit layout."""
        self._save_user_widths()
        # Insert at end (user can drag to reorder)
        if key not in self._columns:
            self._columns.append(key)
        self._user_col_order = list(self._columns)
        self._queue_column_layout_save()
        self._repopulate_keeping_state()

    def _reset_columns(self) -> None:
        """Reset to default column set and widths."""
        self._user_col_widths.clear()
        self._user_col_order = None
        self._setup_columns()
        self._queue_column_layout_save()
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
            key = self._col_key_for_logical(i)
            if key:
                self._user_col_widths[key] = header.sectionSize(i)

        # Save visual order (the order the user sees after dragging)
        visual_keys: list[str] = []
        for vis in range(offset, col_count):
            logical = header.logicalIndex(vis)
            key = self._col_key_for_logical(logical)
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

    def _start_file_drag(self) -> None:
        """Initiate an async Alt+drag export.

        Launches _FilePrepThread to copy + embed artwork in the background.
        Shows a wait cursor and grabs the mouse while preparing so the table
        doesn't do rubber-band selection. QDrag.exec() is called from
        _on_drag_files_ready once the thread finishes and the mouse is still held.
        """
        import os

        from PyQt6.QtWidgets import QApplication

        if self._drag_prep_thread is not None:
            return  # already preparing

        tracks = self._drag_start_tracks or self._get_selected_tracks()
        if not tracks:
            return

        try:
            session = self._device_sessions.current_session()
            ipod_root = session.device_path or ""
            artworkdb_path = session.artworkdb_path or ""
            artwork_folder = session.artwork_folder_path or ""
        except Exception:
            return
        if not ipod_root:
            return

        import shutil

        from infrastructure.settings_paths import default_cache_dir
        cache_root = (
            self._settings_service.get_effective_settings().transcode_cache_dir
            or default_cache_dir()
        )
        temp_dir = os.path.join(cache_root, ".drag_tmp")
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)

        self._drag_prep_thread = _FilePrepThread(
            list(tracks), ipod_root, artworkdb_path, artwork_folder, temp_dir
        )
        self._drag_prep_thread.files_ready.connect(self._on_drag_files_ready)
        self._drag_prep_thread.prep_failed.connect(self._on_drag_prep_failed)

        self._drag_progress_widget = _DragProgressWidget(list(tracks))
        self._drag_prep_thread.track_done.connect(self._drag_progress_widget.mark_done)
        self._drag_prep_thread.start()

        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # Position near the cursor, offset so it doesn't sit under the pointer
        from PyQt6.QtGui import QCursor as _QCursor
        _pos = _QCursor.pos()
        self._drag_progress_widget.adjustSize()
        self._drag_progress_widget.move(_pos.x() + 20, _pos.y() + 20)
        self._drag_progress_widget.show()
        vp = self.table.viewport()
        if vp:
            vp.grabMouse()

    def _on_drag_files_ready(self, urls: list) -> None:
        """Called from the main thread when _FilePrepThread finishes successfully."""
        from PyQt6.QtCore import QMimeData
        from PyQt6.QtGui import QDrag
        from PyQt6.QtWidgets import QApplication

        self._cleanup_drag_prep()

        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            return  # mouse released during prep — silent cancel

        import os
        import shutil
        temp_dir = os.path.dirname(urls[0].toLocalFile()) if urls else ""

        mime = QMimeData()
        mime.setUrls(urls)
        drag = QDrag(self.table)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

        # exec() returns after the drop completes — safe to delete now
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _on_drag_prep_failed(self, msg: str) -> None:
        """Called from the main thread when _FilePrepThread fails."""
        self._cleanup_drag_prep()
        log.warning("Alt+drag file prep failed: %s", msg)

    def _cleanup_drag_prep(self) -> None:
        """Idempotent teardown: restore cursor, release mouse grab, clear thread.

        If the prep thread is still running (e.g. mouse released early), it is
        moved to _drag_orphan_threads so Python keeps a reference until Qt's
        finished() fires — avoiding the "destroyed while still running" warning.
        """
        from PyQt6.QtWidgets import QApplication
        if self._drag_progress_widget is not None:
            # Disconnect track_done signal before clearing the widget
            # to prevent signal firing on None after this
            t = self._drag_prep_thread
            if t is not None:
                try:
                    t.track_done.disconnect()
                except Exception:
                    pass
            self._drag_progress_widget.close()
            self._drag_progress_widget = None
        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        vp = self.table.viewport()
        if vp:
            vp.releaseMouse()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t = self._drag_prep_thread
        self._drag_prep_thread = None
        if t is not None and t.isRunning():
            try:
                t.files_ready.disconnect()
                t.prep_failed.disconnect()
            except Exception:
                pass
            self._drag_orphan_threads.append(t)
            t.finished.connect(lambda: self._reap_orphan_thread(t))

    def _reap_orphan_thread(self, t: _FilePrepThread) -> None:
        """Remove a finished orphan thread from the holding list."""
        try:
            self._drag_orphan_threads.remove(t)
        except ValueError:
            pass

    def _on_track_context_menu(self, pos) -> None:
        """Show context menu when right-clicking on track rows."""
        selected = self._get_selected_tracks()
        if not selected:
            return

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

        cache = self._library_cache

        # ── "Add to Playlist >" cascade ──
        if cache is not None and cache.is_ready():
            playlists = cache.get_playlists()

            # Filter to regular (non-master, non-smart, non-podcast) playlists
            regular = [
                pl for pl in playlists
                if not pl.get("master_flag") and not pl.get("smart_playlist_data") and pl.get("_source") != "smart" and pl.get("podcast_flag", 0) != 1 and pl.get("_source") != "podcast"  # smart_playlist_data was smartPlaylistData
            ]

            add_menu = menu.addMenu("Add to Playlist")
            if add_menu:
                add_menu.setStyleSheet(menu_style)

                new_playlist_act = add_menu.addAction("New Playlist")
                if new_playlist_act:
                    icon = glyph_icon("plus", 14, Colors.TEXT_PRIMARY)
                    if icon is not None:
                        new_playlist_act.setIcon(icon)
                    new_playlist_act.triggered.connect(self._create_new_playlist_from_selected)

                if regular:
                    add_menu.addSeparator()
                    for pl in regular:
                        title = pl.get("Title", "Untitled")
                        act = add_menu.addAction(title)
                        if act:
                            act.triggered.connect(
                                lambda _=False, p=pl: self._add_selected_to_playlist(p)
                            )

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

        # ── "Remove from iPod" ──
        menu.addSeparator()
        n_sel = len(selected)
        remove_ipod_label = f"Remove {n_sel} Track{'s' if n_sel != 1 else ''} from iPod"
        remove_ipod_act = menu.addAction(remove_ipod_label)
        if remove_ipod_act:
            remove_ipod_act.triggered.connect(
                lambda _=False, sel=selected: self.remove_from_ipod_requested.emit(sel)
            )

        # ── "Move Up / Move Down" (reorderable playlists only) ──
        if self._is_reorderable_playlist():
            selected_rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
            menu.addSeparator()
            up_act = menu.addAction(f"Move Up\t{_CTRL}+\u2191")
            if up_act:
                up_act.setEnabled(bool(selected_rows) and selected_rows[0] > 0)
                up_act.triggered.connect(lambda: self._move_selected_rows(-1))
            down_act = menu.addAction(f"Move Down\t{_CTRL}+\u2193")
            if down_act:
                down_act.setEnabled(bool(selected_rows) and selected_rows[-1] < self.table.rowCount() - 1)
                down_act.triggered.connect(lambda: self._move_selected_rows(1))

        # ── Track Flags ──
        menu.addSeparator()
        if cache is not None:
            self._build_flag_menu(menu, menu_style, selected, cache)

        # ── Content Advisory (rtng / explicit flag) ──
        self._build_content_advisory_menu(menu, menu_style, selected)

        # ── Rating ──
        if cache is not None:
            self._build_rating_menu(menu, menu_style, selected, cache)

        # ── Volume Adjustment ──
        self._build_volume_menu(menu, menu_style, selected)

        # ── Start/Stop Time ──
        self._build_start_stop_menu(menu, menu_style, selected)

        # ── Copy ──
        menu.addSeparator()
        copy_text_act = menu.addAction(f"Copy as Text\t{_CTRL}+C")
        if copy_text_act:
            copy_text_act.triggered.connect(self._copy_selection)
        copy_files_act = menu.addAction(f"Copy as File(s)\t{_CTRL}+{_ALT}+C")
        if copy_files_act:
            copy_files_act.triggered.connect(self._copy_files_to_clipboard)

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

    def _build_content_advisory_menu(self, menu: QMenu, style: str, selected: list[dict]) -> None:
        """Add Content Advisory submenu for iPod 'rtng' semantics.

        iPod/iTunesDB values:
          - 0: no advisory tag (unset / not present)
          - 1: explicit
          - 2: clean
        """
        advisory_menu = menu.addMenu("Content Advisory")
        if not advisory_menu:
            return
        advisory_menu.setStyleSheet(style)

        current_flags = {int(t.get("explicit_flag", 0) or 0) for t in selected}
        unanimous = current_flags.pop() if len(current_flags) == 1 else None

        if unanimous is None and len(selected) > 1:
            mixed = advisory_menu.addAction("(mixed selection)")
            if mixed:
                mixed.setEnabled(False)
            advisory_menu.addSeparator()

        options: list[tuple[int, str]] = [
            (0, "None (Unset)"),
            (1, "Explicit"),
            (2, "Clean"),
        ]
        for value, label in options:
            act = advisory_menu.addAction(label)
            if act:
                act.setCheckable(True)
                act.setChecked(unanimous == value)
                icon = self._advisory_badge_icon(value)
                if icon is not None:
                    act.setIcon(icon)
                act.triggered.connect(
                    lambda _=False, v=value: self._set_track_flag("explicit_flag", v)
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
        selected = self._get_selected_tracks()
        if not selected:
            return

        cache = self._library_cache
        if cache is None:
            return
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
                    if key == "explicit_flag":
                        self._apply_explicit_cell_visuals(cell, raw)

    def _add_selected_to_playlist(self, playlist: dict) -> None:
        """Add all selected tracks to the given playlist and save it."""
        selected = self._get_selected_tracks()
        if not selected:
            return

        cache = self._library_cache
        if cache is None:
            return
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
        cache.playlist_quick_sync.emit()

        title = playlist.get("Title", "Untitled")
        log.info("Added %d track(s) to playlist '%s' (id=0x%X)",
                 added, title, playlist.get("playlist_id", 0))

    def _create_new_playlist_from_selected(self) -> None:
        """Create a new regular playlist from the current selection."""
        selected = self._get_selected_tracks()
        if not selected:
            return

        cache = self._library_cache
        if cache is None or not cache.is_ready():
            return

        playlist = build_new_regular_playlist(selected)
        if playlist is None:
            return

        cache.save_user_playlist(playlist)
        cache.playlist_quick_sync.emit()

        log.info(
            "Created playlist '%s' with %d track(s) (id=0x%X)",
            playlist.get("Title", "Untitled"),
            len(playlist.get("items", [])),
            playlist.get("playlist_id", 0),
        )

    def _remove_selected_from_playlist(self) -> None:
        """Remove selected tracks from the current playlist and save it."""
        playlist = self._current_playlist
        if not playlist:
            return

        selected = self._get_selected_tracks()
        if not selected:
            return

        cache = self._library_cache
        if cache is None:
            return
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
        cache.playlist_quick_sync.emit()

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
    # Ctrl+Alt+C — Copy selected tracks as files into the clipboard
    # -------------------------------------------------------------------------

    def _copy_files_to_clipboard(self) -> None:
        """Prepare selected tracks as files and place them on the clipboard.

        Uses the same background-thread + progress-widget flow as Alt+drag.
        The temporary files live in {cache}/.clip_tmp until the clipboard is
        replaced (dataChanged signal) or a new copy is triggered (whichever
        comes first).
        """
        import os
        import shutil

        from infrastructure.settings_paths import default_cache_dir

        if self._clip_prep_thread is not None:
            return  # already preparing

        tracks = self._get_selected_tracks()
        if not tracks:
            return

        try:
            session = self._device_sessions.current_session()
            ipod_root = session.device_path or ""
            artworkdb_path = session.artworkdb_path or ""
            artwork_folder = session.artwork_folder_path or ""
        except Exception:
            return
        if not ipod_root:
            return

        # Build a fresh temp dir in the user's cache directory
        cache_root = (
            self._settings_service.get_effective_settings().transcode_cache_dir
            or default_cache_dir()
        )
        temp_dir = os.path.join(cache_root, ".clip_tmp")
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)

        self._clip_prep_thread = _FilePrepThread(
            list(tracks), ipod_root, artworkdb_path, artwork_folder, temp_dir
        )
        self._clip_prep_thread.files_ready.connect(self._on_clip_files_ready)
        self._clip_prep_thread.prep_failed.connect(self._on_clip_prep_failed)

        self._clip_progress_widget = _DragProgressWidget(list(tracks))
        self._clip_prep_thread.track_done.connect(self._clip_progress_widget.mark_done)
        self._clip_prep_thread.start()

        from PyQt6.QtGui import QCursor as _QCursor
        _pos = _QCursor.pos()
        self._clip_progress_widget.adjustSize()
        self._clip_progress_widget.move(_pos.x() + 20, _pos.y() + 20)
        self._clip_progress_widget.show()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    def _on_clip_files_ready(self, urls: list) -> None:
        """Place prepared files on the system clipboard."""
        import os

        log.info("clip: files_ready — %d url(s)", len(urls))
        for u in urls:
            local = u.toLocalFile()
            exists = os.path.isfile(local)
            log.info("  clip url=%s  exists=%s", local, exists)

        self._cleanup_clip_prep()

        import sys

        from PyQt6.QtCore import QByteArray
        from PyQt6.QtCore import QMimeData as _QMimeData
        mime = _QMimeData()
        mime.setUrls(urls)

        if sys.platform == "linux":
            # Nautilus/GNOME requires this additional format alongside text/uri-list.
            # KDE/Dolphin accepts text/uri-list alone.
            uri_bytes = "\n".join(u.toString() for u in urls).encode()
            mime.setData("x-special/gnome-copied-files", QByteArray(b"copy\n" + uri_bytes))

        log.info("clip: mime formats after setUrls: %s", mime.formats())

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setMimeData(mime)
            cb_mime = clipboard.mimeData()
            if cb_mime:
                log.info("clip: clipboard formats: %s", cb_mime.formats())
                log.info("clip: clipboard urls: %s", [u.toString() for u in cb_mime.urls()])
            else:
                log.warning("clip: clipboard.mimeData() returned None after setMimeData")
        else:
            log.warning("clip: QApplication.clipboard() returned None")

    def _on_clip_prep_failed(self, msg: str) -> None:
        self._cleanup_clip_prep()
        log.warning("Ctrl+Alt+C file prep failed: %s", msg)

    def _cleanup_clip_prep(self) -> None:
        """Restore UI state after clipboard file prep (success, failure, or cancel)."""
        from PyQt6.QtWidgets import QApplication as _QApp
        if self._clip_progress_widget is not None:
            # Disconnect track_done signal before clearing the widget
            # to prevent signal firing on closed/deleted widget
            t = self._clip_prep_thread
            if t is not None:
                try:
                    t.track_done.disconnect()
                except Exception:
                    pass
            self._clip_progress_widget.close()
            self._clip_progress_widget = None
        if _QApp.overrideCursor() is not None:
            _QApp.restoreOverrideCursor()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t = self._clip_prep_thread
        self._clip_prep_thread = None
        if t is not None and t.isRunning():
            try:
                t.files_ready.disconnect()
                t.prep_failed.disconnect()
            except Exception:
                pass
            self._clip_orphan_threads.append(t)
            t.finished.connect(lambda: self._reap_clip_orphan_thread(t))

    def _reap_clip_orphan_thread(self, t: _FilePrepThread) -> None:
        try:
            self._clip_orphan_threads.remove(t)
        except ValueError:
            pass

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


def _embed_artwork(path: str, ext: str, jpeg_bytes: bytes) -> None:
    """Embed JPEG artwork into an audio file in-place using mutagen."""
    if ext in (".m4a", ".m4b", ".aac", ".mp4"):
        from mutagen.mp4 import MP4, MP4Cover
        audio = MP4(path)
        audio["covr"] = [MP4Cover(jpeg_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
    elif ext == ".mp3":
        import mutagen.id3
        try:
            tags = mutagen.id3.ID3(path)
        except Exception:
            tags = mutagen.id3.ID3()
        tags.delall("APIC")
        tags.add(mutagen.id3.APIC(  # type: ignore[attr-defined]
            encoding=3,
            mime="image/jpeg",
            type=3,
            desc="Cover",
            data=jpeg_bytes,
        ))
        tags.save(path)
