from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QImage,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from iopenpod.infrastructure.settings_schema import (
    PLAYER_POSITION_TOP,
    normalize_player_position,
)

from ..glyphs import glyph_icon, glyph_pixmap
from ..hidpi import effective_device_pixel_ratio, logical_to_physical
from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
)
from .formatters import format_duration_mmss

_CLASSIC_REFERENCE_COLORS = {
    "bar_top": "#f6f7f8",
    "bar_mid": "#dfe2e5",
    "bar_bottom": "#bcc2c8",
    "panel_top": "#eef1f4",
    "panel_mid": "#cfd5dc",
    "panel_bottom": "#aeb8c1",
    "panel_border": "#77838e",
    "panel_highlight": "#ffffff",
    "text": "#1f2328",
    "text_secondary": "#38424a",
    "text_tertiary": "#56616a",
    "icon": "#51565b",
    "icon_disabled": "#9da3a8",
    "groove": "#a8adb2",
    "groove_fill": "#79838c",
    "handle": "#f7f8f9",
}


def _first_text(track: dict, *keys: str) -> str:
    for key in keys:
        value = track.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _int_value(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return max(0, int(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        try:
            return max(0, int(text))
        except ValueError:
            return 0
    try:
        return max(0, int(str(value)))
    except (TypeError, ValueError):
        return 0


def _track_duration_ms(track: dict) -> int:
    for key in ("length", "duration_ms", "duration", "Time"):
        duration = _int_value(track.get(key))
        if duration > 0:
            return duration
    return 0


def _duration_text(ms: int) -> str:
    return format_duration_mmss(ms) if ms > 0 else "0:00"


def _rating_value(value: object) -> int:
    rating = _int_value(value)
    if rating <= 0:
        return 0
    return max(0, min(100, round(rating / 20) * 20))


def _paint_color(value: str, fallback: str = "#888888") -> QColor:
    color = QColor(value)
    if color.isValid():
        return color
    if value.startswith("rgba"):
        try:
            raw_parts = value[value.index("(") + 1:value.rindex(")")].split(",")
            r, g, b = (int(raw_parts[index].strip()) for index in range(3))
            alpha_raw = float(raw_parts[3].strip()) if len(raw_parts) > 3 else 255.0
            alpha = int(alpha_raw * 255) if alpha_raw <= 1 else int(alpha_raw)
            return QColor(r, g, b, max(0, min(255, alpha)))
        except (ValueError, IndexError):
            pass
    return QColor(fallback)


def _css_color(color: QColor) -> str:
    if color.alpha() >= 255:
        return color.name(QColor.NameFormat.HexRgb)
    return f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha()})"


def _composite_color(foreground: str, background: str) -> str:
    fg = _paint_color(foreground)
    bg = _paint_color(background)
    alpha = fg.alphaF()
    inv_alpha = 1.0 - alpha
    return _css_color(
        QColor(
            round(fg.red() * alpha + bg.red() * inv_alpha),
            round(fg.green() * alpha + bg.green() * inv_alpha),
            round(fg.blue() * alpha + bg.blue() * inv_alpha),
        )
    )


def _mix_color(first: str, second: str, amount: float) -> str:
    amount = max(0.0, min(1.0, float(amount)))
    first_color = _paint_color(first)
    second_color = _paint_color(second)
    keep = 1.0 - amount
    return _css_color(
        QColor(
            round(first_color.red() * keep + second_color.red() * amount),
            round(first_color.green() * keep + second_color.green() * amount),
            round(first_color.blue() * keep + second_color.blue() * amount),
            round(first_color.alpha() * keep + second_color.alpha() * amount),
        )
    )


def _theme_surface(color: str, background: str) -> str:
    return _composite_color(color, background) if "rgba" in color else color


def _player_theme_colors() -> dict[str, str]:
    dark = getattr(Colors, "_active_mode", "dark") == "dark"
    base = _theme_surface(Colors.DIALOG_BG, Colors.BG_DARK)
    bg = _theme_surface(Colors.BG_DARK, base)
    mid = _theme_surface(Colors.BG_MID, base)
    surface = _theme_surface(Colors.SURFACE, base)
    surface_alt = _theme_surface(Colors.SURFACE_ALT, base)
    raised = _theme_surface(Colors.SURFACE_RAISED, base)
    hover = _theme_surface(Colors.SURFACE_HOVER, base)
    active = _theme_surface(Colors.SURFACE_ACTIVE, base)
    border = _theme_surface(Colors.BORDER, base)
    border_subtle = _theme_surface(Colors.BORDER_SUBTLE, base)
    text = _theme_surface(Colors.TEXT_PRIMARY, base)
    text_secondary = _theme_surface(Colors.TEXT_SECONDARY, base)
    text_tertiary = _theme_surface(Colors.TEXT_TERTIARY, base)
    disabled = _theme_surface(Colors.TEXT_DISABLED, base)
    accent = _theme_surface(Colors.ACCENT, base)

    if dark:
        bar_top = _mix_color(base, "#ffffff", 0.10)
        bar_mid = _mix_color(_mix_color(base, mid, 0.50), "#ffffff", 0.05)
        bar_bottom = _mix_color(mid, "#000000", 0.14)
        panel_top = _mix_color(raised, "#ffffff", 0.10)
        panel_mid = _mix_color(surface_alt, "#ffffff", 0.04)
        panel_bottom = _mix_color(surface, "#000000", 0.16)
        panel_highlight = _mix_color(panel_top, "#ffffff", 0.28)
        groove_top = _mix_color(surface_alt, "#000000", 0.32)
        groove_mid = _mix_color(raised, "#ffffff", 0.04)
        groove_bottom = _mix_color(raised, "#ffffff", 0.12)
        handle_top = _mix_color(panel_top, text, 0.36)
        handle_mid = _mix_color(panel_mid, text, 0.24)
        handle_bottom = _mix_color(panel_bottom, "#000000", 0.12)
    else:
        bar_top = _mix_color(base, "#ffffff", 0.58)
        bar_mid = _mix_color(_mix_color(base, mid, 0.40), "#000000", 0.04)
        bar_bottom = _mix_color(mid, "#000000", 0.12)
        panel_top = _mix_color(raised, "#ffffff", 0.38)
        panel_mid = _mix_color(surface_alt, "#000000", 0.03)
        panel_bottom = _mix_color(surface, "#000000", 0.12)
        panel_highlight = _mix_color(panel_top, "#ffffff", 0.55)
        groove_top = _mix_color(surface_alt, "#000000", 0.22)
        groove_mid = _mix_color(raised, "#000000", 0.06)
        groove_bottom = _mix_color(raised, "#ffffff", 0.34)
        handle_top = _mix_color(panel_top, "#ffffff", 0.58)
        handle_mid = _mix_color(panel_mid, "#ffffff", 0.28)
        handle_bottom = _mix_color(panel_bottom, "#000000", 0.16)

    return {
        "accent": accent,
        "art_bg": _mix_color(panel_mid, bg, 0.08),
        "art_border": _mix_color(border, text_tertiary, 0.18),
        "bar_top": bar_top,
        "bar_mid": bar_mid,
        "bar_bottom": bar_bottom,
        "border": border,
        "border_subtle": border_subtle,
        "disabled": disabled,
        "groove_top": groove_top,
        "groove_mid": groove_mid,
        "groove_bottom": groove_bottom,
        "groove_fill_top": _mix_color(accent, text, 0.10 if dark else 0.04),
        "groove_fill_bottom": _mix_color(accent, "#000000", 0.18 if dark else 0.08),
        "handle_top": handle_top,
        "handle_mid": handle_mid,
        "handle_bottom": handle_bottom,
        "hover": hover,
        "icon": text_secondary,
        "icon_disabled": disabled,
        "inactive_star": _mix_color(text_tertiary, base, 0.45),
        "panel_top": panel_top,
        "panel_mid": panel_mid,
        "panel_bottom": panel_bottom,
        "panel_border": _mix_color(border, text_tertiary, 0.22),
        "panel_highlight": panel_highlight,
        "pressed": active,
        "star": _theme_surface(Colors.STAR, base),
        "text": text,
        "text_secondary": text_secondary,
        "text_tertiary": text_tertiary,
    }


class _PlayerTextLabel(QLabel):
    """Single-line player label that elides during paint instead of clipping."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        colors = _player_theme_colors()
        self._paint_color_value = colors["text"]
        self._disabled_paint_color = colors["disabled"]
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def setPaintColor(self, color: str, disabled_color: str | None = None) -> None:
        self._paint_color_value = color
        if disabled_color is not None:
            self._disabled_paint_color = disabled_color
        self.update()

    def paintEvent(self, a0) -> None:
        painter = QPainter(self)
        painter.setFont(self.font())
        color = self._disabled_paint_color if not self.isEnabled() else self._paint_color_value
        painter.setPen(_paint_color(color))

        text = self.text()
        if text:
            fm = QFontMetrics(self.font())
            text = fm.elidedText(
                text,
                Qt.TextElideMode.ElideRight,
                max(0, self.width()),
            )
            painter.drawText(self.rect(), self.alignment(), text)
        painter.end()


class RatingStars(QWidget):
    """Compact 0-5 star rating editor using iPod rating units (stars x 20)."""

    rating_changed = pyqtSignal(int)
    _STAR_COUNT = 5
    _BASE_STAR_CELL_W = 16
    _BASE_STAR_H = 18

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rating = 0
        self._hover_rating: int | None = None
        self._star_cell_w = self._BASE_STAR_CELL_W
        colors = _player_theme_colors()
        self._active_color = colors["star"]
        self._inactive_color = colors["inactive_star"]
        self._disabled_color = colors["disabled"]
        self.setObjectName("playerRatingStars")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.refreshStyle()
        self.setRating(0)

    def rating(self) -> int:
        return self._rating

    def previewRating(self) -> int:
        return self._hover_rating if self._hover_rating is not None else self._rating

    def setRating(self, value: object) -> None:
        self._rating = _rating_value(value)
        self._sync_tooltip()
        self.update()

    def refreshStyle(self) -> None:
        self.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        fm = QFontMetrics(self.font())
        self._star_cell_w = max(
            self._BASE_STAR_CELL_W,
            fm.horizontalAdvance("★") + 4,
        )
        star_height = max(self._BASE_STAR_H, fm.height() + 2)
        self.setFixedSize(self._STAR_COUNT * self._star_cell_w, star_height)
        self.update()

    def setColors(self, active: str, inactive: str, disabled: str) -> None:
        self._active_color = active
        self._inactive_color = inactive
        self._disabled_color = disabled
        self.update()

    def paintEvent(self, a0) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(self.font())

        active_stars = self.previewRating() // 20
        active_color = self._active_color if self.isEnabled() else self._disabled_color
        inactive_color = self._inactive_color if self.isEnabled() else self._disabled_color
        for index in range(self._STAR_COUNT):
            rect = QRect(index * self._star_cell_w, 0, self._star_cell_w, self.height())
            is_active = index < active_stars
            if not is_active and active_stars == 0 and self._hover_rating is None:
                continue
            painter.setPen(_paint_color(active_color if is_active else inactive_color))
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                "★" if is_active else "☆",
            )
        painter.end()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None or not self.isEnabled():
            return
        self._hover_rating = self._rating_for_x(int(a0.position().x()))
        self._sync_tooltip()
        self.update()

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None or not self.isEnabled() or a0.button() != Qt.MouseButton.LeftButton:
            return
        value = self._rating_for_x(int(a0.position().x()))
        rating = 0 if self._rating == value else value
        self._hover_rating = None
        self.setRating(rating)
        self.rating_changed.emit(rating)

    def leaveEvent(self, a0: QEvent | None) -> None:
        self._hover_rating = None
        self._sync_tooltip()
        self.update()
        super().leaveEvent(a0)

    def starCenter(self, star: int) -> QPoint:
        clamped = max(1, min(self._STAR_COUNT, int(star)))
        return QPoint(
            (clamped - 1) * self._star_cell_w + self._star_cell_w // 2,
            self.height() // 2,
        )

    def _rating_for_x(self, x: int) -> int:
        star = max(1, min(self._STAR_COUNT, x // self._star_cell_w + 1))
        return star * 20

    def _sync_tooltip(self) -> None:
        rating = self.previewRating()
        if rating <= 0:
            self.setToolTip("No rating")
            return
        stars = rating // 20
        self.setToolTip(f"Rate {stars} star{'s' if stars != 1 else ''}")


class MusicPlayerBar(QFrame):
    """Dockable player chrome for local iPod track playback."""

    _BAR_MARGIN_X = 24
    _BAR_MARGIN_Y = 2

    play_pause_requested = pyqtSignal(bool)
    previous_requested = pyqtSignal()
    next_requested = pyqtSignal()
    seek_requested = pyqtSignal(int)
    rating_changed = pyqtSignal(int)
    volume_changed = pyqtSignal(int)
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._is_playing = False
        self._duration_ms = 0
        self._artwork_data: tuple[int, int, bytes] | None = None
        self._track: dict | None = None
        self._dock_position = PLAYER_POSITION_TOP
        self._player_colors = _player_theme_colors()

        self.setObjectName("MusicPlayerBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.surface = QFrame()
        self.surface.setObjectName("MusicPlayerSurface")
        self.surface.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.left_chrome = QWidget()
        self.left_chrome.setObjectName("MusicPlayerLeftChrome")
        self.left_chrome.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.center_chrome = QWidget()
        self.center_chrome.setObjectName("MusicPlayerCenterChrome")
        self.center_chrome.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.right_chrome = QWidget()
        self.right_chrome.setObjectName("MusicPlayerRightChrome")
        self.right_chrome.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.art_label = QLabel()
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_label.setFixedSize(56, 56)

        self.title_label = _PlayerTextLabel("No track selected")
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.detail_label = _PlayerTextLabel("")
        self.detail_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.detail_label.setMinimumWidth(0)
        self.detail_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.queue_label = _PlayerTextLabel("")
        self.queue_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.queue_label.setMinimumWidth(0)
        self.queue_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.queue_label.setVisible(False)

        self._text_layout = QVBoxLayout()
        text_layout = self._text_layout
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        self.current_time_label = QLabel("0:00")
        self.current_time_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.current_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.setSingleStep(1000)
        self.progress_slider.setPageStep(10_000)
        self.progress_slider.setEnabled(False)
        self.progress_slider.sliderMoved.connect(self.seek_requested.emit)

        self.duration_label = QLabel("0:00")
        self.duration_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)
        progress_layout.addWidget(self.current_time_label)
        progress_layout.addWidget(self.progress_slider, 1)
        progress_layout.addWidget(self.duration_label)

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.detail_label)
        text_layout.addSpacing(2)
        text_layout.addLayout(progress_layout)

        self.previous_button = self._make_icon_button("skip-back", "Previous track", size=34)
        self.play_button = self._make_icon_button("play", "Play", size=44, accent=True)
        self.next_button = self._make_icon_button("skip-forward", "Next track", size=34)
        self.close_button = self._make_icon_button("close", "Close player", size=44)
        self.queue_button = self._make_icon_button("playlist", "Playback queue", size=24)

        self.previous_button.clicked.connect(self.previous_requested.emit)
        self.play_button.clicked.connect(self._toggle_playing)
        self.next_button.clicked.connect(self.next_requested.emit)
        self.close_button.clicked.connect(self.close_requested.emit)

        self._controls_layout = QHBoxLayout()
        controls = self._controls_layout
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)

        self.rating_control = RatingStars()
        self.rating_control.rating_changed.connect(self.rating_changed.emit)

        self.volume_icon_label = QLabel()
        self.volume_icon_label.setFixedSize(14, 14)
        self.volume_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.volume_icon_label.setVisible(False)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("playerVolumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(138)
        self.volume_slider.valueChanged.connect(self._on_volume_slider_changed)

        self.volume_label = QLabel("100%")
        self.volume_label.setObjectName("playerVolumeLabel")
        self.volume_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.volume_label.setFixedWidth(30)
        self.volume_label.setVisible(False)

        self._volume_layout = QHBoxLayout()
        volume_layout = self._volume_layout
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(6)
        volume_layout.addWidget(self.volume_icon_label)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_label)

        self._left_chrome_layout = QHBoxLayout(self.left_chrome)
        self._left_chrome_layout.setContentsMargins(0, 0, 0, 0)
        self._left_chrome_layout.setSpacing(16)
        self._left_chrome_layout.addLayout(controls)
        self._left_chrome_layout.addLayout(volume_layout)

        self._utility_layout = QVBoxLayout()
        utility_layout = self._utility_layout
        utility_layout.setContentsMargins(0, 0, 0, 0)
        utility_layout.setSpacing(3)
        utility_layout.addStretch(1)
        utility_layout.addWidget(self.queue_button, 0, Qt.AlignmentFlag.AlignHCenter)
        utility_layout.addWidget(self.rating_control, 0, Qt.AlignmentFlag.AlignHCenter)
        utility_layout.addStretch(1)

        self._surface_layout = QHBoxLayout(self.surface)
        surface_layout = self._surface_layout
        surface_layout.setContentsMargins(7, 2, 8, 2)
        surface_layout.setSpacing(8)
        surface_layout.addWidget(self.art_label, 0, Qt.AlignmentFlag.AlignVCenter)
        surface_layout.addLayout(text_layout, 1)
        surface_layout.addLayout(utility_layout, 0)

        self._center_chrome_layout = QHBoxLayout(self.center_chrome)
        self._center_chrome_layout.setContentsMargins(0, 0, 0, 0)
        self._center_chrome_layout.setSpacing(0)
        self._center_chrome_layout.addWidget(self.surface, 1)

        self._right_chrome_layout = QHBoxLayout(self.right_chrome)
        self._right_chrome_layout.setContentsMargins(0, 0, 0, 0)
        self._right_chrome_layout.setSpacing(0)
        self._right_chrome_layout.addStretch(1)
        self._right_chrome_layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self._bar_layout = QHBoxLayout(self)
        layout = self._bar_layout
        layout.setContentsMargins(
            self._BAR_MARGIN_X,
            self._BAR_MARGIN_Y,
            self._BAR_MARGIN_X,
            self._BAR_MARGIN_Y,
        )
        layout.setSpacing(20)
        layout.addWidget(self.left_chrome)
        layout.addWidget(self.center_chrome, 1)
        layout.addWidget(self.right_chrome)

        self.refreshStyle()
        self.setTransportAvailability(False, False)
        self.setQueueContext(-1, 0)

    def setDockPosition(self, position: str) -> None:
        position = normalize_player_position(position)
        if position == self._dock_position:
            return
        self._dock_position = position
        self.refreshStyle()

    def refreshStyle(self) -> None:
        self._player_colors = _player_theme_colors()
        colors = self._player_colors
        geometry = self._refresh_scaled_geometry()
        height = geometry["bar_height"]
        surface_height = geometry["surface_height"]
        border_top = (
            "none"
            if self._dock_position == PLAYER_POSITION_TOP
            else f"1px solid {colors['panel_border']}"
        )
        border_bottom = (
            f"1px solid {colors['panel_border']}"
            if self._dock_position == PLAYER_POSITION_TOP
            else "none"
        )
        self.setFixedHeight(height)
        self.surface.setFixedHeight(surface_height)
        self.setStyleSheet(f"""
            QFrame#MusicPlayerBar {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors['bar_top']},
                    stop:0.48 {colors['bar_mid']},
                    stop:1 {colors['bar_bottom']});
                border-top: {border_top};
                border-left: none;
                border-right: none;
                border-bottom: {border_bottom};
            }}
            QFrame#MusicPlayerSurface {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors['panel_top']},
                    stop:0.5 {colors['panel_mid']},
                    stop:1 {colors['panel_bottom']});
                border: 1px solid {colors['panel_border']};
                border-top-color: {colors['panel_highlight']};
                border-radius: 5px;
            }}
            QWidget#MusicPlayerLeftChrome,
            QWidget#MusicPlayerCenterChrome,
            QWidget#MusicPlayerRightChrome {{
                background: transparent;
                border: none;
            }}
        """)
        self.art_label.setStyleSheet(f"""
            QLabel {{
                background: {colors['art_bg']};
                border: 1px solid {colors['art_border']};
                border-radius: 2px;
            }}
        """)
        self.title_label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)
        self.detail_label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)
        self.queue_label.setStyleSheet(f"""
            QLabel {{
                color: {colors['text_tertiary']};
                background: transparent;
                border: none;
            }}
        """)
        label_css = f"color: {colors['text_tertiary']}; background: transparent; border: none;"
        self.current_time_label.setStyleSheet(label_css)
        self.duration_label.setStyleSheet(label_css)
        self.title_label.setPaintColor(colors["text"], colors["disabled"])
        self.detail_label.setPaintColor(colors["text_secondary"], colors["disabled"])
        self.queue_label.setPaintColor(colors["text_tertiary"], colors["disabled"])
        self.rating_control.setColors(
            colors["star"],
            colors["inactive_star"],
            colors["disabled"],
        )
        self.progress_slider.setStyleSheet(
            self._themed_slider_css(
                handle_size=geometry["slider_handle"],
                groove_height=geometry["slider_groove"],
                colors=colors,
            )
        )
        self.volume_slider.setStyleSheet(
            self._themed_slider_css(
                handle_size=geometry["volume_handle"],
                groove_height=geometry["volume_groove"],
                colors=colors,
            )
        )
        self.volume_label.setStyleSheet(label_css)
        volume_pixmap = glyph_pixmap(
            "volume",
            geometry["volume_icon_size"],
            colors["icon"],
        )
        if volume_pixmap is not None:
            self.volume_icon_label.setPixmap(volume_pixmap)
        self._configure_icon_button(
            self.previous_button,
            "skip-back",
            "Previous track",
            geometry["transport_button_size"],
        )
        self._configure_icon_button(
            self.next_button,
            "skip-forward",
            "Next track",
            geometry["transport_button_size"],
        )
        self._configure_icon_button(
            self.close_button,
            "close",
            "Close player",
            geometry["close_button_size"],
        )
        self._configure_icon_button(
            self.queue_button,
            "playlist",
            self.queue_label.toolTip() or "Playback queue",
            geometry["queue_button_size"],
        )
        self._configure_icon_button(
            self.play_button,
            "play",
            "Play",
            geometry["play_button_size"],
            accent=True,
        )
        self._sync_surface_margins()
        self._apply_current_artwork()
        self._sync_play_icon()

    def setTrack(self, track: dict | None) -> None:
        self._track = track if isinstance(track, dict) else None
        if not track:
            self._duration_ms = 0
            self.title_label.setText("No track selected")
            self.title_label.setToolTip("")
            self.detail_label.setText("")
            self.detail_label.setToolTip("")
            self.queue_label.setText("")
            self.queue_label.setVisible(False)
            self.progress_slider.setRange(0, 0)
            self.progress_slider.setEnabled(False)
            self.current_time_label.setText("0:00")
            self.duration_label.setText("0:00")
            self.rating_control.setRating(0)
            self.rating_control.setEnabled(False)
            self._artwork_data = None
            self._set_fallback_art()
            self.setPlaying(False)
            return

        title = _first_text(track, "Title", "title", "name") or "Untitled Track"
        artist = _first_text(track, "Artist", "artist")
        album = _first_text(track, "Album", "album")
        detail = " - ".join(part for part in (artist, album) if part)

        self._duration_ms = _track_duration_ms(track)
        self.title_label.setText(title)
        self.title_label.setToolTip(title)
        self.detail_label.setText(detail)
        self.detail_label.setToolTip(detail)
        self.current_time_label.setText("0:00")
        self.duration_label.setText(_duration_text(self._duration_ms))
        self.progress_slider.setValue(0)
        self.progress_slider.setRange(0, self._duration_ms)
        self.progress_slider.setEnabled(self._duration_ms > 0)
        self.rating_control.setRating(track.get("rating", 0))
        self.rating_control.setEnabled(True)
        self._artwork_data = None
        self._set_fallback_art()
        self.setPlaying(False)

    def setPlaying(self, playing: bool) -> None:
        self._is_playing = bool(playing)
        self._sync_play_icon()

    def isPlaying(self) -> bool:
        return self._is_playing

    def setPosition(self, position_ms: int) -> None:
        position = min(max(0, _int_value(position_ms)), self._duration_ms)
        self.progress_slider.setValue(position)
        self.current_time_label.setText(_duration_text(position))

    def setDuration(self, duration_ms: int) -> None:
        duration = _int_value(duration_ms)
        if duration <= 0:
            return
        self._duration_ms = duration
        self.duration_label.setText(_duration_text(duration))
        self.progress_slider.setRange(0, duration)
        self.progress_slider.setEnabled(True)

    def setTransportAvailability(self, has_previous: bool, has_next: bool) -> None:
        self.previous_button.setEnabled(bool(has_previous))
        self.next_button.setEnabled(bool(has_next))

    def setQueueContext(self, index: int, total: int) -> None:
        if total <= 0 or index < 0:
            self.queue_label.setText("")
            self.queue_label.setToolTip("")
            if hasattr(self, "queue_button"):
                self.queue_button.setToolTip("Playback queue")
            self.queue_label.setVisible(False)
            return
        text = f"Track {index + 1:,} of {total:,}"
        self.queue_label.setText(text)
        self.queue_label.setToolTip(text)
        if hasattr(self, "queue_button"):
            self.queue_button.setToolTip(text)
        self.queue_label.setVisible(False)

    def setArtworkData(self, artwork: tuple[int, int, bytes] | None) -> None:
        self._artwork_data = artwork
        self._apply_current_artwork()

    def setVolumePercent(self, percent: int) -> None:
        value = max(0, min(100, _int_value(percent)))
        blocker = QSignalBlocker(self.volume_slider)
        self.volume_slider.setValue(value)
        del blocker
        self.volume_label.setText(f"{value}%")

    def volumePercent(self) -> int:
        return int(self.volume_slider.value())

    def _apply_current_artwork(self) -> None:
        artwork = self._artwork_data
        if artwork is None:
            self._set_fallback_art()
            return

        width, height, rgba = artwork
        if width <= 0 or height <= 0 or not rgba:
            self._set_fallback_art()
            return

        qimage = QImage(
            rgba,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        pixmap = self._contained_artwork_pixmap(QPixmap.fromImage(qimage))
        if pixmap.isNull():
            self._set_fallback_art()
            return
        self.art_label.setPixmap(pixmap)

    def _contained_artwork_pixmap(self, source: QPixmap) -> QPixmap:
        target = self.art_label.size()
        if source.isNull() or target.isEmpty():
            return QPixmap()

        inset = 0
        content_width = max(1, target.width() - inset * 2)
        content_height = max(1, target.height() - inset * 2)
        scaled = source.scaled(
            content_width,
            content_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        dpr = effective_device_pixel_ratio(self.art_label)
        canvas = QPixmap(
            logical_to_physical(target.width(), dpr),
            logical_to_physical(target.height(), dpr),
        )
        canvas.setDevicePixelRatio(dpr)
        canvas.fill(Qt.GlobalColor.transparent)

        x = (target.width() - scaled.width()) // 2
        y = (target.height() - scaled.height()) // 2
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(x, y, scaled)
        painter.end()
        return canvas

    def _toggle_playing(self) -> None:
        self.setPlaying(not self._is_playing)
        self.play_pause_requested.emit(self._is_playing)

    def _on_volume_slider_changed(self, value: int) -> None:
        percent = max(0, min(100, int(value)))
        self.volume_label.setText(f"{percent}%")
        self.volume_changed.emit(percent)

    def _sync_play_icon(self) -> None:
        colors = self._player_colors
        name = "pause" if self._is_playing else "play"
        tooltip = "Pause" if self._is_playing else "Play"
        icon_size = max(20, min(30, self.play_button.width() - 12))
        icon = glyph_icon(name, icon_size, colors["icon"])
        if icon is not None:
            self.play_button.setIcon(icon)
            self.play_button.setIconSize(QSize(icon_size, icon_size))
        self.play_button.setToolTip(tooltip)

    def _set_fallback_art(self) -> None:
        pixmap = glyph_pixmap(
            "music",
            max(20, self.art_label.width() // 2),
            self._player_colors["icon_disabled"],
        )
        if pixmap is not None:
            self.art_label.setPixmap(pixmap)

    def _make_icon_button(
        self,
        icon_name: str,
        tooltip: str,
        *,
        size: int = 30,
        accent: bool = False,
    ) -> QPushButton:
        button = QPushButton()
        button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._configure_icon_button(button, icon_name, tooltip, size, accent=accent)
        return button

    def _configure_icon_button(
        self,
        button: QPushButton,
        icon_name: str,
        tooltip: str,
        size: int,
        *,
        accent: bool = False,
    ) -> None:
        colors = self._player_colors
        button.setFixedSize(size, size)
        button.setToolTip(tooltip)
        button.setStyleSheet(
            self._accent_button_css(size, colors) if accent else self._icon_button_css(size, colors)
        )
        icon_size = max(14, min(30 if accent else 28, size - 10))
        icon = glyph_icon(
            icon_name,
            icon_size,
            colors["icon"],
        )
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QSize(icon_size, icon_size))

    def _refresh_scaled_geometry(self) -> dict[str, int]:
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.Bold))
        self.detail_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        self.queue_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.current_time_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.DemiBold))
        self.duration_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.DemiBold))
        self.volume_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_time_label.setVisible(True)
        self.duration_label.setVisible(True)

        title_h = max(14, QFontMetrics(self.title_label.font()).height())
        detail_h = max(12, QFontMetrics(self.detail_label.font()).height())
        meta_h = max(12, QFontMetrics(self.volume_label.font()).height() + 2)
        self.title_label.setFixedHeight(title_h)
        self.detail_label.setFixedHeight(detail_h)
        self.queue_label.setFixedHeight(meta_h)
        self.current_time_label.setFixedHeight(meta_h)
        self.duration_label.setFixedHeight(meta_h)
        self.volume_label.setFixedHeight(meta_h)
        time_w = max(
            42,
            QFontMetrics(self.current_time_label.font()).horizontalAdvance("-00:00") + 6,
        )
        self.current_time_label.setFixedWidth(time_w)
        self.duration_label.setFixedWidth(time_w)

        slider_handle = max(8, round(Metrics.FONT_XS * 1.05))
        slider_groove = max(3, round(slider_handle * 0.32))
        slider_h = max(meta_h, slider_handle + 3)
        self.progress_slider.setFixedHeight(slider_h)

        volume_handle = max(12, round(Metrics.FONT_MD * 1.15))
        volume_groove = max(5, round(volume_handle * 0.32))
        self.volume_slider.setFixedHeight(max(meta_h, volume_handle + 3))

        volume_label_w = max(
            30,
            QFontMetrics(self.volume_label.font()).horizontalAdvance("100%") + 6,
        )
        self.volume_label.setFixedWidth(volume_label_w)

        volume_icon_size = max(14, min(20, Metrics.FONT_XS + 6))
        self.volume_icon_label.setFixedSize(volume_icon_size, volume_icon_size)
        volume_slider_w = max(96, min(122, Metrics.FONT_MD * 9))
        self.volume_slider.setFixedWidth(volume_slider_w)
        self._volume_layout.setSpacing(max(5, Metrics.FONT_XS // 2))

        art_size = max(36, min(48, round(Metrics.FONT_MD * 3.7)))
        self.art_label.setFixedSize(art_size, art_size)

        transport_button_size = max(34, min(40, round(Metrics.FONT_MD * 2.6)))
        play_button_size = max(44, min(50, round(Metrics.FONT_MD * 3.2)))
        close_button_size = max(44, min(54, round(Metrics.FONT_MD * 3.4)))
        queue_button_size = max(24, min(30, round(Metrics.FONT_MD * 1.9)))
        control_spacing = max(6, round(Metrics.FONT_MD * 0.45))
        left_group_spacing = max(16, round(Metrics.FONT_MD * 1.25))
        surface_spacing = max(8, round(Metrics.FONT_MD * 0.55))
        surface_margin_y = max(2, Metrics.FONT_XS // 4)
        playback_gap = max(18, round(Metrics.FONT_MD * 1.8))
        self._controls_layout.setSpacing(control_spacing)
        self._left_chrome_layout.setSpacing(left_group_spacing)
        self._surface_layout.setSpacing(surface_spacing)
        self._text_layout.setSpacing(1)
        self._utility_layout.setSpacing(max(3, Metrics.FONT_XS // 3))
        self.rating_control.refreshStyle()
        self._sync_surface_margins(surface_margin_y)

        rating_height = self.rating_control.height()
        utility_h = queue_button_size + rating_height + self._utility_layout.spacing()
        text_h = (
            title_h
            + detail_h
            + slider_h
            + self._text_layout.spacing() * 2
            + 2
        )
        self._text_layout.invalidate()
        self._utility_layout.invalidate()
        self._surface_layout.invalidate()
        text_h = max(text_h, self._text_layout.minimumSize().height())
        utility_h = max(utility_h, self._utility_layout.minimumSize().height())
        content_h = max(art_size, play_button_size, text_h, utility_h)
        surface_height = max(
            38,
            content_h + surface_margin_y * 2,
            self._surface_layout.minimumSize().height(),
        )
        bar_height = max(44, surface_height + self._BAR_MARGIN_Y * 2)

        controls_width = (
            transport_button_size
            + play_button_size
            + transport_button_size
            + control_spacing * 2
        )
        left_width = controls_width + left_group_spacing + volume_slider_w
        self.left_chrome.setFixedWidth(left_width)
        self.left_chrome.setFixedHeight(surface_height)
        self.center_chrome.setMinimumHeight(surface_height)
        self.center_chrome.setFixedHeight(surface_height)
        self.right_chrome.setFixedWidth(close_button_size)
        self.right_chrome.setFixedHeight(surface_height)
        center_min_width = max(340, min(440, Metrics.FONT_MD * 30))
        center_max_width = max(920, min(1200, Metrics.FONT_MD * 110))
        self.surface.setMinimumWidth(center_min_width)
        self.surface.setMaximumWidth(center_max_width)

        self._bar_layout.setContentsMargins(
            self._BAR_MARGIN_X,
            self._BAR_MARGIN_Y,
            self._BAR_MARGIN_X,
            self._BAR_MARGIN_Y,
        )
        self._bar_layout.setSpacing(playback_gap)

        return {
            "bar_height": bar_height,
            "close_button_size": close_button_size,
            "play_button_size": play_button_size,
            "queue_button_size": queue_button_size,
            "slider_groove": slider_groove,
            "slider_handle": slider_handle,
            "surface_height": surface_height,
            "transport_button_size": transport_button_size,
            "volume_groove": volume_groove,
            "volume_handle": volume_handle,
            "volume_icon_size": volume_icon_size,
        }

    def _sync_surface_margins(self, surface_margin_y: int | None = None) -> None:
        if surface_margin_y is None:
            surface_margin_y = max(2, Metrics.FONT_XS // 4)
        left = max(7, round(Metrics.FONT_MD * 0.6))
        right = max(8, round(Metrics.FONT_MD * 0.65))
        self._surface_layout.setContentsMargins(
            left,
            surface_margin_y,
            right,
            surface_margin_y,
        )

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        if hasattr(self, "_surface_layout"):
            self._sync_surface_margins()

    @staticmethod
    def _icon_button_css(size: int, colors: dict[str, str]) -> str:
        radius = max(4, size // 2)
        return f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: {radius}px;
                padding: 0px;
                min-width: {size}px;
                max-width: {size}px;
                min-height: {size}px;
                max-height: {size}px;
            }}
            QPushButton:hover {{
                background: {colors['hover']};
            }}
            QPushButton:pressed {{
                background: {colors['pressed']};
                padding-top: 1px;
            }}
            QPushButton:disabled {{
                background: transparent;
                color: {colors['disabled']};
            }}
        """

    @staticmethod
    def _accent_button_css(size: int, colors: dict[str, str]) -> str:
        return MusicPlayerBar._icon_button_css(size, colors)

    @staticmethod
    def _themed_slider_css(
        *,
        handle_size: int = 12,
        groove_height: int = 4,
        colors: dict[str, str],
    ) -> str:
        handle_margin = -max(1, (handle_size - groove_height) // 2)
        handle_radius = max(1, handle_size // 2)
        handle_geometry = f"""
                width: {handle_size}px;
                height: {handle_size}px;
                margin: {handle_margin}px 0;
                border-radius: {handle_radius}px;
        """
        return f"""
            QSlider::groove:horizontal {{
                height: {groove_height}px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors['groove_top']},
                    stop:0.5 {colors['groove_mid']},
                    stop:1 {colors['groove_bottom']});
                border: 1px solid {colors['border']};
                border-radius: {max(1, groove_height // 2)}px;
            }}
            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors['groove_fill_top']},
                    stop:1 {colors['groove_fill_bottom']});
                border-radius: {max(1, groove_height // 2)}px;
            }}
            QSlider::handle:horizontal {{
                {handle_geometry}
                background: qradialgradient(cx:0.35, cy:0.25, radius:0.85,
                    stop:0 {colors['handle_top']},
                    stop:0.45 {colors['handle_mid']},
                    stop:1 {colors['handle_bottom']});
                border: 1px solid {colors['border']};
            }}
            QSlider::handle:horizontal:hover {{
                {handle_geometry}
                border-color: {colors['accent']};
            }}
            QSlider::handle:horizontal:pressed {{
                {handle_geometry}
                border-color: {colors['accent']};
            }}
            QSlider::groove:horizontal:disabled {{
                background: {colors['border_subtle']};
            }}
            QSlider::sub-page:horizontal:disabled {{
                background: {colors['border']};
            }}
            QSlider::handle:horizontal:disabled {{
                {handle_geometry}
                background: {colors['disabled']};
                border-color: {colors['border']};
            }}
        """
