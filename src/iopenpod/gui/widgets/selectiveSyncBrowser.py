"""
SelectiveSyncBrowser — full-page PC library browser for selective sync.

Mirrors the look and feel of the main MusicBrowser (grid cards, sidebar
categories, track list) but displays tracks from a local PC folder instead
of the iPod database.  The user browses albums/artists/genres, checks or
unchecks individual tracks, then submits only the selected paths for sync.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from PIL import Image, ImageOps
from PyQt6.QtCore import QPoint, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iopenpod.application.progress import ETATracker
from iopenpod.artworkdb_writer.art_extractor import (
    extract_art,
    find_folder_art,
)
from iopenpod.infrastructure.media_folders import (
    media_folder_entries_to_settings,
    media_folder_paths,
)
from iopenpod.itunesdb_shared.album_identity import (
    album_identity_from_track,
    group_tracks_by_album_identity,
)
from iopenpod.sync.pc_library import PCTrack
from iopenpod.sync.photos import PCPhoto, PCPhotoLibrary, scan_pc_photos

from ..glyphs import glyph_icon
from ..styles import (
    FONT_FAMILY,
    Colors,
    Design,
    Metrics,
    accent_btn_css,
    back_btn_css,
    btn_css,
    context_menu_css,
    make_scroll_area,
    progress_bar_css,
    sidebar_panel_css,
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
from .sidebarNavButton import SidebarNavButton

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from iopenpod.application.services import DeviceSessionService, SettingsService

# ── Artwork extraction helpers ─────────────────────────────────────────────

_ART_BATCH = 20  # files per background worker
_PC_PHOTO_THUMB_BATCH_SIZE = 6
_PC_PHOTO_PREFETCH_AHEAD = 6
_PC_PHOTO_MAX_THUMB_WORKERS = 2
_PC_PHOTO_PREVIEW_MAX = (1600, 1600)
PCPhotoTilePayload = tuple[int, int, bytes, tuple[int, int, int] | None]


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


def _normalize_folder_entries(folders: object) -> list[dict[str, object]]:
    return media_folder_entries_to_settings(folders)


def _folder_label(folders: list[str]) -> str:
    if not folders:
        return "No folders selected"
    if len(folders) == 1:
        display = folders[0]
        return "\u2026" + display[-57:] if len(display) > 60 else display
    names = [os.path.basename(os.path.normpath(folder)) or folder for folder in folders[:3]]
    suffix = "" if len(folders) <= 3 else f" + {len(folders) - 3} more"
    return f"{len(folders)} folders: {', '.join(names)}{suffix}"


# ── Background workers ──────────────────────────────────────────────────────


class _PCLibScanWorker(QThread):
    """Scan media folders with PCLibrary and emit the track list."""
    finished = pyqtSignal(object)  # {"tracks": list[PCTrack], "photos": PCPhotoLibrary, "playlists": SyncPlaylistDiscovery}
    progress = pyqtSignal(str, int, int, str)  # stage, current, total, filename
    error = pyqtSignal(str)

    def __init__(
        self,
        folders: object,
        include_video: bool = True,
        include_photo: bool = True,
        max_workers: int | None = None,
    ):
        super().__init__()
        self._folder_entries = _normalize_folder_entries(folders)
        self._folders = media_folder_paths(self._folder_entries)
        self._include_video = include_video
        self._include_photo = include_photo
        self._max_workers = max_workers
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def run(self):
        try:
            from iopenpod.sync.pc_library import PCLibrary
            lib = PCLibrary(self._folder_entries)

            def _on_track_progress(current: int, total: int, filename: str) -> None:
                self.progress.emit("scan_pc", current, total, filename)

            tracks = list(
                lib.scan(
                    include_video=self._include_video,
                    progress_callback=_on_track_progress,
                    max_workers=self._max_workers,
                    is_cancelled=self._is_cancelled,
                )
            )
            if self._is_cancelled():
                return
            playlist_discovery = None
            try:
                from iopenpod.sync.sync_playlist_files import (
                    discover_sync_playlist_files,
                    normalize_sync_playlist_path,
                )

                self.progress.emit("scan_playlists", 0, 0, "")
                playlist_discovery = discover_sync_playlist_files(
                    lib.root_entries,
                    include_video=self._include_video,
                )
                existing_source_keys = {
                    normalize_sync_playlist_path(track.path)
                    for track in tracks
                }
                extra_media_paths = [
                    path
                    for path in playlist_discovery.media_paths
                    if normalize_sync_playlist_path(path) not in existing_source_keys
                ]
                total_extra = len(extra_media_paths)
                for index, raw_path in enumerate(extra_media_paths, start=1):
                    if self._is_cancelled():
                        return
                    path = Path(raw_path)
                    self.progress.emit("scan_playlists", index, total_extra, path.name)
                    try:
                        track = lib._read_track(path)
                    except Exception as exc:
                        log.warning("Failed to read playlist-referenced track %s: %s", path, exc)
                        continue
                    if track is None:
                        continue
                    tracks.append(track)
                    existing_source_keys.add(normalize_sync_playlist_path(track.path))
            except Exception as exc:
                log.warning("Selective sync playlist scan failed: %s", exc)
            if self._include_photo:
                if self._is_cancelled():
                    return
                self.progress.emit("scan_photos", 0, 0, "")

                def _on_photo_progress(current: int, total: int, filename: str) -> None:
                    self.progress.emit("scan_photos", current, total, filename)

                photos = scan_pc_photos(
                    self._folder_entries,
                    progress_callback=_on_photo_progress,
                    max_workers=self._max_workers,
                    is_cancelled=self._is_cancelled,
                )
            else:
                photos = PCPhotoLibrary(sync_root=os.pathsep.join(self._folders))
            if self._is_cancelled():
                return
            self.finished.emit({
                "tracks": tracks,
                "photos": photos,
                "playlists": playlist_discovery,
            })
        except Exception as e:
            if self._is_cancelled():
                return
            self.error.emit(str(e))


# ── PC-aware grid ───────────────────────────────────────────────────────────

class PCMusicBrowserGrid(MusicBrowserGrid):
    """Subclass of MusicBrowserGrid that loads artwork from embedded tags
    (or folder images) instead of the iPod ArtworkDB."""

    def __init__(
        self,
        *,
        device_sessions: DeviceSessionService | None = None,
        settings_service: SettingsService | None = None,
    ):
        super().__init__(
            device_sessions=device_sessions,
            settings_service=settings_service,
            multi_select_enabled=True,
        )
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
            art_paths = info.get("art_paths", [])
            artwork_id_ref = info.get("artwork_id_ref")
            art_key = key if art_paths else artwork_id_ref
            if art_paths:
                self._pc_art_map[key] = art_paths

            items.append({
                "title": key,
                "subtitle": info.get("subtitle", ""),
                "artwork_id_ref": artwork_id_ref,
                "_grid_art_key": art_key,
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
            if record.artwork_id is not None:
                return super()._load_cached_artwork(record)
            return None
        return _ART_CACHE_UNSET

    def _load_art_async(self):
        if not self._pc_mode:
            super()._load_art_async()
            return

        records = self._visible_records_needing_art()
        if not records:
            return

        if any(
            record.artwork_id is not None
            and record.artwork_key is not None
            and not self._pc_art_map.get(str(record.artwork_key))
            for record in records
        ):
            super()._load_art_async()

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

        load_id = self._load_id
        pool = ThreadPoolSingleton.get_instance()
        batch: list[tuple[str, list[str]]] = []

        for record in records:
            key = str(record.artwork_key)
            paths = self._pc_art_map.get(key, [])
            if not paths:
                continue
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

_HERO_ART_SIZE = 176  # px, artwork square in the hero header

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

        def _patched_populate(*, preserve_column_layout: bool = True) -> None:
            owner._has_checkbox_col = False
            _orig_populate(preserve_column_layout=preserve_column_layout)

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
        self._hero.setMaximumHeight(312)
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
        top_lay.setContentsMargins(12, 4, 12, 0)
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
        body_lay.setContentsMargins(20, 4, 20, 10)
        body_lay.setSpacing(16)

        # Artwork
        self._hero_art = QLabel()
        self._hero_art.setFixedSize(_HERO_ART_SIZE, _HERO_ART_SIZE)
        self._hero_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_lay.addWidget(self._hero_art, 0, Qt.AlignmentFlag.AlignTop)

        # Info column
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 2, 0, 0)
        info_col.setSpacing(2)

        self._title_label = QLabel()
        self._title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        self._title_label.setWordWrap(True)
        info_col.addWidget(self._title_label)

        self._artist_label = QLabel()
        self._artist_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.DemiBold))
        self._artist_label.setWordWrap(True)
        info_col.addWidget(self._artist_label)

        self._subtitle_label = QLabel()
        self._subtitle_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        info_col.addWidget(self._subtitle_label)

        self._meta_label = QLabel()
        self._meta_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        info_col.addWidget(self._meta_label)

        info_col.addSpacing(6)

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

    def setArtist(self, artist: str):
        text = artist.strip()
        self._artist_label.setText(text)
        self._artist_label.setVisible(bool(text))

    def setMeta(self, meta: str):
        self._meta_label.setText(meta)

    def setHeroColor(self, r: int, g: int, b: int):
        """Tint the hero header background with the artwork's dominant color."""
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
        self._artist_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        self._subtitle_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._meta_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        _default_btn = btn_css(padding="5px 12px", radius=Metrics.BORDER_RADIUS_SM)
        self._back_btn.setStyleSheet(back_btn_css())
        self._sel_btn.setStyleSheet(_default_btn)
        self._desel_btn.setStyleSheet(_default_btn)

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
        self._artist_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        self._subtitle_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._meta_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        _default_btn = btn_css(padding="5px 12px", radius=Metrics.BORDER_RADIUS_SM)
        self._back_btn.setStyleSheet(back_btn_css())
        self._sel_btn.setStyleSheet(_default_btn)
        self._desel_btn.setStyleSheet(_default_btn)

    def setHeroArt(self, pixmap, fallback_glyph: str = "music"):
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
            icon = glyph_icon(fallback_glyph, 48, Colors.TEXT_TERTIARY)
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
            "Location": getattr(t, "display_path", None) or t.path,
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

    def __init__(
        self,
        settings_service: SettingsService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._settings_service = settings_service
        self._photos: list[PCPhoto] = []
        self._selection: dict[str, bool] = {}
        self._visible_photos: list[PCPhoto] = []
        self._search_query = ""
        self._sort_key = "title"
        self._sort_reverse = False
        self._tile_pixmap_cache: dict[str, QPixmap] = {}
        self._tile_color_cache: dict[str, tuple[int, int, int] | None] = {}
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
        self._photo_grid = PooledPhotoGridView(
            checkable=True,
            settings_service=self._settings_service,
        )
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
        self._tile_color_cache.clear()
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

    def refresh_artwork_appearance(self) -> None:
        self._photo_grid.refresh_artwork_appearance()

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
    def _dominant_color_from_image(image: Image.Image) -> tuple[int, int, int] | None:
        try:
            from ..imgMaker import get_artwork_colors

            dominant_color, _album_colors = get_artwork_colors(image.convert("RGBA"))
            return dominant_color
        except Exception:
            try:
                pixel = cast(
                    tuple[int, int, int],
                    image.convert("RGB").resize((1, 1)).getpixel((0, 0)),
                )
                return int(pixel[0]), int(pixel[1]), int(pixel[2])
            except Exception:
                return None

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
    def _encode_pc_photo_tile(
        path: str,
        *,
        max_size: tuple[int, int],
    ) -> PCPhotoTilePayload | None:
        try:
            with Image.open(path) as img:
                image = ImageOps.exif_transpose(img)
                image.thumbnail(max_size)
                image = image.convert("RGBA")
                dominant_color = PCPhotoListView._dominant_color_from_image(image)
                return (
                    image.width,
                    image.height,
                    image.tobytes("raw", "RGBA"),
                    dominant_color,
                )
        except Exception:
            return None

    @staticmethod
    def _load_thumb_batch(paths: list[str]) -> dict[str, PCPhotoTilePayload | None]:
        return {
            path: PCPhotoListView._encode_pc_photo_tile(path, max_size=(132, 132))
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
                    dominant_color=self._tile_color_cache.get(photo.source_path),
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

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

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
        results: dict[str, PCPhotoTilePayload | None] | None,
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
            dominant_color: tuple[int, int, int] | None = None
            if data is not None:
                width, height, rgba, dominant_color = data
                pixmap = self._pixmap_from_rgba_bytes(width, height, rgba)
            self._tile_pixmap_cache[path] = pixmap
            self._tile_color_cache[path] = dominant_color
            self._photo_grid.setRecordPixmap(
                path,
                pixmap,
                dominant_color=dominant_color,
            )

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

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

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
    "Albums": "album",
    "Artists": "user",
    "Genres": "grid",
    "All Tracks": "music",
    "Playlists": "playlist",
    "Photos": "photo",
    "Podcasts": "broadcast",
    "Audiobooks": "book",
    "TV Shows": "monitor",
    "Movies": "film",
    "Music Videos": "video",
}

# Modes that use the grid → drill-in track-list pattern.
_GRID_MODES = {"Albums", "Artists", "Genres", "Playlists", "Podcasts", "Audiobooks",
               "TV Shows", "Music Videos"}

# Modes that go straight to the track list with no grouping.
_LIST_MODES = {"All Tracks", "Movies", "Photos"}

_PLAN_PLAYLIST_SECTION_KEYS = {
    "playlists_to_add",
    "playlists_to_edit",
    "playlists_to_remove",
}

_PLAN_PHOTO_SECTION_KEYS = {
    "photos_to_add",
    "photos_to_remove",
    "photos_to_update",
    "albums_to_add",
    "albums_to_remove",
    "album_membership_adds",
    "album_membership_removes",
}


class SelectiveSyncBrowser(QWidget):
    """Full-page widget for browsing PC media folders and selecting tracks."""
    selection_done = pyqtSignal(object, object)  # (folders, {"tracks": frozenset[str], "photos": tuple})
    cancelled = pyqtSignal()
    plan_selection_done = pyqtSignal(object)
    plan_selection_cancelled = pyqtSignal()

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
        self._folder_entries: list[dict[str, object]] = []
        self._folders: list[str] = []
        self._all_tracks: list = []
        self._playlist_discovery = None
        self._photo_library = PCPhotoLibrary(sync_root="")
        self._all_photos: list[PCPhoto] = []
        self._groups: dict[str, dict[str, dict]] = {}  # mode -> groups
        self._buckets: dict[str, list] = {}  # media_type -> tracks
        self._selected_tracks: dict[str, bool] = {}
        self._selected_photos: dict[str, bool] = {}
        self._selected_playlists: dict[str, bool] = {}
        self._plan_selection_mode = False
        self._plan_selection_sections: list[dict[str, object]] = []
        self._plan_selection_state: dict[str, set[int]] = {}
        self._plan_section_by_key: dict[str, dict[str, object]] = {}
        self._current_plan_section_key = ""
        self._plan_action_buttons: dict[str, QPushButton] = {}
        self._plan_track_key_to_selection: dict[str, tuple[str, int]] = {}
        self._plan_photo_key_to_selection: dict[str, tuple[str, int]] = {}
        self._plan_playlist_key_to_selection: dict[str, tuple[str, int]] = {}
        self._device_supports_video = True
        self._device_supports_photo = True
        self._device_supports_podcast = True
        self._current_mode = "Albums"
        self._current_group: str | None = None
        self._current_group_tracks: list = []
        self._scan_worker: _PCLibScanWorker | None = None
        self._scan_orphan_workers: list[_PCLibScanWorker] = []
        self._eta_tracker = ETATracker()

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

        self._title_label = QLabel("Selective Sync")
        self._title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        self._title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        hdr_lay.addWidget(self._title_label)

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
        self._sidebar.setObjectName("selectiveSyncSidebar")
        self._sidebar.setFixedWidth(Metrics.SIDEBAR_WIDTH)
        self._sidebar.setStyleSheet(sidebar_panel_css("selectiveSyncSidebar"))
        sb_lay = QVBoxLayout(self._sidebar)
        margin = Design.SIDEBAR_OUTER_MARGIN
        sb_lay.setContentsMargins(margin, margin, margin, margin)
        sb_lay.setSpacing(0)
        self._sidebar_layout = sb_lay

        # Build buttons for every known category; empty buckets are hidden
        # after the library scan completes.
        self._mode_buttons: dict[str, SidebarNavButton] = {}
        self._mode_separators: dict[str, QFrame] = {}

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
            "Playlists",
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
            btn = SidebarNavButton(cat, icon_name=icon_name)
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

        # Horizontal sync-action tabs used when this browser edits a review
        # plan. The left sidebar remains the normal category navigation.
        content_shell = QWidget()
        content_shell_lay = QVBoxLayout(content_shell)
        content_shell_lay.setContentsMargins(0, 0, 0, 0)
        content_shell_lay.setSpacing(0)

        self._action_tabs_frame = QFrame()
        self._action_tabs_frame.setVisible(False)
        self._action_tabs_frame.setStyleSheet(f"""
            QFrame {{
                background: {Colors.BG_DARK};
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        self._action_tabs_layout = QHBoxLayout(self._action_tabs_frame)
        self._action_tabs_layout.setContentsMargins(12, 8, 12, 8)
        self._action_tabs_layout.setSpacing(8)
        self._action_tabs_layout.addStretch()
        content_shell_lay.addWidget(self._action_tabs_frame)

        # --- Content area (stacked) ---
        self._content = QStackedWidget()

        # Page 0: loading progress (match Sync Review style)
        loading_page = QWidget()
        lp_lay = QVBoxLayout(loading_page)
        lp_lay.setContentsMargins(24, 0, 24, 0)
        lp_lay.setSpacing(0)

        lp_lay.addStretch(3)

        # Stage headline
        self._loading_label = QLabel("Scanning library...", loading_page)
        self._loading_label.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: {Metrics.FONT_HERO}pt;"
            f" font-weight: 500;"
        )
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp_lay.addWidget(self._loading_label)

        lp_lay.addSpacing(16)

        # Progress bar
        self._progress_bar = QProgressBar(loading_page)
        self._progress_bar.setFixedWidth(360)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(progress_bar_css(bg=Colors.BORDER_SUBTLE))
        lp_lay.addWidget(self._progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        lp_lay.addSpacing(10)

        # ETA / counter
        self._eta_label = QLabel("", loading_page)
        self._eta_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; font-size: {Metrics.FONT_MD}pt;"
        )
        self._eta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp_lay.addWidget(self._eta_label)

        lp_lay.addSpacing(16)

        # Detail — current file
        self._progress_detail = QLabel("", loading_page)
        self._progress_detail.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; font-size: {Metrics.FONT_LG}pt;"
        )
        self._progress_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_detail.setWordWrap(False)
        self._progress_detail.setMaximumWidth(560)
        self._progress_detail.setMaximumHeight(200)
        self._progress_detail.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        lp_lay.addWidget(self._progress_detail, alignment=Qt.AlignmentFlag.AlignCenter)

        lp_lay.addStretch(4)
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

        for cat in ("Albums", "Artists", "Genres", "Playlists",
                    "Podcasts", "Audiobooks", "TV Shows", "Music Videos"):
            grid = PCMusicBrowserGrid(
                device_sessions=self._device_sessions,
                settings_service=self._settings_service,
            )
            grid.item_selected.connect(self._on_grid_item_clicked)
            grid.item_context_requested.connect(self._on_grid_item_context_requested)
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
        self._photo_list = PCPhotoListView(settings_service=self._settings_service)
        self._photo_list.toggled.connect(self._on_photo_toggled)
        self._photo_list.select_all_requested.connect(self._on_select_all_photos)
        self._photo_list.deselect_all_requested.connect(self._on_deselect_all_photos)
        self._content.addWidget(self._photo_list)  # index 3

        content_shell_lay.addWidget(self._content, 1)
        body_lay.addWidget(content_shell, 1)
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
        self._done_btn.setStyleSheet(accent_btn_css())
        self._done_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._done_btn.clicked.connect(self._on_done)
        ft_lay.addWidget(self._done_btn)

        root.addWidget(self._footer)

    # ── Public API ───────────────────────────────────────────────────────

    def refresh_artwork_appearance(self) -> None:
        """Refresh visible grid artwork for the current global appearance."""
        for grid in self._grids.values():
            grid.refresh_artwork_appearance()
        if hasattr(self, "_photo_list"):
            self._photo_list.refresh_artwork_appearance()

    def load_sync_plan(self, plan: object, selection_state: object | None = None) -> None:
        """Render a sync plan as a categorized selection editor."""

        self._cleanup_scan_worker()
        self._plan_selection_mode = True
        self._title_label.setText("Edit Sync Selection")
        self._folder_label.setText("Choose a sync action, then browse it by category")
        self._done_btn.setText("Back to Review")
        self._back_btn.setToolTip("Back to Review")
        self._show_plan_mode_sidebar(True)
        self._plan_selection_sections = self._build_plan_selection_sections(plan)
        self._plan_section_by_key = {
            str(section["key"]): section
            for section in self._plan_selection_sections
        }
        self._plan_selection_state = self._normalize_plan_selection_state(
            selection_state,
            self._plan_selection_sections,
        )
        self._rebuild_plan_action_tabs()

        if self._plan_selection_sections:
            first_key = str(self._plan_selection_sections[0]["key"])
            self._show_plan_section(first_key)
        else:
            self._current_plan_section_key = ""
            self._clear_plan_content()
            self._content.setCurrentIndex(0)
            self._loading_label.setText("No selectable sync changes")
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(0)
            self._eta_label.setText("")
            self._progress_detail.setText("")
            self._count_label.setText("No selectable sync changes")
            self._done_btn.setEnabled(True)

    @staticmethod
    def _sync_item_size(item: object) -> int:
        estimated = getattr(item, "estimated_size", None)
        if estimated is not None:
            try:
                return int(estimated or 0)
            except (TypeError, ValueError):
                return 0
        track = getattr(item, "pc_track", None)
        if track is not None:
            try:
                return int(getattr(track, "size", 0) or 0)
            except (TypeError, ValueError):
                return 0
        ipod = getattr(item, "ipod_track", None)
        if isinstance(ipod, dict):
            try:
                return int(ipod.get("size", ipod.get("Size", 0)) or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    @staticmethod
    def _list_plan_items(items: object) -> list[object]:
        if items is None or isinstance(items, (str, bytes, bytearray)):
            return []
        if isinstance(items, Iterable):
            return list(items)
        return []

    def _build_plan_selection_sections(self, plan: object) -> list[dict[str, object]]:
        sections: list[dict[str, object]] = []

        def add_section(
            key: str,
            label: str,
            icon: str,
            accent: str,
            items: object,
            *,
            bucket: str,
            checked_by_default: bool = True,
        ) -> None:
            item_list = self._list_plan_items(items)
            if not item_list:
                return
            sections.append({
                "key": key,
                "label": label,
                "icon": icon,
                "accent": accent,
                "items": item_list,
                "bucket": bucket,
                "checked_by_default": checked_by_default,
            })

        add_section("to_add", "Add Items", "plus", Colors.SUCCESS, getattr(plan, "to_add", ()), bucket="sync_items")
        add_section(
            "to_remove",
            "Remove Items",
            "minus",
            Colors.DANGER,
            getattr(plan, "to_remove", ()),
            bucket="sync_items",
            checked_by_default=bool(getattr(plan, "removals_pre_checked", False)),
        )
        add_section("to_update_file", "Re-sync Files", "refresh", Colors.SYNC_CYAN, getattr(plan, "to_update_file", ()), bucket="sync_items")
        add_section("to_update_metadata", "Update Details", "edit", Colors.SYNC_PURPLE, getattr(plan, "to_update_metadata", ()), bucket="sync_items")
        add_section("to_update_artwork", "Update Artwork", "download", Colors.SYNC_MAGENTA, getattr(plan, "to_update_artwork", ()), bucket="sync_items")
        add_section("to_sync_playcount", "Play Counts", "music", Colors.INFO, getattr(plan, "to_sync_playcount", ()), bucket="sync_items")
        add_section("to_sync_rating", "Ratings", "star", Colors.WARNING, getattr(plan, "to_sync_rating", ()), bucket="sync_items")

        add_section("playlists_to_add", "Add Playlists", "playlist", Colors.INFO, getattr(plan, "playlists_to_add", ()), bucket="playlists_to_add")
        add_section("playlists_to_edit", "Update Playlists", "playlist", Colors.INFO, getattr(plan, "playlists_to_edit", ()), bucket="playlists_to_edit")
        add_section("playlists_to_remove", "Remove Playlists", "playlist", Colors.DANGER, getattr(plan, "playlists_to_remove", ()), bucket="playlists_to_remove")

        photo_plan = getattr(plan, "photo_plan", None)
        if photo_plan is not None:
            add_section("photos_to_add", "Add Photos", "photo", Colors.SUCCESS, getattr(photo_plan, "photos_to_add", ()), bucket="photos_to_add")
            add_section("photos_to_remove", "Remove Photos", "photo", Colors.DANGER, getattr(photo_plan, "photos_to_remove", ()), bucket="photos_to_remove", checked_by_default=False)
            add_section("photos_to_update", "Update Photos", "photo", Colors.SYNC_PURPLE, getattr(photo_plan, "photos_to_update", ()), bucket="photos_to_update")
            add_section("albums_to_add", "Create Photo Albums", "album", Colors.INFO, getattr(photo_plan, "albums_to_add", ()), bucket="albums_to_add")
            add_section("albums_to_remove", "Remove Photo Albums", "album", Colors.DANGER, getattr(photo_plan, "albums_to_remove", ()), bucket="albums_to_remove", checked_by_default=False)
            add_section("album_membership_adds", "Add to Photo Albums", "album", Colors.INFO, getattr(photo_plan, "album_membership_adds", ()), bucket="album_membership_adds")
            add_section("album_membership_removes", "Remove from Photo Albums", "album", Colors.DANGER, getattr(photo_plan, "album_membership_removes", ()), bucket="album_membership_removes", checked_by_default=False)

        return sections

    @staticmethod
    def _normalize_plan_selection_state(
        selection_state: object | None,
        sections: list[dict[str, object]],
    ) -> dict[str, set[int]]:
        known_buckets = {
            "sync_items",
            "playlists_to_add",
            "playlists_to_edit",
            "playlists_to_remove",
            "photos_to_add",
            "photos_to_remove",
            "photos_to_update",
            "albums_to_add",
            "albums_to_remove",
            "album_membership_adds",
            "album_membership_removes",
        }
        state: dict[str, set[int]] = {bucket: set() for bucket in known_buckets}
        if isinstance(selection_state, dict):
            for key, values in selection_state.items():
                try:
                    state[str(key)] = {int(value) for value in values}
                except TypeError:
                    state[str(key)] = set()
            return state

        for section in sections:
            if not bool(section.get("checked_by_default", True)):
                continue
            bucket = str(section["bucket"])
            state.setdefault(bucket, set()).update(id(item) for item in section["items"])  # type: ignore[index]
        return state

    def _show_plan_mode_sidebar(self, enabled: bool) -> None:
        frame = self.__dict__.get("_action_tabs_frame")
        if isinstance(frame, QFrame):
            frame.setVisible(enabled and bool(self._plan_selection_sections))
        if not enabled:
            for btn in getattr(self, "_mode_buttons", {}).values():
                btn.setVisible(True)
            for sep in getattr(self, "_mode_separators", {}).values():
                sep.setVisible(True)

    def _is_plan_selection_mode(self) -> bool:
        return bool(self.__dict__.get("_plan_selection_mode", False))

    def _clear_plan_mode_buttons(self) -> None:
        self._clear_plan_action_tabs()

    def _clear_plan_action_tabs(self) -> None:
        layout = self.__dict__.get("_action_tabs_layout")
        if not isinstance(layout, QHBoxLayout):
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        layout.addStretch()
        self._plan_action_buttons.clear()

    def _rebuild_plan_action_tabs(self) -> None:
        self._clear_plan_action_tabs()
        layout = self.__dict__.get("_action_tabs_layout")
        if not isinstance(layout, QHBoxLayout):
            return
        for section in self._plan_selection_sections:
            key = str(section["key"])
            btn = QPushButton(self._plan_action_tab_text(section))
            btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(self._plan_action_tab_css(False, str(section["accent"])))
            icon = glyph_icon(str(section["icon"]), 18, Colors.TEXT_SECONDARY)
            if icon:
                btn.setIcon(icon)
                btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda checked=False, section_key=key: self._show_plan_section(section_key))
            layout.insertWidget(max(0, layout.count() - 1), btn)
            self._plan_action_buttons[key] = btn
        self._show_plan_mode_sidebar(True)

    def _plan_action_tab_text(self, section: dict[str, object]) -> str:
        items = self._list_plan_items(section.get("items"))
        return f"{section['label']} ({len(items)})"

    @staticmethod
    def _plan_action_tab_css(selected: bool, accent: str) -> str:
        if selected:
            return btn_css(
                bg=Colors.ACCENT_MUTED,
                bg_hover=Colors.ACCENT_DIM,
                bg_press=Colors.ACCENT_PRESS,
                fg=accent,
                border=f"1px solid {accent}",
                radius=Metrics.BORDER_RADIUS_SM,
                padding="7px 13px",
                extra="font-weight: 700;",
            )
        return btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE,
            fg=Colors.TEXT_SECONDARY,
            border=f"1px solid {Colors.BORDER_SUBTLE}",
            radius=Metrics.BORDER_RADIUS_SM,
            padding="7px 13px",
            extra="font-weight: 600;",
        )

    def _show_plan_section(self, key: str) -> None:
        section = self._plan_section_by_key.get(key)
        if section is None:
            return
        self._current_plan_section_key = key
        for section_key, btn in self._plan_action_buttons.items():
            source = self._plan_section_by_key[section_key]
            selected = section_key == key
            accent = str(source["accent"])
            btn.setStyleSheet(self._plan_action_tab_css(selected, accent))
            icon = glyph_icon(
                str(source["icon"]),
                18,
                accent if selected else Colors.TEXT_SECONDARY,
            )
            if icon:
                btn.setIcon(icon)
        self._load_plan_section_content(section)
        self._update_plan_footer()

    def _clear_plan_content(self) -> None:
        self._all_tracks = []
        self._all_photos = []
        self._playlist_discovery = None
        self._photo_library = PCPhotoLibrary(sync_root="")
        self._groups.clear()
        self._buckets.clear()
        self._selected_tracks.clear()
        self._selected_photos.clear()
        self._selected_playlists.clear()
        self._plan_track_key_to_selection.clear()
        self._plan_photo_key_to_selection.clear()
        self._plan_playlist_key_to_selection.clear()
        self._current_group = None
        self._current_group_tracks = []
        grid_loaded = self.__dict__.get("_grid_loaded")
        if isinstance(grid_loaded, set):
            grid_loaded.clear()
        for grid in getattr(self, "_grids", {}).values():
            grid._art_cache.clear()
            grid._art_pending.clear()
            grid._art_seen.clear()
            grid.clearItemSelection()

    def _load_plan_section_content(self, section: dict[str, object]) -> None:
        self._clear_plan_content()
        section_key = str(section["key"])
        bucket = str(section["bucket"])
        label = str(section["label"])
        selected_ids = self._plan_selection_state.setdefault(bucket, set())
        items = self._list_plan_items(section.get("items"))

        if section_key in _PLAN_PLAYLIST_SECTION_KEYS:
            playlists: list[SimpleNamespace] = []
            for index, item in enumerate(items):
                item_id = id(item)
                track = self._plan_playlist_to_track(item, section_key, index, label)
                self._all_tracks.append(track)
                self._selected_tracks[track.path] = item_id in selected_ids
                self._plan_track_key_to_selection[track.path] = (bucket, item_id)

                playlist = self._plan_playlist_to_discovery(item, section_key, index, track.path)
                playlists.append(playlist)
                self._selected_playlists[playlist.source_path] = item_id in selected_ids
                self._plan_playlist_key_to_selection[playlist.source_path] = (bucket, item_id)
            self._playlist_discovery = SimpleNamespace(playlists=tuple(playlists))

        elif section_key in _PLAN_PHOTO_SECTION_KEYS:
            photos: list[PCPhoto] = []
            for index, item in enumerate(items):
                item_id = id(item)
                photo = self._plan_item_to_photo(item, section_key, index, label)
                photos.append(photo)
                self._selected_photos[photo.source_path] = item_id in selected_ids
                self._plan_photo_key_to_selection[photo.source_path] = (bucket, item_id)
            self._all_photos = photos
            self._photo_library = PCPhotoLibrary(
                sync_root="",
                photos={photo.source_path: photo for photo in photos},
                albums={name for photo in photos for name in photo.album_names},
            )

        else:
            for index, item in enumerate(items):
                item_id = id(item)
                track = self._plan_sync_item_to_track(item, section_key, index, label)
                self._all_tracks.append(track)
                self._selected_tracks[track.path] = item_id in selected_ids
                self._plan_track_key_to_selection[track.path] = (bucket, item_id)

        self._build_groups()
        self._apply_sidebar_visibility()
        for mode in self._preferred_plan_modes(section_key):
            if self._mode_has_content(mode):
                self._show_mode(mode)
                return

        self._content.setCurrentIndex(0)
        self._loading_label.setText(f"No {label.lower()} to show")
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        self._eta_label.setText("")
        self._progress_detail.setText("")

    @staticmethod
    def _preferred_plan_modes(section_key: str) -> tuple[str, ...]:
        if section_key in _PLAN_PLAYLIST_SECTION_KEYS:
            return (
                "Playlists", "All Tracks", "Albums", "Artists", "Genres",
                "Podcasts", "Audiobooks", "TV Shows", "Movies", "Music Videos", "Photos",
            )
        if section_key in _PLAN_PHOTO_SECTION_KEYS:
            return ("Photos",)
        return (
            "Albums", "Artists", "Genres", "All Tracks", "Playlists", "Photos",
            "Podcasts", "Audiobooks", "TV Shows", "Movies", "Music Videos",
        )

    @staticmethod
    def _coerce_plan_int(value: object, default: int = 0) -> int:
        if value in (None, ""):
            return default
        try:
            if isinstance(value, int | float | str | bytes | bytearray):
                return int(value)
        except (TypeError, ValueError):
            pass
        return default

    @staticmethod
    def _set_plan_display_path(track: PCTrack, display_path: str) -> None:
        track.__dict__["display_path"] = display_path

    @staticmethod
    def _dict_first(data: dict, *keys: str, default: object = "") -> object:
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return value
        return default

    def _plan_sync_item_to_track(
        self,
        item: object,
        section_key: str,
        index: int,
        section_label: str,
    ) -> PCTrack:
        track = getattr(item, "pc_track", None)
        if isinstance(track, PCTrack):
            return replace(track)
        rebuild_tracks = self._list_plan_items(getattr(item, "aggregate_rebuild_pc_tracks", ()))
        if rebuild_tracks and isinstance(rebuild_tracks[0], PCTrack):
            clone = replace(rebuild_tracks[0])
            clone.path = self._plan_fake_path("track", section_key, index, item)
            clone.relative_path = str(getattr(clone, "relative_path", "") or clone.filename)
            clone.title = str(getattr(item, "description", "") or clone.album or clone.title)
            self._set_plan_display_path(
                clone,
                str(getattr(item, "description", "") or clone.relative_path),
            )
            return clone
        ipod = getattr(item, "ipod_track", None)
        return self._plan_synthetic_track_from_ipod(
            ipod if isinstance(ipod, dict) else {},
            item,
            section_key,
            index,
            section_label,
        )

    def _plan_synthetic_track_from_ipod(
        self,
        ipod: dict,
        item: object,
        section_key: str,
        index: int,
        section_label: str,
    ) -> PCTrack:
        location = str(self._dict_first(ipod, "Location", "location"))
        filename = os.path.basename(location.replace(":", "/")) or f"{section_key}-{index + 1}"
        extension = os.path.splitext(filename)[1]
        media_type = self._coerce_plan_int(self._dict_first(ipod, "media_type", "Media Type", default=1), 1)
        is_podcast = bool(media_type & 0x04)
        is_audiobook = bool(media_type & 0x08)
        is_video = bool(media_type & (0x02 | 0x20 | 0x40))
        video_kind = ""
        if media_type & 0x40:
            video_kind = "tv_show"
        elif media_type & 0x20:
            video_kind = "music_video"
        elif media_type & 0x02:
            video_kind = "movie"

        description = str(getattr(item, "description", "") or "")
        title = str(self._dict_first(ipod, "Title", "title", default=description or filename or "Track"))
        artist = str(self._dict_first(ipod, "Artist", "artist", default="Unknown Artist"))
        album = str(self._dict_first(ipod, "Album", "album", default=section_label))
        track = PCTrack(
            path=self._plan_fake_path("track", section_key, index, item),
            relative_path=location or description or filename,
            filename=filename,
            extension=extension,
            mtime=0,
            size=self._sync_item_size(item),
            title=title,
            artist=artist,
            album=album,
            album_artist=str(self._dict_first(ipod, "Album Artist", "album_artist", default=artist)) or None,
            genre=str(self._dict_first(ipod, "Genre", "genre", default="")) or None,
            year=self._coerce_plan_int(self._dict_first(ipod, "year", "Year", default=0)) or None,
            track_number=self._coerce_plan_int(self._dict_first(ipod, "track_number", "Track Number", default=0)) or None,
            track_total=self._coerce_plan_int(self._dict_first(ipod, "total_tracks", "Total Tracks", default=0)) or None,
            disc_number=self._coerce_plan_int(self._dict_first(ipod, "disc_number", "Disc Number", default=0)) or None,
            disc_total=self._coerce_plan_int(self._dict_first(ipod, "total_discs", "Total Discs", default=0)) or None,
            duration_ms=self._coerce_plan_int(self._dict_first(ipod, "length", "duration_ms", "Total Time", default=0)),
            bitrate=self._coerce_plan_int(self._dict_first(ipod, "bitrate", "Bit Rate", default=0)) or None,
            sample_rate=self._coerce_plan_int(self._dict_first(ipod, "sample_rate_1", "sample_rate", default=0)) or None,
            rating=self._coerce_plan_int(self._dict_first(ipod, "rating", "Rating", default=0)) or None,
            is_video=is_video,
            video_kind=video_kind,
            show_name=str(self._dict_first(ipod, "show_name", "Show", default="")) or None,
            season_number=self._coerce_plan_int(self._dict_first(ipod, "season_number", "Season", default=0)) or None,
            episode_number=self._coerce_plan_int(self._dict_first(ipod, "episode_number", "Episode", default=0)) or None,
            is_podcast=is_podcast,
            is_audiobook=is_audiobook,
        )
        artwork_id_ref = self._coerce_plan_int(
            self._dict_first(
                ipod,
                "artwork_id_ref",
                "mhii_link",
                "mhiiLink",
                default=0,
            )
        )
        if artwork_id_ref:
            track.__dict__["artwork_id_ref"] = artwork_id_ref
        self._set_plan_display_path(track, location or description)
        return track

    def _plan_playlist_to_track(
        self,
        item: object,
        section_key: str,
        index: int,
        section_label: str,
    ) -> PCTrack:
        title = self._plan_playlist_title(item)
        source = self._plan_playlist_source(item)
        track = PCTrack(
            path=self._plan_fake_path("playlist", section_key, index, item),
            relative_path=source or title,
            filename=title,
            extension=".playlist",
            mtime=0,
            size=0,
            title=title,
            artist=section_label,
            album="Playlists",
            album_artist=section_label,
            genre="Playlist",
            year=None,
            track_number=index + 1,
            track_total=None,
            disc_number=None,
            disc_total=None,
            duration_ms=0,
            bitrate=None,
            sample_rate=None,
            rating=None,
        )
        self._set_plan_display_path(track, source or title)
        return track

    def _plan_playlist_to_discovery(
        self,
        item: object,
        section_key: str,
        index: int,
        track_path: str,
    ) -> SimpleNamespace:
        source = self._plan_playlist_source(item) or self._plan_fake_path("playlist-source", section_key, index, item)
        total_entries = 1
        skipped_entries = 0
        if isinstance(item, dict):
            items = item.get("items") or item.get("Playlist Items") or []
            if isinstance(items, list):
                total_entries = len(items) or 1
            total_entries = self._coerce_plan_int(
                item.get("_sync_playlist_total_entries", item.get("track_count", total_entries)),
                total_entries,
            )
            skipped_entries = self._coerce_plan_int(item.get("_sync_playlist_skipped_count", 0))
        return SimpleNamespace(
            title=self._plan_playlist_title(item),
            source_path=source,
            items=({"source_path": track_path},),
            total_entries=total_entries,
            skipped_entries=skipped_entries,
        )

    @staticmethod
    def _plan_playlist_title(item: object) -> str:
        if isinstance(item, dict):
            return str(item.get("Title") or item.get("name") or "Untitled playlist")
        return str(getattr(item, "title", "") or getattr(item, "name", "") or "Untitled playlist")

    @staticmethod
    def _plan_playlist_source(item: object) -> str:
        if isinstance(item, dict):
            return str(
                item.get("_sync_playlist_path")
                or item.get("_sync_playlist_source_path")
                or item.get("source_path")
                or ""
            )
        return str(getattr(item, "source_path", "") or "")

    def _plan_item_to_photo(
        self,
        item: object,
        section_key: str,
        index: int,
        section_label: str,
    ) -> PCPhoto:
        display_name = str(
            getattr(item, "display_name", "")
            or getattr(item, "album_name", "")
            or f"{section_label} {index + 1}"
        )
        source_path = str(getattr(item, "source_path", "") or "")
        album_names_obj = getattr(item, "album_names", set()) or set()
        if isinstance(album_names_obj, str):
            album_names = {album_names_obj}
        else:
            try:
                album_names = {str(name) for name in album_names_obj if name}
            except TypeError:
                album_names = set()
        album_name = str(getattr(item, "album_name", "") or "")
        if album_name:
            album_names.add(album_name)
        if not album_names and section_key.startswith("albums_"):
            album_names.add(display_name)
        size = self._coerce_plan_int(
            getattr(item, "estimated_size", 0) or getattr(item, "size", 0) or 0
        )
        return PCPhoto(
            visual_hash=str(
                getattr(item, "visual_hash", "")
                or self._plan_fake_path("photo-hash", section_key, index, item)
            ),
            display_name=display_name,
            source_path=source_path or self._plan_fake_path("photo", section_key, index, item),
            size=size,
            album_names=album_names,
        )

    @staticmethod
    def _plan_fake_path(kind: str, section_key: str, index: int, item: object) -> str:
        return f"iopenpod://sync-plan/{kind}/{section_key}/{index}/{id(item)}"

    def _set_plan_selection_item(self, bucket: str, item_id: int, checked: bool) -> None:
        selected_ids = self._plan_selection_state.setdefault(bucket, set())
        if checked:
            selected_ids.add(item_id)
        else:
            selected_ids.discard(item_id)

    def _set_plan_track_selection(self, path: str, checked: bool) -> bool:
        changed = self._selected_tracks.get(path, True) != checked
        self._selected_tracks[path] = checked
        target = self._plan_track_key_to_selection.get(path)
        if target is not None:
            bucket, item_id = target
            self._set_plan_selection_item(bucket, item_id, checked)
        return changed

    def _set_plan_photo_selection(self, path: str, checked: bool) -> bool:
        changed = self._selected_photos.get(path, True) != checked
        self._selected_photos[path] = checked
        target = self._plan_photo_key_to_selection.get(path)
        if target is not None:
            bucket, item_id = target
            self._set_plan_selection_item(bucket, item_id, checked)
        return changed

    def _set_plan_playlist_selection(self, path: str, checked: bool) -> bool:
        changed = self._selected_playlists.get(path, True) != checked
        self._selected_playlists[path] = checked
        target = self._plan_playlist_key_to_selection.get(path)
        if target is not None:
            bucket, item_id = target
            self._set_plan_selection_item(bucket, item_id, checked)
        return changed

    def _set_current_plan_action_checked(self, checked: bool) -> None:
        section = self._plan_section_by_key.get(self._current_plan_section_key)
        if section is None:
            return
        bucket = str(section["bucket"])
        item_ids = {id(item) for item in self._list_plan_items(section.get("items"))}
        selected_ids = self._plan_selection_state.setdefault(bucket, set())
        if checked:
            selected_ids.update(item_ids)
        else:
            selected_ids.difference_update(item_ids)

        for path in list(self._selected_tracks):
            self._selected_tracks[path] = checked
        for path in list(self._selected_photos):
            self._selected_photos[path] = checked
        for path in list(self._selected_playlists):
            self._selected_playlists[path] = checked
        if self._content.currentIndex() == 2:
            self._track_list.setAllChecked(checked)
        if self._content.currentIndex() == 3:
            self._photo_list.setAllChecked(checked)
        self._update_plan_footer()

    def _update_plan_footer(self) -> None:
        total = 0
        selected = 0
        current_total = 0
        current_selected = 0
        for section in self._plan_selection_sections:
            bucket = str(section["bucket"])
            ids = self._plan_selection_state.setdefault(bucket, set())
            items = self._list_plan_items(section.get("items"))
            section_total = len(items)
            section_selected = sum(1 for item in items if id(item) in ids)
            total += section_total
            selected += section_selected
            if str(section["key"]) == self._current_plan_section_key:
                current_total = section_total
                current_selected = section_selected
        if total:
            current = (
                f"{current_selected} of {current_total} in this tab"
                if current_total
                else "No changes in this tab"
            )
            self._count_label.setText(f"{selected} of {total} changes selected · {current}")
        else:
            self._count_label.setText("No selectable sync changes")
        self._done_btn.setEnabled(True)

    def _cleanup_scan_worker(self):
        """Disconnect and clean up the current scan worker, if any."""
        worker = self._scan_worker
        if worker is None:
            return
        try:
            worker.finished.disconnect()
            worker.progress.disconnect()
            worker.error.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._scan_worker = None
        worker.cancel()
        if worker.isRunning():
            self._retain_scan_worker(worker)
        else:
            self._reap_scan_worker(worker)

    def _retain_scan_worker(self, worker: _PCLibScanWorker) -> None:
        if worker in self._scan_orphan_workers:
            return
        self._scan_orphan_workers.append(worker)
        try:
            QThread.finished.__get__(worker, type(worker)).connect(
                lambda w=worker: self._reap_scan_worker(w)
            )
        except Exception:
            pass

    def _reap_scan_worker(self, worker: _PCLibScanWorker) -> None:
        if self._scan_worker is worker:
            self._scan_worker = None
        try:
            self._scan_orphan_workers.remove(worker)
        except ValueError:
            pass
        try:
            worker.deleteLater()
        except RuntimeError:
            pass

    def load(self, folder: object):
        """Start scanning one or more folders and prepare the browser."""
        self._plan_selection_mode = False
        self._title_label.setText("Selective Sync")
        self._done_btn.setText("Done Selecting")
        self._back_btn.setToolTip("Back")
        self._show_plan_mode_sidebar(False)
        self._clear_plan_mode_buttons()
        self._plan_selection_sections = []
        self._plan_selection_state = {}
        self._plan_section_by_key = {}
        self._current_plan_section_key = ""
        self._plan_track_key_to_selection = {}
        self._plan_photo_key_to_selection = {}
        self._plan_playlist_key_to_selection = {}
        self._folder_entries = _normalize_folder_entries(folder)
        self._folders = media_folder_paths(self._folder_entries)
        self._folder = self._folders[0] if self._folders else ""
        caps = self._device_sessions.current_session().capabilities
        self._device_supports_video = (
            bool(caps.supports_video) if caps is not None else True
        )
        self._device_supports_photo = (
            bool(caps.supports_photo) if caps is not None else True
        )
        self._device_supports_podcast = (
            bool(caps.supports_podcast) if caps is not None else True
        )
        self._all_tracks = []
        self._playlist_discovery = None
        self._photo_library = PCPhotoLibrary(sync_root=os.pathsep.join(self._folders))
        self._all_photos = []
        self._groups.clear()
        self._buckets.clear()
        self._selected_tracks.clear()
        self._selected_photos.clear()
        self._selected_playlists.clear()
        self._current_mode = "Albums"
        self._grid_loaded.clear()
        self._current_group = None
        self._current_group_tracks = []
        for grid in self._grids.values():
            grid._art_cache.clear()
            grid._art_pending.clear()
            grid._art_seen.clear()
            grid.clearItemSelection()

        self._folder_label.setText(_folder_label(self._folders))

        self._content.setCurrentIndex(0)  # loading
        self._loading_label.setText("Scanning PC library")
        self._progress_bar.setRange(0, 0)
        self._eta_label.setText("")
        self._progress_detail.setText("")
        self._eta_tracker.start()
        self._update_footer()
        self._highlight_mode("Albums")

        # Stop and clean up any prior worker
        self._cleanup_scan_worker()

        settings = self._settings_service.get_effective_settings()
        try:
            scan_workers = settings.sync_workers
        except Exception:
            scan_workers = 0
        scan_workers = scan_workers or None

        self._scan_worker = _PCLibScanWorker(
            self._folder_entries,
            include_video=self._device_supports_video,
            include_photo=self._device_supports_photo,
            max_workers=scan_workers,
        )
        worker = self._scan_worker
        worker.finished.connect(
            lambda payload, w=worker: self._on_scan_complete(payload, w)
        )
        worker.progress.connect(
            lambda stage, current, total, filename, w=worker: self._on_scan_progress(
                stage,
                current,
                total,
                filename,
                w,
            )
        )
        worker.error.connect(lambda msg, w=worker: self._on_scan_error(msg, w))
        worker.start()

    # ── Scan callbacks ───────────────────────────────────────────────────

    def _on_scan_progress(
        self,
        stage: str,
        current: int,
        total: int,
        filename: str,
        worker: _PCLibScanWorker | None = None,
    ) -> None:
        if worker is not None and self._scan_worker is not worker:
            return
        stage_label = {
            "scan_pc": "Scanning PC library",
            "scan_playlists": "Scanning playlist files",
            "scan_photos": "Scanning photos",
        }.get(stage, stage.replace("_", " ").title())

        self._loading_label.setText(stage_label)
        self._progress_detail.setText(filename or "")
        self._progress_detail.setTextFormat(Qt.TextFormat.PlainText)
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
            self._eta_tracker.update(stage, current, total)
            self._eta_label.setText(
                self._eta_tracker.format_stage_progress(stage, current, total)
            )
        else:
            self._progress_bar.setRange(0, 0)
            self._eta_label.setText("")

    def _on_scan_complete(
        self,
        tracks: list,
        worker: _PCLibScanWorker | None = None,
    ):
        if worker is not None and self._scan_worker is not worker:
            return
        worker = self._scan_worker
        self._scan_worker = None
        if worker is not None:
            worker.deleteLater()
        if isinstance(tracks, dict):
            self._all_tracks = list(tracks.get("tracks", []))
            self._photo_library = tracks.get("photos") or PCPhotoLibrary(sync_root=os.pathsep.join(self._folders))
            self._playlist_discovery = tracks.get("playlists")
        else:
            self._all_tracks = list(tracks)
            self._playlist_discovery = None
            self._photo_library = PCPhotoLibrary(sync_root=os.pathsep.join(self._folders))
        if not self._device_supports_podcast:
            self._all_tracks = [
                track for track in self._all_tracks
                if not getattr(track, "is_podcast", False)
            ]
        if not self._device_supports_video:
            self._all_tracks = [
                track for track in self._all_tracks
                if not getattr(track, "is_video", False)
            ]
        self._all_photos = sorted(
            self._photo_library.photos.values(),
            key=lambda photo: (photo.display_name or photo.source_path).lower(),
        ) if self._device_supports_photo else []
        self._selected_tracks = {t.path: True for t in self._all_tracks}
        self._selected_photos = {photo.source_path: True for photo in self._all_photos}
        playlists = (
            getattr(self._playlist_discovery, "playlists", ())
            if self._playlist_discovery is not None
            else ()
        )
        self._selected_playlists = {
            str(getattr(playlist, "source_path", "") or ""): True
            for playlist in playlists
            if getattr(playlist, "source_path", "")
        }
        self._build_groups()
        self._apply_sidebar_visibility()
        # Pick the first mode that actually has content.
        for mode in ("Albums", "Artists", "Genres", "All Tracks", "Playlists", "Photos",
                     "Podcasts", "Audiobooks",
                     "TV Shows", "Movies", "Music Videos"):
            if self._mode_has_content(mode):
                self._show_mode(mode)
                return
        # Nothing to show — leave loading label.
        self._loading_label.setText("No music or photos found in these folders.")

    def _on_scan_error(
        self,
        msg: str,
        worker: _PCLibScanWorker | None = None,
    ):
        if worker is not None and self._scan_worker is not worker:
            return
        worker = self._scan_worker
        self._scan_worker = None
        if worker is not None:
            worker.deleteLater()
        self._loading_label.setText(f"Scan failed: {msg}")

    # ── Grouping ─────────────────────────────────────────────────────────

    @staticmethod
    def _art_candidates(track_list: list) -> list[str]:
        """Build a list of candidate file paths for artwork extraction.

        Prioritises files that already have an art_hash (embedded art is
        known to exist) and includes a few fallbacks so the background
        worker can also check folder images.
        """
        valid_paths = [
            t.path for t in track_list
            if getattr(t, "path", "") and not str(t.path).startswith("iopenpod://")
        ]
        with_art = [t.path for t in track_list if getattr(t, "art_hash", None) and t.path in valid_paths]
        without = [path for path in valid_paths if path not in with_art]
        # Return art-hash files first, then up to 3 fallbacks.
        return with_art[:5] + without[:3]

    @staticmethod
    def _track_artwork_id(track: object) -> int | None:
        for key in ("artwork_id_ref", "mhii_link", "mhiiLink"):
            try:
                value = getattr(track, key)
            except AttributeError:
                continue
            if value in (None, ""):
                continue
            try:
                artwork_id = int(value)
            except (TypeError, ValueError):
                continue
            if artwork_id:
                return artwork_id
        return None

    @classmethod
    def _artwork_id_for_tracks(cls, track_list: list) -> int | None:
        for track in track_list:
            artwork_id = cls._track_artwork_id(track)
            if artwork_id is not None:
                return artwork_id
        return None

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

        from iopenpod.sync.unknown_metadata import apply_unknown_placeholders
        apply_unknown_placeholders(buckets["music"])
        apply_unknown_placeholders(buckets["music_video"])

        self._groups["Albums"] = self._build_music_albums(buckets["music"])
        self._groups["Artists"] = self._build_music_artists(buckets["music"])
        self._groups["Genres"] = self._build_music_genres(buckets["music"])
        self._groups["Playlists"] = self._build_playlist_groups()
        self._groups["Podcasts"] = self._build_podcast_shows(buckets["podcast"])
        self._groups["Audiobooks"] = self._build_audiobooks(buckets["audiobook"])
        self._groups["TV Shows"] = self._build_tv_shows(buckets["tv_show"])
        self._groups["Music Videos"] = self._build_music_videos(buckets["music_video"])
        # Movies and All Tracks are list-mode and don't need pre-built groups.

    # ── Per-type group builders ──────────────────────────────────────────

    def _build_music_albums(self, tracks: list) -> dict[str, dict]:
        album_groups = group_tracks_by_album_identity(tracks, album_identity_from_track)

        _by_name: dict[str, list[str]] = defaultdict(list)
        for album_group in album_groups:
            album = album_group.identity.album or "Unknown Album"
            artist = (
                album_group.identity.album_artist
                or album_group.identity.artist
                or "Unknown Artist"
            )
            _by_name[album].append(artist)

        out: dict[str, dict] = {}
        for album_group in album_groups:
            group = album_group.tracks
            album = album_group.identity.album or "Unknown Album"
            artist = (
                album_group.identity.album_artist
                or album_group.identity.artist
                or "Unknown Artist"
            )
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
                "artwork_id_ref": self._artwork_id_for_tracks(group),
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
                "artwork_id_ref": self._artwork_id_for_tracks(group),
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
                "artwork_id_ref": self._artwork_id_for_tracks(group),
                "category": "Genres",
                "filter_key": "genre",
                "filter_value": genre,
                "artist_count": artist_count,
                "track_count": len(group),
            }
        return out

    def _build_playlist_groups(self) -> dict[str, dict]:
        discovery = self._playlist_discovery
        playlists = getattr(discovery, "playlists", ()) if discovery is not None else ()
        if not playlists:
            return {}

        try:
            from iopenpod.sync.sync_playlist_files import normalize_sync_playlist_path
        except Exception:
            def normalize_sync_playlist_path(path):
                return os.path.normcase(str(path))

        track_by_source = {
            normalize_sync_playlist_path(track.path): track
            for track in self._all_tracks
        }
        title_counts: dict[str, int] = defaultdict(int)
        for playlist in playlists:
            title_counts[getattr(playlist, "title", "") or "Imported Playlist"] += 1

        out: dict[str, dict] = {}
        for playlist in playlists:
            title = getattr(playlist, "title", "") or "Imported Playlist"
            source_path = getattr(playlist, "source_path", "")
            display_title = title
            if title_counts[title] > 1 and source_path:
                parent = os.path.basename(os.path.dirname(source_path)) or source_path
                display_title = f"{title} ({parent})"

            group_tracks = []
            for item in getattr(playlist, "items", ()):
                raw_path = item.get("source_path") if isinstance(item, dict) else ""
                track = track_by_source.get(normalize_sync_playlist_path(raw_path or ""))
                if track is not None:
                    group_tracks.append(track)

            skipped = int(getattr(playlist, "skipped_entries", 0) or 0)
            skipped += max(0, len(getattr(playlist, "items", ())) - len(group_tracks))
            total_entries = int(getattr(playlist, "total_entries", 0) or 0)
            sub_parts = [
                f"{len(group_tracks)} track{'s' if len(group_tracks) != 1 else ''}",
            ]
            if skipped:
                sub_parts.append(f"{skipped} skipped")
            if source_path:
                sub_parts.append(os.path.basename(source_path))

            out[display_title] = {
                "tracks": group_tracks,
                "subtitle": " \xb7 ".join(sub_parts),
                "art_paths": self._art_candidates(group_tracks),
                "artwork_id_ref": self._artwork_id_for_tracks(group_tracks),
                "category": "Playlists",
                "filter_key": "playlist",
                "filter_value": display_title,
                "track_count": len(group_tracks),
                "skipped_count": skipped,
                "total_entries": total_entries,
                "source_path": source_path,
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
                "artwork_id_ref": self._artwork_id_for_tracks(eps),
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
                "artwork_id_ref": self._artwork_id_for_tracks(parts),
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
                "artwork_id_ref": self._artwork_id_for_tracks(eps),
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
                "artwork_id_ref": self._artwork_id_for_tracks(vids),
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

        music_section = any(has[c] for c in (
            "Albums", "Artists", "Genres", "All Tracks", "Playlists", "Photos"
        ))
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
                self._track_list.setArtist("")
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
            btn.setSelected(cat == active)

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
        subtitle_text = str(group.get("subtitle", "") or "")
        artist_text = str(group.get("artist", "") or "")
        if artist_text:
            artist_prefix = f"{artist_text} \u00b7 "
            if subtitle_text.startswith(artist_prefix):
                subtitle_text = subtitle_text[len(artist_prefix):]
            elif subtitle_text == artist_text:
                subtitle_text = ""
        self._track_list.setArtist(artist_text)
        self._track_list.setSubtitle(subtitle_text)

        # Build meta line: total duration + total size
        tracks = group["tracks"]
        total_ms = sum(getattr(t, "duration_ms", 0) or 0 for t in tracks)
        total_bytes = sum(getattr(t, "size", 0) or 0 for t in tracks)
        meta_parts = []
        if total_ms:
            meta_parts.append(format_duration_human(total_ms))
        if total_bytes:
            meta_parts.append(format_size(total_bytes))
        skipped = int(group.get("skipped_count", 0) or 0)
        if skipped:
            meta_parts.append(f"{skipped} skipped entr{'y' if skipped == 1 else 'ies'}")
        source_path = str(group.get("source_path", "") or "")
        if source_path:
            meta_parts.append(source_path)
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

        fallback_glyph = _CATEGORY_GLYPHS.get(group.get("category", ""), "music")
        self._track_list.setHeroArt(pixmap, fallback_glyph=fallback_glyph)
        if dcol:
            self._track_list.setHeroColor(*dcol)
        else:
            self._track_list.resetHeroColor()

        self._track_list.setHeroVisible(True)
        self._track_list.setBackVisible(True)
        self._track_list.setTracks(tracks, self._selected_tracks)
        self._content.setCurrentIndex(2)

    def _on_grid_item_context_requested(self, item_data_list: object, global_pos: QPoint):
        items = [
            dict(item)
            for item in item_data_list
            if isinstance(item, dict)
        ] if isinstance(item_data_list, list) else []
        tracks = self._tracks_for_grid_items(items)
        if not tracks:
            return

        multi = len(items) > 1
        add_label = "Add Selected to Queue" if multi else "Add to Queue"
        remove_label = "Remove Selected from Queue" if multi else "Remove from Queue"

        menu = QMenu(self)
        menu.setStyleSheet(context_menu_css())
        add_action = menu.addAction(add_label)
        remove_action = menu.addAction(remove_label)

        action = menu.exec(global_pos)
        if action == add_action:
            self._set_grid_playlists_checked(items, True)
            self._set_grid_tracks_checked(tracks, True)
        elif action == remove_action:
            self._set_grid_playlists_checked(items, False)
            self._set_grid_tracks_checked(tracks, False)

    def _tracks_for_grid_items(self, items: list[dict]) -> list:
        groups = self._groups.get(self._current_mode, {})
        tracks: list = []
        seen_paths: set[str] = set()
        for item in items:
            key = item.get("title", "")
            group = groups.get(key)
            if group is None:
                continue
            for track in group.get("tracks", []):
                path = getattr(track, "path", "")
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                tracks.append(track)
        return tracks

    def _set_grid_tracks_checked(self, tracks: list, checked: bool):
        changed = False
        for track in tracks:
            path = getattr(track, "path", "")
            if not path:
                continue
            if self._is_plan_selection_mode():
                changed = self._set_plan_track_selection(path, checked) or changed
            else:
                if self._selected_tracks.get(path, True) != checked:
                    changed = True
                self._selected_tracks[path] = checked
        content = self.__dict__.get("_content")
        if isinstance(content, QStackedWidget) and content.currentIndex() == 2:
            self._track_list.updateCheckStates(self._selected_tracks)
        if changed:
            self._update_footer()

    def _set_grid_playlists_checked(self, items: list[dict], checked: bool):
        if self._current_mode != "Playlists":
            return
        groups = self._groups.get("Playlists", {})
        changed = False
        for item in items:
            key = item.get("title", "")
            group = groups.get(key)
            if group is None:
                continue
            source_path = str(group.get("source_path", "") or "")
            if not source_path:
                continue
            if self._is_plan_selection_mode():
                changed = self._set_plan_playlist_selection(source_path, checked) or changed
            else:
                if self._selected_playlists.get(source_path, True) != checked:
                    changed = True
                self._selected_playlists[source_path] = checked
        if changed:
            self._update_footer()

    def _current_playlist_source_path(self) -> str:
        if self._current_mode != "Playlists" or not self._current_group:
            return ""
        group = self._groups.get("Playlists", {}).get(self._current_group, {})
        return str(group.get("source_path", "") or "")

    def _sync_current_playlist_selection_from_tracks(self) -> None:
        source_path = self._current_playlist_source_path()
        if not source_path:
            return
        any_selected = any(
            self._selected_tracks.get(getattr(track, "path", ""), False)
            for track in self._current_group_tracks
        )
        if self._is_plan_selection_mode():
            self._set_plan_playlist_selection(source_path, any_selected)
            return
        self._selected_playlists[source_path] = any_selected

    def _on_track_back(self):
        self._current_group = None
        self._current_group_tracks = []
        # Grid is still intact behind the track list — just switch back
        self._content.setCurrentIndex(1)

    # ── Checkbox toggling ────────────────────────────────────────────────

    def _on_track_toggled(self, path: str, checked: bool):
        if self._is_plan_selection_mode():
            self._set_plan_track_selection(path, checked)
            self._sync_current_playlist_selection_from_tracks()
            self._update_footer()
            return
        self._selected_tracks[path] = checked
        self._sync_current_playlist_selection_from_tracks()
        self._update_footer()

    def _on_select_all(self):
        if self._is_plan_selection_mode():
            self._set_current_plan_action_checked(True)
            return
        for path in self._selected_tracks:
            self._selected_tracks[path] = True
        for path in self._selected_photos:
            self._selected_photos[path] = True
        for path in self._selected_playlists:
            self._selected_playlists[path] = True
        # Refresh track list if visible
        if self._content.currentIndex() == 2:
            self._track_list.setAllChecked(True)
        if self._content.currentIndex() == 3:
            self._photo_list.setAllChecked(True)
        self._update_footer()

    def _on_deselect_all(self):
        if self._is_plan_selection_mode():
            self._set_current_plan_action_checked(False)
            return
        for path in self._selected_tracks:
            self._selected_tracks[path] = False
        for path in self._selected_photos:
            self._selected_photos[path] = False
        for path in self._selected_playlists:
            self._selected_playlists[path] = False
        if self._content.currentIndex() == 2:
            self._track_list.setAllChecked(False)
        if self._content.currentIndex() == 3:
            self._photo_list.setAllChecked(False)
        self._update_footer()

    def _on_group_select_all(self):
        """Select all tracks in the current drilled-in group."""
        for t in self._current_group_tracks:
            if self._is_plan_selection_mode():
                self._set_plan_track_selection(t.path, True)
            else:
                self._selected_tracks[t.path] = True
        source_path = self._current_playlist_source_path()
        if source_path:
            if self._is_plan_selection_mode():
                self._set_plan_playlist_selection(source_path, True)
            else:
                self._selected_playlists[source_path] = True
        self._track_list.setAllChecked(True)
        self._update_footer()

    def _on_group_deselect_all(self):
        """Deselect all tracks in the current drilled-in group."""
        for t in self._current_group_tracks:
            if self._is_plan_selection_mode():
                self._set_plan_track_selection(t.path, False)
            else:
                self._selected_tracks[t.path] = False
        source_path = self._current_playlist_source_path()
        if source_path:
            if self._is_plan_selection_mode():
                self._set_plan_playlist_selection(source_path, False)
            else:
                self._selected_playlists[source_path] = False
        self._track_list.setAllChecked(False)
        self._update_footer()

    def _on_photo_toggled(self, path: str, checked: bool):
        if self._is_plan_selection_mode():
            self._set_plan_photo_selection(path, checked)
            self._update_footer()
            return
        self._selected_photos[path] = checked
        self._update_footer()

    def _on_select_all_photos(self):
        if self._is_plan_selection_mode():
            self._set_current_plan_action_checked(True)
            return
        for path in self._selected_photos:
            self._selected_photos[path] = True
        self._photo_list.setAllChecked(True)
        self._update_footer()

    def _on_deselect_all_photos(self):
        if self._is_plan_selection_mode():
            self._set_current_plan_action_checked(False)
            return
        for path in self._selected_photos:
            self._selected_photos[path] = False
        self._photo_list.setAllChecked(False)
        self._update_footer()

    # ── Footer ───────────────────────────────────────────────────────────

    def _update_footer(self):
        if self._is_plan_selection_mode():
            self._update_plan_footer()
            return
        total_tracks = len(self._selected_tracks)
        checked_tracks = sum(1 for v in self._selected_tracks.values() if v)
        total_photos = len(self._selected_photos)
        checked_photos = sum(1 for v in self._selected_photos.values() if v)
        total_playlists = len(self._selected_playlists)
        checked_playlists = sum(1 for v in self._selected_playlists.values() if v)
        parts: list[str] = []
        if total_tracks:
            parts.append(f"{checked_tracks} of {total_tracks} tracks selected")
        if total_photos:
            parts.append(f"{checked_photos} of {total_photos} photos selected")
        if total_playlists:
            parts.append(f"{checked_playlists} of {total_playlists} playlists selected")
        self._count_label.setText(
            " · ".join(parts) if parts else "No music, photos, or playlists found"
        )
        self._done_btn.setEnabled((checked_tracks + checked_photos + checked_playlists) > 0)

    # ── Done / Cancel ────────────────────────────────────────────────────

    def _on_done(self):
        if self._is_plan_selection_mode():
            self.plan_selection_done.emit({
                key: set(value)
                for key, value in self._plan_selection_state.items()
            })
            return
        selected_track_paths = frozenset(
            path for path, checked in self._selected_tracks.items() if checked
        )
        selected_playlist_paths = frozenset(
            path for path, checked in self._selected_playlists.items() if checked
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
        self.selection_done.emit(list(self._folder_entries), {
            "tracks": selected_track_paths,
            "photos": tuple(selected_photo_imports),
            "playlists": selected_playlist_paths,
        })

    def _on_cancel(self):
        if self._is_plan_selection_mode():
            self.plan_selection_cancelled.emit()
            return
        self._cleanup_scan_worker()
        self.cancelled.emit()
