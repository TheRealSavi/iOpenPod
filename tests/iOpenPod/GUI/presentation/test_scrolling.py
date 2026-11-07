"""Shared wheel input animates ordinary areas and stops tables on row boundaries."""

import gc
from collections.abc import Iterator
from typing import Literal
from weakref import ReferenceType, ref

import pytest
from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEvent,
    QPoint,
    QPointF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QMouseEvent, QStandardItem, QStandardItemModel, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QListView,
    QPlainTextEdit,
    QScrollArea,
    QScrollBar,
    QSpinBox,
    QTableView,
    QTextEdit,
    QTreeView,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.presentation.scrolling import install_scrolling
from iOpenPod.GUI.presentation.smooth_wheel_scrolling import SmoothWheelScrolling


def _wheel(
    area: QAbstractScrollArea,
    angle: int = -120,
    *,
    pixels: int = 0,
    over_scrollbar: bool = False,
    target: QWidget | None = None,
) -> QWheelEvent:
    target = target or (area.verticalScrollBar() if over_scrollbar else area.viewport())
    point = QPoint(40, 40)
    event = QWheelEvent(
        QPointF(point),
        QPointF(target.mapToGlobal(point)),
        QPoint(0, pixels),
        QPoint(0, angle),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    APPLICATION.sendEvent(target, event)
    return event


def _animation(area: QAbstractScrollArea) -> QVariantAnimation:
    controller = area.findChild(
        SmoothWheelScrolling, options=Qt.FindChildOption.FindDirectChildrenOnly
    )
    assert controller is not None
    animation = controller.findChild(QVariantAnimation, "wheelScrollAnimation")
    assert animation is not None
    return animation


def _finish(area: QAbstractScrollArea) -> None:
    animation = _animation(area)
    animation.setCurrentTime(animation.duration())


@pytest.fixture
def table() -> Iterator[QTableView]:
    view = QTableView()
    model = QStandardItemModel(view)
    for row in range(100):
        model.appendRow(QStandardItem(f"Track {row}"))
    view.setModel(model)
    view.verticalHeader().setDefaultSectionSize(40)
    view.resize(400, 300)
    view.show()
    APPLICATION.processEvents()
    yield view
    view.close()


@pytest.mark.parametrize("over_scrollbar", (False, True))
def test_table_wheel_animates_one_row_per_notch(
    table: QTableView, over_scrollbar: bool
) -> None:
    bar = table.verticalScrollBar()
    assert _wheel(table, over_scrollbar=over_scrollbar).isAccepted()
    assert bar.value() == 0
    animation = _animation(table)
    animation.setCurrentTime(animation.duration() // 2)
    assert 0 < bar.value() < 40
    _finish(table)
    assert bar.value() == 40
    assert table.rowViewportPosition(1) == 0


@pytest.mark.parametrize("over_scrollbar", (False, True))
def test_wheel_recovers_when_qt_replaces_the_vertical_scrollbar(
    table: QTableView, over_scrollbar: bool, capfd: pytest.CaptureFixture[str]
) -> None:
    _wheel(table, -360)
    animation = _animation(table)
    animation.setCurrentTime(animation.duration() // 2)
    replacement = QScrollBar(Qt.Orientation.Vertical)
    table.setVerticalScrollBar(replacement)
    position = replacement.value()
    _finish(table)
    assert replacement.value() == position

    replacement.setValue(0)
    assert _wheel(table, over_scrollbar=over_scrollbar).isAccepted()
    assert animation.state() is QAbstractAnimation.State.Running
    _finish(table)
    assert replacement.value() == table.rowHeight(0)

    _wheel(table, over_scrollbar=over_scrollbar)
    replacement.setValue(3 * table.rowHeight(0))
    assert animation.state() is QAbstractAnimation.State.Stopped
    assert "already deleted" not in capfd.readouterr().err


@pytest.mark.parametrize("over_scrollbar", (False, True))
@pytest.mark.parametrize("replace_scrollbar", (False, True))
def test_wheel_recovers_when_qt_replaces_the_viewport(
    table: QTableView,
    over_scrollbar: bool,
    replace_scrollbar: bool,
    capfd: pytest.CaptureFixture[str],
) -> None:
    for _ in range(2):
        _wheel(table, -360)
        table.setViewport(QWidget())
        if replace_scrollbar:
            table.setVerticalScrollBar(QScrollBar(Qt.Orientation.Vertical))
        bar = table.verticalScrollBar()
        position = bar.value()
        _finish(table)
        assert bar.value() == position
        APPLICATION.processEvents()
        bar.setValue(0)

        assert _wheel(table, over_scrollbar=over_scrollbar).isAccepted()
        _finish(table)
        assert bar.value() == table.rowHeight(0)

        _wheel(table, over_scrollbar=over_scrollbar)
        table.viewport().hide()
        assert _animation(table).state() is QAbstractAnimation.State.Stopped
        table.viewport().show()
    assert "already deleted" not in capfd.readouterr().err


def test_table_uses_visible_row_geometry_including_reordered_rows(
    table: QTableView,
) -> None:
    table.setRowHeight(0, 60)
    table.setRowHidden(1, True)
    table.setRowHeight(2, 80)
    table.verticalHeader().moveSection(3, 2)
    APPLICATION.processEvents()
    _wheel(table)
    _finish(table)
    assert table.verticalScrollBar().value() == 60
    assert table.rowViewportPosition(3) == 0
    _wheel(table)
    _finish(table)
    assert table.rowViewportPosition(2) == 0
    _wheel(table)
    _finish(table)
    assert table.verticalScrollBar().value() == 180
    _wheel(table, 120)
    _finish(table)
    assert table.rowViewportPosition(2) == 0


def test_table_accumulates_notches_and_reverses_to_a_row_boundary(
    table: QTableView,
) -> None:
    for _ in range(3):
        _wheel(table)
    animation = _animation(table)
    animation.setCurrentTime(animation.duration() // 2)
    before = table.verticalScrollBar().value()
    assert 80 < before < 120
    changes = QSignalSpy(table.verticalScrollBar().valueChanged)
    _wheel(table, 120)
    assert changes.count() == 0
    _finish(table)
    assert table.verticalScrollBar().value() == 80


def test_table_accumulates_small_wheel_deltas_into_whole_rows(
    table: QTableView,
) -> None:
    for _ in range(119):
        assert _wheel(table, -1).isAccepted()
    assert table.verticalScrollBar().value() == 0
    _wheel(table, -1)
    _finish(table)
    assert table.verticalScrollBar().value() == 40


def test_partial_reversal_stops_outstanding_table_travel(table: QTableView) -> None:
    _wheel(table, -360)
    animation = _animation(table)
    animation.setCurrentTime(animation.duration() // 2)
    position = table.verticalScrollBar().value()
    _wheel(table, 60)
    assert animation.state() is QAbstractAnimation.State.Stopped
    assert table.verticalScrollBar().value() == position
    _wheel(table, 60)
    _finish(table)
    assert table.verticalScrollBar().value() == 80


def test_table_wheel_burst_stays_bounded_and_row_aligned(table: QTableView) -> None:
    for _ in range(40):
        _wheel(table)
    _finish(table)
    value = table.verticalScrollBar().value()
    assert 0 < value <= table.viewport().height()
    assert value % 40 == 0


def test_table_trackpad_stays_precise_and_next_notch_returns_to_a_row(
    table: QTableView,
) -> None:
    _wheel(table)
    _wheel(table, pixels=-17)
    assert table.verticalScrollBar().value() == 17
    assert _animation(table).state() is QAbstractAnimation.State.Stopped
    _wheel(table)
    _finish(table)
    assert table.verticalScrollBar().value() == 40


def test_table_wheel_reaches_both_edges(table: QTableView) -> None:
    bar = table.verticalScrollBar()
    bar.setValue((bar.maximum() - 1) // table.rowHeight(0) * table.rowHeight(0))
    _wheel(table)
    _finish(table)
    assert bar.value() == bar.maximum()
    _wheel(table)
    assert _animation(table).state() is QAbstractAnimation.State.Stopped
    bar.setValue(5)
    _wheel(table, 120)
    _finish(table)
    assert bar.value() == 0


@pytest.mark.parametrize(
    "action", ("hide", "reset", "resize_row", "keyboard", "slider")
)
def test_table_navigation_and_layout_cancel_animation(
    table: QTableView,
    action: Literal["hide", "reset", "resize_row", "keyboard", "slider"],
) -> None:
    table.setCurrentIndex(table.model().index(0, 0))
    _wheel(table)
    match action:
        case "hide":
            table.hide()
        case "reset":
            table.model().removeRows(0, table.model().rowCount())
        case "resize_row":
            table.setRowHeight(0, 70)
        case "keyboard":
            QTest.keyClick(table, Qt.Key.Key_PageDown)
        case "slider":
            table.verticalScrollBar().setSliderDown(True)
    APPLICATION.processEvents()
    assert _animation(table).state() is QAbstractAnimation.State.Stopped


def test_middle_press_cancels_wheel_before_any_drag_motion(table: QTableView) -> None:
    _wheel(table)
    point = QPoint(40, 40)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(point),
        QPointF(table.viewport().mapToGlobal(point)),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    APPLICATION.sendEvent(table.viewport(), event)
    assert _animation(table).state() is QAbstractAnimation.State.Stopped
    QTest.qWait(160)
    assert table.verticalScrollBar().value() == 0


@pytest.mark.parametrize("kind", ("area", "list", "tree", "text", "plain_text"))
def test_new_scroll_surfaces_automatically_receive_smooth_wheel_input(
    kind: str,
) -> None:
    area: QAbstractScrollArea
    if kind == "area":
        area = QScrollArea()
        content = QWidget()
        content.resize(250, 2_000)
        area.setWidget(content)
    elif kind in {"text", "plain_text"}:
        area = QTextEdit() if kind == "text" else QPlainTextEdit()
        area.setPlainText("\n".join(f"Line {row}" for row in range(100)))
    else:
        area = QListView() if kind == "list" else QTreeView()
        model = QStandardItemModel(area)
        for row in range(100):
            model.appendRow(QStandardItem(f"Item {row}"))
        area.setModel(model)
    area.resize(300, 250)
    area.show()
    APPLICATION.processEvents()
    try:
        _wheel(area)
        bar = area.verticalScrollBar()
        assert bar.value() == 0
        animation = _animation(area)
        animation.setCurrentTime(animation.duration() // 4)
        intermediate = bar.value()
        _finish(area)
        assert 0 < intermediate < bar.value()
        install_scrolling(APPLICATION)
        area.hide()
        area.show()
        assert len(area.findChildren(QVariantAnimation, "wheelScrollAnimation")) == 1
    finally:
        area.close()


def test_wheel_over_embedded_input_keeps_its_native_action() -> None:
    area = QScrollArea()
    content = QWidget()
    content.resize(300, 2_000)
    spin = QSpinBox(content)
    spin.setValue(50)
    area.setWidget(content)
    area.resize(300, 250)
    area.show()
    APPLICATION.processEvents()
    _wheel(area, target=spin)
    assert spin.value() == 49
    assert area.verticalScrollBar().value() == 0
    assert _animation(area).state() is QAbstractAnimation.State.Stopped


def test_deleting_a_dialog_disposes_its_pending_scroll_animation() -> None:
    dialog = QWidget()
    area = QTextEdit(dialog)
    area.setPlainText("\n".join(f"Line {row}" for row in range(100)))
    dialog.show()
    APPLICATION.processEvents()
    _wheel(area)
    destroyed = QSignalSpy(_animation(area).destroyed)
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1


def test_collecting_a_visible_scroll_area_does_not_call_cleared_controller(
    capfd: pytest.CaptureFixture[str],
) -> None:
    def show_text_editor() -> ReferenceType[QPlainTextEdit]:
        area = QPlainTextEdit()
        area.show()
        APPLICATION.processEvents()
        _animation(area)
        return ref(area)

    editor = show_text_editor()
    gc.collect()
    APPLICATION.processEvents()

    assert editor() is None
    errors = capfd.readouterr().err
    assert "Error calling Python override" not in errors
    assert "Slot 'SmoothWheelScrolling::' not found" not in errors


def test_table_can_reach_bottom_of_a_final_row_taller_than_the_viewport(
    table: QTableView,
) -> None:
    table.setRowHeight(99, 600)
    APPLICATION.processEvents()
    table.verticalScrollBar().setValue(table.verticalHeader().sectionPosition(99))
    _wheel(table)
    _finish(table)
    assert table.verticalScrollBar().value() == table.verticalScrollBar().maximum()


def test_nested_wheel_scrolls_inner_table_then_outer_area_at_the_edge() -> None:
    outer = QScrollArea()
    content = QWidget()
    content.resize(350, 2_000)
    inner = QTableView(content)
    model = QStandardItemModel(100, 1, inner)
    inner.setModel(model)
    inner.resize(300, 200)
    outer.setWidget(content)
    outer.resize(400, 300)
    outer.show()
    APPLICATION.processEvents()
    point = inner.viewport().mapTo(outer, QPoint(40, 40))
    window = outer.windowHandle()
    QTest.wheelEvent(window, point, QPoint(0, -120))
    _finish(inner)
    assert inner.verticalScrollBar().value() == inner.rowHeight(0)
    assert outer.verticalScrollBar().value() == 0
    inner.verticalScrollBar().setValue(inner.verticalScrollBar().maximum())
    QTest.wheelEvent(window, point, QPoint(0, -120))
    _finish(outer)
    assert outer.verticalScrollBar().value() > 0


def test_plain_text_trackpad_input_uses_native_line_conversion() -> None:
    area = QPlainTextEdit()
    area.setPlainText("\n".join(f"Line {row}" for row in range(100)))
    area.resize(300, 200)
    area.show()
    APPLICATION.processEvents()
    _wheel(area, angle=0, pixels=-17)
    # A pixel delta must never become seventeen complete text lines.
    assert area.verticalScrollBar().value() < 17
    assert _animation(area).state() is QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("row_height", (64, 148), ids=("queue", "podcast_episodes"))
@pytest.mark.parametrize("wheel_lines", (1, 3, 6))
def test_tall_list_rows_do_not_inflate_wheel_distance(
    row_height: int, wheel_lines: int
) -> None:
    """Exercise the native list geometry used by Queue and Podcast rows."""

    lines = APPLICATION.wheelScrollLines()
    APPLICATION.setWheelScrollLines(wheel_lines)
    view = QListView()
    model = QStandardItemModel(view)
    for row in range(100):
        item = QStandardItem(f"Item {row}")
        item.setSizeHint(QSize(200, row_height))
        model.appendRow(item)
    view.setModel(model)
    view.setUniformItemSizes(True)
    view.resize(400, 500)
    view.show()
    APPLICATION.processEvents()
    try:
        _wheel(view)
        _finish(view)
        distance = view.verticalScrollBar().value()
        assert distance == 32 * wheel_lines, (
            f"One notch scrolled {distance} pixels "
            f"(native line step: {view.verticalScrollBar().singleStep()})"
        )
        view.resize(480, 600)
        APPLICATION.processEvents()
        view.verticalScrollBar().setValue(0)
        _wheel(view)
        _finish(view)
        assert view.verticalScrollBar().value() == 32 * wheel_lines
    finally:
        view.close()
        APPLICATION.setWheelScrollLines(lines)
