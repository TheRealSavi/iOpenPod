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

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QImage, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
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

from ..hidpi import scale_pixmap_for_display
from ..styles import (
    Colors,
    Metrics,
    FONT_FAMILY,
    accent_btn_css,
    btn_css,
    make_label,
    make_separator,
    scrollbar_css,
    table_css,
    LABEL_SECONDARY,
)
from ..glyphs import glyph_icon, glyph_pixmap
from .formatters import format_size

log = logging.getLogger(__name__)


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
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OSError, ValueError):
        return ""


# ── Feed artwork cache ───────────────────────────────────────────────────────
# Maps artwork URL → QPixmap so that repeated list refreshes don't re-download.
_artwork_cache: dict[str, QPixmap] = {}


class PodcastBrowser(QFrame):
    """Full podcast management widget.

    Must be initialised with ``set_device(serial, ipod_path)`` before use.
    """

    # Emitted when the user confirms podcast sync — carries a SyncPlan
    podcast_sync_requested = pyqtSignal(object)
    # Download progress: completed_episodes, total_episodes,
    # bytes_downloaded_current, total_bytes_current, episode_title
    download_progress = pyqtSignal(int, int, int, int, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._device_serial: str = ""
        self._ipod_path: str = ""
        self._store = None          # SubscriptionStore (lazy)
        self._selected_feed = None  # Current PodcastFeed
        self._deferred_reconcile_tracks: list[dict] | None = None
        self._episode_by_guid: dict[str, object] = {}
        self._pending_ready: list[tuple[int, object]] = []
        self._pending_target_guids: set[str] = set()

        self.download_progress.connect(self._on_download_progress)

        self._build_ui()

    # ── Public API ───────────────────────────────────────────────────────

    def set_device(self, serial: str, ipod_path: str) -> None:
        """Bind to a specific iPod device.  Loads subscriptions."""
        self._device_serial = serial or "_default"
        self._ipod_path = ipod_path

        from PodcastManager.subscription_store import SubscriptionStore
        self._store = SubscriptionStore(ipod_path)
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

    def clear(self) -> None:
        """Reset all state (called on device change)."""
        self._store = None
        self._selected_feed = None
        self._deferred_reconcile_tracks = None
        self._episode_by_guid.clear()
        self._pending_ready = []
        self._pending_target_guids = set()
        self._feed_list.clear()
        self._episode_table.setRowCount(0)
        self._status_label.setText("")
        self._stack.setCurrentIndex(0)

    def reconcile_ipod_statuses(self, ipod_tracks: Optional[list[dict]] = None) -> None:
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
            try:
                from ..app import iTunesDBCache
                cache = iTunesDBCache.get_instance()
                if not cache.is_ready():
                    return
                ipod_tracks = cache.get_tracks() or []
            except Exception:
                return

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
        root.addWidget(make_separator())

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
        bar = QFrame()
        bar.setFixedHeight((44))
        bar.setStyleSheet(f"background: {Colors.SURFACE}; border: none;")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins((12), (6), (12), (6))
        layout.setSpacing((8))

        self._add_btn = QPushButton("Add Podcast")
        self._add_btn.setFont(QFont(FONT_FAMILY, (Metrics.FONT_SM)))
        self._add_btn.setStyleSheet(accent_btn_css())
        self._add_btn.setFixedHeight((30))
        _add_ic = glyph_icon("plus", (14), Colors.TEXT_ON_ACCENT)
        if _add_ic:
            self._add_btn.setIcon(_add_ic)
            self._add_btn.setIconSize(QSize((14), (14)))
        self._add_btn.clicked.connect(self._on_search)
        layout.addWidget(self._add_btn)

        self._refresh_btn = QPushButton("Refresh All")
        self._refresh_btn.setFont(QFont(FONT_FAMILY, (Metrics.FONT_SM)))
        self._refresh_btn.setStyleSheet(btn_css())
        self._refresh_btn.setFixedHeight((30))
        _refresh_ic = glyph_icon("refresh", (14), Colors.TEXT_PRIMARY)
        if _refresh_ic:
            self._refresh_btn.setIcon(_refresh_ic)
            self._refresh_btn.setIconSize(QSize((14), (14)))
        self._refresh_btn.clicked.connect(self._on_refresh_all)
        layout.addWidget(self._refresh_btn)

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

        layout.addSpacing((12))

        heading = make_label(
            "No Podcast Subscriptions",
            size=(Metrics.FONT_PAGE_TITLE),
            weight=QFont.Weight.DemiBold,
        )
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        layout.addSpacing((6))

        desc = make_label(
            "Search for podcasts or add an RSS feed to get started.\n"
            "Episodes can be downloaded and synced to your iPod.",
            size=(Metrics.FONT_LG),
            style=LABEL_SECONDARY(),
            wrap=True,
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        layout.addSpacing((16))

        cta_btn = QPushButton("Add Your First Podcast")
        cta_btn.setFont(QFont(FONT_FAMILY, (Metrics.FONT_MD), QFont.Weight.DemiBold))
        cta_btn.setStyleSheet(accent_btn_css())
        cta_btn.setFixedHeight((38))
        cta_btn.setFixedWidth((240))
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
        splitter.setHandleWidth((3))
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {Colors.BORDER_SUBTLE};
            }}
        """)

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
        panel = QFrame()
        panel.setMinimumWidth((200))
        panel.setStyleSheet("background: transparent; border: none;")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = make_label(
            "Subscriptions",
            size=(Metrics.FONT_SM),
            weight=QFont.Weight.DemiBold,
            style=f"color: {Colors.TEXT_SECONDARY}; padding: {(8)}px {(12)}px;"
            f" background: transparent; border: none;",
        )
        layout.addWidget(header)

        self._feed_list = QListWidget()
        self._feed_list.setIconSize(QSize((36), (36)))
        self._feed_list.setSpacing((2))
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
            {scrollbar_css()}
        """)

        layout.addWidget(self._feed_list, stretch=1)
        return panel

    def _build_episode_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("background: transparent; border: none;")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Feed info header ─────────────────────────────────────────────
        self._feed_header = QFrame()
        self._feed_header.setFixedHeight((176))
        self._feed_header.setStyleSheet(f"""
            background: {Colors.SURFACE};
            border: 1px solid {Colors.BORDER_SUBTLE};
            border-radius: {Metrics.BORDER_RADIUS_LG}px;
        """)

        hdr_layout = QVBoxLayout(self._feed_header)
        hdr_layout.setContentsMargins((12), (12), (12), (12))
        hdr_layout.setSpacing((10))

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing((12))

        self._feed_art = QLabel()
        art_size = (128)
        self._feed_art.setFixedSize(art_size, art_size)
        self._feed_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._feed_art.setStyleSheet(f"""
            background: {Colors.SURFACE_RAISED};
            border-radius: {Metrics.BORDER_RADIUS_SM}px;
            border: 1px solid {Colors.BORDER_SUBTLE};
            color: {Colors.TEXT_TERTIARY};
            font-size: {(32)}px;
        """)
        self._set_feed_art_placeholder()
        top_row.addWidget(self._feed_art)

        hdr_text = QVBoxLayout()
        hdr_text.setSpacing((4))
        self._feed_title_label = make_label(
            "Select a podcast",
            size=(Metrics.FONT_TITLE),
            weight=QFont.Weight.DemiBold,
        )
        self._feed_title_label.setWordWrap(True)
        hdr_text.addWidget(self._feed_title_label)

        self._feed_author_label = make_label(
            "",
            size=(Metrics.FONT_MD),
            style=LABEL_SECONDARY(),
        )
        self._feed_author_label.setWordWrap(True)
        hdr_text.addWidget(self._feed_author_label)

        self._feed_description_label = make_label(
            "",
            size=(Metrics.FONT_SM),
            style=LABEL_SECONDARY(),
            wrap=True,
        )
        self._feed_description_label.setMaximumHeight((44))
        hdr_text.addWidget(self._feed_description_label)

        self._feed_detail_label = make_label(
            "",
            size=(Metrics.FONT_SM),
            style=LABEL_SECONDARY(),
        )
        self._feed_detail_label.setWordWrap(True)
        hdr_text.addWidget(self._feed_detail_label)

        top_row.addLayout(hdr_text, stretch=1)

        rhs_col = QVBoxLayout()
        rhs_col.setSpacing((5))
        rhs_col.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self._feed_stat_episodes = make_label(
            "",
            size=(Metrics.FONT_SM),
            style=f"color: {Colors.TEXT_PRIMARY};",
        )
        self._feed_stat_downloaded = make_label(
            "",
            size=(Metrics.FONT_SM),
            style=f"color: {Colors.ACCENT};",
        )
        self._feed_stat_on_ipod = make_label(
            "",
            size=(Metrics.FONT_SM),
            style=f"color: {Colors.SUCCESS};",
        )
        self._feed_stat_extra = make_label(
            "",
            size=(Metrics.FONT_SM),
            style=LABEL_SECONDARY(),
            wrap=True,
        )
        self._feed_stat_extra.setAlignment(Qt.AlignmentFlag.AlignRight)

        rhs_col.addWidget(self._feed_stat_episodes, alignment=Qt.AlignmentFlag.AlignRight)
        rhs_col.addWidget(self._feed_stat_downloaded, alignment=Qt.AlignmentFlag.AlignRight)
        rhs_col.addWidget(self._feed_stat_on_ipod, alignment=Qt.AlignmentFlag.AlignRight)
        rhs_col.addWidget(self._feed_stat_extra, alignment=Qt.AlignmentFlag.AlignRight)
        rhs_col.addStretch()
        top_row.addLayout(rhs_col)

        hdr_layout.addLayout(top_row)

        self._feed_settings_hint = QLabel("Settings will go here (Not added yet)")
        self._feed_settings_hint.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._feed_settings_hint.setFixedHeight((34))
        self._feed_settings_hint.setMaximumWidth((540))
        self._feed_settings_hint.setStyleSheet(f"""
            color: {Colors.TEXT_SECONDARY};
            background: {Colors.SURFACE_RAISED};
            border: 1px dashed {Colors.BORDER};
            border-radius: {Metrics.BORDER_RADIUS_SM}px;
            padding: 0 {(10)}px;
        """)

        settings_row = QHBoxLayout()
        settings_row.setContentsMargins(0, 0, 0, 0)
        settings_row.setSpacing((8))
        settings_row.addSpacing(art_size + (12))
        settings_row.addWidget(self._feed_settings_hint, 0, Qt.AlignmentFlag.AlignLeft)
        settings_row.addStretch()
        hdr_layout.addLayout(settings_row)

        layout.addWidget(self._feed_header)
        layout.addWidget(make_separator())

        # ── Episode table ────────────────────────────────────────────────
        self._episode_table = QTableWidget(0, _COL_COUNT)
        self._episode_table.setHorizontalHeaderLabels(
            ["Title", "Duration", "Date", "Status"]
        )
        self._episode_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._episode_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._episode_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._episode_table.customContextMenuRequested.connect(self._on_episode_context_menu)
        vh = self._episode_table.verticalHeader()
        if vh:
            vh.setVisible(False)
            vh.setDefaultSectionSize((32))
        self._episode_table.setShowGrid(False)
        self._episode_table.setAlternatingRowColors(True)
        self._episode_table.setSortingEnabled(False)
        self._episode_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Column widths
        hh = self._episode_table.horizontalHeader()
        assert hh is not None
        hh.setMinimumSectionSize((30))
        hh.resizeSection(_COL_DURATION, (70))
        hh.resizeSection(_COL_DATE, (90))
        hh.resizeSection(_COL_STATUS, (110))
        hh.setSectionResizeMode(_COL_TITLE, QHeaderView.ResizeMode.Stretch)
        self._episode_table.setStyleSheet(table_css())

        layout.addWidget(self._episode_table, stretch=1)

        # ── Download progress bar (hidden by default) ────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight((3))
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

        # ── Action bar ───────────────────────────────────────────────────
        action_bar = QFrame()
        action_bar.setFixedHeight((44))
        action_bar.setStyleSheet(
            f"background: {Colors.SURFACE}; border-top: 1px solid {Colors.BORDER_SUBTLE};"
        )

        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins((12), (6), (12), (6))
        action_layout.setSpacing((8))

        self._add_to_ipod_btn = QPushButton("Add to iPod")
        self._add_to_ipod_btn.setFont(QFont(FONT_FAMILY, (Metrics.FONT_SM)))
        self._add_to_ipod_btn.setStyleSheet(accent_btn_css())
        self._add_to_ipod_btn.setFixedHeight((30))
        _sync_ic = glyph_icon("download", (14), Colors.TEXT_ON_ACCENT)
        if _sync_ic:
            self._add_to_ipod_btn.setIcon(_sync_ic)
            self._add_to_ipod_btn.setIconSize(QSize((14), (14)))
        self._add_to_ipod_btn.clicked.connect(self._on_add_to_ipod)
        action_layout.addWidget(self._add_to_ipod_btn)

        action_layout.addStretch()

        self._action_status = make_label(
            "",
            size=(Metrics.FONT_SM),
            style=LABEL_SECONDARY(),
        )
        action_layout.addWidget(self._action_status)

        layout.addWidget(action_bar)

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
            if feed.artwork_url and feed.artwork_url in _artwork_cache:
                icon_pm = scale_pixmap_for_display(
                    _artwork_cache[feed.artwork_url],
                    36,
                    36,
                    widget=self._feed_list,
                    aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
                    transform_mode=Qt.TransformationMode.SmoothTransformation,
                )
                item.setIcon(QIcon(icon_pm))
            elif feed.artwork_url:
                self._load_feed_list_artwork(feed.artwork_url, i)

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
        # If right-clicked row is not already selected, target that row only.
        row = self._episode_table.rowAt(pos.y())
        if row >= 0:
            title_item = self._episode_table.item(row, _COL_TITLE)
            if title_item and not title_item.isSelected():
                self._episode_table.clearSelection()
                self._episode_table.selectRow(row)

        selected = self._get_selected_episodes()
        if not selected:
            return

        from PodcastManager.models import (
            STATUS_DOWNLOADED, STATUS_DOWNLOADING, STATUS_ON_IPOD,
        )

        can_add = [ep for _, ep in selected if ep.status not in (STATUS_ON_IPOD, STATUS_DOWNLOADING)]
        can_remove_dl = [ep for _, ep in selected if ep.status in (STATUS_DOWNLOADED,) and ep.downloaded_path]
        can_remove_ipod = [ep for _, ep in selected if ep.status == STATUS_ON_IPOD and ep.ipod_db_id]

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

        viewport = self._episode_table.viewport()
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

    def _show_episodes(self, feed) -> None:
        """Populate the episode table for the given feed."""
        self._episode_table.setRowCount(0)
        self._episode_by_guid.clear()

        if not feed:
            self._feed_title_label.setText("Select a podcast")
            self._feed_author_label.setText("")
            self._feed_description_label.setText("")
            self._feed_detail_label.setText("")
            self._feed_stat_episodes.setText("")
            self._feed_stat_downloaded.setText("")
            self._feed_stat_on_ipod.setText("")
            self._feed_stat_extra.setText("")
            self._feed_settings_hint.setText("Settings will go here (Not added yet)")
            self._set_feed_art_placeholder()
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

        self._feed_settings_hint.setText(
            f"Settings will go here (Not added yet)"
        )

        # Load header artwork
        if feed.artwork_url:
            self._load_feed_artwork(feed.artwork_url)
        else:
            self._set_feed_art_placeholder()

        # Populate episodes (newest first)
        episodes = sorted(feed.episodes, key=lambda e: e.pub_date, reverse=True)
        self._episode_by_guid = {ep.guid: ep for ep in episodes}
        self._episode_table.setRowCount(len(episodes))

        for row, ep in enumerate(episodes):
            # Title
            title_item = QTableWidgetItem(ep.title or ep.guid)
            title_item.setData(Qt.ItemDataRole.UserRole, ep.guid)
            title_item.setToolTip(ep.description[:300] if ep.description else "")
            self._episode_table.setItem(row, _COL_TITLE, title_item)

            # Duration
            dur_item = QTableWidgetItem(_fmt_duration(ep.duration_seconds))
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._episode_table.setItem(row, _COL_DURATION, dur_item)

            # Date
            date_item = QTableWidgetItem(_fmt_date(ep.pub_date))
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._episode_table.setItem(row, _COL_DATE, date_item)

            # Status
            status_text, status_color = self._episode_status_display(ep)
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status_color:
                status_item.setForeground(status_color)
            self._episode_table.setItem(row, _COL_STATUS, status_item)

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

        from ..app import Worker, ThreadPoolSingleton
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
        self._set_status(f"Refreshed {count} feed{'s' if count != 1 else ''}")
        self._refresh_feed_list()

    def _on_refresh_error(self, error_tuple) -> None:
        _, value, _ = error_tuple
        self._set_status(f"Refresh failed: {value}")

    # ── Subscribe / unsubscribe ──────────────────────────────────────────

    def _subscribe_to_feed(self, feed_url: str) -> None:
        """Subscribe to a feed by URL (called from search dialog)."""
        if not self._store:
            return

        # Check if already subscribed
        if self._store.get_feed(feed_url):
            self._set_status("Already subscribed")
            return

        self._set_status("Fetching feed…")

        from ..app import Worker, ThreadPoolSingleton
        from PodcastManager.feed_parser import fetch_feed

        worker = Worker(fetch_feed, feed_url)
        worker.signals.result.connect(self._on_feed_fetched)
        worker.signals.error.connect(self._on_subscribe_error)
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_feed_fetched(self, feed) -> None:
        if not self._store:
            return
        self._store.add_feed(feed)
        self._set_status(f"Subscribed to {feed.title}")
        self._refresh_feed_list()

        # Select the new feed
        for i in range(self._feed_list.count()):
            item = self._feed_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == feed.feed_url:
                self._feed_list.setCurrentRow(i)
                break

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

        from ..app import Worker, ThreadPoolSingleton
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
        self._set_status(f"Refreshed {feed.title}")
        self._refresh_feed_list()

    # ── Episode selection ────────────────────────────────────────────────

    def _get_selected_episodes(self):
        """Return list of (row, episode) for the currently selected table rows."""
        if not self._selected_feed:
            return []

        selected_rows = sorted({idx.row() for idx in self._episode_table.selectedIndexes()})
        result = []
        for row in selected_rows:
            title_item = self._episode_table.item(row, _COL_TITLE)
            if title_item:
                guid = title_item.data(Qt.ItemDataRole.UserRole)
                ep = self._episode_by_guid.get(guid)
                if ep is not None:
                    result.append((row, ep))
        return result

    # ── Add to iPod (download + sync in one step) ──────────────────

    def _on_add_to_ipod(self) -> None:
        """Download (if needed) and sync selected episodes to iPod.

        Single-action flow:
        1. Filters out episodes already on iPod
        2. Downloads any not-yet-downloaded episodes with progress
        3. Auto-emits the sync plan when ready
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

        from PodcastManager.models import (
            STATUS_DOWNLOADED, STATUS_NOT_DOWNLOADED, STATUS_ON_IPOD,
        )

        # Filter out episodes already on iPod
        actionable = [
            (row, ep) for row, ep in selected
            if ep.status != STATUS_ON_IPOD
        ]
        if not actionable:
            self._set_action_status("Selected episodes are already on iPod")
            return

        need_download = [
            (row, ep) for row, ep in actionable
            if ep.status == STATUS_NOT_DOWNLOADED
        ]
        already_ready = [
            (row, ep) for row, ep in actionable
            if ep.status == STATUS_DOWNLOADED and ep.downloaded_path
        ]

        feed = self._selected_feed
        self._add_to_ipod_btn.setEnabled(False)

        if need_download:
            # Download first, then build sync plan
            self._pending_ready = already_ready
            self._pending_target_guids = {ep.guid for _, ep in actionable}
            self._start_download_and_sync(need_download, feed)
        else:
            # All selected are already downloaded — go straight to sync
            self._build_and_emit_plan(already_ready, feed)

    def _start_download_and_sync(self, to_download, feed) -> None:
        """Download episodes with per-episode progress, then emit sync plan."""
        from ..app import Worker, ThreadPoolSingleton
        from PodcastManager.downloader import download_episode, embed_feed_artwork
        from PodcastManager.models import STATUS_DOWNLOADED, STATUS_DOWNLOADING, STATUS_NOT_DOWNLOADED

        assert self._store is not None
        store = self._store
        dest_dir = store.feed_dir(feed)
        total = len(to_download)

        self._progress_bar.setRange(0, max(1, total * 100))
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self._set_action_status(f"Downloading 0 / {total} — 0%", timeout_ms=0)

        def _download_all():
            downloaded = 0
            for idx, (_, ep) in enumerate(to_download):
                ep.status = STATUS_DOWNLOADING

                def _progress_cb(bytes_done: int, total_bytes: int, *, _idx: int = idx, _title: str = (ep.title or "Episode")):
                    self.download_progress.emit(_idx, total, bytes_done, total_bytes, _title)

                try:
                    path = download_episode(ep, dest_dir, progress_cb=_progress_cb)
                    embed_feed_artwork(path, feed.artwork_url)
                    ep.downloaded_path = str(path)
                    ep.status = STATUS_DOWNLOADED
                    downloaded += 1
                    # Snap progress to the next completed episode boundary.
                    self.download_progress.emit(downloaded, total, 0, 0, ep.title or "Episode")
                except Exception as exc:
                    log.warning("Download failed for %s: %s", ep.title, exc)
                    ep.status = STATUS_NOT_DOWNLOADED
            store.update_feeds([feed])
            return downloaded

        worker = Worker(_download_all)
        worker.signals.result.connect(
            lambda count: self._on_download_then_sync_done(count, feed))
        worker.signals.error.connect(self._on_add_error)
        worker.signals.finished.connect(
            lambda: self._add_to_ipod_btn.setEnabled(True))
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_download_progress(
        self,
        completed_episodes: int,
        total_episodes: int,
        bytes_downloaded: int,
        total_bytes: int,
        episode_title: str,
    ) -> None:
        """Update UI with live per-episode download progress."""
        total_units = max(1, total_episodes * 100)

        if total_bytes > 0:
            percent = min(100, max(0, int((bytes_downloaded * 100) / total_bytes)))
            value = min(total_units, completed_episodes * 100 + percent)
            self._progress_bar.setRange(0, total_units)
            self._progress_bar.setValue(value)
            title_suffix = f" · {episode_title}" if episode_title else ""
            self._set_action_status(
                f"Downloading {completed_episodes} / {total_episodes} — "
                f"{percent}% ({format_size(bytes_downloaded)} / {format_size(total_bytes)})"
                f"{title_suffix}",
                timeout_ms=0,
            )
            return

        # Unknown total size: keep completed episode progress and show bytes so far.
        value = min(total_units, completed_episodes * 100)
        self._progress_bar.setRange(0, total_units)
        self._progress_bar.setValue(value)
        title_suffix = f" · {episode_title}" if episode_title else ""
        if bytes_downloaded > 0:
            self._set_action_status(
                f"Downloading {completed_episodes} / {total_episodes} — "
                f"{format_size(bytes_downloaded)}{title_suffix}",
                timeout_ms=0,
            )
        else:
            self._set_action_status(
                f"Downloading {completed_episodes} / {total_episodes}…{title_suffix}",
                timeout_ms=0,
            )

    def _on_download_then_sync_done(self, count: int, feed) -> None:
        """Downloads finished — refresh UI and emit the sync plan."""
        from PodcastManager.models import STATUS_DOWNLOADED

        self._progress_bar.hide()
        self._show_episodes(self._selected_feed)

        # Merge newly-downloaded with previously-ready episodes, but only for
        # episodes explicitly selected by the user for this action.
        ready = list(getattr(self, '_pending_ready', []))
        target_guids = set(getattr(self, '_pending_target_guids', set()))
        for ep in feed.episodes:
            if target_guids and ep.guid not in target_guids:
                continue
            if ep.status == STATUS_DOWNLOADED and ep.downloaded_path:
                if not any(r_ep.guid == ep.guid for _, r_ep in ready):
                    ready.append((0, ep))

        # Reset one-shot pending state.
        self._pending_ready = []
        self._pending_target_guids = set()

        if not ready:
            self._set_action_status("All selected downloads failed")
            return

        self._set_action_status(
            f"Downloaded {count}, sending to sync…", timeout_ms=0)
        self._build_and_emit_plan(ready, feed)

    def _build_and_emit_plan(self, ready_episodes, feed) -> None:
        """Build a SyncPlan from ready episodes and emit to main app."""
        from PodcastManager.models import STATUS_DOWNLOADED

        episodes_for_plan = [
            (ep, feed) for _, ep in ready_episodes
            if ep.status == STATUS_DOWNLOADED and ep.downloaded_path
        ]

        if not episodes_for_plan:
            self._set_action_status("No episodes ready to sync")
            self._add_to_ipod_btn.setEnabled(True)
            return

        # Get current iPod tracks for dedup
        ipod_tracks: list[dict] = []
        try:
            from ..app import iTunesDBCache
            cache = iTunesDBCache.get_instance()
            ipod_tracks = cache.get_tracks() or []
        except Exception:
            pass

        from PodcastManager.podcast_sync import build_podcast_sync_plan
        plan = build_podcast_sync_plan(episodes_for_plan, ipod_tracks)

        if not plan.to_add:
            self._set_action_status("All selected episodes are already on iPod")
            self._add_to_ipod_btn.setEnabled(True)
            return

        n = len(plan.to_add)
        self._set_action_status(
            f"Sending {n} episode{'s' if n != 1 else ''} to sync…")

        self.podcast_sync_requested.emit(plan)
        self._add_to_ipod_btn.setEnabled(True)

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

        from SyncEngine.fingerprint_diff_engine import SyncPlan, SyncItem, SyncAction, StorageSummary

        ipod_tracks: list[dict] = []
        try:
            from ..app import iTunesDBCache
            cache = iTunesDBCache.get_instance()
            ipod_tracks = cache.get_tracks() or []
        except Exception:
            pass

        tracks_by_db_id = {t.get("db_id", 0): t for t in ipod_tracks if t.get("db_id")}

        to_remove: list[SyncItem] = []
        bytes_to_remove = 0
        for ep in episodes:
            ipod_track = tracks_by_db_id.get(ep.ipod_db_id)
            if not ipod_track:
                continue
            to_remove.append(SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                ipod_track=ipod_track,
                description=f"\U0001f399 {self._selected_feed.title} \u2014 {ep.title}",
            ))
            bytes_to_remove += ipod_track.get("size", 0)

        if not to_remove:
            self._set_action_status("Episodes not found on iPod")
            return

        plan = SyncPlan(
            to_remove=to_remove,
            storage=StorageSummary(bytes_to_remove=bytes_to_remove),
        )
        n = len(to_remove)
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

    def _set_feed_art_placeholder(self) -> None:
        """Set a crisp HiDPI-safe placeholder icon in the feed artwork slot."""
        placeholder = glyph_pixmap("broadcast", (52), Colors.TEXT_TERTIARY)
        if placeholder:
            pm = scale_pixmap_for_display(
                placeholder,
                52,
                52,
                widget=self._feed_art,
                aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
                transform_mode=Qt.TransformationMode.SmoothTransformation,
            )
            self._feed_art.setPixmap(pm)
            self._feed_art.setText("")
            return
        self._feed_art.setText("◎")

    def _load_feed_artwork(self, url: str) -> None:
        """Load feed artwork for the header panel in background."""
        if url in _artwork_cache:
            art_w = max(1, self._feed_art.width())
            art_h = max(1, self._feed_art.height())
            pm = scale_pixmap_for_display(
                _artwork_cache[url],
                art_w,
                art_h,
                widget=self._feed_art,
                aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
                transform_mode=Qt.TransformationMode.SmoothTransformation,
            )
            self._feed_art.setPixmap(pm)
            self._feed_art.setText("")
            return

        from ..app import Worker, ThreadPoolSingleton
        import requests

        target_url = url

        def _fetch():
            resp = requests.get(target_url, timeout=10)
            resp.raise_for_status()
            return resp.content

        worker = Worker(_fetch)
        worker.signals.result.connect(
            lambda data, u=target_url: self._on_feed_artwork_loaded(data, u)
        )
        worker.signals.error.connect(
            lambda _: log.debug("Failed to load artwork: %s", target_url)
        )
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_feed_artwork_loaded(self, data: bytes, url: str) -> None:
        img = QImage()
        if not img.loadFromData(data):
            return
        full_pm = QPixmap.fromImage(img)
        _artwork_cache[url] = full_pm

        # Update header art if still showing the same feed
        if self._selected_feed and self._selected_feed.artwork_url == url:
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

        # Update feed list item icon too
        self._update_feed_list_icon(url, full_pm)

    def _load_feed_list_artwork(self, url: str, row: int) -> None:
        """Load a feed's artwork for its list item thumbnail."""
        from ..app import Worker, ThreadPoolSingleton
        import requests

        target_url = url

        def _fetch():
            resp = requests.get(target_url, timeout=10)
            resp.raise_for_status()
            return resp.content

        worker = Worker(_fetch)
        worker.signals.result.connect(
            lambda data, u=target_url: self._on_list_artwork_loaded(data, u)
        )
        worker.signals.error.connect(
            lambda _: log.debug("Failed to load list artwork: %s", target_url)
        )
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_list_artwork_loaded(self, data: bytes, url: str) -> None:
        img = QImage()
        if not img.loadFromData(data):
            return
        full_pm = QPixmap.fromImage(img)
        _artwork_cache[url] = full_pm
        self._update_feed_list_icon(url, full_pm)

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
            if feed.artwork_url == url:
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
        """Set action bar status text with auto-clear."""
        self._action_status.setText(text)
        if timeout_ms > 0 and text:
            QTimer.singleShot(timeout_ms, lambda: self._clear_action_if(text))

    def _clear_action_if(self, expected: str) -> None:
        if self._action_status.text() == expected:
            self._action_status.setText("")
