"""Canonical stateful navigation row used by button-based sidebars."""

from PyQt6.QtCore import QEvent, QSize, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QIcon
from PyQt6.QtWidgets import QPushButton, QSizePolicy

from ..glyphs import glyph_icon
from ..styles import (
    FONT_FAMILY,
    Design,
    Metrics,
    sidebar_nav_css,
    sidebar_nav_state,
)


class SidebarNavButton(QPushButton):
    """Own sidebar row geometry, selection styling, glyph color, and elision."""

    def __init__(
        self,
        text: str,
        parent=None,
        *,
        icon_name: str | None = None,
        icon_size: int = Design.SIDEBAR_ICON_SIZE,
    ) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self._navigation_icon_name = icon_name
        self._navigation_icon_size = icon_size
        self._selected = False
        self._dimmed = False
        self.setFont(QFont(FONT_FAMILY, Metrics.FONT_SIDEBAR))
        self.setToolTip(text)
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self._apply_navigation_appearance()

    def setSelected(self, selected: bool) -> None:
        selected = bool(selected)
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_navigation_appearance()

    def isSelected(self) -> bool:
        return self._selected

    def setNavigationIcon(self, icon_name: str | None, size: int | None = None) -> None:
        self._navigation_icon_name = icon_name
        if size is not None:
            self._navigation_icon_size = int(size)
        self._apply_navigation_appearance()

    def setDimmed(self, dimmed: bool) -> None:
        dimmed = bool(dimmed)
        if self._dimmed == dimmed:
            return
        self._dimmed = dimmed
        self._apply_navigation_appearance()

    def setText(self, text: str | None) -> None:
        normalized = text or ""
        self._full_text = normalized
        self.setToolTip(normalized)
        self._refresh_elided_text()

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        self._refresh_elided_text()

    def changeEvent(self, e: QEvent | None) -> None:
        super().changeEvent(e)
        if e is not None and e.type() == QEvent.Type.EnabledChange:
            self._apply_navigation_appearance()

    def _apply_navigation_appearance(self) -> None:
        enabled = self.isEnabled()
        self.setStyleSheet(sidebar_nav_css(
            selected=self._selected,
            enabled=enabled,
            dimmed=self._dimmed,
        ))
        icon_name = self._navigation_icon_name
        if icon_name:
            state = sidebar_nav_state(
                self._selected,
                enabled=enabled,
                dimmed=self._dimmed,
            )
            icon = glyph_icon(icon_name, self._navigation_icon_size, state.icon)
            if icon is not None:
                self.setIcon(icon)
                self.setIconSize(QSize(
                    self._navigation_icon_size,
                    self._navigation_icon_size,
                ))
        elif not self.icon().isNull():
            self.setIcon(QIcon())
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
