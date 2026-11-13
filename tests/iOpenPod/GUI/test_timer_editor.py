"""Saved timer controls preserve unknown values and emit explicit preset edits."""

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QPushButton, QSpinBox
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.extras_test_support import ExtrasTestController, find_widget

from device_registry import AlarmFormat, ExtrasSupport
from iOpenPod.app.models.extras import ExtrasCatalog
from iOpenPod.app.timer_sounds import TIMER_SOUND_LABELS
from iOpenPod.GUI.dialogs.timer_editor import TimerEditor
from iOpenPod.GUI.pages.alarms_page import AlarmsPage
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iPodDB.alarms import (
    COUNTDOWN_TIMER_SOUNDS,
    CountdownTimerChanges,
    CountdownTimerSnapshot,
)


def _timer() -> CountdownTimerSnapshot:
    return CountdownTimerSnapshot(
        saved_hours=0,
        saved_minutes=15,
        sleep_ipod=True,
        sound_index=2,
        can_edit_duration=True,
        can_edit_sleep=True,
        can_edit_sound=True,
    )


def test_sound_choice_clears_sleep_without_changing_duration() -> None:
    assert TIMER_SOUND_LABELS == COUNTDOWN_TIMER_SOUNDS
    editor = TimerEditor(_timer())
    try:
        assert editor.selected_changes() == CountdownTimerChanges()
        ending = find_widget(editor, AppComboBox, "timerEnding")
        assert ending.count() == 26
        ending.setCurrentIndex(ending.findData(9))
        assert editor.selected_changes() == CountdownTimerChanges(sound_index=9)
        ending.setCurrentIndex(ending.findData(-1))
        assert editor.selected_changes() == CountdownTimerChanges()
        find_widget(editor, QSpinBox, "timerMinutes").setValue(25)
        assert editor.selected_changes() == CountdownTimerChanges(saved_minutes=25)
    finally:
        editor.close()


def test_unknown_values_are_unchanged_until_explicit_selection() -> None:
    editor = TimerEditor(
        replace(
            _timer(),
            saved_hours=None,
            saved_minutes=None,
            sound_index=None,
            sleep_ipod=None,
        )
    )
    try:
        assert editor.selected_changes() == CountdownTimerChanges()
        assert find_widget(editor, QSpinBox, "timerHours").value() == -1
        ending = find_widget(editor, AppComboBox, "timerEnding")
        assert ending.currentData() is None
        ending.setCurrentIndex(ending.findData(-1))
        assert editor.selected_changes() == CountdownTimerChanges(sleep_ipod=True)
    finally:
        editor.close()


@pytest.mark.parametrize("expire", ("device", "catalog", "busy"))
def test_timer_editor_is_bound_to_captured_device_and_settings(expire: str) -> None:
    controller = ExtrasTestController(
        ExtrasCatalog(
            timer=_timer(),
            support=ExtrasSupport(
                alarm_format=AlarmFormat.TIMER, timer_settings_write=True
            ),
        )
    )
    page = AlarmsPage(controller)
    try:
        find_widget(page, QPushButton, "timerEdit").click()
        editor = page.findChild(TimerEditor)
        assert editor is not None and editor.isVisible()
        if expire == "device":
            controller.current = None
        elif expire == "catalog":
            controller.view = replace(controller.view)
        else:
            controller.working = True
        controller.changed.emit()
        APPLICATION.processEvents()
        if expire == "busy":
            assert not find_widget(editor, QPushButton, "timerEditorSave").isEnabled()
        else:
            assert not editor.isVisible()
    finally:
        page.close()
        APPLICATION.processEvents()
