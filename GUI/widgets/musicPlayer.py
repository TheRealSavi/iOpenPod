from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QImage, QMouseEvent, QPainter, QPixmap
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

from infrastructure.settings_schema import (
    PLAYER_POSITION_BOTTOM,
    PLAYER_POSITION_TOP,
    normalize_player_position,
)

from ..glyphs import glyph_icon, glyph_pixmap
from ..hidpi import effective_device_pixel_ratio, logical_to_physical
from ..styles import (
    FONT_FAMILY,
    LABEL_PRIMARY,
    LABEL_SECONDARY,
    LABEL_TERTIARY,
    Colors,
    Metrics,
    btn_css,
)
from .formatters import format_duration_mmss


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


class RatingStars(QWidget):
    """Compact 0-5 star rating editor using iPod rating units (stars x 20)."""

    rating_changed = pyqtSignal(int)
    _STAR_COUNT = 5
    _STAR_CELL_W = 16
    _STAR_H = 18

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rating = 0
        self._hover_rating: int | None = None
        self.setObjectName("playerRatingStars")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(self._STAR_COUNT * self._STAR_CELL_W, self._STAR_H)
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
        self.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        self.update()

    def paintEvent(self, a0) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(self.font())

        active_stars = self.previewRating() // 20
        active_color = Colors.STAR if self.isEnabled() else Colors.TEXT_DISABLED
        inactive_color = Colors.TEXT_DISABLED
        for index in range(self._STAR_COUNT):
            rect = QRect(index * self._STAR_CELL_W, 0, self._STAR_CELL_W, self.height())
            is_active = index < active_stars
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
            (clamped - 1) * self._STAR_CELL_W + self._STAR_CELL_W // 2,
            self.height() // 2,
        )

    def _rating_for_x(self, x: int) -> int:
        star = max(1, min(self._STAR_COUNT, x // self._STAR_CELL_W + 1))
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
        self._dock_position = PLAYER_POSITION_BOTTOM

        self.setObjectName("MusicPlayerBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.surface = QFrame()
        self.surface.setObjectName("MusicPlayerSurface")
        self.surface.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.art_label = QLabel()
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_label.setFixedSize(40, 40)

        self.title_label = QLabel("No track selected")
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        self.detail_label = QLabel("")
        self.detail_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.detail_label.setMinimumWidth(0)
        self.detail_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        self.queue_label = QLabel("")
        self.queue_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.queue_label.setMinimumWidth(0)
        self.queue_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.queue_label.setVisible(False)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.current_time_label = QLabel("0:00")
        self.current_time_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.current_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.current_time_label.setVisible(False)

        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.setSingleStep(1000)
        self.progress_slider.setPageStep(10_000)
        self.progress_slider.setEnabled(False)
        self.progress_slider.sliderMoved.connect(self.seek_requested.emit)

        self.duration_label = QLabel("0:00")
        self.duration_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.duration_label.setVisible(False)

        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(0)
        progress_layout.addWidget(self.current_time_label)
        progress_layout.addWidget(self.progress_slider, 1)
        progress_layout.addWidget(self.duration_label)

        text_layout.addStretch(1)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.detail_label)
        text_layout.addSpacing(1)
        text_layout.addLayout(progress_layout)
        text_layout.addStretch(1)

        self.previous_button = self._make_icon_button("skip-back", "Previous track", size=28)
        self.play_button = self._make_icon_button("play", "Play", size=34, accent=True)
        self.next_button = self._make_icon_button("skip-forward", "Next track", size=28)
        self.close_button = self._make_icon_button("close", "Close player", size=26)

        self.previous_button.clicked.connect(self.previous_requested.emit)
        self.play_button.clicked.connect(self._toggle_playing)
        self.next_button.clicked.connect(self.next_requested.emit)
        self.close_button.clicked.connect(self.close_requested.emit)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)

        self.rating_control = RatingStars()
        self.rating_control.rating_changed.connect(self.rating_changed.emit)

        self.volume_icon_label = QLabel()
        self.volume_icon_label.setFixedSize(14, 14)
        self.volume_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("playerVolumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(64)
        self.volume_slider.valueChanged.connect(self._on_volume_slider_changed)

        self.volume_label = QLabel("100%")
        self.volume_label.setObjectName("playerVolumeLabel")
        self.volume_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.volume_label.setFixedWidth(30)

        volume_layout = QHBoxLayout()
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(5)
        volume_layout.addWidget(self.volume_icon_label)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_label)

        utility_top_layout = QHBoxLayout()
        utility_top_layout.setContentsMargins(0, 0, 0, 0)
        utility_top_layout.setSpacing(6)
        utility_top_layout.addWidget(self.rating_control, 0, Qt.AlignmentFlag.AlignVCenter)

        utility_layout = QVBoxLayout()
        utility_layout.setContentsMargins(0, 0, 0, 0)
        utility_layout.setSpacing(2)
        utility_layout.addStretch(1)
        utility_layout.addLayout(utility_top_layout)
        utility_layout.addLayout(volume_layout)
        utility_layout.addStretch(1)

        surface_layout = QHBoxLayout(self.surface)
        surface_layout.setContentsMargins(14, 4, 12, 4)
        surface_layout.setSpacing(10)
        surface_layout.addLayout(controls, 0)
        surface_layout.addWidget(self.art_label)
        surface_layout.addLayout(text_layout, 1)
        surface_layout.addLayout(utility_layout, 0)
        surface_layout.addWidget(self.close_button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(0)
        layout.addWidget(self.surface)

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
        height = max(54, Metrics.FONT_MD * 5)
        surface_height = max(44, height - 8)
        border_top = (
            "none"
            if self._dock_position == PLAYER_POSITION_TOP
            else f"1px solid {Colors.BORDER}"
        )
        border_bottom = (
            f"1px solid {Colors.BORDER}"
            if self._dock_position == PLAYER_POSITION_TOP
            else "none"
        )
        self.setFixedHeight(height)
        self.surface.setFixedHeight(surface_height)
        self.setStyleSheet(f"""
            QFrame#MusicPlayerBar {{
                background: {Colors.DIALOG_BG};
                border-top: {border_top};
                border-left: none;
                border-right: none;
                border-bottom: {border_bottom};
            }}
            QFrame#MusicPlayerSurface {{
                background: {Colors.SURFACE};
                border: none;
                border-radius: {surface_height // 2}px;
            }}
        """)
        self.art_label.setStyleSheet(f"""
            QLabel {{
                background: transparent;
                border: none;
                border-radius: {Metrics.BORDER_RADIUS}px;
            }}
        """)
        self.title_label.setStyleSheet(LABEL_PRIMARY())
        self.detail_label.setStyleSheet(LABEL_SECONDARY())
        self.queue_label.setStyleSheet(f"""
            QLabel {{
                {LABEL_TERTIARY()}
                padding: 2px 7px;
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                background: {Colors.SURFACE_ALT};
            }}
        """)
        self.current_time_label.setStyleSheet(LABEL_TERTIARY())
        self.duration_label.setStyleSheet(LABEL_TERTIARY())
        self.progress_slider.setStyleSheet(self._slider_css(handle_size=8, groove_height=2))
        self.volume_slider.setStyleSheet(self._slider_css(handle_size=8, groove_height=2))
        self.volume_label.setStyleSheet(LABEL_TERTIARY())
        volume_pixmap = glyph_pixmap("volume", 14, Colors.TEXT_TERTIARY)
        if volume_pixmap is not None:
            self.volume_icon_label.setPixmap(volume_pixmap)
        self.rating_control.refreshStyle()
        for button in (self.previous_button, self.next_button, self.close_button):
            button.setStyleSheet(self._icon_button_css(button.width()))
        self.play_button.setStyleSheet(self._accent_button_css(self.play_button.width()))
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
            self.queue_label.setVisible(False)
            return
        text = f"Track {index + 1:,} of {total:,}"
        self.queue_label.setText(text)
        self.queue_label.setToolTip(text)
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
        name = "pause" if self._is_playing else "play"
        tooltip = "Pause" if self._is_playing else "Play"
        icon = glyph_icon(name, 20, Colors.TEXT_PRIMARY)
        if icon is not None:
            self.play_button.setIcon(icon)
            self.play_button.setIconSize(QSize(20, 20))
        self.play_button.setToolTip(tooltip)

    def _set_fallback_art(self) -> None:
        pixmap = glyph_pixmap("music", 20, Colors.TEXT_TERTIARY)
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
        button.setFixedSize(size, size)
        button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        button.setToolTip(tooltip)
        button.setStyleSheet(
            self._accent_button_css(size) if accent else self._icon_button_css(size)
        )
        icon_size = max(14, min(20, size - 12))
        icon = glyph_icon(
            icon_name,
            icon_size,
            Colors.TEXT_PRIMARY if accent else Colors.TEXT_SECONDARY,
        )
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QSize(icon_size, icon_size))
        return button

    @staticmethod
    def _icon_button_css(size: int) -> str:
        return btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_HOVER,
            bg_press=Colors.SURFACE_ACTIVE,
            fg=Colors.TEXT_PRIMARY,
            bg_disabled="transparent",
            fg_disabled=Colors.TEXT_DISABLED,
            padding="0px",
            radius=max(Metrics.BORDER_RADIUS_SM, size // 2),
            extra=(
                f"min-width: {size}px; max-width: {size}px; "
                f"min-height: {size}px; max-height: {size}px;"
            ),
        )

    @staticmethod
    def _accent_button_css(size: int) -> str:
        return btn_css(
            bg="transparent",
            bg_hover=Colors.ACCENT_MUTED,
            bg_press=Colors.SURFACE_ACTIVE,
            fg=Colors.TEXT_PRIMARY,
            border="none",
            bg_disabled="transparent",
            fg_disabled=Colors.TEXT_DISABLED,
            padding="0px",
            radius=max(Metrics.BORDER_RADIUS_SM, size // 2),
            extra=(
                f"min-width: {size}px; max-width: {size}px; "
                f"min-height: {size}px; max-height: {size}px;"
            ),
        )

    @staticmethod
    def _slider_css(handle_size: int = 12, groove_height: int = 4) -> str:
        handle_margin = -max(1, (handle_size - groove_height) // 2)
        handle_radius = max(1, handle_size // 2)
        return f"""
            QSlider::groove:horizontal {{
                height: {groove_height}px;
                background: {Colors.SURFACE_ALT};
                border: none;
                border-radius: {max(1, groove_height // 2)}px;
            }}
            QSlider::sub-page:horizontal {{
                background: {Colors.ACCENT};
                border-radius: {max(1, groove_height // 2)}px;
            }}
            QSlider::handle:horizontal {{
                width: {handle_size}px;
                height: {handle_size}px;
                margin: {handle_margin}px 0;
                border-radius: {handle_radius}px;
                background: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
            }}
            QSlider::handle:horizontal:hover {{
                background: {Colors.ACCENT_LIGHT};
                border-color: {Colors.ACCENT_BORDER};
            }}
            QSlider::groove:horizontal:disabled {{
                background: {Colors.SURFACE};
            }}
            QSlider::sub-page:horizontal:disabled {{
                background: {Colors.SURFACE_HOVER};
            }}
            QSlider::handle:horizontal:disabled {{
                background: {Colors.TEXT_DISABLED};
                border-color: {Colors.BORDER_SUBTLE};
            }}
        """
