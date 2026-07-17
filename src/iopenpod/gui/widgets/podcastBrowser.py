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

import html
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QMouseEvent,
    QPainter,
    QPalette,
    QPixmap,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
    context_menu_css,
    make_label,
    make_separator,
    progress_bar_css,
    sidebar_item_view_css,
    spin_css,
)
from .browserChrome import (
    BrowserHeroHeader,
    BrowserPane,
    chrome_action_btn_css,
    style_browser_splitter,
)
from .formatters import format_size
from .podcastStates import PodcastStatePanel

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from iopenpod.application.services import (
        DeviceSessionService,
        LibraryCacheLike,
        LibraryService,
        SettingsService,
    )
    from iopenpod.podcasts.models import PodcastFeed


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


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _episode_listened_override(ep) -> bool | None:
    override = getattr(ep, "listened_override", None)
    if override is None:
        return None
    return bool(override)


def _episode_is_listened(ep) -> bool:
    override = _episode_listened_override(ep)
    if override is not None:
        return override
    return (
        _coerce_int(getattr(ep, "play_count", 0)) > 0
        or _coerce_int(getattr(ep, "last_played", 0)) > 0
    )


def _set_episode_listened(ep, listened: bool) -> None:
    if listened:
        ep.listened_override = True
        ep.play_count = max(1, _coerce_int(getattr(ep, "play_count", 0)))
        if _coerce_int(getattr(ep, "last_played", 0)) <= 0:
            ep.last_played = int(time.time())
        return

    from iopenpod.podcasts.models import STATUS_ON_IPOD

    ep.play_count = 0
    ep.last_played = 0
    ep.listened_override = (
        False
        if getattr(ep, "status", "") == STATUS_ON_IPOD
        and bool(getattr(ep, "ipod_db_track_id", 0))
        else None
    )


# ── Podcast episode list ─────────────────────────────────────────────────────

_PODCAST_EPISODE_COLUMNS = [
    "Title",
    "Description Text",
    "ep_status",
    "length",
    "date_added",
    "size",
]
_COMBINED_FEED_COLUMNS = [
    "Title",
    "podcast_feed_title",
    "Description Text",
    "ep_status",
    "length",
    "date_added",
    "size",
]
_COMBINED_FEED_KEY = "__iopenpod_combined_feed__"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CSS_RGBA_RE = re.compile(r"rgba?\((\d+),(\d+),(\d+)(?:,(\d+))?\)")
_EPISODE_DESCRIPTION_MAX_CHARS = 1600
_EPISODE_CARD_MARGIN_X = 12
_EPISODE_CARD_MARGIN_Y = 6
_EPISODE_CARD_PADDING = 14
_EPISODE_CARD_RADIUS = 8
_EPISODE_CARD_ARTWORK_SIZE = 54
_EPISODE_CARD_VPAD = 10
_EPISODE_CARD_SPACING = 4
_EPISODE_TOP_ROW_GAP = 10
_EPISODE_TITLE_LABEL_GAP = 2
_EPISODE_ACTION_ROW_HEIGHT = 24
_EPISODE_ACTION_BUTTON_GAP = 6
_EPISODE_ACTION_ICON_BUTTON_WIDTH = 30
_EPISODE_DESC_COLLAPSED_LINES = 2
_EPISODE_COLLAPSED_HEIGHT = 158
_EPISODE_ARTWORK_COLLAPSED_HEIGHT = 174
_EPISODE_EXPANDED_MAX_LINES = 14
_EPISODE_ROW_GAP = 8
_EPISODE_ROW_BUFFER = 4


def _episode_description_text(description: str) -> str:
    """Return compact plain text suitable for the episode table."""
    text = _HTML_TAG_RE.sub(" ", str(description or ""))
    text = html.unescape(text)
    text = " ".join(text.split())
    if len(text) > _EPISODE_DESCRIPTION_MAX_CHARS:
        return f"{text[:_EPISODE_DESCRIPTION_MAX_CHARS - 3].rstrip()}..."
    return text


def _episode_key(feed, episode) -> str:
    """Stable table key for an episode within a feed."""
    return f"{getattr(feed, 'feed_url', '')}\0{getattr(episode, 'guid', '')}"


def _qcolor(value: str) -> QColor:
    """Parse theme CSS colors for direct QPainter usage."""
    text = str(value or "").replace(" ", "")
    match = _CSS_RGBA_RE.fullmatch(text)
    if match:
        r, g, b, a = match.groups()
        return QColor(int(r), int(g), int(b), int(a or 255))
    return QColor(value)


def _is_remote_artwork_source(source: str) -> bool:
    from iopenpod.podcasts.artwork import is_remote_artwork_source

    return is_remote_artwork_source(source)


def _resolve_local_artwork_path(source: str) -> Path | None:
    from iopenpod.podcasts.artwork import resolve_local_artwork_path

    return resolve_local_artwork_path(source)


def _read_local_artwork_bytes(source: str) -> bytes | None:
    from iopenpod.podcasts.artwork import read_local_artwork_bytes

    return read_local_artwork_bytes(source)


def _load_artwork_bytes(source: str) -> bytes | None:
    from iopenpod.podcasts.artwork import load_artwork_bytes

    return load_artwork_bytes(source)


def _status_accent(status: str) -> str:
    if status == "On iPod":
        return Colors.SUCCESS
    if status == "Downloaded":
        return Colors.ACCENT
    if status == "Listened":
        return Colors.WARNING
    if "Downloading" in status:
        return Colors.WARNING
    return Colors.TEXT_TERTIARY


def _is_state_status(status: str) -> bool:
    return status in {"On iPod", "Downloaded", "Listened"} or "Downloading" in status


