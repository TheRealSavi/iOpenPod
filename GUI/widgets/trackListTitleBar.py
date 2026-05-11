from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ..glyphs import glyph_icon
from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
    display_accent_rgb,
    text_rgb_for_background,
)

_TITLE_BAR_CONTRAST_TARGET = 2.95
_TITLE_BAR_CORNER_RADIUS = 8


def _mix_rgb(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, float(amount)))
    left_red, left_green, left_blue = left
    right_red, right_green, right_blue = right
    return (
        int(round((left_red * (1.0 - amount)) + (right_red * amount))),
        int(round((left_green * (1.0 - amount)) + (right_green * amount))),
        int(round((left_blue * (1.0 - amount)) + (right_blue * amount))),
    )


def _css_rgb(rgb: tuple[int, int, int]) -> str:
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"


def _css_rgba(rgb: tuple[int, int, int], alpha: int) -> str:
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{alpha})"


def _title_bar_css(
    *,
    top_rgb: tuple[int, int, int],
    bottom_rgb: tuple[int, int, int],
    border_rgb: tuple[int, int, int],
    text_rgb: tuple[int, int, int],
    text_secondary_rgb: tuple[int, int, int],
) -> str:
    """Generate a refined, contrast-limited title bar stylesheet."""
    text_color = _css_rgb(text_rgb)
    text_secondary = _css_rgba(text_secondary_rgb, 205)
    button_bg = _css_rgba(text_rgb, 18)
    button_hover = _css_rgba(text_rgb, 30)
    button_press = _css_rgba(text_rgb, 24)
    return f"""
        QFrame {{
            background: qlineargradient(
                x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 {_css_rgba(top_rgb, 190)},
                stop: 1 {_css_rgba(bottom_rgb, 178)}
            );
            border: none;
            border-bottom: 1px solid {_css_rgba(border_rgb, 130)};
            border-top-left-radius: {_TITLE_BAR_CORNER_RADIUS}px;
            border-top-right-radius: {_TITLE_BAR_CORNER_RADIUS}px;
            border-bottom-left-radius: 0px;
            border-bottom-right-radius: 0px;
        }}
        QLabel {{
            font-weight: 700;
            font-size: {Metrics.FONT_TITLE}px;
            color: {text_color};
            background: transparent;
        }}
        QPushButton {{
            background-color: {button_bg};
            border: none;
            color: {text_secondary};
            font-size: {Metrics.FONT_TITLE}px;
            font-weight: bold;
            width: {(28)}px;
            height: {(28)}px;
            border-radius: {(6)}px;
        }}
        QPushButton:hover {{
            background-color: {button_hover};
        }}
        QPushButton:pressed {{
            background-color: {button_press};
        }}
    """


def _resolve_bar_palette(
    base_rgb: tuple[int, int, int],
    *,
    text: tuple[int, int, int] | None = None,
    text_secondary: tuple[int, int, int] | None = None,
) -> dict[str, tuple[int, int, int]]:
    """Limit and shape a title-bar palette so it sits comfortably in the app."""
    bg = display_accent_rgb(
        base_rgb,
        background=Colors.BG_DARK,
        target_ratio=_TITLE_BAR_CONTRAST_TARGET,
    )
    top = _mix_rgb(bg, (255, 255, 255), 0.08)
    bottom = _mix_rgb(bg, (0, 0, 0), 0.16)
    primary_text = text or text_rgb_for_background(bg)
    secondary_text = text_secondary or _mix_rgb(primary_text, bg, 0.3)
    border = _mix_rgb(bg, (0, 0, 0), 0.28)
    return {
        "bg": bg,
        "top": top,
        "bottom": bottom,
        "border": border,
        "text": primary_text,
        "text_secondary": secondary_text,
    }


