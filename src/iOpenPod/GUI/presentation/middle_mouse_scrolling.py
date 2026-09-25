"""Application-wide middle-button autoscrolling for Qt scroll areas."""

from math import copysign

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QScrollBar,
    QWidget,
)

_OBJECT_NAME = "middleMouseScrollFilter"
_TICK_INTERVAL_MS = 16
_MAXIMUM_TICK_MS = 100
_VELOCITY_EXPONENT = 2.2
_VELOCITY_MULTIPLIER = 0.008
_MINIMUM_VELOCITY = 24.0


class MiddleMouseScrollFilter(QObject):
    """Autoscroll continuously according to distance from a fixed origin."""

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        self.setObjectName(_OBJECT_NAME)
        self._viewport: QWidget | None = None
        self._scroll_area: QAbstractScrollArea | None = None
        self._origin = QPoint()
        self._velocity = QPointF()
        self._horizontal_position = 0.0
        self._vertical_position = 0.0
        self._previous_cursor = QCursor()
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_INTERVAL_MS)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._advance_scroll)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        event_type = event.type()
        if self._viewport is not None and (
            event_type is QEvent.Type.ApplicationDeactivate
            or (
                watched is self._viewport
                and event_type in {QEvent.Type.Hide, QEvent.Type.UngrabMouse}
            )
        ):
            self._finish_drag()
            return False

        if not isinstance(event, QMouseEvent):
            return False

        if self._viewport is None:
            if (
                event_type is QEvent.Type.MouseButtonPress
                and event.button() is Qt.MouseButton.MiddleButton
            ):
                return self._start_drag(watched, event)
            return False

        if watched is not self._viewport:
            return False

        if event_type is QEvent.Type.MouseMove:
            if not event.buttons() & Qt.MouseButton.MiddleButton:
                self._finish_drag()
                return False
            self._update_velocity(event.globalPosition().toPoint())
            event.accept()
            return True

        if (
            event_type is QEvent.Type.MouseButtonRelease
            and event.button() is Qt.MouseButton.MiddleButton
        ):
            self._finish_drag()
            event.accept()
            return True

        return False

    def _start_drag(self, watched: QObject, event: QMouseEvent) -> bool:
        if not isinstance(watched, QWidget):
            return False
        parent = watched.parentWidget()
        if (
            not isinstance(parent, QAbstractScrollArea)
            or parent.viewport() is not watched
        ):
            return False

        horizontal = parent.horizontalScrollBar()
        vertical = parent.verticalScrollBar()
        if not (_can_scroll(horizontal) or _can_scroll(vertical)):
            return False

        self._viewport = watched
        self._scroll_area = parent
        self._origin = event.globalPosition().toPoint()
        self._velocity = QPointF()
        self._horizontal_position = float(horizontal.value())
        self._vertical_position = float(vertical.value())
        self._previous_cursor = watched.cursor()
        watched.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._elapsed.start()
        self._timer.start()
        event.accept()
        return True

    def _update_velocity(self, position: QPoint) -> None:
        delta = position - self._origin
        self._velocity = QPointF(
            _velocity_for_distance(delta.x()),
            _velocity_for_distance(delta.y()),
        )

    def _advance_scroll(self) -> None:
        area = self._scroll_area
        if area is None:
            return
        elapsed_ms = min(self._elapsed.restart(), _MAXIMUM_TICK_MS)
        if elapsed_ms <= 0:
            return
        horizontal = area.horizontalScrollBar()
        vertical = area.verticalScrollBar()
        self._horizontal_position += _scroll_delta(
            area,
            horizontal,
            self._velocity.x() * elapsed_ms / 1_000,
            Qt.Orientation.Horizontal,
        )
        self._vertical_position += _scroll_delta(
            area,
            vertical,
            self._velocity.y() * elapsed_ms / 1_000,
            Qt.Orientation.Vertical,
        )
        horizontal.setValue(round(self._horizontal_position))
        vertical.setValue(round(self._vertical_position))
        if horizontal.value() in {horizontal.minimum(), horizontal.maximum()}:
            self._horizontal_position = float(horizontal.value())
        if vertical.value() in {vertical.minimum(), vertical.maximum()}:
            self._vertical_position = float(vertical.value())

    def _finish_drag(self) -> None:
        self._timer.stop()
        viewport = self._viewport
        if viewport is not None:
            viewport.setCursor(self._previous_cursor)
        self._viewport = None
        self._scroll_area = None
        self._velocity = QPointF()


def install_middle_mouse_scrolling(
    application: QApplication,
) -> MiddleMouseScrollFilter:
    """Install the process-wide filter once and return it."""

    existing = application.findChild(MiddleMouseScrollFilter, _OBJECT_NAME)
    if existing is not None:
        return existing
    scroll_filter = MiddleMouseScrollFilter(application)
    application.installEventFilter(scroll_filter)
    return scroll_filter


def _can_scroll(scrollbar: QScrollBar) -> bool:
    return scrollbar.isEnabled() and scrollbar.minimum() < scrollbar.maximum()


def _velocity_for_distance(distance: int) -> float:
    if distance == 0:
        return 0.0
    speed = _MINIMUM_VELOCITY + abs(distance) ** _VELOCITY_EXPONENT * (
        _VELOCITY_MULTIPLIER
    )
    return copysign(speed, distance)


def _scroll_delta(
    area: QAbstractScrollArea,
    scrollbar: QScrollBar,
    pixel_delta: float,
    orientation: Qt.Orientation,
) -> float:
    if not isinstance(area, QAbstractItemView):
        return pixel_delta
    mode = (
        area.horizontalScrollMode()
        if orientation is Qt.Orientation.Horizontal
        else area.verticalScrollMode()
    )
    if mode is QAbstractItemView.ScrollMode.ScrollPerPixel:
        return pixel_delta
    viewport_extent = (
        area.viewport().width()
        if orientation is Qt.Orientation.Horizontal
        else area.viewport().height()
    )
    return pixel_delta * max(1, scrollbar.pageStep()) / max(1, viewport_extent)


__all__ = ["MiddleMouseScrollFilter", "install_middle_mouse_scrolling"]
