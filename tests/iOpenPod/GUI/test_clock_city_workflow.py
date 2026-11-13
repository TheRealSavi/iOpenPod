"""City search, native fields, explicit creation and stale-dialog behavior."""

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QTimeEdit, QTreeWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.extras_test_support import ExtrasTestController, find_widget
from whenever import Time

from device_registry import AlarmFormat, ExtrasSupport
from iOpenPod.app.models.extras import (
    AlarmItem,
    AlarmSound,
    CreateClockAlarm,
    ExtrasCatalog,
)
from iOpenPod.GUI.pages.alarms_page import AlarmEditor, AlarmsPage
from iOpenPod.GUI.widgets.clock_city_picker import ClockCityPicker
from iPodDB.alarms import CLOCK_CITIES, ClockCity

BEEP = AlarmSound(AlarmSound.Kind.BEEP, "Beep", playlist_index=-1)
CATALOG = ExtrasCatalog(
    support=ExtrasSupport(alarm_format=AlarmFormat.CLOCK, alarm_write=True),
    can_create_alarm=True,
    clock_cities=CLOCK_CITIES,
    alarm_sounds=(BEEP,),
)


class CityController(ExtrasTestController):
    def __init__(self) -> None:
        super().__init__(CATALOG)
        self.cities: list[CreateClockAlarm] = []

    def create_clock_alarm(
        self,
        city: ClockCity,
        time: Time,
        *,
        daylight_saving: bool = False,
        enabled: bool = False,
        sound: AlarmSound | None = None,
    ) -> bool:
        self.cities.append(
            CreateClockAlarm(city, time, daylight_saving, enabled, sound)
        )
        return True


def test_city_search_requires_known_choice_and_submits_complete_alarm() -> None:
    controller = CityController()
    page = AlarmsPage(controller)
    try:
        page.show()
        find_widget(page, QPushButton, "alarmNew").click()
        editor = page.findChild(AlarmEditor)
        assert editor is not None and editor.windowTitle() == "Add city"
        picker = find_widget(editor, ClockCityPicker, "alarmCity")
        assert picker.count() == 204
        picker.setEditText("Atlantis")
        find_widget(editor, QPushButton, "alarmEditorSave").click()
        assert not controller.cities and editor.isVisible()
        assert (
            find_widget(editor, QLabel, "alarmEditorError").text()
            == "Choose a city from the list."
        )
        picker.setEditText("Tokyo")
        find_widget(editor, QTimeEdit, "alarmTime").setTime(QTime(7, 15))
        find_widget(editor, QCheckBox, "alarmDaylightSaving").setChecked(True)
        find_widget(editor, QCheckBox, "alarmEnabled").setChecked(True)
        find_widget(editor, QPushButton, "alarmEditorSave").click()
        (created,) = controller.cities
        assert created.city.name == "Tokyo" and created.time == Time(7, 15)
        assert created.daylight_saving and created.enabled and created.sound == BEEP
    finally:
        page.close()
        APPLICATION.processEvents()


def test_new_city_cancellation_and_device_change_never_submit() -> None:
    controller = CityController()
    page = AlarmsPage(controller)
    try:
        find_widget(page, QPushButton, "alarmNew").click()
        editor = page.findChild(AlarmEditor)
        assert editor is not None
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        assert not controller.cities
        APPLICATION.processEvents()
        find_widget(page, QPushButton, "alarmNew").click()
        editor = next(
            dialog for dialog in page.findChildren(AlarmEditor) if dialog.isVisible()
        )
        controller.current = None
        controller.changed.emit()
        assert not editor.isVisible() and not controller.cities
    finally:
        page.close()
        APPLICATION.processEvents()


def test_city_completion_can_be_selected_with_keyboard() -> None:
    picker = ClockCityPicker(CLOCK_CITIES)
    try:
        picker.show()
        picker.setFocus()
        APPLICATION.processEvents()
        line = picker.lineEdit()
        assert line is not None
        QTest.keyClicks(line, "tok")
        APPLICATION.processEvents()
        completer = picker.completer()
        assert completer is not None and completer.completionCount() >= 1
        popup = completer.popup()
        assert popup is not None
        QTest.keyClick(popup, Qt.Key.Key_Down)
        QTest.keyClick(popup, Qt.Key.Key_Return)
        APPLICATION.processEvents()
        selected = picker.selected_city()
        assert selected is not None and selected.name == "Tokyo"
    finally:
        picker.close()
        picker.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_city_label_and_manual_dst_edit_keep_the_original_city() -> None:
    city = next(city for city in CLOCK_CITIES if city.name == "Dallas")
    item = AlarmItem(
        0,
        city.name,
        Time(8),
        None,
        True,
        clock_city=city,
        daylight_saving=True,
        daylight_saving_editable=True,
    )
    controller = ExtrasTestController(
        ExtrasCatalog(
            alarms=(item,), support=CATALOG.support, clock_cities=CLOCK_CITIES
        )
    )
    page = AlarmsPage(controller)
    editor = AlarmEditor(item, cities=CLOCK_CITIES)
    try:
        row = find_widget(page, QTreeWidget, "alarmsList").topLevelItem(0)
        assert row is not None and row.text(0) == "Dallas"
        assert (
            editor.selected_city() == city and editor.selected_daylight_saving() is None
        )
        assert find_widget(editor, ClockCityPicker, "alarmCity").isHidden()
        find_widget(editor, QCheckBox, "alarmDaylightSaving").setChecked(False)
        assert editor.selected_daylight_saving() is False
    finally:
        editor.close()
        page.close()
