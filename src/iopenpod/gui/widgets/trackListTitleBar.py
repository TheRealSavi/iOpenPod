from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from iopenpod.infrastructure.theme_renderer import TrackTitleBarPaints, render_track_title_bar_paints

from ..glyphs import glyph_icon
from ..styles import (
    FONT_FAMILY,
    Metrics,
    current_theme,
    icon_btn_css,
)

_TITLE_BAR_CORNER_RADIUS = 8
_TITLE_BAR_SEARCH_WIDTH = 190
_TITLE_BAR_SEARCH_HEIGHT = 28


def _title_bar_css(paints: TrackTitleBarPaints) -> str:
    """Adapt renderer-owned title-bar paints to the Qt stylesheet."""
    if paints.gradient_middle is not None:
        background_css = f"""
            background: qlineargradient(
                x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 {paints.gradient_top.css},
                stop: 0.58 {paints.gradient_middle.css},
                stop: 1 {paints.gradient_bottom.css}
            );
        """
        border_css = ""
    else:
        background_css = f"""
            background: qlineargradient(
                x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 {paints.gradient_top.css},
                stop: 1 {paints.gradient_bottom.css}
            );
        """
        border_css = f"border-bottom: 1px solid {paints.border.css};" if paints.border else ""

    return f"""
        QFrame {{
            {background_css}
            border: none;
            {border_css}
            border-top-left-radius: {_TITLE_BAR_CORNER_RADIUS}px;
            border-top-right-radius: {_TITLE_BAR_CORNER_RADIUS}px;
            border-bottom-left-radius: 0px;
            border-bottom-right-radius: 0px;
        }}
        QLabel {{
            font-weight: 700;
            font-size: {Metrics.FONT_TITLE}pt;
            color: {paints.title_text.css};
            background: transparent;
        }}
    """ + icon_btn_css(
        28,
        bg=paints.button_fill.css,
        bg_hover=paints.button_hover.css,
        bg_press=paints.button_pressed.css,
        fg=paints.secondary_text.css,
        radius=6,
    )


def _title_bar_search_css(paints: TrackTitleBarPaints) -> str:
    """Adapt renderer-owned search paints to the Qt stylesheet."""
    return f"""
        QLineEdit#trackListTitleSearchField {{
            background: {paints.search_fill.css};
            border: 1px solid {paints.search_border.css};
            border-radius: {_TITLE_BAR_SEARCH_HEIGHT // 2}px;
            color: {paints.search_text.css};
            placeholder-text-color: {paints.search_placeholder.css};
            padding: 0px 10px;
            font-size: {Metrics.FONT_BROWSER_SEARCH}pt;
            font-weight: 500;
        }}
        QLineEdit#trackListTitleSearchField:focus {{
            background: {paints.search_focus_fill.css};
            border-color: {paints.search_focus_border.css};
            color: {paints.search_focus_text.css};
        }}
    """


