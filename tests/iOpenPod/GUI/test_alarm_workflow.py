"""Alarm controls submit explicit native edits and expire with their device."""

from dataclasses import replace
from itertools import pairwise

import pytest
from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTimeEdit,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.extras_test_support import ExtrasTestController, find_widget
from whenever import PlainDateTime

from device_registry import DEFAULT_DEVICE_REGISTRY, AlarmFormat, ExtrasSupport
from iOpenPod.app.models.extras import AlarmItem, AlarmSound, ExtrasCatalog
from iOpenPod.GUI.pages.alarms_page import AlarmEditor, AlarmsPage
from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    ThemeTokens,
    resolve_typography,
)
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iPodDB.alarms import CountdownTimerSnapshot

SUPPORT = ExtrasSupport(alarm_format=AlarmFormat.CLASSIC, alarm_write=True)


def test_sound_change_retains_disabled_checkbox_and_submits_explicit_choice() -> None:
    beep = AlarmSound(AlarmSound.Kind.BEEP, "Beep", tone_name="Signalton")
    bells = AlarmSound(AlarmSound.Kind.TONE, "Morning bells", tone_name="Morning bells")
    item = AlarmItem(
        0,
        "Alarm",
        PlainDateTime(2027, 1, 1, 8),
        0,
        True,
        enabled=False,
        enabled_editable=True,
        sound=beep,
        sound_editable=True,
    )
    editor = AlarmEditor(item, sounds=(beep, bells))
    try:
        assert editor.selected_sound() is None and editor.selected_enabled() is None
        find_widget(editor, AppComboBox, "alarmSound").setCurrentIndex(1)
        assert editor.selected_sound() == bells
        assert editor.selected_enabled() is False
        find_widget(editor, QCheckBox, "alarmEnabled").setChecked(True)
        assert editor.selected_enabled() is True
    finally:
        editor.close()


def test_playlist_sound_is_labeled_and_keeps_native_position() -> None:
    playlist = AlarmSound(AlarmSound.Kind.PLAYLIST, "Morning", 99, 7)
    item = AlarmItem(
        0,
        "Alarm",
        PlainDateTime(2027, 1, 1),
        0,
        True,
        enabled=False,
        enabled_editable=True,
        sound_editable=True,
    )
    editor = AlarmEditor(item, sounds=(playlist,))
    try:
        choices = find_widget(editor, AppComboBox, "alarmSound")
        assert choices.itemText(1) == "Playlist: Morning"
        choices.setCurrentIndex(1)
        assert editor.selected_sound() == playlist
        assert editor.selected_enabled() is False
    finally:
        editor.close()


def test_sound_selection_exposes_native_enable_when_old_kind_is_unknown() -> None:
    beep = AlarmSound(AlarmSound.Kind.BEEP, "Beep", playlist_index=-1)
    editor = AlarmEditor(
        AlarmItem(
            0, "Clock", PlainDateTime(2027, 1, 1), None, True, sound_editable=True
        ),
        sounds=(beep,),
    )
    try:
        checkbox = find_widget(editor, QCheckBox, "alarmEnabled")
        choices = find_widget(editor, AppComboBox, "alarmSound")
        assert checkbox.checkState() is Qt.CheckState.PartiallyChecked
        assert not checkbox.isEnabled()
        choices.setCurrentIndex(1)
        assert checkbox.isChecked() and checkbox.isEnabled()
        assert editor.selected_enabled() is True
        checkbox.setChecked(False)
        assert editor.selected_enabled() is False
        choices.setCurrentIndex(0)
        assert editor.selected_enabled() is None
        assert checkbox.checkState() is Qt.CheckState.PartiallyChecked
    finally:
        editor.close()


@pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS])
def test_styled_editor_keeps_time_and_following_fields_separate(
    tokens: ThemeTokens,
) -> None:
    original_stylesheet = APPLICATION.styleSheet()
    APPLICATION.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    editor = AlarmEditor(
        AlarmItem(
            0,
            "Alarm",
            PlainDateTime(2027, 2, 3, 8),
            0,
            True,
            repeat_editable=True,
            enabled=True,
            enabled_editable=True,
            label_index=3,
            label_editable=True,
        )
    )
    try:
        editor.show()
        APPLICATION.processEvents()
        fields = (
            find_widget(editor, QTimeEdit, "alarmTime"),
            find_widget(editor, QDateEdit, "alarmDate"),
            find_widget(editor, AppComboBox, "alarmRepeat"),
            find_widget(editor, AppComboBox, "alarmLabel"),
        )
        for previous, current in pairwise(fields):
            label = next(
                label
                for label in editor.findChildren(QLabel)
                if label.buddy() is current
            )
            assert label.geometry().top() > previous.geometry().bottom()
        save = find_widget(editor, QPushButton, "alarmEditorSave")
        assert save.isVisible() and editor.rect().contains(save.geometry())
        fields[0].setFocus()
        fields[0].setCurrentSectionIndex(fields[0].sectionCount() - 1)
        QTest.keyClick(fields[0], Qt.Key.Key_Tab)
        assert editor.focusWidget() is fields[1]
    finally:
        editor.close()
        APPLICATION.setStyleSheet(original_stylesheet)
        APPLICATION.processEvents()


