"""Extras editors preserve native civil values and selected-device authority."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import (
    QDate,
    QLocale,
    QObject,
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
from whenever import Date, Instant, PlainDateTime, Time

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    AlarmFormat,
    ExtrasSupport,
    FeatureSupport,
    IdentificationStatus,
)
from iOpenPod.app import developer_flags
from iOpenPod.app.display_text import source_text
from iOpenPod.app.extras_controller import ExtrasController
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.models.extras import (
    AlarmItem,
    CalendarGroup,
    CalendarItem,
    ExtrasCatalog,
)
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
from iPodDB.library import LibrarySnapshot
from storage import FileFingerprint

pytestmark = pytest.mark.usefixtures("enable_extras_pages")


def _active() -> ActiveIPod:
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MB565"
    )
    candidate = DeviceCandidate(
        id=DeviceCandidateId("extras-gui"),
        display_name="iPod",
        host_description="Test",
        bus="usb",
        identification_status=IdentificationStatus.EXACT,
        readiness=DeviceReadiness.READY,
        profile=profile,
        total_bytes=120_000_000_000,
        available_bytes=60_000_000_000,
    )
    return ActiveIPod(
        candidate=candidate,
        profile=profile,
        library=LibrarySnapshot(),
        database_name="iTunesDB",
        database_fingerprint=FileFingerprint(
            size=0, modified_ns=0, device=0, inode=0, sha256="0" * 64
        ),
    )


class _Controller(ExtrasController):
    """A signal-bearing application boundary, without filesystem workers."""

    def __init__(self, catalog: ExtrasCatalog | None = None) -> None:
        QObject.__init__(self)
        self.current: ActiveIPod | None = _active()
        self.view = catalog or ExtrasCatalog()
        self.working = False
        self.error = ""
        self.calendar_edits: list[
            tuple[CalendarEntryDraft | CalendarEntryChanges, CalendarItem | None]
        ] = []
        self.alarm_edits: list[tuple[AlarmItem, PlainDateTime | Time, int | None]] = []
        self.refreshes = 0
        self.destinations: list[CalendarGroup | None] = []
        self.names: list[tuple[CalendarGroup | None, str]] = []
        self.imports: list[tuple[str, str | None]] = []
        self.skipped: list[tuple[CalendarItem, Date, Date]] = []
        self.removed: list[CalendarItem] = []

    @property
    def active_ipod(self) -> ActiveIPod | None:
        return self.current

    @property
    def catalog(self) -> ExtrasCatalog:
        return self.view

    @property
    def busy(self) -> bool:
        return self.working

    @property
    def message(self) -> str:
        return self.error

    @property
    def can_write(self) -> bool:
        return self.current is not None and not self.working

    def refresh(self) -> None:
        self.refreshes += 1

    def save_calendar(
        self,
        edit: CalendarEntryDraft | CalendarEntryChanges,
        existing: CalendarItem | None = None,
        destination: CalendarGroup | None = None,
    ) -> bool:
        self.calendar_edits.append((edit, existing))
        self.destinations.append(destination)
        return True

    def create_calendar(self, name: str) -> bool:
        self.names.append((None, name))
        return True

    def skip_calendar_occurrence(
        self, item: CalendarItem, day: Date, start_day: Date
    ) -> bool:
        self.skipped.append((item, day, start_day))
        return True

    def remove_calendar(self, item: CalendarItem) -> bool:
        self.removed.append(item)
        return True

    def rename_calendar(self, calendar: CalendarGroup, name: str) -> bool:
        self.names.append((calendar, name))
        return True

    def import_calendar(self, path: str, name: str | None = None) -> bool:
        self.imports.append((path, name))
        return True

    def save_alarm(
        self, item: AlarmItem, time: PlainDateTime | Time, repeat: int | None = None
    ) -> bool:
        self.alarm_edits.append((item, time, repeat))
        return True


def _find[T: QObject](parent: QObject, cls: type[T], name: str) -> T:
    found = parent.findChild(cls, name)
    assert isinstance(found, cls)
    return found


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
def test_video_alarm_snapshot_stays_visible_without_offering_an_editor(
    available: bool,
) -> None:
    item = AlarmItem(0, "Clock alarm snapshot", Time(7, 30), None, False)
    controller = _Controller(
        ExtrasCatalog(
            alarms=(item,) if available else (),
            support=ExtrasSupport(calendar_write=True, alarm_format=AlarmFormat.VIDEO),
        )
    )
    active = _active()
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
        tree = _find(page, QTreeWidget, "alarmsList")
        row = tree.topLevelItem(0)
        if available:
            assert row is not None and row.text(0) == "Clock alarm snapshot"
            tree.setCurrentItem(row)
            tree.itemActivated.emit(row, 0)
        else:
            assert row is None
            empty = _find(page, QLabel, "alarmsEmpty").text()
            assert "could not be read" in empty
            assert "No saved alarms" not in empty
        assert not _find(page, QPushButton, "alarmEdit").isEnabled()
        assert tree.accessibleName() == "Clock alarm snapshot"
        assert (
            "may be disabled or out of date"
            in _find(page, QLabel, "alarmsStatus").text()
        )
        assert page.findChild(AlarmEditor) is None
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
        _find(editor, QLineEdit, "calendarSummary").setText("Changed")
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryChanges)
        assert edit.summary == "Changed"
        assert edit.start is UNCHANGED and edit.end is UNCHANGED
        assert edit.due is UNCHANGED and edit.completed_at is UNCHANGED
        assert not _find(editor, QDateEdit, "calendarStartDate").isEnabled()
    finally:
        editor.close()


def test_utc_calendar_editor_preserves_instant_without_host_conversion() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT, _calendar("DTSTART:19691231T233000Z")
    )
    try:
        assert _find(editor, QDateEdit, "calendarStartDate").date() == QDate(
            1969, 12, 31
        )
        _find(editor, QTimeEdit, "calendarStartTime").setTime(QTime(23, 45))
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryChanges)
        assert edit.start == Instant.from_utc(1969, 12, 31, 23, 45)
    finally:
        editor.close()


def test_new_all_day_event_uses_exclusive_following_day_end() -> None:
    editor = CalendarEditor(CalendarEntryKind.EVENT, None)
    try:
        _find(editor, QLineEdit, "calendarSummary").setText("Day off")
        _find(editor, QDateEdit, "calendarStartDate").setDate(QDate(2026, 11, 1))
        _find(editor, QDateEdit, "calendarEndDate").setDate(QDate(2026, 11, 1))
        _find(editor, QCheckBox, "calendarAllDay").setChecked(True)
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
        _find(editor, AppComboBox, "calendarTodoStatus").setCurrentIndex(2)
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
        _find(editor, QTimeEdit, "alarmTime").setTime(QTime(2, 45))
        assert editor.selected_time() == PlainDateTime(2026, 3, 8, 2, 45)
        assert editor.selected_repeat() is None
        combo = _find(editor, AppComboBox, "alarmRepeat")
        combo.setCurrentIndex(combo.findData(2))
        assert editor.selected_repeat() == 2
    finally:
        editor.close()


def test_preferences_alarm_has_minute_only_editor_and_no_repeat_edit() -> None:
    editor = AlarmEditor(AlarmItem(0, "Clock alarm", Time(0), None, True))
    try:
        assert _find(editor, QDateEdit, "alarmDate").isHidden()
        assert _find(editor, AppComboBox, "alarmRepeat").isHidden()
        assert editor.selected_time() == Time(0)
        assert editor.selected_repeat() is None
    finally:
        editor.close()


@pytest.mark.parametrize("end_day", [1, 2])
def test_invalid_new_calendar_range_keeps_the_draft_open(end_day: int) -> None:
    editor = CalendarEditor(CalendarEntryKind.EVENT, None)
    try:
        editor.show()
        _find(editor, QLineEdit, "calendarSummary").setText("Retain my draft")
        _find(editor, QDateEdit, "calendarStartDate").setDate(QDate(2026, 11, 2))
        _find(editor, QDateEdit, "calendarEndDate").setDate(QDate(2026, 11, end_day))
        _find(editor, QTimeEdit, "calendarEndTime").setTime(QTime(9, 0))
        _find(editor, QPushButton, "calendarEditorSave").click()
        assert editor.isVisible()
        assert "later" in _find(editor, QLabel, "calendarEditorError").text()
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
        _find(editor, QTimeEdit, "calendarEndTime").setTime(QTime(9, 0))
        _find(editor, QPushButton, "calendarEditorSave").click()
        assert editor.isVisible()
        assert "later" in _find(editor, QLabel, "calendarEditorError").text()
    finally:
        editor.close()
    equal = _calendar(
        f"DTSTART:20261101T090000{suffix}\r\nDTEND:20261101T090000{suffix}"
    )
    retained = CalendarEditor(CalendarEntryKind.EVENT, equal)
    try:
        retained.show()
        _find(retained, QLineEdit, "calendarSummary").setText("Text edit")
        _find(retained, QPushButton, "calendarEditorSave").click()
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
        _find(editor, QTimeEdit, "alarmTime").setTime(QTime(6, 28, 15))
        _find(editor, QPushButton, "alarmEditorSave").click()
        assert editor.isVisible()
        assert "06:28:14" in _find(editor, QLabel, "alarmEditorError").text()
    finally:
        editor.close()
    original = AlarmEditor(AlarmItem(0, "Alarm", sentinel, 1, True))
    try:
        original.show()
        _find(original, QPushButton, "alarmEditorSave").click()
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
    controller = _Controller(
        ExtrasCatalog(
            calendar=(_calendar("DTSTART:20261101T013000"),),
            alarms=(AlarmItem(0, "Alarm", Time(7), None, True),),
            support=ExtrasSupport(calendar_write=True, alarm_write=True),
        )
    )
    page = page_type(controller)
    try:
        if isinstance(page, CalendarPage):
            _find(page, MonthGrid, "calendarMonthGrid").setSelectedDate(
                QDate(2026, 11, 1)
            )
        page.show()
        tree = _find(page, QTreeWidget, tree_name)
        first = tree.topLevelItem(0)
        assert first is not None
        tree.setCurrentItem(first)
        if activate_item:
            tree.itemActivated.emit(first, 0)
        elif button_name is None:
            assert _entry_menu(tree, "Edit")["Edit"]
        else:
            _find(page, QPushButton, button_name).click()
        editor = page.findChild(editor_type)
        assert editor is not None and editor.isVisible()
        controller.current = _active()  # same model, different captured connection
        controller.changed.emit()
        assert not editor.isVisible()
        assert not controller.calendar_edits and not controller.alarm_edits
    finally:
        page.close()
        APPLICATION.processEvents()


def test_calendar_busy_and_errors_remain_page_local() -> None:
    controller = _Controller(ExtrasCatalog(support=ExtrasSupport(calendar_write=True)))
    page = CalendarPage(controller)
    try:
        controller.working = True
        controller.error = "<b>Calendar unavailable</b>"
        controller.changed.emit()
        assert not _find(page, QPushButton, "calendarNew").isEnabled()
        status = _find(page, QLabel, "calendarStatus")
        assert status.text() == controller.error
        assert status.textFormat() is Qt.TextFormat.PlainText
        controller.working = False
        controller.changed.emit()
        tabs = _find(page, QTabWidget, "calendarTabs")
        tabs.setCurrentIndex(1)
        assert "To Dos" in _find(page, QLabel, "calendarEmpty").text()
        controller.current = None
        controller.changed.emit()
        assert not _find(page, QPushButton, "calendarImport").isEnabled()
    finally:
        page.close()


def test_sleep_timer_explains_device_control_without_a_host_timer() -> None:
    page = AlarmsPage(_Controller())
    try:
        text = _find(page, QLabel, "sleepTimerInstructions").text()
        assert "on your iPod" in text and "cannot read or change" in text
        assert page.findChild(QPushButton, "startSleepTimer") is None
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
    controller = _Controller(
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
        _find(editor, QLineEdit, "calendarSummary").setText("User's unchanged title")
        _find(editor, QTimeEdit, "calendarStartTime").setTime(QTime(8, 45))
        before = editor.selected_edit()
        assert APPLICATION.installTranslator(translator)
        APPLICATION.processEvents()
        assert editor.windowTitle() == title
        assert editor.selected_edit() == before
        assert cancel in [button.text() for button in editor.findChildren(QPushButton)]
        row = _find(page, QTreeWidget, "alarmsList").topLevelItem(0)
        assert row is not None and row.text(0) == alarm_label
    finally:
        APPLICATION.removeTranslator(translator)
        editor.close()
        page.close()


@pytest.mark.parametrize("firmware", ["", "9.9.9"])
def test_calendar_and_alarm_read_only_messages_follow_their_own_support(
    firmware: str,
) -> None:
    controller = _Controller(ExtrasCatalog(support=ExtrasSupport()))
    controller.current = replace(_active(), firmware_version=firmware)
    calendar, alarms = CalendarPage(controller), AlarmsPage(controller)
    try:
        calendar_status = _find(calendar, QLabel, "calendarStatus")
        alarm_status = _find(alarms, QLabel, "alarmsStatus")
        for label in (calendar_status, alarm_status):
            assert controller.current.profile.display_name in label.text()
            assert label.textFormat() is Qt.TextFormat.PlainText
        if firmware:
            assert "Firmware 9.9.9" in alarm_status.text()
        else:
            assert "firmware version could not be confirmed" in alarm_status.text()
        assert "Calendar editing is unavailable" in calendar_status.text()
        assert "editing is unavailable" in alarm_status.text()
        assert not _find(calendar, QPushButton, "calendarNew").isEnabled()
        assert not _find(calendar, QPushButton, "calendarImport").isEnabled()
        assert not _find(alarms, QPushButton, "alarmEdit").isEnabled()
        assert "Create" not in _find(calendar, QLabel, "calendarEmpty").text()
        empty = _find(alarms, QLabel, "alarmsEmpty").text()
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
    page = CalendarPage(_Controller(ExtrasCatalog(calendar=(item,))))
    try:
        _find(page, MonthGrid, "calendarMonthGrid").setSelectedDate(
            QDate(2026, 11, day)
        )
        assert (
            _find(page, QTreeWidget, "calendarEvents").topLevelItemCount() == expected
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
    page = CalendarPage(_Controller(ExtrasCatalog(calendar=(recurring, unknown))))
    try:
        grid = _find(page, MonthGrid, "calendarMonthGrid")
        tree = _find(page, QTreeWidget, "calendarEvents")
        grid.setSelectedDate(QDate(2026, 11, 1))
        assert tree.topLevelItemCount() == 1
        first = tree.topLevelItem(0)
        assert first is not None and "Unknown/Zone" in first.text(1)
        grid.setSelectedDate(QDate(2026, 11, 2))
        assert tree.topLevelItemCount() == 0
        _find(page, AppComboBox, "calendarScope").setCurrentIndex(1)
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
    page = CalendarPage(_Controller(ExtrasCatalog(calendar=(item,))))
    try:
        grid = _find(page, MonthGrid, "calendarMonthGrid")
        grid.setSelectedDate(QDate(2026, 11, 7))
        tree = _find(page, QTreeWidget, "calendarEvents")
        search = _find(page, SearchField, "calendarSearch")
        assert tree.topLevelItemCount() == 0
        search.set_query("station")
        search.queryChanged.emit("station")
        assert tree.topLevelItemCount() == 1
        assert _find(page, QLabel, "calendarAgendaTitle").text() == "Search results"
        search.set_query("")
        search.queryChanged.emit("")
        assert tree.topLevelItemCount() == 0
        assert grid.selectedDate() == QDate(2026, 11, 7)
    finally:
        page.close()


def test_new_event_uses_selected_day_and_month_navigation_updates_agenda() -> None:
    controller = _Controller(ExtrasCatalog(support=ExtrasSupport(calendar_write=True)))
    page = CalendarPage(controller)
    try:
        grid = _find(page, MonthGrid, "calendarMonthGrid")
        grid.setSelectedDate(QDate(2026, 11, 7))
        _find(page, QToolButton, "calendarNextMonth").click()
        assert grid.selectedDate() == QDate(2026, 12, 1)
        _find(page, QPushButton, "calendarNew").click()
        editor = page.findChild(CalendarEditor)
        assert editor is not None
        assert editor.selected_edit().start == PlainDateTime(2026, 12, 1, 9)
        editor.reject()
        _find(page, QPushButton, "calendarToday").click()
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
    controller = _Controller(
        ExtrasCatalog(calendar=(item,), support=ExtrasSupport(calendar_write=True))
    )
    page = CalendarPage(controller)
    try:
        _find(page, QTabWidget, "calendarTabs").setCurrentIndex(1)
        tree = _find(page, QTreeWidget, "calendarTodos")
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
    controller = _Controller(ExtrasCatalog(calendar=(item,)))
    page = CalendarPage(controller)
    try:
        page.resize(1000, 700)
        page.show()
        grid = _find(page, MonthGrid, "calendarMonthGrid")
        grid.setSelectedDate(QDate(2026, 11, 1))
        grid.setFocus()
        target = grid.focusProxy()
        assert target is not None
        QTest.keyClick(target, Qt.Key.Key_Right)
        assert grid.selectedDate() == QDate(2026, 11, 2)
        controller.current = None
        controller.view = ExtrasCatalog()
        controller.changed.emit()
        assert _find(page, QTreeWidget, "calendarEvents").topLevelItemCount() == 0
        assert not _find(page, QPushButton, "calendarNew").isEnabled()
    finally:
        page.close()


def test_calendar_weekday_header_stays_slim_when_the_date_grid_grows() -> None:
    grid = MonthGrid(today=QDate(2026, 11, 10))
    try:
        grid.resize(720, 340)
        grid.show()
        APPLICATION.processEvents()
        view = _find(grid, QTableView, "qt_calendar_calendarview")
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
    controller = _Controller(
        ExtrasCatalog(
            calendar=(first, series), support=ExtrasSupport(calendar_write=True)
        )
    )
    page = CalendarPage(controller)
    try:
        _find(page, MonthGrid, "calendarMonthGrid").setSelectedDate(QDate(2026, 11, 1))
        page.resize(1000, 700)
        page.show()
        tree = _find(page, QTreeWidget, "calendarEvents")
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
            controller.current = _active()
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
    active = _active()
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
        extras = _find(compact, QPushButton, "compactExtras")
        assert not extras.isHidden()
        dropdown = _find(compact, HoverDropdown, "compactExtrasMenu")
        requests: list[str] = []
        compact.pageRequested.connect(requests.append)
        compact.resize(1400, 60)
        compact.show()
        extras.setFocus()
        QTest.keyClick(extras, Qt.Key.Key_Down)
        APPLICATION.processEvents()
        assert not requests
        actions = dropdown.actions()
        assert len(actions) == 2
        actions[0].trigger()
        actions[1].trigger()
        assert requests == [PageId.CALENDAR.value, PageId.ALARMS.value]
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
    context.device_controller.finish_library_save(_active())
    refreshes: list[bool] = []
    monkeypatch.setattr(
        context.extras_controller, "refresh", lambda: refreshes.append(True)
    )
    window = MainWindow(context, auto_discover=False)
    try:
        sidebar = window.findChild(Sidebar)
        compact = window.findChild(CompactTopBar)
        assert sidebar is not None and compact is not None
        assert not _find(compact, QPushButton, "compactExtras").isHidden()
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
    controller = _Controller(
        ExtrasCatalog(
            calendar=(first, second),
            support=ExtrasSupport(calendar_write=True),
            calendars=groups,
        )
    )
    page = CalendarPage(controller)
    try:
        selector = _find(page, AppComboBox, "calendarSelector")
        scope = _find(page, AppComboBox, "calendarScope")
        scope.setCurrentIndex(1)
        events = _find(page, QTreeWidget, "calendarEvents")
        assert selector.count() == 4
        assert events.topLevelItemCount() == 2
        selector.setCurrentIndex(1)
        assert events.topLevelItemCount() == 1
        row = events.topLevelItem(0)
        assert row is not None
        assert row.data(0, Qt.ItemDataRole.UserRole) == (
            "Work.ics",
            0,
        )
        selector.setCurrentIndex(3)
        assert events.topLevelItemCount() == 0
        assert _find(page, QPushButton, "calendarRename").isEnabled()
        controller.current = None
        controller.view = ExtrasCatalog()
        controller.changed.emit()
        assert selector.count() == 1
        assert not _find(page, QPushButton, "calendarRename").isEnabled()
    finally:
        page.close()


@pytest.mark.parametrize(
    "name,accepted", (("Imported", True), ("", True), ("Ignored", False))
)
def test_import_calendar_offers_a_name_before_publication(
    monkeypatch: pytest.MonkeyPatch, name: str, accepted: bool
) -> None:
    controller = _Controller(ExtrasCatalog(support=ExtrasSupport(calendar_write=True)))
    page = CalendarPage(controller)

    def open_file(*args: object) -> tuple[str, str]:
        return ("example.ics", "")

    def get_text(*args: object, **kwargs: object) -> tuple[str, bool]:
        return (name, accepted)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", open_file)
    monkeypatch.setattr(QInputDialog, "getText", get_text)
    try:
        _find(page, QPushButton, "calendarImport").click()
        assert controller.imports == (
            [("example.ics", name or None)] if accepted else []
        )
    finally:
        page.close()


def test_create_and_rename_calendar_use_the_selected_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = CalendarGroup("Work", ("Work.ics",), True)
    controller = _Controller(
        ExtrasCatalog(support=ExtrasSupport(calendar_write=True), calendars=(group,))
    )
    page = CalendarPage(controller)

    def get_text(*args: object, **kwargs: object) -> tuple[str, bool]:
        return ("Team", True)

    monkeypatch.setattr(QInputDialog, "getText", get_text)
    try:
        _find(page, QPushButton, "calendarCreate").click()
        selector = _find(page, AppComboBox, "calendarSelector")
        selector.setCurrentIndex(1)
        _find(page, QPushButton, "calendarRename").click()
        assert controller.names == [(None, "Team"), (group, "Team")]
    finally:
        page.close()


def test_new_entry_retains_its_chosen_destination_while_editor_is_open() -> None:
    work = CalendarGroup("Work", ("Work.ics",), True)
    personal = CalendarGroup("Personal", ("Personal.ics",), True)
    controller = _Controller(
        ExtrasCatalog(
            support=ExtrasSupport(calendar_write=True), calendars=(work, personal)
        )
    )
    page = CalendarPage(controller)
    try:
        selector = _find(page, AppComboBox, "calendarSelector")
        selector.setCurrentIndex(1)
        _find(page, QPushButton, "calendarNew").click()
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
    controller = _Controller(
        ExtrasCatalog(support=ExtrasSupport(calendar_write=True), calendars=(work,))
    )
    page = CalendarPage(controller)

    def choose(*args: object) -> tuple[str, bool]:
        controller.current = _active()
        return "Work", True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    try:
        _find(page, QPushButton, "calendarNew").click()
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
    controller = _Controller(ExtrasCatalog(calendar=(source,), support=support))
    page = CalendarPage(controller)
    try:
        _find(page, MonthGrid, "calendarMonthGrid").setSelectedDate(QDate(2026, 11, 8))
        events = _find(page, QTreeWidget, "calendarEvents")
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
        _find(editor, QLineEdit, "calendarSummary").setText("Series changed")
        editor.accept()
        assert controller.calendar_edits[0][1] == source
        _find(page, MonthGrid, "calendarMonthGrid").setSelectedDate(QDate(2026, 11, 9))
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
        _find(editor, AppComboBox, "calendarRepeat").setCurrentIndex(2)
        _find(editor, QSpinBox, "calendarRepeatInterval").setValue(2)
        _find(editor, AppComboBox, "calendarRepeatLimit").setCurrentIndex(1)
        _find(editor, QSpinBox, "calendarRepeatCount").setValue(3)
        draft = editor.selected_edit()
        assert isinstance(draft, CalendarEntryDraft)
        assert draft.recurrence == CalendarRecurrenceRule(
            CalendarFrequency.WEEKLY, 2, 3
        )
        assert draft.reminder is None
        assert _find(editor, QCheckBox, "calendarReminder").isVisibleTo(editor)
    finally:
        editor.close()


def test_classic_editor_offers_saved_reminder_and_qualified_repeat() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT,
        None,
        initial_date=Date(2026, 11, 1),
    )
    try:
        _find(editor, QCheckBox, "calendarReminder").setChecked(True)
        _find(editor, QSpinBox, "calendarReminderMinutes").setValue(30)
        draft = editor.selected_edit()
        assert isinstance(draft, CalendarEntryDraft)
        assert draft.reminder == CalendarReminderDraft(-1800)
        assert draft.recurrence is None
        assert _find(editor, AppComboBox, "calendarRepeat").isVisibleTo(editor)
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
        _find(editor, AppComboBox, "calendarRepeat").setCurrentIndex(2)
        _find(editor, QSpinBox, "calendarRepeatInterval").setValue(2)
        _find(editor, QCheckBox, "calendarAdvancedRepeat").setChecked(True)
        _find(editor, QPushButton, "calendarAddedDatesAdd").click()
        _find(editor, QPushButton, "calendarRepeatWeekdaysAdd").click()
        _find(editor, QCheckBox, "calendarReminder").setChecked(True)
        _find(editor, QSpinBox, "calendarReminderMinutes").setValue(25)
        before = editor.selected_edit()
        original_title = editor.windowTitle()
        assert APPLICATION.installTranslator(translator)
        APPLICATION.processEvents()
        editor.retranslate_ui()
        assert editor.selected_edit() == before
        assert editor.windowTitle() != original_title
        add = "Hinzufügen" if language == "de" else "Añadir"
        assert _find(editor, QPushButton, "calendarAddedDatesAdd").text() == add
        assert _find(editor, QPushButton, "calendarRepeatWeekdaysAdd").text() == add
    finally:
        APPLICATION.removeTranslator(translator)
        editor.close()


def test_editor_can_author_repeat_and_reminder_together() -> None:
    editor = CalendarEditor(
        CalendarEntryKind.EVENT, None, initial_date=Date(2026, 11, 1)
    )
    try:
        _find(editor, AppComboBox, "calendarRepeat").setCurrentIndex(1)
        _find(editor, QCheckBox, "calendarReminder").setChecked(True)
        _find(editor, QSpinBox, "calendarReminderMinutes").setValue(15)
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
        _find(editor, AppComboBox, "calendarRepeat").setCurrentIndex(3)
        _find(editor, QCheckBox, "calendarAdvancedRepeat").setChecked(True)
        _find(editor, AppComboBox, "calendarRepeatWeekdaysPicker").setCurrentIndex(4)
        _find(editor, AppComboBox, "calendarRepeatWeekdaysOrdinal").setCurrentIndex(6)
        _find(editor, QPushButton, "calendarRepeatWeekdaysAdd").click()
        _find(editor, QDateEdit, "calendarAddedDatesPicker").setDate(QDate(2026, 11, 8))
        _find(editor, QPushButton, "calendarAddedDatesAdd").click()
        _find(editor, QDateEdit, "calendarExcludedDatesPicker").setDate(
            QDate(2026, 11, 27)
        )
        _find(editor, QPushButton, "calendarExcludedDatesAdd").click()
        _find(editor, QPushButton, "calendarExcludedDatesRemove").click()
        _find(editor, QDateEdit, "calendarExcludedDatesPicker").setDate(
            QDate(2026, 11, 28)
        )
        _find(editor, QPushButton, "calendarExcludedDatesAdd").click()
        _find(editor, AppComboBox, "calendarExclusionRule").setCurrentIndex(2)
        _find(
            editor, AppComboBox, "calendarExclusionRuleWeekdaysPicker"
        ).setCurrentIndex(6)
        _find(editor, QPushButton, "calendarExclusionRuleWeekdaysAdd").click()
        _find(editor, QCheckBox, "calendarReminder").setChecked(True)
        _find(editor, AppComboBox, "calendarReminderMode").setCurrentIndex(3)
        _find(editor, QSpinBox, "calendarReminderMinutes").setValue(10)
        _find(editor, QSpinBox, "calendarReminderSeconds").setValue(5)
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
        cutoff = _find(editor, QTimeEdit, "calendarRepeatUntilTime")
        assert any(
            label.buddy() is cutoff and label.text() == "Through time"
            for label in editor.findChildren(QLabel)
        )
        assert cutoff.time() == QTime(8, 59, 59)
        cutoff.setTime(QTime(9, 0))
        _find(editor, QPushButton, "calendarEditorSave").click()
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
        frequency = _find(editor, AppComboBox, "calendarRepeat")
        frequency.setCurrentIndex(4)
        _find(editor, QCheckBox, "calendarAdvancedRepeat").setChecked(True)
        _find(editor, AppComboBox, "calendarRepeatMonthsPicker").setCurrentIndex(10)
        _find(editor, QPushButton, "calendarRepeatMonthsAdd").click()
        _find(editor, AppComboBox, "calendarRepeatMonthDaysPicker").setCurrentIndex(31)
        _find(editor, QPushButton, "calendarRepeatMonthDaysAdd").click()
        edit = editor.selected_edit()
        assert isinstance(edit, CalendarEntryDraft)
        assert edit.recurrence == CalendarRecurrenceRule(
            CalendarFrequency.YEARLY, month_days=(-1,), months=(11,)
        )
        frequency.setCurrentIndex(2)
        _find(editor, AppComboBox, "calendarRepeatWeekStart").setCurrentIndex(7)
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
    controller = _Controller(
        ExtrasCatalog(calendar=(source,), support=ExtrasSupport(calendar_write=True))
    )
    page = CalendarPage(controller)
    try:
        grid = _find(page, MonthGrid, "calendarMonthGrid")
        tree = _find(page, QTreeWidget, "calendarEvents")
        grid.setSelectedDate(QDate(2026, 11, 2))
        assert "Skip this occurrence" not in _entry_menu(tree)
        grid.setSelectedDate(QDate(2026, 11, 9))
        assert _entry_menu(tree, "Skip this occurrence")["Skip this occurrence"]
        assert controller.skipped == [(source, Date(2026, 11, 9), Date(2026, 11, 8))]
        _find(page, AppComboBox, "calendarScope").setCurrentIndex(1)
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
    controller = _Controller(
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
        _find(page, MonthGrid, "calendarMonthGrid").setSelectedDate(QDate(2026, 11, 1))
        assert _entry_menu(_find(page, QTreeWidget, "calendarEvents"), "Edit")["Edit"]
        editor = page.findChild(CalendarEditor)
        assert editor is not None
        basis = _find(editor, AppComboBox, "calendarTimeBasis")
        assert basis.currentText() == "UTC"
        assert [basis.itemText(index) for index in range(basis.count())] == [
            "iPod local time",
            "UTC",
            "Home/West",
        ]
        basis.setCurrentIndex(2)
        _find(editor, QPushButton, "calendarEditorSave").click()
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