class TrackListTitleBar(QFrame):
    """Draggable title bar for the track list panel."""

    search_changed = pyqtSignal(str)

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

        title_bar_height = max(40, Metrics.FONT_TITLE * 2)
        self.setMinimumHeight(title_bar_height)
        self.setMaximumHeight(title_bar_height)
        self.setFixedHeight(title_bar_height)

        self.title = QLabel("Tracks")
        self.title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))

        self.button1 = QPushButton()
        self._icon_size = QSize(18, 18)
        self.button1.setToolTip("Minimize")
        self.button1.clicked.connect(self._toggleMinimize)

        self.button2 = QPushButton()
        self.button2.setToolTip("Maximize")
        self.button2.clicked.connect(self._toggleMaximize)

        self.search = QLineEdit(self)
        self.search.setObjectName("trackListTitleSearchField")
        self.search.setPlaceholderText("Search tracks")
        self.search.setAccessibleName("Search tracks")
        self.search.setToolTip(
            "Search visible and hidden track metadata in the current list"
        )
        self.search.setClearButtonEnabled(True)
        self.search.setFixedSize(
            _TITLE_BAR_SEARCH_WIDTH,
            _TITLE_BAR_SEARCH_HEIGHT,
        )
        self._search_icon_action: QAction | None = None
        self.search.textChanged.connect(self.search_changed.emit)

        self.titleBarLayout.addWidget(self.title)
        self.titleBarLayout.addStretch()
        self.titleBarLayout.addWidget(self.search)
        self.titleBarLayout.addWidget(self.button1)
        self.titleBarLayout.addWidget(self.button2)

        self.resetColor()

    def setTitle(self, title: str):
        """Set the title text."""
        self.title.setText(title)

    def setSearchQuery(self, query: str) -> None:
        """Synchronize the title-bar field with its attached track list."""
        self.search.setText(query)

    def setColor(
        self,
        r: int,
        g: int,
        b: int,
        text: tuple[int, int, int] | None = None,
        text_secondary: tuple[int, int, int] | None = None,
        contrast_ensured: bool = False,
    ):
        """Set the title bar color using a limited, contrast-aware palette."""
        paints = render_track_title_bar_paints(
            current_theme(),
            (r, g, b),
            text_rgb=text,
            text_secondary_rgb=text_secondary,
            contrast_ensured=contrast_ensured,
        )
        self._apply_paints(paints)

    def setFullscreenMode(self, fullscreen: bool):
        """Enable/disable fullscreen mode. Hides buttons and disables dragging."""
        self._fullscreen_mode = fullscreen
        self.button1.setVisible(not fullscreen)
        self.button2.setVisible(not fullscreen)
        self.unsetCursor()

    def resetColor(self):
        """Reset to the default limited title-bar palette."""
        self._apply_paints(
            render_track_title_bar_paints(
                current_theme(),
                current_theme().paint("playlist.regular").color.rgb,
            )
        )

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

    def _apply_paints(self, paints: TrackTitleBarPaints) -> None:
        self.setStyleSheet(_title_bar_css(paints))
        self._set_handle_color()
        self._refresh_button_icons(paints.icon_text.css)
        self._refresh_search_style(paints)

    def _refresh_search_style(self, paints: TrackTitleBarPaints) -> None:
        self.search.setStyleSheet(_title_bar_search_css(paints))
        icon = glyph_icon("search", 15, paints.icon_text.css)
        if icon is None:
            return
        if self._search_icon_action is None:
            self._search_icon_action = self.search.addAction(
                icon,
                QLineEdit.ActionPosition.LeadingPosition,
            )
        else:
            self._search_icon_action.setIcon(icon)

    def _refresh_button_icons(self, color: str) -> None:
        down_icon = glyph_icon("chevron-down", 18, color)
        if down_icon:
            self.button1.setIcon(down_icon)
            self.button1.setIconSize(self._icon_size)
            self.button1.setText("")
        else:
            self.button1.setText("▼")

        up_icon = glyph_icon("chevron-up", 18, color)
        if up_icon:
            self.button2.setIcon(up_icon)
            self.button2.setIconSize(self._icon_size)
            self.button2.setText("")
        else:
            self.button2.setText("▲")

    def _toggleMinimize(self):
        """Minimize the track list panel."""
        total = self._available_splitter_height()
        min_height = self.minimumHeight()
        # Set track panel to minimum (just title bar)
        self.splitter.setSizes([max(total - min_height, 0), min_height])
        self.enforceMinHeight()

    def _toggleMaximize(self):
        """Maximize the track list panel."""
        total = self._available_splitter_height()
        track_height = max(int(total * 0.8), self.minimumHeight() + 1)
        grid_height = max(total - track_height, 0)
        self.splitter.setSizes([grid_height, track_height])
        self.enforceMinHeight()

    def _available_splitter_height(self) -> int:
        """Return the real splitter height even during collapsed-size transitions."""

        sizes = self.splitter.sizes()
        reported_total = sum(sizes)
        widget_height = self.splitter.height()
        return max(reported_total, widget_height, self.minimumHeight())

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