class TrackListTitleBar(QFrame):
    """Draggable title bar for the track list panel."""

    def __init__(self, splitterToControl):
        super().__init__()
        self.splitter = splitterToControl
        self.dragging = False
        self.dragStartPos = QPoint()
        self._fullscreen_mode = False
        self.setMouseTracking(True)
        self.titleBarLayout = QHBoxLayout(self)
        self.titleBarLayout.setContentsMargins((14), 0, (10), 0)
        self.splitter.splitterMoved.connect(self.enforceMinHeight)

        self.setMinimumHeight(40)
        self.setMaximumHeight(40)
        self.setFixedHeight(40)

        self.title = QLabel("Tracks")
        self.title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))

        self.button1 = QPushButton()
        self._icon_size = QSize(18, 18)
        self.button1.setToolTip("Minimize")
        self.button1.clicked.connect(self._toggleMinimize)

        self.button2 = QPushButton()
        self.button2.setToolTip("Maximize")
        self.button2.clicked.connect(self._toggleMaximize)

        self.titleBarLayout.addWidget(self.title)
        self.titleBarLayout.addStretch()
        self.titleBarLayout.addWidget(self.button1)
        self.titleBarLayout.addWidget(self.button2)

        self.resetColor()

    def setTitle(self, title: str):
        """Set the title text."""
        self.title.setText(title)

    def setColor(self, r: int, g: int, b: int,
                 text: tuple | None = None, text_secondary: tuple | None = None):
        """Set the title bar color using a limited, contrast-aware palette."""
        palette = _resolve_bar_palette(
            (r, g, b),
            text=text,
            text_secondary=text_secondary,
        )
        self._apply_palette(palette)

    def setFullscreenMode(self, fullscreen: bool):
        """Enable/disable fullscreen mode. Hides buttons and disables dragging."""
        self._fullscreen_mode = fullscreen
        self.button1.setVisible(not fullscreen)
        self.button2.setVisible(not fullscreen)
        self.unsetCursor()

    def resetColor(self):
        """Reset to the default limited title-bar palette."""
        self._apply_palette(_resolve_bar_palette(Colors.PLAYLIST_REGULAR))

    def _set_handle_color(self):
        """Keep the splitter handle invisible in every interaction state."""
        self.splitter.setStyleSheet("""
            QSplitter::handle:vertical {{
                background: transparent;
            }}
            QSplitter::handle:vertical:hover {{
                background: transparent;
            }}
            QSplitter::handle:vertical:pressed {{
                background: transparent;
            }}
        """)

    def _apply_palette(self, palette: dict[str, tuple[int, int, int]]) -> None:
        self.setStyleSheet(
            _title_bar_css(
                top_rgb=palette["top"],
                bottom_rgb=palette["bottom"],
                border_rgb=palette["border"],
                text_rgb=palette["text"],
                text_secondary_rgb=palette["text_secondary"],
            )
        )
        self._set_handle_color()
        self._refresh_button_icons(palette["text_secondary"])

    def _refresh_button_icons(self, rgb: tuple[int, int, int]) -> None:
        down_icon = glyph_icon("chevron-down", 18, _css_rgb(rgb))
        if down_icon:
            self.button1.setIcon(down_icon)
            self.button1.setIconSize(self._icon_size)
            self.button1.setText("")
        else:
            self.button1.setText("▼")

        up_icon = glyph_icon("chevron-up", 18, _css_rgb(rgb))
        if up_icon:
            self.button2.setIcon(up_icon)
            self.button2.setIconSize(self._icon_size)
            self.button2.setText("")
        else:
            self.button2.setText("▲")

    def _toggleMinimize(self):
        """Minimize the track list panel."""
        sizes = self.splitter.sizes()
        total = sum(sizes)
        # Set track panel to minimum (just title bar)
        self.splitter.setSizes([total - 40, 40])

    def _toggleMaximize(self):
        """Maximize the track list panel."""
        sizes = self.splitter.sizes()
        total = sum(sizes)
        # Set track panel to 80% of space
        self.splitter.setSizes([int(total * 0.2), int(total * 0.8)])

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            if not self._fullscreen_mode and self.childAt(a0.pos()) is None:
                self.dragging = True
                self.dragStartPos = a0.globalPosition().toPoint()
                a0.accept()
            else:
                a0.ignore()

    def mouseMoveEvent(self, a0):
        if self.dragging and a0:
            self.dragStartPos = a0.globalPosition().toPoint()

            new_pos = self.splitter.mapFromGlobal(
                a0.globalPosition().toPoint()).y()

            parent = self.splitter.parent()
            max_pos = parent.height() - self.splitter.handleWidth() if parent else 0

            new_pos = max(0, min(new_pos, max_pos))

            # move the splitter handle
            self.splitter.moveSplitter(new_pos, 1)
            a0.accept()
        elif a0:
            a0.ignore()

    def mouseReleaseEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            a0.accept()

    def enterEvent(self, event):  # type: ignore[override]
        if event and not self._fullscreen_mode:
            pos = event.position().toPoint()
            if self.childAt(pos) is None:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.unsetCursor()

    def leaveEvent(self, a0):
        self.unsetCursor()
        super().leaveEvent(a0)

    def enforceMinHeight(self):
        sizes = self.splitter.sizes()
        min_height = self.minimumHeight()
        parent = self.parent()
        if sizes[1] <= min_height:
            if parent:
                for child in parent.children():
                    if isinstance(child, QWidget) and child != self:
                        child.hide()
        else:
            if parent:
                for child in parent.children():
                    if isinstance(child, QWidget):
                        child.show()

        if sizes[1] < min_height:
            total = sizes[0] + sizes[1]
            sizes[1] = min_height
            sizes[0] = max(total - min_height, 0)
            self.splitter.setSizes(sizes)
