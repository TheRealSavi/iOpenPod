"""Calendar destinations use the shared dropdown and preserve explicit choices."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.extras_test_support import ExtrasTestController, find_widget

from device_registry import ExtrasSupport
from iOpenPod.app.models.extras import CalendarGroup, ExtrasCatalog
from iOpenPod.GUI.dialogs.calendar_picker import CalendarPickerDialog
from iOpenPod.GUI.pages.calendar_page import CalendarEditor, CalendarPage
from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
from iOpenPod.GUI.presentation.theme.tokens import (
    LIGHT_TOKENS,
    ORIGINAL_DARK_TOKENS,
    ThemeTokens,
    resolve_typography,
)
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox


@pytest.mark.parametrize("tokens", [LIGHT_TOKENS, ORIGINAL_DARK_TOKENS])
def test_calendar_picker_has_an_opaque_themed_dialog_surface(
    tokens: ThemeTokens,
) -> None:
    original = APPLICATION.styleSheet()
    APPLICATION.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    dialog = CalendarPickerDialog(("Work", "Personal"))
    dialog.show()
    APPLICATION.processEvents()
    try:
        pixel = dialog.grab().toImage().pixelColor(2, 2)
        assert pixel.alpha() == 255
        assert pixel == QColor(tokens.window)
    finally:
        dialog.close()
        APPLICATION.setStyleSheet(original)


def test_calendar_picker_uses_themed_dropdown_and_accepts_the_selected_index() -> None:
    dialog = CalendarPickerDialog(("Work", "Personal"))
    dialog.show()
    APPLICATION.processEvents()
    try:
        combo = find_widget(dialog, AppComboBox, "calendarDestination")
        assert combo.property("themedIndicator") is True
        assert combo.view().property("themedComboPopup") is True
        combo.setCurrentIndex(1)
        accept = next(b for b in dialog.findChildren(QPushButton) if b.isDefault())
        QTest.mouseClick(accept, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.selected_index() == 1
    finally:
        dialog.close()


def test_calendar_picker_escape_cancels() -> None:
    dialog = CalendarPickerDialog(("Work", "Personal"))
    dialog.show()
    APPLICATION.processEvents()
    try:
        combo = find_widget(dialog, AppComboBox, "calendarDestination")
        combo.setCurrentIndex(1)
        QTest.keyClick(combo, Qt.Key.Key_Escape)
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert not dialog.isVisible()
    finally:
        dialog.close()


@pytest.mark.parametrize("accepted", [True, False])
def test_calendar_page_uses_picked_destination_or_cancels_without_editing(
    monkeypatch: pytest.MonkeyPatch, accepted: bool
) -> None:
    groups = (
        CalendarGroup("Work", ("first.ics",), True),
        CalendarGroup("Work", ("second.ics",), True),
    )
    controller = ExtrasTestController(
        ExtrasCatalog(support=ExtrasSupport(calendar_write=True), calendars=groups)
    )
    page = CalendarPage(controller)
    choices: list[str] = []

    def choose(picker: CalendarPickerDialog) -> int:
        combo = find_widget(picker, AppComboBox, "calendarDestination")
        choices.extend(combo.itemText(index) for index in range(combo.count()))
        combo.setCurrentIndex(1)
        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

    monkeypatch.setattr(CalendarPickerDialog, "exec", choose)
    try:
        find_widget(page, QPushButton, "calendarNew").click()
        assert choices == ["Work (1)", "Work (2)"]
        editor = page.findChild(CalendarEditor)
        if accepted:
            assert editor is not None
            editor.accept()
            assert controller.destinations == [groups[1]]
        else:
            assert editor is None
            assert not controller.calendar_edits
    finally:
        page.close()
        APPLICATION.processEvents()
