from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget

from ..styles import FONT_FAMILY, Colors, Metrics, btn_css


def chrome_action_btn_css() -> str:
    """Shared style for action buttons hosted in BrowserHeroHeader."""
    return btn_css(
        bg=Colors.SURFACE_RAISED,
        bg_hover=Colors.SURFACE_HOVER,
        bg_press=Colors.SURFACE_ACTIVE,
        fg=Colors.TEXT_PRIMARY,
        border=f"1px solid {Colors.BORDER_SUBTLE}",
        padding="6px 10px",
    )


class BrowserHeroHeader(QFrame):
    """Reusable browser header that acts as a controls strip."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("browserHeroHeader")
        self.setFixedHeight(48)
        self.setStyleSheet(f"""
            QFrame#browserHeroHeader {{
                background: {Colors.SURFACE};
                border-top: 1px solid {Colors.BORDER_SUBTLE};
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
                border-left: none;
                border-right: none;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.actions_layout = QHBoxLayout()
        self.actions_layout.setContentsMargins(12, 0, 12, 0)
        self.actions_layout.setSpacing(8)
        layout.addLayout(self.actions_layout)


class BrowserPane(QFrame):
    """Reusable titled pane used for sidebars and supporting content panels."""

    def __init__(
        self,
        title: str,
        *,
        min_width: int = 0,
        body_margins: tuple[int, int, int, int] = (0, 0, 0, 0),
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("browserPane")
        self.setStyleSheet(f"""
            QFrame#browserPane {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 0px;
            }}
        """)
        if min_width:
            self.setMinimumWidth(min_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_label = QLabel(title, self)
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        self.title_label.setStyleSheet(f"""
            color:{Colors.TEXT_PRIMARY};
            background:transparent;
            border:none;
            padding:8px 12px 4px 12px;
        """)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        if title:
            self.title_label.setFixedHeight(36)
            layout.addWidget(self.title_label)
        else:
            self.title_label.hide()

        self.body = QWidget(self)
        self.body.setObjectName("browserPaneBody")
        self.body.setAutoFillBackground(False)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(*body_margins)
        self.body_layout.setSpacing(0)
        layout.addWidget(self.body, 1)

    def addWidget(self, widget, stretch: int = 0):
        self.body_layout.addWidget(widget, stretch)


def style_browser_splitter(splitter: QSplitter) -> None:
    if splitter.handleWidth() != 0:
        splitter.setHandleWidth(1)
    splitter.setStyleSheet(f"""
        QSplitter::handle {{
            background: {Colors.BORDER_SUBTLE};
        }}
        QSplitter::handle:hover {{
            background: {Colors.ACCENT};
        }}
        QSplitter::handle:pressed {{
            background: {Colors.ACCENT_LIGHT};
        }}
    """)
