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
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QPlainTextEdit,
    QTableView,
)
from shiboken6 import isValid

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

_WHEEL_NOTCH = 120


class SmoothWheelScrolling(QObject):
    """Animate a bounded vertical target, with whole-row wheel steps in tables."""

    def __init__(self, view: QAbstractScrollArea) -> None:
        super().__init__(view)
        if isinstance(view, QAbstractItemView):
            view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._viewport = view.viewport()
        self._scrollbar = view.verticalScrollBar()
        self._target = float(self._scrollbar.value())
        self._pending_angle = 0
        self._advancing = False
        self._animation = QVariantAnimation(self)
        self._animation.setObjectName("wheelScrollAnimation")
        self._animation.setDuration(LAYOUT.scroll_animation_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._advance)
        self._watch_scrollbar()
        application = QApplication.instance()
        if isinstance(application, QApplication):
            application.applicationStateChanged.connect(self.cancel)
        if isinstance(view, QTableView):
            view.verticalHeader().geometriesChanged.connect(self.cancel)
        view.installEventFilter(self)
        self._viewport.installEventFilter(self)

    def _watch_scrollbar(self) -> None:
        self._scrollbar.valueChanged.connect(self._value_changed)
        self._scrollbar.rangeChanged.connect(self.cancel)
        self._scrollbar.sliderPressed.connect(self.cancel)
        self._scrollbar.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in {
            QEvent.Type.Hide,
            QEvent.Type.KeyPress,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Resize,
        }:
            self.cancel()
        return False

    def wheel(self, view: QAbstractScrollArea, event: QWheelEvent) -> bool:
        """Handle input from the viewport or scrollbar without retaining their area."""

        viewport = view.viewport()
        if viewport is not self._viewport:
            self.cancel()
            if isValid(self._viewport):
                self._viewport.removeEventFilter(self)
            self._viewport = viewport
            self._viewport.installEventFilter(self)

        scrollbar = view.verticalScrollBar()
        if scrollbar is not self._scrollbar:
            # Qt can replace and delete the scrollbar while the area stays alive.
            self._scrollbar = scrollbar
            self.cancel()
            self._watch_scrollbar()

        if not self._scrollbar.isEnabled() or event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.AltModifier
        ):
            self.cancel()
            return False

        pixels = event.pixelDelta()
        angle = event.angleDelta()
        if not pixels.isNull():
            # Trackpads already supply smooth, possibly momentum-driven motion.
            # Qt's deltas already include the Host's natural-scroll direction.
            self.cancel()
            if isinstance(view, QPlainTextEdit):
                # This native control scrolls in text lines, not pixels. Let Qt
                # translate precise trackpad input into its document coordinates.
                return False
            if not pixels.y() or abs(pixels.x()) > abs(pixels.y()):
                return False
            before = self._scrollbar.value()
            self._scrollbar.setValue(before - pixels.y())
            if self._scrollbar.value() == before:
                return False
            event.accept()
            return True
        if not angle.y() or abs(angle.x()) > abs(angle.y()):
            self.cancel()
            return False

        lines = QApplication.wheelScrollLines()
        if lines <= 0:
            self.cancel()
            return False
        line_step = self._scrollbar.singleStep()
        if isinstance(view, QAbstractItemView):
            # Qt derives pixel-view steps from item height. Tall Podcast and
            # Queue rows must not turn each Host wheel line into a whole item.
            line_step = min(line_step, LAYOUT.scroll_line_height)
        delta = -angle.y() / _WHEEL_NOTCH * lines * line_step
        current = self._scrollbar.value()
        if (
            self._animation.state() is QAbstractAnimation.State.Running
            and delta * (self._target - current) < 0
        ):
            # Reversing direction drops the outstanding travel immediately.
            self._animation.stop()
            self._target = float(current)
        # Bound queued travel so a burst cannot leave an area coasting for pages.
        limit = max(self._scrollbar.singleStep(), self._scrollbar.pageStep())
        target = max(
            self._scrollbar.minimum(),
            current - limit,
            min(self._scrollbar.maximum(), current + limit, self._target + delta),
        )
        if isinstance(view, QTableView):
            if self._pending_angle * angle.y() > 0:
                self._pending_angle = 0
            self._pending_angle -= angle.y()
            steps = int(self._pending_angle / _WHEEL_NOTCH)
            self._pending_angle -= steps * _WHEEL_NOTCH
            if not steps:
                can_move = (
                    current < self._scrollbar.maximum()
                    if angle.y() < 0
                    else current > self._scrollbar.minimum()
                )
                if can_move:
                    event.accept()
                else:
                    self.cancel()
                return can_move
            target = self._table_target(view, steps)
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
        if not isValid(self._scrollbar) or not isValid(self._viewport):
            self.cancel()
            return
        self._advancing = True
        try:
            self._scrollbar.setValue(round(value))
        finally:
            self._advancing = False

    def _value_changed(self, _value: int) -> None:
        if not self._advancing:
            self.cancel()

    def cancel(self, *_args: object) -> None:
        """Yield immediately to another input, layout change, or navigation."""

        # During parent destruction Qt can hide the viewport after invalidating
        # its scrollbar wrapper, before emitting that scrollbar's destroyed signal.
        if not isValid(self._animation):
            return
        self._animation.stop()
        if isValid(self._scrollbar):
            self._target = float(self._scrollbar.value())
        self._pending_angle = 0

    def _table_target(self, table: QTableView, steps: int) -> float:
        """Walk visible row boundaries without scanning the table's model."""

        header = table.verticalHeader()
        current = self._scrollbar.value()
        target = round(self._target)
        direction = 1 if steps > 0 else -1
        row = header.logicalIndexAt(target - current)
        if row < 0:
            return float(current)
        limit = max(table.viewport().height(), header.sectionSize(row))
        for _ in range(min(abs(steps), header.count())):
            top = header.sectionPosition(row)
            if direction < 0 and target > top:
                candidate = top
            else:
                visual = header.visualIndex(row) + direction
                while 0 <= visual < header.count():
                    row = header.logicalIndex(visual)
                    if not header.isSectionHidden(row):
                        break
                    visual += direction
                else:
                    candidate = (
                        self._scrollbar.maximum()
                        if direction > 0
                        else self._scrollbar.minimum()
                    )
                    target = candidate
                    break
                candidate = header.sectionPosition(row)
            candidate = max(
                self._scrollbar.minimum(), min(self._scrollbar.maximum(), candidate)
            )
            if abs(candidate - current) > limit:
                break
            target = candidate
        return float(target)


__all__ = ["SmoothWheelScrolling"]
