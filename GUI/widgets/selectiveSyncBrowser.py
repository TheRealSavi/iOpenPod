"""
SelectiveSyncBrowser — full-page PC library browser for selective sync.

Mirrors the look and feel of the main MusicBrowser (grid cards, sidebar
categories, track list) but displays tracks from a local PC folder instead
of the iPod database.  The user browses albums/artists/genres, checks or
unchecks individual tracks, then submits only the selected paths for sync.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from PIL import Image, ImageOps
from PyQt6.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ArtworkDB_Writer.art_extractor import (
    extract_art,
    find_folder_art,
)
from SyncEngine.photos import PCPhoto, PCPhotoLibrary, scan_pc_photos

from ..glyphs import glyph_icon
from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
    back_btn_css,
    btn_css,
    make_scroll_area,
    sidebar_nav_css,
    sidebar_nav_selected_css,
)
from .browserChrome import style_browser_splitter
from .formatters import format_duration_human, format_size
from .gridHeaderBar import GridHeaderBar
from .MBGridView import (
    _ART_CACHE_UNSET,
    ArtworkResult,
    CachedArtworkLookup,
    GridRecord,
    MusicBrowserGrid,
)
from .MBGridViewItem import MusicBrowserGridItem
from .photoViewer import PhotoViewerPane
from .pooledPhotoGrid import PhotoTileModel, PooledPhotoGridView

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app_core.services import DeviceSessionService, SettingsService

# ── Artwork extraction helpers ─────────────────────────────────────────────

_ART_BATCH = 20  # files per background worker
_PC_PHOTO_THUMB_BATCH_SIZE = 6
_PC_PHOTO_PREFETCH_AHEAD = 6
_PC_PHOTO_MAX_THUMB_WORKERS = 2
_PC_PHOTO_PREVIEW_MAX = (1600, 1600)


def _extract_art_for_group(file_paths: list[str]) -> tuple | None:
    """Try embedded art from each file, then folder art.  Return
    (PIL.Image, dominant_color, album_colors) or None."""
    import io

    from PIL import Image

    img: Image.Image | None = None

    # 1) Try embedded art from the given files
    for fp in file_paths:
        raw = extract_art(fp)
        if raw is not None:
            try:
                img = Image.open(io.BytesIO(raw)).convert("RGB")
            except Exception:
                pass
            if img is not None:
                break

    # 2) Fallback: folder artwork next to the first file
    if img is None and file_paths:
        folder_path = find_folder_art(file_paths[0])
        if folder_path:
            try:
                img = Image.open(folder_path).convert("RGB")
            except Exception:
                pass

    if img is None:
        return None

    img.thumbnail((300, 300))
    from ..imgMaker import getAlbumColors, getDominantColor
    dcol = getDominantColor(img)
    album_colors = getAlbumColors(img, bg=dcol)
    return (img, dcol, album_colors)


# ── Background workers ──────────────────────────────────────────────────────


class _PCLibScanWorker(QThread):
    """Scan a folder with PCLibrary and emit the track list."""
    finished = pyqtSignal(object)  # {"tracks": list[PCTrack], "photos": PCPhotoLibrary}
    error = pyqtSignal(str)

    def __init__(self, folder: str, include_video: bool = True):
        super().__init__()
        self._folder = folder
        self._include_video = include_video

    def run(self):
        try:
            from SyncEngine.pc_library import PCLibrary
            lib = PCLibrary(self._folder)
            tracks = list(lib.scan(include_video=self._include_video))
            photos = scan_pc_photos(self._folder)
            self.finished.emit({"tracks": tracks, "photos": photos})
        except Exception as e:
            self.error.emit(str(e))


# ── PC-aware grid ───────────────────────────────────────────────────────────

class PCMusicBrowserGrid(MusicBrowserGrid):
    """Subclass of MusicBrowserGrid that loads artwork from embedded tags
    (or folder images) instead of the iPod ArtworkDB."""

    def __init__(self, *, settings_service: SettingsService | None = None):
        super().__init__(settings_service=settings_service)
        self._pc_art_map: dict[str, list[str]] = {}
        self._pc_mode = False

    def loadPCCategory(self, groups: dict[str, dict]):
        """Populate the grid from PC track groups.

        *groups* maps display_key -> {"tracks": [...], "subtitle": str,
        "art_paths": list[str], "filter_key": str, "filter_value": str}.
        """
        self._pc_mode = True
        self._pc_art_map.clear()

        items: list[dict] = []
        for key, info in sorted(groups.items(), key=lambda kv: kv[0].lower()):
            self._pc_art_map[key] = info.get("art_paths", [])

            items.append({
                "title": key,
                "subtitle": info.get("subtitle", ""),
                "artwork_id_ref": None,  # prevents base-class iPod art loading
                "_grid_art_key": key,
                "category": info.get("category", "Albums"),
                "filter_key": info.get("filter_key", "album"),
                "filter_value": info.get("filter_value", key),
                "album": info.get("album"),
                "artist": info.get("artist"),
                "year": info.get("year", 0),
                "track_count": info.get("track_count", 0),
                "album_count": info.get("album_count", 0),
                "artist_count": info.get("artist_count", 0),
            })

        self._set_source_items(items, reset_scroll=True)

    def _load_cached_artwork(
        self,
        record: GridRecord,
    ) -> CachedArtworkLookup:
        if not self._pc_mode:
            return super()._load_cached_artwork(record)

        if record.artwork_key is None:
            return None
        if not self._pc_art_map.get(str(record.artwork_key)):
            return None
        return _ART_CACHE_UNSET

    def _load_art_async(self):
        if not self._pc_mode:
            super()._load_art_async()
            return

        records = self._visible_records_needing_art()
        if not records:
            return

        from app_core.runtime import ThreadPoolSingleton, Worker

        load_id = self._load_id
        pool = ThreadPoolSingleton.get_instance()
        batch: list[tuple[str, list[str]]] = []

        for record in records:
            key = str(record.artwork_key)
            paths = self._pc_art_map.get(key, [])
            if paths:
                self._art_pending.add(key)
                batch.append((key, paths))
            if len(batch) >= _ART_BATCH:
                worker = Worker(self._pc_art_batch, list(batch))
                worker.signals.result.connect(
                    lambda result, lid=load_id: self._on_pc_art_loaded(result, lid)
                )
                pool.start(worker)
                batch = []

        if batch:
            worker = Worker(self._pc_art_batch, list(batch))
            worker.signals.result.connect(
                lambda result, lid=load_id: self._on_pc_art_loaded(result, lid)
            )
            pool.start(worker)

    @staticmethod
    def _pc_art_batch(
        pairs: list[tuple[str, list[str]]],
    ) -> dict[str, tuple | None]:
        results: dict[str, tuple | None] = {}
        for key, paths in pairs:
            art = _extract_art_for_group(paths)
            if art is not None:
                img, dcol, album_colors = art
                img_rgba = img.convert("RGBA")
                results[key] = (
                    img_rgba.width, img_rgba.height,
                    img_rgba.tobytes("raw", "RGBA"),
                    dcol, album_colors,
                )
            else:
                results[key] = None
        return results

    def _on_pc_art_loaded(self, results: dict | None, load_id: int):
        if results is None or self._load_id != load_id:
            return

        try:
            for key, data in results.items():
                self._art_pending.discard(key)
                if data is None:
                    self._art_cache[key] = None
                    self._art_seen.add(key)
                    self._apply_art_to_visible_widgets(key)
                    continue

                w, h, rgba, dcol, album_colors = data
                pil_img = Image.frombytes("RGBA", (w, h), rgba)
                self._art_cache[key] = ArtworkResult(
                    pil_img,
                    dcol,
                    album_colors,
                )
                self._apply_art_to_visible_widgets(key)
        except RuntimeError:
            pass

    def loadCategory(self, category: str):
        """Switch back to iPod mode when the base-class loader is used."""
        self._pc_mode = False
        self._pc_art_map.clear()
        super().loadCategory(category)

    def clearGrid(self, preserve_all_items: bool = False):
        super().clearGrid(preserve_all_items=preserve_all_items)
        if not preserve_all_items:
            self._pc_art_map.clear()


# ── PC-adapted track table ─────────────────────────────────────────────────

_HERO_ART_SIZE = 120  # px, artwork square in the hero header

# Columns suitable for PC tracks (no iPod-only stats like play_count, date_added)
_PC_DEFAULT_COLUMNS = [
    "Title", "Artist", "Album", "Genre", "year",
    "track_number", "length", "size", "bitrate",
]


class _PCMusicBrowserList:
    """Mixin-style wrapper that adapts MusicBrowserList for PC track display.

    - Disables artwork loading (no ArtworkDB for PC files)
    - Re-injects the checkbox column after every repopulate
    - Disables iPod-only context menus and drag-to-OS
    """

    @staticmethod
    def create(owner: PCTrackListView):
        """Create and configure a MusicBrowserList for PC track use."""
        from .MBListView import MusicBrowserList

        bl = MusicBrowserList(
            settings_service=owner._settings_service,
            device_sessions=owner._device_sessions,
            show_art_override=False,
            content_type_override="pc_tracks",
        )

        # Disable iPod-specific features
        bl.table.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        bl.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        bl.table.setDragEnabled(False)

        # Monkey-patch to disable art, re-inject checkboxes after every
        # repopulate, and offset column lookups for the checkbox column.
        _orig_populate = bl._populate_table
        _orig_finish = bl._finish_population
        _orig_col_key = bl._col_key_at

        # Track whether the checkbox column currently exists — it does NOT
        # exist during _finish_population (called by the base), only after
        # our patched finish injects it.
        owner._has_checkbox_col = False

        def _patched_populate():
            owner._has_checkbox_col = False
            _orig_populate()

        def _patched_finish():
            _orig_finish()
            # Re-inject checkboxes after the table is fully populated
            if owner._selection:
                owner._add_checkbox_column(owner._selection)
                owner._has_checkbox_col = True

        def _patched_col_key_at(visual_col: int) -> str | None:
            # Only shift by 1 when the checkbox column actually exists
            offset = 1 if owner._has_checkbox_col else 0
            adjusted = visual_col - offset
            return _orig_col_key(adjusted) if adjusted >= 0 else None

        bl._populate_table = _patched_populate
        bl._finish_population = _patched_finish
        bl._col_key_at = _patched_col_key_at

        return bl


# ── Track list with checkboxes ──────────────────────────────────────────────


class PCTrackListView(QWidget):
    """Table of tracks with per-row checkboxes for selective sync."""
    toggled = pyqtSignal(str, bool)  # (path, checked)
    back_requested = pyqtSignal()
    select_all_requested = pyqtSignal()
    deselect_all_requested = pyqtSignal()

    def __init__(
        self,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
        parent=None,
    ):
        super().__init__(parent)
        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._tracks: list = []
        self._selection: dict[str, bool] = {}
        self._loading = False
        self._has_checkbox_col: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Hero header ─────────────────────────────────────────────────
        self._hero = QFrame()
        self._hero.setMaximumHeight(375)
        self._hero.setStyleSheet(f"""
            QFrame#heroHeader {{
                background: {Colors.BG_DARK};
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        self._hero.setObjectName("heroHeader")
        hero_root = QVBoxLayout(self._hero)
        hero_root.setContentsMargins(0, 0, 0, 0)
        hero_root.setSpacing(0)

        # Top row: back button
        top_bar = QFrame()
        top_bar.setStyleSheet("background: transparent; border: none;")
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(12, 8, 12, 0)
        top_lay.setSpacing(0)

        self._back_btn = QPushButton("\u2190")
        self._back_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self._back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._back_btn.setToolTip("Back")
        self._back_btn.clicked.connect(self.back_requested.emit)
        top_lay.addWidget(self._back_btn)
        top_lay.addStretch()
        hero_root.addWidget(top_bar)

        # Main hero content: artwork + info side by side
        hero_body = QFrame()
        hero_body.setStyleSheet("background: transparent; border: none;")
        body_lay = QHBoxLayout(hero_body)
        body_lay.setContentsMargins(24, 12, 24, 16)
        body_lay.setSpacing(20)

        # Artwork
        self._hero_art = QLabel()
        self._hero_art.setFixedSize(_HERO_ART_SIZE, _HERO_ART_SIZE)
        self._hero_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_lay.addWidget(self._hero_art, 0, Qt.AlignmentFlag.AlignTop)

        # Info column
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 4, 0, 0)
        info_col.setSpacing(4)

        self._title_label = QLabel()
        self._title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        self._title_label.setWordWrap(True)
        info_col.addWidget(self._title_label)

        self._subtitle_label = QLabel()
        self._subtitle_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        info_col.addWidget(self._subtitle_label)

        self._meta_label = QLabel()
        self._meta_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        info_col.addWidget(self._meta_label)

        info_col.addSpacing(8)

        # Select / Deselect buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._sel_btn = QPushButton("Select All")
        self._sel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._sel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._sel_btn.clicked.connect(self.select_all_requested.emit)
        btn_row.addWidget(self._sel_btn)

        self._desel_btn = QPushButton("Deselect All")
        self._desel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._desel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._desel_btn.clicked.connect(self.deselect_all_requested.emit)
        btn_row.addWidget(self._desel_btn)
        btn_row.addStretch()

        info_col.addLayout(btn_row)
        info_col.addStretch()
        body_lay.addLayout(info_col, 1)

        # Collect hero buttons for unified styling
        self._hero_btns = [self._back_btn, self._sel_btn, self._desel_btn]

        # Apply default (non-tinted) styling
        self._apply_hero_default_style()

        hero_root.addWidget(hero_body)
        layout.addWidget(self._hero)

        # ── Track table (adapted MusicBrowserList for PC tracks) ──
        self._pc_tracks: list = []
        self._pc_track_dicts: list[dict] = []
        self._browser_list = _PCMusicBrowserList.create(self)
        layout.addWidget(self._browser_list)

    # ── Public setters ──────────────────────────────────────────────────

    def setTitle(self, title: str):
        self._title_label.setText(title)

    def setSubtitle(self, subtitle: str):
        self._subtitle_label.setText(subtitle)

    def setMeta(self, meta: str):
        self._meta_label.setText(meta)

    def setHeroColor(self, r: int, g: int, b: int):
        """Tint the hero header background with the artwork's dominant color."""
        if Colors._active_mode == "light":
            glass_bg = "rgba(0, 0, 0, 20)"
            glass_hover = "rgba(0, 0, 0, 28)"
            glass_press = "rgba(0, 0, 0, 14)"
            glass_border = "rgba(0, 0, 0, 24)"
        else:
            glass_bg = "rgba(255, 255, 255, 18)"
            glass_hover = "rgba(255, 255, 255, 35)"
            glass_press = "rgba(255, 255, 255, 12)"
            glass_border = "rgba(255, 255, 255, 15)"

        self._hero.setStyleSheet(f"""
            QFrame#heroHeader {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({r}, {g}, {b}, 80),
                    stop:1 {Colors.BG_DARK}
                );
                border-bottom: 1px solid rgba({r}, {g}, {b}, 40);
            }}
        """)
        self._hero_art.setStyleSheet(f"""
            background: rgba({r}, {g}, {b}, 30);
            border-radius: {Metrics.BORDER_RADIUS}px;
            border: 1px solid rgba({r}, {g}, {b}, 50);
        """)
        self._title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        self._subtitle_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._meta_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        # Frosted-glass buttons that sit nicely on the tinted background
        _overlay_css = btn_css(
            bg=glass_bg,
            bg_hover=glass_hover,
            bg_press=glass_press,
            fg=Colors.TEXT_PRIMARY,
            border=f"1px solid {glass_border}",
            padding="5px 12px",
            radius=Metrics.BORDER_RADIUS_SM,
        )
        self._back_btn.setStyleSheet(back_btn_css())
        self._sel_btn.setStyleSheet(_overlay_css)
        self._desel_btn.setStyleSheet(_overlay_css)

    def resetHeroColor(self):
        """Reset the hero header to default (no artwork tint)."""
        self._apply_hero_default_style()

    def _apply_hero_default_style(self):
        """Apply the default (non-tinted) hero styling."""
        self._hero.setStyleSheet(f"""
            QFrame#heroHeader {{
                background: {Colors.BG_DARK};
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        self._hero_art.setStyleSheet(f"""
            background: {Colors.SURFACE};
            border-radius: {Metrics.BORDER_RADIUS}px;
            border: 1px solid {Colors.BORDER_SUBTLE};
        """)
        self._title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        self._subtitle_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._meta_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        _default_btn = btn_css(padding="5px 12px", radius=Metrics.BORDER_RADIUS_SM)
        self._back_btn.setStyleSheet(back_btn_css())
        self._sel_btn.setStyleSheet(_default_btn)
        self._desel_btn.setStyleSheet(_default_btn)

    def setHeroArt(self, pixmap):
        """Set the hero artwork image from a QPixmap."""
        from ..hidpi import scale_pixmap_for_display
        if pixmap and not pixmap.isNull():
            scaled = scale_pixmap_for_display(
                pixmap, _HERO_ART_SIZE, _HERO_ART_SIZE,
                widget=self._hero_art,
                aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
                transform_mode=Qt.TransformationMode.SmoothTransformation,
            )
            self._hero_art.setPixmap(scaled)
        else:
            self._hero_art.clear()
            from ..glyphs import glyph_icon
            icon = glyph_icon("music", 48, Colors.TEXT_TERTIARY)
            if icon:
                self._hero_art.setPixmap(icon.pixmap(48, 48))

    def setHeroVisible(self, visible: bool):
        """Show or hide the entire hero header section."""
        self._hero.setVisible(visible)

    def setBackVisible(self, visible: bool):
        self._back_btn.setVisible(visible)

    @staticmethod
    def _pc_track_to_dict(t) -> dict:
        """Convert a PCTrack object to a dict compatible with MusicBrowserList."""
        return {
            "Title": t.title or t.filename,
            "Artist": t.artist or "",
            "Album": t.album or "",
            "Album Artist": getattr(t, "album_artist", "") or "",
            "Genre": getattr(t, "genre", "") or "",
            "Composer": getattr(t, "composer", "") or "",
            "Comment": getattr(t, "comment", "") or "",
            "year": getattr(t, "year", 0) or 0,
            "track_number": t.track_number or 0,
            "total_tracks": getattr(t, "track_total", 0) or 0,
            "disc_number": getattr(t, "disc_number", 0) or 0,
            "total_discs": getattr(t, "disc_total", 0) or 0,
            "length": t.duration_ms or 0,
            "size": t.size or 0,
            "bitrate": getattr(t, "bitrate", 0) or 0,
            "sample_rate_1": getattr(t, "sample_rate", 0) or 0,
            "bpm": getattr(t, "bpm", 0) or 0,
            "rating": getattr(t, "rating", 0) or 0,
            "compilation_flag": 1 if getattr(t, "compilation", False) else 0,
            "vbr_flag": 1 if getattr(t, "vbr", False) else 0,
            "explicit_flag": getattr(t, "explicit_flag", 0) or 0,
            "filetype": t.extension.lstrip(".").upper() if t.extension else "",
            "Location": t.path,
            "_pc_path": t.path,  # internal key for checkbox tracking
        }

    def setTracks(self, tracks: list, selection: dict[str, bool]):
        """Populate the table with *tracks* (PCTrack objects)."""
        self._pc_tracks = tracks
        self._selection = selection

        # Convert to dicts for MusicBrowserList
        self._pc_track_dicts = [self._pc_track_to_dict(t) for t in tracks]

        # Feed into the browser list
        bl = self._browser_list
        bl._all_tracks = self._pc_track_dicts
        bl._tracks = self._pc_track_dicts
        bl._is_playlist_mode = False
        bl._current_filter = None
        if not bl._columns or bl._columns == ["Title"]:
            bl._columns = _PC_DEFAULT_COLUMNS.copy()
        bl._load_id += 1
        bl._populate_table()

    def _add_checkbox_column(self, selection: dict[str, bool]):
        """Insert a checkbox column at position 0 in the table."""
        t = self._browser_list.table
        t.blockSignals(True)

        # Insert checkbox column at the front
        t.insertColumn(0)
        t.setHorizontalHeaderItem(0, QTableWidgetItem("\u2611"))
        t.setColumnWidth(0, 36)

        hh = t.horizontalHeader()
        if hh:
            hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)

        for row in range(t.rowCount()):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)

            # Find the path from the track dict via the row's anchor
            path = self._path_for_row(row)
            checked = selection.get(path, True) if path else True
            chk.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
            chk.setData(Qt.ItemDataRole.UserRole, path)
            t.setItem(row, 0, chk)

        t.blockSignals(False)

        # Connect checkbox toggling
        try:
            t.cellChanged.disconnect(self._on_cell_changed)
        except (TypeError, RuntimeError):
            pass
        t.cellChanged.connect(self._on_cell_changed)

    def _path_for_row(self, row: int) -> str | None:
        """Get the PC file path for a table row (accounts for sorting)."""
        t = self._browser_list.table
        bl = self._browser_list
        # Anchor is at the first data column. After checkbox insertion at 0
        # it shifts right by 1.  If art were shown it would shift another 1.
        first_data_col = 1 + (1 if bl._show_art else 0)
        anchor = t.item(row, first_data_col)
        if anchor:
            orig_idx = anchor.data(Qt.ItemDataRole.UserRole + 1)
            if orig_idx is not None and 0 <= orig_idx < len(self._pc_track_dicts):
                return self._pc_track_dicts[orig_idx].get("_pc_path")
        return None

    def _on_cell_changed(self, row: int, col: int):
        if col != 0:
            return
        item = self._browser_list.table.item(row, 0)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        checked = item.checkState() == Qt.CheckState.Checked
        if path:
            self.toggled.emit(path, checked)

    def setAllChecked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        t = self._browser_list.table
        t.blockSignals(True)
        for row in range(t.rowCount()):
            item = t.item(row, 0)
            if item:
                item.setCheckState(state)
        t.blockSignals(False)

    def updateCheckStates(self, selection: dict[str, bool]):
        """Refresh checkbox states from selection dict without emitting signals."""
        t = self._browser_list.table
        t.blockSignals(True)
        for row in range(t.rowCount()):
            item = t.item(row, 0)
            if item:
                path = item.data(Qt.ItemDataRole.UserRole)
                checked = selection.get(path, True) if path else True
                item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
        t.blockSignals(False)


# ── Photo list with checkboxes ──────────────────────────────────────────────


class PCPhotoListView(QWidget):
    """Icon-grid photo picker for selective sync."""

    toggled = pyqtSignal(str, bool)  # (path, checked)
    select_all_requested = pyqtSignal()
    deselect_all_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._photos: list[PCPhoto] = []
        self._selection: dict[str, bool] = {}
        self._visible_photos: list[PCPhoto] = []
        self._search_query = ""
        self._sort_key = "title"
        self._sort_reverse = False
        self._tile_pixmap_cache: dict[str, QPixmap] = {}
        self._preview_pixmap_cache: dict[str, QPixmap] = {}
        self._thumb_queue: deque[tuple[str, int]] = deque()
        self._queued_thumb_paths: set[str] = set()
        self._thumb_in_flight_paths: set[str] = set()
        self._thumb_workers_in_flight = 0
        self._preview_pending: set[str] = set()
        self._preview_request_token = 0
        self._load_token = 0
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._process_thumb_batch)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        style_browser_splitter(body_splitter)

        list_panel = QWidget()
        list_lay = QVBoxLayout(list_panel)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(0)

        self._grid_header = GridHeaderBar()
        self._grid_header.setCategory("Photos")
        self._grid_header.sort_changed.connect(self._on_sort_changed)
        self._grid_header.search_changed.connect(self._on_search_changed)
        list_lay.addWidget(self._grid_header)

        self._photo_scroll = make_scroll_area()
        self._photo_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._photo_grid = PooledPhotoGridView(checkable=True)
        self._photo_grid.currentIndexChanged.connect(self._on_current_photo_changed)
        self._photo_grid.checkedChanged.connect(self._on_photo_checked_changed)
        self._photo_grid.visibleIndicesChanged.connect(
            self._on_visible_photo_indices_changed
        )
        self._photo_scroll.setWidget(self._photo_grid)
        list_lay.addWidget(self._photo_scroll, 1)
        body_splitter.addWidget(list_panel)

        self._viewer = PhotoViewerPane(
            heading="",
            empty_title="No photo selected",
            empty_summary="Select a photo from the sync browser to preview it here.",
        )
        body_splitter.addWidget(self._viewer)
        body_splitter.setSizes([680, 360])
        layout.addWidget(body_splitter, 1)

    def setPhotos(self, photos: list[PCPhoto], selection: dict[str, bool]):
        self._photos = photos
        self._selection = selection
        self._search_query = ""
        self._sort_key = "title"
        self._sort_reverse = False
        self._load_token += 1
        self._preview_request_token += 1
        self._tile_pixmap_cache.clear()
        self._preview_pixmap_cache.clear()
        self._thumb_queue.clear()
        self._queued_thumb_paths.clear()
        self._thumb_in_flight_paths.clear()
        self._thumb_workers_in_flight = 0
        self._preview_pending.clear()
        self._grid_header.blockSignals(True)
        self._grid_header.resetState()
        self._grid_header.blockSignals(False)
        self._refresh_list()

    def _matches_search(self, photo: PCPhoto) -> bool:
        if not self._search_query:
            return True
        haystack = " ".join(
            part for part in (
                photo.display_name,
                photo.source_path,
                " ".join(sorted(name for name in photo.album_names if name)),
            ) if part
        ).lower()
        return self._search_query in haystack

    def _sort_photos(self, photos: list[PCPhoto]) -> list[PCPhoto]:
        if self._sort_key == "size":
            key_fn = self._photo_size_sort_key
        elif self._sort_key == "album_count":
            key_fn = self._photo_album_count_sort_key
        else:
            key_fn = self._photo_title_sort_key
        return sorted(photos, key=key_fn, reverse=self._sort_reverse)

    def _photo_sort_label(self, photo: PCPhoto) -> str:
        return (photo.display_name or photo.source_path).lower()

    def _photo_size_sort_key(self, photo: PCPhoto) -> tuple[int, str]:
        return photo.size, self._photo_sort_label(photo)

    def _photo_album_count_sort_key(self, photo: PCPhoto) -> tuple[int, str]:
        return len(photo.album_names), self._photo_sort_label(photo)

    def _photo_title_sort_key(self, photo: PCPhoto) -> tuple[str, int]:
        return self._photo_sort_label(photo), photo.size

    @staticmethod
    def _pixmap_from_rgba_bytes(width: int, height: int, rgba: bytes) -> QPixmap:
        qimg = QImage(rgba, width, height, width * 4, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())

    @staticmethod
    def _encode_pc_photo(
        path: str,
        *,
        max_size: tuple[int, int] | None = None,
    ) -> tuple[int, int, bytes] | None:
        try:
            with Image.open(path) as img:
                image = ImageOps.exif_transpose(img)
                if max_size is not None:
                    image.thumbnail(max_size)
                image = image.convert("RGBA")
                return image.width, image.height, image.tobytes("raw", "RGBA")
        except Exception:
            return None

    @staticmethod
    def _load_thumb_batch(paths: list[str]) -> dict[str, tuple[int, int, bytes] | None]:
        return {
            path: PCPhotoListView._encode_pc_photo(path, max_size=(132, 132))
            for path in paths
        }

    @staticmethod
    def _load_preview(path: str) -> tuple[int, int, bytes] | None:
        return PCPhotoListView._encode_pc_photo(path, max_size=_PC_PHOTO_PREVIEW_MAX)

    def _refresh_list(self) -> None:
        current_index = self._photo_grid.currentIndex()
        current_path = (
            self._visible_photos[current_index].source_path
            if 0 <= current_index < len(self._visible_photos)
            else None
        )

        self._load_token += 1
        self._preview_request_token += 1
        self._thumb_timer.stop()
        self._thumb_queue.clear()
        self._queued_thumb_paths.clear()
        self._thumb_in_flight_paths.clear()
        self._thumb_workers_in_flight = 0
        self._preview_pending.clear()
        self._visible_photos = self._sort_photos(
            [photo for photo in self._photos if self._matches_search(photo)]
        )
        records: list[PhotoTileModel] = []
        target_index = -1
        for index, photo in enumerate(self._visible_photos):
            title = photo.display_name or photo.source_path
            checked = self._selection.get(photo.source_path, True)
            if current_path and photo.source_path == current_path:
                target_index = index
            records.append(
                PhotoTileModel(
                    key=photo.source_path,
                    title=title,
                    pixmap=self._tile_pixmap_cache.get(photo.source_path, QPixmap()),
                    checked=checked,
                )
            )
        self._photo_grid.setRecords(
            records,
            reset_scroll=False,
            preserve_selection=True,
            fallback_index=target_index if target_index >= 0 else (0 if records else -1),
        )
        self._queue_visible_photo_loads(self._load_token)
        if not records:
            self._viewer.clearPreview(
                title="No photos found",
                summary="Add photos to this folder to preview them here.",
            )

    def _on_sort_changed(self, key: str, reverse: bool):
        self._sort_key = key
        self._sort_reverse = reverse
        self._refresh_list()

    def _on_search_changed(self, query: str):
        self._search_query = query.strip().lower()
        self._refresh_list()

    def setAllChecked(self, checked: bool):
        for photo in self._visible_photos:
            self._selection[photo.source_path] = checked
        self._photo_grid.setAllRecordsChecked(checked)

    def _on_visible_photo_indices_changed(self, _indices: object) -> None:
        self._queue_visible_photo_loads(self._load_token)

    def _queue_visible_photo_loads(self, load_token: int) -> None:
        visible_indices = list(self._photo_grid.visibleIndices())
        if not visible_indices:
            return

        first_index = min(visible_indices)
        last_index = max(visible_indices)
        prefetch_start = max(0, first_index - (_PC_PHOTO_PREFETCH_AHEAD // 2))
        prefetch_stop = min(
            len(self._visible_photos),
            last_index + 1 + _PC_PHOTO_PREFETCH_AHEAD,
        )

        next_queue: deque[tuple[str, int]] = deque()
        next_queued_paths: set[str] = set()
        for index in range(prefetch_start, prefetch_stop):
            if not (0 <= index < len(self._visible_photos)):
                continue
            photo = self._visible_photos[index]
            path = photo.source_path
            if (
                not path
                or path in self._tile_pixmap_cache
                or path in self._thumb_in_flight_paths
            ):
                continue
            next_queued_paths.add(path)
            next_queue.append((path, load_token))
        self._thumb_queue = next_queue
        self._queued_thumb_paths = next_queued_paths
        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(0)

    def _process_thumb_batch(self) -> None:
        if not self._thumb_queue or self._thumb_workers_in_flight >= _PC_PHOTO_MAX_THUMB_WORKERS:
            return

        from app_core.runtime import ThreadPoolSingleton, Worker

        batch: list[str] = []
        load_token = self._load_token
        for _ in range(_PC_PHOTO_THUMB_BATCH_SIZE):
            if not self._thumb_queue:
                break
            path, token = self._thumb_queue.popleft()
            if token != self._load_token:
                self._queued_thumb_paths.discard(path)
                continue
            self._queued_thumb_paths.discard(path)
            self._thumb_in_flight_paths.add(path)
            batch.append(path)

        if not batch:
            if self._thumb_queue and not self._thumb_timer.isActive():
                self._thumb_timer.start(1)
            return

        self._thumb_workers_in_flight += 1
        worker = Worker(self._load_thumb_batch, batch)
        worker.signals.result.connect(
            lambda result, lid=load_token: self._on_thumb_batch_loaded(result, lid)
        )
        ThreadPoolSingleton.get_instance().start(worker)

        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(1)

    def _on_thumb_batch_loaded(
        self,
        results: dict[str, tuple[int, int, bytes] | None] | None,
        load_token: int,
    ) -> None:
        self._thumb_workers_in_flight = max(0, self._thumb_workers_in_flight - 1)
        if results is None:
            return
        if load_token != self._load_token:
            for path in results:
                self._thumb_in_flight_paths.discard(path)
            return

        for path, data in results.items():
            self._thumb_in_flight_paths.discard(path)
            pixmap = QPixmap()
            if data is not None:
                width, height, rgba = data
                pixmap = self._pixmap_from_rgba_bytes(width, height, rgba)
            self._tile_pixmap_cache[path] = pixmap
            self._photo_grid.setRecordPixmap(path, pixmap)

        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(0)

    def _on_current_photo_changed(self, row: int):
        if row < 0:
            self._preview_request_token += 1
            self._viewer.clearPreview()
            return
        if row >= len(self._visible_photos):
            self._preview_request_token += 1
            self._viewer.clearPreview()
            return
        photo = self._visible_photos[row]

        album_names = sorted(name for name in photo.album_names if name)
        summary_parts = [", ".join(album_names) if album_names else "All Photos"]
        if photo.size:
            summary_parts.append(format_size(photo.size))
        meta_lines = [photo.source_path] if photo.source_path else []
        cached = self._preview_pixmap_cache.get(photo.source_path, QPixmap())
        self._viewer.setPhoto(
            title=photo.display_name or photo.source_path,
            pixmap=cached,
            summary=" · ".join(part for part in summary_parts if part),
            meta_lines=meta_lines,
        )
        if cached.isNull() and photo.source_path:
            self._viewer.setPreviewPlaceholder("Loading preview...")
            self._request_preview_async(photo.source_path)

    def _request_preview_async(self, path: str) -> None:
        if not path or path in self._preview_pixmap_cache or path in self._preview_pending:
            return

        from app_core.runtime import ThreadPoolSingleton, Worker

        self._preview_request_token += 1
        request_token = self._preview_request_token
        load_token = self._load_token
        self._preview_pending.add(path)
        worker = Worker(self._load_preview, path)
        worker.signals.result.connect(
            lambda result, p=path, lid=load_token, rid=request_token: self._on_preview_loaded(
                p,
                result,
                lid,
                rid,
            )
        )
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_preview_loaded(
        self,
        path: str,
        result: tuple[int, int, bytes] | None,
        load_token: int,
        request_token: int,
    ) -> None:
        self._preview_pending.discard(path)
        if load_token != self._load_token or request_token != self._preview_request_token:
            return

        pixmap = QPixmap()
        if result is not None:
            width, height, rgba = result
            pixmap = self._pixmap_from_rgba_bytes(width, height, rgba)
        self._preview_pixmap_cache[path] = pixmap

        current_index = self._photo_grid.currentIndex()
        if not (0 <= current_index < len(self._visible_photos)):
            return
        current_photo = self._visible_photos[current_index]
        if current_photo.source_path == path:
            self._viewer.setPreviewPixmap(pixmap)

    def _on_photo_checked_changed(self, index: int, checked: bool) -> None:
        if index < 0 or index >= len(self._visible_photos):
            return
        photo = self._visible_photos[index]
        prior = self._selection.get(photo.source_path, True)
        self._selection[photo.source_path] = checked
        if prior != checked:
            self.toggled.emit(photo.source_path, checked)


# ── Main browser widget ─────────────────────────────────────────────────────

_CATEGORY_GLYPHS = {
    "Albums": "music",
    "Artists": "user",
    "Genres": "grid",
    "All Tracks": "music",
    "Photos": "photo",
    "Podcasts": "broadcast",
    "Audiobooks": "book",
    "TV Shows": "monitor",
    "Movies": "film",
    "Music Videos": "video",
}

# Modes that use the grid → drill-in track-list pattern.
_GRID_MODES = {"Albums", "Artists", "Genres", "Podcasts", "Audiobooks",
               "TV Shows", "Music Videos"}

# Modes that go straight to the track list with no grouping.
_LIST_MODES = {"All Tracks", "Movies", "Photos"}


class SelectiveSyncBrowser(QWidget):
    """Full-page widget for browsing a PC media folder and selecting tracks."""
    selection_done = pyqtSignal(str, object)  # (folder, frozenset[str])
    cancelled = pyqtSignal()

    def __init__(
        self,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
        parent=None,
    ):
        super().__init__(parent)
        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._folder = ""
        self._all_tracks: list = []
        self._photo_library = PCPhotoLibrary(sync_root="")
        self._all_photos: list[PCPhoto] = []
        self._groups: dict[str, dict[str, dict]] = {}  # mode -> groups
        self._buckets: dict[str, list] = {}  # media_type -> tracks
        self._selected_tracks: dict[str, bool] = {}
        self._selected_photos: dict[str, bool] = {}
        self._current_mode = "Albums"
        self._current_group: str | None = None
        self._current_group_tracks: list = []
        self._scan_worker: _PCLibScanWorker | None = None

        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self._header = QFrame()
        self._header.setFixedHeight(44)
        self._header.setStyleSheet(f"""
            QFrame {{
                background: {Colors.BG_DARK};
            }}
        """)
        hdr_lay = QHBoxLayout(self._header)
        hdr_lay.setContentsMargins(16, 0, 16, 0)
        hdr_lay.setSpacing(8)

        self._back_btn = QPushButton("\u2190")
        self._back_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self._back_btn.setStyleSheet(back_btn_css())
        self._back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._back_btn.setToolTip("Back")
        self._back_btn.clicked.connect(self._on_cancel)
        hdr_lay.addWidget(self._back_btn)

        title = QLabel("Selective Sync")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        hdr_lay.addWidget(title)

        self._folder_label = QLabel()
        self._folder_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._folder_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        hdr_lay.addWidget(self._folder_label, 1)

        root.addWidget(self._header)

        # Body: sidebar + content
        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        # --- Mini sidebar ---
        self._sidebar = QFrame()
        self._sidebar.setFixedWidth(Metrics.SIDEBAR_WIDTH)
        self._sidebar.setStyleSheet(f"""
            QFrame {{
                background: {Colors.BG_DARK};
                border-right: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        sb_lay = QVBoxLayout(self._sidebar)
        sb_lay.setContentsMargins(8, 12, 8, 12)
        sb_lay.setSpacing(1)

        # Build buttons for every known category; empty buckets are hidden
        # after the library scan completes.
        self._mode_buttons: dict[str, QPushButton] = {}
        self._mode_separators: dict[str, QFrame] = {}
        nav_icon_sz = QSize(20, 20)

        def _make_separator() -> QFrame:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet(
                f"background: {Colors.BORDER_SUBTLE}; border: none; margin: 4px 6px;"
            )
            return sep

        _ordered_cats = [
            "Albums", "Artists", "Genres", "All Tracks",
            "Photos",
            "__sep_media__",
            "Podcasts", "Audiobooks",
            "__sep_video__",
            "TV Shows", "Movies", "Music Videos",
        ]
        for cat in _ordered_cats:
            if cat.startswith("__sep"):
                sep = _make_separator()
                sb_lay.addWidget(sep)
                self._mode_separators[cat] = sep
                continue
            icon_name = _CATEGORY_GLYPHS[cat]
            btn = QPushButton(cat)
            btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            icon = glyph_icon(icon_name, 20, Colors.TEXT_SECONDARY)
            if icon:
                btn.setIcon(icon)
                btn.setIconSize(nav_icon_sz)
            btn.setStyleSheet(sidebar_nav_css())
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda checked, c=cat: self._on_mode_clicked(c))
            sb_lay.addWidget(btn)
            self._mode_buttons[cat] = btn

        sb_lay.addStretch()

        # Select / Deselect All (apply to ALL tracks, not just visible)
        sel_all = QPushButton("Select All")
        sel_all.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        sel_all.setStyleSheet(btn_css(padding="5px 10px", radius=Metrics.BORDER_RADIUS_SM))
        sel_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        sel_all.clicked.connect(self._on_select_all)
        sb_lay.addWidget(sel_all)

        desel_all = QPushButton("Deselect All")
        desel_all.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        desel_all.setStyleSheet(btn_css(padding="5px 10px", radius=Metrics.BORDER_RADIUS_SM))
        desel_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        desel_all.clicked.connect(self._on_deselect_all)
        sb_lay.addWidget(desel_all)

        body_lay.addWidget(self._sidebar)

        # --- Content area (stacked) ---
        self._content = QStackedWidget()

        # Page 0: loading spinner
        loading_page = QWidget()
        lp_lay = QVBoxLayout(loading_page)
        lp_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label = QLabel("Scanning library\u2026")
        self._loading_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE))
        self._loading_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp_lay.addWidget(self._loading_label)
        self._content.addWidget(loading_page)  # index 0

        # Page 1: grid header bar + per-category grid stack
        from .gridHeaderBar import GridHeaderBar
        grid_page = QWidget()
        grid_page_lay = QVBoxLayout(grid_page)
        grid_page_lay.setContentsMargins(0, 0, 0, 0)
        grid_page_lay.setSpacing(0)

        self._grid_header = GridHeaderBar()
        self._grid_header.sort_changed.connect(self._on_grid_sort)
        self._grid_header.search_changed.connect(self._on_grid_search)
        grid_page_lay.addWidget(self._grid_header)

        self._grid_stack = QStackedWidget()
        self._grids: dict[str, PCMusicBrowserGrid] = {}
        self._grid_scrolls: dict[str, QWidget] = {}
        self._grid_loaded: set[str] = set()  # categories already populated

        for cat in ("Albums", "Artists", "Genres",
                    "Podcasts", "Audiobooks", "TV Shows", "Music Videos"):
            grid = PCMusicBrowserGrid(settings_service=self._settings_service)
            grid.item_selected.connect(self._on_grid_item_clicked)
            scroll = make_scroll_area()
            scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            scroll.setWidget(grid)
            grid.attachScrollArea(scroll)
            self._grids[cat] = grid
            self._grid_scrolls[cat] = scroll
            self._grid_stack.addWidget(scroll)

        grid_page_lay.addWidget(self._grid_stack, 1)
        self._content.addWidget(grid_page)  # index 1

        # Page 2: track list
        self._track_list = PCTrackListView(
            settings_service=self._settings_service,
            device_sessions=self._device_sessions,
        )
        self._track_list.toggled.connect(self._on_track_toggled)
        self._track_list.back_requested.connect(self._on_track_back)
        self._track_list.select_all_requested.connect(self._on_group_select_all)
        self._track_list.deselect_all_requested.connect(self._on_group_deselect_all)
        self._content.addWidget(self._track_list)  # index 2

        # Page 3: photo picker
        self._photo_list = PCPhotoListView()
        self._photo_list.toggled.connect(self._on_photo_toggled)
        self._photo_list.select_all_requested.connect(self._on_select_all_photos)
        self._photo_list.deselect_all_requested.connect(self._on_deselect_all_photos)
        self._content.addWidget(self._photo_list)  # index 3

        body_lay.addWidget(self._content, 1)
        root.addWidget(body, 1)

        # Footer
        self._footer = QFrame()
        self._footer.setFixedHeight(48)
        self._footer.setStyleSheet(f"""
            QFrame {{
                background: {Colors.BG_DARK};
                border-top: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        ft_lay = QHBoxLayout(self._footer)
        ft_lay.setContentsMargins(16, 0, 16, 0)
        ft_lay.setSpacing(8)

        self._count_label = QLabel()
        self._count_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._count_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        ft_lay.addWidget(self._count_label, 1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        cancel_btn.setStyleSheet(btn_css(padding="6px 16px", radius=Metrics.BORDER_RADIUS_SM))
        cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel_btn.clicked.connect(self._on_cancel)
        ft_lay.addWidget(cancel_btn)

        self._done_btn = QPushButton("Done Selecting")
        self._done_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.Bold))
        self._done_btn.setStyleSheet(btn_css(
            bg=Colors.ACCENT_DIM,
            bg_hover=Colors.ACCENT_HOVER,
            bg_press=Colors.ACCENT_PRESS,
            fg=Colors.TEXT_ON_ACCENT,
            border=f"1px solid {Colors.ACCENT_BORDER}",
            padding="6px 16px",
            radius=Metrics.BORDER_RADIUS_SM,
        ))
        self._done_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._done_btn.clicked.connect(self._on_done)
        ft_lay.addWidget(self._done_btn)

        root.addWidget(self._footer)

    # ── Public API ───────────────────────────────────────────────────────

    def refresh_artwork_appearance(self) -> None:
        """Refresh visible grid artwork for the current global appearance."""
        for grid in self._grids.values():
            grid.refresh_artwork_appearance()

    def _cleanup_scan_worker(self):
        """Disconnect and clean up the current scan worker, if any."""
        if self._scan_worker is None:
            return
        try:
            self._scan_worker.finished.disconnect()
            self._scan_worker.error.disconnect()
        except (TypeError, RuntimeError):
            pass
        if self._scan_worker.isRunning():
            self._scan_worker.quit()
            self._scan_worker.wait(2000)
            if self._scan_worker.isRunning():
                self._scan_worker.terminate()
                self._scan_worker.wait(1000)
        self._scan_worker.deleteLater()
        self._scan_worker = None

    def load(self, folder: str):
        """Start scanning *folder* and prepare the browser."""
        self._folder = folder
        self._all_tracks = []
        self._photo_library = PCPhotoLibrary(sync_root=folder)
        self._all_photos = []
        self._groups.clear()
        self._buckets.clear()
        self._selected_tracks.clear()
        self._selected_photos.clear()
        self._current_mode = "Albums"
        self._grid_loaded.clear()
        self._current_group = None
        self._current_group_tracks = []
        for grid in self._grids.values():
            grid._art_cache.clear()
            grid._art_pending.clear()
            grid._art_seen.clear()

        # Truncate long paths for the header
        display = folder
        if len(display) > 60:
            display = "\u2026" + display[-57:]
        self._folder_label.setText(display)

        self._content.setCurrentIndex(0)  # loading
        self._update_footer()
        self._highlight_mode("Albums")

        # Stop and clean up any prior worker
        self._cleanup_scan_worker()

        self._scan_worker = _PCLibScanWorker(folder)
        self._scan_worker.finished.connect(self._on_scan_complete)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    # ── Scan callbacks ───────────────────────────────────────────────────

    def _on_scan_complete(self, tracks: list):
        if isinstance(tracks, dict):
            self._all_tracks = list(tracks.get("tracks", []))
            self._photo_library = tracks.get("photos") or PCPhotoLibrary(sync_root=self._folder)
        else:
            self._all_tracks = list(tracks)
            self._photo_library = PCPhotoLibrary(sync_root=self._folder)
        self._all_photos = sorted(
            self._photo_library.photos.values(),
            key=lambda photo: (photo.display_name or photo.source_path).lower(),
        )
        self._selected_tracks = {t.path: True for t in self._all_tracks}
        self._selected_photos = {photo.source_path: True for photo in self._all_photos}
        self._build_groups()
        self._apply_sidebar_visibility()
        # Pick the first mode that actually has content.
        for mode in ("Albums", "Artists", "Genres", "All Tracks", "Photos",
                     "Podcasts", "Audiobooks",
                     "TV Shows", "Movies", "Music Videos"):
            if self._mode_has_content(mode):
                self._show_mode(mode)
                return
        # Nothing to show — leave loading label.
        self._loading_label.setText("No music or photos found in this folder.")

    def _on_scan_error(self, msg: str):
        self._loading_label.setText(f"Scan failed: {msg}")

    # ── Grouping ─────────────────────────────────────────────────────────

    @staticmethod
    def _art_candidates(track_list: list) -> list[str]:
        """Build a list of candidate file paths for artwork extraction.

        Prioritises files that already have an art_hash (embedded art is
        known to exist) and includes a few fallbacks so the background
        worker can also check folder images.
        """
        with_art = [t.path for t in track_list if getattr(t, "art_hash", None)]
        without = [t.path for t in track_list if not getattr(t, "art_hash", None)]
        # Return art-hash files first, then up to 3 fallbacks.
        return with_art[:5] + without[:3]

    @staticmethod
    def _classify(track) -> str:
        """Return the media-type bucket for *track*.

        Priority: podcasts > audiobooks > video_kind > music. A track is only
        counted in one bucket so podcasts don't leak into Albums.
        """
        if getattr(track, "is_podcast", False):
            return "podcast"
        if getattr(track, "is_audiobook", False):
            return "audiobook"
        if getattr(track, "is_video", False):
            kind = getattr(track, "video_kind", "") or ""
            if kind == "tv_show":
                return "tv_show"
            if kind == "music_video":
                return "music_video"
            # Default unclassified videos to movies.
            return "movie"
        return "music"

    def _build_groups(self):
        """Partition tracks by media type, then build per-mode groupings.

        Music tracks power the existing Albums / Artists / Genres / All
        Tracks views.  Podcasts, audiobooks, TV shows, and music videos get
        their own grid groupings; movies use the direct track-list view.
        """
        # ── Partition by media type ───────────────────────────────────────
        buckets: dict[str, list] = {
            "music": [], "podcast": [], "audiobook": [],
            "tv_show": [], "movie": [], "music_video": [],
        }
        for t in self._all_tracks:
            buckets[self._classify(t)].append(t)
        self._buckets = buckets

        # Reset all mode group maps — stale modes must disappear between
        # scans when the user switches folders.
        self._groups.clear()

        self._groups["Albums"] = self._build_music_albums(buckets["music"])
        self._groups["Artists"] = self._build_music_artists(buckets["music"])
        self._groups["Genres"] = self._build_music_genres(buckets["music"])
        self._groups["Podcasts"] = self._build_podcast_shows(buckets["podcast"])
        self._groups["Audiobooks"] = self._build_audiobooks(buckets["audiobook"])
        self._groups["TV Shows"] = self._build_tv_shows(buckets["tv_show"])
        self._groups["Music Videos"] = self._build_music_videos(buckets["music_video"])
        # Movies and All Tracks are list-mode and don't need pre-built groups.

    # ── Per-type group builders ──────────────────────────────────────────

    def _build_music_albums(self, tracks: list) -> dict[str, dict]:
        album_raw: dict[tuple[str, str], list] = defaultdict(list)
        for t in tracks:
            album_artist = getattr(t, "album_artist", None) or t.artist or "Unknown Artist"
            album_raw[(album_artist, t.album or "Unknown Album")].append(t)

        _by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for artist, album in album_raw:
            _by_name[album].append((artist, album))

        out: dict[str, dict] = {}
        for (artist, album), group in album_raw.items():
            year = next((getattr(t, "year", 0) or 0 for t in group
                         if getattr(t, "year", 0) or 0), 0)
            sub_parts = [artist]
            if year:
                sub_parts.append(str(year))
            sub_parts.append(f"{len(group)} track{'s' if len(group) != 1 else ''}")

            display_title = album
            if len(_by_name.get(album, [])) > 1:
                display_title = f"{album} ({artist})"

            out[display_title] = {
                "tracks": group,
                "subtitle": " \xb7 ".join(sub_parts),
                "art_paths": self._art_candidates(group),
                "category": "Albums",
                "filter_key": "album",
                "filter_value": album,
                "album": album,
                "artist": artist,
                "year": year,
                "track_count": len(group),
            }
        return out

    def _build_music_artists(self, tracks: list) -> dict[str, dict]:
        artist_raw: dict[str, list] = defaultdict(list)
        for t in tracks:
            artist_raw[getattr(t, "album_artist", None) or t.artist or "Unknown Artist"].append(t)

        out: dict[str, dict] = {}
        for artist, group in artist_raw.items():
            album_count = len({(t.album or "") for t in group})
            sub_parts = []
            if album_count > 1:
                sub_parts.append(f"{album_count} albums")
            sub_parts.append(f"{len(group)} track{'s' if len(group) != 1 else ''}")
            out[artist] = {
                "tracks": group,
                "subtitle": " \xb7 ".join(sub_parts),
                "art_paths": self._art_candidates(group),
                "category": "Artists",
                "filter_key": "artist",
                "filter_value": artist,
                "album_count": album_count,
                "track_count": len(group),
            }
        return out

    def _build_music_genres(self, tracks: list) -> dict[str, dict]:
        genre_raw: dict[str, list] = defaultdict(list)
        for t in tracks:
            genre_raw[getattr(t, "genre", None) or "Unknown Genre"].append(t)

        out: dict[str, dict] = {}
        for genre, group in genre_raw.items():
            artist_count = len({(getattr(t, "album_artist", None) or t.artist or "") for t in group})
            sub_parts = []
            if artist_count > 1:
                sub_parts.append(f"{artist_count} artists")
            sub_parts.append(f"{len(group)} track{'s' if len(group) != 1 else ''}")
            out[genre] = {
                "tracks": group,
                "subtitle": " \xb7 ".join(sub_parts),
                "art_paths": self._art_candidates(group),
                "category": "Genres",
                "filter_key": "genre",
                "filter_value": genre,
                "artist_count": artist_count,
                "track_count": len(group),
            }
        return out

    def _build_podcast_shows(self, tracks: list) -> dict[str, dict]:
        """Group podcast episodes by show (album tag is typically the show)."""
        show_raw: dict[str, list] = defaultdict(list)
        for t in tracks:
            show = t.album or t.artist or "Unknown Podcast"
            show_raw[show].append(t)

        out: dict[str, dict] = {}
        for show, eps in show_raw.items():
            # Sort newest first when release dates are available; fall back
            # to track number so the drill-in view is ordered predictably.
            eps.sort(key=lambda e: (
                -(getattr(e, "date_released", 0) or 0),
                getattr(e, "track_number", 0) or 0,
            ))
            n = len(eps)
            out[show] = {
                "tracks": eps,
                "subtitle": f"{n} episode{'s' if n != 1 else ''}",
                "art_paths": self._art_candidates(eps),
                "category": "Podcasts",
                "filter_key": "podcast",
                "filter_value": show,
                "track_count": n,
            }
        return out

    def _build_audiobooks(self, tracks: list) -> dict[str, dict]:
        """Group audiobook chapters/tracks by book (album tag)."""
        book_raw: dict[tuple[str, str], list] = defaultdict(list)
        for t in tracks:
            author = getattr(t, "album_artist", None) or t.artist or "Unknown Author"
            book = t.album or t.title or "Unknown Book"
            book_raw[(author, book)].append(t)

        out: dict[str, dict] = {}
        for (author, book), parts in book_raw.items():
            parts.sort(key=lambda p: (
                getattr(p, "disc_number", 0) or 0,
                getattr(p, "track_number", 0) or 0,
            ))
            total_ms = sum(getattr(p, "duration_ms", 0) or 0 for p in parts)
            sub_parts = [author]
            if total_ms:
                sub_parts.append(format_duration_human(total_ms))
            sub_parts.append(f"{len(parts)} part{'s' if len(parts) != 1 else ''}")
            out[book] = {
                "tracks": parts,
                "subtitle": " \xb7 ".join(sub_parts),
                "art_paths": self._art_candidates(parts),
                "category": "Audiobooks",
                "filter_key": "audiobook",
                "filter_value": book,
                "track_count": len(parts),
            }
        return out

    def _build_tv_shows(self, tracks: list) -> dict[str, dict]:
        """Group TV episodes by (show, season)."""
        show_raw: dict[tuple[str, int], list] = defaultdict(list)
        for t in tracks:
            show = getattr(t, "show_name", None) or t.album or t.artist or "Unknown Show"
            season = getattr(t, "season_number", 0) or 0
            show_raw[(show, season)].append(t)

        out: dict[str, dict] = {}
        for (show, season), eps in show_raw.items():
            eps.sort(key=lambda e: getattr(e, "episode_number", 0) or 0)
            n = len(eps)
            title = f"{show} \u2014 Season {season}" if season else show
            sub_parts = []
            if season:
                sub_parts.append(f"Season {season}")
            sub_parts.append(f"{n} episode{'s' if n != 1 else ''}")
            out[title] = {
                "tracks": eps,
                "subtitle": " \xb7 ".join(sub_parts),
                "art_paths": self._art_candidates(eps),
                "category": "TV Shows",
                "filter_key": "tv_show",
                "filter_value": title,
                "show": show,
                "season": season,
                "track_count": n,
            }
        return out

    def _build_music_videos(self, tracks: list) -> dict[str, dict]:
        """Group music videos by artist."""
        artist_raw: dict[str, list] = defaultdict(list)
        for t in tracks:
            artist_raw[getattr(t, "album_artist", None) or t.artist or "Unknown Artist"].append(t)

        out: dict[str, dict] = {}
        for artist, vids in artist_raw.items():
            n = len(vids)
            out[artist] = {
                "tracks": vids,
                "subtitle": f"{n} video{'s' if n != 1 else ''}",
                "art_paths": self._art_candidates(vids),
                "category": "Music Videos",
                "filter_key": "artist",
                "filter_value": artist,
                "track_count": n,
            }
        return out

    # ── Sidebar visibility ───────────────────────────────────────────────

    def _mode_has_content(self, mode: str) -> bool:
        if mode == "All Tracks":
            return bool(self._buckets.get("music"))
        if mode == "Photos":
            return bool(self._all_photos)
        if mode == "Movies":
            return bool(self._buckets.get("movie"))
        return bool(self._groups.get(mode))

    def _apply_sidebar_visibility(self):
        """Hide buttons for empty media buckets; hide separators that
        become orphans because every neighbor is hidden.

        Uses bucket contents directly (rather than ``isVisible()``) so the
        calculation is correct before the widget is first shown.
        """
        has: dict[str, bool] = {
            cat: self._mode_has_content(cat) for cat in self._mode_buttons
        }
        for cat, btn in self._mode_buttons.items():
            btn.setVisible(has[cat])

        music_section = any(has[c] for c in
                            ("Albums", "Artists", "Genres", "All Tracks", "Photos"))
        non_music = any(has[c] for c in (
            "Podcasts", "Audiobooks", "TV Shows", "Movies", "Music Videos"
        ))
        if "__sep_media__" in self._mode_separators:
            # Only show when there's content on BOTH sides of the divider.
            self._mode_separators["__sep_media__"].setVisible(
                music_section and non_music
            )

        audio_media = any(has[c] for c in ("Podcasts", "Audiobooks"))
        video_media = any(has[c] for c in ("TV Shows", "Movies", "Music Videos"))
        if "__sep_video__" in self._mode_separators:
            self._mode_separators["__sep_video__"].setVisible(
                audio_media and video_media
            )

    # ── Mode switching ───────────────────────────────────────────────────

    def _on_mode_clicked(self, mode: str):
        self._current_group = None
        self._current_group_tracks = []
        self._show_mode(mode)

    def _show_mode(self, mode: str):
        self._current_mode = mode
        self._highlight_mode(mode)

        if mode in _LIST_MODES:
            # Direct track list — no grouping, no grid.
            if mode == "Photos":
                self._current_group = mode
                self._current_group_tracks = []
                self._photo_list.setPhotos(self._all_photos, self._selected_photos)
                self._content.setCurrentIndex(3)
            else:  # Movies
                if mode == "All Tracks":
                    tracks = self._buckets.get("music", [])
                    title = "All Tracks"
                    noun = ("track", "tracks")
                else:
                    tracks = self._buckets.get("movie", [])
                    title = "Movies"
                    noun = ("movie", "movies")
                self._current_group = mode
                self._current_group_tracks = tracks
                self._track_list.setTitle(title)
                n = len(tracks)
                self._track_list.setSubtitle(
                    f"{n} {noun[0] if n == 1 else noun[1]}"
                )
                total_ms = sum(getattr(t, "duration_ms", 0) or 0 for t in tracks)
                total_bytes = sum(getattr(t, "size", 0) or 0 for t in tracks)
                meta_parts = []
                if total_ms:
                    meta_parts.append(format_duration_human(total_ms))
                if total_bytes:
                    meta_parts.append(format_size(total_bytes))
                self._track_list.setMeta(" \u00b7 ".join(meta_parts))
                self._track_list.setHeroVisible(False)
                self._track_list.setBackVisible(False)
                self._track_list.setTracks(tracks, self._selected_tracks)
                self._content.setCurrentIndex(2)
        else:
            grid = self._grids.get(mode)
            if grid and mode not in self._grid_loaded:
                groups = self._groups.get(mode, {})
                grid.loadPCCategory(groups)
                self._grid_loaded.add(mode)
            # Update header bar and reset sort/search for this category
            self._grid_header.setCategory(mode)
            self._grid_header.blockSignals(True)
            self._grid_header.resetState()
            self._grid_header.blockSignals(False)
            # Sync the grid to default sort (header signals were blocked)
            # Only reset if the grid's sort/search drifted from defaults
            if grid and (grid._sort_key != "title" or grid._sort_reverse
                         or grid._search_query):
                grid.resetFilters()
            # Switch the inner grid stack to the right category
            scroll = self._grid_scrolls.get(mode)
            if scroll:
                self._grid_stack.setCurrentWidget(scroll)
            self._content.setCurrentIndex(1)
            if grid:
                grid.rearrangeGrid()

        self._update_footer()

    def _on_grid_sort(self, key: str, reverse: bool):
        """Forward sort change to the currently visible grid."""
        grid = self._grids.get(self._current_mode)
        if grid:
            grid.setSort(key, reverse)

    def _on_grid_search(self, query: str):
        """Forward search query to the currently visible grid."""
        grid = self._grids.get(self._current_mode)
        if grid:
            grid.setSearchFilter(query)

    def _highlight_mode(self, active: str):
        for cat, btn in self._mode_buttons.items():
            selected = cat == active
            btn.setStyleSheet(
                sidebar_nav_selected_css() if selected else sidebar_nav_css()
            )
            icon_name = _CATEGORY_GLYPHS.get(cat)
            if icon_name:
                color = Colors.ACCENT if selected else Colors.TEXT_SECONDARY
                icon = glyph_icon(icon_name, 20, color)
                if icon:
                    btn.setIcon(icon)

    # ── Grid item click → drill into track list ──────────────────────────

    def _on_grid_item_clicked(self, item_data: dict):
        key = item_data.get("title", "")
        mode = self._current_mode
        groups = self._groups.get(mode, {})
        group = groups.get(key)
        if group is None:
            return

        self._current_group = key
        self._current_group_tracks = group["tracks"]

        # Populate hero header
        self._track_list.setTitle(key)
        self._track_list.setSubtitle(group.get("subtitle", ""))

        # Build meta line: total duration + total size
        tracks = group["tracks"]
        total_ms = sum(getattr(t, "duration_ms", 0) or 0 for t in tracks)
        total_bytes = sum(getattr(t, "size", 0) or 0 for t in tracks)
        meta_parts = []
        if total_ms:
            meta_parts.append(format_duration_human(total_ms))
        if total_bytes:
            meta_parts.append(format_size(total_bytes))
        self._track_list.setMeta(" \u00b7 ".join(meta_parts))

        # Grab artwork pixmap from the grid item widget
        pixmap = None
        dcol = item_data.get("dominant_color")
        active_grid = self._grids.get(self._current_mode)
        for gi in (active_grid.gridItems if active_grid else []):
            if not isinstance(gi, MusicBrowserGridItem):
                continue
            if gi.item_data.get("title") == key:
                pm = gi.img_label.pixmap()
                if pm and not pm.isNull():
                    pixmap = pm
                if not dcol:
                    dcol = gi.item_data.get("dominant_color")
                break

        self._track_list.setHeroArt(pixmap)
        if dcol:
            self._track_list.setHeroColor(*dcol)
        else:
            self._track_list.resetHeroColor()

        self._track_list.setHeroVisible(True)
        self._track_list.setBackVisible(True)
        self._track_list.setTracks(tracks, self._selected_tracks)
        self._content.setCurrentIndex(2)

    def _on_track_back(self):
        self._current_group = None
        self._current_group_tracks = []
        # Grid is still intact behind the track list — just switch back
        self._content.setCurrentIndex(1)

    # ── Checkbox toggling ────────────────────────────────────────────────

    def _on_track_toggled(self, path: str, checked: bool):
        self._selected_tracks[path] = checked
        self._update_footer()

    def _on_select_all(self):
        for path in self._selected_tracks:
            self._selected_tracks[path] = True
        for path in self._selected_photos:
            self._selected_photos[path] = True
        # Refresh track list if visible
        if self._content.currentIndex() == 2:
            self._track_list.setAllChecked(True)
        if self._content.currentIndex() == 3:
            self._photo_list.setAllChecked(True)
        self._update_footer()

    def _on_deselect_all(self):
        for path in self._selected_tracks:
            self._selected_tracks[path] = False
        for path in self._selected_photos:
            self._selected_photos[path] = False
        if self._content.currentIndex() == 2:
            self._track_list.setAllChecked(False)
        if self._content.currentIndex() == 3:
            self._photo_list.setAllChecked(False)
        self._update_footer()

    def _on_group_select_all(self):
        """Select all tracks in the current drilled-in group."""
        for t in self._current_group_tracks:
            self._selected_tracks[t.path] = True
        self._track_list.setAllChecked(True)
        self._update_footer()

    def _on_group_deselect_all(self):
        """Deselect all tracks in the current drilled-in group."""
        for t in self._current_group_tracks:
            self._selected_tracks[t.path] = False
        self._track_list.setAllChecked(False)
        self._update_footer()

    def _on_photo_toggled(self, path: str, checked: bool):
        self._selected_photos[path] = checked
        self._update_footer()

    def _on_select_all_photos(self):
        for path in self._selected_photos:
            self._selected_photos[path] = True
        self._photo_list.setAllChecked(True)
        self._update_footer()

    def _on_deselect_all_photos(self):
        for path in self._selected_photos:
            self._selected_photos[path] = False
        self._photo_list.setAllChecked(False)
        self._update_footer()

    # ── Footer ───────────────────────────────────────────────────────────

    def _update_footer(self):
        total_tracks = len(self._selected_tracks)
        checked_tracks = sum(1 for v in self._selected_tracks.values() if v)
        total_photos = len(self._selected_photos)
        checked_photos = sum(1 for v in self._selected_photos.values() if v)
        parts: list[str] = []
        if total_tracks:
            parts.append(f"{checked_tracks} of {total_tracks} tracks selected")
        if total_photos:
            parts.append(f"{checked_photos} of {total_photos} photos selected")
        self._count_label.setText(" · ".join(parts) if parts else "No music or photos found")
        self._done_btn.setEnabled((checked_tracks + checked_photos) > 0)

    # ── Done / Cancel ────────────────────────────────────────────────────

    def _on_done(self):
        selected_track_paths = frozenset(
            path for path, checked in self._selected_tracks.items() if checked
        )
        selected_photo_imports: list[tuple[str, str]] = []
        for photo in self._all_photos:
            if not self._selected_photos.get(photo.source_path, False):
                continue
            album_names = sorted(name for name in photo.album_names if name)
            if album_names:
                selected_photo_imports.extend((photo.source_path, album_name) for album_name in album_names)
            else:
                selected_photo_imports.append((photo.source_path, ""))
        self.selection_done.emit(self._folder, {
            "tracks": selected_track_paths,
            "photos": tuple(selected_photo_imports),
        })

    def _on_cancel(self):
        self._cleanup_scan_worker()
        self.cancelled.emit()