def _episode_meta_text(row: dict) -> str:
    parts = []
    date_text = _fmt_date(float(row.get("date_added") or 0))
    if date_text:
        parts.append(date_text)
    duration_ms = int(row.get("length") or 0)
    if duration_ms > 0:
        parts.append(_fmt_duration(duration_ms // 1000))
    size = int(row.get("size") or 0)
    if size > 0:
        parts.append(format_size(size))
    status = str(row.get("ep_status") or "")
    if row.get("_was_listened") and status != "Listened":
        parts.append("Listened")
    if status and not _is_state_status(status) and status not in parts:
        parts.append(status)
    return "  |  ".join(parts) if parts else "Episode"


def _wrap_lines(
    text: str,
    metrics: QFontMetrics,
    width: int,
    max_lines: int | None = None,
) -> tuple[list[str], bool]:
    """Word-wrap plain text into measured lines."""
    clean = " ".join(str(text or "").split())
    if not clean or width <= 0:
        return [], False
    if max_lines is not None and max_lines <= 0:
        return [], True

    words = clean.split(" ")
    lines: list[str] = []
    line = ""
    truncated = False

    for idx, word in enumerate(words):
        candidate = word if not line else f"{line} {word}"
        if metrics.horizontalAdvance(candidate) <= width:
            line = candidate
            continue

        if line:
            lines.append(line)
            line = word
        else:
            lines.append(metrics.elidedText(word, Qt.TextElideMode.ElideRight, width))
            line = ""

        if max_lines is not None and len(lines) >= max_lines:
            rest = " ".join(([line] if line else []) + words[idx + 1:])
            if rest:
                lines[-1] = metrics.elidedText(
                    f"{lines[-1]} {rest}",
                    Qt.TextElideMode.ElideRight,
                    width,
                )
                truncated = True
            return lines[:max_lines], truncated

    if line:
        lines.append(line)

    if max_lines is not None and len(lines) > max_lines:
        visible = lines[:max_lines]
        visible[-1] = metrics.elidedText(
            " ".join(lines[max_lines - 1:]),
            Qt.TextElideMode.ElideRight,
            width,
        )
        return visible, True

    return lines, truncated


class _PodcastCardMouseButton(QPushButton):
    """Button that does not steal the row's selection state."""

    def mousePressEvent(self, e: QMouseEvent | None) -> None:
        if e is not None:
            e.accept()
        super().mousePressEvent(e)


class _PodcastEpisodeCard(QFrame):
    clicked = pyqtSignal(int, object)
    more_requested = pyqtSignal(int)
    add_requested = pyqtSignal(int)
    remove_requested = pyqtSignal(int)
    context_requested = pyqtSignal(int, QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row_index = -1
        self._row_key = ""
        self._artwork_source = ""
        self._selected = False

        self.setObjectName("podcastEpisodeCard")
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context_menu)

        self._art_label = QLabel(self)
        self._art_label.setObjectName("podcastEpisodeArtwork")
        self._art_label.setFixedSize(
            _EPISODE_CARD_ARTWORK_SIZE,
            _EPISODE_CARD_ARTWORK_SIZE,
        )
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.setStyleSheet(f"""
            QLabel#podcastEpisodeArtwork {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 7px;
            }}
        """)
        self._art_label.hide()

        self._podcast_label = make_label(
            "",
            size=Metrics.FONT_SM,
            weight=QFont.Weight.DemiBold,
            style=f"color: {Colors.ACCENT_LIGHT};",
        )
        self._podcast_label.setParent(self)
        self._podcast_label.setObjectName("podcastEpisodePodcast")
        self._podcast_label.setWordWrap(False)

        self._title_label = make_label(
            "",
            size=Metrics.FONT_MD,
            weight=QFont.Weight.DemiBold,
        )
        self._title_label.setParent(self)
        self._title_label.setObjectName("podcastEpisodeTitle")
        self._title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._title_label.setWordWrap(True)
        self._title_label.setMaximumHeight(42)

        self._status_label = make_label(
            "",
            size=Metrics.FONT_SM,
            weight=QFont.Weight.DemiBold,
        )
        self._status_label.setParent(self)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setMinimumWidth(86)
        self._status_label.setMaximumWidth(132)

        self._meta_label = make_label("", size=Metrics.FONT_SM, style=LABEL_SECONDARY())
        self._meta_label.setParent(self)
        self._meta_label.setObjectName("podcastEpisodeMeta")
        self._meta_label.setWordWrap(False)
        self._meta_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._meta_label.setFixedHeight(QFontMetrics(self._meta_label.font()).lineSpacing())

        self._description_label = make_label(
            "",
            size=Metrics.FONT_SM,
            style=LABEL_SECONDARY(),
            wrap=True,
        )
        self._description_label.setParent(self)
        self._description_label.setObjectName("podcastEpisodeDescription")
        self._description_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._description_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )

        self._action_row = QWidget(self)
        self._action_row.setObjectName("podcastEpisodeActionRow")
        self._action_row.setFixedHeight(_EPISODE_ACTION_ROW_HEIGHT)

        self._add_btn = _PodcastCardMouseButton("Add to iPod", self._action_row)
        self._add_btn.setObjectName("podcastEpisodeAddButton")
        self._add_btn.setToolTip("Add this episode to iPod")
        self._add_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        self._add_btn.setStyleSheet(
            btn_css(
                bg=Colors.ACCENT_DIM,
                bg_hover=Colors.ACCENT_HOVER,
                bg_press=Colors.ACCENT_PRESS,
                fg=Colors.TEXT_ON_ACCENT,
                border=f"1px solid {Colors.ACCENT_BORDER}",
                padding="3px 9px",
                radius=Metrics.BORDER_RADIUS_SM,
            )
        )
        add_icon = glyph_icon("plus", 13, Colors.TEXT_ON_ACCENT)
        if add_icon:
            self._add_btn.setIcon(add_icon)
            self._add_btn.setIconSize(QSize(13, 13))
        add_metrics = QFontMetrics(self._add_btn.font())
        self._add_btn_full_text = "Add to iPod"
        self._add_btn_full_width = add_metrics.horizontalAdvance(
            self._add_btn_full_text
        ) + 34
        self._add_btn.setFixedSize(
            self._add_btn_full_width,
            _EPISODE_ACTION_ROW_HEIGHT,
        )
        self._add_btn.clicked.connect(lambda: self.add_requested.emit(self._row_index))

        self._remove_btn = _PodcastCardMouseButton(
            "Remove from iPod",
            self._action_row,
        )
        self._remove_btn.setObjectName("podcastEpisodeRemoveButton")
        self._remove_btn.setToolTip("Remove this episode from iPod")
        self._remove_btn.setFont(
            QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold)
        )
        self._remove_btn.setStyleSheet(
            btn_css(
                bg="transparent",
                bg_hover=Colors.DANGER_DIM,
                bg_press=Colors.DANGER_HOVER,
                fg=Colors.DANGER,
                border=f"1px solid {Colors.DANGER_BORDER}",
                padding="3px 9px",
                radius=Metrics.BORDER_RADIUS_SM,
            )
        )
        remove_icon = glyph_icon("minus", 13, Colors.DANGER)
        if remove_icon:
            self._remove_btn.setIcon(remove_icon)
            self._remove_btn.setIconSize(QSize(13, 13))
        remove_metrics = QFontMetrics(self._remove_btn.font())
        self._remove_btn_full_text = "Remove from iPod"
        self._remove_btn_full_width = remove_metrics.horizontalAdvance(
            self._remove_btn_full_text
        ) + 34
        self._remove_btn.setFixedSize(
            self._remove_btn_full_width,
            _EPISODE_ACTION_ROW_HEIGHT,
        )
        self._remove_btn.clicked.connect(
            lambda: self.remove_requested.emit(self._row_index)
        )

        self._more_btn = _PodcastCardMouseButton("More", self._action_row)
        self._more_btn.setObjectName("podcastEpisodeMoreButton")
        self._more_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        self._more_btn.setStyleSheet(
            btn_css(padding="3px 10px", radius=Metrics.BORDER_RADIUS_SM)
        )
        btn_metrics = QFontMetrics(self._more_btn.font())
        self._more_btn.setFixedSize(
            max(
                btn_metrics.horizontalAdvance("More"),
                btn_metrics.horizontalAdvance("Show less"),
            )
            + 24,
            _EPISODE_ACTION_ROW_HEIGHT,
        )
        self._more_btn.clicked.connect(lambda: self.more_requested.emit(self._row_index))

        self._install_child_event_filters()
        self._apply_style()

    def _install_child_event_filters(self) -> None:
        for child in (
            self._art_label,
            self._podcast_label,
            self._title_label,
            self._status_label,
            self._meta_label,
            self._description_label,
            self._action_row,
            self._add_btn,
            self._remove_btn,
            self._more_btn,
        ):
            child.installEventFilter(self)

    def bind(
        self,
        *,
        row_index: int,
        row: dict,
        row_key: str,
        selected: bool,
        expanded: bool,
        description_text: str,
        show_more: bool,
        show_artwork: bool,
        artwork_source: str,
        artwork_pixmap: QPixmap | None,
    ) -> None:
        self._row_index = row_index
        self._row_key = row_key
        self._artwork_source = artwork_source if show_artwork else ""
        self._selected = selected

        self._art_label.setVisible(show_artwork)
        if show_artwork:
            if artwork_pixmap is not None:
                self._set_artwork_pixmap(artwork_pixmap)
            else:
                self._art_label.clear()
                self._art_label.setText("◎")
        else:
            self._art_label.clear()
            self._art_label.setText("")

        podcast_title = str(row.get("podcast_feed_title") or "")
        self._podcast_label.setText(podcast_title)
        self._podcast_label.setVisible(bool(podcast_title))
        self._title_label.setText(str(row.get("Title") or "Untitled Episode"))
        self._meta_label.setText(_episode_meta_text(row))
        self._description_label.setText(description_text or "No description available.")
        self._set_description_height(description_text, expanded)

        status = str(row.get("ep_status") or "")
        if _is_state_status(status):
            self._status_label.setText(status)
            self._status_label.show()
        else:
            self._status_label.hide()

        self._more_btn.setText("Show less" if expanded else "More")
        self._more_btn.setVisible(show_more)
        self._add_btn.setVisible(bool(row.get("_can_add_to_ipod")))
        self._remove_btn.setVisible(bool(row.get("_can_remove_from_ipod")))
        self._update_card_layout()
        self._apply_style()

    def set_artwork(self, source: str, pixmap: QPixmap) -> None:
        if not self._art_label.isVisible() or source != self._artwork_source:
            return
        self._set_artwork_pixmap(pixmap)

    def _set_artwork_pixmap(self, pixmap: QPixmap) -> None:
        size = _EPISODE_CARD_ARTWORK_SIZE
        pm = scale_pixmap_for_display(
            pixmap,
            size,
            size,
            widget=self._art_label,
            aspect_mode=Qt.AspectRatioMode.KeepAspectRatio,
            transform_mode=Qt.TransformationMode.SmoothTransformation,
        )
        self._art_label.setPixmap(pm)
        self._art_label.setText("")

    def _set_description_height(self, text: str, expanded: bool) -> None:
        metrics = QFontMetrics(self._description_label.font())
        if expanded:
            line_count = max(
                1,
                min(_EPISODE_EXPANDED_MAX_LINES, str(text or "").count("\n") + 1),
            )
        else:
            line_count = _EPISODE_DESC_COLLAPSED_LINES
        self._description_label.setMinimumHeight(line_count * metrics.lineSpacing())
        self._description_label.setMaximumHeight(16777215)

    def _title_height_for_width(self, width: int) -> int:
        metrics = QFontMetrics(self._title_label.font())
        if width <= 0:
            return metrics.lineSpacing()
        text = self._title_label.text() or "Untitled Episode"
        bounds = metrics.boundingRect(
            QRect(0, 0, width, 200),
            Qt.TextFlag.TextWordWrap,
            text,
        )
        return min(
            max(metrics.lineSpacing(), bounds.height()),
            max(metrics.lineSpacing(), self._title_label.maximumHeight()),
        )

    def _update_card_layout(self) -> None:
        left = _EPISODE_CARD_PADDING
        top = _EPISODE_CARD_VPAD
        width = max(1, self.width() - 2 * _EPISODE_CARD_PADDING)

        art_visible = not self._art_label.isHidden()
        art_size = _EPISODE_CARD_ARTWORK_SIZE if art_visible else 0
        if art_visible:
            self._art_label.setGeometry(left, top, art_size, art_size)
            title_x = left + art_size + _EPISODE_TOP_ROW_GAP
        else:
            self._art_label.setGeometry(left, top, 0, 0)
            title_x = left

        status_visible = not self._status_label.isHidden()
        status_w = self._status_label.maximumWidth() if status_visible else 0
        status_gap = _EPISODE_TOP_ROW_GAP if status_visible else 0
        title_w = max(1, left + width - title_x - status_gap - status_w)

        podcast_visible = not self._podcast_label.isHidden()
        podcast_h = (
            QFontMetrics(self._podcast_label.font()).lineSpacing()
            if podcast_visible
            else 0
        )
        title_h = self._title_height_for_width(title_w)
        title_y = top
        if podcast_visible:
            self._podcast_label.setGeometry(title_x, top, title_w, podcast_h)
            title_y = top + podcast_h + _EPISODE_TITLE_LABEL_GAP
        else:
            self._podcast_label.setGeometry(title_x, top, title_w, 0)
        self._title_label.setGeometry(title_x, title_y, title_w, title_h)

        if status_visible:
            status_h = self._status_label.sizeHint().height()
            self._status_label.setGeometry(
                left + width - status_w,
                top,
                status_w,
                status_h,
            )
        else:
            self._status_label.setGeometry(left + width, top, 0, 0)

        title_block_h = (
            podcast_h
            + (_EPISODE_TITLE_LABEL_GAP if podcast_visible else 0)
            + title_h
        )
        top_h = max(art_size, title_block_h)

        meta_y = top + top_h + _EPISODE_CARD_SPACING
        meta_h = self._meta_label.minimumHeight()
        self._meta_label.setGeometry(left, meta_y, width, meta_h)

        desc_y = meta_y + meta_h + _EPISODE_CARD_SPACING
        action_y = max(
            desc_y + self._description_label.minimumHeight() + _EPISODE_CARD_SPACING,
            self.height() - _EPISODE_CARD_VPAD - _EPISODE_ACTION_ROW_HEIGHT,
        )
        self._action_row.setGeometry(
            left,
            action_y,
            width,
            _EPISODE_ACTION_ROW_HEIGHT,
        )

        more_visible = not self._more_btn.isHidden()
        more_w = self._more_btn.width() if more_visible else 0
        action_limit = width
        if more_visible:
            action_limit = max(0, width - more_w - _EPISODE_ACTION_BUTTON_GAP)

        action_x = 0
        for button, full_text, full_width in (
            (self._add_btn, self._add_btn_full_text, self._add_btn_full_width),
            (
                self._remove_btn,
                self._remove_btn_full_text,
                self._remove_btn_full_width,
            ),
        ):
            if button.isHidden():
                button.setGeometry(0, 0, 0, 0)
                continue
            compact = (
                action_x + full_width > action_limit
                and not button.icon().isNull()
            )
            target_text = "" if compact else full_text
            target_w = (
                _EPISODE_ACTION_ICON_BUTTON_WIDTH if compact else full_width
            )
            if button.text() != target_text:
                button.setText(target_text)
            if button.width() != target_w:
                button.setFixedWidth(target_w)
            button.setGeometry(
                action_x,
                0,
                target_w,
                _EPISODE_ACTION_ROW_HEIGHT,
            )
            action_x += target_w + _EPISODE_ACTION_BUTTON_GAP

        self._more_btn.setGeometry(
            max(0, width - self._more_btn.width()),
            0,
            self._more_btn.width(),
            _EPISODE_ACTION_ROW_HEIGHT,
        )

        desc_h = max(
            self._description_label.minimumHeight(),
            action_y - desc_y - _EPISODE_CARD_SPACING,
        )
        self._description_label.setGeometry(left, desc_y, width, desc_h)

    def _apply_style(self) -> None:
        bg = Colors.ACCENT_MUTED if self._selected else Colors.SURFACE_RAISED
        border = Colors.ACCENT_BORDER if self._selected else Colors.BORDER_SUBTLE
        self.setStyleSheet(f"""
            QFrame#podcastEpisodeCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {_EPISODE_CARD_RADIUS}px;
            }}
        """)

        status = self._status_label.text()
        accent = _status_accent(status)
        self._status_label.setStyleSheet(f"""
            QLabel {{
                color: {accent};
                background: {Colors.SURFACE};
                border: 1px solid {accent};
                border-radius: 7px;
                padding: 2px 8px;
            }}
        """)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._update_card_layout()

    def contextMenuEvent(self, a0: QContextMenuEvent | None) -> None:
        if a0 is not None:
            self._emit_context_menu(a0.pos())
            a0.accept()
            return
        super().contextMenuEvent(a0)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is None:
            return super().eventFilter(a0, a1)

        if a1.type() == QEvent.Type.ContextMenu:
            context_event = cast(QContextMenuEvent, a1)
            if isinstance(a0, QWidget):
                pos = self.mapFromGlobal(context_event.globalPos())
            else:
                pos = context_event.pos()
            self._emit_context_menu(pos)
            context_event.accept()
            return True

        if a1.type() == QEvent.Type.MouseButtonPress:
            mouse_event = cast(QMouseEvent, a1)
            if a0 in (self._add_btn, self._remove_btn, self._more_btn):
                return super().eventFilter(a0, a1)
            if mouse_event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit(self._row_index, mouse_event.modifiers())
                mouse_event.accept()
                return True

        return super().eventFilter(a0, a1)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._row_index, a0.modifiers())
            a0.accept()
            return
        super().mousePressEvent(a0)

    def _emit_context_menu(self, pos: QPoint) -> None:
        self.context_requested.emit(self._row_index, pos)


