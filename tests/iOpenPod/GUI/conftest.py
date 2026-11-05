"""Qt object-lifecycle and input-state isolation for GUI tests."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget


def _reset_input(application: QApplication) -> None:
    if mouse_grabber := QWidget.mouseGrabber():
        mouse_grabber.releaseMouse()
    if keyboard_grabber := QWidget.keyboardGrabber():
        keyboard_grabber.releaseKeyboard()
    surface = QWidget()
    for button in Qt.MouseButton:
        if (
            button.value & (button.value - 1) == 0
            and application.mouseButtons() & button
        ):
            QTest.mouseRelease(surface, button, delay=0)
    for key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
        QTest.keyRelease(surface, key, delay=0)
    while application.overrideCursor() is not None:
        application.restoreOverrideCursor()
    # A repeated QTest.mouseMove at the previous global position emits no move.
    # Park outside the virtual desktop so the next widget gets a fresh entry.
    desktop = QRect()
    for screen in application.screens():
        desktop = desktop.united(screen.geometry())
    QCursor.setPos(desktop.topLeft() - QPoint(1, 1))
    surface.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


@pytest.fixture(autouse=True)
def _release_top_level_widgets() -> Iterator[None]:
    """Do not carry widget trees or synthetic input into another GUI test."""

    application = QApplication.instance()
    if isinstance(application, QApplication):
        _reset_input(application)
    yield
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        return
    for widget in application.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    _reset_input(application)