def test_create_alarm_exposes_native_fields_and_submits_only_on_save() -> None:
    controller = ExtrasTestController(
        ExtrasCatalog(support=SUPPORT, can_create_alarm=True)
    )
    page = AlarmsPage(controller)
    try:
        page.show()
        find_widget(page, QPushButton, "alarmNew").click()
        editor = page.findChild(AlarmEditor)
        assert editor is not None and editor.windowTitle() == "New alarm"
        assert not controller.created_alarms
        find_widget(editor, QDateEdit, "alarmDate").setDate(QDate(2027, 2, 3))
        find_widget(editor, QTimeEdit, "alarmTime").setTime(QTime(6, 45))
        find_widget(editor, AppComboBox, "alarmRepeat").setCurrentIndex(2)
        labels = find_widget(editor, AppComboBox, "alarmLabel")
        assert labels.count() == 23
        labels.setCurrentIndex(0)
        find_widget(editor, QCheckBox, "alarmEnabled").setChecked(False)
        find_widget(editor, QPushButton, "alarmEditorSave").click()
        assert controller.created_alarms == [
            (PlainDateTime(2027, 2, 3, 6, 45), 2, False, 0)
        ]
    finally:
        page.close()
        APPLICATION.processEvents()


def test_new_alarm_dialog_expires_when_device_changes() -> None:
    controller = ExtrasTestController(
        ExtrasCatalog(support=SUPPORT, can_create_alarm=True)
    )
    page = AlarmsPage(controller)
    try:
        find_widget(page, QPushButton, "alarmNew").click()
        editor = page.findChild(AlarmEditor)
        assert editor is not None
        controller.current = None
        controller.changed.emit()
        assert not editor.isVisible() and not controller.created_alarms
    finally:
        page.close()
        APPLICATION.processEvents()


def test_edit_preserves_unknown_label_until_explicitly_replaced() -> None:
    item = AlarmItem(
        0,
        "Alarm",
        PlainDateTime(2027, 2, 3, 8),
        1,
        True,
        repeat_editable=True,
        enabled=False,
        enabled_editable=True,
        label_index=900,
        label_editable=True,
    )
    editor = AlarmEditor(item)
    try:
        assert editor.selected_label() is None and editor.selected_enabled() is None
        find_widget(editor, AppComboBox, "alarmLabel").setCurrentIndex(15)
        find_widget(editor, QCheckBox, "alarmEnabled").setChecked(True)
        assert editor.selected_label() == 15 and editor.selected_enabled() is True
        editor.set_writable(False)
        assert not find_widget(editor, QPushButton, "alarmEditorSave").isEnabled()
    finally:
        editor.close()


def test_remove_requires_current_catalog_after_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = AlarmItem(0, "Alarm", PlainDateTime(2027, 2, 3, 8), 1, True)
    controller = ExtrasTestController(
        ExtrasCatalog(alarms=(item,), support=SUPPORT, can_create_alarm=True)
    )
    page = AlarmsPage(controller)
    try:

        def confirm_removal(*args: object) -> QMessageBox.StandardButton:
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", confirm_removal)
        find_widget(page, QPushButton, "alarmRemove").click()
        assert controller.removed_alarms == [item]
        controller.removed_alarms.clear()

        def change_device(*args: object) -> QMessageBox.StandardButton:
            controller.current = None
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", change_device)
        find_widget(page, QPushButton, "alarmRemove").click()
        assert not controller.removed_alarms
    finally:
        page.close()


def test_touch_nano_shows_saved_timer_without_alarm_authoring() -> None:
    controller = ExtrasTestController(
        ExtrasCatalog(
            support=ExtrasSupport(alarm_format=AlarmFormat.TIMER),
            timer=CountdownTimerSnapshot(
                saved_hours=1,
                saved_minutes=15,
                sleep_ipod=True,
                deadline=PlainDateTime(2026, 11, 13, 22, 30),
            ),
        )
    )
    assert controller.current is not None
    profile = next(
        p
        for p in DEFAULT_DEVICE_REGISTRY.profiles
        if (p.family, p.generation) == ("iPod Nano", "6th Gen")
    )
    controller.current = replace(controller.current, profile=profile)
    page = AlarmsPage(controller)
    try:
        tabs = find_widget(page, QTabWidget, "alarmsTabs")
        assert not tabs.isTabVisible(0) and tabs.currentIndex() == 1
        assert find_widget(page, QLabel, "timerSavedDuration").text() == "1 h 15 min"
        text = find_widget(page, QLabel, "sleepTimerInstructions").text()
        assert "Sleep iPod" in text and "whether the timer is running" in text
        assert not find_widget(page, QPushButton, "alarmNew").isEnabled()
    finally:
        page.close()
