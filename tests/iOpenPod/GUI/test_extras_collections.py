"""Compact Extras panels keep every saved row and its actions reachable."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.extras_test_support import ExtrasTestController, find_widget
from whenever import PlainDateTime

from device_registry import AlarmFormat, ExtrasSupport
from iOpenPod.app.models.extras import AlarmItem, AlarmToneItem, ExtrasCatalog
from iOpenPod.GUI.pages.alarms_page import AlarmsPage
from iOpenPod.GUI.pages.tones_page import TonesPage
from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LAYOUT,
    LIGHT_TOKENS,
    ORIGINAL_DARK_TOKENS,
    ThemeTokens,
    resolve_typography,
)
from iOpenPod.GUI.widgets.extras_collection import ExtrasCollection
from iPodDB.alarms import AlarmToneNote

NOTES = (AlarmToneNote(262, 500),)
CATALOG = ExtrasCatalog(
    support=ExtrasSupport(alarm_format=AlarmFormat.CLASSIC, alarm_write=True),
    alarms=(
        AlarmItem(
            0, "Holiday", PlainDateTime(2026, 11, 16, 10, 12), 4, True, enabled=True
        ),
        AlarmItem(
            1, "Birthday", PlainDateTime(2026, 11, 16, 15, 52), 2, True, enabled=False
        ),
    ),
    tones=(
        AlarmToneItem("beep", "Beep", NOTES, builtin=True),
        AlarmToneItem("melody", "A saved melody", NOTES),
    ),
    can_create_alarm=True,
)


@pytest.fixture(params=[AlarmsPage, TonesPage])
def workspace(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[AlarmsPage | TonesPage, ExtrasTestController]]:
    page_type: type[AlarmsPage] | type[TonesPage] = request.param
    controller = ExtrasTestController(CATALOG)
    page = page_type(controller)
    try:
        yield page, controller
    finally:
        page.close()


@pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS, ORIGINAL_DARK_TOKENS])
def test_short_collections_fit_their_rows_and_preserve_keyboard_selection(
    workspace: tuple[AlarmsPage | TonesPage, ExtrasTestController], tokens: ThemeTokens
) -> None:
    page, controller = workspace
    page.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    panel = page.findChild(ExtrasCollection)
    assert panel is not None
    for width, height in [(1440, 900), (760, 500), (1000, 700), (2560, 1330)]:
        page.resize(width, height)
        page.show()
        APPLICATION.processEvents()
        assert page.size().width() == width
        assert page.size().height() == height
        assert panel.width() <= LAYOUT.extras_collection_width
        assert panel.height() < 400
        assert panel.view.verticalScrollBar().maximum() == 0
        bounds = QRect(panel.mapTo(page, QPoint()), panel.size())
        assert page.rect().contains(bounds)
        tree = panel.view
        tree.setFocus()
        QTest.keyClick(tree, Qt.Key.Key_End)
        assert tree.currentItem() == tree.topLevelItem(1)
        controller.changed.emit()
        assert tree.currentItem() == tree.topLevelItem(1)
        QTest.keyClick(tree, Qt.Key.Key_Home)
        assert tree.currentItem() == tree.topLevelItem(0)


def test_long_collections_scroll_without_hiding_actions_and_shrink_when_cleared(
    workspace: tuple[AlarmsPage | TonesPage, ExtrasTestController],
) -> None:
    page, controller = workspace
    page.setStyleSheet(render_stylesheet(ORIGINAL_DARK_TOKENS, resolve_typography()))
    controller.view = replace(
        CATALOG,
        alarms=tuple(replace(CATALOG.alarms[0], index=i) for i in range(20)),
        tones=tuple(AlarmToneItem(str(i), "A saved melody", NOTES) for i in range(19)),
    )
    controller.changed.emit()
    page.resize(760, 420)
    page.show()
    APPLICATION.processEvents()
    panel = page.findChild(ExtrasCollection)
    assert panel is not None
    tree = panel.view
    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_End)
    APPLICATION.processEvents()
    last = tree.topLevelItem(tree.topLevelItemCount() - 1)
    assert last is not None and tree.currentItem() == last
    assert tree.verticalScrollBar().maximum() > 0
    # The visible highlight is inset from the native item's scroll boundary.
    inset = LAYOUT.space_2xs
    assert (
        tree.viewport()
        .rect()
        .contains(tree.visualItemRect(last).adjusted(inset, inset, -inset, -inset))
    )
    for button in panel.findChildren(QPushButton):
        assert button.isVisible()
        assert page.rect().contains(QRect(button.mapTo(page, QPoint()), button.size()))
        assert (
            button.mapTo(page, QPoint()).y()
            >= tree.mapTo(page, QPoint(0, tree.height())).y()
        )
    page.resize(760, 900)
    APPLICATION.processEvents()
    populated_height = panel.height()
    populated_width = panel.width()
    controller.view = replace(CATALOG, alarms=(), tones=())
    controller.working = True
    controller.changed.emit()
    APPLICATION.processEvents()
    assert not tree.isVisible()
    assert panel.empty.isVisible() and "Loading" in panel.empty.text()
    assert panel.height() < populated_height
    assert panel.width() == populated_width
    controller.working = False
    controller.changed.emit()
    assert "No " in panel.empty.text()
    for name in ("alarmEdit", "tonePreview"):
        action = page.findChild(QPushButton, name)
        if action is not None:
            assert not action.isEnabled()


def test_tone_row_retains_hidden_metadata_for_accessibility_and_tooltips() -> None:
    controller = ExtrasTestController(CATALOG)
    page = TonesPage(controller)
    try:
        panel = page.findChild(ExtrasCollection)
        assert panel is not None
        row = panel.view.topLevelItem(0)
        assert row is not None
        description = row.data(0, Qt.ItemDataRole.AccessibleTextRole)
        assert description == row.toolTip(0)
        assert all(row.text(column) in description for column in range(3))
        assert panel.view.accessibleName() == "Tones"
        controller.error = "Could not preview this tone."
        controller.changed.emit()
        assert any(
            label.text() == controller.error for label in page.findChildren(QLabel)
        )
        assert find_widget(page, QPushButton, "tonePreview").isEnabled()
    finally:
        page.close()
