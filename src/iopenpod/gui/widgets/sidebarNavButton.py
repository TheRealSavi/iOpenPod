"""Shared eliding navigation button used by browser sidebars."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QPushButton, QSizePolicy

from ..styles import FONT_FAMILY, Metrics


class SidebarNavButton(QPushButton):
    """A fixed-height sidebar button that elides its label to the right."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.setToolTip(text)
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

    def setText(self, text: str | None) -> None:
        normalized = text or ""
        self._full_text = normalized
        self.setToolTip(normalized)
        self._refresh_elided_text()

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        self._refresh_elided_text()

    def _refresh_elided_text(self) -> None:
        icon_width = self.iconSize().width() + 8 if not self.icon().isNull() else 0
        available = max(1, self.width() - 24 - icon_width)
        elided = QFontMetrics(self.font()).elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            available,
        )
        QPushButton.setText(self, elided)
