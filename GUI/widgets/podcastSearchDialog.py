"""Podcast search dialog — iTunes Search API powered discovery.

Modal dialog that lets users search for podcasts by name and subscribe
to them.  Search runs in a background worker thread to keep the UI
responsive.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QImage
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..styles import (
    Colors,
    Metrics,
    FONT_FAMILY,
    accent_btn_css,
    btn_css,
    font_scaled,
    make_label,
    scaled,
    scrollbar_css,
    LABEL_SECONDARY,
)
from ..glyphs import glyph_pixmap

log = logging.getLogger(__name__)


class PodcastSearchDialog(QDialog):
    """Modal dialog for searching and subscribing to podcasts.

    Emits ``subscribed(str)`` with the RSS feed URL when the user
    clicks Subscribe on a search result.
    """

    subscribed = pyqtSignal(str)  # feed_url

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Search Podcasts")
        self.setMinimumSize(scaled(560), scaled(480))
        self.resize(scaled(620), scaled(540))
        self.setStyleSheet(f"""
            QDialog {{
                background: {Colors.DIALOG_BG};
            }}
        """)

        self._build_ui()
        self._results: list = []

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled(16), scaled(16), scaled(16), scaled(16))
        layout.setSpacing(scaled(12))

        # ── Search bar ───────────────────────────────────────────────────
        search_row = QHBoxLayout()
        search_row.setSpacing(scaled(8))

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search for podcasts…")
        self._search_input.setFont(QFont(FONT_FAMILY, font_scaled(Metrics.FONT_MD)))
        self._search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: {scaled(8)}px {scaled(12)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {Colors.BORDER_FOCUS};
            }}
        """)
        self._search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_input, stretch=1)

        self._search_btn = QPushButton("Search")
        self._search_btn.setFont(QFont(FONT_FAMILY, font_scaled(Metrics.FONT_MD)))
        self._search_btn.setStyleSheet(accent_btn_css())
        self._search_btn.setFixedHeight(scaled(36))
        self._search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self._search_btn)

        layout.addLayout(search_row)

        # ── Status label ─────────────────────────────────────────────────
        self._status_label = make_label(
            "Enter a search term to find podcasts",
            size=font_scaled(Metrics.FONT_SM),
            style=LABEL_SECONDARY(),
        )
        layout.addWidget(self._status_label)

        # ── Results scroll area ──────────────────────────────────────────
        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(scaled(4))
        self._results_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._results_container)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
            }}
            {scrollbar_css()}
        """)
        layout.addWidget(scroll, stretch=1)

        # ── Manual RSS row ───────────────────────────────────────────────
        rss_row = QHBoxLayout()
        rss_row.setSpacing(scaled(8))

        rss_label = make_label(
            "Or paste RSS URL:",
            size=font_scaled(Metrics.FONT_SM),
            style=LABEL_SECONDARY(),
        )
        rss_row.addWidget(rss_label)

        self._rss_input = QLineEdit()
        self._rss_input.setPlaceholderText("https://example.com/feed.xml")
        self._rss_input.setFont(QFont(FONT_FAMILY, font_scaled(Metrics.FONT_SM)))
        self._rss_input.setStyleSheet(f"""
            QLineEdit {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: {scaled(6)}px {scaled(10)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {Colors.BORDER_FOCUS};
            }}
        """)
        self._rss_input.returnPressed.connect(self._on_add_rss)
        rss_row.addWidget(self._rss_input, stretch=1)

        self._rss_btn = QPushButton("Add Feed")
        self._rss_btn.setFont(QFont(FONT_FAMILY, font_scaled(Metrics.FONT_SM)))
        self._rss_btn.setStyleSheet(accent_btn_css())
        self._rss_btn.setFixedHeight(scaled(32))
        self._rss_btn.clicked.connect(self._on_add_rss)
        rss_row.addWidget(self._rss_btn)

        layout.addLayout(rss_row)

        # ── Close button ─────────────────────────────────────────────────
        close_btn = QPushButton("Close")
        close_btn.setFont(QFont(FONT_FAMILY, font_scaled(Metrics.FONT_MD)))
        close_btn.setStyleSheet(btn_css())
        close_btn.setFixedHeight(scaled(36))
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    # ── Slots ────────────────────────────────────────────────────────────

    def _on_search(self):
        query = self._search_input.text().strip()
        if not query:
            return

        self._search_btn.setEnabled(False)
        self._status_label.setText("Searching…")

        from ..app import Worker, ThreadPoolSingleton
        from PodcastManager.itunes_search import search_podcasts

        worker = Worker(search_podcasts, query)
        worker.signals.result.connect(self._on_search_results)
        worker.signals.error.connect(self._on_search_error)
        worker.signals.finished.connect(lambda: self._search_btn.setEnabled(True))
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_search_results(self, results):
        self._results = results
        self._clear_results()

        if not results:
            self._status_label.setText("No podcasts found")
            return

        self._status_label.setText(f"Found {len(results)} podcast{'s' if len(results) != 1 else ''}")

        for result in results:
            card = _SearchResultCard(result, self)
            card.subscribe_clicked.connect(self._on_subscribe)
            self._results_layout.insertWidget(
                self._results_layout.count() - 1,  # Before stretch
                card,
            )

    def _on_search_error(self, error_tuple):
        _, value, _ = error_tuple
        self._status_label.setText(f"Search failed: {value}")
        self._search_btn.setEnabled(True)

    def _on_subscribe(self, feed_url: str):
        self.subscribed.emit(feed_url)

    def _on_add_rss(self):
        url = self._rss_input.text().strip()
        if url and (url.startswith("http://") or url.startswith("https://")):
            self.subscribed.emit(url)
            self._rss_input.clear()

    def _clear_results(self):
        while self._results_layout.count() > 1:  # Keep the stretch
            item = self._results_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget:
                    widget.deleteLater()


class _SearchResultCard(QFrame):
    """A single search result row with podcast info and Subscribe button."""

    subscribe_clicked = pyqtSignal(str)  # feed_url

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self._result = result
        self.setStyleSheet(f"""
            _SearchResultCard {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
            }}
            _SearchResultCard:hover {{
                background: {Colors.SURFACE_HOVER};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(scaled(10), scaled(8), scaled(10), scaled(8))
        layout.setSpacing(scaled(10))

        # Artwork placeholder
        self._art_label = QLabel()
        self._art_label.setFixedSize(scaled(56), scaled(56))
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.setStyleSheet(f"""
            background: {Colors.SURFACE_RAISED};
            border-radius: {Metrics.BORDER_RADIUS_SM}px;
            color: {Colors.TEXT_TERTIARY};
            font-size: {font_scaled(20)}px;
        """)
        self._art_label.setText("◎")
        _search_px = glyph_pixmap("broadcast", scaled(24), Colors.TEXT_TERTIARY)
        if _search_px:
            self._art_label.setPixmap(_search_px)
        layout.addWidget(self._art_label)

        # Load artwork in background
        if result.artwork_url_small:
            self._load_artwork(result.artwork_url_small)

        # Info column
        info = QVBoxLayout()
        info.setSpacing(scaled(2))

        title_lbl = make_label(
            result.title,
            size=font_scaled(Metrics.FONT_MD),
            weight=QFont.Weight.DemiBold,
        )
        title_lbl.setWordWrap(True)
        title_lbl.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        info.addWidget(title_lbl)

        details = result.artist
        if result.genre:
            details += f"  ·  {result.genre}"
        if result.track_count:
            details += f"  ·  {result.track_count} episodes"
        detail_lbl = make_label(
            details,
            size=font_scaled(Metrics.FONT_SM),
            style=LABEL_SECONDARY(),
        )
        detail_lbl.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        info.addWidget(detail_lbl)

        layout.addLayout(info, stretch=1)

        # Subscribe button
        sub_btn = QPushButton("Subscribe")
        sub_btn.setFont(QFont(FONT_FAMILY, font_scaled(Metrics.FONT_SM)))
        sub_btn.setStyleSheet(accent_btn_css())
        sub_btn.setFixedSize(scaled(90), scaled(32))
        sub_btn.clicked.connect(lambda: self.subscribe_clicked.emit(result.feed_url))
        layout.addWidget(sub_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def _load_artwork(self, url: str):
        """Load artwork thumbnail in background."""
        from ..app import Worker, ThreadPoolSingleton
        import requests

        def _fetch():
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.content

        worker = Worker(_fetch)
        worker.signals.result.connect(self._on_artwork_loaded)
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_artwork_loaded(self, data: bytes):
        img = QImage()
        if img.loadFromData(data):
            dpr = self._art_label.devicePixelRatio()
            phys = round(scaled(56) * dpr)
            pm = QPixmap.fromImage(img).scaled(
                phys, phys,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pm.setDevicePixelRatio(dpr)
            self._art_label.setPixmap(pm)
            self._art_label.setText("")
