"""Time inputs share AM/PM presentation without changing stored civil values."""

import pytest
from PySide6.QtCore import QEvent, QLocale, Qt, QTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QTimeEdit, QVBoxLayout, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from whenever import Time

from iOpenPod.app.models.extras import AlarmItem
from iOpenPod.GUI.pages.alarms_page import AlarmEditor
from iOpenPod.GUI.pages.calendar_page import CalendarEditor
from iOpenPod.GUI.widgets.app_time_edit import AppTimeEdit
from iOpenPod.GUI.widgets.metadata_date_edit import MetadataDateEdit
from iPodDB.calendar import CalendarEntryKind


@pytest.mark.parametrize(
    "time,text",
    [
        (QTime(0, 0, 7), "12:00:07 AM"),
        (QTime(9, 15, 42), "9:15:42 AM"),
        (QTime(12, 0, 7), "12:00:07 PM"),
        (QTime(23, 59, 59), "11:59:59 PM"),
    ],
)
def test_time_display_keeps_noon_midnight_and_seconds(time: QTime, text: str) -> None:
    field = AppTimeEdit()
    try:
        field.setLocale(QLocale("en_US"))
        field.setTime(time)
        assert field.text() == text
        assert field.time() == time
        assert field.buttonSymbols() is QAbstractSpinBox.ButtonSymbols.NoButtons
    finally:
        field.close()


def test_am_pm_can_be_changed_using_the_keyboard_without_spinner_buttons() -> None:
    host = QWidget()
    field = AppTimeEdit(host)
    QVBoxLayout(host).addWidget(field)
    field.setTime(QTime(0, 15, 42))
    host.show()
    APPLICATION.processEvents()
    try:
        field.setFocus()
        field.setSelectedSection(QTimeEdit.Section.AmPmSection)
        QTest.keyClick(field, Qt.Key.Key_Up)
        assert field.time() == QTime(12, 15, 42)
        QTest.keyClick(field, Qt.Key.Key_Down)
        assert field.time() == QTime(0, 15, 42)
    finally:
        host.close()


@pytest.mark.parametrize("locale", ["en_US", "de_DE", "es_ES"])
def test_all_editors_use_shared_time_fields_after_locale_and_language_changes(
    locale: str,
) -> None:
    host = QWidget()
    owners = (
        CalendarEditor(CalendarEntryKind.EVENT, None, host),
        CalendarEditor(CalendarEntryKind.TODO, None, host),
        AlarmEditor(AlarmItem(0, "Alarm", Time(15, 24, 7), None, True), host),
        MetadataDateEdit(1_700_001_234, False, host),
    )
    try:
        for owner in owners:
            fields = owner.findChildren(QTimeEdit)
            assert fields
            original_values = tuple(field.time() for field in fields)
            owner.setLocale(QLocale(locale))
            APPLICATION.sendEvent(owner, QEvent(QEvent.Type.LanguageChange))
            for field, value in zip(fields, original_values, strict=True):
                assert isinstance(field, AppTimeEdit)
                assert field.property("themedTimeInput") is True
                assert field.buttonSymbols() is QAbstractSpinBox.ButtonSymbols.NoButtons
                assert field.displayFormat() == (
                    "h:mm AP" if isinstance(owner, AlarmEditor) else "h:mm:ss AP"
                )
                assert field.time() == value
    finally:
        for owner in owners:
            owner.close()
        host.close()
