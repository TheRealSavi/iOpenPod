"""Podcast browser — two-panel widget for managing podcast subscriptions.

Layout:
    ┌──────────────────────────────────────────────────────────────┐
    │  Toolbar: [Add Podcast] [Refresh All]             status    │
    ├─────────────────┬────────────────────────────────────────────┤
    │  Feed list      │  Feed header (artwork · title · meta)     │
    │  (left panel)   ├────────────────────────────────────────────┤
    │  ┌───────────┐  │  Episode table (row-select, right-click)  │
    │  │ ▍art Feed │  │   Title        Duration   Date   Status   │
    │  │ ▍art Feed │  │                                           │
    │  └───────────┘  ├────────────────────────────────────────────┤
    │                 │  Action bar: [Add to iPod]                 │
    └─────────────────┴────────────────────────────────────────────┘

    When no feeds exist, a full-page empty state with a prominent CTA
    replaces the splitter.

Select episodes → click "Add to iPod" → automatic download + sync.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..glyphs import glyph_icon, glyph_pixmap
from ..hidpi import scale_pixmap_for_display
from ..styles import (
    FONT_FAMILY,
    LABEL_SECONDARY,
    Colors,
    Metrics,
    accent_btn_css,
    btn_css,
    combo_css,
    make_label,
    make_separator,
)
from .browserChrome import (
    BrowserHeroHeader,
    BrowserPane,
    chrome_action_btn_css,
    style_browser_splitter,
)
from .formatters import format_size

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app_core.services import (
        DeviceSessionService,
        LibraryCacheLike,
        LibraryService,
        SettingsService,
    )


# ── Column definitions ───────────────────────────────────────────────────────
_COL_TITLE = 0
_COL_DURATION = 1
_COL_DATE = 2
_COL_STATUS = 3
_COL_COUNT = 4


def _fmt_duration(seconds: int) -> str:
    """Compact H:MM:SS or M:SS for episode durations."""
    if not seconds or seconds <= 0:
        return ""
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_date(ts: float) -> str:
    if not ts or ts <= 0:
        return ""
    from datetime import datetime
    try:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
    except (OSError, ValueError):
        return ""


# ── Podcast episode list ─────────────────────────────────────────────────────

_PODCAST_EPISODE_COLUMNS = ["Title", "ep_status", "length", "date_added", "size"]


def _is_remote_artwork_source(source: str) -> bool:
    parsed = urlparse(str(source or "").strip())
    return parsed.scheme.lower() in {"http", "https"}


def _resolve_local_artwork_path(source: str) -> Path | None:
    text = str(source or "").strip()
    if not text:
        return None

    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https"}:
        return None

    if scheme == "file":
        path_text = unquote(parsed.path or "")
        if (
            os.name == "nt"
            and path_text.startswith("/")
            and len(path_text) > 2
            and path_text[2] == ":"
        ):
            path_text = path_text[1:]
        if parsed.netloc and parsed.netloc.lower() != "localhost" and path_text:
            if os.name == "nt":
                return Path("\\\\" + parsed.netloc + path_text.replace("/", "\\"))
            return Path("//" + parsed.netloc + path_text)
        return Path(path_text)

    if re.match(r"^[a-zA-Z]:[\\/]", text):
        return Path(text)

    if text.startswith("\\\\") or text.startswith("//"):
        return Path(text)

    return Path(text)


def _read_local_artwork_bytes(source: str) -> bytes | None:
    path = _resolve_local_artwork_path(source)
    if path is None:
        return None
    try:
        if not path.exists() or not path.is_file():
            return b""
        return path.read_bytes()
    except OSError:
        return b""


def _load_artwork_bytes(source: str) -> bytes | None:
    local_bytes = _read_local_artwork_bytes(source)
    if local_bytes is not None:
        return local_bytes or None

    if not _is_remote_artwork_source(source):
        return None

    import requests

    resp = requests.get(
        source,
        timeout=10,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    resp.raise_for_status()
    return resp.content or None


def _colorize_ep_status(bl) -> None:
    """Apply per-row colors to the ep_status column after population."""
    if "ep_status" not in bl._columns:
        return
    col_idx = bl._columns.index("ep_status")
    t = bl.table
    for row in range(t.rowCount()):
        item = t.item(row, col_idx)
        if not item:
            continue
        text = item.text()
        if text == "On iPod":
            item.setForeground(QColor(Colors.SUCCESS))
        elif text == "Downloaded":
            item.setForeground(QColor(Colors.ACCENT))
        elif "Downloading" in text:
            item.setForeground(QColor(Colors.WARNING))


class _PodcastEpisodeList:
    """Adapts MusicBrowserList for podcast episode display."""

    @staticmethod
    def create(owner: PodcastBrowser):
        from .MBListView import COLUMN_CONFIG, MusicBrowserList

        # Register the podcast-only status column if not already present
        COLUMN_CONFIG.setdefault("ep_status", ("Status", None))

        bl = MusicBrowserList(
            settings_service=owner._settings_service,
            device_sessions=owner._device_sessions,
            library_cache=owner._library_cache,
            show_art_override=False,
            content_type_override="podcast_episodes",
        )

        # Override the music-library defaults with podcast-appropriate columns
        bl._columns = _PODCAST_EPISODE_COLUMNS.copy()

        # Row-based multi-selection; no drag
        bl.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        bl.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        bl.table.setDragEnabled(False)

        # Replace iPod track context menu with episode context menu
        try:
            bl.table.customContextMenuRequested.disconnect()
        except (TypeError, RuntimeError):
            pass
        bl.table.customContextMenuRequested.connect(owner._on_episode_context_menu)

        _orig_finish = bl._finish_population

        def _patched_finish():
            _orig_finish()
            _colorize_ep_status(bl)

        bl._finish_population = _patched_finish

        return bl


# ── Feed artwork cache ───────────────────────────────────────────────────────
# Maps artwork source path/URL → QPixmap so that repeated list refreshes don't re-download.
_artwork_cache: dict[str, QPixmap] = {}
_artwork_color_cache: dict[str, tuple[int, int, int]] = {}


class PodcastBrowser(QFrame):
    """Full podcast management widget.

    Must be initialised with ``set_device(serial, ipod_path)`` before use.
    """

    # Emitted when the user confirms podcast sync — carries a SyncPlan
    podcast_sync_requested = pyqtSignal(object)

    def __init__(
        self,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
        libraries: LibraryService,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._library_cache: LibraryCacheLike = libraries.cache()
        self._device_serial: str = ""
        self._ipod_path: str = ""
        self._store = None          # SubscriptionStore (lazy)
        self._selected_feed = None  # Current PodcastFeed
        self._deferred_reconcile_tracks: list[dict] | None = None
        self._episode_by_guid: dict[str, object] = {}
        self._episode_dicts: list[dict] = []
        self._artwork_inflight: dict[str, list[Callable[[str, QPixmap], None]]] = {}

        self._build_ui()

    def _current_ipod_tracks(self) -> list[dict] | None:
        try:
            if not self._library_cache.is_ready():
                return None
            return self._library_cache.get_tracks() or []
        except Exception:
            return None

    # ── Public API ───────────────────────────────────────────────────────

    def set_device(self, serial: str, ipod_path: str) -> None:
        """Bind to a specific iPod device.  Loads subscriptions."""
        normalized_serial = serial or "_default"
        normalized_path = ipod_path or ""
        same_device = (
            self._store is not None
            and self._device_serial == normalized_serial
            and self._ipod_path == normalized_path
        )

        # Fast path for tab switches: avoid rebuilding store + list when the
        # selected iPod has not changed.
        if same_device:
            if self._deferred_reconcile_tracks is not None:
                deferred = self._deferred_reconcile_tracks
                self._deferred_reconcile_tracks = None
                self.reconcile_ipod_statuses(deferred)
            return

        self._device_serial = normalized_serial
        self._ipod_path = normalized_path

        from PodcastManager.subscription_store import SubscriptionStore
        settings = self._settings_service.get_effective_settings()
        self._store = SubscriptionStore(
            ipod_path,
            download_cache_dir=settings.transcode_cache_dir,
        )
        self._store.load()

        # Apply any deferred reconciliation captured before the Podcasts
        # view/store was initialized (e.g. app.py data-ready timing).
        if self._deferred_reconcile_tracks is not None:
            deferred = self._deferred_reconcile_tracks
            self._deferred_reconcile_tracks = None
            self.reconcile_ipod_statuses(deferred)
        else:
            self.reconcile_ipod_statuses()

        self._refresh_feed_list()

        # Eagerly refresh all feeds from RSS so the full episode catalog
        # is available (the store only persists on-iPod/downloaded episodes).
        if self._store.get_feeds():
            self._refresh_all_feeds_bg()

    def clear(self) -> None:
        """Reset all state (called on device change)."""
        global _artwork_cache, _artwork_color_cache
        _artwork_cache.clear()
        _artwork_color_cache.clear()
        self._artwork_inflight.clear()

        self._store = None
        self._selected_feed = None
        self._deferred_reconcile_tracks = None
        self._episode_by_guid.clear()
        if hasattr(self, '_session_refreshed'):
            self._session_refreshed.clear()
        self._feed_list.clear()
        self._episode_list.table.setRowCount(0)
        self._episode_dicts = []
        self._status_label.setText("")
        self._stack.setCurrentIndex(0)

    def reconcile_ipod_statuses(self, ipod_tracks: list[dict] | None = None) -> None:
        """Reconcile stored episode state with the current iPod track list.

        This keeps "Downloaded" / "On iPod" statuses accurate even when
        feeds are loaded after iTunesDB parsing or tracks were removed.
        """
        if not self._store:
            # Store tracks for later reconciliation when set_device() creates
            # the SubscriptionStore after the Podcasts tab is opened.
            if ipod_tracks is not None:
                self._deferred_reconcile_tracks = list(ipod_tracks)
            return

        if ipod_tracks is None:
            current_tracks = self._current_ipod_tracks()
            if current_tracks is None:
                return
            ipod_tracks = current_tracks

        from PodcastManager.podcast_sync import PodcastTrackMatcher

        feeds = self._store.get_feeds()
        matcher = PodcastTrackMatcher(ipod_tracks)
        changed_feeds: list = []

        for feed in feeds:
            if matcher.match_feed(feed):
                changed_feeds.append(feed)

        if changed_feeds:
            self._store.update_feeds(changed_feeds)

        if self._selected_feed:
            refreshed = self._store.get_feed(self._selected_feed.feed_url)
            if refreshed:
                self._selected_feed = refreshed

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────────
        toolbar = self._build_toolbar()
        root.addWidget(toolbar)

        # ── Stacked widget: empty state vs. main content ─────────────────
        self._stack = QStackedWidget()

        # Page 0: Empty state
        self._empty_page = self._build_empty_page()
        self._stack.addWidget(self._empty_page)

        # Page 1: Main splitter
        self._main_page = self._build_main_page()
        self._stack.addWidget(self._main_page)

        self._stack.setCurrentIndex(0)
        root.addWidget(self._stack, stretch=1)

    def _build_toolbar(self) -> QWidget:
        bar = BrowserHeroHeader("Podcasts", self)
        layout = bar.actions_layout

        self._add_btn = QPushButton("Add Podcast")
        self._add_btn.setFont(QFont(FONT_FAMILY, (Metrics.FONT_SM)))
        self._add_btn.setStyleSheet(chrome_action_btn_css())
        _add_ic = glyph_icon("plus", (14), Colors.TEXT_PRIMARY)
        if _add_ic:
            self._add_btn.setIcon(_add_ic)
            self._add_btn.setIconSize(QSize((14), (14)))
        self._add_btn.clicked.connect(self._on_search)
        layout.addWidget(self._add_btn)

        self._refresh_btn = QPushButton("Refresh All")
        self._refresh_btn.setFont(QFont(FONT_FAMILY, (Metrics.FONT_SM)))
        self._refresh_btn.setStyleSheet(chrome_action_btn_css())
        _refresh_ic = glyph_icon("refresh", (14), Colors.TEXT_PRIMARY)
        if _refresh_ic:
            self._refresh_btn.setIcon(_refresh_ic)
            self._refresh_btn.setIconSize(QSize((14), (14)))
        self._refresh_btn.clicked.connect(self._on_refresh_all)
        layout.addWidget(self._refresh_btn)

        self._sync_btn = QPushButton("Sync Podcasts")
        self._sync_btn.setFont(QFont(FONT_FAMILY, (Metrics.FONT_SM)))
        self._sync_btn.setStyleSheet(chrome_action_btn_css())
        _sync_ic = glyph_icon("refresh", (14), Colors.TEXT_PRIMARY)
        if _sync_ic:
            self._sync_btn.setIcon(_sync_ic)
            self._sync_btn.setIconSize(QSize((14), (14)))
        self._sync_btn.setToolTip(
            "Apply per-feed settings: remove listened/old episodes, "
            "fill empty slots with new episodes"
        )
        self._sync_btn.clicked.connect(self._on_sync_podcasts)
        layout.addWidget(self._sync_btn)

        layout.addStretch()

        self._status_label = make_label(
            "",
            size=(Metrics.FONT_SM),
            style=LABEL_SECONDARY(),
        )
        layout.addWidget(self._status_label)

        return bar

    def _build_empty_page(self) -> QWidget:
        """Full-page empty state shown when there are no subscriptions."""
        page = QWidget()
        page.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(page)
        layout.setContentsMargins((48), (48), (48), (48))
        layout.addStretch()

        icon_lbl = QLabel()
        _px = glyph_pixmap("broadcast", Metrics.FONT_ICON_XL, Colors.TEXT_TERTIARY)
        if _px:
            icon_lbl.setPixmap(_px)
        else:
            icon_lbl.setText("◎")
            icon_lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_XL))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        layout.addWidget(icon_lbl)

        layout.addSpacing(12)

        heading = make_label(
            "No Podcast Subscriptions",
            size=(Metrics.FONT_PAGE_TITLE),
            weight=QFont.Weight.DemiBold,
        )
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        layout.addSpacing(6)

        desc = make_label(
            "Search for podcasts or add an RSS feed to get started.\n"
            "Episodes can be downloaded and synced to your iPod.",
            size=(Metrics.FONT_LG),
            style=LABEL_SECONDARY(),
            wrap=True,
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        layout.addSpacing(16)

        cta_btn = QPushButton("Add Your First Podcast")
        cta_btn.setFont(QFont(FONT_FAMILY, (Metrics.FONT_MD), QFont.Weight.DemiBold))
        cta_btn.setStyleSheet(accent_btn_css())
        cta_btn.setFixedHeight(38)
        cta_btn.setFixedWidth(240)
        _cta_ic = glyph_icon("plus", (16), Colors.TEXT_ON_ACCENT)
        if _cta_ic:
            cta_btn.setIcon(_cta_ic)
            cta_btn.setIconSize(QSize((16), (16)))
        cta_btn.clicked.connect(self._on_search)
        layout.addWidget(cta_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        return page

    def _build_main_page(self) -> QWidget:
        """The main splitter containing feed list and episode panel."""
        splitter = QSplitter(Qt.Orientation.Horizontal)
        style_browser_splitter(splitter)

        # Left: feed list
        left = self._build_feed_panel()
        splitter.addWidget(left)

        # Right: episode table + action bar
        right = self._build_episode_panel()
        splitter.addWidget(right)

        splitter.setSizes([(240), (600)])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        return splitter

    def _build_feed_panel(self) -> QWidget:
        panel = BrowserPane(
            "Subscriptions",
            min_width=220,
            body_margins=(8, 2, 8, 8),
        )

        self._feed_list = QListWidget()
        self._feed_list.setIconSize(QSize((36), (36)))
        self._feed_list.setSpacing(2)
        self._feed_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._feed_list.customContextMenuRequested.connect(self._on_feed_context_menu)
        self._feed_list.currentRowChanged.connect(self._on_feed_selected)
        self._feed_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                padding: {(6)}px {(8)}px;
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
            }}
            QListWidget::item:selected {{
                background: {Colors.ACCENT_MUTED};
                color: {Colors.ACCENT};
            }}
            QListWidget::item:hover:!selected {{
                background: {Colors.SURFACE_ACTIVE};
            }}
        """)

        panel.addWidget(self._feed_list, 1)
        return panel

    def _build_episode_panel(self) -> QWidget:
        panel = QWidget()

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Feed hero header ─────────────────────────────────────────────
        self._feed_header = QFrame()
        self._feed_header.setObjectName("heroHeader")
        self._feed_header.setMaximumHeight(375)
        self._feed_header.setStyleSheet(f"""
            QFrame#heroHeader {{
                background: {Colors.BG_DARK};
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)

        hdr_layout = QVBoxLayout(self._feed_header)
        hdr_layout.setContentsMargins(0, 0, 0, 0)
        hdr_layout.setSpacing(0)

        # Main hero body: art left, info right
        hero_body = QFrame()
        hero_body.setStyleSheet("background: transparent; border: none;")
        body_lay = QHBoxLayout(hero_body)
        body_lay.setContentsMargins(24, 16, 24, 16)
        body_lay.setSpacing(20)

        art_size = 120
        self._feed_art = QLabel()
        self._feed_art.setFixedSize(art_size, art_size)
        self._feed_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._feed_art.setStyleSheet(f"""
            background: {Colors.SURFACE};
            border-radius: {Metrics.BORDER_RADIUS}px;
            border: 1px solid {Colors.BORDER_SUBTLE};
        """)
        self._set_feed_art_placeholder()
        body_lay.addWidget(self._feed_art, 0, Qt.AlignmentFlag.AlignTop)

        # Info column
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 4, 0, 0)
        info_col.setSpacing(4)

        self._feed_title_label = make_label(
            "Select a podcast",
            size=Metrics.FONT_PAGE_TITLE,
            weight=QFont.Weight.DemiBold,
        )
        self._feed_title_label.setWordWrap(True)
        info_col.addWidget(self._feed_title_label)

        self._feed_author_label = make_label(
            "",
            size=Metrics.FONT_MD,
            style=LABEL_SECONDARY(),
        )
        self._feed_author_label.setWordWrap(True)
        info_col.addWidget(self._feed_author_label)

        self._feed_description_label = make_label(
            "",
            size=Metrics.FONT_SM,
            style=LABEL_SECONDARY(),
            wrap=True,
        )
        self._feed_description_label.setMaximumHeight(44)
        info_col.addWidget(self._feed_description_label)

        info_col.addSpacing(4)

        # Stats row: episodes · downloaded · on iPod
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self._feed_stat_episodes = make_label("", size=Metrics.FONT_SM,
                                              style=f"color: {Colors.TEXT_SECONDARY};")
        self._feed_stat_downloaded = make_label("", size=Metrics.FONT_SM,
                                                style=f"color: {Colors.ACCENT};")
        self._feed_stat_on_ipod = make_label("", size=Metrics.FONT_SM,
                                             style=f"color: {Colors.SUCCESS};")
        # hidden ghost label kept for _show_episodes compat
        self._feed_stat_extra = make_label("", size=Metrics.FONT_SM)
        self._feed_stat_extra.hide()

        stats_row.addWidget(self._feed_stat_episodes)
        stats_row.addWidget(self._feed_stat_downloaded)
        stats_row.addWidget(self._feed_stat_on_ipod)
        stats_row.addStretch()
        info_col.addLayout(stats_row)

        self._feed_detail_label = make_label("", size=Metrics.FONT_SM, style=LABEL_SECONDARY())
        info_col.addWidget(self._feed_detail_label)

        info_col.addStretch()
        body_lay.addLayout(info_col, 1)
        hdr_layout.addWidget(hero_body)

        self._hero_btns: list[QPushButton] = []
        self._reset_feed_hero_color()  # apply initial default styling

        # ── Per-feed settings strip ────────────────────────────────────
        hdr_layout.addWidget(make_separator())

        _lbl_css = (
            f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
        )
        _combo_style = combo_css()
        _spin_style = f"""
            QSpinBox {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 2px 6px;
            }}
            QSpinBox:hover {{
                border: 1px solid {Colors.BORDER_FOCUS};
            }}
            QSpinBox:focus {{
                border: 1px solid {Colors.BORDER_FOCUS};
            }}
        """

        def _make_setting_combo(options: list[str], width: int = 110) -> QComboBox:
            cb = QComboBox()
            cb.addItems(options)
            cb.setFixedWidth(width)
            cb.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            cb.setStyleSheet(_combo_style)
            return cb

        def _make_setting_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            lbl.setStyleSheet(_lbl_css)
            return lbl

        def _make_pair(label_text: str, control: QWidget) -> QWidget:
            """Wrap a label + control into a single flow-layout item."""
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            lay.addWidget(_make_setting_label(label_text))
            lay.addWidget(control)
            return w

        from .flowLayout import FlowLayout as _SettingsFlow
        settings_strip = QFrame()
        settings_strip.setStyleSheet("background: transparent; border: none;")
        flow = _SettingsFlow(settings_strip, spacing=12)
        flow.setContentsMargins(24, 8, 24, 10)

        self._feed_episode_slots = QSpinBox()
        self._feed_episode_slots.setRange(1, 50)
        self._feed_episode_slots.setValue(3)
        self._feed_episode_slots.setFixedWidth(60)
        self._feed_episode_slots.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._feed_episode_slots.setStyleSheet(_spin_style)

        self._feed_fill_mode = _make_setting_combo(["Newest Episode", "Next Episode"])
        self._feed_clear_method = _make_setting_combo(
            ["Remove Immediately", "Mark for Replacement"], width=140)
        self._feed_clear_listened = _make_setting_combo(["Yes", "No"], width=70)
        self._feed_clear_older = _make_setting_combo([
            "1 Day", "3 Days", "1 Week", "2 Weeks",
            "1 Month", "2 Months", "3 Months", "Never",
        ])

        flow.addWidget(_make_pair("Episodes:", self._feed_episode_slots))
        flow.addWidget(_make_pair("Fill with:", self._feed_fill_mode))
        flow.addWidget(_make_pair("Clear method:", self._feed_clear_method))
        flow.addWidget(_make_pair("Clear when listened:", self._feed_clear_listened))
        flow.addWidget(_make_pair("Clear older than:", self._feed_clear_older))

        # Connect setting changes to save handler
        self._feed_episode_slots.valueChanged.connect(self._on_feed_setting_changed)
        self._feed_fill_mode.currentTextChanged.connect(self._on_feed_setting_changed)
        self._feed_clear_listened.currentTextChanged.connect(self._on_feed_setting_changed)
        self._feed_clear_older.currentTextChanged.connect(self._on_feed_setting_changed)
        self._feed_clear_method.currentTextChanged.connect(self._on_feed_setting_changed)

        hdr_layout.addWidget(settings_strip)

        layout.addWidget(self._feed_header)

        # ── Episode list (MusicBrowserList-based) ────────────────────────
        self._episode_list = _PodcastEpisodeList.create(self)
        layout.addWidget(self._episode_list, stretch=1)

        # ── Download progress bar (hidden by default) ────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(3)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {Colors.SURFACE};
                border: none;
            }}
            QProgressBar::chunk {{
                background: {Colors.ACCENT};
                border-radius: 1px;
            }}
        """)
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)

        # ── Status toast (hidden until a message is set) ─────────────────
        self._status_toast = QFrame()
        self._status_toast.setFixedHeight(32)
        self._status_toast.setStyleSheet(
            f"background: {Colors.SURFACE_RAISED};"
            f" border-top: 1px solid {Colors.BORDER_SUBTLE};"
        )
        toast_lay = QHBoxLayout(self._status_toast)
        toast_lay.setContentsMargins(12, 0, 12, 0)
        self._action_status = make_label("", size=Metrics.FONT_SM, style=LABEL_SECONDARY())
        toast_lay.addWidget(self._action_status)
        toast_lay.addStretch()
        self._status_toast.hide()
        layout.addWidget(self._status_toast)

        return panel

    # ── Feed list management ─────────────────────────────────────────────

    def _refresh_feed_list(self) -> None:
        """Repopulate the feed list widget from the subscription store."""
        if not self._store:
            return

        self._feed_list.blockSignals(True)
        prev_url = self._selected_feed.feed_url if self._selected_feed else None
        self._feed_list.clear()

        feeds = self._store.get_feeds()

        # Show empty state or main content
        if not feeds:
            self._stack.setCurrentIndex(0)
            self._feed_list.blockSignals(False)
            self._selected_feed = None
            self._show_episodes(None)
            return
        self._stack.setCurrentIndex(1)

        select_row = -1

        for i, feed in enumerate(feeds):
            ep_count = len(feed.episodes)
            label = feed.title or "Untitled"
            item = QListWidgetItem(f"{label}  ({ep_count})")
            item.setData(Qt.ItemDataRole.UserRole, feed.feed_url)
            item.setSizeHint(QSize(0, (44)))

            # Feed artwork thumbnail in list
            artwork_source = self._feed_artwork_source(feed)
            item.setIcon(QIcon(self._artwork_placeholder_pixmap(36)))
            if artwork_source and artwork_source in _artwork_cache:
                icon_pm = scale_pixmap_for_display(
                    _artwork_cache[artwork_source],
                    36,
                    36,
                    widget=self._feed_list,
                    aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
                    transform_mode=Qt.TransformationMode.SmoothTransformation,
                )
                item.setIcon(QIcon(icon_pm))
            elif artwork_source:
                self._load_feed_list_artwork(artwork_source, i)

            self._feed_list.addItem(item)
            if feed.feed_url == prev_url:
                select_row = i

        self._feed_list.blockSignals(False)

        if select_row >= 0:
            self._feed_list.setCurrentRow(select_row)
        elif self._feed_list.count() > 0:
            self._feed_list.setCurrentRow(0)
        else:
            self._selected_feed = None
            self._show_episodes(None)

    def _on_feed_selected(self, row: int) -> None:
        if row < 0 or not self._store:
            self._selected_feed = None
            self._show_episodes(None)
            return

        item = self._feed_list.item(row)
        if not item:
            return

        feed_url = item.data(Qt.ItemDataRole.UserRole)
        self._selected_feed = self._store.get_feed(feed_url)
        self._show_episodes(self._selected_feed)

        # Auto-refresh from RSS if this feed only has persisted episodes
        # (on-iPod / downloaded) and hasn't been refreshed this session.
        if self._selected_feed and not self._is_feed_refreshed_this_session(feed_url):
            self._refresh_single_feed(self._selected_feed)

    def _is_feed_refreshed_this_session(self, feed_url: str) -> bool:
        """Check if a feed has been RSS-refreshed during this app session."""
        if not hasattr(self, '_session_refreshed'):
            self._session_refreshed: set[str] = set()
        return feed_url in self._session_refreshed

    def _mark_feed_refreshed(self, feed_url: str) -> None:
        if not hasattr(self, '_session_refreshed'):
            self._session_refreshed: set[str] = set()
        self._session_refreshed.add(feed_url)

    def _on_feed_context_menu(self, pos):
        item = self._feed_list.itemAt(pos)
        if not item or not self._store:
            return

        feed_url = item.data(Qt.ItemDataRole.UserRole)
        feed = self._store.get_feed(feed_url)
        if not feed:
            return

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

        refresh_action = menu.addAction("Refresh Feed")
        menu.addSeparator()
        unsub_action = menu.addAction("Unsubscribe")

        action = menu.exec(self._feed_list.mapToGlobal(pos))
        if action == refresh_action:
            self._refresh_single_feed(feed)
        elif action == unsub_action:
            self._unsubscribe_feed(feed)

    # ── Episode context menu ─────────────────────────────────────────────

    def _on_episode_context_menu(self, pos) -> None:
        """Right-click on episode rows → Add/Remove actions."""
        t = self._episode_list.table
        # If right-clicked row is not already selected, target that row only.
        row = t.rowAt(pos.y())
        if row >= 0:
            selected_rows = {idx.row() for idx in t.selectedIndexes()}
            if row not in selected_rows:
                t.clearSelection()
                t.selectRow(row)

        selected = self._get_selected_episodes()
        if not selected:
            return

        from PodcastManager.models import (
            STATUS_DOWNLOADED,
            STATUS_DOWNLOADING,
            STATUS_ON_IPOD,
        )

        can_add = [ep for _, ep in selected if ep.status not in (STATUS_ON_IPOD, STATUS_DOWNLOADING)]
        can_remove_dl = [ep for _, ep in selected if ep.status in (STATUS_DOWNLOADED,) and ep.downloaded_path]
        can_remove_ipod = [ep for _, ep in selected if ep.status == STATUS_ON_IPOD and ep.ipod_db_track_id]

        if not can_add and not can_remove_dl and not can_remove_ipod:
            return

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

        add_action = remove_dl_action = remove_ipod_action = None

        if can_add:
            n = len(can_add)
            suffix = f" ({n})" if n > 1 else ""
            add_action = menu.addAction(f"Add to iPod{suffix}")

        if can_remove_dl:
            if add_action:
                menu.addSeparator()
            n = len(can_remove_dl)
            suffix = f" ({n})" if n > 1 else ""
            remove_dl_action = menu.addAction(f"Remove Download{suffix}")

        if can_remove_ipod:
            if add_action or remove_dl_action:
                menu.addSeparator()
            n = len(can_remove_ipod)
            suffix = f" ({n})" if n > 1 else ""
            remove_ipod_action = menu.addAction(f"Remove from iPod{suffix}")

        viewport = self._episode_list.table.viewport()
        if not viewport:
            return
        action = menu.exec(viewport.mapToGlobal(pos))
        if action is None:
            return
        if action == add_action:
            self._on_add_to_ipod()
        elif action == remove_dl_action:
            self._remove_downloads(can_remove_dl)
        elif action == remove_ipod_action:
            self._remove_from_ipod(can_remove_ipod)

    # ── Episode table ────────────────────────────────────────────────────

    @staticmethod
    def _ep_to_dict(ep, status_text: str) -> dict:
        """Convert a PodcastEpisode to a MusicBrowserList-compatible dict."""
        return {
            "Title": ep.title or ep.guid or "",
            "ep_status": status_text,
            "length": (ep.duration_seconds or 0) * 1000,
            "date_added": int(ep.pub_date or 0),
            "size": ep.size_bytes or 0,
            "_ep_guid": ep.guid,
        }

    def _show_episodes(self, feed) -> None:
        """Populate the episode list for the given feed."""
        bl = self._episode_list
        self._episode_by_guid.clear()
        self._episode_dicts = []

        if not feed:
            self._feed_title_label.setText("Select a podcast")
            self._feed_author_label.setText("")
            self._feed_description_label.setText("")
            self._feed_detail_label.setText("")
            self._feed_stat_episodes.setText("")
            self._feed_stat_downloaded.setText("")
            self._feed_stat_on_ipod.setText("")
            self._feed_stat_extra.setText("")
            self._load_feed_settings(None)
            self._set_feed_art_placeholder()
            bl._all_tracks = []
            bl._tracks = []
            bl._load_id += 1
            bl._populate_table()
            return

        self._feed_title_label.setText(feed.title or "Untitled Podcast")
        self._feed_author_label.setText(feed.author or "Unknown Author")

        desc_text = (feed.description or "").replace("\n", " ").strip()
        if len(desc_text) > 170:
            desc_text = f"{desc_text[:167].rstrip()}..."
        self._feed_description_label.setText(desc_text)

        detail_parts = []
        if feed.language:
            detail_parts.append(feed.language.upper())
        refreshed = _fmt_date(feed.last_refreshed)
        if refreshed:
            detail_parts.append(f"Updated {refreshed}")
        if feed.feed_url:
            detail_parts.append("RSS feed linked")
        self._feed_detail_label.setText("  ·  ".join(detail_parts))

        self._feed_stat_episodes.setText(f"Episodes: {len(feed.episodes)}")
        self._feed_stat_downloaded.setText(f"Downloaded: {feed.downloaded_count}")
        self._feed_stat_on_ipod.setText(f"On iPod: {feed.on_ipod_count}")

        extra_parts = []
        if feed.category:
            extra_parts.append(feed.category)
        if feed.language:
            extra_parts.append(feed.language.upper())
        self._feed_stat_extra.setText(" · ".join(extra_parts))

        self._load_feed_settings(feed)

        # Load header artwork
        self._set_feed_art_placeholder()
        artwork_source = self._feed_artwork_source(feed)
        if artwork_source:
            self._load_feed_artwork(artwork_source)

        # Populate episodes (newest first)
        episodes = sorted(feed.episodes, key=lambda e: e.pub_date, reverse=True)
        self._episode_by_guid = {ep.guid: ep for ep in episodes}
        self._episode_dicts = [
            self._ep_to_dict(ep, self._episode_status_display(ep)[0])
            for ep in episodes
        ]

        bl._all_tracks = self._episode_dicts
        bl._tracks = self._episode_dicts
        bl._is_playlist_mode = False
        bl._current_filter = None
        bl._load_id += 1
        bl._populate_table()

    @staticmethod
    def _episode_status_display(ep):
        """Return (text, QColor|None) for episode status."""
        from PyQt6.QtGui import QColor as _QC

        from PodcastManager.models import (
            STATUS_DOWNLOADED,
            STATUS_DOWNLOADING,
            STATUS_ON_IPOD,
        )
        if ep.status == STATUS_ON_IPOD:
            return ("On iPod", _QC(Colors.SUCCESS))
        if ep.status == STATUS_DOWNLOADED:
            return ("Downloaded", _QC(Colors.ACCENT))
        if ep.status == STATUS_DOWNLOADING:
            return ("Downloading…", _QC(Colors.WARNING))
        if ep.size_bytes and ep.size_bytes > 0:
            return (format_size(ep.size_bytes), None)
        return ("", None)

    # ── Toolbar actions ──────────────────────────────────────────────────

    def _on_search(self) -> None:
        """Open the podcast search dialog."""
        from .podcastSearchDialog import PodcastSearchDialog

        dialog = PodcastSearchDialog(self)
        dialog.subscribed.connect(self._subscribe_to_feed)
        dialog.exec()

    def _refresh_all_feeds_bg(self) -> None:
        """Silently refresh all feeds from RSS in the background.

        Called automatically on device load so the full episode catalog
        is available.  Unlike ``_on_refresh_all`` this does not disable
        buttons or show a status bar message.
        """
        if not self._store:
            return
        feeds = self._store.get_feeds()
        if not feeds:
            return

        from app_core.runtime import ThreadPoolSingleton, Worker
        from PodcastManager.feed_parser import fetch_feed

        store = self._store

        def _refresh():
            refreshed_feeds = []
            for feed in feeds:
                try:
                    refreshed_feeds.append(fetch_feed(feed.feed_url, existing=feed))
                except Exception as exc:
                    log.warning("Background refresh failed for %s: %s", feed.title, exc)
            return store.update_feeds(refreshed_feeds)

        worker = Worker(_refresh)
        worker.signals.result.connect(self._on_refresh_done)
        worker.signals.error.connect(self._on_refresh_error)
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_refresh_all(self) -> None:
        """Refresh all subscribed feeds in background."""
        if not self._store:
            return

        feeds = self._store.get_feeds()
        if not feeds:
            self._set_status("No subscriptions to refresh")
            return

        self._refresh_btn.setEnabled(False)
        self._set_status(f"Refreshing {len(feeds)} feeds…")

        from app_core.runtime import ThreadPoolSingleton, Worker
        from PodcastManager.feed_parser import fetch_feed

        store = self._store

        def _refresh_all():
            refreshed_feeds = []
            for feed in feeds:
                try:
                    refreshed_feeds.append(fetch_feed(feed.feed_url, existing=feed))
                except Exception as exc:
                    log.warning("Failed to refresh %s: %s", feed.title, exc)
            return store.update_feeds(refreshed_feeds)

        worker = Worker(_refresh_all)
        worker.signals.result.connect(self._on_refresh_done)
        worker.signals.error.connect(self._on_refresh_error)
        worker.signals.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_refresh_done(self, count: int) -> None:
        # Mark all feeds as refreshed this session
        if self._store:
            for f in self._store.get_feeds():
                self._mark_feed_refreshed(f.feed_url)
        if count:
            self._set_status(f"Refreshed {count} feed{'s' if count != 1 else ''}")

        # Reconcile episode statuses after RSS merge so that episodes
        # present on the iPod (but only known from RSS, not yet stored)
        # are correctly marked as "On iPod".
        self.reconcile_ipod_statuses()

        self._refresh_feed_list()

        # Re-display the currently selected feed's episodes with full catalog
        if self._selected_feed and self._store:
            updated = self._store.get_feed(self._selected_feed.feed_url)
            if updated:
                self._selected_feed = updated
                self._show_episodes(updated)

    def _on_refresh_error(self, error_tuple) -> None:
        _, value, _ = error_tuple
        self._set_status(f"Refresh failed: {value}")

    # ── Managed podcast sync ─────────────────────────────────────────────

    def _on_sync_podcasts(self) -> None:
        """Refresh all feeds, then build a managed sync plan.

        The plan applies each feed's slot settings: removing listened/old
        episodes and filling empty slots with new ones.
        """
        if not self._store:
            return

        feeds = self._store.get_feeds()
        if not feeds:
            self._set_status("No subscriptions to sync")
            return

        self._sync_btn.setEnabled(False)
        self._set_status("Refreshing feeds for sync…", timeout_ms=0)

        from app_core.runtime import ThreadPoolSingleton, Worker
        from PodcastManager.feed_parser import fetch_feed

        store = self._store

        def _refresh_and_plan():
            # Phase 1: Refresh all feeds from RSS
            refreshed = []
            for feed in feeds:
                try:
                    refreshed.append(fetch_feed(feed.feed_url, existing=feed))
                except Exception as exc:
                    log.warning("Failed to refresh %s: %s", feed.title, exc)
                    refreshed.append(feed)  # Keep existing data
            store.update_feeds(refreshed)
            return refreshed

        worker = Worker(_refresh_and_plan)
        worker.signals.result.connect(self._on_sync_feeds_refreshed)
        worker.signals.error.connect(self._on_sync_error)
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_sync_feeds_refreshed(self, refreshed_feeds: list) -> None:
        """Feeds refreshed — build podcast sync plan and emit for review."""
        if not self._store:
            self._sync_btn.setEnabled(True)
            return

        # Mark all as refreshed this session
        for f in refreshed_feeds:
            self._mark_feed_refreshed(f.feed_url)
        self._refresh_feed_list()

        # Get iPod tracks for plan building
        ipod_tracks = self._current_ipod_tracks() or []

        # Reconcile episode statuses against actual iPod tracks before
        # building the plan.  This ensures episodes synced in a prior run
        # are correctly marked as "On iPod" even if the subscription store
        # on disk was stale (e.g. NOT_DOWNLOADED episodes from RSS that
        # were synced but never persisted with ON_IPOD status).
        self.reconcile_ipod_statuses(ipod_tracks)

        from PodcastManager.podcast_sync import build_podcast_managed_plan

        # Re-read feeds from store (they were just updated by reconcile)
        feeds = self._store.get_feeds()
        plan = build_podcast_managed_plan(feeds, ipod_tracks, self._store)

        if not plan.has_changes:
            self._set_status("All podcasts are up to date")
            self._sync_btn.setEnabled(True)
            return

        # Emit the plan (pending episodes will download during sync)
        summary_parts = []
        if plan.to_remove:
            summary_parts.append(f"{len(plan.to_remove)} to remove")
        if plan.to_add:
            summary_parts.append(f"{len(plan.to_add)} to add")
        self._set_status(f"Podcast sync: {', '.join(summary_parts)}")
        self._sync_btn.setEnabled(True)
        self.podcast_sync_requested.emit(plan)

    def _on_sync_error(self, error_tuple) -> None:
        self._progress_bar.hide()
        _, value, _ = error_tuple
        self._set_status(f"Sync failed: {value}")
        self._sync_btn.setEnabled(True)

    # ── Subscribe / unsubscribe ──────────────────────────────────────────

    def _subscribe_to_feed(self, feed_url: str, artwork_url: str = "") -> None:
        """Subscribe to a feed by URL (called from search dialog)."""
        if not self._store:
            return

        # Check if already subscribed
        if self._store.get_feed(feed_url):
            self._set_status("Already subscribed")
            return

        self._set_status("Fetching feed…")

        from app_core.runtime import ThreadPoolSingleton, Worker

        worker = Worker(self._fetch_subscribed_feed, feed_url, artwork_url)
        worker.signals.result.connect(self._on_feed_fetched)
        worker.signals.error.connect(self._on_subscribe_error)
        ThreadPoolSingleton.get_instance().start(worker)

    def _fetch_subscribed_feed(self, feed_url: str, artwork_url: str = ""):
        from PodcastManager.feed_parser import fetch_feed

        feed = fetch_feed(feed_url)
        if artwork_url and self._store:
            cached_path = self._cache_artwork_file(feed_url, artwork_url)
            if cached_path:
                feed.artwork_path = cached_path
        return feed

    def _cache_artwork_file(self, feed_url: str, artwork_url: str) -> str:
        if not self._store or not artwork_url:
            return ""

        cache_dir = os.path.join(self._store.podcast_dir, "artwork-cache")
        os.makedirs(cache_dir, exist_ok=True)

        suffix = Path(urlparse(artwork_url).path).suffix.lower() or ".jpg"
        key = hashlib.sha256(f"{feed_url}|{artwork_url}".encode()).hexdigest()[:24]
        cache_path = os.path.join(cache_dir, f"{key}{suffix}")
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            return cache_path

        try:
            import requests

            resp = requests.get(
                artwork_url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Referer": "https://www.buzzsprout.com/",
                },
            )
            resp.raise_for_status()
            with open(cache_path, "wb") as f:
                f.write(resp.content)
            return cache_path
        except Exception as exc:
            log.debug("Failed to cache podcast artwork from %s: %s", artwork_url, exc)
            return ""

    def _on_feed_fetched(self, feed) -> None:
        if not self._store:
            return
        self._store.add_feed(feed)
        self._mark_feed_refreshed(feed.feed_url)
        self._set_status(f"Subscribed to {feed.title}")
        self._refresh_feed_list()

        # Select the new feed
        for i in range(self._feed_list.count()):
            item = self._feed_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == feed.feed_url:
                self._feed_list.setCurrentRow(i)
                break

        self._selected_feed = self._store.get_feed(feed.feed_url) or feed
        self._show_episodes(self._selected_feed)

    def _on_subscribe_error(self, error_tuple) -> None:
        _, value, _ = error_tuple
        self._set_status(f"Subscribe failed: {value}")

    def _unsubscribe_feed(self, feed) -> None:
        if not self._store:
            return
        self._store.remove_feed(feed.feed_url)
        self._set_status(f"Unsubscribed from {feed.title}")
        self._selected_feed = None
        self._refresh_feed_list()

    def _refresh_single_feed(self, feed) -> None:
        """Refresh a single feed in the background."""
        self._set_status(f"Refreshing {feed.title}…")

        from app_core.runtime import ThreadPoolSingleton, Worker
        from PodcastManager.feed_parser import fetch_feed

        def _do():
            return fetch_feed(feed.feed_url, existing=feed)

        worker = Worker(_do)
        worker.signals.result.connect(self._on_single_feed_refreshed)
        worker.signals.error.connect(self._on_refresh_error)
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_single_feed_refreshed(self, feed) -> None:
        if not self._store:
            return
        self._store.update_feed(feed)
        self._mark_feed_refreshed(feed.feed_url)
        self._set_status(f"Refreshed {feed.title}")
        self._refresh_feed_list()

        # Re-display episodes for the selected feed — _refresh_feed_list
        # restores the selection but setCurrentRow won't emit if the row
        # index didn't change, so the episode table wouldn't update.
        if self._selected_feed and self._selected_feed.feed_url == feed.feed_url:
            self._selected_feed = feed
            self._show_episodes(feed)

    # ── Episode selection ────────────────────────────────────────────────

    def _get_selected_episodes(self):
        """Return list of (row, episode) for the currently selected table rows."""
        if not self._selected_feed:
            return []

        t = self._episode_list.table
        selected_rows = sorted({idx.row() for idx in t.selectedIndexes()})
        result = []
        for row in selected_rows:
            # Anchor item at column 0 (Title) stores original dict index in UserRole+1
            anchor = t.item(row, 0)
            if anchor:
                orig_idx = anchor.data(Qt.ItemDataRole.UserRole + 1)
                if orig_idx is not None and 0 <= orig_idx < len(self._episode_dicts):
                    guid = self._episode_dicts[orig_idx].get("_ep_guid")
                    ep = self._episode_by_guid.get(guid)
                    if ep is not None:
                        result.append((row, ep))
        return result

    # ── Add to iPod (download + sync in one step) ──────────────────

    def _on_add_to_ipod(self) -> None:
        """Sync selected episodes to iPod.

        Builds a sync plan that includes both downloaded and pending
        episodes. Pending episodes will be downloaded during sync execution.

        Single-action flow:
        1. Filters out episodes already on iPod
        2. Builds a sync plan (includes pending episodes)
        3. Emits plan for sync review
        """
        selected = self._get_selected_episodes()
        if not selected:
            self._set_action_status("Select episodes first")
            return
        if not self._selected_feed:
            self._set_action_status("No feed selected")
            return
        if not self._ipod_path:
            self._set_action_status("No iPod connected")
            return

        from PodcastManager.models import STATUS_ON_IPOD

        # Filter out episodes already on iPod
        actionable = [
            ep for _, ep in selected
            if ep.status != STATUS_ON_IPOD
        ]
        if not actionable:
            self._set_action_status("Selected episodes are already on iPod")
            return

        feed = self._selected_feed

        # Build sync plan directly (pending episodes will download during sync)
        self._build_and_emit_plan(actionable, feed)

    def _build_and_emit_plan(self, actionable_episodes, feed) -> None:
        """Build a SyncPlan from actionable episodes and emit to main app.

        Accepts both downloaded and pending episodes. Pending episodes will
        be downloaded during sync execution.

        Args:
            actionable_episodes: List of PodcastEpisodes (not yet on iPod)
            feed: Parent PodcastFeed
        """
        episodes_for_plan = [(ep, feed) for ep in actionable_episodes]

        if not episodes_for_plan:
            self._set_action_status("No episodes to sync")
            return

        # Get current iPod tracks for dedup
        ipod_tracks = self._current_ipod_tracks() or []

        from PodcastManager.podcast_sync import build_podcast_sync_plan
        plan = build_podcast_sync_plan(episodes_for_plan, ipod_tracks, self._store)

        if not plan.to_add:
            self._set_action_status("All selected episodes are already on iPod")
            return

        n = len(plan.to_add)
        self._set_action_status(
            f"Sending {n} episode{'s' if n != 1 else ''} to sync…")

        self.podcast_sync_requested.emit(plan)

    def _on_add_error(self, error_tuple) -> None:
        self._progress_bar.hide()
        _, value, _ = error_tuple
        self._set_action_status(f"Failed: {value}")

    # ── Remove download / Remove from iPod ───────────────────────────────

    def _remove_downloads(self, episodes: list) -> None:
        """Delete downloaded files and reset episode status."""
        import os

        from PodcastManager.models import STATUS_NOT_DOWNLOADED

        removed = 0
        for ep in episodes:
            if ep.downloaded_path and os.path.exists(ep.downloaded_path):
                try:
                    os.remove(ep.downloaded_path)
                except OSError as exc:
                    log.warning("Could not delete %s: %s", ep.downloaded_path, exc)
                    continue
            ep.downloaded_path = ""
            ep.status = STATUS_NOT_DOWNLOADED
            removed += 1

        if self._store and self._selected_feed:
            self._store.update_feed(self._selected_feed)

        self._show_episodes(self._selected_feed)
        self._refresh_feed_list()
        self._set_action_status(f"Removed {removed} download{'s' if removed != 1 else ''}")

    def _remove_from_ipod(self, episodes: list) -> None:
        """Build a sync plan to remove episodes from the iPod."""
        if not self._selected_feed or not self._ipod_path:
            return

        from app_core.sync_plan_builder import build_podcast_removal_sync_plan

        ipod_tracks = self._current_ipod_tracks() or []
        plan = build_podcast_removal_sync_plan(
            episodes,
            ipod_tracks,
            self._selected_feed.title,
        )

        if plan is None:
            self._set_action_status("Episodes not found on iPod")
            return

        n = len(plan.to_remove)
        self._set_action_status(
            f"Sending {n} removal{'s' if n != 1 else ''} to sync\u2026")
        self.podcast_sync_requested.emit(plan)

    def refresh_episodes(self) -> None:
        """Public: refresh the episode table and feed list from store.

        Called after sync completes so status changes (e.g. 'on_ipod')
        are reflected in the UI.
        """
        if self._selected_feed and self._store:
            # Re-read the feed from store (statuses may have been updated)
            refreshed = self._store.get_feed(self._selected_feed.feed_url)
            if refreshed:
                self._selected_feed = refreshed
            self._show_episodes(self._selected_feed)
        self._refresh_feed_list()

    # ── Artwork loading ──────────────────────────────────────────────────

    # ── Per-feed settings ───────────────────────────────────────────────

    def _load_feed_settings(self, feed) -> None:
        """Populate the per-feed setting controls from a PodcastFeed."""
        # Block signals while loading to avoid triggering saves
        for w in (self._feed_episode_slots, self._feed_fill_mode,
                  self._feed_clear_listened, self._feed_clear_older,
                  self._feed_clear_method):
            w.blockSignals(True)

        enabled = feed is not None
        self._feed_episode_slots.setEnabled(enabled)
        self._feed_fill_mode.setEnabled(enabled)
        self._feed_clear_listened.setEnabled(enabled)
        self._feed_clear_older.setEnabled(enabled)
        self._feed_clear_method.setEnabled(enabled)

        if feed is not None:
            self._feed_episode_slots.setValue(feed.episode_slots)

            _fill_display = {"newest": "Newest Episode", "next": "Next Episode"}
            idx = self._feed_fill_mode.findText(
                _fill_display.get(feed.fill_mode, "Newest Episode"),
            )
            if idx >= 0:
                self._feed_fill_mode.setCurrentIndex(idx)

            _cl_display = {True: "Yes", False: "No"}
            idx = self._feed_clear_listened.findText(
                _cl_display.get(feed.clear_when_listened, "Yes"),
            )
            if idx >= 0:
                self._feed_clear_listened.setCurrentIndex(idx)

            _older_display = {
                "1_day": "1 Day", "3_days": "3 Days",
                "1_week": "1 Week", "2_weeks": "2 Weeks",
                "1_month": "1 Month", "2_months": "2 Months",
                "3_months": "3 Months", "never": "Never",
            }
            idx = self._feed_clear_older.findText(
                _older_display.get(feed.clear_older_than, "Never"),
            )
            if idx >= 0:
                self._feed_clear_older.setCurrentIndex(idx)

            _method_display = {
                "remove": "Remove Immediately",
                "replace": "Mark for Replacement",
            }
            idx = self._feed_clear_method.findText(
                _method_display.get(feed.clear_method, "Remove Immediately"),
            )
            if idx >= 0:
                self._feed_clear_method.setCurrentIndex(idx)
        else:
            self._feed_episode_slots.setValue(3)
            self._feed_fill_mode.setCurrentIndex(0)
            self._feed_clear_listened.setCurrentIndex(0)
            self._feed_clear_older.setCurrentIndex(
                self._feed_clear_older.count() - 1,  # "Never"
            )
            self._feed_clear_method.setCurrentIndex(0)

        for w in (self._feed_episode_slots, self._feed_fill_mode,
                  self._feed_clear_listened, self._feed_clear_older,
                  self._feed_clear_method):
            w.blockSignals(False)

    def _on_feed_setting_changed(self, *_args) -> None:
        """Write current setting controls back to the selected feed."""
        if not self._store or not self._selected_feed:
            return

        feed = self._selected_feed

        _fill_keys = {"Newest Episode": "newest", "Next Episode": "next"}
        _cl_keys = {"Yes": True, "No": False}
        _older_keys = {
            "1 Day": "1_day", "3 Days": "3_days",
            "1 Week": "1_week", "2 Weeks": "2_weeks",
            "1 Month": "1_month", "2 Months": "2_months",
            "3 Months": "3_months", "Never": "never",
        }
        _method_keys = {
            "Remove Immediately": "remove",
            "Mark for Replacement": "replace",
        }

        feed.episode_slots = self._feed_episode_slots.value()
        feed.fill_mode = _fill_keys.get(
            self._feed_fill_mode.currentText(), "newest",
        )
        feed.clear_when_listened = _cl_keys.get(
            self._feed_clear_listened.currentText(), True,
        )
        feed.clear_older_than = _older_keys.get(
            self._feed_clear_older.currentText(), "never",
        )
        feed.clear_method = _method_keys.get(
            self._feed_clear_method.currentText(), "remove",
        )

        self._store.update_feed(feed)

    def _set_feed_art_placeholder(self) -> None:
        """Set a crisp HiDPI-safe placeholder icon in the feed artwork slot."""
        placeholder = self._artwork_placeholder_pixmap(52)
        if placeholder:
            self._feed_art.setPixmap(placeholder)
            self._feed_art.setText("")
        else:
            self._feed_art.setText("◎")
        self._reset_feed_hero_color()

    def _artwork_placeholder_pixmap(self, size: int) -> QPixmap | None:
        """Create the gray square placeholder used when artwork is missing."""
        glyph = glyph_pixmap("broadcast", max(16, int(size * 0.52)), Colors.TEXT_TERTIARY)
        if glyph is None:
            return None

        px = QPixmap(size, size)
        px.fill(QColor(Colors.SURFACE_ALT))
        painter = QPainter(px)
        try:
            x = (size - glyph.width()) // 2
            y = (size - glyph.height()) // 2
            painter.drawPixmap(x, y, glyph)
        finally:
            painter.end()
        return px

    def _apply_hero_color_from_pixmap(self, pixmap: QPixmap) -> None:
        """Extract average color from pixmap using Qt only (no PIL, no encode)."""
        try:
            # Scale to a tiny thumbnail with Qt — fast nearest-neighbor
            small = pixmap.scaled(
                20, 20,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            img = small.toImage().convertToFormat(QImage.Format.Format_RGB888)
            ptr = img.bits()
            if ptr is None:
                return
            raw = bytes(ptr.asarray(img.width() * img.height() * 3))
            n = img.width() * img.height()
            if n == 0:
                return
            r = sum(raw[0::3]) // n
            g = sum(raw[1::3]) // n
            b = sum(raw[2::3]) // n
            self._apply_feed_hero_color(r, g, b)
        except Exception:
            pass

    def _apply_hero_color_for_source(self, source: str, pixmap: QPixmap) -> None:
        cached = _artwork_color_cache.get(source)
        if cached is not None:
            self._apply_feed_hero_color(*cached)
            return
        try:
            small = pixmap.scaled(
                20,
                20,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            img = small.toImage().convertToFormat(QImage.Format.Format_RGB888)
            ptr = img.bits()
            if ptr is None:
                return
            raw = bytes(ptr.asarray(img.width() * img.height() * 3))
            n = img.width() * img.height()
            if n == 0:
                return
            color = (
                sum(raw[0::3]) // n,
                sum(raw[1::3]) // n,
                sum(raw[2::3]) // n,
            )
            _artwork_color_cache[source] = color
            self._apply_feed_hero_color(*color)
        except Exception:
            pass

    def _apply_feed_hero_color(self, r: int, g: int, b: int) -> None:
        """Tint the hero header with the artwork's dominant color."""
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

        self._feed_header.setStyleSheet(f"""
            QFrame#heroHeader {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({r}, {g}, {b}, 80),
                    stop:1 {Colors.BG_DARK}
                );
                border-bottom: 1px solid rgba({r}, {g}, {b}, 40);
            }}
        """)
        self._feed_art.setStyleSheet(f"""
            background: rgba({r}, {g}, {b}, 30);
            border-radius: {Metrics.BORDER_RADIUS}px;
            border: 1px solid rgba({r}, {g}, {b}, 50);
        """)
        self._feed_title_label.setStyleSheet(
            "color: " + Colors.TEXT_PRIMARY + "; background: transparent;")
        self._feed_author_label.setStyleSheet(
            "color: " + Colors.TEXT_SECONDARY + "; background: transparent;")
        self._feed_description_label.setStyleSheet(
            "color: " + Colors.TEXT_SECONDARY + "; background: transparent;")
        self._feed_detail_label.setStyleSheet(
            "color: " + Colors.TEXT_TERTIARY + "; background: transparent;")

        _glass_css = btn_css(
            bg=glass_bg,
            bg_hover=glass_hover,
            bg_press=glass_press,
            fg=Colors.TEXT_PRIMARY,
            border=f"1px solid {glass_border}",
            padding="5px 12px",
            radius=Metrics.BORDER_RADIUS_SM,
        )
        for btn in self._hero_btns:
            btn.setStyleSheet(_glass_css)

    def _reset_feed_hero_color(self) -> None:
        """Reset the hero to the default (no artwork tint) style."""
        self._feed_header.setStyleSheet(f"""
            QFrame#heroHeader {{
                background: {Colors.BG_DARK};
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        self._feed_art.setStyleSheet(f"""
            background: {Colors.SURFACE};
            border-radius: {Metrics.BORDER_RADIUS}px;
            border: 1px solid {Colors.BORDER_SUBTLE};
        """)
        # Labels and buttons may not exist yet during initial construction
        if not hasattr(self, '_feed_title_label'):
            return
        self._feed_title_label.setStyleSheet(
            "color: " + Colors.TEXT_PRIMARY + "; background: transparent;")
        self._feed_author_label.setStyleSheet(
            "color: " + Colors.TEXT_SECONDARY + "; background: transparent;")
        self._feed_description_label.setStyleSheet(
            "color: " + Colors.TEXT_SECONDARY + "; background: transparent;")
        self._feed_detail_label.setStyleSheet(
            "color: " + Colors.TEXT_TERTIARY + "; background: transparent;")
        _default_css = btn_css(padding="5px 12px", radius=Metrics.BORDER_RADIUS_SM)
        for btn in self._hero_btns:
            btn.setStyleSheet(_default_css)

    def _feed_artwork_source(self, feed) -> str:
        return getattr(feed, "artwork_path", "") or getattr(feed, "artwork_url", "")

    def _request_artwork(
        self,
        source: str,
        on_ready: Callable[[str, QPixmap], None],
    ) -> None:
        if not source:
            return

        cached = _artwork_cache.get(source)
        if cached is not None:
            on_ready(source, cached)
            return

        waiters = self._artwork_inflight.get(source)
        if waiters is not None:
            waiters.append(on_ready)
            return

        self._artwork_inflight[source] = [on_ready]

        from app_core.runtime import ThreadPoolSingleton, Worker

        def _fetch() -> tuple[str, bytes | None]:
            return source, _load_artwork_bytes(source)

        worker = Worker(_fetch)
        worker.signals.result.connect(self._on_artwork_request_finished)
        worker.signals.error.connect(
            lambda _, s=source: self._on_artwork_request_failed(s)
        )
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_artwork_request_finished(self, result: tuple[str, bytes | None]) -> None:
        source, data = result
        callbacks = self._artwork_inflight.pop(source, [])
        if not data:
            return

        img = QImage()
        if not img.loadFromData(data):
            return

        full_pm = QPixmap.fromImage(img)
        _artwork_cache[source] = full_pm

        for callback in callbacks:
            callback(source, full_pm)

    def _on_artwork_request_failed(self, source: str) -> None:
        self._artwork_inflight.pop(source, None)
        log.debug("Failed to load artwork: %s", source)

    def _apply_feed_artwork_pixmap(self, source: str, full_pm: QPixmap) -> None:
        art_w = max(1, self._feed_art.width())
        art_h = max(1, self._feed_art.height())
        pm = scale_pixmap_for_display(
            full_pm,
            art_w,
            art_h,
            widget=self._feed_art,
            aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
            transform_mode=Qt.TransformationMode.SmoothTransformation,
        )
        self._feed_art.setPixmap(pm)
        self._feed_art.setText("")
        self._apply_hero_color_for_source(source, full_pm)

    def _load_feed_artwork(self, source: str) -> None:
        """Load feed artwork for the header panel in background."""
        def _apply_if_selected(loaded_source: str, full_pm: QPixmap) -> None:
            if (
                self._selected_feed
                and self._feed_artwork_source(self._selected_feed) == loaded_source
            ):
                self._apply_feed_artwork_pixmap(loaded_source, full_pm)
            self._update_feed_list_icon(loaded_source, full_pm)

        self._request_artwork(source, _apply_if_selected)

    def _load_feed_list_artwork(self, source: str, row: int) -> None:
        """Load a feed's artwork for its list item thumbnail."""
        _ = row
        self._request_artwork(
            source,
            lambda loaded_source, full_pm: self._update_feed_list_icon(
                loaded_source,
                full_pm,
            ),
        )

    def _update_feed_list_icon(self, url: str, full_pm: QPixmap) -> None:
        """Set the icon for all feed list items whose artwork URL matches."""
        if not self._store:
            return
        icon_pm = scale_pixmap_for_display(
            full_pm,
            36,
            36,
            widget=self._feed_list,
            aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
            transform_mode=Qt.TransformationMode.SmoothTransformation,
        )
        icon = QIcon(icon_pm)
        feeds = self._store.get_feeds()
        for i, feed in enumerate(feeds):
            if self._feed_artwork_source(feed) == url:
                item = self._feed_list.item(i)
                if item:
                    item.setIcon(icon)

    # ── Status helpers ───────────────────────────────────────────────────

    def _set_status(self, text: str, timeout_ms: int = 5000) -> None:
        """Set toolbar status text with auto-clear."""
        self._status_label.setText(text)
        if timeout_ms > 0 and text:
            QTimer.singleShot(timeout_ms, lambda: self._clear_status_if(text))

    def _clear_status_if(self, expected: str) -> None:
        """Clear status only if it still shows the expected message."""
        if self._status_label.text() == expected:
            self._status_label.setText("")

    def _set_action_status(self, text: str, timeout_ms: int = 5000) -> None:
        """Show the status toast with *text*, auto-hiding after *timeout_ms*."""
        self._action_status.setText(text)
        if text:
            self._status_toast.show()
        else:
            self._status_toast.hide()
        if timeout_ms > 0 and text:
            QTimer.singleShot(timeout_ms, lambda: self._clear_action_if(text))

    def _clear_action_if(self, expected: str) -> None:
        if self._action_status.text() == expected:
            self._action_status.setText("")
            self._status_toast.hide()