class _PodcastEpisodeScrollArea(QScrollArea):
    """Compatibility wrapper around the pooled episode renderer."""

    def __init__(self, episode_list: _PodcastEpisodeList) -> None:
        super().__init__(episode_list)
        self._episode_list = episode_list
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setAutoFillBackground(False)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        self.setPalette(pal)
        viewport = self.viewport()
        if viewport is not None:
            viewport.setPalette(pal)
            viewport.setAutoFillBackground(False)

    def rowAt(self, y: int) -> int:
        return self._episode_list.row_at_viewport_y(y)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._episode_list.schedule_viewport_refresh(force=True)


class _PodcastEpisodeContent(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)


class _PodcastEpisodeList(QFrame):
    """Pooled, lazy episode card list with in-card description expansion."""

    def __init__(self, owner: PodcastBrowser):
        super().__init__(owner)
        self._owner = owner
        self._columns = _PODCAST_EPISODE_COLUMNS.copy()
        self._all_tracks: list[dict] = []
        self._tracks: list[dict] = []
        self._is_playlist_mode = False
        self._current_filter = None
        self._load_id = 0

        self._expanded_keys: set[str] = set()
        self._selected_rows: set[int] = set()
        self._row_heights: list[int] = []
        self._row_offsets: list[int] = [0]
        self._expanded_text_cache: dict[tuple[str, int], tuple[str, int]] = {}

        self._widget_pool: list[_PodcastEpisodeCard] = []
        self._visible_widgets: dict[int, _PodcastEpisodeCard] = {}
        self._refresh_scheduled = False
        self._refresh_force = False
        self._last_visible_range: tuple[int, int, int] | None = None
        self._requested_artwork_sources: set[str] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.table = _PodcastEpisodeScrollArea(self)
        self._content = _PodcastEpisodeContent()
        self.table.setWidget(self._content)
        self.table.customContextMenuRequested.connect(owner._on_episode_context_menu)
        layout.addWidget(self.table)

        bar = self.table.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(lambda _value: self.schedule_viewport_refresh())

    @staticmethod
    def build(owner: PodcastBrowser) -> _PodcastEpisodeList:
        return _PodcastEpisodeList(owner)

    def set_rows(self, rows: list[dict], columns: list[str]) -> None:
        self._columns = columns.copy()
        self._all_tracks = rows
        self._tracks = rows
        self._is_playlist_mode = False
        self._current_filter = None
        self._load_id += 1
        valid_keys = {self._row_key(row) for row in rows}
        self._expanded_keys.intersection_update(valid_keys)
        self._selected_rows = {
            row for row in self._selected_rows if 0 <= row < len(rows)
        }
        self._expanded_text_cache.clear()
        self._requested_artwork_sources.clear()
        self._rebuild_heights()
        self._reset_scroll_position()
        self.schedule_viewport_refresh(force=True)

    def selected_rows(self) -> list[int]:
        return sorted(row for row in self._selected_rows if row < len(self._tracks))

    def clear_selection(self) -> None:
        if not self._selected_rows:
            return
        old_rows = set(self._selected_rows)
        self._selected_rows.clear()
        self._update_selection_for_rows(old_rows)

    def select_row(self, row: int) -> None:
        if not (0 <= row < len(self._tracks)):
            return
        old_rows = set(self._selected_rows)
        self._selected_rows = {row}
        self._update_selection_for_rows(old_rows | {row})

    def row_at_viewport_y(self, y: int) -> int:
        bar = self.table.verticalScrollBar()
        scroll = bar.value() if bar is not None else 0
        return self._row_at_content_y(scroll + y)

    def _reset_scroll_position(self) -> None:
        bar = self.table.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)

    def schedule_viewport_refresh(self, *, force: bool = False) -> None:
        if force:
            self._refresh_force = True
            self._last_visible_range = None
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        QTimer.singleShot(0, self._refresh_viewport)

    def _row_key(self, row: dict) -> str:
        return str(row.get("_ep_key") or row.get("_ep_guid") or id(row))

    def _shows_podcast_artwork(self) -> bool:
        return "podcast_feed_title" in self._columns

    def _collapsed_height_for_row(self, _row: dict) -> int:
        if self._shows_podcast_artwork():
            return _EPISODE_ARTWORK_COLLAPSED_HEIGHT
        return _EPISODE_COLLAPSED_HEIGHT

    def _rebuild_heights(self) -> None:
        self._row_heights = [
            self._collapsed_height_for_row(row) for row in self._tracks
        ]
        for i, row in enumerate(self._tracks):
            if self._row_key(row) in self._expanded_keys:
                self._row_heights[i] = self._height_for_row(i, row)
        self._row_offsets = [0]
        total = 0
        for height in self._row_heights:
            total += height + _EPISODE_ROW_GAP
            self._row_offsets.append(total)
        self._content.setMinimumHeight(total)
        self._content.resize(self._content_width(), total)

    def _content_width(self) -> int:
        viewport = self.table.viewport()
        width = viewport.width() if viewport is not None else self.width()
        return max(240, width)

    def _card_width(self) -> int:
        return max(180, self._content_width() - 2 * _EPISODE_CARD_MARGIN_X)

    def _height_for_row(self, _index: int, row: dict) -> int:
        key = self._row_key(row)
        if key not in self._expanded_keys:
            return self._collapsed_height_for_row(row)
        _text, height = self._expanded_description(row, self._card_width())
        return height

    def _expanded_description(self, row: dict, card_width: int) -> tuple[str, int]:
        key = self._row_key(row)
        text_width = max(80, card_width - 2 * _EPISODE_CARD_PADDING)
        cache_key = (key, text_width)
        cached = self._expanded_text_cache.get(cache_key)
        if cached is not None:
            return cached

        metrics = QFontMetrics(QFont(FONT_FAMILY, Metrics.FONT_SM))
        lines, truncated = _wrap_lines(
            row.get("Description Text", ""),
            metrics,
            text_width,
            max_lines=_EPISODE_EXPANDED_MAX_LINES,
        )
        display = "\n".join(lines)
        if truncated and display and not display.endswith("..."):
            display = f"{display.rstrip()}..."
        line_count = max(1, len(lines))
        base_height = self._collapsed_height_for_row(row)
        height = max(
            base_height,
            116 + line_count * (metrics.height() + 3),
        )
        height = min(height, 420)
        cached = (display, height)
        self._expanded_text_cache[cache_key] = cached
        return cached

    def _collapsed_description(self, row: dict, card_width: int) -> tuple[str, bool]:
        text_width = max(80, card_width - 2 * _EPISODE_CARD_PADDING)
        metrics = QFontMetrics(QFont(FONT_FAMILY, Metrics.FONT_SM))
        lines, truncated = _wrap_lines(
            row.get("Description Text", ""),
            metrics,
            text_width,
            max_lines=_EPISODE_DESC_COLLAPSED_LINES,
        )
        return "\n".join(lines), truncated

    def _row_at_content_y(self, y: int) -> int:
        import bisect

        if not self._tracks:
            return -1
        index = bisect.bisect_right(self._row_offsets, max(0, y)) - 1
        return min(max(index, 0), len(self._tracks) - 1)

    def _visible_range(self) -> tuple[int, int]:
        if not self._tracks:
            return 0, 0
        bar = self.table.verticalScrollBar()
        scroll = bar.value() if bar is not None else 0
        viewport = self.table.viewport()
        viewport_height = viewport.height() if viewport is not None else self.height()
        start = max(0, self._row_at_content_y(scroll) - _EPISODE_ROW_BUFFER)
        end = min(
            len(self._tracks),
            self._row_at_content_y(scroll + viewport_height) + _EPISODE_ROW_BUFFER + 1,
        )
        return start, end

    def _refresh_viewport(self) -> None:
        self._refresh_scheduled = False
        width = self._content_width()
        total_height = self._row_offsets[-1] if self._row_offsets else 0
        if self._content.width() != width:
            self._expanded_text_cache.clear()
            self._rebuild_heights()
            width = self._content_width()
            total_height = self._row_offsets[-1] if self._row_offsets else 0
        self._content.resize(width, total_height)

        start, end = self._visible_range()
        view_state = (start, end, width)
        if self._last_visible_range == view_state and not self._refresh_force:
            return
        self._last_visible_range = view_state
        self._refresh_force = False

        needed = set(range(start, end))
        for row_index in list(self._visible_widgets.keys()):
            if row_index not in needed:
                self._release_widget(row_index)

        card_width = self._card_width()
        for row_index in range(start, end):
            row = self._tracks[row_index]
            widget = self._visible_widgets.get(row_index)
            if widget is None:
                widget = self._acquire_widget()
                self._visible_widgets[row_index] = widget
            self._bind_widget(widget, row_index, row)
            widget.setGeometry(
                QRect(
                    _EPISODE_CARD_MARGIN_X,
                    self._row_offsets[row_index] + _EPISODE_CARD_MARGIN_Y,
                    card_width,
                    max(1, self._row_heights[row_index] - _EPISODE_ROW_GAP),
                )
            )
            widget.show()

    def _acquire_widget(self) -> _PodcastEpisodeCard:
        if self._widget_pool:
            widget = self._widget_pool.pop()
            widget.setParent(self._content)
            return widget
        widget = _PodcastEpisodeCard(self._content)
        widget.clicked.connect(self._on_card_clicked)
        widget.more_requested.connect(self._toggle_expanded)
        add_handler = getattr(self._owner, "_on_episode_card_add_to_ipod", None)
        if callable(add_handler):
            widget.add_requested.connect(add_handler)
        remove_handler = getattr(self._owner, "_on_episode_card_remove_from_ipod", None)
        if callable(remove_handler):
            widget.remove_requested.connect(remove_handler)
        widget.context_requested.connect(self._on_card_context_menu)
        return widget

    def _release_widget(self, row_index: int) -> None:
        widget = self._visible_widgets.pop(row_index, None)
        if widget is None:
            return
        widget.hide()
        self._widget_pool.append(widget)

    def _bind_widget(self, widget: _PodcastEpisodeCard, row_index: int, row: dict) -> None:
        key = self._row_key(row)
        expanded = key in self._expanded_keys
        card_width = self._card_width()
        if expanded:
            description_text, _height = self._expanded_description(row, card_width)
            show_more = True
        else:
            description_text, show_more = self._collapsed_description(row, card_width)
        show_artwork = self._shows_podcast_artwork()
        artwork_source = (
            str(row.get("_podcast_artwork_source") or "") if show_artwork else ""
        )
        artwork_pixmap = None
        if show_artwork:
            artwork_pixmap = _artwork_cache.get(artwork_source)
            if artwork_pixmap is None:
                artwork_pixmap = self._owner._artwork_placeholder_pixmap(
                    _EPISODE_CARD_ARTWORK_SIZE,
                )
        widget.bind(
            row_index=row_index,
            row=row,
            row_key=key,
            selected=row_index in self._selected_rows,
            expanded=expanded,
            description_text=description_text,
            show_more=show_more or expanded,
            show_artwork=show_artwork,
            artwork_source=artwork_source,
            artwork_pixmap=artwork_pixmap,
        )
        if (
            show_artwork
            and artwork_source
            and artwork_source not in _artwork_cache
            and artwork_source not in self._requested_artwork_sources
        ):
            self._requested_artwork_sources.add(artwork_source)
            self._owner._request_artwork(
                artwork_source,
                self._apply_artwork_to_visible_cards,
            )

    def _apply_artwork_to_visible_cards(self, source: str, pixmap: QPixmap) -> None:
        for widget in self._visible_widgets.values():
            widget.set_artwork(source, pixmap)

    def _toggle_expanded(self, row_index: int) -> None:
        if not (0 <= row_index < len(self._tracks)):
            return
        key = self._row_key(self._tracks[row_index])
        if key in self._expanded_keys:
            self._expanded_keys.remove(key)
        else:
            self._expanded_keys.add(key)
        old_height = self._row_heights[row_index]
        new_height = self._height_for_row(row_index, self._tracks[row_index])
        if new_height != old_height:
            delta = new_height - old_height
            self._row_heights[row_index] = new_height
            for i in range(row_index + 1, len(self._row_offsets)):
                self._row_offsets[i] += delta
            total_height = self._row_offsets[-1] if self._row_offsets else 0
            self._content.setMinimumHeight(total_height)
            self._content.resize(self._content_width(), total_height)
        self.schedule_viewport_refresh(force=True)

    def _on_card_clicked(
        self,
        row_index: int,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        if not (0 <= row_index < len(self._tracks)):
            return
        old_rows = set(self._selected_rows)
        ctrl = bool(
            modifiers
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if shift and self._selected_rows:
            anchor = min(self._selected_rows)
            lo, hi = sorted((anchor, row_index))
            self._selected_rows = set(range(lo, hi + 1))
        elif ctrl:
            if row_index in self._selected_rows:
                self._selected_rows.remove(row_index)
            else:
                self._selected_rows.add(row_index)
        else:
            self._selected_rows = {row_index}
        self._update_selection_for_rows(old_rows | self._selected_rows)

    def _on_card_context_menu(self, row_index: int, pos: QPoint) -> None:
        widget = self._visible_widgets.get(row_index)
        if widget is None:
            return
        viewport = self.table.viewport()
        if viewport is None:
            return
        viewport_pos = viewport.mapFromGlobal(widget.mapToGlobal(pos))
        self.table.customContextMenuRequested.emit(viewport_pos)

    def _update_selection_for_rows(self, rows: set[int]) -> None:
        for row in rows:
            widget = self._visible_widgets.get(row)
            if widget is not None and 0 <= row < len(self._tracks):
                self._bind_widget(widget, row, self._tracks[row])

    def _recycle_all_visible_widgets(self) -> None:
        for row_index in list(self._visible_widgets):
            self._release_widget(row_index)


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
        self._showing_combined_feed = False
        self._deferred_reconcile_tracks: list[dict] | None = None
        self._episode_by_guid: dict[str, object] = {}
        self._episode_feed_by_key: dict[str, object] = {}
        self._episode_dicts: list[dict] = []
        self._artwork_inflight: dict[str, list[Callable[[str, QPixmap], None]]] = {}
        self._episode_state_retry: Callable[[], None] | None = None

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

        from iopenpod.podcasts.subscription_store import SubscriptionStore
        settings = self._settings_service.get_effective_settings()
        session = self._device_sessions.current_session()
        storage = session.storage
        self._store = SubscriptionStore(
            ipod_path,
            download_cache_dir=settings.transcode_cache_dir,
            reported_volume_format=(
                storage.reported_volume_format if storage is not None else ""
            ),
            expected_volume_identity_key=(
                storage.volume_identity_key if storage is not None else ""
            ),
        )
        try:
            self._store.load()
        except Exception as exc:
            log.exception("Could not safely load podcast subscriptions")
            self._store = None
            self._feed_list.clear()
            self._episode_list.set_rows([], _PODCAST_EPISODE_COLUMNS)
            self._stack.setCurrentIndex(0)
            self._set_status("Podcast data could not be loaded safely")
            QMessageBox.critical(
                self,
                "Podcast Data Not Loaded",
                "iOpenPod could not safely read the podcast subscriptions on "
                f"this iPod and left them unchanged.\n\n{exc}\n\nReconnect and "
                "reload the iPod before making podcast changes.",
            )
            return

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
        self._showing_combined_feed = False
        self._deferred_reconcile_tracks = None
        self._episode_by_guid.clear()
        self._episode_feed_by_key.clear()
        if hasattr(self, '_session_refreshed'):
            self._session_refreshed.clear()
        self._feed_list.clear()
        self._episode_list.set_rows([], _PODCAST_EPISODE_COLUMNS)
        self._episode_dicts = []
        self._status_label.setText("")
        self._stack.setCurrentIndex(0)

    def _persist_subscription_change(
        self,
        action: str,
        operation: Callable[[], object],
    ) -> bool:
        """Run one device-store mutation and alert instead of masking refusal."""
        try:
            operation()
            return True
        except Exception as exc:
            log.exception("Could not %s", action)
            if self._store is not None:
                try:
                    self._store.load()
                except Exception:
                    log.exception("Could not reload podcast subscriptions after failure")
            QMessageBox.critical(
                self,
                "Podcast Changes Not Saved",
                f"iOpenPod stopped before it could {action}.\n\n{exc}\n\n"
                "Reconnect and reload the iPod before trying again.",
            )
            self._set_status("Podcast changes were not saved")
            return False

    def reconcile_ipod_statuses(self, ipod_tracks: list[dict] | None = None) -> None:
        """Reconcile stored episode state with the current iPod track list.

        This keeps "Downloaded" / "On iPod" statuses accurate even when
        feeds are loaded after iTunesDB parsing or tracks were removed.
        """
        store = self._store
        if store is None:
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

        from iopenpod.podcasts.podcast_sync import PodcastTrackMatcher

        feeds = store.get_feeds()
        matcher = PodcastTrackMatcher(ipod_tracks)
        changed_feeds: list = []

        for feed in feeds:
            if matcher.match_feed(feed):
                changed_feeds.append(feed)

        if changed_feeds:
            if not self._persist_subscription_change(
                "update podcast status",
                lambda: store.update_feeds(changed_feeds),
            ):
                return

        if self._selected_feed:
            refreshed = store.get_feed(self._selected_feed.feed_url)
            if refreshed:
                self._selected_feed = refreshed
        if self._showing_combined_feed:
            self._show_combined_feed()
        elif self._selected_feed:
            self._show_episodes(self._selected_feed)

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
        self._feed_list.setFont(QFont(FONT_FAMILY, Metrics.FONT_SIDEBAR))
        self._feed_list.setIconSize(QSize((36), (36)))
        self._feed_list.setSpacing(2)
        self._feed_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._feed_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._feed_list.customContextMenuRequested.connect(self._on_feed_context_menu)
        self._feed_list.currentRowChanged.connect(self._on_feed_selected)
        self._feed_list.setStyleSheet(sidebar_item_view_css(background="transparent"))

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
        _spin_style = spin_css(padding="2px 6px", font_size=Metrics.FONT_SM)

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
            "Immediately", "1 Day", "3 Days", "1 Week", "2 Weeks",
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

        # ── Episode list ────────────────────────────────────────────────
        self._episode_list = _PodcastEpisodeList.build(self)
        self._episode_stack = QStackedWidget()
        self._episode_stack.setStyleSheet("background: transparent; border: none;")
        self._episode_stack.addWidget(self._episode_list)  # index 0: list

        self._episode_state = PodcastStatePanel()
        self._episode_state.action_clicked.connect(self._retry_episode_state)
        self._episode_stack.addWidget(self._episode_state)  # index 1: visual state
        self._episode_stack.setCurrentIndex(0)
        layout.addWidget(self._episode_stack, stretch=1)

        # ── Download progress bar (hidden by default) ────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(3)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setStyleSheet(
            progress_bar_css(height=3, radius=1, bg=Colors.SURFACE)
        )
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

    # ── Episode state visuals ───────────────────────────────────────────

    def _show_episode_content(self) -> None:
        self._episode_state_retry = None
        if hasattr(self, "_episode_stack"):
            self._episode_stack.setCurrentIndex(0)

    def _show_episode_loading(self, title: str, message: str) -> None:
        self._episode_state_retry = None
        self._episode_state.show_loading(title, message)
        self._episode_stack.setCurrentIndex(1)

    def _show_episode_empty(self, title: str, message: str) -> None:
        self._episode_state_retry = None
        self._episode_state.show_empty(title, message)
        self._episode_stack.setCurrentIndex(1)

    def _show_episode_error(
        self,
        error: BaseException,
        *,
        action: str,
        retry: Callable[[], None] | None = None,
    ) -> None:
        from iopenpod.podcasts.network_errors import describe_podcast_error

        info = describe_podcast_error(error, action=action)
        self._episode_state_retry = retry
        self._episode_state.show_error(
            info.title,
            info.message,
            code=info.code,
            action_text="Try Again" if retry else "",
        )
        self._episode_stack.setCurrentIndex(1)

    def _retry_episode_state(self) -> None:
        retry = self._episode_state_retry
        if retry is not None:
            retry()

    # ── Feed list management ─────────────────────────────────────────────

    def _refresh_feed_list(self) -> None:
        """Repopulate the feed list widget from the subscription store."""
        if not self._store:
            return

        self._feed_list.blockSignals(True)
        prev_url = (
            _COMBINED_FEED_KEY
            if self._showing_combined_feed
            else self._selected_feed.feed_url if self._selected_feed else None
        )
        self._feed_list.clear()

        feeds = self._store.get_feeds()

        # Show empty state or main content
        if not feeds:
            self._stack.setCurrentIndex(0)
            self._feed_list.blockSignals(False)
            self._selected_feed = None
            self._showing_combined_feed = False
            self._show_episodes(None)
            return
        self._stack.setCurrentIndex(1)

        feed_item = QListWidgetItem("Feed")
        feed_item.setData(Qt.ItemDataRole.UserRole, _COMBINED_FEED_KEY)
        feed_item.setSizeHint(QSize(0, 40))
        feed_icon = self._artwork_placeholder_pixmap(36)
        if feed_icon:
            feed_item.setIcon(QIcon(feed_icon))
        self._feed_list.addItem(feed_item)

        select_row = 0 if prev_url in (None, _COMBINED_FEED_KEY) else -1

        for i, feed in enumerate(feeds):
            ep_count = len(feed.episodes)
            label = feed.title or "Untitled"
            item = QListWidgetItem(f"{label}  ({ep_count})")
            item.setData(Qt.ItemDataRole.UserRole, feed.feed_url)
            item.setSizeHint(QSize(0, 40))

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
                self._load_feed_list_artwork(artwork_source, i + 1)

            self._feed_list.addItem(item)
            if feed.feed_url == prev_url:
                select_row = i + 1

        self._feed_list.blockSignals(False)

        if select_row >= 0:
            self._feed_list.setCurrentRow(select_row)
        elif self._feed_list.count() > 0:
            self._feed_list.setCurrentRow(0)
        else:
            self._selected_feed = None
            self._showing_combined_feed = False
            self._show_episodes(None)

    def _on_feed_selected(self, row: int) -> None:
        if row < 0 or not self._store:
            self._selected_feed = None
            self._showing_combined_feed = False
            self._show_episodes(None)
            return

        item = self._feed_list.item(row)
        if not item:
            return

        feed_url = item.data(Qt.ItemDataRole.UserRole)
        if feed_url == _COMBINED_FEED_KEY:
            self._selected_feed = None
            self._showing_combined_feed = True
            self._show_combined_feed()
            return

        self._selected_feed = self._store.get_feed(feed_url)
        self._showing_combined_feed = False
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
        if feed_url == _COMBINED_FEED_KEY:
            return
        feed = self._store.get_feed(feed_url)
        if not feed:
            return

        menu = QMenu(self)
        menu.setStyleSheet(context_menu_css())

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
            selected_rows = set(self._episode_list.selected_rows())
            if row not in selected_rows:
                self._episode_list.clear_selection()
                self._episode_list.select_row(row)

        selected = self._get_selected_episode_refs()
        if not selected:
            return

        from iopenpod.podcasts.models import (
            STATUS_DOWNLOADED,
            STATUS_DOWNLOADING,
            STATUS_ON_IPOD,
        )

        can_add = [
            (row, ep, feed)
            for row, ep, feed in selected
            if ep.status not in (STATUS_ON_IPOD, STATUS_DOWNLOADING)
        ]
        can_remove_dl = [
            (row, ep, feed)
            for row, ep, feed in selected
            if ep.status in (STATUS_DOWNLOADED,) and ep.downloaded_path
        ]
        can_remove_ipod = [
            (row, ep, feed)
            for row, ep, feed in selected
            if ep.status == STATUS_ON_IPOD and ep.ipod_db_track_id
        ]
        can_mark_listened = [
            (row, ep, feed)
            for row, ep, feed in selected
            if not _episode_is_listened(ep)
        ]
        can_mark_unlistened = [
            (row, ep, feed)
            for row, ep, feed in selected
            if _episode_is_listened(ep)
        ]

        if not any((
            can_add,
            can_remove_dl,
            can_remove_ipod,
            can_mark_listened,
            can_mark_unlistened,
        )):
            return

        menu = QMenu(self)
        menu.setStyleSheet(context_menu_css())

        add_action = remove_dl_action = remove_ipod_action = None
        mark_listened_action = mark_unlistened_action = None

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

        if can_mark_listened or can_mark_unlistened:
            if add_action or remove_dl_action or remove_ipod_action:
                menu.addSeparator()
            if can_mark_listened:
                n = len(can_mark_listened)
                suffix = f" ({n})" if n > 1 else ""
                mark_listened_action = menu.addAction(f"Mark as Listened{suffix}")
            if can_mark_unlistened:
                n = len(can_mark_unlistened)
                suffix = f" ({n})" if n > 1 else ""
                mark_unlistened_action = menu.addAction(f"Mark as Unlistened{suffix}")

        viewport = self._episode_list.table.viewport()
        if not viewport:
            return
        action = menu.exec(viewport.mapToGlobal(pos))
        if action is None:
            return
        if action == add_action:
            self._add_to_ipod_refs(can_add)
        elif action == remove_dl_action:
            self._remove_download_refs(can_remove_dl)
        elif action == remove_ipod_action:
            self._remove_from_ipod_refs(can_remove_ipod)
        elif action == mark_listened_action:
            self._set_listened_refs(can_mark_listened, True)
        elif action == mark_unlistened_action:
            self._set_listened_refs(can_mark_unlistened, False)

    # ── Episode table ────────────────────────────────────────────────────

    @staticmethod
    def _ep_to_dict(ep, status_text: str, feed=None) -> dict:
        """Convert a PodcastEpisode to a MusicBrowserList-compatible dict."""
        from iopenpod.podcasts.models import STATUS_DOWNLOADING, STATUS_ON_IPOD

        ep_key = _episode_key(feed, ep) if feed is not None else ep.guid
        status = str(getattr(ep, "status", ""))
        play_count = _coerce_int(getattr(ep, "play_count", 0))
        last_played = _coerce_int(getattr(ep, "last_played", 0))
        return {
            "Title": ep.title or ep.guid or "",
            "podcast_feed_title": getattr(feed, "title", "") if feed is not None else "",
            "Description Text": _episode_description_text(ep.description),
            "ep_status": status_text,
            "length": (ep.duration_seconds or 0) * 1000,
            "date_added": int(ep.pub_date or 0),
            "size": ep.size_bytes or 0,
            "play_count_1": play_count,
            "last_played": last_played,
            "_ep_guid": ep.guid,
            "_ep_key": ep_key,
            "_was_listened": _episode_is_listened(ep),
            "_listened_override": _episode_listened_override(ep),
            "_can_add_to_ipod": status not in (STATUS_ON_IPOD, STATUS_DOWNLOADING),
            "_can_remove_from_ipod": (
                status == STATUS_ON_IPOD
                and bool(getattr(ep, "ipod_db_track_id", 0))
            ),
        }

    def _set_episode_rows(self, rows: list[dict], columns: list[str]) -> None:
        self._episode_list.set_rows(rows, columns)

    def _show_combined_feed(self) -> None:
        """Show all subscribed episodes as one plain chronological feed."""
        if not self._store:
            self._show_episodes(None)
            return

        self._selected_feed = None
        self._showing_combined_feed = True
        self._feed_header.hide()
        self._episode_by_guid.clear()
        self._episode_feed_by_key.clear()

        episode_refs = []
        for feed in self._store.get_feeds():
            for ep in feed.episodes:
                episode_refs.append((feed, ep))

        episode_refs.sort(key=lambda ref: ref[1].pub_date or 0, reverse=True)
        rows = []
        artwork_sources: dict[str, str] = {}
        for feed, ep in episode_refs:
            key = _episode_key(feed, ep)
            self._episode_by_guid[key] = ep
            self._episode_feed_by_key[key] = feed
            feed_key = str(getattr(feed, "feed_url", "") or id(feed))
            if feed_key not in artwork_sources:
                artwork_sources[feed_key] = self._feed_artwork_source(feed)
            row = self._ep_to_dict(ep, self._episode_status_display(ep)[0], feed)
            row["_podcast_artwork_source"] = artwork_sources[feed_key]
            rows.append(row)

        self._episode_dicts = rows
        self._set_episode_rows(rows, _COMBINED_FEED_COLUMNS)
        if rows:
            self._show_episode_content()
        else:
            self._show_episode_empty(
                "Waiting for episodes",
                "Subscribed shows will appear here after their feeds refresh.",
            )

    def _show_episodes(self, feed) -> None:
        """Populate the episode list for the given feed."""
        self._episode_by_guid.clear()
        self._episode_feed_by_key.clear()
        self._episode_dicts = []

        if not feed:
            self._feed_header.show()
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
            self._set_episode_rows([], _PODCAST_EPISODE_COLUMNS)
            self._show_episode_content()
            return

        self._showing_combined_feed = False
        self._feed_header.show()
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
        episodes = sorted(feed.episodes, key=lambda e: e.pub_date or 0, reverse=True)
        rows = []
        for ep in episodes:
            key = _episode_key(feed, ep)
            self._episode_by_guid[key] = ep
            self._episode_feed_by_key[key] = feed
            rows.append(self._ep_to_dict(ep, self._episode_status_display(ep)[0], feed))
        self._episode_dicts = rows
        self._set_episode_rows(rows, _PODCAST_EPISODE_COLUMNS)
        if rows:
            self._show_episode_content()
        else:
            self._show_episode_empty(
                "No episodes found",
                "This podcast loaded, but its feed did not list any episodes.",
            )

    @staticmethod
    def _episode_status_display(ep):
        """Return (text, QColor|None) for episode status."""
        from PyQt6.QtGui import QColor as _QC

        from iopenpod.podcasts.models import (
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
        if _episode_is_listened(ep):
            return ("Listened", _QC(Colors.WARNING))
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

        if not self._episode_dicts:
            self._show_episode_loading(
                "Loading episodes…",
                "",
            )

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker
        from iopenpod.podcasts.feed_parser import fetch_feed

        store = self._store

        def _refresh():
            refreshed_feeds = []
            failures = []
            for feed in feeds:
                try:
                    refreshed = fetch_feed(feed.feed_url, existing=feed)
                    store.cache_feed_artwork(refreshed)
                    refreshed_feeds.append(refreshed)
                except Exception as exc:
                    log.warning("Background refresh failed for %s: %s", feed.title, exc)
                    failures.append((feed.title, exc))
            return store.update_feeds(refreshed_feeds), failures

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
        self._show_episode_loading(
            "Refreshing podcasts…",
            "Checking subscribed feeds for new episodes.",
        )
        self._episode_state_retry = self._on_refresh_all

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker
        from iopenpod.podcasts.feed_parser import fetch_feed

        store = self._store

        def _refresh_all():
            refreshed_feeds = []
            failures = []
            for feed in feeds:
                try:
                    refreshed = fetch_feed(feed.feed_url, existing=feed)
                    store.cache_feed_artwork(refreshed)
                    refreshed_feeds.append(refreshed)
                except Exception as exc:
                    log.warning("Failed to refresh %s: %s", feed.title, exc)
                    failures.append((feed.title, exc))
            return store.update_feeds(refreshed_feeds), failures

        worker = Worker(_refresh_all)
        worker.signals.result.connect(self._on_refresh_done)
        worker.signals.error.connect(self._on_refresh_error)
        worker.signals.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_refresh_done(self, result) -> None:
        if isinstance(result, tuple):
            count = int(result[0] or 0)
            failures = list(result[1] or [])
        else:
            count = int(result or 0)
            failures = []

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
        if self._showing_combined_feed and self._store:
            self._show_combined_feed()
        elif self._selected_feed and self._store:
            updated = self._store.get_feed(self._selected_feed.feed_url)
            if updated:
                self._selected_feed = updated
                self._show_episodes(updated)

        if failures:
            if count:
                self._set_status(
                    f"Refreshed {count}; {len(failures)} feed"
                    f"{'s' if len(failures) != 1 else ''} could not update"
                )
            elif not self._episode_dicts:
                _feed_title, error = failures[0]
                self._show_episode_error(
                    error,
                    action="refresh podcasts",
                    retry=self._on_refresh_all,
                )
                self._set_status("Podcasts could not refresh")
            else:
                self._set_status("Some podcasts could not refresh")

    def _on_refresh_error(self, error_tuple) -> None:
        _, value, _ = error_tuple
        self._show_episode_error(
            value,
            action="refresh podcasts",
            retry=self._episode_state_retry or self._on_refresh_all,
        )
        self._set_status("Refresh failed")

    # ── Managed podcast sync ─────────────────────────────────────────────

    def _on_sync_podcasts(self) -> None:
        """Refresh all feeds, then build a managed sync plan.

        The plan applies each feed's slot settings: removing listened/old
        episodes and filling empty slots with new ones.
        """
        if not self._store:
            return
        caps = self._device_sessions.current_session().capabilities
        if caps is not None and not caps.supports_podcast:
            self._set_status("This iPod does not support podcasts")
            return

        feeds = self._store.get_feeds()
        if not feeds:
            self._set_status("No subscriptions to sync")
            return

        self._sync_btn.setEnabled(False)
        self._set_status("Refreshing feeds for sync…", timeout_ms=0)
        self._show_episode_loading(
            "Preparing podcast sync…",
            "Refreshing feeds before building the sync plan.",
        )
        self._episode_state_retry = self._on_sync_podcasts

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker
        from iopenpod.podcasts.feed_parser import fetch_feed

        store = self._store

        def _refresh_and_plan():
            # Phase 1: Refresh all feeds from RSS
            refreshed = []
            for feed in feeds:
                try:
                    refreshed_feed = fetch_feed(feed.feed_url, existing=feed)
                    store.cache_feed_artwork(refreshed_feed)
                    refreshed.append(refreshed_feed)
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
        if self._showing_combined_feed:
            self._show_combined_feed()
        elif self._selected_feed:
            updated = self._store.get_feed(self._selected_feed.feed_url)
            if updated:
                self._selected_feed = updated
                self._show_episodes(updated)

        from iopenpod.podcasts.podcast_sync import build_podcast_managed_plan

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
        self._show_episode_error(
            value,
            action="prepare podcast sync",
            retry=self._episode_state_retry or self._on_sync_podcasts,
        )
        self._set_status("Sync failed")
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
        self._stack.setCurrentIndex(1)
        self._show_episode_loading(
            "Adding podcast…",
            "Fetching the feed and latest episodes.",
        )
        self._episode_state_retry = (
            lambda feed_url=feed_url, artwork_url=artwork_url: self._subscribe_to_feed(
                feed_url,
                artwork_url,
            )
        )

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

        worker = Worker(self._fetch_subscribed_feed, feed_url, artwork_url)
        worker.signals.result.connect(self._on_feed_fetched)
        worker.signals.error.connect(self._on_subscribe_error)
        ThreadPoolSingleton.get_instance().start(worker)

    def _fetch_subscribed_feed(self, feed_url: str, artwork_url: str = ""):
        from iopenpod.podcasts.feed_parser import fetch_feed
        from iopenpod.podcasts.models import normalize_artwork_url

        feed = fetch_feed(feed_url)
        fallback_url = normalize_artwork_url(artwork_url)
        if fallback_url and not feed.artwork_url:
            feed.artwork_url = fallback_url
        if self._store:
            self._store.cache_feed_artwork(
                feed,
                fallback_urls=[fallback_url] if fallback_url else [],
            )
        return feed

    def _cache_artwork_file(self, feed_url: str, artwork_url: str) -> str:
        if not self._store or not artwork_url:
            return ""

        from iopenpod.podcasts.models import PodcastFeed

        feed = PodcastFeed(feed_url=feed_url, artwork_url=artwork_url)
        return self._store.cache_feed_artwork(feed)

    def _on_feed_fetched(self, feed) -> None:
        store = self._store
        if store is None:
            return
        if not self._persist_subscription_change(
            "save the podcast subscription",
            lambda: store.add_feed(feed),
        ):
            return
        self._mark_feed_refreshed(feed.feed_url)
        self._set_status(f"Subscribed to {feed.title}")
        self._showing_combined_feed = False
        self._refresh_feed_list()

        # Select the new feed
        for i in range(self._feed_list.count()):
            item = self._feed_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == feed.feed_url:
                self._feed_list.setCurrentRow(i)
                break

        self._selected_feed = store.get_feed(feed.feed_url) or feed
        self._show_episodes(self._selected_feed)

    def _on_subscribe_error(self, error_tuple) -> None:
        _, value, _ = error_tuple
        self._show_episode_error(
            value,
            action="add podcast",
            retry=self._episode_state_retry,
        )
        self._set_status("Could not add podcast")

    def _unsubscribe_feed(self, feed) -> None:
        store = self._store
        if store is None:
            return
        if not self._persist_subscription_change(
            "remove the podcast subscription",
            lambda: store.remove_feed(feed.feed_url),
        ):
            return
        self._set_status(f"Unsubscribed from {feed.title}")
        self._selected_feed = None
        self._showing_combined_feed = False
        self._refresh_feed_list()

    def _refresh_single_feed(self, feed) -> None:
        """Refresh a single feed in the background."""
        self._set_status(f"Refreshing {feed.title}…")
        self._show_episode_loading(
            "Refreshing this podcast…",
            "Checking the feed for the latest episodes.",
        )
        self._episode_state_retry = lambda feed=feed: self._refresh_single_feed(feed)

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker
        from iopenpod.podcasts.feed_parser import fetch_feed

        def _do():
            refreshed = fetch_feed(feed.feed_url, existing=feed)
            if self._store:
                self._store.cache_feed_artwork(refreshed)
            return refreshed

        worker = Worker(_do)
        worker.signals.result.connect(self._on_single_feed_refreshed)
        worker.signals.error.connect(self._on_refresh_error)
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_single_feed_refreshed(self, feed) -> None:
        store = self._store
        if store is None:
            return
        if not self._persist_subscription_change(
            "save the refreshed podcast",
            lambda: store.update_feed(feed),
        ):
            return
        self._mark_feed_refreshed(feed.feed_url)
        self._set_status(f"Refreshed {feed.title}")
        was_combined = self._showing_combined_feed
        self._refresh_feed_list()

        # Re-display episodes for the selected feed — _refresh_feed_list
        # restores the selection but setCurrentRow won't emit if the row
        # index didn't change, so the episode table wouldn't update.
        if was_combined:
            self._show_combined_feed()
        elif self._selected_feed and self._selected_feed.feed_url == feed.feed_url:
            self._selected_feed = feed
            self._show_episodes(feed)

    # ── Episode selection ────────────────────────────────────────────────

    def _get_selected_episode_refs(self):
        """Return list of (row, episode, feed) for selected episode rows."""
        if not self._selected_feed and not self._showing_combined_feed:
            return []

        result = []
        for row in self._episode_list.selected_rows():
            ref = self._episode_ref_at_row(row)
            if ref is not None:
                result.append(ref)
        return result

    def _episode_ref_at_row(self, row: int):
        if not (0 <= row < len(self._episode_dicts)):
            return None
        row_data = self._episode_dicts[row]
        key = str(row_data.get("_ep_key") or row_data.get("_ep_guid") or "")
        if not key:
            return None
        ep = self._episode_by_guid.get(key)
        feed = self._episode_feed_by_key.get(key) or self._selected_feed
        if ep is None or feed is None:
            return None
        return row, ep, feed

    def _get_selected_episodes(self):
        """Return list of (row, episode) for compatibility with callers/tests."""
        return [(row, ep) for row, ep, _feed in self._get_selected_episode_refs()]

    # ── Listened state ──────────────────────────────────────────────────

    def _set_listened_refs(self, episode_refs: list, listened: bool) -> None:
        changed_feeds: dict[str, PodcastFeed] = {}
        changed_count = 0

        for _row, ep, feed in episode_refs:
            if ep is None:
                continue
            if _episode_is_listened(ep) == listened:
                continue
            _set_episode_listened(ep, listened)
            changed_count += 1
            if feed is not None:
                changed_feeds[getattr(feed, "feed_url", str(id(feed)))] = cast(
                    "PodcastFeed",
                    feed,
                )

        if changed_count <= 0:
            self._set_action_status(
                "Selected episodes are already marked"
                if listened
                else "Selected episodes are already unmarked"
            )
            return

        store = self._store
        if store is not None and changed_feeds:
            if not self._persist_subscription_change(
                "save listened status",
                lambda: store.update_feeds(list(changed_feeds.values())),
            ):
                return

        if self._showing_combined_feed:
            self._show_combined_feed()
        else:
            self._show_episodes(self._selected_feed)
        self._refresh_feed_list()

        state = "listened" if listened else "unlistened"
        self._set_action_status(
            f"Marked {changed_count} episode{'s' if changed_count != 1 else ''} as {state}"
        )

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
        selected = self._get_selected_episode_refs()
        if not selected:
            self._set_action_status("Select episodes first")
            return
        self._add_to_ipod_refs(selected)

    def _on_episode_card_add_to_ipod(self, row_index: int) -> None:
        ref = self._episode_ref_at_row(row_index)
        if ref is None:
            return
        self._add_to_ipod_refs([ref])

    def _add_to_ipod_refs(self, episode_refs: list) -> None:
        caps = self._device_sessions.current_session().capabilities
        if caps is not None and not caps.supports_podcast:
            self._set_action_status("This iPod does not support podcasts")
            return
        if not self._ipod_path:
            self._set_action_status("No iPod connected")
            return

        from iopenpod.podcasts.models import STATUS_DOWNLOADING, STATUS_ON_IPOD

        # Filter out episodes already on iPod
        actionable = [
            (row, ep, feed) for row, ep, feed in episode_refs
            if ep.status not in (STATUS_ON_IPOD, STATUS_DOWNLOADING)
        ]
        if not actionable:
            if all(ep.status == STATUS_ON_IPOD for _row, ep, _feed in episode_refs):
                self._set_action_status("Selected episodes are already on iPod")
            else:
                self._set_action_status("Selected episodes cannot be added yet")
            return

        # Build sync plan directly (pending episodes will download during sync)
        self._build_and_emit_refs(actionable)

    def _build_and_emit_plan(self, actionable_episodes, feed) -> None:
        """Build a SyncPlan from actionable episodes and emit to main app.

        Accepts both downloaded and pending episodes. Pending episodes will
        be downloaded during sync execution.

        Args:
            actionable_episodes: List of PodcastEpisodes (not yet on iPod)
            feed: Parent PodcastFeed
        """
        self._build_and_emit_refs(
            [(0, ep, feed) for ep in actionable_episodes]
        )

    def _build_and_emit_refs(self, actionable_refs) -> None:
        """Build a SyncPlan from ``(row, episode, feed)`` references."""
        episodes_for_plan = [
            (ep, feed)
            for _row, ep, feed in actionable_refs
            if ep is not None and feed is not None
        ]

        if not episodes_for_plan:
            self._set_action_status("No episodes to sync")
            return

        # Get current iPod tracks for dedup
        ipod_tracks = self._current_ipod_tracks() or []

        from iopenpod.podcasts.podcast_sync import build_podcast_sync_plan
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
        """Delete downloaded files from the selected feed."""
        if not self._selected_feed:
            return
        self._remove_download_refs(
            [(0, ep, self._selected_feed) for ep in episodes]
        )

    def _remove_download_refs(self, episode_refs: list) -> None:
        """Delete downloaded files and reset episode status."""

        from iopenpod.podcasts.models import STATUS_NOT_DOWNLOADED

        removed = 0
        failures: list[tuple[object, Exception]] = []
        changed_feeds: dict[str, PodcastFeed] = {}
        store = self._store
        for _row, ep, feed in episode_refs:
            downloaded_path = ep.downloaded_path
            if downloaded_path:
                try:
                    if store is None:
                        raise RuntimeError("Podcast download storage is unavailable")
                    store.remove_episode_download(downloaded_path)
                except Exception as exc:
                    log.warning(
                        "Could not safely remove podcast download %r: %s",
                        downloaded_path,
                        exc,
                    )
                    failures.append((downloaded_path, exc))
                    continue
            ep.downloaded_path = ""
            ep.status = STATUS_NOT_DOWNLOADED
            if feed is not None:
                changed_feeds[getattr(feed, "feed_url", str(id(feed)))] = cast(
                    "PodcastFeed",
                    feed,
                )
            removed += 1

        if store is not None and changed_feeds:
            if not self._persist_subscription_change(
                "save downloaded episode status",
                lambda: store.update_feeds(list(changed_feeds.values())),
            ):
                return

        if self._showing_combined_feed:
            self._show_combined_feed()
        else:
            self._show_episodes(self._selected_feed)
        self._refresh_feed_list()
        if failures:
            failed_count = len(failures)
            title = "Download Not Removed" if failed_count == 1 else "Downloads Not Removed"
            first_error = failures[0][1]
            QMessageBox.warning(
                self,
                title,
                "iOpenPod left "
                f"{failed_count} episode download"
                f"{'s' if failed_count != 1 else ''} and their saved state "
                "unchanged because the stored path was unsafe or the file "
                f"could not be removed.\n\n{first_error}",
            )
            if removed:
                self._set_action_status(
                    f"Removed {removed}; {failed_count} not removed"
                )
            else:
                verb = "was" if failed_count == 1 else "were"
                self._set_action_status(
                    f"{failed_count} download{'s' if failed_count != 1 else ''} "
                    f"{verb} not removed"
                )
            return
        self._set_action_status(
            f"Removed {removed} download{'s' if removed != 1 else ''}"
        )

    def _remove_from_ipod(self, episodes: list) -> None:
        """Build a sync plan to remove episodes from the iPod."""
        if not self._selected_feed:
            return
        self._remove_from_ipod_refs(
            [(0, ep, self._selected_feed) for ep in episodes]
        )

    def _on_episode_card_remove_from_ipod(self, row_index: int) -> None:
        ref = self._episode_ref_at_row(row_index)
        if ref is None:
            return
        self._remove_from_ipod_refs([ref])

    def _remove_from_ipod_refs(self, episode_refs: list) -> None:
        """Build a sync plan to remove episode/feed refs from the iPod."""
        if not self._ipod_path:
            self._set_action_status("No iPod connected")
            return

        from iopenpod.application.sync_plan_builder import build_podcast_removal_sync_plan
        from iopenpod.sync.contracts import StorageSummary, SyncPlan

        ipod_tracks = self._current_ipod_tracks() or []
        episodes_by_feed: dict[str, tuple[object, list]] = {}
        for _row, ep, feed in episode_refs:
            if feed is None:
                continue
            key = getattr(feed, "feed_url", "") or str(id(feed))
            if key not in episodes_by_feed:
                episodes_by_feed[key] = (feed, [])
            episodes_by_feed[key][1].append(ep)

        plan = SyncPlan()
        plan.storage = StorageSummary()
        plan.removals_pre_checked = True
        for feed, episodes in episodes_by_feed.values():
            partial = build_podcast_removal_sync_plan(
                episodes,
                ipod_tracks,
                getattr(feed, "title", "") or "Podcast",
            )
            if partial is None:
                continue
            plan.to_remove.extend(partial.to_remove)
            plan.storage.bytes_to_remove += partial.storage.bytes_to_remove

        if not plan.to_remove:
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
        was_combined = self._showing_combined_feed
        if self._selected_feed and self._store:
            # Re-read the feed from store (statuses may have been updated)
            refreshed = self._store.get_feed(self._selected_feed.feed_url)
            if refreshed:
                self._selected_feed = refreshed
            self._show_episodes(self._selected_feed)
        self._refresh_feed_list()
        if was_combined and self._store:
            self._show_combined_feed()

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
                "immediate": "Immediately",
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
        store = self._store
        if store is None or not self._selected_feed:
            return

        feed = self._selected_feed

        _fill_keys = {"Newest Episode": "newest", "Next Episode": "next"}
        _cl_keys = {"Yes": True, "No": False}
        _older_keys = {
            "Immediately": "immediate",
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

        self._persist_subscription_change(
            "save podcast sync settings",
            lambda: store.update_feed(feed),
        )

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
        from iopenpod.podcasts.artwork import resolve_feed_artwork_source

        podcast_dir = self._store.podcast_dir if self._store else ""
        return resolve_feed_artwork_source(feed, podcast_dir)

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

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

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
                item = self._feed_list.item(i + 1)
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
