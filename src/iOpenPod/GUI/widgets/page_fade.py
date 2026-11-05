"""Crossfade a page snapshot over immediately committed navigation."""

from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRect,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QWidget

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class PageFade(QWidget):
    """Keep navigation live while fading one viewport-sized outgoing frame."""

    def __init__(self, page: QWidget) -> None:
        super().__init__(page)
        self._page = page
        self._snapshot = QPixmap()
        self._opacity = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()
        self._animation = QVariantAnimation(self)
        self._animation.setObjectName("pageFadeAnimation")
        self._animation.setDuration(LAYOUT.page_fade_animation_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self.cancel)
        page.installEventFilter(self)

    def transition(self, change_page: Callable[[], None]) -> None:
        # Include an unfinished fade in the next snapshot to avoid a flash when
        # the user opens or goes Back again before the animation completes.
        snapshot = QPixmap()
        if self._page.isVisible():
            # A child page's grab has transparent gaps where its ancestors paint
            # the background. Capture the composed window region so new controls
            # cannot appear through those gaps at full strength on the first frame.
            window = self._page.window()
            region = QRect(self._page.mapTo(window, QPoint()), self._page.size())
            snapshot = window.grab(region)
        self.cancel()
        change_page()
        layout = self._page.layout()
        if layout is not None:
            layout.activate()
        if snapshot.isNull() or not self._page.isVisible():
            return
        self._snapshot = snapshot
        self._opacity = 1.0
        self.setGeometry(self._page.rect())
        self.show()
        self.raise_()
        self._animation.start()

    def cancel(self) -> None:
        self._animation.stop()
        self.hide()
        self._snapshot = QPixmap()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._page and event.type() in {
            QEvent.Type.Hide,
            QEvent.Type.Resize,
            QEvent.Type.StyleChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.FontChange,
            QEvent.Type.LanguageChange,
        }:
            self.cancel()
        return False

    def _advance(self, value: object) -> None:
        if isinstance(value, (int, float)):
            self._opacity = float(value)
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(0, 0, self._snapshot)
        painter.end()
