"""Shared, interruptible motion for the Qt presentation boundary.

Spatial motion uses a critically damped spring on Qt's animation clock. Fades
use a short timing curve. These are iOpenPod tunings, not Apple platform values.
"""

from math import exp

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSignalBlocker,
    QVariantAnimation,
)
from PySide6.QtWidgets import QStyle, QWidget

from iOpenPod.GUI.presentation.theme.tokens import MOTION as MOTION

type MotionValue = int | float | QPoint | QRect | QRectF


def animations_enabled(widget: QWidget, *, style: QStyle | None = None) -> bool:
    """Use the same Host widget-animation preference throughout the GUI."""
    style = widget.style() if style is None else style
    # Current Qt styles expose duration=0; retain compatibility with styles that
    # still override only the older boolean hint.
    return style.styleHint(
        QStyle.StyleHint.SH_Widget_Animation_Duration, None, widget
    ) > 0 and bool(style.styleHint(QStyle.StyleHint.SH_Widget_Animate, None, widget))


def fade_curve() -> QEasingCurve:
    """A quick response with a soft finish; opacity never overshoots."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.2, 0.0), QPointF(0.0, 1.0), QPointF(1.0, 1.0))
    return curve


def _components(value: object) -> tuple[float, ...]:
    if isinstance(value, (int, float)):
        return (float(value),)
    if isinstance(value, QPoint):
        return (float(value.x()), float(value.y()))
    if isinstance(value, (QRect, QRectF)):
        return (
            float(value.x()),
            float(value.y()),
            float(value.width()),
            float(value.height()),
        )
    raise TypeError(f"Unsupported motion value: {type(value).__name__}")


class _Spring:
    def __init__(self) -> None:
        self.initial_velocity: tuple[float, ...] = ()
        self.velocity: tuple[float, ...] = ()
        self.duration_ms = MOTION.control_ms

    def interpolate(self, start: object, end: object, progress: float) -> object:
        before, after = _components(start), _components(end)
        if len(before) != len(after):
            raise TypeError("Motion endpoints must have the same dimensions")
        velocity = self.initial_velocity or (0.0,) * len(before)
        # Ten time constants leave <0.05% travel at completion. Evaluate the
        # closed form, so a dropped frame doesn't destabilize the simulation.
        omega = 10.0 / (self.duration_ms / 1000.0)
        seconds = progress * self.duration_ms / 1000.0
        decay = exp(-omega * seconds)
        values: list[float] = []
        speeds: list[float] = []
        for source, target, speed in zip(before, after, velocity, strict=True):
            displacement = source - target
            coefficient = speed + omega * displacement
            values.append(target + (displacement + coefficient * seconds) * decay)
            speeds.append((speed - omega * coefficient * seconds) * decay)
        self.velocity = tuple(speeds) if progress < 1.0 else (0.0,) * len(before)
        if progress <= 0.0:
            return start
        if progress >= 1.0:
            return end
        if isinstance(start, QRect):
            return QRect(*(round(value) for value in values))
        if isinstance(start, QRectF):
            return QRectF(*values)
        if isinstance(start, QPoint):
            return QPoint(*(round(value) for value in values))
        return round(values[0]) if isinstance(start, int) else values[0]


def _retarget(
    animation: QVariantAnimation,
    spring: _Spring,
    start: MotionValue,
    target: MotionValue,
    duration_ms: int,
) -> None:
    if duration_ms <= 0:
        raise ValueError("Spring settling time must be positive")
    # Only a live trajectory carries momentum. Explicit cancellation, resizing
    # and context replacement must not resurrect velocity on the next gesture.
    velocity = (
        spring.velocity
        if animation.state() != QAbstractAnimation.State.Stopped
        and animation.currentValue() == start
        else ()
    )
    animation.stop()
    spring.initial_velocity = velocity
    spring.duration_ms = duration_ms
    # Endpoint changes at an old time can emit stale intermediate frames.
    with QSignalBlocker(animation):
        animation.setDuration(duration_ms)
        animation.setStartValue(start)
        animation.setEndValue(target)
        animation.setCurrentTime(0)
    animation.start()


class SpringAnimation(QVariantAnimation):
    """Animate a typed value; retarget from its visible position and velocity."""

    def __init__(self, parent: QObject) -> None:
        self._spring = _Spring()
        super().__init__(parent)

    def retarget(
        self, start: MotionValue, target: MotionValue, duration_ms: int
    ) -> None:
        _retarget(self, self._spring, start, target, duration_ms)

    def interpolated(self, start: object, end: object, progress: float) -> object:
        return self._spring.interpolate(start, end, progress)


class SpringPropertyAnimation(QPropertyAnimation):
    """The same spring with Qt's native property binding and object lifetime."""

    def __init__(self, target: QObject, property_name: bytes, parent: QObject) -> None:
        self._spring = _Spring()
        super().__init__(target, property_name, parent)

    def retarget(
        self, start: MotionValue, target: MotionValue, duration_ms: int
    ) -> None:
        _retarget(self, self._spring, start, target, duration_ms)

    def interpolated(self, start: object, end: object, progress: float) -> object:
        return self._spring.interpolate(start, end, progress)
