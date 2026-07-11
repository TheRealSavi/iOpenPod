"""Shared podcast loading, empty, and network-error states."""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..glyphs import glyph_pixmap
from ..styles import (
    FONT_FAMILY,
    MONO_FONT_FAMILY,
    Colors,
    Metrics,
    accent_btn_css,
    make_label,
    progress_bar_css,
)


class PodcastStatePanel(QFrame):
    """Centered state visual for podcast loading, empty, and error screens."""

    action_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, *, compact: bool = False):
        super().__init__(parent)
        self._compact = compact
        self._message_text = ""
        self.setObjectName("podcastStatePanel")
        self.setStyleSheet("QFrame#podcastStatePanel { background: transparent; border: none; }")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        margin = 20 if compact else 36
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(8)
        layout.addStretch()

        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._icon)

        self._title = make_label(
            "",
            size=Metrics.FONT_TITLE if compact else Metrics.FONT_PAGE_TITLE,
            weight=QFont.Weight.DemiBold,
        )
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._message = make_label(
            "",
            size=Metrics.FONT_SM if compact else Metrics.FONT_LG,
            style=f"color: {Colors.TEXT_SECONDARY}; background: transparent;",
            wrap=True,
        )
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setMaximumWidth(520)
        self._message.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(self._message, alignment=Qt.AlignmentFlag.AlignCenter)

        self._code = QLabel("")
        self._code.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
        self._code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._code.setStyleSheet(f"""
            QLabel {{
                color: {Colors.TEXT_SECONDARY};
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                padding: 4px 9px;
            }}
        """)
        self._code.hide()
        layout.addWidget(self._code, alignment=Qt.AlignmentFlag.AlignCenter)

        self._progress = QProgressBar()
        self._progress.setFixedHeight(4)
        self._progress.setFixedWidth(220 if compact else 260)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 0)
        self._progress.setStyleSheet(
            progress_bar_css(height=4, radius=2, bg=Colors.SURFACE)
        )
        self._progress.hide()
        layout.addWidget(self._progress, alignment=Qt.AlignmentFlag.AlignCenter)

        self._action = QPushButton("")
        self._action.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        self._action.setStyleSheet(accent_btn_css())
        self._action.setFixedHeight(34)
        self._action.clicked.connect(self.action_clicked.emit)
        self._action.hide()
        layout.addWidget(self._action, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()

    def show_loading(self, title: str, message: str) -> None:
        self._set_icon("broadcast", Colors.ACCENT)
        self._title.setText(title)
        self._set_message(message)
        self._code.hide()
        self._progress.show()
        self._action.hide()

    def show_empty(self, title: str, message: str, *, glyph: str = "broadcast") -> None:
        self._set_icon(glyph, Colors.TEXT_TERTIARY)
        self._title.setText(title)
        self._set_message(message)
        self._code.hide()
        self._progress.hide()
        self._action.hide()

    def show_error(
        self,
        title: str,
        message: str,
        *,
        code: str = "",
        action_text: str = "Try Again",
    ) -> None:
        self._set_icon("wifi-no-connection", Colors.WARNING)
        self._title.setText(title)
        self._set_message(message)
        self._code.setText(code)
        self._code.setVisible(bool(code))
        self._progress.hide()
        self._action.setText(action_text)
        self._action.setVisible(bool(action_text))

    def _set_message(self, message: str) -> None:
        self._message_text = message
        self._message.setText(message)
        self._message.setVisible(bool(message))
        self._update_message_height()

    def _update_message_height(self) -> None:
        if not self._message_text:
            self._message.setMinimumSize(0, 0)
            self._message.setMaximumHeight(0)
            return
        horizontal_margin = 40 if self._compact else 72
        width = max(160, min(520, self.width() - horizontal_margin))
        metrics = QFontMetrics(self._message.font())
        flags = Qt.TextFlag.TextWordWrap.value | Qt.AlignmentFlag.AlignCenter.value
        bounds = metrics.boundingRect(
            QRect(0, 0, width, 2000),
            flags,
            self._message_text,
        )
        height = bounds.height() + metrics.lineSpacing()
        self._message.setFixedSize(width, height)
        self._message.updateGeometry()

    def _set_icon(self, glyph: str, color: str) -> None:
        size = Metrics.FONT_ICON_LG if self._compact else Metrics.FONT_ICON_XL
        px = glyph_pixmap(glyph, size, color)
        if px:
            self._icon.setPixmap(px)
            self._icon.setText("")
            return
        self._icon.clear()
        self._icon.setText("!")
        self._icon.setFont(QFont(FONT_FAMILY, size))
        self._icon.setStyleSheet(f"color: {color}; background: transparent; border: none;")

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._update_message_height()
