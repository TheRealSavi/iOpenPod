"""Extras editors preserve native civil values and selected-device authority."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import (
    QDate,
    QLocale,
    QPoint,
    Qt,
    QTime,
    QTimer,
    QTranslator,
)
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QTabWidget,
    QTimeEdit,
    QToolButton,
    QTreeWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.GUI.extras_test_support import (
    ExtrasTestController,
    find_widget,
    make_active_ipod,
)
from whenever import Date, Instant, PlainDateTime, Time

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    AlarmFormat,
    ExtrasSupport,
    FeatureSupport,
)
from iOpenPod.app import developer_flags
from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.extras import (
    AlarmItem,
    CalendarGroup,
    CalendarItem,
    ExtrasCatalog,
)
from iOpenPod.GUI.dialogs.calendar_picker import CalendarPickerDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId, page_supported
from iOpenPod.GUI.pages.alarms_page import AlarmEditor, AlarmsPage
from iOpenPod.GUI.pages.calendar_page import CalendarEditor, CalendarPage
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.calendar_month import MonthGrid
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.hover_dropdown import HoverDropdown
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iPodDB.calendar import (
    UNCHANGED,
    CalendarDayRule,
    CalendarEntryChanges,
    CalendarEntryDraft,
    CalendarEntryKind,
    CalendarFrequency,
    CalendarRecurrenceRule,
    CalendarReminderDraft,
    CalendarTodoStatus,
    CalendarWeekday,
    parse_calendar,
    update_entry,
)

pytestmark = pytest.mark.usefixtures("enable_extras_pages")


def _open_entry_menu(
    tree: QTreeWidget, *, row_index: int = 0, keyboard: bool = False
) -> QMenu:
    row = tree.currentItem() if keyboard else tree.topLevelItem(row_index)
    assert row is not None
    point = QPoint() if keyboard else tree.visualItemRect(row).center()
    APPLICATION.sendEvent(
        tree.viewport(),
        QContextMenuEvent(
            QContextMenuEvent.Reason.Keyboard
            if keyboard
            else QContextMenuEvent.Reason.Mouse,
            point,
            tree.viewport().mapToGlobal(point),
        ),
    )
    return next(
        menu
        for menu in tree.window().findChildren(QMenu, "calendarEntryMenu")
        if menu.isVisible()
    )


def _entry_menu(
    tree: QTreeWidget, choose: str | None = None, *, keyboard: bool = False
) -> dict[str, bool]:
    menu = _open_entry_menu(tree, keyboard=keyboard)
    actions = {
        action.text(): action.isEnabled()
        for action in menu.actions()
        if not action.isSeparator()
    }
    if choose is not None:
        action = next(action for action in menu.actions() if action.text() == choose)
        assert action.isEnabled()
        QTest.mouseClick(
            menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center()
        )
    menu.close()
    return actions


def _calendar(properties: str, *, kind: str = "VEVENT") -> CalendarItem:
    data = (
        f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:{kind}\r\nSUMMARY:Original\r\nUID:test\r\n"
        + properties
        + f"\r\nEND:{kind}\r\nEND:VCALENDAR\r\n"
    ).encode()
    return CalendarItem("calendar.ics", parse_calendar(data).entries[0])


@pytest.mark.parametrize("available", [True, False])
def test_per_city_alarm_offers_saved_time_editor(
    available: bool,
) -> None:
    item = AlarmItem(0, "Clock 1", Time(7, 30), None, True, enabled=False)
    controller = ExtrasTestController(
        ExtrasCatalog(
            alarms=(item,) if available else (),
            support=ExtrasSupport(
                calendar_write=True, alarm_format=AlarmFormat.CLOCK, alarm_write=True
            ),
        )
    )
    active = make_active_ipod()
    profile = next(
        p
        for p in DEFAULT_DEVICE_REGISTRY.profiles
        if (p.family, p.generation) == ("iPod", "5th Gen")
    )
    controller.current = replace(
        active,
        candidate=replace(active.candidate, profile=profile),
        profile=profile,
        firmware_version="1.3",
    )
    page = AlarmsPage(controller)
    try:
        page.show()
        tree = find_widget(page, QTreeWidget, "alarmsList")
        row = tree.topLevelItem(0)
        if available:
            assert row is not None and row.text(0) == "Clock 1"
            assert row.text(3) == "Disabled"
            tree.setCurrentItem(row)
            tree.itemActivated.emit(row, 0)
        else:
            assert row is None
            empty = find_widget(page, QLabel, "alarmsEmpty").text()
            assert "No saved alarms" in empty
        assert find_widget(page, QPushButton, "alarmEdit").isEnabled() is available
        assert tree.accessibleName() == "Cities & alarms"
        editor = page.findChild(AlarmEditor)
        if available:
            assert editor is not None
            assert editor.selected_time() == Time(7, 30)
            assert find_widget(editor, QCheckBox, "alarmEnabled").isHidden()
            editor.reject()
        else:
            assert editor is None
        assert not controller.alarm_edits
    finally:
        page.close()
        APPLICATION.processEvents()


@pytest.mark.parametrize(
    "properties",
    [
        "DTSTART;TZID=America/New_York:20261101T013000\r\nRRULE:FREQ=DAILY",
        "DTSTART:20261399T256199",
        "DTSTART:20261101T013000\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-P1W\r\nEND:VALARM",
    ],
)
def test_text_edit_preserves_unresolved_dates_and_recurrence(properties: str) -> None:
    item = _calendar(properties)
    editor = CalendarEditor(CalendarEntryKind.EVENT, item)
    try:
        find_widget(editor, QLineEdit, "calendarSummary").setText("Changed")
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryChanges)
        assert edit.summary == "Changed"
        assert edit.start is UNCHANGED and edit.end is UNCHANGED
        assert edit.due is UNCHANGED and edit.completed_at is UNCHANGED
        assert not find_widget(editor, QDateEdit, "calendarStartDate").isEnabled()
    finally:
        editor.close()


def test_utc_calendar_editor_preserves_instant_without_host_conversion() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT, _calendar("DTSTART:19691231T233000Z")
    )
    try:
        assert find_widget(editor, QDateEdit, "calendarStartDate").date() == QDate(
            1969, 12, 31
        )
        find_widget(editor, QTimeEdit, "calendarStartTime").setTime(QTime(23, 45))
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryChanges)
        assert edit.start == Instant.from_utc(1969, 12, 31, 23, 45)
    finally:
        editor.close()


def test_new_all_day_event_uses_exclusive_following_day_end() -> None:
    editor = CalendarEditor(CalendarEntryKind.EVENT, None)
    try:
        find_widget(editor, QLineEdit, "calendarSummary").setText("Day off")
        find_widget(editor, QDateEdit, "calendarStartDate").setDate(QDate(2026, 11, 1))
        find_widget(editor, QDateEdit, "calendarEndDate").setDate(QDate(2026, 11, 1))
        find_widget(editor, QCheckBox, "calendarAllDay").setChecked(True)
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryDraft)
        assert edit.start == Date(2026, 11, 1)
        assert edit.end == Date(2026, 11, 2)
    finally:
        editor.close()


def test_todo_completion_preserves_existing_due_date() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.TODO,
        _calendar("DUE;TZID=Unknown/Zone:20261101T013000", kind="VTODO"),
    )
    try:
        find_widget(editor, AppComboBox, "calendarTodoStatus").setCurrentIndex(2)
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryChanges)
        assert edit.todo_status is CalendarTodoStatus.COMPLETED
        assert edit.completed_at is UNCHANGED
        assert edit.due is UNCHANGED
    finally:
        editor.close()


def test_alarm_editor_keeps_civil_gap_time_and_unknown_repeat() -> None:
    item = AlarmItem(
        0, "Alarm", PlainDateTime(2026, 3, 8, 2, 30), 42, True, repeat_editable=True
    )
    editor = AlarmEditor(item)
    try:
        assert editor.selected_time() == item.time
        assert editor.selected_repeat() is None
        find_widget(editor, QTimeEdit, "alarmTime").setTime(QTime(2, 45))
        assert editor.selected_time() == PlainDateTime(2026, 3, 8, 2, 45)
        assert editor.selected_repeat() is None
        combo = find_widget(editor, AppComboBox, "alarmRepeat")
        combo.setCurrentIndex(combo.findData(2))
        assert editor.selected_repeat() == 2
    finally:
        editor.close()


def test_preferences_alarm_has_minute_only_editor_and_no_repeat_edit() -> None:
    editor = AlarmEditor(AlarmItem(0, "Clock alarm", Time(0), None, True))
    try:
        assert find_widget(editor, QDateEdit, "alarmDate").isHidden()
        assert find_widget(editor, AppComboBox, "alarmRepeat").isHidden()
        assert editor.selected_time() == Time(0)
        assert editor.selected_repeat() is None
    finally:
        editor.close()


@pytest.mark.parametrize("end_day", [1, 2])
def test_invalid_new_calendar_range_keeps_the_draft_open(end_day: int) -> None:
    editor = CalendarEditor(CalendarEntryKind.EVENT, None)
    try:
        editor.show()
        find_widget(editor, QLineEdit, "calendarSummary").setText("Retain my draft")
        find_widget(editor, QDateEdit, "calendarStartDate").setDate(QDate(2026, 11, 2))
        find_widget(editor, QDateEdit, "calendarEndDate").setDate(
            QDate(2026, 11, end_day)
        )
        find_widget(editor, QTimeEdit, "calendarEndTime").setTime(QTime(9, 0))
        find_widget(editor, QPushButton, "calendarEditorSave").click()
        assert editor.isVisible()
        assert "later" in find_widget(editor, QLabel, "calendarEditorError").text()
        assert editor.selected_edit().summary == "Retain my draft"
    finally:
        editor.close()


@pytest.mark.parametrize("suffix", ["", "Z"])
def test_explicit_equal_calendar_end_rejected_but_imported_equality_preserved(
    suffix: str,
) -> None:
    valid = _calendar(
        f"DTSTART:20261101T090000{suffix}\r\nDTEND:20261101T100000{suffix}"
    )
    editor = CalendarEditor(CalendarEntryKind.EVENT, valid)
    try:
        editor.show()
        find_widget(editor, QTimeEdit, "calendarEndTime").setTime(QTime(9, 0))
        find_widget(editor, QPushButton, "calendarEditorSave").click()
        assert editor.isVisible()
        assert "later" in find_widget(editor, QLabel, "calendarEditorError").text()
    finally:
        editor.close()
    equal = _calendar(
        f"DTSTART:20261101T090000{suffix}\r\nDTEND:20261101T090000{suffix}"
    )
    retained = CalendarEditor(CalendarEntryKind.EVENT, equal)
    try:
        retained.show()
        find_widget(retained, QLineEdit, "calendarSummary").setText("Text edit")
        find_widget(retained, QPushButton, "calendarEditorSave").click()
        assert not retained.isVisible()
        change = retained.selected_edit()
        assert isinstance(change, CalendarEntryChanges)
        assert change.start is UNCHANGED and change.end is UNCHANGED
    finally:
        retained.close()


def test_new_alarm_sentinel_is_rejected_but_retained_sentinel_can_stay() -> None:
    sentinel = PlainDateTime(2106, 2, 7, 6, 28, 15)
    editor = AlarmEditor(
        AlarmItem(0, "Alarm", PlainDateTime(2106, 2, 7, 6, 28, 14), 1, True)
    )
    try:
        editor.show()
        find_widget(editor, QTimeEdit, "alarmTime").setTime(QTime(6, 28, 15))
        find_widget(editor, QPushButton, "alarmEditorSave").click()
        assert editor.isVisible()
        assert "06:28:14" in find_widget(editor, QLabel, "alarmEditorError").text()
    finally:
        editor.close()
    original = AlarmEditor(AlarmItem(0, "Alarm", sentinel, 1, True))
    try:
        original.show()
        find_widget(original, QPushButton, "alarmEditorSave").click()
        assert not original.isVisible()
        assert original.selected_time() == sentinel
    finally:
        original.close()


@pytest.mark.parametrize(
    "page_type,tree_name,button_name,editor_type",
    [
        (CalendarPage, "calendarEvents", None, CalendarEditor),
        (AlarmsPage, "alarmsList", "alarmEdit", AlarmEditor),
    ],
)
@pytest.mark.parametrize("activate_item", [False, True])
def test_device_switch_closes_captured_editor(
    page_type: type[CalendarPage] | type[AlarmsPage],
    tree_name: str,
    button_name: str | None,
    editor_type: type[CalendarEditor] | type[AlarmEditor],
    activate_item: bool,
) -> None:
    controller = ExtrasTestController(
        ExtrasCatalog(
            calendar=(_calendar("DTSTART:20261101T013000"),),
            alarms=(AlarmItem(0, "Alarm", Time(7), None, True),),
            support=ExtrasSupport(calendar_write=True, alarm_write=True),
        )
    )
    page = page_type(controller)
    try:
        if isinstance(page, CalendarPage):
            find_widget(page, MonthGrid, "calendarMonthGrid").setSelectedDate(
                QDate(2026, 11, 1)
            )
        page.show()
        tree = find_widget(page, QTreeWidget, tree_name)
        first = tree.topLevelItem(0)
        assert first is not None
        tree.setCurrentItem(first)
        if activate_item:
            tree.itemActivated.emit(first, 0)
        elif button_name is None:
            assert _entry_menu(tree, "Edit")["Edit"]
        else:
            find_widget(page, QPushButton, button_name).click()
        editor = page.findChild(editor_type)
        assert editor is not None and editor.isVisible()
        controller.current = (
            make_active_ipod()
        )  # same model, different captured connection
        controller.changed.emit()
        assert not editor.isVisible()
        assert not controller.calendar_edits and not controller.alarm_edits
    finally:
        page.close()
        APPLICATION.processEvents()


def test_calendar_busy_and_errors_remain_page_local() -> None:
    controller = ExtrasTestController(
        ExtrasCatalog(support=ExtrasSupport(calendar_write=True))
    )
    page = CalendarPage(controller)
    try:
        controller.working = True
        controller.error = "<b>Calendar unavailable</b>"
        controller.changed.emit()
        assert not find_widget(page, QPushButton, "calendarNew").isEnabled()
        status = find_widget(page, QLabel, "calendarStatus")
        assert status.text() == controller.error
        assert status.textFormat() is Qt.TextFormat.PlainText
        controller.working = False
        controller.changed.emit()
        tabs = find_widget(page, QTabWidget, "calendarTabs")
        tabs.setCurrentIndex(1)
        assert "To Dos" in find_widget(page, QLabel, "calendarEmpty").text()
        controller.current = None
        controller.changed.emit()
        assert not find_widget(page, QPushButton, "calendarImport").isEnabled()
    finally:
        page.close()


def test_alarms_page_shows_content_without_sleep_timer_or_tabs() -> None:
    page = AlarmsPage(ExtrasTestController())
    try:
        page.show()
        assert page.findChild(QTabWidget) is None
        assert page.findChild(QLabel, "sleepTimerInstructions") is None
        assert page.findChild(QPushButton, "alarmsRefresh") is None
        assert not any(
            label.text() == "Saved alarms" or "Times follow" in label.text()
            for label in page.findChildren(QLabel)
        )
        assert find_widget(page, QLabel, "alarmsEmpty").isVisible()
        assert find_widget(page, QPushButton, "alarmEdit").isVisible()
        assert page.findChild(QPushButton, "timerEdit") is None
    finally:
        page.close()


@pytest.mark.parametrize(
    "language,title,alarm_label,cancel",
    [
        ("de", "Neues Ereignis", "Wecker 1", "Abbrechen"),
        ("es", "Nuevo evento", "Alarma 1", "Cancelar"),
    ],
)
def test_extras_retranslate_without_resetting_editor_values(
    language: str, title: str, alarm_label: str, cancel: str
) -> None:
    translator = QTranslator()
    catalog = (
        Path(__file__).resolve().parents[3]
        / "src/iOpenPod/GUI/presentation/i18n/translations"
        / f"iopenpod_{language}.qm"
    )
    assert translator.load(str(catalog))
    controller = ExtrasTestController(
        ExtrasCatalog(
            alarms=(
                AlarmItem(
                    0, source_text("Alarm {number}", number="1"), Time(7), None, True
                ),
            )
        )
    )
    page = AlarmsPage(controller)
    editor = CalendarEditor(CalendarEntryKind.EVENT, None)
    try:
        find_widget(editor, QLineEdit, "calendarSummary").setText(
            "User's unchanged title"
        )
        find_widget(editor, QTimeEdit, "calendarStartTime").setTime(QTime(8, 45))
        before = editor.selected_edit()
        assert APPLICATION.installTranslator(translator)
        APPLICATION.processEvents()
        assert editor.windowTitle() == title
        assert editor.selected_edit() == before
        assert cancel in [button.text() for button in editor.findChildren(QPushButton)]
        row = find_widget(page, QTreeWidget, "alarmsList").topLevelItem(0)
        assert row is not None and row.text(0) == alarm_label
    finally:
        APPLICATION.removeTranslator(translator)
        editor.close()
        page.close()


@pytest.mark.parametrize("firmware", ["", "9.9.9"])
def test_calendar_and_alarm_read_only_messages_follow_their_own_support(
    firmware: str,
) -> None:
    controller = ExtrasTestController(ExtrasCatalog(support=ExtrasSupport()))
    controller.current = replace(make_active_ipod(), firmware_version=firmware)
    calendar, alarms = CalendarPage(controller), AlarmsPage(controller)
    try:
        calendar_status = find_widget(calendar, QLabel, "calendarStatus")
        alarm_status = find_widget(alarms, QLabel, "alarmsStatus")
        for label in (calendar_status, alarm_status):
            assert controller.current.profile.display_name in label.text()
            assert label.textFormat() is Qt.TextFormat.PlainText
        if firmware:
            assert "Firmware 9.9.9" in alarm_status.text()
        else:
            assert "firmware version could not be confirmed" in alarm_status.text()
        assert "Calendar editing is unavailable" in calendar_status.text()
        assert "editing is unavailable" in alarm_status.text()
        assert not find_widget(calendar, QPushButton, "calendarNew").isEnabled()
        assert not find_widget(calendar, QPushButton, "calendarImport").isEnabled()
        assert not find_widget(alarms, QPushButton, "alarmEdit").isEnabled()
        assert "Create" not in find_widget(calendar, QLabel, "calendarEmpty").text()
        empty = find_widget(alarms, QLabel, "alarmsEmpty").text()
        assert "cannot be read" in empty
        assert "No saved alarms" not in empty
    finally:
        calendar.close()
        alarms.close()


@pytest.mark.parametrize("day,expected", [(1, 1), (2, 1), (3, 0)])
def test_calendar_day_agenda_respects_exclusive_all_day_end(
    day: int, expected: int
) -> None:
    item = _calendar("DTSTART;VALUE=DATE:20261101\r\nDTEND;VALUE=DATE:20261103")
    page = CalendarPage(ExtrasTestController(ExtrasCatalog(calendar=(item,))))
    try:
        find_widget(page, MonthGrid, "calendarMonthGrid").setSelectedDate(
            QDate(2026, 11, day)
        )
        assert (
            find_widget(page, QTreeWidget, "calendarEvents").topLevelItemCount()
            == expected
        )
    finally:
        page.close()


def test_calendar_all_events_retains_unknown_dates_and_does_not_expand_recurrence() -> (
    None
):
    recurring = _calendar(
        "DTSTART;TZID=Unknown/Zone:20261101T013000\r\nRRULE:FREQ=DAILY"
    )
    unknown = replace(_calendar("DTSTART:bad-date"), document_key="unknown")
    page = CalendarPage(
        ExtrasTestController(ExtrasCatalog(calendar=(recurring, unknown)))
    )
    try:
        grid = find_widget(page, MonthGrid, "calendarMonthGrid")
        tree = find_widget(page, QTreeWidget, "calendarEvents")
        grid.setSelectedDate(QDate(2026, 11, 1))
        assert tree.topLevelItemCount() == 1
        first = tree.topLevelItem(0)
        assert first is not None and "Unknown/Zone" in first.text(1)
        grid.setSelectedDate(QDate(2026, 11, 2))
        assert tree.topLevelItemCount() == 0
        find_widget(page, AppComboBox, "calendarScope").setCurrentIndex(1)
        assert tree.topLevelItemCount() == 2
        assert any(
            "bad-date" in row.text(1)
            for i in range(2)
            if (row := tree.topLevelItem(i)) is not None
        )
    finally:
        page.close()


def test_calendar_search_finds_other_dates_and_clear_restores_day_agenda() -> None:
    item = _calendar("DTSTART:20261225T090000\r\nLOCATION:Station")
    page = CalendarPage(ExtrasTestController(ExtrasCatalog(calendar=(item,))))
    try:
        grid = find_widget(page, MonthGrid, "calendarMonthGrid")
        grid.setSelectedDate(QDate(2026, 11, 7))
        tree = find_widget(page, QTreeWidget, "calendarEvents")
        search = find_widget(page, SearchField, "calendarSearch")
        assert tree.topLevelItemCount() == 0
        search.set_query("station")
        search.queryChanged.emit("station")
        assert tree.topLevelItemCount() == 1
        assert (
            find_widget(page, QLabel, "calendarAgendaTitle").text() == "Search results"
        )
        search.set_query("")
        search.queryChanged.emit("")
        assert tree.topLevelItemCount() == 0
        assert grid.selectedDate() == QDate(2026, 11, 7)
    finally:
        page.close()


def test_new_event_uses_selected_day_and_month_navigation_updates_agenda() -> None:
    controller = ExtrasTestController(
        ExtrasCatalog(support=ExtrasSupport(calendar_write=True))
    )
    page = CalendarPage(controller)
    try:
        grid = find_widget(page, MonthGrid, "calendarMonthGrid")
        grid.setSelectedDate(QDate(2026, 11, 7))
        find_widget(page, QToolButton, "calendarNextMonth").click()
        assert grid.selectedDate() == QDate(2026, 12, 1)
        find_widget(page, QPushButton, "calendarNew").click()
        editor = page.findChild(CalendarEditor)
        assert editor is not None
        assert editor.selected_edit().start == PlainDateTime(2026, 12, 1, 9)
        editor.reject()
        find_widget(page, QPushButton, "calendarToday").click()
        assert grid.selectedDate() == QDate.currentDate()
    finally:
        page.close()
        APPLICATION.processEvents()


@pytest.mark.parametrize("completed", [False, True])
def test_todo_completion_preserves_unknown_due_and_uses_explicit_controller_intent(
    completed: bool,
) -> None:
    item = _calendar("DUE:unknown", kind="VTODO")
    item = replace(item, entry=replace(item.entry, completed=completed))
    controller = ExtrasTestController(
        ExtrasCatalog(calendar=(item,), support=ExtrasSupport(calendar_write=True))
    )
    page = CalendarPage(controller)
    try:
        find_widget(page, QTabWidget, "calendarTabs").setCurrentIndex(1)
        tree = find_widget(page, QTreeWidget, "calendarTodos")
        action = "Mark incomplete" if completed else "Mark complete"
        assert _entry_menu(tree, action)[action]
        edit, existing = controller.calendar_edits[0]
        assert isinstance(edit, CalendarEntryChanges)
        assert existing is item
        assert edit.completed is not completed
        assert edit.due is UNCHANGED
        assert edit.completed_at is UNCHANGED
        controller.working = True
        controller.changed.emit()
        assert not _entry_menu(tree)[action]
    finally:
        page.close()


def test_calendar_keyboard_day_navigation_and_disconnect_clear_events() -> None:
    item = _calendar("DTSTART:20261101T090000")
    controller = ExtrasTestController(ExtrasCatalog(calendar=(item,)))
    page = CalendarPage(controller)
    try:
        page.resize(1000, 700)
        page.show()
        grid = find_widget(page, MonthGrid, "calendarMonthGrid")
        grid.setSelectedDate(QDate(2026, 11, 1))
        grid.setFocus()
        target = grid.focusProxy()
        assert target is not None
        QTest.keyClick(target, Qt.Key.Key_Right)
        assert grid.selectedDate() == QDate(2026, 11, 2)
        controller.current = None
        controller.view = ExtrasCatalog()
        controller.changed.emit()
        assert find_widget(page, QTreeWidget, "calendarEvents").topLevelItemCount() == 0
        assert not find_widget(page, QPushButton, "calendarNew").isEnabled()
    finally:
        page.close()


def test_calendar_weekday_header_stays_slim_when_the_date_grid_grows() -> None:
    grid = MonthGrid(today=QDate(2026, 11, 10))
    try:
        grid.resize(720, 340)
        grid.show()
        APPLICATION.processEvents()
        view = find_widget(grid, QTableView, "qt_calendar_calendarview")
        rows = view.verticalHeader()
        weekday_height = rows.sectionSize(0)
        week_height = rows.sectionSize(1)
        assert 0 < weekday_height < week_height

        grid.resize(1024, 720)
        grid.showNextMonth()
        APPLICATION.processEvents()
        assert rows.sectionSize(0) == weekday_height
        assert rows.sectionSize(1) > week_height
        assert rows.length() == view.viewport().height()
    finally:
        grid.close()


@pytest.mark.parametrize("switch_device", [False, True])
def test_calendar_menu_removes_the_clicked_series_with_confirmation(
    switch_device: bool,
) -> None:
    first = _calendar("DTSTART:20261101T080000")
    series = replace(
        _calendar(
            "DTSTART:20261101T090000\r\nDTEND:20261101T100000\r\nRRULE:FREQ=WEEKLY;COUNT=3"
        ),
        document_key="series.ics",
    )
    controller = ExtrasTestController(
        ExtrasCatalog(
            calendar=(first, series), support=ExtrasSupport(calendar_write=True)
        )
    )
    page = CalendarPage(controller)
    try:
        find_widget(page, MonthGrid, "calendarMonthGrid").setSelectedDate(
            QDate(2026, 11, 1)
        )
        page.resize(1000, 700)
        page.show()
        tree = find_widget(page, QTreeWidget, "calendarEvents")
        selected, clicked = tree.topLevelItem(0), tree.topLevelItem(1)
        assert selected is not None and clicked is not None
        tree.setCurrentItem(selected)
        confirmations: list[str] = []
        point = tree.viewport().rect().bottomRight() - QPoint(4, 4)
        APPLICATION.sendEvent(
            tree.viewport(),
            QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse,
                point,
                tree.viewport().mapToGlobal(point),
            ),
        )
        assert page.findChild(QMenu, "calendarEntryMenu") is None

        def confirm() -> None:
            question = APPLICATION.activeModalWidget()
            if isinstance(question, QMessageBox):
                confirmations.append(question.windowTitle())
                if question.standardButtons() & QMessageBox.StandardButton.Yes:
                    question.button(QMessageBox.StandardButton.Yes).click()
                else:
                    question.reject()

        menu = _open_entry_menu(tree, row_index=1)
        assert tree.currentItem() is clicked
        tree.setCurrentItem(selected)
        if switch_device:
            controller.current = make_active_ipod()
            controller.changed.emit()
        action = next(
            action for action in menu.actions() if action.text() == "Remove series"
        )
        QTimer.singleShot(0, confirm)
        QTest.mouseClick(
            menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center()
        )
        assert confirmations == (
            [] if switch_device else ["Remove entire repeating series?"]
        )
        assert controller.removed == ([] if switch_device else [series])
        assert page.findChild(QLabel, "calendarDetails") is None
        assert page.findChild(QPushButton, "calendarEdit") is None
        assert page.findChild(QPushButton, "calendarRemove") is None
    finally:
        page.close()


def test_extras_are_direct_sidebar_routes_and_a_compact_dropdown() -> None:
    active = make_active_ipod()
    sidebar, compact = Sidebar(), CompactTopBar(playlists=LibraryWorkspace())
    try:
        sidebar.set_active_ipod(active)
        compact.set_active_ipod(active)
        direct = {
            button.property("pageId"): button
            for button in sidebar.findChildren(QPushButton)
        }
        assert not direct[PageId.CALENDAR.value].isHidden()
        assert not direct[PageId.ALARMS.value].isHidden()
        extras = find_widget(compact, QPushButton, "compactExtras")
        assert not extras.isHidden()
        dropdown = find_widget(compact, HoverDropdown, "compactExtrasMenu")
        requests: list[str] = []
        compact.pageRequested.connect(requests.append)
        compact.resize(1400, 60)
        compact.show()
        extras.setFocus()
        QTest.keyClick(extras, Qt.Key.Key_Down)
        APPLICATION.processEvents()
        assert not requests
        actions = dropdown.actions()
        assert len(actions) == 3
        actions[0].trigger()
        actions[1].trigger()
        actions[2].trigger()
        assert requests == [
            PageId.CALENDAR.value,
            PageId.ALARMS.value,
            PageId.TONES.value,
        ]
        unknown = replace(
            active.profile,
            capabilities=replace(
                active.profile.capabilities,
                extras=replace(
                    active.profile.capabilities.extras,
                    calendar=FeatureSupport.UNKNOWN,
                    todos=FeatureSupport.UNKNOWN,
                    alarms=FeatureSupport.UNKNOWN,
                    sleep_timer=FeatureSupport.UNKNOWN,
                ),
            ),
        )
        assert not page_supported(PageId.CALENDAR, unknown)
        assert not page_supported(PageId.ALARMS, unknown)
        compact.set_active_ipod(None)
        assert extras.isHidden()
    finally:
        sidebar.close()
        compact.close()


def test_alarm_development_flag_leaves_calendar_navigation_and_route_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(developer_flags, "ENABLE_EXTRAS_PAGES", False)
    context = build_context()
    context.device_controller.finish_library_save(make_active_ipod())
    refreshes: list[bool] = []
    monkeypatch.setattr(
        context.extras_controller, "refresh", lambda: refreshes.append(True)
    )
    window = MainWindow(context, auto_discover=False)
    try:
        sidebar = window.findChild(Sidebar)
        compact = window.findChild(CompactTopBar)
        assert sidebar is not None and compact is not None
        assert not find_widget(compact, QPushButton, "compactExtras").isHidden()
        direct = {
            button.property("pageId"): button
            for button in sidebar.findChildren(QPushButton)
        }
        assert not direct[PageId.CALENDAR.value].isHidden()
        assert direct[PageId.ALARMS.value].isHidden()
        sidebar.pageRequested.emit(PageId.ALARMS.value)
        assert not refreshes
        sidebar.pageRequested.emit(PageId.CALENDAR.value)
        assert window.findChild(CalendarPage) is not None
        assert window.findChild(AlarmsPage) is None
        assert refreshes == [True]
    finally:
        window.close()
        context.shutdown()


def test_calendar_selector_includes_empty_groups_and_filters_entries() -> None:
    first = replace(
        _calendar("DTSTART:20261108T120000"),
        document_key="Work.ics",
        calendar_name="Work",
    )
    second = replace(
        _calendar("DTSTART:20261108T130000"),
        document_key="Personal.ics",
        calendar_name="Personal",
    )
    groups = (
        CalendarGroup("Work", ("Work.ics",), True),
        CalendarGroup("Personal", ("Personal.ics",), True),
        CalendarGroup("Empty", ("Empty.ics",), True),
    )
    controller = ExtrasTestController(
        ExtrasCatalog(
            calendar=(first, second),
            support=ExtrasSupport(calendar_write=True),
            calendars=groups,
        )
    )
    page = CalendarPage(controller)
    try:
        selector = find_widget(page, AppComboBox, "calendarSelector")
        scope = find_widget(page, AppComboBox, "calendarScope")
        scope.setCurrentIndex(1)
        events = find_widget(page, QTreeWidget, "calendarEvents")
        assert selector.count() == 4
        assert events.topLevelItemCount() == 2
        rename = find_widget(page, QPushButton, "calendarRename")
        assert rename.isHidden()
        selector.setCurrentIndex(1)
        assert not rename.isHidden()
        assert events.topLevelItemCount() == 1
        row = events.topLevelItem(0)
        assert row is not None
        assert row.data(0, Qt.ItemDataRole.UserRole) == (
            "Work.ics",
            0,
        )
        selector.setCurrentIndex(3)
        assert events.topLevelItemCount() == 0
        assert find_widget(page, QPushButton, "calendarRename").isEnabled()
        controller.working = True
        controller.changed.emit()
        assert rename.isHidden()
        controller.working = False
        controller.changed.emit()
        assert not rename.isHidden()
        selector.setCurrentIndex(0)
        assert rename.isHidden()
        controller.current = None
        controller.view = ExtrasCatalog()
        controller.changed.emit()
        assert selector.count() == 1
        assert not find_widget(page, QPushButton, "calendarRename").isEnabled()
        assert rename.isHidden()
    finally:
        page.close()


@pytest.mark.parametrize(
    "name,accepted", (("Imported", True), ("", True), ("Ignored", False))
)
def test_import_calendar_offers_a_name_before_publication(
    monkeypatch: pytest.MonkeyPatch, name: str, accepted: bool
) -> None:
    controller = ExtrasTestController(
        ExtrasCatalog(support=ExtrasSupport(calendar_write=True))
    )
    page = CalendarPage(controller)

    def open_file(*args: object) -> tuple[str, str]:
        return ("example.ics", "")

    def get_text(*args: object, **kwargs: object) -> tuple[str, bool]:
        return (name, accepted)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", open_file)
    monkeypatch.setattr(QInputDialog, "getText", get_text)
    try:
        find_widget(page, QPushButton, "calendarImport").click()
        assert controller.imports == (
            [("example.ics", name or None)] if accepted else []
        )
    finally:
        page.close()


def test_create_and_rename_calendar_use_the_selected_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = CalendarGroup("Work", ("Work.ics",), True)
    controller = ExtrasTestController(
        ExtrasCatalog(support=ExtrasSupport(calendar_write=True), calendars=(group,))
    )
    page = CalendarPage(controller)

    def get_text(*args: object, **kwargs: object) -> tuple[str, bool]:
        return ("Team", True)

    monkeypatch.setattr(QInputDialog, "getText", get_text)
    try:
        create = find_widget(page, QToolButton, "calendarCreate")
        assert not create.text() and not create.icon().isNull()
        assert create.accessibleName() == create.toolTip() == "New calendar…"
        assert page.findChild(QPushButton, "calendarRefresh") is None
        create.click()
        selector = find_widget(page, AppComboBox, "calendarSelector")
        selector.setCurrentIndex(1)
        find_widget(page, QPushButton, "calendarRename").click()
        assert controller.names == [(None, "Team"), (group, "Team")]
    finally:
        page.close()


def test_new_entry_retains_its_chosen_destination_while_editor_is_open() -> None:
    work = CalendarGroup("Work", ("Work.ics",), True)
    personal = CalendarGroup("Personal", ("Personal.ics",), True)
    controller = ExtrasTestController(
        ExtrasCatalog(
            support=ExtrasSupport(calendar_write=True), calendars=(work, personal)
        )
    )
    page = CalendarPage(controller)
    try:
        selector = find_widget(page, AppComboBox, "calendarSelector")
        selector.setCurrentIndex(1)
        find_widget(page, QPushButton, "calendarNew").click()
        editor = page.findChild(CalendarEditor)
        assert editor is not None
        selector.setCurrentIndex(2)
        editor.accept()
        assert controller.destinations == [work]
    finally:
        page.close()
        APPLICATION.processEvents()


def test_destination_picker_cannot_open_an_editor_for_a_new_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = CalendarGroup("Work", ("Work.ics",), True)
    controller = ExtrasTestController(
        ExtrasCatalog(support=ExtrasSupport(calendar_write=True), calendars=(work,))
    )
    page = CalendarPage(controller)

    def choose(picker: CalendarPickerDialog) -> int:
        controller.current = make_active_ipod()
        return picker.DialogCode.Accepted

    monkeypatch.setattr(CalendarPickerDialog, "exec", choose)
    try:
        find_widget(page, QPushButton, "calendarNew").click()
        assert page.findChild(CalendarEditor) is None
        assert not controller.calendar_edits
    finally:
        page.close()


def test_mini_recurring_occurrence_appears_on_future_day_but_edits_source_series() -> (
    None
):
    source = _calendar(
        "DTSTART:20261101T090000\r\nDTEND:20261101T100000\r\nRRULE:FREQ=WEEKLY;COUNT=3"
    )
    support = ExtrasSupport(calendar_write=True)
    controller = ExtrasTestController(
        ExtrasCatalog(calendar=(source,), support=support)
    )
    page = CalendarPage(controller)
    try:
        find_widget(page, MonthGrid, "calendarMonthGrid").setSelectedDate(
            QDate(2026, 11, 8)
        )
        events = find_widget(page, QTreeWidget, "calendarEvents")
        assert events.topLevelItemCount() == 1
        row = events.topLevelItem(0)
        assert row is not None
        assert QLocale().toString(
            QDate(2026, 11, 8), QLocale.FormatType.ShortFormat
        ) in row.text(1)
        events.setCurrentItem(row)
        actions = _entry_menu(events, "Edit series", keyboard=True)
        assert actions == {
            "Edit series": True,
            "Skip this occurrence": True,
            "Remove series": True,
        }
        editor = page.findChild(CalendarEditor)
        assert editor is not None
        find_widget(editor, QLineEdit, "calendarSummary").setText("Series changed")
        editor.accept()
        assert controller.calendar_edits[0][1] == source
        find_widget(page, MonthGrid, "calendarMonthGrid").setSelectedDate(
            QDate(2026, 11, 9)
        )
        assert events.topLevelItemCount() == 0
    finally:
        page.close()
        APPLICATION.processEvents()


def test_mini_editor_offers_qualified_repeat_and_reminder() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT,
        None,
        initial_date=Date(2026, 11, 1),
    )
    try:
        find_widget(editor, AppComboBox, "calendarRepeat").setCurrentIndex(2)
        find_widget(editor, QSpinBox, "calendarRepeatInterval").setValue(2)
        find_widget(editor, AppComboBox, "calendarRepeatLimit").setCurrentIndex(1)
        find_widget(editor, QSpinBox, "calendarRepeatCount").setValue(3)
        draft = editor.selected_edit()
        assert isinstance(draft, CalendarEntryDraft)
        assert draft.recurrence == CalendarRecurrenceRule(
            CalendarFrequency.WEEKLY, 2, 3
        )
        assert draft.reminder is None
        assert find_widget(editor, QCheckBox, "calendarReminder").isVisibleTo(editor)
    finally:
        editor.close()


def test_classic_editor_offers_saved_reminder_and_qualified_repeat() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT,
        None,
        initial_date=Date(2026, 11, 1),
    )
    try:
        find_widget(editor, QCheckBox, "calendarReminder").setChecked(True)
        find_widget(editor, QSpinBox, "calendarReminderMinutes").setValue(30)
        draft = editor.selected_edit()
        assert isinstance(draft, CalendarEntryDraft)
        assert draft.reminder == CalendarReminderDraft(-1800)
        assert draft.recurrence is None
        assert find_widget(editor, AppComboBox, "calendarRepeat").isVisibleTo(editor)
    finally:
        editor.close()


@pytest.mark.parametrize("language", ("de", "es"))
def test_calendar_option_translation_preserves_unsaved_native_choices(
    language: str,
) -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT, None, initial_date=Date(2026, 11, 1)
    )
    translator = QTranslator()
    catalog = (
        Path(__file__).resolve().parents[3]
        / "src/iOpenPod/GUI/presentation/i18n/translations"
        / f"iopenpod_{language}.qm"
    )
    assert translator.load(str(catalog))
    try:
        find_widget(editor, AppComboBox, "calendarRepeat").setCurrentIndex(2)
        find_widget(editor, QSpinBox, "calendarRepeatInterval").setValue(2)
        find_widget(editor, QCheckBox, "calendarAdvancedRepeat").setChecked(True)
        find_widget(editor, QPushButton, "calendarAddedDatesAdd").click()
        find_widget(editor, QPushButton, "calendarRepeatWeekdaysAdd").click()
        find_widget(editor, QCheckBox, "calendarReminder").setChecked(True)
        find_widget(editor, QSpinBox, "calendarReminderMinutes").setValue(25)
        before = editor.selected_edit()
        original_title = editor.windowTitle()
        assert APPLICATION.installTranslator(translator)
        APPLICATION.processEvents()
        editor.retranslate_ui()
        assert editor.selected_edit() == before
        assert editor.windowTitle() != original_title
        add = "Hinzufügen" if language == "de" else "Añadir"
        assert find_widget(editor, QPushButton, "calendarAddedDatesAdd").text() == add
        assert (
            find_widget(editor, QPushButton, "calendarRepeatWeekdaysAdd").text() == add
        )
    finally:
        APPLICATION.removeTranslator(translator)
        editor.close()


def test_editor_can_author_repeat_and_reminder_together() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT, None, initial_date=Date(2026, 11, 1)
    )
    try:
        find_widget(editor, AppComboBox, "calendarRepeat").setCurrentIndex(1)
        find_widget(editor, QCheckBox, "calendarReminder").setChecked(True)
        find_widget(editor, QSpinBox, "calendarReminderMinutes").setValue(15)
        draft = editor.selected_edit()
        assert isinstance(draft, CalendarEntryDraft)
        assert draft.recurrence == CalendarRecurrenceRule(CalendarFrequency.DAILY)
        assert draft.reminder == CalendarReminderDraft(-900)
    finally:
        editor.close()


def test_editor_authors_monthly_exceptions_and_end_relative_reminder() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT, None, initial_date=Date(2026, 11, 1)
    )
    try:
        find_widget(editor, AppComboBox, "calendarRepeat").setCurrentIndex(3)
        find_widget(editor, QCheckBox, "calendarAdvancedRepeat").setChecked(True)
        find_widget(
            editor, AppComboBox, "calendarRepeatWeekdaysPicker"
        ).setCurrentIndex(4)
        find_widget(
            editor, AppComboBox, "calendarRepeatWeekdaysOrdinal"
        ).setCurrentIndex(6)
        find_widget(editor, QPushButton, "calendarRepeatWeekdaysAdd").click()
        find_widget(editor, QDateEdit, "calendarAddedDatesPicker").setDate(
            QDate(2026, 11, 8)
        )
        find_widget(editor, QPushButton, "calendarAddedDatesAdd").click()
        find_widget(editor, QDateEdit, "calendarExcludedDatesPicker").setDate(
            QDate(2026, 11, 27)
        )
        find_widget(editor, QPushButton, "calendarExcludedDatesAdd").click()
        find_widget(editor, QPushButton, "calendarExcludedDatesRemove").click()
        find_widget(editor, QDateEdit, "calendarExcludedDatesPicker").setDate(
            QDate(2026, 11, 28)
        )
        find_widget(editor, QPushButton, "calendarExcludedDatesAdd").click()
        find_widget(editor, AppComboBox, "calendarExclusionRule").setCurrentIndex(2)
        find_widget(
            editor, AppComboBox, "calendarExclusionRuleWeekdaysPicker"
        ).setCurrentIndex(6)
        find_widget(editor, QPushButton, "calendarExclusionRuleWeekdaysAdd").click()
        find_widget(editor, QCheckBox, "calendarReminder").setChecked(True)
        find_widget(editor, AppComboBox, "calendarReminderMode").setCurrentIndex(3)
        find_widget(editor, QSpinBox, "calendarReminderMinutes").setValue(10)
        find_widget(editor, QSpinBox, "calendarReminderSeconds").setValue(5)
        draft = editor.selected_edit()
        assert isinstance(draft, CalendarEntryDraft)
        assert draft.recurrence is not None
        assert draft.recurrence.frequency is CalendarFrequency.MONTHLY
        assert draft.recurrence.weekdays == (
            CalendarDayRule(CalendarWeekday.FRIDAY, -1),
        )
        assert draft.exceptions is not None
        assert draft.exceptions.added == (Date(2026, 11, 8),)
        assert draft.exceptions.excluded == (Date(2026, 11, 28),)
        assert draft.exceptions.exclusion_rule == CalendarRecurrenceRule(
            CalendarFrequency.WEEKLY,
            weekdays=(CalendarDayRule(CalendarWeekday.SUNDAY),),
        )
        assert draft.reminder == CalendarReminderDraft(605, related_to_end=True)
    finally:
        editor.close()


def test_editor_preserves_saved_repeat_cutoff_and_edits_it_to_the_second() -> None:
    item = _calendar(
        "DTSTART:20261101T090000\r\nDTEND:20261101T100000\r\n"
        "RRULE:FREQ=WEEKLY;UNTIL=20261115T085959"
    )
    editor = CalendarEditor(CalendarEntryKind.EVENT, item)
    try:
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryChanges)
        assert edit.recurrence is UNCHANGED
        cutoff = find_widget(editor, QTimeEdit, "calendarRepeatUntilTime")
        assert any(
            label.buddy() is cutoff and label.text() == "Through time"
            for label in editor.findChildren(QLabel)
        )
        assert cutoff.time() == QTime(8, 59, 59)
        cutoff.setTime(QTime(9, 0))
        find_widget(editor, QPushButton, "calendarEditorSave").click()
        assert editor.result() == CalendarEditor.DialogCode.Accepted
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryChanges)
        assert isinstance(edit.recurrence, CalendarRecurrenceRule)
        assert edit.recurrence.until == PlainDateTime(2026, 11, 15, 9)
    finally:
        editor.close()


def test_editor_maps_yearly_month_dates_and_weekly_week_start() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT, None, initial_date=Date(2026, 11, 1)
    )
    try:
        frequency = find_widget(editor, AppComboBox, "calendarRepeat")
        frequency.setCurrentIndex(4)
        find_widget(editor, QCheckBox, "calendarAdvancedRepeat").setChecked(True)
        find_widget(editor, AppComboBox, "calendarRepeatMonthsPicker").setCurrentIndex(
            10
        )
        find_widget(editor, QPushButton, "calendarRepeatMonthsAdd").click()
        find_widget(
            editor, AppComboBox, "calendarRepeatMonthDaysPicker"
        ).setCurrentIndex(31)
        find_widget(editor, QPushButton, "calendarRepeatMonthDaysAdd").click()
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryDraft)
        assert edit.recurrence == CalendarRecurrenceRule(
            CalendarFrequency.YEARLY, month_days=(-1,), months=(11,)
        )
        frequency.setCurrentIndex(2)
        find_widget(editor, AppComboBox, "calendarRepeatWeekStart").setCurrentIndex(7)
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryDraft)
        assert edit.recurrence == CalendarRecurrenceRule(
            CalendarFrequency.WEEKLY, week_start=CalendarWeekday.SUNDAY
        )
    finally:
        editor.close()


def test_agenda_skips_selected_span_from_its_start_and_hides_skip_for_seed() -> None:
    source = _calendar(
        "DTSTART:20261101T090000\r\nDTEND:20261102T100000\r\nRRULE:FREQ=WEEKLY;COUNT=3"
    )
    controller = ExtrasTestController(
        ExtrasCatalog(calendar=(source,), support=ExtrasSupport(calendar_write=True))
    )
    page = CalendarPage(controller)
    try:
        grid = find_widget(page, MonthGrid, "calendarMonthGrid")
        tree = find_widget(page, QTreeWidget, "calendarEvents")
        grid.setSelectedDate(QDate(2026, 11, 2))
        assert "Skip this occurrence" not in _entry_menu(tree)
        grid.setSelectedDate(QDate(2026, 11, 9))
        assert _entry_menu(tree, "Skip this occurrence")["Skip this occurrence"]
        assert controller.skipped == [(source, Date(2026, 11, 9), Date(2026, 11, 8))]
        find_widget(page, AppComboBox, "calendarScope").setCurrentIndex(1)
        assert "Skip this occurrence" not in _entry_menu(tree)
    finally:
        page.close()


def test_existing_timezone_picker_uses_the_entries_own_file_and_keeps_clock_time() -> (
    None
):
    zone = (
        b"BEGIN:VTIMEZONE\r\nTZID:Home/West\r\nBEGIN:STANDARD\r\n"
        b"TZOFFSETTO:-0500\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
    )
    data = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        + zone
        + b"BEGIN:VEVENT\r\nSUMMARY:Event\r\nDTSTART:20261101T091530Z\r\n"
        b"END:VEVENT\r\n"
        + zone.replace(b"Home/West", b"Late/Zone")
        + b"END:VCALENDAR\r\n"
    )
    document = parse_calendar(data)
    item = CalendarItem(
        "second.ics",
        document.entries[0],
        "Shared",
        source_calendar=document.components[0],
    )
    controller = ExtrasTestController(
        ExtrasCatalog(
            calendar=(item,),
            support=ExtrasSupport(calendar_write=True),
            calendars=(
                CalendarGroup(
                    "Shared", ("first.ics", item.document_key), True, ("First/File",)
                ),
            ),
        )
    )
    page = CalendarPage(controller)
    try:
        find_widget(page, MonthGrid, "calendarMonthGrid").setSelectedDate(
            QDate(2026, 11, 1)
        )
        assert _entry_menu(find_widget(page, QTreeWidget, "calendarEvents"), "Edit")[
            "Edit"
        ]
        editor = page.findChild(CalendarEditor)
        assert editor is not None
        basis = find_widget(editor, AppComboBox, "calendarTimeBasis")
        assert basis.currentText() == "UTC"
        assert [basis.itemText(index) for index in range(basis.count())] == [
            "iPod local time",
            "UTC",
            "Home/West",
        ]
        basis.setCurrentIndex(2)
        find_widget(editor, QPushButton, "calendarEditorSave").click()
        change, source = controller.calendar_edits[0]
        assert source == item and isinstance(change, CalendarEntryChanges)
        assert change.tzid == "Home/West"
        updated = update_entry(document, item.index, change)
        assert updated.raw_bytes == data.replace(
            b"DTSTART:20261101T091530Z", b"DTSTART;TZID=Home/West:20261101T091530"
        )
    finally:
        page.close()
        APPLICATION.processEvents()


@pytest.mark.parametrize("model", ["MC525", "MD480", "MKN22"])
def test_touch_nano_has_no_alarm_route_in_either_navigation_style(model: str) -> None:
    active = make_active_ipod()
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == model
    )
    nano = replace(
        active, profile=profile, candidate=replace(active.candidate, profile=profile)
    )
    sidebar, compact = Sidebar(), CompactTopBar(playlists=LibraryWorkspace())
    try:
        sidebar.set_active_ipod(nano)
        compact.set_active_ipod(nano)
        assert not page_supported(PageId.ALARMS, profile)
        alarm = next(
            button
            for button in sidebar.findChildren(QPushButton)
            if button.property("pageId") == PageId.ALARMS.value
        )
        assert alarm.isHidden()
        assert find_widget(compact, QPushButton, "compactExtras").isHidden()
        sidebar.set_active_ipod(active)
        compact.set_active_ipod(active)
        assert not alarm.isHidden()
        assert not find_widget(compact, QPushButton, "compactExtras").isHidden()
    finally:
        sidebar.close()
        compact.close()
