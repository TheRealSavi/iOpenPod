from PyQt6.QtCore import Qt, QPoint, QSize
from PyQt6.QtWidgets import QHBoxLayout, QFrame, QLabel, QPushButton, QWidget
from PyQt6.QtGui import QFont

from ..styles import Colors, FONT_FAMILY, Metrics, scaled
from ..glyphs import glyph_icon


def _title_bar_css(r1: int, g1: int, b1: int, r2: int, g2: int, b2: int,
                   text_color: str = Colors.TEXT_ON_ACCENT,
                   text_secondary: str = Colors.TEXT_PRIMARY) -> str:
    """Generate the title bar stylesheet for given gradient colors."""
    return f"""
        QFrame {{
            background: rgba({r1},{g1},{b1},180);
            border: none;
            border-radius: 0px;
        }}
        QLabel {{
            font-weight: 700;
            font-size: {Metrics.FONT_TITLE}px;
            color: {text_color};
            background: transparent;
        }}
        QPushButton {{
            background-color: transparent;
            border: none;
            color: {text_secondary};
            font-size: {Metrics.FONT_TITLE}px;
            font-weight: bold;
            width: {scaled(28)}px;
            height: {scaled(28)}px;
            border-radius: {scaled(6)}px;
        }}
        QPushButton:hover {{
            background-color: rgba(255,255,255,30);
        }}
        QPushButton:pressed {{
            background-color: rgba(255,255,255,18);
        }}
    """


# Default blue gradient — call at runtime since scaled values aren't ready at import time
def _default_css() -> str:
    r, g, b = Colors.PLAYLIST_REGULAR
    return _title_bar_css(r, g, b, max(0, r - 25), max(0, g - 25), max(0, b - 25))


class TrackListTitleBar(QFrame):
    """Draggable title bar for the track list panel."""

    def __init__(self, splitterToControl):
        super().__init__()
        self.splitter = splitterToControl
        self.dragging = False
        self.dragStartPos = QPoint()
        self.setMouseTracking(True)
        self.titleBarLayout = QHBoxLayout(self)
        self.titleBarLayout.setContentsMargins(scaled(14), 0, scaled(10), 0)
        self.splitter.splitterMoved.connect(self.enforceMinHeight)

        self.setMinimumHeight(scaled(40))
        self.setMaximumHeight(scaled(40))
        self.setFixedHeight(scaled(40))

        self.setStyleSheet(_default_css())

        self.title = QLabel("Tracks")
        self.title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))

        self.button1 = QPushButton()
        _ic_sz = QSize(scaled(18), scaled(18))
        _ic_dn = glyph_icon("chevron-down", scaled(18), Colors.TEXT_ON_ACCENT)
        if _ic_dn:
            self.button1.setIcon(_ic_dn)
            self.button1.setIconSize(_ic_sz)
        else:
            self.button1.setText("▼")
        self.button1.setToolTip("Minimize")
        self.button1.clicked.connect(self._toggleMinimize)

        self.button2 = QPushButton()
        _ic_up = glyph_icon("chevron-up", scaled(18), Colors.TEXT_ON_ACCENT)
        if _ic_up:
            self.button2.setIcon(_ic_up)
            self.button2.setIconSize(_ic_sz)
        else:
            self.button2.setText("▲")
        self.button2.setToolTip("Maximize")
        self.button2.clicked.connect(self._toggleMaximize)

        self.titleBarLayout.addWidget(self.title)
        self.titleBarLayout.addStretch()
        self.titleBarLayout.addWidget(self.button1)
        self.titleBarLayout.addWidget(self.button2)

    def setTitle(self, title: str):
        """Set the title text."""
        self.title.setText(title)

    def setColor(self, r: int, g: int, b: int,
                 text: tuple | None = None, text_secondary: tuple | None = None):
        """Set the title bar gradient to the given RGB color with optional text colors."""
        r2 = min(255, r + 25)
        g2 = min(255, g + 25)
        b2 = min(255, b + 25)
        r3 = max(0, r - 25)
        g3 = max(0, g - 25)
        b3 = max(0, b - 25)
        txt = f"rgb({text[0]},{text[1]},{text[2]})" if text else Colors.TEXT_ON_ACCENT
        txt_sec = f"rgba({text_secondary[0]},{text_secondary[1]},{text_secondary[2]},180)" if text_secondary else Colors.TEXT_PRIMARY
        self.setStyleSheet(_title_bar_css(r2, g2, b2, r3, g3, b3,
                                          text_color=txt,
                                          text_secondary=txt_sec))
        self._set_handle_color(f"rgba({r2},{g2},{b2},180)")

    def resetColor(self):
        """Reset to the default blue gradient."""
        self.setStyleSheet(_default_css())
        r, g, b = Colors.PLAYLIST_REGULAR
        self._set_handle_color(f"rgba({r},{g},{b},180)")

    def _set_handle_color(self, color: str):
        """Update the splitter handle to match the title bar color."""
        self.splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {color};
            }}
        """)

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
            if self.childAt(a0.pos()) is None:
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
        if event:
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
