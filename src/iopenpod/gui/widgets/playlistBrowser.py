"""
PlaylistBrowser — Dedicated playlist browsing widget.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from iopenpod.application.jobs import (
    PlaylistDeleteWorker as _PlaylistDeleteWorker,
)
from iopenpod.application.jobs import (
    PlaylistImportWorker as _PlaylistImportWorker,
)
from iopenpod.application.jobs import (
    PlaylistWriteWorker as _PlaylistWriteWorker,
)
from iopenpod.application.runtime import display_playlists_from_rows
from iopenpod.itunesdb_shared.constants import MHOD_TYPE_TITLE
from iopenpod.itunesdb_shared.playlist_properties import playlist_description_from_row

from ..glyphs import glyph_icon, glyph_pixmap
from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
    btn_css,
    make_detail_row,
    make_scroll_area,
    make_separator,
    make_sidebar_section_header,
    panel_css,
    progress_bar_css,
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
from .sidebarNavButton import SidebarNavButton
from .trackListTitleBar import TrackListTitleBar

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from iopenpod.application.services import (
        DeviceSessionService,
        LibraryCacheLike,
        LibraryService,
        SettingsService,
    )

# Icons for each playlist type
_ICON_REGULAR = "playlist"
_ICON_SMART = "filter"
_ICON_PODCAST = "broadcast"
_ICON_MASTER = "home"
_ICON_CATEGORY = "grid"


def _delete_embedded_widget(widget: QWidget | None) -> None:
    if widget is None:
        return
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


def _label_css(color: str) -> str:
    return f"color: {color}; background: transparent; border: none;"


def _subtle_label_css(color: str = Colors.TEXT_TERTIARY) -> str:
    return (
        f"color: {color}; background: transparent; border: none;"
        " text-transform: uppercase;"
    )


def _mhsd5_type_value(playlist: dict | None) -> int:
    if not playlist:
        return 0
    return _int_value(playlist.get("mhsd5_type"))


def _is_ipod_category_playlist(playlist: dict | None) -> bool:
    if not playlist:
        return False
    dataset_type = _playlist_dataset_type(playlist)
    if dataset_type:
        return dataset_type == 5
    return bool(playlist.get("_source") == "category" and dataset_type in (0, 5))


def _playlist_dataset_type(playlist: dict | None) -> int:
    if not playlist:
        return 0
    return _int_value(playlist.get("_mhsd_dataset_type"))


def _is_user_smart_playlist(playlist: dict | None) -> bool:
    return bool(
        playlist
        and playlist.get("smart_playlist_data")
        and not _is_ipod_category_playlist(playlist)
    )


def _is_regular_track_playlist(playlist: dict | None) -> bool:
    if not playlist:
        return False
    source = str(playlist.get("_source") or "").strip()
    if source and source != "regular":
        return False
    if playlist.get("master_flag") or _is_ipod_category_playlist(playlist):
        return False
    if _is_display_merged_playlist(playlist):
        return False
    if _is_user_smart_playlist(playlist):
        return False
    if playlist.get("podcast_flag", 0) == 1:
        return False
    if playlist.get("_source") in ("category", "smart"):
        return False
    return True


def _display_origin_types(playlist: dict | None) -> list[int]:
    if not playlist:
        return []
    raw = playlist.get("_mhsd_display_types")
    if isinstance(raw, list):
        return [_int_value(value) for value in raw if _int_value(value)]
    dataset_type = _playlist_dataset_type(playlist)
    return [dataset_type] if dataset_type else []


def _is_display_merged_playlist(playlist: dict | None) -> bool:
    return bool(playlist and playlist.get("_mhsd_display_merged"))


def _mhsd_type_label(playlist: dict | None) -> str:
    types = _display_origin_types(playlist)
    if not types:
        return "MHSD type unknown"
    return " + ".join(f"MHSD type {dataset_type}" for dataset_type in types)


def _int_value(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        try:
            return int(text)
        except ValueError:
            return 0
    if isinstance(value, bytes | bytearray):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _mhip_title_from_children(item: dict) -> str:
    for wrapper in item.get("children", []) or []:
        if not isinstance(wrapper, dict):
            continue
        data = wrapper.get("data", {})
        if (
            isinstance(data, dict)
            and data.get("mhod_type") == MHOD_TYPE_TITLE
            and data.get("string")
        ):
            return str(data["string"])
    return ""


def _podcast_grouping_summary(
    playlist: dict | None,
    track_id_index: dict[int, dict] | None = None,
) -> list[dict[str, object]]:
    """Return parsed dataset-3 podcast groups without inventing hierarchy.

    Type-3 podcast playlists may contain synthetic MHIP group-header rows
    (``podcast_group_flag == 256``) followed by episode rows whose
    ``group_id_ref`` points back to the header. That is not a general playlist
    folder model; it is the podcast grouping libgpod writes for MHSD type 3.
    """

    if not playlist or _playlist_dataset_type(playlist) != 3:
        return []

    items = playlist.get("items", [])
    if not isinstance(items, list):
        return []

    groups_by_id: dict[int, dict[str, object]] = {}
    order: list[int] = []
    ungrouped: list[dict] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        if _int_value(item.get("podcast_group_flag")) != 256:
            continue
        group_id = _int_value(item.get("group_id"))
        if not group_id:
            continue
        title = (
            str(item.get("podcast_group_title") or "").strip()
            or _mhip_title_from_children(item).strip()
            or f"Group {group_id}"
        )
        groups_by_id[group_id] = {"group_id": group_id, "title": title, "items": []}
        order.append(group_id)

    if not groups_by_id:
        return []

    for item in items:
        if not isinstance(item, dict):
            continue
        if _int_value(item.get("podcast_group_flag")) == 256:
            continue
        ref = _int_value(item.get("group_id_ref") or item.get("podcast_group_ref"))
        target = groups_by_id.get(ref)
        if target is None:
            ungrouped.append(item)
            continue
        target_items = target["items"]
        if isinstance(target_items, list):
            target_items.append(item)

    if ungrouped:
        groups_by_id[0] = {"group_id": 0, "title": "Ungrouped", "items": ungrouped}
        order.append(0)

    summaries: list[dict[str, object]] = []
    track_id_index = track_id_index or {}
    for group_id in order:
        group = groups_by_id[group_id]
        group_items = group.get("items", [])
        if not isinstance(group_items, list):
            continue
        titles: list[str] = []
        for item in group_items:
            track = track_id_index.get(_int_value(item.get("track_id")))
            title = str((track or {}).get("Title") or item.get("Title") or "").strip()
            if title:
                titles.append(title)
        summaries.append({
            "group_id": group_id,
            "title": group["title"],
            "count": len(group_items),
            "preview_titles": titles[:3],
        })
    return summaries


class _CompressibleScrollArea(QScrollArea):
    """A scroll area that does not force its contents into splitter minima."""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def sizeHint(self) -> QSize:
        return QSize(0, 72)


class _CurrentPageStack(QStackedWidget):
    """Report size hints from the visible page, not every stacked page."""

    def __init__(self) -> None:
        super().__init__()
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def minimumSizeHint(self) -> QSize:
        widget = self.currentWidget()
        if widget is None:
            return QSize(0, 0)
        return widget.minimumSizeHint()

    def sizeHint(self) -> QSize:
        widget = self.currentWidget()
        if widget is None:
            return QSize(0, 0)
        return widget.sizeHint()


def _make_compressible_scroll_area() -> _CompressibleScrollArea:
    scroll = _CompressibleScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    scroll.setMinimumHeight(0)

    palette = scroll.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
    palette.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
    scroll.setPalette(palette)
    viewport = scroll.viewport()
    if viewport is not None:
        viewport.setPalette(palette)
        viewport.setAutoFillBackground(False)

    return scroll


# =============================================================================
# PlaylistInfoCard — right-hand info panel above the track list
# =============================================================================

class PlaylistInfoCard(QFrame):
    """Displays detailed metadata about the selected playlist."""

    def __init__(self):
        super().__init__()
        self.setObjectName("playlistInfoCard")
        self.setStyleSheet(panel_css(
            "playlistInfoCard",
            radius=Metrics.BORDER_RADIUS_LG,
        ))
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)

        # ── Identity + actions ─────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)

        self.title_label = QLabel("Select a playlist")
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        self.title_label.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        self.title_label.setWordWrap(True)
        title_col.addWidget(self.title_label)

        self.description_label = QLabel("")
        self.description_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.description_label.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        self.description_label.setWordWrap(True)
        self.description_label.hide()
        title_col.addWidget(self.description_label)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(6)

        self.type_label = QLabel("")
        self.type_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        self.type_label.setStyleSheet(_subtle_label_css(Colors.TEXT_SECONDARY))
        self.type_label.hide()
        meta_row.addWidget(self.type_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._source_label = QLabel("")
        self._source_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self._source_label.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
        meta_row.addWidget(self._source_label, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addStretch()
        title_col.addLayout(meta_row)
        header.addLayout(title_col, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _ed_ic = glyph_icon("edit", (14), Colors.TEXT_SECONDARY)
        if _ed_ic:
            self.edit_btn.setIcon(_ed_ic)
            self.edit_btn.setIconSize(QSize((14), (14)))
        self.edit_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_HOVER,
            bg_press=Colors.SURFACE_ACTIVE,
            fg=Colors.TEXT_SECONDARY,
            border=f"1px solid {Colors.BORDER}",
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
        _eval_ic = glyph_icon("check-circle", (14), Colors.TEXT_SECONDARY)
        if _eval_ic:
            self.evaluate_btn.setIcon(_eval_ic)
            self.evaluate_btn.setIconSize(QSize((14), (14)))
        self.evaluate_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_HOVER,
            bg_press=Colors.SURFACE_ACTIVE,
            fg=Colors.TEXT_SECONDARY,
            border=f"1px solid {Colors.BORDER}",
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

        header.addLayout(btn_row)
        self._layout.addLayout(header)

        # ── Separator ──────────────────────────────────────────
        self._layout.addWidget(make_separator())

        # ── At-a-glance metrics ─────────────────────────────────
        self._metrics_row = QHBoxLayout()
        self._metrics_row.setContentsMargins(0, 0, 0, 0)
        self._metrics_row.setSpacing(16)
        self._track_metric = self._add_metric("Tracks")
        self._duration_metric = self._add_metric("Duration")
        self._size_metric = self._add_metric("Size")
        self._sort_metric = self._add_metric("Sort")
        self._metrics_row.addStretch()
        self._layout.addLayout(self._metrics_row)

        # Retained as a public-ish attribute for compatibility with older code paths.
        self.stats_label = QLabel("")
        self.stats_label.hide()

        self._rules_panel = QFrame()
        self._rules_panel.setMinimumHeight(0)
        self._rules_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._rules_panel.setStyleSheet(
            f"background: {Colors.SURFACE_ALT};"
            f"border: 1px solid {Colors.BORDER_SUBTLE};"
            f"border-radius: {Metrics.BORDER_RADIUS_SM}px;"
        )
        rules_panel_layout = QVBoxLayout(self._rules_panel)
        rules_panel_layout.setContentsMargins(10, 8, 10, 9)
        rules_panel_layout.setSpacing(6)

        rules_header = QHBoxLayout()
        rules_header.setContentsMargins(0, 0, 0, 0)
        rules_header.setSpacing(8)
        rules_title = QLabel("Rules")
        rules_title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        rules_title.setStyleSheet(_subtle_label_css(Colors.TEXT_SECONDARY))
        rules_header.addWidget(rules_title)

        self._rules_summary_label = QLabel("")
        self._rules_summary_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self._rules_summary_label.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
        rules_header.addWidget(self._rules_summary_label, 1)
        rules_panel_layout.addLayout(rules_header)

        self._rules_preview_layout = QVBoxLayout()
        self._rules_preview_layout.setContentsMargins(0, 0, 0, 0)
        self._rules_preview_layout.setSpacing(4)
        rules_panel_layout.addLayout(self._rules_preview_layout)
        self._layout.addWidget(self._rules_panel)
        self._rules_panel.hide()
        self._rules_preview_widgets: list[QWidget] = []

        # ── Details section (compressible; scrolls before it blocks the track list)
        self.details_area = _make_compressible_scroll_area()
        self.details_widget = QWidget()
        self.details_widget.setStyleSheet("background: transparent; border: none;")
        details_outer_layout = QVBoxLayout(self.details_widget)
        details_outer_layout.setContentsMargins(0, 0, 0, 0)
        details_outer_layout.setSpacing(7)
        details_outer_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        details_header_widget = QWidget(self.details_widget)
        details_header_widget.setStyleSheet("background: transparent; border: none;")
        details_header = QHBoxLayout(details_header_widget)
        details_header.setContentsMargins(0, 0, 0, 0)
        details_header.setSpacing(8)
        details_label = QLabel("Details", details_header_widget)
        details_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        details_label.setStyleSheet(_subtle_label_css(Colors.TEXT_SECONDARY))
        details_header.addWidget(details_label)
        details_header.addWidget(make_separator(), 1)
        details_outer_layout.addWidget(details_header_widget)

        self._details_rows = QWidget(self.details_widget)
        self._details_rows.setStyleSheet("background: transparent; border: none;")
        self.details_layout = QVBoxLayout(self._details_rows)
        self.details_layout.setContentsMargins(0, 0, 0, 0)
        self.details_layout.setSpacing(3)
        self.details_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        details_outer_layout.addWidget(self._details_rows)
        self.details_area.setWidget(self.details_widget)
        self._layout.addWidget(self.details_area, 1)

        self._detail_labels: list[QWidget] = []
        self._current_playlist: dict | None = None

    def _add_metric(self, label: str) -> QLabel:
        group = QVBoxLayout()
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(2)

        label_widget = QLabel(label)
        label_widget.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        label_widget.setStyleSheet(_subtle_label_css(Colors.TEXT_SECONDARY))
        group.addWidget(label_widget)

        value_widget = QLabel("—")
        value_widget.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        value_widget.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        value_widget.setMinimumWidth(72)
        group.addWidget(value_widget)

        self._metrics_row.addLayout(group)
        return value_widget

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def showPlaylist(
        self,
        playlist: dict,
        resolved_tracks: list[dict],
        track_id_index: dict[int, dict] | None = None,
    ) -> None:
        """Populate the card with data from a parsed playlist dict."""
        self._clear_details()

        title = playlist.get("Title", "Untitled")
        is_master = bool(playlist.get("master_flag"))
        is_smart = _is_user_smart_playlist(playlist)
        is_podcast = playlist.get("podcast_flag", 0) == 1
        is_category = _is_ipod_category_playlist(playlist)
        source = "category" if is_category else playlist.get("_source", "regular")

        # ── Title ──
        self.title_label.setText(title)
        description = playlist_description_from_row(playlist)
        self.description_label.setText(description)
        self.description_label.setVisible(bool(description))

        # ── Type badge ──
        origin_label = _mhsd_type_label(playlist)
        if _is_display_merged_playlist(playlist):
            self.type_label.setText(f"{origin_label} Playlist")
        elif is_category:
            self.type_label.setText(f"{origin_label} Internal Browsing Category")
        elif is_master:
            self.type_label.setText(f"{origin_label} Master Library Playlist")
        elif is_smart:
            self.type_label.setText(f"{origin_label} Smart Playlist")
        else:
            self.type_label.setText(f"{origin_label} Regular Playlist")
        self.type_label.show()
        self._source_label.setText(
            self._source_summary(source, is_master, is_category, playlist)
        )

        # Display-merged rows are editable as one logical playlist; cache saves
        # fan out to each represented MHSD row.
        editable = (
            not is_master
            and not is_category
            and (_is_display_merged_playlist(playlist) or not is_podcast)
        )
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
        self._populate_podcast_grouping(playlist, track_id_index)
        self._populate_smart_rules_preview(playlist, is_smart)

        self.details_layout.addStretch()

    def _source_summary(
        self,
        source: str,
        is_master: bool,
        is_category: bool,
        playlist: dict,
    ) -> str:
        dataset_label = _mhsd_type_label(playlist)
        if _is_display_merged_playlist(playlist):
            return f"{dataset_label} rows with the same playlist ID"
        if is_category:
            return f"{dataset_label} built-in browse view"
        if is_master:
            return f"{dataset_label} master playlist"
        if source == "smart":
            return f"{dataset_label} smart playlist row"
        return f"{dataset_label} playlist row"

    def _populate_smart_rules_preview(self, playlist: dict, is_smart: bool) -> None:
        self._clear_rules_preview()
        if not is_smart:
            self._rules_panel.hide()
            return

        prefs = playlist.get("smart_playlist_data")
        rules = playlist.get("smart_playlist_rules")
        rule_lines = format_smart_rules_summary(rules, prefs)
        if not rule_lines:
            self._rules_panel.hide()
            return

        self._rules_panel.show()
        summary_parts: list[str] = []
        rule_rows: list[str] = []
        for line in rule_lines:
            text = line.strip()
            if not text:
                continue
            if text.startswith("•"):
                rule_rows.append(text.removeprefix("•").strip())
            elif text.startswith("Match "):
                summary_parts.insert(0, text)
            else:
                summary_parts.append(text)

        self._rules_summary_label.setText("  ·  ".join(summary_parts))

        if rule_rows:
            for row_text in rule_rows[:4]:
                self._add_rule_preview_row(row_text)
            extra_count = len(rule_rows) - 4
            if extra_count > 0:
                more = QLabel(f"+ {extra_count} more rule{'s' if extra_count != 1 else ''}")
                more.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
                more.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
                self._rules_preview_layout.addWidget(more)
                self._rules_preview_widgets.append(more)
        else:
            empty = QLabel("No explicit rules; this playlist is controlled by its smart preferences.")
            empty.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            empty.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
            empty.setWordWrap(True)
            self._rules_preview_layout.addWidget(empty)
            self._rules_preview_widgets.append(empty)

    def _add_rule_preview_row(self, text: str) -> None:
        row = QWidget(self._rules_panel)
        row.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        bullet_slot = QWidget(row)
        bullet_slot.setFixedWidth(5)
        bullet_slot.setStyleSheet("background: transparent; border: none;")
        bullet_layout = QVBoxLayout(bullet_slot)
        bullet_layout.setContentsMargins(0, 5, 0, 0)
        bullet_layout.setSpacing(0)

        bullet = QFrame(bullet_slot)
        bullet.setFixedSize(5, 5)
        bullet.setStyleSheet(
            f"background: {Colors.ACCENT_LIGHT};"
            "border: none;"
            "border-radius: 2px;"
        )
        bullet_layout.addWidget(bullet, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(bullet_slot, 0, Qt.AlignmentFlag.AlignTop)

        label = QLabel(text, row)
        label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        label.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        label.setWordWrap(True)
        layout.addWidget(label, 1)

        self._rules_preview_layout.addWidget(row)
        self._rules_preview_widgets.append(row)

    def _clear_rules_preview(self) -> None:
        while self._rules_preview_layout.count():
            item = self._rules_preview_layout.takeAt(0)
            widget = item.widget() if item else None
            _delete_embedded_widget(widget)
        self._rules_preview_widgets.clear()
        self._rules_summary_label.setText("")

    def _populate_stats(self, playlist: dict, resolved_tracks: list[dict], source: str) -> None:
        """Populate stats line and basic detail rows."""
        track_count = len(resolved_tracks)
        total_ms = sum(t.get("length", 0) for t in resolved_tracks)
        total_size = sum(t.get("size", 0) for t in resolved_tracks)
        sort_order = format_sort_order(playlist.get("sort_order", 0))

        self._track_metric.setText(f"{track_count:,}")
        self._duration_metric.setText(format_duration_human(total_ms) if total_ms > 0 else "—")
        self._size_metric.setText(format_size(total_size) if total_size > 0 else "—")
        self._sort_metric.setText(sort_order)

        stat_parts = [f"{track_count} tracks"]
        if total_ms > 0:
            stat_parts.append(format_duration_human(total_ms))
        if total_size > 0:
            stat_parts.append(format_size(total_size))
        self.stats_label.setText(" · ".join(stat_parts))

        details: list[tuple[str, str]] = []
        details.append(("Sort Order", sort_order))
        if description := playlist_description_from_row(playlist):
            details.append(("Description", description))

        for ts_key, label in (("timestamp", "Created"), ("timestamp_2", "Modified")):
            ts = playlist.get(ts_key, 0)
            if ts and ts > 0:
                try:
                    details.append((label, datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")))
                except (ValueError, OSError):
                    pass

        details.append(("Dataset Type", _mhsd_type_label(playlist)))
        if _is_display_merged_playlist(playlist):
            details.append((
                "Display Merge",
                "Same playlist ID represented in multiple MHSD playlist datasets",
            ))
            origins = playlist.get("_mhsd_display_origins", [])
            if isinstance(origins, list):
                for origin in origins:
                    if not isinstance(origin, dict):
                        continue
                    origin_type = _int_value(origin.get("dataset_type"))
                    origin_title = str(origin.get("title") or "").strip()
                    if origin_type:
                        details.append((
                            f"MHSD Type {origin_type}",
                            origin_title or "Untitled",
                        ))
        else:
            details.append(("Dataset Source", source))

        mhsd5 = _mhsd5_type_value(playlist)
        if mhsd5:
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
                        if k in (
                            "playlist_prefs",
                            "playlist_settings",
                            "playlist_property_plist",
                        )}
        extra_strings = {k: v for k, v in playlist.items()
                         if k.startswith("unknown_mhod_")}
        known_extra = {**extra_binary, **extra_strings}
        if not known_extra:
            return

        self._add_section_header("Extra MHOD Fields")
        for k, v in known_extra.items():
            if k == "playlist_property_plist" and isinstance(v, dict):
                raw_body = v.get("raw_body")
                if isinstance(raw_body, (bytes, bytearray)):
                    body_len = len(raw_body)
                elif isinstance(raw_body, str):
                    body_len = len(raw_body)
                else:
                    body_len = "?"
                plist = v.get("plist")
                if isinstance(plist, dict):
                    keys = ", ".join(str(key) for key in plist.keys()) or "none"
                elif "description" in v:
                    keys = "description"
                else:
                    keys = "unknown"
                display_val = f"binary plist — {body_len} bytes; keys: {keys}"
            elif isinstance(v, dict):
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

        bitrates = [
            bitrate
            for t in resolved_tracks
            if (bitrate := _int_value(t.get("bitrate"))) > 0
        ]
        if bitrates:
            avg_br = sum(bitrates) / len(bitrates)
            self._add_detail_row("Avg Bitrate", f"{avg_br:.0f} kbps")

        ratings = [
            rating
            for t in resolved_tracks
            if (rating := _int_value(t.get("rating"))) > 0
        ]
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
            self._add_detail_row("File Formats", ft_str)

        years = [
            year
            for t in resolved_tracks
            if (year := _int_value(t.get("year"))) > 0
        ]
        if years:
            min_y, max_y = min(years), max(years)
            yr_str = str(min_y) if min_y == max_y else f"{min_y}–{max_y}"
            self._add_detail_row("Year Range", yr_str)

    def _populate_podcast_grouping(
        self,
        playlist: dict,
        track_id_index: dict[int, dict] | None,
    ) -> None:
        """Show parsed MHSD-3 podcast group headers and item links."""
        groups = _podcast_grouping_summary(playlist, track_id_index)
        if not groups:
            return

        self._add_section_header("Podcast Grouping")
        total_items = sum(_int_value(group.get("count")) for group in groups)
        self._add_detail_row("Group Headers", str(len(groups)))
        self._add_detail_row("Linked Episodes", str(total_items))
        for group in groups[:6]:
            count = _int_value(group.get("count"))
            label = f"{group.get('title', 'Group')} ({count})"
            group_id = _int_value(group.get("group_id"))
            if group_id:
                label = f"{label}  id={group_id}"
            self._add_detail_text(label)
            preview_titles = group.get("preview_titles", [])
            if isinstance(preview_titles, list) and preview_titles:
                self._add_detail_text("  " + ", ".join(str(t) for t in preview_titles))
        extra = len(groups) - 6
        if extra > 0:
            self._add_detail_text(f"+ {extra} more group{'s' if extra != 1 else ''}")

    def showEmpty(self) -> None:
        """Show default empty state."""
        self._clear_details()
        self._clear_rules_preview()
        self._rules_panel.hide()
        self.title_label.setText("Select a playlist")
        self.description_label.setText("")
        self.description_label.hide()
        self.type_label.setText("")
        self.type_label.hide()
        self._source_label.setText("Choose a playlist to inspect its tracks and database metadata")
        self.stats_label.setText("")
        for metric in (self._track_metric, self._duration_metric, self._size_metric, self._sort_metric):
            metric.setText("—")
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
            _delete_embedded_widget(lbl)
        self._detail_labels.clear()
        # Remove stretch
        while self.details_layout.count():
            item = self.details_layout.takeAt(0)
            w = item.widget() if item else None
            _delete_embedded_widget(w)

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

        lbl = QLabel(text.upper())
        lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
            f" border: none; padding-top: {(6)}px;"
            f" letter-spacing: 1.2px;"
        )
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

        self._buttons: list[SidebarNavButton] = []
        self._button_icons: dict[int, str] = {}  # button index -> icon name
        self._selected_btn: SidebarNavButton | None = None
        self._playlist_map: dict[int, dict] = {}  # button index -> playlist dict

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def loadPlaylists(self, playlists: list[dict]) -> None:
        """Populate the panel with playlists grouped by type."""
        self._clear()

        # Categorize by playlist contents. MHSD location is shown separately as
        # type metadata, and type 5 rows with category markers are internal
        # browsing categories.
        regular: list[dict] = []
        smart: list[dict] = []
        podcast: list[dict] = []
        category: list[dict] = []
        master: dict | None = None

        for pl in playlists:
            if _is_ipod_category_playlist(pl):
                category.append(pl)
            elif pl.get("master_flag"):
                master = pl
            elif pl.get("podcast_flag", 0) == 1:
                podcast.append(pl)
            elif _is_user_smart_playlist(pl):
                smart.append(pl)
            else:
                regular.append(pl)

        # Build sections
        if regular:
            self._add_section("REGULAR PLAYLISTS")
            for pl in regular:
                self._add_playlist_button(pl, _ICON_REGULAR)

        if smart:
            self._add_section("SMART PLAYLISTS")
            for pl in smart:
                self._add_playlist_button(pl, _ICON_SMART)

        if podcast:
            self._add_section("PODCAST PLAYLISTS")
            for pl in podcast:
                self._add_playlist_button(pl, _ICON_PODCAST)

        if category:
            self._add_section("INTERNAL BROWSE CATEGORIES")
            for pl in category:
                self._add_playlist_button(pl, _ICON_CATEGORY, dimmed=True)

        # Master at bottom, dimmed
        if master:
            self._add_section("LIBRARY")
            self._add_playlist_button(master, _ICON_MASTER, dimmed=True)

        # Empty state
        if not regular and not smart and not podcast and not category and master is None:
            empty_container = QWidget()
            empty_container.setStyleSheet("background: transparent; border: none;")
            empty_vbox = QVBoxLayout(empty_container)
            empty_vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_vbox.setSpacing(8)

            empty_icon = QLabel()
            _px = glyph_pixmap("playlist", Metrics.FONT_ICON_LG, Colors.TEXT_TERTIARY)
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

    def selectPlaylistById(
        self, playlist_id: int, dataset_type: int | None = None
    ) -> bool:
        """Select a playlist by ID and, when known, its source MHSD dataset."""
        for index, playlist in self._playlist_map.items():
            if _int_value(playlist.get("playlist_id")) == playlist_id:
                if (
                    dataset_type is not None
                    and _playlist_dataset_type(playlist) != dataset_type
                ):
                    continue
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
            _delete_embedded_widget(w)

    def _add_section(self, text: str) -> None:
        if not text:
            spacer = QWidget()
            spacer.setFixedHeight(8)
            spacer.setStyleSheet("background: transparent; border: none;")
            self._inner_layout.addWidget(spacer)
            return
        lbl = make_sidebar_section_header(text)
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

        btn = SidebarNavButton(btn_text, icon_name=icon_name)
        btn.setToolTip(f"{title}\n{count} tracks\n{_mhsd_type_label(playlist)}")
        btn.setDimmed(dimmed)

        idx = len(self._buttons)
        self._playlist_map[idx] = playlist
        self._button_icons[idx] = icon_name
        btn.clicked.connect(lambda checked, i=idx: self._on_click(i))

        self._inner_layout.addWidget(btn)
        self._buttons.append(btn)

    def _on_click(self, index: int) -> None:
        # Reset previous selection
        if self._selected_btn is not None:
            self._selected_btn.setSelected(False)

        # Highlight new selection
        btn = self._buttons[index]
        btn.setSelected(True)
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

    track_activated = pyqtSignal(dict)
    playback_requested = pyqtSignal(dict, list, int)

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
        self._topStack = _CurrentPageStack()
        self._topStack.setMinimumHeight(0)
        self._topStack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

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
        self._import_progress_bar.setStyleSheet(progress_bar_css(
            chunk=(
                "qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                f"stop:0 {Colors.ACCENT}, stop:1 {Colors.ACCENT_LIGHT})"
            )
        ))
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
            show_search_bar=False,
        )
        self.trackTitleBar.search_changed.connect(self.trackList.setSearchQuery)
        self.trackList.search_query_changed.connect(self.trackTitleBar.setSearchQuery)
        self.trackList.setMinimumHeight(0)
        self.trackList.setMinimumWidth(0)
        self.trackList.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.trackList.minimumSizeHint = lambda: QSize(0, 0)
        self.trackList.track_activated.connect(self.track_activated.emit)
        self.trackList.playback_requested.connect(self.playback_requested.emit)
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

    def _set_empty_regular_playlist_notice(
        self,
        _playlist: dict | None,
        _track_count: int,
    ) -> None:
        return

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def loadPlaylists(self) -> None:
        """Load playlists from iTunesDBCache and populate the list panel."""
        cache = self._library_cache
        if not cache.is_ready():
            return

        playlists = display_playlists_from_rows(cache.get_playlists())
        signature = self._compute_playlist_signature(playlists)
        if signature == self._playlist_signature:
            return

        self.listPanel.loadPlaylists(playlists)
        self._playlist_signature = signature
        self._switchToBrowse()
        self.infoCard.showEmpty()
        self.trackList.clearTable()
        self._set_empty_regular_playlist_notice(None, 0)
        self.trackTitleBar.setTitle("Select a playlist")
        self.trackTitleBar.resetColor()
        self._current_playlist = None

    def refreshFromCache(self) -> None:
        """Refresh playlist UI from cache while preserving the current selection."""
        cache = self._library_cache
        if not cache.is_ready():
            return

        playlists = display_playlists_from_rows(cache.get_playlists())
        signature = self._compute_playlist_signature(playlists)
        current_pid = _int_value((self._current_playlist or {}).get("playlist_id"))
        current_dataset = (
            _playlist_dataset_type(self._current_playlist)
            if self._current_playlist and not _is_display_merged_playlist(self._current_playlist)
            else None
        )

        if signature != self._playlist_signature:
            self.listPanel.loadPlaylists(playlists)
            self._playlist_signature = signature

        if current_pid:
            if self.listPanel.selectPlaylistById(current_pid, current_dataset):
                return

    def clear(self) -> None:
        """Clear everything when device changes."""
        self._switchToBrowse()
        self.listPanel.clear()
        self.infoCard.showEmpty()
        self.trackList.clearTable(clear_cache=True)
        self._set_empty_regular_playlist_notice(None, 0)
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
                    _int_value(pl.get("playlist_id")),
                    str(pl.get("Title", "")),
                    _int_value(pl.get("mhip_child_count")),
                    _int_value(pl.get("master_flag")),
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
        self._set_empty_regular_playlist_notice(None, 0)
        current_page = self._topStack.currentWidget()
        min_height = current_page.minimumSizeHint().height() if current_page else 0
        self._topStack.setMinimumHeight(max(360, min_height))
        self.rightSplitter.setCollapsible(0, False)
        # Give the editor more room
        self.rightSplitter.setSizes([450, 400])

    def _switchToBrowse(self) -> None:
        """Show the info card (default view)."""
        self._topStack.setCurrentIndex(0)
        self._editing = False
        self._topStack.setMinimumHeight(0)
        self.rightSplitter.setCollapsible(0, True)
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
            self._set_empty_regular_playlist_notice(None, 0)
            return

        track_id_index = cache.get_track_id_index()

        # Resolve track IDs from MHIP items
        items = playlist.get("items", [])
        track_ids = [item.get("track_id", 0) for item in items]
        resolved_tracks = [track_id_index[tid] for tid in track_ids if tid in track_id_index]

        # Update info card
        self.infoCard.showPlaylist(playlist, resolved_tracks, track_id_index)

        # Update title bar
        title = playlist.get("Title", "Untitled")
        if playlist.get("master_flag") and not _is_ipod_category_playlist(playlist):
            title = "Library (Master)"
        self.trackTitleBar.setTitle(title)

        # Color the title bar based on playlist type
        if _is_ipod_category_playlist(playlist):
            self.trackTitleBar.resetColor()
        elif _is_user_smart_playlist(playlist):
            self.trackTitleBar.setColor(*Colors.PLAYLIST_SMART)
        elif playlist.get("podcast_flag", 0) == 1:
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
        self._set_empty_regular_playlist_notice(playlist, len(resolved_tracks))

    def _onNewPlaylist(self, kind: str) -> None:
        """Handle the 'New Playlist' button from the list panel."""
        if kind == "smart":
            self.editor.set_playlist_options(
                display_playlists_from_rows(self._library_cache.get_playlists())
            )
            self.editor.new_playlist()
            self._switchToEditor(1)
            self.trackTitleBar.setTitle("New Smart Playlist")
            self.trackTitleBar.setColor(*Colors.PLAYLIST_SMART)
            self.trackList.clearTable()
            self._set_empty_regular_playlist_notice(None, 0)
        else:
            self.regularEditor.new_playlist()
            self._switchToEditor(2)
            self.trackTitleBar.setTitle("New Playlist")
            self.trackTitleBar.resetColor()
            self.trackList.clearTable()
            self._set_empty_regular_playlist_notice(None, 0)

    def _onEditClicked(self) -> None:
        """Handle the Edit button on the info card."""
        if not self._current_playlist:
            return
        if _is_ipod_category_playlist(self._current_playlist):
            return
        if _is_user_smart_playlist(self._current_playlist):
            self.editor.set_playlist_options(
                display_playlists_from_rows(self._library_cache.get_playlists())
            )
            self.editor.edit_playlist(self._current_playlist)
            self._switchToEditor(1)
        elif not self._current_playlist.get("master_flag"):
            self.regularEditor.edit_playlist(self._current_playlist)
            self._switchToEditor(2)

    def _onDeleteClicked(self) -> None:
        """Handle the Delete button — confirm, remove from cache, rewrite DB."""
        playlist = self._current_playlist
        if not playlist or playlist.get("master_flag") or _is_ipod_category_playlist(playlist):
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
        if _is_user_smart_playlist(playlist_data):
            self.trackTitleBar.setColor(*Colors.PLAYLIST_SMART)
            self._set_empty_regular_playlist_notice(None, 0)
        else:
            self.trackTitleBar.resetColor()
            self._set_empty_regular_playlist_notice(playlist_data, 0)

        log.info("Playlist saved to cache: '%s' (id=0x%X)",
                 title, playlist_data.get("playlist_id", 0))

        # ── Write to iPod immediately ──
        self._writePlaylistToIPod(playlist_data)

    def _refreshList(self) -> None:
        """Reload the playlist list from cache."""
        cache = self._library_cache
        if cache.is_ready():
            playlists = display_playlists_from_rows(cache.get_playlists())
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

        dataset_type = None if _is_display_merged_playlist(playlist) else _playlist_dataset_type(playlist)
        cache.remove_user_playlist(pid, dataset_type)

        # Disable buttons during write
        self.infoCard.edit_btn.setEnabled(False)
        self.infoCard.delete_btn.setEnabled(False)
        self.infoCard.evaluate_btn.setEnabled(False)

        device = self._device_sessions.current_session()
        self._delete_worker = _PlaylistDeleteWorker(
            playlist,
            device.device_path or "",
            self._library_cache,
            device_storage=device.storage,
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
        self._set_empty_regular_playlist_notice(None, 0)
        self.trackTitleBar.setTitle("Select a playlist")
        self.trackTitleBar.resetColor()

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

        device = self._device_sessions.current_session()
        self._eval_worker = _PlaylistWriteWorker(
            playlist,
            device.device_path or "",
            self._library_cache,
            device_storage=device.storage,
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
        if not _is_user_smart_playlist(self._current_playlist):
            self.infoCard.evaluate_btn.setVisible(False)

        is_smart = _is_user_smart_playlist(self._current_playlist)

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

    def _onWriteFailed(self, error_msg: str) -> None:
        """Playlist write failed."""
        self.infoCard.edit_btn.setEnabled(True)
        self.infoCard.evaluate_btn.setEnabled(True)
        self.infoCard.evaluate_btn.setText("Evaluate Now")
        if not _is_user_smart_playlist(self._current_playlist):
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
        if not playlist or not _is_user_smart_playlist(playlist):
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
                from iopenpod.sync.ipod_track_paths import expected_ipod_track_file_path

                resolved = expected_ipod_track_file_path(ipod_root, location)
                if resolved is not None:
                    return str(resolved)
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
            device_storage=device.storage,
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
            duration_s = _int_value(track.get("length")) // 1000
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
            duration_s = _int_value(track.get("length")) // 1000
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
