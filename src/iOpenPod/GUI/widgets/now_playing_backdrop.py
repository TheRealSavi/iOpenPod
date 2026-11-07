"""Visible-only artwork motion behind the Now Playing controls."""

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QHideEvent, QImage, QPainter, QPaintEvent, QShowEvent
from PySide6.QtWidgets import QStyle, QWidget

from iOpenPod.GUI.presentation.now_playing_background import (
    ArtworkBackgroundAnimation,
    now_playing_background,
)
from iOpenPod.GUI.presentation.theme.tokens import ThemeTokens


class NowPlayingBackdrop(QWidget):
    """Cache image preparation; animate only a 96-pixel raster at 30 fps."""

    def __init__(self, tokens: ThemeTokens, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("nowPlayingBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._tokens = tokens
        self._artwork = QImage()
        self._animation = ArtworkBackgroundAnimation(QColor(tokens.window))
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._observed_window: QWidget | None = None

    def set_artwork(
        self, image: QImage, tokens: ThemeTokens, *, animate: bool = True
    ) -> None:
        if image == self._artwork and tokens == self._tokens:
            if not animate:
                self._animation.settle()
                self._sync_timer()
                self.update()
            return
        # Theme text changes immediately, so its readability scrim must too.
        animate = animate and tokens == self._tokens and self._can_animate()
        self._artwork = image
        self._tokens = tokens
        self._animation.set_image(
            now_playing_background(image, tokens),
            QColor(tokens.window),
            animate=animate,
        )
        self._sync_timer()
        self.update()

    def _animations_enabled(self) -> bool:
        return bool(
            self.style().styleHint(QStyle.StyleHint.SH_Widget_Animate, None, self)
        )

    def _can_animate(self) -> bool:
        return (
            self.isVisible()
            and not self.window().isMinimized()
            and self._animations_enabled()
        )

    def _sync_timer(self) -> None:
        enabled = self._animations_enabled()
        if not enabled:
            self._animation.settle()
            self.update()
        running = self._can_animate() and self._animation.active
        if running and not self._timer.isActive():
            self._clock.start()
            self._timer.start()
        elif not running:
            self._timer.stop()
            self._clock.invalidate()

    def _tick(self) -> None:
        if not self._can_animate():
            self._sync_timer()
            return
        self._animation.advance(self._clock.restart() / 1000)
        self.update()
        if not self._animation.active:
            self._sync_timer()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        window = self.window()
        if window is not self._observed_window:
            if self._observed_window is not None:
                self._observed_window.removeEventFilter(self)
            self._observed_window = window
            window.installEventFilter(self)
        self._sync_timer()

    def hideEvent(self, event: QHideEvent) -> None:
        self._timer.stop()
        self._clock.invalidate()
        super().hideEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.StyleChange and hasattr(self, "_timer"):
            self._sync_timer()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._observed_window
            and event.type() == QEvent.Type.WindowStateChange
        ):
            self._sync_timer()
        return super().eventFilter(watched, event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self._animation.image)
