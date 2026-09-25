"""Reusable debounced search input for large-library views."""

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QLineEdit, QSizePolicy, QWidget

from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

_SEARCH_DEBOUNCE_MS = 180


class SearchField(QLineEdit):
    """A palette-aware search field with one reusable debounce contract."""

    queryChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(180)
        self.setMaximumWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._search_icon = glyph_icon(
            "search",
            LAYOUT.icon_size,
            self.palette().color(QPalette.ColorRole.PlaceholderText),
            self.devicePixelRatioF(),
        )
        self._query_timer = QTimer(self)
        self._query_timer.setSingleShot(True)
        self._query_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self.textChanged.connect(self._queue_query)
        self._query_timer.timeout.connect(self._emit_query)
        self._update_text_margins()
        self._refresh_cursor()
        self._refresh_icon()

    def set_query(self, query: str) -> None:
        """Synchronize displayed text without starting another search."""

        if query == self.text():
            return
        blocker = QSignalBlocker(self)
        self.setText(query)
        del blocker

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in {
            QEvent.Type.LayoutDirectionChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        }:
            self._update_text_margins()
            self._refresh_icon()
        if event.type() == QEvent.Type.EnabledChange:
            self._refresh_cursor()
        super().changeEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        pixmap = self._search_icon.pixmap(QSize(LAYOUT.icon_size, LAYOUT.icon_size))
        x = LAYOUT.space_xs
        if self.layoutDirection() is Qt.LayoutDirection.RightToLeft:
            x = self.width() - LAYOUT.space_xs - LAYOUT.icon_size
        y = (self.height() - LAYOUT.icon_size) // 2
        painter = QPainter(self)
        painter.drawPixmap(x, y, pixmap)
        painter.end()

    def _queue_query(self, _text: str) -> None:
        self._query_timer.start()

    def _emit_query(self) -> None:
        self.queryChanged.emit(self.text())

    def _refresh_cursor(self) -> None:
        cursor = (
            Qt.CursorShape.IBeamCursor
            if self.isEnabled()
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)

    def _refresh_icon(self) -> None:
        self._search_icon = glyph_icon(
            "search",
            LAYOUT.icon_size,
            self.palette().color(QPalette.ColorRole.PlaceholderText),
            self.devicePixelRatioF(),
        )
        self.update()

    def _update_text_margins(self) -> None:
        reserved = LAYOUT.icon_size + LAYOUT.space_sm
        if self.layoutDirection() is Qt.LayoutDirection.RightToLeft:
            self.setTextMargins(0, 0, reserved, 0)
        else:
            self.setTextMargins(reserved, 0, 0, 0)
