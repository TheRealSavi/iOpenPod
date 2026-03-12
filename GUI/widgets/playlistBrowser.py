"""
PlaylistBrowser — Dedicated playlist browsing widget.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QThread, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout,
    QWidget,
)

from ..styles import (
    Colors, FONT_FAMILY, Metrics, btn_css,
    sidebar_nav_css, sidebar_nav_selected_css,
    LABEL_SECONDARY, make_scroll_area,
    make_detail_row, make_separator, make_section_header,
)
from ..glyphs import glyph_icon, glyph_pixmap
from .formatters import (
    format_duration_human,
    format_mhsd5_type,
    format_size,
    format_sort_order,
    format_smart_rules_summary,
)
from .MBListView import MusicBrowserList
from .playlistEditor import NewPlaylistDialog, RegularPlaylistEditor, SmartPlaylistEditor
from .trackListTitleBar import TrackListTitleBar

log = logging.getLogger(__name__)

# Icons for each playlist type
_ICON_REGULAR = "annotation-dots"
_ICON_SMART = "filter"
_ICON_PODCAST = "broadcast"
_ICON_MASTER = "home"


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
        self._layout.setSpacing((8))

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
        source = playlist.get("_source", "regular")

        # ── Title ──
        self.title_label.setText(title)

        # ── Type badge ──
        if is_master:
            self.type_label.setText("Master Library Playlist")
        elif is_smart:
            self.type_label.setText("Smart Playlist")
        elif is_podcast or source == "podcast":
            self.type_label.setText("Podcast Playlist")
        else:
            self.type_label.setText("Playlist")

        # Show edit button for user-created playlists (smart or regular, not iPod browsing-category ones)
        editable = not is_master and source != "smart" and not is_podcast
        self.edit_btn.setVisible(editable)
        # Delete button for user-deletable playlists (not master, not iPod browsing-category)
        deletable = not is_master and source != "smart"
        self.delete_btn.setVisible(deletable)
        # Show evaluate button for any smart playlist (except master)
        self.evaluate_btn.setVisible(is_smart and not is_master)
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

        db_id = playlist.get("unk0x24", 0)
        if db_id:
            self._add_detail_row("Database ID", f"0x{db_id:016X}")

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

        db_id_2 = playlist.get("db_id_2", 0)
        if db_id_2:
            self._add_detail_row("DB ID 2", f"0x{db_id_2:016X}")

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
    new_playlist_requested = pyqtSignal(str)  # "smart" or "regular"

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame#playlistListPanel {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
        """)
        self.setObjectName("playlistListPanel")
        self.setFixedWidth((210))

        outer = QVBoxLayout(self)
        outer.setContentsMargins((10), (12), (10), (12))
        outer.setSpacing((8))

        # ── New Playlist button (fixed, above scroll) ──
        self._new_btn = QPushButton("＋  New Playlist")
        self._new_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.Bold))
        self._new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_btn.setMinimumHeight((34))
        self._new_btn.setStyleSheet(btn_css(
            bg=Colors.ACCENT_DIM,
            bg_hover=Colors.ACCENT_HOVER,
            bg_press=Colors.ACCENT_PRESS,
            fg=Colors.ACCENT,
            border=f"1px solid {Colors.ACCENT_BORDER}",
            radius=Metrics.BORDER_RADIUS_SM,
            padding="6px 8px",
        ))
        self._new_btn.clicked.connect(self._on_new_playlist)
        outer.addWidget(self._new_btn)

        # Scroll area wrapping playlist sections
        self._scroll = make_scroll_area()
        outer.addWidget(self._scroll, 1)

        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(0, 0, 0, 0)
        self._inner_layout.setSpacing(2)
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
        podcast: list[dict] = []
        master: dict | None = None

        for pl in playlists:
            if pl.get("master_flag"):
                master = pl
            elif pl.get("smart_playlist_data") or pl.get("_source") == "smart":
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
            empty_vbox.setSpacing((8))

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

    def _on_new_playlist(self) -> None:
        """Show the type picker dialog."""
        dlg = NewPlaylistDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            choice = dlg.get_choice()
            if choice:
                self.new_playlist_requested.emit(choice)

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

    def __init__(self):
        super().__init__()
        self._current_playlist: dict | None = None
        self._editing = False

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing((8))

        # ── Left: playlist list panel ──
        self.listPanel = PlaylistListPanel()
        self.listPanel.playlist_selected.connect(self._onPlaylistSelected)
        self.listPanel.new_playlist_requested.connect(self._onNewPlaylist)
        main_layout.addWidget(self.listPanel)

        # ── Right: vertical splitter (info-or-editor / track list) ──
        self.rightSplitter = QSplitter(Qt.Orientation.Vertical)

        # Stacked widget: index 0 = info card, index 1 = editor
        self._topStack = QStackedWidget()

        # Info card (page 0)
        self.infoCard = PlaylistInfoCard()
        self.infoCard.edit_btn.clicked.connect(self._onEditClicked)
        self.infoCard.delete_btn.clicked.connect(self._onDeleteClicked)
        self.infoCard.evaluate_btn.clicked.connect(self._onEvaluateNow)
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

        self._topStack.setCurrentIndex(0)  # start in browse mode
        self.rightSplitter.addWidget(self._topStack)

        # Track container (bottom)
        self.trackContainer = QFrame()
        self.trackContainerLayout = QVBoxLayout(self.trackContainer)
        self.trackContainerLayout.setContentsMargins(0, 0, 0, 0)
        self.trackContainerLayout.setSpacing(0)

        self.trackTitleBar = TrackListTitleBar(self.rightSplitter)
        self.trackContainerLayout.addWidget(self.trackTitleBar)

        self.trackList = MusicBrowserList()
        self.trackList.setMinimumHeight(0)
        self.trackList.setMinimumWidth(0)
        self.trackList.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.trackList.minimumSizeHint = lambda: QSize(0, 0)
        self.trackContainerLayout.addWidget(self.trackList)

        self.rightSplitter.addWidget(self.trackContainer)

        # Splitter styling
        self.rightSplitter.setCollapsible(0, True)
        self.rightSplitter.setCollapsible(1, True)
        self.rightSplitter.setHandleWidth((3))
        self.rightSplitter.setStretchFactor(0, 1)
        self.rightSplitter.setStretchFactor(1, 3)
        self.rightSplitter.setSizes([250, 600])
        self.rightSplitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {Colors.BORDER_SUBTLE};
            }}
            QSplitter::handle:hover {{
                background: {Colors.ACCENT};
            }}
            QSplitter::handle:pressed {{
                background: {Colors.ACCENT_LIGHT};
            }}
        """)

        main_layout.addWidget(self.rightSplitter, stretch=1)

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def loadPlaylists(self) -> None:
        """Load playlists from iTunesDBCache and populate the list panel."""
        from ..app import iTunesDBCache
        cache = iTunesDBCache.get_instance()
        if not cache.is_ready():
            return

        playlists = cache.get_playlists()
        self.listPanel.loadPlaylists(playlists)
        self._switchToBrowse()
        self.infoCard.showEmpty()
        self.trackList.clearTable()
        self.trackTitleBar.setTitle("Select a playlist")
        self.trackTitleBar.resetColor()
        self._current_playlist = None

    def clear(self) -> None:
        """Clear everything when device changes."""
        self._switchToBrowse()
        self.listPanel.clear()
        self.infoCard.showEmpty()
        self.trackList.clearTable()
        self.trackTitleBar.setTitle("Select a playlist")
        self.trackTitleBar.resetColor()
        self._current_playlist = None

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

    def _onPlaylistSelected(self, playlist: dict) -> None:
        """Handle when a playlist is clicked in the list panel."""
        # If editing, cancel first
        if self._editing:
            self._switchToBrowse()

        from ..app import iTunesDBCache

        self._current_playlist = playlist
        cache = iTunesDBCache.get_instance()
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
        from ..app import iTunesDBCache

        # Tag smart playlists appropriately
        if playlist_data.get("smart_playlist_data"):
            playlist_data.setdefault("_source", "regular")

        cache = iTunesDBCache.get_instance()
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
        from ..app import iTunesDBCache
        cache = iTunesDBCache.get_instance()
        if cache.is_ready():
            playlists = cache.get_playlists()
            self.listPanel.loadPlaylists(playlists)

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
        from ..app import iTunesDBCache

        cache = iTunesDBCache.get_instance()
        pid = playlist.get("playlist_id", 0)

        # Remove from user playlists cache (if it was user-created)
        cache.remove_user_playlist(pid)

        # Disable buttons during write
        self.infoCard.edit_btn.setEnabled(False)
        self.infoCard.delete_btn.setEnabled(False)
        self.infoCard.evaluate_btn.setEnabled(False)

        self._delete_worker = _PlaylistDeleteWorker(playlist)
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

        self._eval_worker = _PlaylistWriteWorker(playlist)
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
        from ..app import iTunesDBCache
        cache = iTunesDBCache.get_instance()
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


# =============================================================================
# _PlaylistWriteWorker — background thread for playlist save + write
# =============================================================================

class _PlaylistWriteWorker(QThread):
    """Merge a playlist into the iPod database and rewrite it."""

    finished_ok = pyqtSignal(int, str)  # matched_count, playlist_name
    failed = pyqtSignal(str)            # error message

    def __init__(self, playlist: dict):
        super().__init__()
        self._playlist = playlist

    def run(self):
        try:
            from ..app import iTunesDBCache, DeviceManager
            from SyncEngine.sync_executor import SyncExecutor

            cache = iTunesDBCache.get_instance()
            device = DeviceManager.get_instance()
            ipod_path = device.device_path
            if not ipod_path:
                self.failed.emit("No iPod connected.")
                return

            data = cache.get_data()
            if not data:
                self.failed.emit("No iPod database loaded.")
                return

            playlist = self._playlist
            name = playlist.get("Title", "Untitled")

            # ── Build a SyncExecutor to reuse its write + eval logic ──
            executor = SyncExecutor(ipod_path)

            existing_db = executor._read_existing_database()
            existing_tracks_data = existing_db["tracks"]
            existing_playlists_raw = list(existing_db["playlists"])
            existing_smart_raw = list(existing_db["smart_playlists"])

            # Convert tracks to TrackInfo objects
            all_tracks = []
            for t in existing_tracks_data:
                all_tracks.append(executor._track_dict_to_info(t))

            # Update the target playlist in the raw lists
            target_pid = playlist.get("playlist_id", 0)
            replaced = False
            for i, epl in enumerate(existing_playlists_raw):
                if epl.get("playlist_id") == target_pid:
                    existing_playlists_raw[i] = playlist
                    replaced = True
                    break
            if not replaced:
                for i, epl in enumerate(existing_smart_raw):
                    if epl.get("playlist_id") == target_pid:
                        existing_smart_raw[i] = playlist
                        replaced = True
                        break
            if not replaced:
                # New playlist — also merge any other user playlists
                existing_playlists_raw.append(playlist)

            # Also merge other pending user playlists
            try:
                for upl in cache.get_user_playlists():
                    uid = upl.get("playlist_id", 0)
                    if uid == target_pid:
                        continue  # already handled above
                    is_new = upl.get("_isNew", False)
                    if is_new:
                        existing_playlists_raw.append(upl)
                    else:
                        ureplaced = False
                        for i, epl in enumerate(existing_playlists_raw):
                            if epl.get("playlist_id") == uid:
                                existing_playlists_raw[i] = upl
                                ureplaced = True
                                break
                        if not ureplaced:
                            existing_playlists_raw.append(upl)
            except Exception:
                pass

            # Build and evaluate all playlists
            _master_name, playlists, smart_playlists = executor._build_and_evaluate_playlists(
                existing_tracks_data, all_tracks,
                existing_playlists_raw, existing_smart_raw,
            )

            # Find how many tracks matched our target playlist
            matched_count = 0
            for pl in playlists:
                if pl.playlist_id == target_pid:
                    matched_count = len(pl.track_ids)
                    break
            else:
                for pl in smart_playlists:
                    if pl.playlist_id == target_pid:
                        matched_count = len(pl.track_ids)
                        break

            # Write the database
            success = executor._write_database(
                all_tracks,
                playlists=playlists,
                smart_playlists=smart_playlists,
                master_playlist_name=_master_name,
            )

            if success:
                # Clear pending playlists — they've been written
                try:
                    cache._user_playlists.clear()
                except Exception:
                    pass
                self.finished_ok.emit(matched_count, name)
            else:
                self.failed.emit("Database write returned False.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))


# =============================================================================
# _PlaylistDeleteWorker — background thread for playlist deletion + rewrite
# =============================================================================

class _PlaylistDeleteWorker(QThread):
    """Remove a playlist from the iPod database and rewrite it."""

    finished_ok = pyqtSignal(str)   # playlist_name
    failed = pyqtSignal(str)        # error message

    def __init__(self, playlist: dict):
        super().__init__()
        self._playlist = playlist

    def run(self):
        try:
            from ..app import iTunesDBCache, DeviceManager
            from SyncEngine.sync_executor import SyncExecutor

            cache = iTunesDBCache.get_instance()
            device = DeviceManager.get_instance()
            ipod_path = device.device_path
            if not ipod_path:
                self.failed.emit("No iPod connected.")
                return

            data = cache.get_data()
            if not data:
                self.failed.emit("No iPod database loaded.")
                return

            playlist = self._playlist
            name = playlist.get("Title", "Untitled")
            target_pid = playlist.get("playlist_id", 0)

            executor = SyncExecutor(ipod_path)

            existing_db = executor._read_existing_database()
            existing_tracks_data = existing_db["tracks"]
            existing_playlists_raw = list(existing_db["playlists"])
            existing_smart_raw = list(existing_db["smart_playlists"])

            # Remove the target playlist from the raw lists
            existing_playlists_raw = [
                p for p in existing_playlists_raw
                if p.get("playlist_id") != target_pid
            ]
            existing_smart_raw = [
                p for p in existing_smart_raw
                if p.get("playlist_id") != target_pid
            ]

            # Convert tracks to TrackInfo objects
            all_tracks = []
            for t in existing_tracks_data:
                all_tracks.append(executor._track_dict_to_info(t))

            # Merge remaining user playlists (excluding the deleted one)
            try:
                for upl in cache.get_user_playlists():
                    uid = upl.get("playlist_id", 0)
                    if uid == target_pid:
                        continue
                    is_new = upl.get("_isNew", False)
                    if is_new:
                        existing_playlists_raw.append(upl)
                    else:
                        ureplaced = False
                        for i, epl in enumerate(existing_playlists_raw):
                            if epl.get("playlist_id") == uid:
                                existing_playlists_raw[i] = upl
                                ureplaced = True
                                break
                        if not ureplaced:
                            existing_playlists_raw.append(upl)
            except Exception:
                pass

            # Build and evaluate all playlists
            master_name, playlists, smart_playlists = executor._build_and_evaluate_playlists(
                existing_tracks_data, all_tracks,
                existing_playlists_raw, existing_smart_raw,
            )

            # Write the database
            success = executor._write_database(
                all_tracks,
                playlists=playlists,
                smart_playlists=smart_playlists,
                master_playlist_name=master_name,
            )

            if success:
                # Clear pending playlists — they've been written
                try:
                    cache._user_playlists.clear()
                except Exception:
                    pass
                self.finished_ok.emit(name)
            else:
                self.failed.emit("Database write returned False.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))
