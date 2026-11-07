"""One application-wide entry point for wheel and middle-button scrolling."""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QHeaderView,
    QWidget,
)

from iOpenPod.GUI.presentation.middle_mouse_scrolling import MiddleMouseScrollFilter
from iOpenPod.GUI.presentation.smooth_wheel_scrolling import SmoothWheelScrolling

_OBJECT_NAME = "applicationScrollFilter"


class ApplicationScrollFilter(MiddleMouseScrollFilter):
    """Give existing and newly opened scroll areas the same input policy."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() is QEvent.Type.Show and isinstance(
            watched, QAbstractScrollArea
        ):
            if not isinstance(watched, QHeaderView):
                _wheel_scrolling(watched)
        elif isinstance(event, QWheelEvent) or (
            isinstance(event, QMouseEvent)
            and event.type() is QEvent.Type.MouseButtonPress
        ):
            area = _scroll_area(watched)
            if area is not None:
                wheel = _wheel_scrolling(area)
                if isinstance(event, QWheelEvent):
                    self._finish_drag()
                    return wheel.wheel(event)
                if event.type() is QEvent.Type.MouseButtonPress:
                    # The global middle-button handler consumes this press before
                    # the area's local cancellation filter can see it.
                    wheel.cancel()
        return super().eventFilter(watched, event)


def install_scrolling(application: QApplication) -> ApplicationScrollFilter:
    """Install the shared scrolling policy once, including already-open areas."""

    existing = application.findChild(ApplicationScrollFilter, _OBJECT_NAME)
    if existing is not None:
        return existing
    scroll_filter = ApplicationScrollFilter(application)
    scroll_filter.setObjectName(_OBJECT_NAME)
    application.installEventFilter(scroll_filter)
    for widget in application.allWidgets():
        if isinstance(widget, QAbstractScrollArea) and not isinstance(
            widget, QHeaderView
        ):
            _wheel_scrolling(widget)
    return scroll_filter


def _wheel_scrolling(area: QAbstractScrollArea) -> SmoothWheelScrolling:
    existing = area.findChild(
        SmoothWheelScrolling, options=Qt.FindChildOption.FindDirectChildrenOnly
    )
    return existing if existing is not None else SmoothWheelScrolling(area)


def _scroll_area(watched: QObject) -> QAbstractScrollArea | None:
    if not isinstance(watched, QWidget):
        return None
    parent = watched.parentWidget()
    # A scrollbar lives inside Qt's scrollbar container, one level below its area.
    if parent is not None and not isinstance(parent, QAbstractScrollArea):
        parent = parent.parentWidget()
    if (
        isinstance(parent, QAbstractScrollArea)
        and not isinstance(parent, QHeaderView)
        and watched in {parent.viewport(), parent.verticalScrollBar()}
    ):
        return parent
    return None


__all__ = ["ApplicationScrollFilter", "install_scrolling"]
