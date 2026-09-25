"""Tests for application-wide middle-button drag scrolling."""

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QTableView, QWidget

from iOpenPod.GUI.presentation.middle_mouse_scrolling import (
    install_middle_mouse_scrolling,
)


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


def test_middle_drag_scrolls_continuously_away_from_its_origin() -> None:
    install_middle_mouse_scrolling(APPLICATION)
    area = QScrollArea()
    content = QWidget()
    content.resize(900, 900)
    area.setWidget(content)
    area.resize(220, 180)
    area.show()
    APPLICATION.processEvents()
    viewport = area.viewport()
    horizontal = area.horizontalScrollBar()
    vertical = area.verticalScrollBar()
    horizontal.setValue(100)
    vertical.setValue(100)
    viewport.setCursor(Qt.CursorShape.PointingHandCursor)

    try:
        _send_mouse(
            viewport,
            QEvent.Type.MouseButtonPress,
            QPoint(30, 30),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
        )
        assert viewport.cursor().shape() is Qt.CursorShape.ClosedHandCursor

        _send_mouse(
            viewport,
            QEvent.Type.MouseMove,
            QPoint(31, 31),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.MiddleButton,
        )
        QTest.qWait(100)
        assert horizontal.value() > 100
        assert vertical.value() > 100

        moved_down = vertical.value()
        _send_mouse(
            viewport,
            QEvent.Type.MouseMove,
            QPoint(0, 0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.MiddleButton,
        )
        QTest.qWait(160)
        assert horizontal.value() < 100
        assert vertical.value() < moved_down

        _send_mouse(
            viewport,
            QEvent.Type.MouseButtonRelease,
            QPoint(0, 0),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.NoButton,
        )
        assert viewport.cursor().shape() is Qt.CursorShape.PointingHandCursor
    finally:
        area.close()


def test_greater_distance_from_origin_increases_scroll_velocity() -> None:
    install_middle_mouse_scrolling(APPLICATION)
    area = QScrollArea()
    content = QWidget()
    content.resize(200, 2_000)
    area.setWidget(content)
    area.resize(180, 180)
    area.show()
    APPLICATION.processEvents()
    scrollbar = area.verticalScrollBar()
    scrollbar.setValue(500)

    try:
        _send_mouse(
            area.viewport(),
            QEvent.Type.MouseButtonPress,
            QPoint(40, 40),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
        )
        _send_mouse(
            area.viewport(),
            QEvent.Type.MouseMove,
            QPoint(40, 41),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.MiddleButton,
        )
        QTest.qWait(160)
        slow_distance = scrollbar.value() - 500

        slow_end = scrollbar.value()
        _send_mouse(
            area.viewport(),
            QEvent.Type.MouseMove,
            QPoint(40, 140),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.MiddleButton,
        )
        QTest.qWait(160)
        fast_distance = scrollbar.value() - slow_end

        assert slow_distance > 0
        assert fast_distance > slow_distance * 4
    finally:
        _send_mouse(
            area.viewport(),
            QEvent.Type.MouseButtonRelease,
            QPoint(40, 140),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.NoButton,
        )
        area.close()


def test_middle_drag_scales_pixel_motion_for_item_scrolling_tables() -> None:
    install_middle_mouse_scrolling(APPLICATION)
    model = QStandardItemModel()
    for row in range(100):
        model.appendRow(QStandardItem(f"Track {row}"))
    table = QTableView()
    table.setModel(model)
    table.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerItem)
    table.resize(320, 220)
    table.show()
    APPLICATION.processEvents()
    scrollbar = table.verticalScrollBar()
    scrollbar.setValue(20)

    try:
        _send_mouse(
            table.viewport(),
            QEvent.Type.MouseButtonPress,
            QPoint(40, 40),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
        )
        _send_mouse(
            table.viewport(),
            QEvent.Type.MouseMove,
            QPoint(40, 140),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.MiddleButton,
        )
        QTest.qWait(180)

        assert 20 < scrollbar.value() < 30
    finally:
        _send_mouse(
            table.viewport(),
            QEvent.Type.MouseButtonRelease,
            QPoint(40, 140),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.NoButton,
        )
        table.close()


def test_installation_is_idempotent() -> None:
    assert install_middle_mouse_scrolling(
        APPLICATION
    ) is install_middle_mouse_scrolling(APPLICATION)


def _send_mouse(
    target: QWidget,
    event_type: QEvent.Type,
    local_position: QPoint,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> None:
    global_position = target.mapToGlobal(local_position)
    event = QMouseEvent(
        event_type,
        QPointF(local_position),
        QPointF(global_position),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(target, event)
