"""
PlaylistBrowser — Dedicated playlist browsing widget.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_core.jobs import (
    PlaylistDeleteWorker as _PlaylistDeleteWorker,
)
from app_core.jobs import (
    PlaylistImportWorker as _PlaylistImportWorker,
)
from app_core.jobs import (
    PlaylistWriteWorker as _PlaylistWriteWorker,
)

from ..glyphs import glyph_icon, glyph_pixmap
from ..styles import (
    FONT_FAMILY,
    LABEL_SECONDARY,
    Colors,
    Metrics,
    btn_css,
    make_detail_row,
    make_scroll_area,
    make_section_header,
    make_separator,
    sidebar_nav_css,
    sidebar_nav_selected_css,
)
from .browserChrome import (
    BrowserHeroHeader,
    BrowserPane,
    chrome_action_btn_css,
    style_browser_splitter,
)
from .formatters import (
    format_duration_human,
    format_mhsd5_type,
    format_size,
    format_smart_rules_summary,
    format_sort_order,
)
from .MBListView import MusicBrowserList
from .playlistEditor import NewPlaylistDialog, RegularPlaylistEditor, SmartPlaylistEditor
from .trackListTitleBar import TrackListTitleBar

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app_core.services import (
        DeviceSessionService,
        LibraryCacheLike,
        LibraryService,
        SettingsService,
    )

# Icons for each playlist type
_ICON_REGULAR = "annotation-dots"
_ICON_SMART = "filter"
_ICON_PODCAST = "broadcast"
_ICON_MASTER = "home"
_ICON_CATEGORY = "grid"


# =============================================================================
# PlaylistInfoCard — right-hand info panel above the track list
# =============================================================================

class PlaylistInfoCard(QFrame):
    """Displays detailed metadata about the selected playlist."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame#playlistInfoCard {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
        """)
        self.setObjectName("playlistInfoCard")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins((16), (16), (16), (16))
        self._layout.setSpacing(8)

        # ── Title row ───────────────────────────────────────────
        self.title_label = QLabel("Select a playlist")
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        self.title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        self.title_label.setWordWrap(True)
        self._layout.addWidget(self.title_label)

        # ── Type badge ──────────────────────────────────────────
        self.type_label = QLabel("")
        self.type_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.type_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self._layout.addWidget(self.type_label)

        # ── Button row (Edit + Evaluate Now) ────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        btn_row.addStretch()

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _ed_ic = glyph_icon("edit", (14), Colors.ACCENT)
        if _ed_ic:
            self.edit_btn.setIcon(_ed_ic)
            self.edit_btn.setIconSize(QSize((14), (14)))
        self.edit_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.ACCENT_DIM,
            bg_press=Colors.ACCENT_PRESS,
            fg=Colors.ACCENT,
            border=f"1px solid {Colors.ACCENT_BORDER}",
            padding="3px 12px",
        ))
        self.edit_btn.hide()
        btn_row.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.DANGER_DIM,
            bg_press=Colors.DANGER_HOVER,
            fg=Colors.DANGER,
            border=f"1px solid {Colors.DANGER_BORDER}",
            padding="3px 12px",
        ))
        self.delete_btn.hide()
        btn_row.addWidget(self.delete_btn)

        self.evaluate_btn = QPushButton("Evaluate Now")
        self.evaluate_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.evaluate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _eval_ic = glyph_icon("check-circle", (14), Colors.SUCCESS)
        if _eval_ic:
            self.evaluate_btn.setIcon(_eval_ic)
            self.evaluate_btn.setIconSize(QSize((14), (14)))
        self.evaluate_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SUCCESS_DIM,
            bg_press=Colors.SUCCESS_HOVER,
            fg=Colors.SUCCESS,
            border=f"1px solid {Colors.SUCCESS_BORDER}",
            padding="3px 12px",
        ))
        self.evaluate_btn.setToolTip(
            "Evaluate this smart playlist against the current library "
            "and write the results to the iPod database."
        )
        self.evaluate_btn.hide()
        btn_row.addWidget(self.evaluate_btn)

        self.export_btn = QPushButton("Export")
        self.export_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _exp_ic = glyph_icon("arrow-up-tray", (14), Colors.TEXT_SECONDARY)
        if _exp_ic:
            self.export_btn.setIcon(_exp_ic)
            self.export_btn.setIconSize(QSize((14), (14)))
        self.export_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_HOVER,
            bg_press=Colors.SURFACE_ACTIVE,
            fg=Colors.TEXT_SECONDARY,
            border=f"1px solid {Colors.BORDER}",
            padding="3px 12px",
        ))
        self.export_btn.setToolTip("Export playlist to M3U8 file")
        self.export_btn.hide()
        btn_row.addWidget(self.export_btn)

        self._layout.addLayout(btn_row)

        # ── Separator ──────────────────────────────────────────
        self._layout.addWidget(make_separator())

        # ── Stats rows ──────────────────────────────────────────
        self.stats_label = QLabel("")
        self.stats_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.stats_label.setStyleSheet(LABEL_SECONDARY())
        self.stats_label.setWordWrap(True)
        self._layout.addWidget(self.stats_label)

        # ── Details section (scrollable for long smart rules) ──
        self.details_area = make_scroll_area()
        self.details_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.details_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.details_area.setMinimumHeight(0)

        self.details_widget = QWidget()
        self.details_widget.setStyleSheet("background: transparent; border: none;")
        self.details_layout = QVBoxLayout(self.details_widget)
        self.details_layout.setContentsMargins(0, 0, 0, 0)
        self.details_layout.setSpacing(3)
        self.details_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.details_area.setWidget(self.details_widget)
        self._layout.addWidget(self.details_area)

        self._detail_labels: list[QWidget] = []
        self._current_playlist: dict | None = None

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def showPlaylist(self, playlist: dict, resolved_tracks: list[dict]) -> None:
        """Populate the card with data from a parsed playlist dict."""
        self._clear_details()

        title = playlist.get("Title", "Untitled")
        is_master = bool(playlist.get("master_flag"))
        is_smart = bool(playlist.get("smart_playlist_data"))
        is_podcast = playlist.get("podcast_flag", 0) == 1
        is_category = playlist.get("_source") == "smart"
        source = playlist.get("_source", "regular")

        # ── Title ──
        self.title_label.setText(title)

        # ── Type badge ──
        if is_master:
            self.type_label.setText("Master Library Playlist")
        elif is_category:
            self.type_label.setText("iPod Browsing Playlist")
        elif is_smart:
            self.type_label.setText("Smart Playlist")
        elif is_podcast or source == "podcast":
            self.type_label.setText("Podcast Playlist")
        else:
            self.type_label.setText("Playlist")

        # Edit/delete: allowed for user playlists, blocked for master/category/podcast
        editable = not is_master and not is_category and not is_podcast
        self.edit_btn.setVisible(editable)
        deletable = not is_master and not is_category
        self.delete_btn.setVisible(deletable)
        # Show evaluate button for any smart playlist (except master and categories)
        self.evaluate_btn.setVisible(is_smart and not is_master and not is_category)
        # Show export button whenever there are tracks to export
        self.export_btn.setVisible(bool(resolved_tracks))
        self._current_playlist = playlist

        self._populate_stats(playlist, resolved_tracks, source)
        self._populate_ids_flags(playlist, is_master, is_podcast)
        self._populate_extra_mhods(playlist)
        self._populate_track_stats(resolved_tracks)
        self._populate_smart_rules(playlist, is_smart)

        self.details_layout.addStretch()

    def _populate_stats(self, playlist: dict, resolved_tracks: list[dict], source: str) -> None:
        """Populate stats line and basic detail rows."""
        track_count = len(resolved_tracks)
        total_ms = sum(t.get("length", 0) for t in resolved_tracks)
        total_size = sum(t.get("size", 0) for t in resolved_tracks)

        stat_parts = [f"{track_count} tracks"]
        if total_ms > 0:
            stat_parts.append(format_duration_human(total_ms))
        if total_size > 0:
            stat_parts.append(format_size(total_size))
        self.stats_label.setText(" · ".join(stat_parts))

        details: list[tuple[str, str]] = []
        details.append(("Sort Order", format_sort_order(playlist.get("sort_order", 0))))

        for ts_key, label in (("timestamp", "Created"), ("timestamp_2", "Modified")):
            ts = playlist.get(ts_key, 0)
            if ts and ts > 0:
                try:
                    details.append((label, datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")))
                except (ValueError, OSError):
                    pass

        details.append(("Dataset Source", source))

        mhsd5 = playlist.get("mhsd5_type")
        if mhsd5 is not None and mhsd5 != 0:
            details.append(("iPod Category", format_mhsd5_type(mhsd5)))

        for label_text, value_text in details:
            self._add_detail_row(label_text, value_text)

    def _populate_ids_flags(self, playlist: dict, is_master: bool, is_podcast: bool) -> None:
        """Populate identifiers and flags section."""
        self._add_section_header("Identifiers & Flags")

        pl_id = playlist.get("playlist_id", 0)
        if pl_id:
            self._add_detail_row("Playlist ID", f"0x{pl_id:016X}")

        pl_id_copy = playlist.get("playlist_id_2", 0)
        if pl_id_copy:
            self._add_detail_row("Playlist ID Copy", f"0x{pl_id_copy:016X}")

        database_id_2 = playlist.get("db_id_2", 0)
        if database_id_2:
            self._add_detail_row("Database ID", f"0x{database_id_2:016X}")

        flag1 = playlist.get("flag1", 0)
        flag2 = playlist.get("flag2", 0)
        flag3 = playlist.get("flag3", 0)

        type_str = "Master" if is_master else "Normal (visible)"
        self._add_detail_row("Playlist Type", type_str)

        if flag1 or flag2 or flag3:
            self._add_detail_row("Flag Bytes", f"f1={flag1}  f2={flag2}  f3={flag3}")

        if is_podcast:
            self._add_detail_row("Podcast Flag", "Yes")
        string_mhod_count = playlist.get("string_mhod_child_count", 0)
        self._add_detail_row("String MHODs", str(string_mhod_count))

        database_id_2 = playlist.get("db_id_2", 0)
        if database_id_2:
            self._add_detail_row("DB ID 2", f"0x{database_id_2:016X}")

        lib_indices = playlist.get("library_indices", [])
        if lib_indices:
            idx_summary = ", ".join(
                f"sort={li.get('sort_type', '?')} (n={li.get('count', '?')})"  # sort_type was sortType
                for li in lib_indices
            )
            self._add_detail_row("Library Indices", f"{len(lib_indices)} entries")
            self._add_detail_text(idx_summary)

    def _populate_extra_mhods(self, playlist: dict) -> None:
        """Populate extra MHOD fields section."""
        extra_binary = {k: v for k, v in playlist.items()
                        if k in ("playlist_prefs", "playlist_settings")}
        extra_strings = {k: v for k, v in playlist.items()
                         if k.startswith("unknown_mhod_")}
        known_extra = {**extra_binary, **extra_strings}
        if not known_extra:
            return

        self._add_section_header("Extra MHOD Fields")
        for k, v in known_extra.items():
            if isinstance(v, dict):
                ctx = v.get("context", "binary")
                bl = v.get("bodyLength", "?")
                display_val = f"{ctx} — {bl} bytes (opaque iTunes view settings)"
            elif isinstance(v, str):
                display_val = v if v else "(empty)"
            else:
                display_val = repr(v)[:80]
            self._add_detail_row(k, display_val)

    def _populate_track_stats(self, resolved_tracks: list[dict]) -> None:
        """Populate track statistics section."""
        if not resolved_tracks:
            return

        self._add_section_header("Track Statistics")

        bitrates = [t.get("bitrate", 0) for t in resolved_tracks if t.get("bitrate", 0) > 0]
        if bitrates:
            avg_br = sum(bitrates) / len(bitrates)
            self._add_detail_row("Avg Bitrate", f"{avg_br:.0f} kbps")

        ratings = [t.get("rating", 0) for t in resolved_tracks if t.get("rating", 0) > 0]
        if ratings:
            avg_rating = sum(ratings) / len(ratings) / 20.0
            self._add_detail_row("Avg Rating", f"{avg_rating:.1f} / 5 ★")

        artists = {t.get("Artist", "") for t in resolved_tracks if t.get("Artist")}
        albums = {t.get("Album", "") for t in resolved_tracks if t.get("Album")}
        genres = {t.get("Genre", "") for t in resolved_tracks if t.get("Genre")}
        if artists:
            self._add_detail_row("Unique Artists", str(len(artists)))
        if albums:
            self._add_detail_row("Unique Albums", str(len(albums)))
        if genres:
            self._add_detail_row("Unique Genres", str(len(genres)))

        filetypes: dict[str, int] = {}
        for t in resolved_tracks:
            ft = t.get("filetype", "")
            if ft:
                filetypes[ft] = filetypes.get(ft, 0) + 1
        if filetypes:
            ft_str = ", ".join(f"{k.strip()}: {v}" for k, v in sorted(filetypes.items(), key=lambda x: -x[1]))
            self._add_detail_row("File Types", ft_str)

        years = [t.get("year", 0) for t in resolved_tracks if t.get("year", 0) > 0]
        if years:
            min_y, max_y = min(years), max(years)
            yr_str = str(min_y) if min_y == max_y else f"{min_y}–{max_y}"
            self._add_detail_row("Year Range", yr_str)

    def _populate_smart_rules(self, playlist: dict, is_smart: bool) -> None:
        """Populate smart playlist rules section."""
        if not is_smart:
            return
        prefs = playlist.get("smart_playlist_data")
        rules = playlist.get("smart_playlist_rules")
        rule_lines = format_smart_rules_summary(rules, prefs)
        if rule_lines:
            self._add_section_header("Smart Rules")
            for line in rule_lines:
                self._add_detail_text(line)

    def showEmpty(self) -> None:
        """Show default empty state."""
        self._clear_details()
        self.title_label.setText("Select a playlist")
        self.type_label.setText("")
        self.stats_label.setText("")
        self.edit_btn.hide()
        self.delete_btn.hide()
        self.evaluate_btn.hide()
        self.export_btn.hide()
        self._current_playlist = None

    # ─────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────

    def _clear_details(self) -> None:
        """Remove all detail rows."""
        for lbl in self._detail_labels:
            lbl.setParent(None)  # type: ignore[arg-type]
            lbl.deleteLater()
        self._detail_labels.clear()
        # Remove stretch
        while self.details_layout.count():
            item = self.details_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()

    def _add_detail_row(self, label: str, value: str) -> None:
        """Add a key-value row to details."""
        row = make_detail_row(label, value)
        self.details_layout.addWidget(row)
        self._detail_labels.append(row)

    def _add_section_header(self, text: str) -> None:
        """Add a small section header label."""
        sep = make_separator()
        self.details_layout.addWidget(sep)
        self._detail_labels.append(sep)

        lbl = make_section_header(text)
        self.details_layout.addWidget(lbl)
        self._detail_labels.append(lbl)

    def _add_detail_text(self, text: str) -> None:
        """Add a plain text line to details (used for rule summaries)."""
        lbl = QLabel(text)
        lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        lbl.setWordWrap(True)
        self.details_layout.addWidget(lbl)
        self._detail_labels.append(lbl)


# =============================================================================
# PlaylistListPanel — left-hand scrollable list of playlists
# =============================================================================

class PlaylistListPanel(QFrame):
    """Scrollable list of playlists grouped by type with section headers."""
    playlist_selected = pyqtSignal(dict)  # Emits the full playlist dict

    def __init__(self):
        super().__init__()
        self.setObjectName("playlistListPanel")
        self.setStyleSheet("background: transparent; border: none;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area wrapping playlist sections
        self._scroll = make_scroll_area()
        outer.addWidget(self._scroll, 1)

        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(0, 0, 0, 0)
        self._inner_layout.setSpacing(4)
        self._inner_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._inner)

        self._buttons: list[QPushButton] = []
        self._button_icons: dict[int, str] = {}  # button index -> icon name
        self._selected_btn: QPushButton | None = None
        self._playlist_map: dict[int, dict] = {}  # button index -> playlist dict

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def loadPlaylists(self, playlists: list[dict]) -> None:
        """Populate the panel with playlists grouped by type."""
        self._clear()

        # Categorize
        regular: list[dict] = []
        smart: list[dict] = []
        category: list[dict] = []
        podcast: list[dict] = []
        master: dict | None = None

        for pl in playlists:
            if pl.get("master_flag"):
                master = pl
            elif pl.get("_source") == "smart":
                # All dataset 5 playlists are iPod browsing categories
                category.append(pl)
            elif pl.get("smart_playlist_data"):
                smart.append(pl)
            elif pl.get("podcast_flag", 0) == 1 or pl.get("_source") == "podcast":
                podcast.append(pl)
            else:
                regular.append(pl)

        # Build sections
        if regular:
            self._add_section("PLAYLISTS")
            for pl in regular:
                self._add_playlist_button(pl, _ICON_REGULAR)

        if smart:
            self._add_section("SMART PLAYLISTS")
            for pl in smart:
                self._add_playlist_button(pl, _ICON_SMART)

        if category:
            self._add_section("iPod CATEGORIES")
            for pl in category:
                self._add_playlist_button(pl, _ICON_CATEGORY, dimmed=True)

        if podcast:
            self._add_section("PODCASTS")
            for pl in podcast:
                self._add_playlist_button(pl, _ICON_PODCAST)

        # Master at bottom, dimmed
        if master:
            self._add_section("LIBRARY")
            self._add_playlist_button(master, _ICON_MASTER, dimmed=True)

        # Empty state
        if not regular and not smart and not podcast and master is None:
            empty_container = QWidget()
            empty_container.setStyleSheet("background: transparent; border: none;")
            empty_vbox = QVBoxLayout(empty_container)
            empty_vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_vbox.setSpacing(8)

            empty_icon = QLabel()
            _px = glyph_pixmap("annotation-dots", Metrics.FONT_ICON_LG, Colors.TEXT_TERTIARY)
            if _px:
                empty_icon.setPixmap(_px)
            else:
                empty_icon.setText("♫")
                empty_icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_LG))
            empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_icon.setStyleSheet("background: transparent; border: none;")
            empty_vbox.addWidget(empty_icon)

            empty_text = QLabel("No playlists on this iPod")
            empty_text.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
            empty_text.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
            empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_text.setWordWrap(True)
            empty_vbox.addWidget(empty_text)

            self._inner_layout.addWidget(empty_container)

        self._inner_layout.addStretch()

    def clear(self) -> None:
        """Public clear."""
        self._clear()

    def selectPlaylistById(self, playlist_id: int) -> bool:
        """Select a playlist button by playlist ID if it is present."""
        for index, playlist in self._playlist_map.items():
            if int(playlist.get("playlist_id", 0) or 0) == playlist_id:
                self._on_click(index)
                return True
        return False

    # ─────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────

    def _clear(self) -> None:
        self._buttons.clear()
        self._button_icons.clear()
        self._selected_btn = None
        self._playlist_map.clear()
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.setParent(None)  # type: ignore[arg-type]
                w.deleteLater()

    def _add_section(self, text: str) -> None:
        if not text:
            spacer = QWidget()
            spacer.setFixedHeight(8)
            spacer.setStyleSheet("background: transparent; border: none;")
            self._inner_layout.addWidget(spacer)
            return
        lbl = QLabel(text)
        lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; "
            f"border: none; padding: 8px 4px 3px 4px;"
        )
        self._inner_layout.addWidget(lbl)

    def _add_playlist_button(self, playlist: dict, icon_name: str, dimmed: bool = False) -> None:
        title = playlist.get("Title", "Untitled")
        count = playlist.get("mhip_child_count", 0)
        is_master = bool(playlist.get("master_flag"))

        display_title = title
        if is_master:
            display_title = "Library (Master)"

        btn_text = display_title
        if count > 0:
            btn_text += f"  ({count})"

        btn = QPushButton(btn_text)
        btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        btn.setToolTip(f"{title}\n{count} tracks")

        fg = Colors.TEXT_DISABLED if dimmed else Colors.TEXT_PRIMARY
        ic = glyph_icon(icon_name, (20), fg)
        if ic:
            btn.setIcon(ic)
            btn.setIconSize(QSize((20), (20)))

        btn.setStyleSheet(sidebar_nav_css())

        idx = len(self._buttons)
        self._playlist_map[idx] = playlist
        self._button_icons[idx] = icon_name
        btn.clicked.connect(lambda checked, i=idx: self._on_click(i))

        self._inner_layout.addWidget(btn)
        self._buttons.append(btn)

    def _on_click(self, index: int) -> None:
        # Reset previous selection
        if self._selected_btn is not None:
            prev_idx = self._buttons.index(self._selected_btn)
            self._selected_btn.setStyleSheet(sidebar_nav_css())
            prev_icon = self._button_icons.get(prev_idx)
            if prev_icon:
                pl = self._playlist_map.get(prev_idx)
                dimmed = bool(pl.get("master_flag")) if pl else False
                fg = Colors.TEXT_DISABLED if dimmed else Colors.TEXT_SECONDARY
                ic = glyph_icon(prev_icon, (20), fg)
                if ic:
                    self._selected_btn.setIcon(ic)

        # Highlight new selection
        btn = self._buttons[index]
        btn.setStyleSheet(sidebar_nav_selected_css())
        icon_name = self._button_icons.get(index)
        if icon_name:
            ic = glyph_icon(icon_name, (20), Colors.ACCENT)
            if ic:
                btn.setIcon(ic)
        self._selected_btn = btn

        playlist = self._playlist_map.get(index)
        if playlist:
            self.playlist_selected.emit(playlist)


# =============================================================================
# PlaylistBrowser — Combines list panel + info card + track list
# =============================================================================

class PlaylistBrowser(QFrame):
    """Full playlist browsing experience with list, info, and track table.

    Supports two modes:
        - **Browse** — read-only PlaylistInfoCard + track list (default)
        - **Edit**   — SmartPlaylistEditor replaces info card
    """

    def __init__(
        self,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
        libraries: LibraryService,
    ):
        super().__init__()
        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._library_cache: LibraryCacheLike = libraries.cache()
        self._current_playlist: dict | None = None
        self._editing = False
        self._playlist_signature: tuple | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = BrowserHeroHeader("Playlists", self)
        root.addWidget(self._header)

        self._new_playlist_btn = QPushButton("New Playlist")
        self._new_playlist_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.Bold))
        self._new_playlist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_playlist_btn.setStyleSheet(chrome_action_btn_css())
        self._new_playlist_btn.clicked.connect(self._onNewPlaylistButton)
        self._header.actions_layout.addWidget(self._new_playlist_btn)

        self._import_playlist_btn = QPushButton("Import Playlist")
        self._import_playlist_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._import_playlist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._import_playlist_btn.setStyleSheet(chrome_action_btn_css())
        self._import_playlist_btn.clicked.connect(self._onImportPlaylist)
        self._header.actions_layout.addWidget(self._import_playlist_btn)
        self._header.actions_layout.addStretch()

        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        style_browser_splitter(self._content_splitter)
        root.addWidget(self._content_splitter, 1)

        # ── Left: playlist list panel ──
        self.listPanel = PlaylistListPanel()
        self.listPanel.playlist_selected.connect(self._onPlaylistSelected)
        self._sidebar_pane = BrowserPane(
            "Playlists",
            min_width=220,
            body_margins=(8, 2, 8, 8),
        )
        self._sidebar_pane.addWidget(self.listPanel, 1)
        self._content_splitter.addWidget(self._sidebar_pane)

        # ── Right: vertical splitter (info-or-editor / track list) ──
        self.rightSplitter = QSplitter(Qt.Orientation.Vertical)

        # Stacked widget: index 0 = info card, index 1 = editor
        self._topStack = QStackedWidget()

        # Info card (page 0)
        self.infoCard = PlaylistInfoCard()
        self.infoCard.edit_btn.clicked.connect(self._onEditClicked)
        self.infoCard.delete_btn.clicked.connect(self._onDeleteClicked)
        self.infoCard.evaluate_btn.clicked.connect(self._onEvaluateNow)
        self.infoCard.export_btn.clicked.connect(self._onExportClicked)
        self.infoCard.setMinimumHeight(0)
        self.infoCard.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._topStack.addWidget(self.infoCard)

        # Smart playlist editor (page 1)
        self.editor = SmartPlaylistEditor()
        self.editor.saved.connect(self._onEditorSaved)
        self.editor.cancelled.connect(self._onEditorCancelled)
        self._topStack.addWidget(self.editor)

        # Regular playlist editor (page 2)
        self.regularEditor = RegularPlaylistEditor()
        self.regularEditor.saved.connect(self._onEditorSaved)
        self.regularEditor.cancelled.connect(self._onEditorCancelled)
        self._topStack.addWidget(self.regularEditor)

        # Import progress page (index 3)
        _imp_page = QFrame()
        _imp_page.setStyleSheet(
            f"QFrame {{ background: {Colors.SURFACE}; border: none; }}"
        )
        _imp_lay = QVBoxLayout(_imp_page)
        _imp_lay.setContentsMargins(24, 24, 24, 24)
        _imp_lay.setSpacing(12)
        _imp_lay.addStretch()

        _imp_title = QLabel("Importing Playlist\u2026")
        _imp_title.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        _imp_title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        _imp_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _imp_lay.addWidget(_imp_title)

        self._import_progress_bar = QProgressBar()
        self._import_progress_bar.setFixedHeight(8)
        self._import_progress_bar.setTextVisible(False)
        self._import_progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {Colors.SURFACE_ALT};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {Colors.ACCENT}, stop:1 {Colors.ACCENT_LIGHT});
                border-radius: 4px;
            }}
        """)
        _imp_lay.addWidget(self._import_progress_bar)

        self._import_status_label = QLabel("")
        self._import_status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._import_status_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
        )
        self._import_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._import_status_label.setWordWrap(True)
        _imp_lay.addWidget(self._import_status_label)

        self._import_count_label = QLabel("")
        self._import_count_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._import_count_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent;"
        )
        self._import_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _imp_lay.addWidget(self._import_count_label)

        _imp_lay.addStretch()
        self._topStack.addWidget(_imp_page)  # Index 3

        self._import_worker: _PlaylistImportWorker | None = None

        self._topStack.setCurrentIndex(0)  # start in browse mode
        self.rightSplitter.addWidget(self._topStack)

        # Track container (bottom)
        self.trackContainer = QFrame()
        self.trackContainerLayout = QVBoxLayout(self.trackContainer)
        self.trackContainerLayout.setContentsMargins(0, 0, 0, 0)
        self.trackContainerLayout.setSpacing(0)

        self.trackTitleBar = TrackListTitleBar(self.rightSplitter)
        self.trackContainerLayout.addWidget(self.trackTitleBar)

        self.trackList = MusicBrowserList(
            settings_service=self._settings_service,
            device_sessions=self._device_sessions,
            library_cache=self._library_cache,
        )
        self.trackList.setMinimumHeight(0)
        self.trackList.setMinimumWidth(0)
        self.trackList.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.trackList.minimumSizeHint = lambda: QSize(0, 0)
        self.trackContainerLayout.addWidget(self.trackList)

        self.rightSplitter.addWidget(self.trackContainer)

        # Splitter styling
        self.rightSplitter.setCollapsible(0, True)
        self.rightSplitter.setCollapsible(1, True)
        self.rightSplitter.setHandleWidth(0)
        self.rightSplitter.setStretchFactor(0, 1)
        self.rightSplitter.setStretchFactor(1, 3)
        self.rightSplitter.setSizes([250, 600])
        style_browser_splitter(self.rightSplitter)

        self._content_splitter.addWidget(self.rightSplitter)
        self._content_splitter.setStretchFactor(0, 0)
        self._content_splitter.setStretchFactor(1, 1)
        self._content_splitter.setSizes([240, 760])

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def loadPlaylists(self) -> None:
        """Load playlists from iTunesDBCache and populate the list panel."""
        cache = self._library_cache
        if not cache.is_ready():
            return

        playlists = cache.get_playlists()
        signature = self._compute_playlist_signature(playlists)
        if signature == self._playlist_signature:
            return

        self.listPanel.loadPlaylists(playlists)
        self._playlist_signature = signature
        self._switchToBrowse()
        self.infoCard.showEmpty()
        self.trackList.clearTable()
        self.trackTitleBar.setTitle("Select a playlist")
        self.trackTitleBar.resetColor()
        self._current_playlist = None

    def refreshFromCache(self) -> None:
        """Refresh playlist UI from cache while preserving the current selection."""
        cache = self._library_cache
        if not cache.is_ready():
            return

        playlists = cache.get_playlists()
        signature = self._compute_playlist_signature(playlists)
        current_pid = int((self._current_playlist or {}).get("playlist_id", 0) or 0)

        if signature != self._playlist_signature:
            self.listPanel.loadPlaylists(playlists)
            self._playlist_signature = signature

        if current_pid:
            if self.listPanel.selectPlaylistById(current_pid):
                return

    def clear(self) -> None:
        """Clear everything when device changes."""
        self._switchToBrowse()
        self.listPanel.clear()
        self.infoCard.showEmpty()
        self.trackList.clearTable(clear_cache=True)
        self.trackTitleBar.setTitle("Select a playlist")
        self.trackTitleBar.resetColor()
        self._current_playlist = None
        self._playlist_signature = None

    @staticmethod
    def _compute_playlist_signature(playlists: list[dict]) -> tuple:
        """Compute a lightweight signature to detect list changes quickly."""
        return tuple(
            sorted(
                (
                    int(pl.get("playlist_id", 0) or 0),
                    str(pl.get("Title", "")),
                    int(pl.get("mhip_child_count", 0) or 0),
                    int(pl.get("master_flag", 0) or 0),
                    str(pl.get("_source", "")),
                )
                for pl in playlists
            )
        )

    # ─────────────────────────────────────────────────────────────
    # Mode switching
    # ─────────────────────────────────────────────────────────────

    def _switchToEditor(self, page: int = 1) -> None:
        """Show a playlist editor in place of the info card.

        Args:
            page: 1 = smart playlist editor, 2 = regular playlist editor.
        """
        self._topStack.setCurrentIndex(page)
        self._editing = True
        # Give the editor more room
        self.rightSplitter.setSizes([450, 400])

    def _switchToBrowse(self) -> None:
        """Show the info card (default view)."""
        self._topStack.setCurrentIndex(0)
        self._editing = False
        self.rightSplitter.setSizes([250, 600])

    # ─────────────────────────────────────────────────────────────
    # Slots
    # ─────────────────────────────────────────────────────────────

    def _set_import_busy(self, busy: bool) -> None:
        self._import_playlist_btn.setEnabled(not busy)
        self._new_playlist_btn.setEnabled(not busy)
        self._import_playlist_btn.setText("Importing…" if busy else "Import Playlist")

    def _onNewPlaylistButton(self) -> None:
        dlg = NewPlaylistDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            choice = dlg.get_choice()
            if choice:
                self._onNewPlaylist(choice)

    def _onPlaylistSelected(self, playlist: dict) -> None:
        """Handle when a playlist is clicked in the list panel."""
        # If editing, cancel first
        if self._editing:
            self._switchToBrowse()

        self._current_playlist = playlist
        cache = self._library_cache
        if not cache.is_ready():
            return

        track_id_index = cache.get_track_id_index()

        # Resolve track IDs from MHIP items
        items = playlist.get("items", [])
        track_ids = [item.get("track_id", 0) for item in items]
        resolved_tracks = [track_id_index[tid] for tid in track_ids if tid in track_id_index]

        # Update info card
        self.infoCard.showPlaylist(playlist, resolved_tracks)

        # Update title bar
        title = playlist.get("Title", "Untitled")
        if playlist.get("master_flag"):
            title = "Library (Master)"
        self.trackTitleBar.setTitle(title)

        # Color the title bar based on playlist type
        if playlist.get("smart_playlist_data"):
            self.trackTitleBar.setColor(*Colors.PLAYLIST_SMART)
        elif playlist.get("podcast_flag", 0) == 1 or playlist.get("_source") == "podcast":
            self.trackTitleBar.setColor(*Colors.PLAYLIST_PODCAST)
        elif playlist.get("master_flag"):
            self.trackTitleBar.setColor(*Colors.PLAYLIST_MASTER)
        else:
            self.trackTitleBar.resetColor()

        # Load tracks into table
        if resolved_tracks:
            self.trackList.filterByPlaylist(track_ids, track_id_index, playlist)
        else:
            self.trackList.clearTable()

    def _onNewPlaylist(self, kind: str) -> None:
        """Handle the 'New Playlist' button from the list panel."""
        if kind == "smart":
            self.editor.new_playlist()
            self._switchToEditor(1)
            self.trackTitleBar.setTitle("New Smart Playlist")
            self.trackTitleBar.setColor(*Colors.PLAYLIST_SMART)
            self.trackList.clearTable()
        else:
            self.regularEditor.new_playlist()
            self._switchToEditor(2)
            self.trackTitleBar.setTitle("New Playlist")
            self.trackTitleBar.resetColor()
            self.trackList.clearTable()

    def _onEditClicked(self) -> None:
        """Handle the Edit button on the info card."""
        if not self._current_playlist:
            return
        if self._current_playlist.get("smart_playlist_data"):
            self.editor.edit_playlist(self._current_playlist)
            self._switchToEditor(1)
        elif not self._current_playlist.get("master_flag"):
            self.regularEditor.edit_playlist(self._current_playlist)
            self._switchToEditor(2)

    def _onDeleteClicked(self) -> None:
        """Handle the Delete button — confirm, remove from cache, rewrite DB."""
        playlist = self._current_playlist
        if not playlist or playlist.get("master_flag"):
            return

        title = playlist.get("Title", "Untitled")
        reply = QMessageBox.question(
            self, "Delete Playlist",
            f"Are you sure you want to delete '{title}'?\n\n"
            "This will remove the playlist from the iPod immediately.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._deletePlaylistFromIPod(playlist)

    def _onEditorSaved(self, playlist_data: dict) -> None:
        """Handle when the editor's Save button is clicked.

        Persists the playlist into iTunesDBCache's user playlist store,
        then immediately writes the full database to the iPod so the
        change takes effect right away.
        """
        # Tag smart playlists appropriately
        if playlist_data.get("smart_playlist_data"):
            playlist_data.setdefault("_source", "regular")

        cache = self._library_cache
        cache.save_user_playlist(playlist_data)

        # Remember the saved playlist so we can re-select it
        self._current_playlist = playlist_data
        self._switchToBrowse()

        # Refresh the list panel; the new/edited playlist is now in get_playlists()
        self._refreshList()

        # Select the saved playlist in the list (if it has an ID)
        self.infoCard.showPlaylist(playlist_data, [])

        title = playlist_data.get("Title", "Untitled")
        self.trackTitleBar.setTitle(title)
        if playlist_data.get("smart_playlist_data"):
            self.trackTitleBar.setColor(*Colors.PLAYLIST_SMART)
        else:
            self.trackTitleBar.resetColor()

        log.info("Playlist saved to cache: '%s' (id=0x%X)",
                 title, playlist_data.get("playlist_id", 0))

        # ── Write to iPod immediately ──
        self._writePlaylistToIPod(playlist_data)

    def _refreshList(self) -> None:
        """Reload the playlist list from cache."""
        cache = self._library_cache
        if cache.is_ready():
            playlists = cache.get_playlists()
            self.listPanel.loadPlaylists(playlists)
            self._playlist_signature = self._compute_playlist_signature(playlists)

    def _onEditorCancelled(self) -> None:
        """Handle when the editor's Cancel button is clicked."""
        self._switchToBrowse()
        # Re-show the previously selected playlist if any
        if self._current_playlist:
            self._onPlaylistSelected(self._current_playlist)

    # ─────────────────────────────────────────────────────────────
    # Write playlist to iPod (shared by Save + Evaluate Now)
    # ─────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────
    # Delete playlist from iPod
    # ─────────────────────────────────────────────────────────────

    def _deletePlaylistFromIPod(self, playlist: dict) -> None:
        """Remove a playlist from cache and rewrite the iPod database."""
        cache = self._library_cache
        pid = playlist.get("playlist_id", 0)

        # Remove from user playlists cache (if it was user-created)
        cache.remove_user_playlist(pid)

        # Disable buttons during write
        self.infoCard.edit_btn.setEnabled(False)
        self.infoCard.delete_btn.setEnabled(False)
        self.infoCard.evaluate_btn.setEnabled(False)

        self._delete_worker = _PlaylistDeleteWorker(
            playlist,
            self._device_sessions.current_session().device_path or "",
            self._library_cache,
        )
        self._delete_worker.finished_ok.connect(self._onDeleteDone)
        self._delete_worker.failed.connect(self._onDeleteFailed)
        self._delete_worker.start()

    def _onDeleteDone(self, playlist_name: str) -> None:
        """Playlist deletion completed successfully."""
        self.infoCard.edit_btn.setEnabled(True)
        self.infoCard.delete_btn.setEnabled(True)
        self.infoCard.evaluate_btn.setEnabled(True)

        log.info("Playlist '%s' deleted from iPod", playlist_name)

        # Clear the view and re-show the list
        self._current_playlist = None
        self.infoCard.showEmpty()
        self.trackList.clearTable()
        self.trackTitleBar.setTitle("Select a playlist")
        self.trackTitleBar.resetColor()

        # Rescan after a short delay
        QTimer.singleShot(500, self._rescanAfterWrite)

    def _onDeleteFailed(self, error_msg: str) -> None:
        """Playlist deletion write failed."""
        self.infoCard.edit_btn.setEnabled(True)
        self.infoCard.delete_btn.setEnabled(True)
        self.infoCard.evaluate_btn.setEnabled(True)

        log.error("Playlist delete failed: %s", error_msg)
        QMessageBox.critical(
            self, "Delete Failed",
            f"Failed to delete playlist from iPod:\n{error_msg}"
        )

    # ─────────────────────────────────────────────────────────────
    # Write playlist to iPod (shared by Save + Evaluate Now)
    # ─────────────────────────────────────────────────────────────

    def _writePlaylistToIPod(self, playlist: dict) -> None:
        """Kick off a background write of the full database to the iPod.

        Used after both editor Save and Evaluate Now.
        """
        # Show a saving indicator on the info card
        self.infoCard.edit_btn.setEnabled(False)
        self.infoCard.evaluate_btn.setEnabled(False)
        self.infoCard.evaluate_btn.setText("Writing…")
        self.infoCard.evaluate_btn.setVisible(True)

        self._eval_worker = _PlaylistWriteWorker(
            playlist,
            self._device_sessions.current_session().device_path or "",
            self._library_cache,
        )
        self._eval_worker.finished_ok.connect(self._onWriteDone)
        self._eval_worker.failed.connect(self._onWriteFailed)
        self._eval_worker.start()

    def _onWriteDone(self, matched_count: int, playlist_name: str) -> None:
        """Playlist write completed successfully."""
        self.infoCard.edit_btn.setEnabled(True)
        self.infoCard.evaluate_btn.setEnabled(True)
        self.infoCard.evaluate_btn.setText("Evaluate Now")
        # Re-evaluate visibility (evaluate is only for smart playlists)
        if self._current_playlist and not self._current_playlist.get("smart_playlist_data"):
            self.infoCard.evaluate_btn.setVisible(False)

        is_smart = self._current_playlist and self._current_playlist.get("smart_playlist_data")

        if is_smart:
            log.info("Playlist '%s': %d tracks matched → written to iPod",
                     playlist_name, matched_count)
            QMessageBox.information(
                self, "Playlist Saved",
                f"'{playlist_name}' saved to iPod: {matched_count} tracks matched."
            )
        else:
            log.info("Playlist '%s' written to iPod", playlist_name)
            QMessageBox.information(
                self, "Playlist Saved",
                f"'{playlist_name}' saved to iPod."
            )

        # Small delay before rescanning so the OS flushes the file to disk
        QTimer.singleShot(500, self._rescanAfterWrite)

    def _rescanAfterWrite(self) -> None:
        """Rescan the iPod database after a short post-write delay."""
        cache = self._library_cache
        cache.invalidate()
        cache.start_loading()

    def _onWriteFailed(self, error_msg: str) -> None:
        """Playlist write failed."""
        self.infoCard.edit_btn.setEnabled(True)
        self.infoCard.evaluate_btn.setEnabled(True)
        self.infoCard.evaluate_btn.setText("Evaluate Now")
        if self._current_playlist and not self._current_playlist.get("smart_playlist_data"):
            self.infoCard.evaluate_btn.setVisible(False)

        log.error("Playlist write failed: %s", error_msg)
        QMessageBox.critical(
            self, "Save Failed",
            f"Failed to write playlist to iPod:\n{error_msg}"
        )

    # ─────────────────────────────────────────────────────────────
    # Evaluate Now
    # ─────────────────────────────────────────────────────────────

    def _onEvaluateNow(self) -> None:
        """Evaluate the current smart playlist and write to iPod."""
        playlist = self._current_playlist
        if not playlist or not playlist.get("smart_playlist_data"):
            return

        prefs_data = playlist.get("smart_playlist_data")
        rules_data = playlist.get("smart_playlist_rules")
        if not prefs_data or not rules_data:
            QMessageBox.warning(
                self, "Cannot Evaluate",
                "This playlist has no smart rules to evaluate."
            )
            return

        # Use the shared write flow
        self._writePlaylistToIPod(playlist)

    def _onExportClicked(self) -> None:
        """Export the current playlist to a standard playlist file."""
        import os

        tracks = self.trackList.tracks
        if not tracks:
            return

        playlist_name = (self._current_playlist or {}).get("Title", "playlist")
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in playlist_name).strip()

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Playlist",
            safe_name + ".m3u8",
            "M3U8 Playlist (*.m3u8);;"
            "M3U Playlist (*.m3u);;"
            "PLS Playlist (*.pls);;"
            "XSPF Playlist (*.xspf);;"
            "All Files (*)",
        )
        if not path:
            return

        ipod_root = self._device_sessions.current_session().device_path or ""

        def _abs_path(track: dict) -> str:
            location = track.get("Location", "")
            if location and ipod_root:
                return os.path.join(ipod_root, location.replace(":", "/").lstrip("/"))
            return location

        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".pls":
                content = self._export_pls(tracks, _abs_path)
            elif ext == ".xspf":
                content = self._export_xspf(tracks, _abs_path, playlist_name)
            else:  # .m3u8, .m3u, or anything else
                content = self._export_m3u(tracks, _abs_path)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            QMessageBox.warning(self, "Export Failed", f"Could not write file:\n{e}")

    # ─────────────────────────────────────────────────────────────
    # Import Playlist
    # ─────────────────────────────────────────────────────────────

    def _onImportPlaylist(self) -> None:
        """Open a file dialog and kick off the import worker."""
        device = self._device_sessions.current_session()
        if not device.device_path:
            QMessageBox.warning(self, "No Device", "Please connect an iPod first.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Playlist",
            "",
            "Playlist Files (*.m3u *.m3u8 *.pls *.xspf);;All Files (*)",
        )
        if not path:
            return

        settings = self._settings_service.get_effective_settings()

        self._set_import_busy(True)
        self._topStack.setCurrentIndex(3)
        self._import_progress_bar.setRange(0, 0)  # indeterminate
        self._import_status_label.setText("Parsing playlist…")
        self._import_count_label.setText("")

        self._import_worker = _PlaylistImportWorker(
            playlist_file=path,
            ipod_path=str(device.device_path),
            fpcalc_path=settings.fpcalc_path,
            cache=self._library_cache,
        )
        self._import_worker.progress.connect(self._onImportProgress)
        self._import_worker.finished_ok.connect(self._onImportDone)
        self._import_worker.failed.connect(self._onImportFailed)
        self._import_worker.start()

    def _onImportProgress(self, current: int, total: int, message: str) -> None:
        if total > 0:
            self._import_progress_bar.setRange(0, total)
            self._import_progress_bar.setValue(current)
            self._import_count_label.setText(f"{current} / {total}")
        else:
            # Indeterminate — keep bar spinning but don't clear previous count
            self._import_progress_bar.setRange(0, 0)
            self._import_count_label.setText("")
        self._import_status_label.setText(message)

    def _onImportDone(self, playlist_name: str, added: int, already_present: int, skipped: int) -> None:
        self._set_import_busy(False)
        self._switchToBrowse()
        parts = []
        if added:
            parts.append(f"{added} track(s) added to iPod")
        if already_present:
            parts.append(f"{already_present} already on iPod")
        if skipped:
            parts.append(f"{skipped} skipped (not found on PC)")
        summary = "\n".join(parts) if parts else "No tracks found."
        QMessageBox.information(
            self, "Import Complete",
            f"Playlist '{playlist_name}' imported.\n\n{summary}",
        )
        QTimer.singleShot(500, self._rescanAfterWrite)

    def _onImportFailed(self, error_msg: str) -> None:
        self._set_import_busy(False)
        self._switchToBrowse()
        QMessageBox.critical(self, "Import Failed", f"Could not import playlist:\n{error_msg}")

    @staticmethod
    def _export_m3u(tracks: list[dict], abs_path_fn) -> str:
        lines = ["#EXTM3U", ""]
        for track in tracks:
            title = track.get("Title") or "Unknown Title"
            artist = track.get("Artist") or track.get("Album Artist") or ""
            duration_s = int((track.get("length") or 0) / 1000)
            extinf_title = f"{artist} - {title}" if artist else title
            lines.append(f"#EXTINF:{duration_s},{extinf_title}")
            lines.append(abs_path_fn(track))
        return "\n".join(lines) + "\n"

    @staticmethod
    def _export_pls(tracks: list[dict], abs_path_fn) -> str:
        lines = ["[playlist]", ""]
        for i, track in enumerate(tracks, 1):
            title = track.get("Title") or "Unknown Title"
            artist = track.get("Artist") or track.get("Album Artist") or ""
            duration_s = int((track.get("length") or 0) / 1000)
            display = f"{artist} - {title}" if artist else title
            lines.append(f"File{i}={abs_path_fn(track)}")
            lines.append(f"Title{i}={display}")
            lines.append(f"Length{i}={duration_s if duration_s else -1}")
            lines.append("")
        lines.append(f"NumberOfEntries={len(tracks)}")
        lines.append("Version=2")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _export_xspf(tracks: list[dict], abs_path_fn, playlist_title: str) -> str:
        import xml.etree.ElementTree as ET
        from urllib.request import pathname2url

        root = ET.Element("playlist", version="1", xmlns="http://xspf.org/ns/0/")
        ET.SubElement(root, "title").text = playlist_title
        track_list = ET.SubElement(root, "trackList")

        for track in tracks:
            t = ET.SubElement(track_list, "track")
            raw_path = abs_path_fn(track)
            if raw_path:
                ET.SubElement(t, "location").text = "file://" + pathname2url(raw_path)
            if title := track.get("Title"):
                ET.SubElement(t, "title").text = title
            artist = track.get("Artist") or track.get("Album Artist") or ""
            if artist:
                ET.SubElement(t, "creator").text = artist
            if album := track.get("Album"):
                ET.SubElement(t, "album").text = album
            if duration_ms := track.get("length"):
                ET.SubElement(t, "duration").text = str(int(duration_ms))
            if track_num := track.get("track_number"):
                ET.SubElement(t, "trackNum").text = str(track_num)

        ET.indent(root, space="  ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        ) + "\n"
