"""Grid wheel input moves predictable pixel distances without jumping cards."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import (
    QAbstractAnimation,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QStandardItem, QStandardItemModel, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyleOptionViewItem
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.delegates.inline_album_delegate import InlineAlbumDelegate
from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView


class _CardDelegate(QStyledItemDelegate):
    def sizeHint(
        self, _option: QStyleOptionViewItem, _index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(160, 240)


@pytest.fixture
def grid() -> Iterator[EqualizedGridView]:
    lines = APPLICATION.wheelScrollLines()
    APPLICATION.setWheelScrollLines(3)
    view = EqualizedGridView()
    model = QStandardItemModel(view)
    for number in range(240):
        model.appendRow(QStandardItem(f"Album {number}"))
    view.setModel(model)
    view.setItemDelegate(_CardDelegate(view))
    view.synchronize_item_size()
    view.setViewMode(QListView.ViewMode.IconMode)
    view.setFlow(QListView.Flow.LeftToRight)
    view.setWrapping(True)
    view.setUniformItemSizes(True)
    view.setMovement(QListView.Movement.Static)
    view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.resize(900, 600)
    view.show()
    QTest.qWait(50)
    try:
        yield view
    finally:
        view.close()
        APPLICATION.setWheelScrollLines(lines)


def _wheel(
    view: EqualizedGridView,
    angle: int = -120,
    *,
    pixels: int = 0,
    inverted: bool = False,
    over_scrollbar: bool = False,
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> QWheelEvent:
    point = QPoint(80, 80)
    event = QWheelEvent(
        QPointF(point),
        QPointF(view.viewport().mapToGlobal(point)),
        QPoint(0, pixels),
        QPoint(0, angle),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        inverted,
    )
    APPLICATION.sendEvent(
        view.verticalScrollBar() if over_scrollbar else view.viewport(), event
    )
    return event


def _animation(view: EqualizedGridView) -> QVariantAnimation:
    animation = view.findChild(QVariantAnimation, "gridWheelScrollAnimation")
    assert animation is not None
    return animation


def _finish(view: EqualizedGridView) -> None:
    animation = _animation(view)
    if animation.state() is QAbstractAnimation.State.Running:
        animation.setCurrentTime(animation.duration())


def test_one_wheel_notch_scrolls_less_than_a_card(grid: EqualizedGridView) -> None:
    _wheel(grid)
    QTest.qWait(240)
    distance = grid.verticalScrollBar().value()
    assert 0 < distance <= 144, f"One wheel notch jumped {distance} pixels"


@pytest.mark.parametrize("over_scrollbar", (False, True))
def test_discrete_wheel_moves_through_intermediate_positions(
    grid: EqualizedGridView, over_scrollbar: bool
) -> None:
    event = _wheel(grid, over_scrollbar=over_scrollbar)
    bar = grid.verticalScrollBar()
    assert event.isAccepted() and bar.value() == 0
    animation = _animation(grid)
    animation.setCurrentTime(animation.duration() // 2)
    assert 0 < bar.value() < 96
    _finish(grid)
    assert bar.value() == 96


@pytest.mark.parametrize("lines", (1, 3, 6))
def test_wheel_respects_host_line_count(grid: EqualizedGridView, lines: int) -> None:
    APPLICATION.setWheelScrollLines(lines)
    _wheel(grid)
    _finish(grid)
    assert grid.verticalScrollBar().value() == lines * 32


def test_repeated_wheel_input_accumulates_and_reversal_drops_pending_travel(
    grid: EqualizedGridView,
) -> None:
    for _ in range(3):
        _wheel(grid)
    _finish(grid)
    bar = grid.verticalScrollBar()
    assert bar.value() == 288
    for _ in range(3):
        _wheel(grid)
    animation = _animation(grid)
    animation.setCurrentTime(animation.duration() // 2)
    before_reversal = bar.value()
    _wheel(grid, 120)
    _finish(grid)
    assert bar.value() == before_reversal - 96


def test_large_wheel_burst_bounds_queued_travel(grid: EqualizedGridView) -> None:
    for _ in range(40):
        _wheel(grid)
    _finish(grid)
    assert 0 < grid.verticalScrollBar().value() <= grid.viewport().height()


@pytest.mark.parametrize("settled", (False, True))
def test_next_wheel_event_does_not_jump_while_retargeting_animation(
    grid: EqualizedGridView, settled: bool
) -> None:
    _wheel(grid)
    animation = _animation(grid)
    animation.setCurrentTime(
        animation.duration() if settled else animation.duration() // 2
    )
    changes = QSignalSpy(grid.verticalScrollBar().valueChanged)
    _wheel(grid)
    assert changes.count() == 0


def test_trackpad_pixels_apply_immediately_and_cancel_wheel_animation(
    grid: EqualizedGridView,
) -> None:
    bar = grid.verticalScrollBar()
    bar.setValue(400)
    _wheel(grid)
    animation = _animation(grid)
    animation.setCurrentTime(animation.duration() // 2)
    before = bar.value()
    _wheel(grid, pixels=-37)
    assert bar.value() == before + 37
    assert animation.state() is QAbstractAnimation.State.Stopped
    _finish(grid)
    assert bar.value() == before + 37


def test_partial_wheel_deltas_accumulate_without_rounding_each_event(
    grid: EqualizedGridView,
) -> None:
    APPLICATION.setWheelScrollLines(1)
    for _ in range(5):
        assert _wheel(grid, -1).isAccepted()
    _finish(grid)
    assert grid.verticalScrollBar().value() == round(5 / 120 * 32)


def test_natural_scroll_deltas_are_not_inverted_twice(grid: EqualizedGridView) -> None:
    _wheel(grid, inverted=True)
    _finish(grid)
    assert grid.verticalScrollBar().value() == 96


def test_external_scroll_takes_over_from_pending_animation(
    grid: EqualizedGridView,
) -> None:
    _wheel(grid)
    grid.verticalScrollBar().setValue(700)
    QTest.qWait(180)
    assert _animation(grid).state() is QAbstractAnimation.State.Stopped
    assert grid.verticalScrollBar().value() == 700


def test_keyboard_navigation_takes_over_from_pending_animation(
    grid: EqualizedGridView,
) -> None:
    grid.setCurrentIndex(grid.model().index(0, 0))
    _wheel(grid)
    QTest.keyClick(grid, Qt.Key.Key_PageDown)
    position = grid.verticalScrollBar().value()
    QTest.qWait(180)
    assert _animation(grid).state() is QAbstractAnimation.State.Stopped
    assert grid.verticalScrollBar().value() == position


@pytest.mark.parametrize("action", ("hide", "reset"))
def test_hidden_or_replaced_grid_cancels_pending_scroll(
    grid: EqualizedGridView, action: str
) -> None:
    _wheel(grid)
    if action == "hide":
        grid.hide()
    else:
        grid.model().removeRows(0, grid.model().rowCount())
        APPLICATION.processEvents()
    assert _animation(grid).state() is QAbstractAnimation.State.Stopped


def test_expanded_album_row_does_not_inflate_wheel_distance(
    grid: EqualizedGridView,
) -> None:
    delegate = InlineAlbumDelegate(grid.itemDelegate(), grid)
    grid.setItemDelegate(delegate)
    grid.set_sectioned_layout(True)
    delegate.configure_expansion(0, 3, 400)
    grid.doItemsLayout()
    APPLICATION.processEvents()
    _wheel(grid)
    _finish(grid)
    assert grid.verticalScrollBar().value() == 96


def test_wheel_clamps_at_grid_edges(grid: EqualizedGridView) -> None:
    bar = grid.verticalScrollBar()
    bar.setValue(bar.maximum() - 20)
    _wheel(grid)
    _finish(grid)
    assert bar.value() == bar.maximum()
    _wheel(grid)
    assert _animation(grid).state() is QAbstractAnimation.State.Stopped
    bar.setValue(10)
    _wheel(grid, 120)
    _finish(grid)
    assert bar.value() == 0


def test_modified_wheel_retains_native_behavior(grid: EqualizedGridView) -> None:
    _wheel(grid, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert _animation(grid).state() is QAbstractAnimation.State.Stopped
