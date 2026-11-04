"""Smooth discrete wheel steps while retaining precise native pixel input."""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

_WHEEL_NOTCH = 120


class SmoothWheelScrolling(QObject):
    """Animate a bounded vertical wheel target without delaying trackpad input."""

    def __init__(self, view: QAbstractItemView) -> None:
        super().__init__(view)
        self._view = view
        self._viewport = view.viewport()
        self._scrollbar = view.verticalScrollBar()
        self._target = float(self._scrollbar.value())
        self._advancing = False
        self._animation = QVariantAnimation(self)
        self._animation.setObjectName("gridWheelScrollAnimation")
        self._animation.setDuration(LAYOUT.grid_scroll_animation_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._advance)
        self._scrollbar.valueChanged.connect(self._value_changed)
        self._scrollbar.rangeChanged.connect(self._cancel)
        self._scrollbar.sliderPressed.connect(self._cancel)
        view.installEventFilter(self)
        self._viewport.installEventFilter(self)
        self._scrollbar.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in {
            QEvent.Type.Hide,
            QEvent.Type.KeyPress,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Resize,
        }:
            self._cancel()
        elif isinstance(event, QWheelEvent) and (
            watched is self._viewport or watched is self._scrollbar
        ):
            return self._wheel(event)
        return False

    def _wheel(self, event: QWheelEvent) -> bool:
        if (
            self._view.verticalScrollMode()
            is not QAbstractItemView.ScrollMode.ScrollPerPixel
            or event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.AltModifier
            )
        ):
            self._cancel()
            return False

        pixels = event.pixelDelta()
        angle = event.angleDelta()
        if not pixels.isNull():
            # Trackpads already supply smooth, possibly momentum-driven motion.
            # Qt's deltas already include the Host's natural-scroll direction.
            self._cancel()
            if not pixels.y() or abs(pixels.x()) > abs(pixels.y()):
                return False
            before = self._scrollbar.value()
            self._scrollbar.setValue(before - pixels.y())
            if self._scrollbar.value() == before:
                return False
            event.accept()
            return True
        if not angle.y() or abs(angle.x()) > abs(angle.y()):
            return False

        lines = QApplication.wheelScrollLines()
        if lines <= 0:
            self._cancel()
            return False
        delta = -angle.y() / _WHEEL_NOTCH * lines * self._scrollbar.singleStep()
        current = self._scrollbar.value()
        if (
            self._animation.state() is QAbstractAnimation.State.Running
            and delta * (self._target - current) < 0
        ):
            # Reversing direction drops the outstanding travel immediately.
            self._target = float(current)
        # Bound queued travel so a burst cannot leave the grid coasting for pages.
        limit = max(self._scrollbar.singleStep(), self._viewport.height())
        target = max(
            self._scrollbar.minimum(),
            current - limit,
            min(self._scrollbar.maximum(), current + limit, self._target + delta),
        )
        self._animation.stop()
        self._target = target
        if target == current:
            return False
        if round(target) == current:
            # Retain fractional high-resolution wheel travel for the next event.
            event.accept()
            return True
        # Reconfiguring a stopped QVariantAnimation can emit interpolated values
        # at its old time. Only actual animation frames should move the viewport.
        blocked = self._animation.blockSignals(True)
        try:
            self._animation.setStartValue(float(current))
            self._animation.setEndValue(float(target))
            self._animation.setCurrentTime(0)
        finally:
            self._animation.blockSignals(blocked)
        self._animation.start()
        event.accept()
        return True

    def _advance(self, value: object) -> None:
        if not isinstance(value, (int, float)):
            return
        self._advancing = True
        try:
            self._scrollbar.setValue(round(value))
        finally:
            self._advancing = False

    def _value_changed(self, _value: int) -> None:
        if not self._advancing:
            self._cancel()

    def _cancel(self, *_args: object) -> None:
        self._animation.stop()
        self._target = float(self._scrollbar.value())


__all__ = ["SmoothWheelScrolling"]
