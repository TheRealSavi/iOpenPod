"""Section slides preserve grouping, input targets, and bounded rendering."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.models.selection_grouping import (
    SelectionGroupingProxyModel,
    SelectionGroupingRole,
)
from iOpenPod.GUI.delegates.selection_group_delegate import SelectionGroupDelegate
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.equalized_grid import EqualizedGridView


class _Cards(QStyledItemDelegate):
    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(180, 90)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.fillRect(option.rect, QColor("#417faa"))
        painter.fillRect(option.rect.adjusted(0, 0, 0, -60), QColor("#d0a050"))
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, str(index.data()))


@pytest.fixture
def grid() -> Iterator[EqualizedGridView]:
    source = QStandardItemModel()
    for row in range(15):
        item = QStandardItem(f"Card {row}")
        item.setCheckable(True)
        item.setCheckState(
            Qt.CheckState.Checked if row < 3 else Qt.CheckState.Unchecked
        )
        source.appendRow(item)
    model = SelectionGroupingProxyModel(source)
    model.set_grouping_enabled(True)
    theme = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    view = EqualizedGridView()
    view.setModel(model)
    view.setItemDelegate(SelectionGroupDelegate(_Cards(view), theme, view))
    view.synchronize_item_size()
    view.setViewMode(QListView.ViewMode.IconMode)
    view.setFlow(QListView.Flow.LeftToRight)
    view.setWrapping(True)
    view.setMovement(QListView.Movement.Static)
    view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
    view.set_sectioned_layout(True)
    view.resize(640, 440)
    view.show()
    APPLICATION.processEvents()
    view.doItemsLayout()
    APPLICATION.processEvents()
    try:
        yield view
    finally:
        view.close()
        theme.close()


def _toggle(view: EqualizedGridView) -> None:
    QTest.mouseClick(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        view.visualRect(view.model().index(0, 0)).center(),
    )


def _animation(view: EqualizedGridView) -> QVariantAnimation:
    animation = view.findChild(QVariantAnimation, "selectionGroupAnimation")
    assert animation is not None
    return animation


def _overlay(view: EqualizedGridView) -> QWidget:
    overlay = view.findChild(QWidget, "selectionGroupSlide")
    assert overlay is not None
    return overlay


@pytest.mark.parametrize("expanding", [False, True])
def test_cards_slide_below_fixed_header_and_finish_on_live_grid(
    grid: EqualizedGridView,
    expanding: bool,
) -> None:
    animation = _animation(grid)
    if expanding:
        _toggle(grid)
        animation.setCurrentTime(animation.duration())
    header = grid.visualRect(grid.model().index(0, 0))
    _toggle(grid)
    overlay = _overlay(grid)
    assert overlay.isVisible()
    assert animation.state() == QAbstractAnimation.State.Running
    assert grid.model().index(0, 0).data(SelectionGroupingRole.EXPANDED) is expanding
    assert overlay.y() == header.bottom() + 1
    assert overlay.size().width() == grid.viewport().width()
    start = overlay.grab().toImage()
    animation.setCurrentTime(animation.duration() // 2)
    middle = overlay.grab().toImage()
    assert start != middle
    assert grid.visualRect(grid.model().index(0, 0)) == header
    animation.setCurrentTime(animation.duration())
    assert not overlay.isVisible()
    assert grid.model().rowCount() == (17 if expanding else 14)


def test_rapid_toggle_reverses_from_current_frame(grid: EqualizedGridView) -> None:
    _toggle(grid)
    animation = _animation(grid)
    animation.setCurrentTime(animation.duration() // 2)
    before = _overlay(grid).grab().toImage()
    _toggle(grid)
    assert _overlay(grid).isVisible()
    assert _overlay(grid).grab().toImage() == before
    assert grid.model().index(0, 0).data(SelectionGroupingRole.EXPANDED) is True
    animation.setCurrentTime(animation.duration())
    assert not _overlay(grid).isVisible()


def test_keyboard_toggle_preserves_header_focus_for_reversal(
    grid: EqualizedGridView,
) -> None:
    grid.setCurrentIndex(grid.model().index(0, 0))
    QTest.keyClick(grid, Qt.Key.Key_Space)
    animation = _animation(grid)
    animation.setCurrentTime(animation.duration() // 2)
    assert grid.currentIndex() == grid.model().index(0, 0)
    QTest.keyClick(grid, Qt.Key.Key_Space)
    assert grid.model().index(0, 0).data(SelectionGroupingRole.EXPANDED) is True
    assert _overlay(grid).isVisible()


@pytest.mark.parametrize("interrupt", ["resize", "hide", "scroll", "model", "navigate"])
def test_changed_view_cancels_snapshot_and_keeps_committed_state(
    grid: EqualizedGridView,
    interrupt: str,
) -> None:
    _toggle(grid)
    assert _overlay(grid).isVisible()
    if interrupt == "resize":
        grid.resize(700, 440)
    elif interrupt == "hide":
        grid.hide()
    elif interrupt == "scroll":
        grid.verticalScrollBar().setValue(10)
    elif interrupt == "navigate":
        QTest.keyClick(grid, Qt.Key.Key_Down)
    else:
        model = grid.model()
        assert isinstance(model, SelectionGroupingProxyModel)
        source = model.sourceModel()
        source.setData(source.index(0, 0), "Changed")
    assert not _overlay(grid).isVisible()
    assert _animation(grid).state() == QAbstractAnimation.State.Stopped
    assert grid.model().index(0, 0).data(SelectionGroupingRole.EXPANDED) is False


def test_snapshot_does_not_activate_cards_at_hidden_final_positions(
    grid: EqualizedGridView,
) -> None:
    _toggle(grid)
    before = grid.currentIndex()
    overlay = _overlay(grid)
    QTest.mouseClick(
        overlay,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        overlay.rect().center(),
    )
    assert grid.currentIndex() == before


def test_hidden_grid_toggles_without_starting_animation(
    grid: EqualizedGridView,
) -> None:
    grid.hide()
    delegate = grid.itemDelegate()
    index = grid.model().index(0, 0)
    option = QStyleOptionViewItem()
    option.initFrom(grid)
    option.rect = grid.visualRect(index)
    assert delegate.editorEvent(
        QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier
        ),
        grid.model(),
        option,
        index,
    )
    assert _animation(grid).state() == QAbstractAnimation.State.Stopped
    assert not _overlay(grid).isVisible()


def test_large_single_group_animates_across_scrollbar_changes(
    grid: EqualizedGridView,
) -> None:
    model = grid.model()
    assert isinstance(model, SelectionGroupingProxyModel)
    source = model.sourceModel()
    assert isinstance(source, QStandardItemModel)
    source.clear()
    for row in range(1_000):
        item = QStandardItem(f"Card {row}")
        item.setCheckable(True)
        item.setCheckState(Qt.CheckState.Checked)
        source.appendRow(item)
    grid.setLayoutMode(QListView.LayoutMode.Batched)
    grid.setBatchSize(64)
    grid.doItemsLayout()
    APPLICATION.processEvents()
    _toggle(grid)
    APPLICATION.processEvents()
    assert _overlay(grid).isVisible()
    assert model.rowCount() == 1
    assert _overlay(grid).height() <= grid.viewport().height()
    animation = _animation(grid)
    animation.setCurrentTime(animation.duration())
    _toggle(grid)
    APPLICATION.processEvents()
    assert _overlay(grid).isVisible()
    assert model.rowCount() == 1_001
    animation.setCurrentTime(animation.duration())
    assert not _overlay(grid).isVisible()
