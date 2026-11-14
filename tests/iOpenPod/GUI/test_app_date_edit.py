"""Themed date fields preserve native selection, bounds and popup cancellation."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QDate, QLocale, QRect, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyleOptionComboBox,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.extras_test_support import find_widget
from whenever import PlainDateTime

from iOpenPod.app.models.extras import AlarmItem
from iOpenPod.GUI.pages.alarms_page import AlarmEditor
from iOpenPod.GUI.pages.calendar_page import CalendarEditor
from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LAYOUT,
    LIGHT_TOKENS,
    ORIGINAL_DARK_TOKENS,
    ThemeTokens,
    resolve_typography,
)
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.app_date_edit import AppDateEdit
from iOpenPod.GUI.widgets.app_time_edit import AppTimeEdit
from iPodDB.calendar import CalendarEntryKind


@pytest.fixture
def date_field() -> Iterator[AppDateEdit]:
    original_style = APPLICATION.styleSheet()
    original_locale = QLocale()
    QLocale.setDefault(QLocale("en_US"))
    APPLICATION.setStyleSheet(
        render_stylesheet(ORIGINAL_DARK_TOKENS, resolve_typography())
    )
    host = QWidget()
    edit = AppDateEdit(host)
    edit.setDateRange(QDate(1970, 1, 1), QDate(2106, 2, 7))
    edit.setDate(QDate(2026, 12, 13))
    layout = QVBoxLayout(host)
    layout.addWidget(edit)
    host.resize(400, 70)
    host.show()
    APPLICATION.processEvents()
    try:
        yield edit
    finally:
        calendar = edit.calendarWidget()
        calendar.window().close()
        host.close()
        APPLICATION.setStyleSheet(original_style)
        QLocale.setDefault(original_locale)


def _arrow(widget: AppDateEdit | AppComboBox) -> QRect:
    option = QStyleOptionComboBox()
    option.initFrom(widget)
    option.editable = isinstance(widget, AppDateEdit)
    return widget.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox,
        option,
        QStyle.SubControl.SC_ComboBoxArrow,
        widget,
    )


def _open(edit: AppDateEdit) -> QCalendarWidget:
    QTest.mouseClick(edit, Qt.MouseButton.LeftButton, pos=_arrow(edit).center())
    APPLICATION.processEvents()
    calendar = edit.calendarWidget()
    assert calendar.isVisible()
    return calendar


def _color_distance(actual: QColor, expected: QColor) -> int:
    return (
        abs(actual.red() - expected.red())
        + abs(actual.green() - expected.green())
        + abs(actual.blue() - expected.blue())
    )


@pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS, ORIGINAL_DARK_TOKENS])
def test_field_arrow_and_opaque_rounded_popup_follow_the_theme(
    date_field: AppDateEdit, tokens: ThemeTokens
) -> None:
    APPLICATION.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    combo = AppComboBox()
    try:
        combo.ensurePolished()
        assert (
            _arrow(date_field).width()
            == _arrow(combo).width()
            == LAYOUT.combo_indicator_width
        )
        calendar = _open(date_field)
        image = calendar.window().grab().toImage()
        scale = image.devicePixelRatio()
        assert image.pixelColor(round(2 * scale), round(100 * scale)) == QColor(
            tokens.surface
        )
        assert image.pixelColor(0, 0).alpha() < 255
        assert calendar.width() >= LAYOUT.date_picker_width
        assert (
            calendar.screen()
            .availableGeometry()
            .contains(calendar.window().frameGeometry())
        )
        assert calendar.height() >= LAYOUT.date_picker_height
        assert (
            calendar.weekdayTextFormat(Qt.DayOfWeek.Saturday).foreground()
            == calendar.headerTextFormat().foreground()
        )
        assert not calendar.isNavigationBarVisible()
    finally:
        combo.close()


def test_month_and_year_navigation_does_not_change_the_date(
    date_field: AppDateEdit,
) -> None:
    calendar = _open(date_field)
    before = date_field.date()
    QTest.mouseClick(
        find_widget(calendar, QToolButton, "datePickerNext"), Qt.MouseButton.LeftButton
    )
    assert (calendar.yearShown(), calendar.monthShown()) == (2027, 1)
    find_widget(calendar, AppComboBox, "datePickerMonth").setCurrentIndex(4)
    find_widget(calendar, QSpinBox, "datePickerYear").setValue(2028)
    assert (calendar.yearShown(), calendar.monthShown()) == (2028, 5)
    assert date_field.date() == before
    calendar.window().close()
    assert date_field.date() == before
    _open(date_field)
    assert (calendar.yearShown(), calendar.monthShown()) == (
        before.year(),
        before.month(),
    )


def test_native_field_section_editing_remains_available(
    date_field: AppDateEdit,
) -> None:
    date_field.setDate(QDate(2026, 5, 13))
    date_field.setFocus()
    date_field.setCurrentSection(QDateEdit.Section.MonthSection)
    QTest.keyClick(date_field, Qt.Key.Key_Up)
    assert date_field.date() == QDate(2026, 6, 13)


def test_escape_in_month_menu_keeps_the_date_popup_open(
    date_field: AppDateEdit,
) -> None:
    calendar = _open(date_field)
    month = find_widget(calendar, AppComboBox, "datePickerMonth")
    month.showPopup()
    APPLICATION.processEvents()
    assert month.view().isVisible()
    QTest.keyClick(month.view(), Qt.Key.Key_Escape)
    assert not month.view().isVisible()
    assert calendar.isVisible()
    QTest.keyClick(month, Qt.Key.Key_Escape)
    assert not calendar.isVisible()


def test_open_popup_updates_its_surface_when_the_theme_changes(
    date_field: AppDateEdit,
) -> None:
    calendar = _open(date_field)
    before = date_field.date()
    APPLICATION.setStyleSheet(render_stylesheet(LIGHT_TOKENS, resolve_typography()))
    APPLICATION.processEvents()
    image = calendar.window().grab().toImage()
    assert image.pixelColor(2, 100) == QColor(LIGHT_TOKENS.surface)
    assert date_field.date() == before and calendar.isVisible()


def test_keyboard_selection_can_be_cancelled_or_accepted(
    date_field: AppDateEdit,
) -> None:
    before = date_field.date()
    calendar = _open(date_field)
    table = find_widget(calendar, QTableView, "qt_calendar_calendarview")
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Right)
    assert calendar.selectedDate() == before.addDays(1)
    QTest.keyClick(table, Qt.Key.Key_Escape)
    APPLICATION.processEvents()
    assert not calendar.isVisible()
    assert date_field.date() == before
    _open(date_field)
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Right)
    QTest.keyClick(table, Qt.Key.Key_Return)
    APPLICATION.processEvents()
    assert not calendar.isVisible()
    assert date_field.date() == before.addDays(1)


def test_clicking_a_day_or_today_commits_and_closes(date_field: AppDateEdit) -> None:
    calendar = _open(date_field)
    table = find_widget(calendar, QTableView, "qt_calendar_calendarview")
    model = table.model()
    target = next(
        model.index(row, column)
        for row in range(1, model.rowCount())
        for column in range(model.columnCount())
        if str(model.index(row, column).data()) == "17"
    )
    QTest.mouseClick(
        table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=table.visualRect(target).center(),
    )
    assert date_field.date() == QDate(2026, 12, 17)
    assert not calendar.isVisible()
    _open(date_field)
    QTest.mouseClick(
        find_widget(calendar, QPushButton, "datePickerToday"), Qt.MouseButton.LeftButton
    )
    assert date_field.date() == QDate.currentDate()
    assert not calendar.isVisible()


def test_date_limits_constrain_navigation_and_selection(
    date_field: AppDateEdit,
) -> None:
    date_field.setDateRange(QDate(2026, 12, 10), QDate(2026, 12, 20))
    calendar = _open(date_field)
    for name in ("datePickerPrevious", "datePickerNext"):
        assert not find_widget(calendar, QToolButton, name).isEnabled()
    year = find_widget(calendar, QSpinBox, "datePickerYear")
    assert year.minimum() == year.maximum() == 2026
    month = find_widget(calendar, AppComboBox, "datePickerMonth")
    model = month.model()
    assert not model.flags(model.index(10, 0)) & Qt.ItemFlag.ItemIsEnabled
    assert model.flags(model.index(11, 0)) & Qt.ItemFlag.ItemIsEnabled
    calendar.setSelectedDate(QDate(2026, 12, 31))
    assert calendar.selectedDate() == QDate(2026, 12, 20)
    assert date_field.date() <= date_field.maximumDate()


@pytest.mark.parametrize("read_only", [False, True])
def test_unavailable_fields_do_not_open_the_popup(
    date_field: AppDateEdit, read_only: bool
) -> None:
    if read_only:
        date_field.setReadOnly(True)
    else:
        date_field.setEnabled(False)
    QTest.mouseClick(
        date_field, Qt.MouseButton.LeftButton, pos=_arrow(date_field).center()
    )
    calendar = date_field.calendarWidget()
    assert not calendar.isVisible()


@pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS, ORIGINAL_DARK_TOKENS])
@pytest.mark.parametrize("dialog_name", ["calendarEditor", "alarmEditor"])
def test_disabled_date_and_time_share_the_muted_field_treatment(
    tokens: ThemeTokens, dialog_name: str
) -> None:
    original_style = APPLICATION.styleSheet()
    APPLICATION.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    dialog = QDialog()
    dialog.setObjectName(dialog_name)
    date = AppDateEdit(dialog)
    date.setDate(QDate(2026, 11, 13))
    time = AppTimeEdit(dialog)
    layout = QHBoxLayout(dialog)
    layout.addWidget(date)
    layout.addWidget(time)
    dialog.show()
    APPLICATION.processEvents()
    try:
        for inherited in (False, True):
            if inherited:
                dialog.setEnabled(False)
            else:
                date.setEnabled(False)
                time.setEnabled(False)
            APPLICATION.processEvents()
            for field in (date, time):
                image = field.grab().toImage()
                scale = image.devicePixelRatio()
                middle = round(field.height() / 2 * scale)
                assert image.pixelColor(round(5 * scale), middle) == QColor(
                    tokens.surface_alt
                )
                assert image.pixelColor(0, middle) == QColor(tokens.border)
                assert field.palette().color(
                    QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text
                ) == QColor(tokens.text_disabled)

            # The painted chevron must dim along with the native date text.
            image = date.grab().toImage()
            scale = image.devicePixelRatio()
            arrow = _arrow(date).adjusted(6, 6, -6, -6)
            expected = QColor(tokens.text_disabled)
            assert any(
                _color_distance(
                    image.pixelColor(round(x * scale), round(y * scale)), expected
                )
                < 15
                for y in range(arrow.top(), arrow.bottom() + 1)
                for x in range(arrow.left(), arrow.right() + 1)
            )
            dialog.setEnabled(True)
            date.setEnabled(True)
            time.setEnabled(True)
            APPLICATION.processEvents()
            assert date.date() == QDate(2026, 11, 13)
            assert date.palette().color(QPalette.ColorRole.Text) == QColor(tokens.text)
    finally:
        dialog.close()
        APPLICATION.setStyleSheet(original_style)


def test_locale_and_right_to_left_layout_preserve_the_selected_date(
    date_field: AppDateEdit,
) -> None:
    date_field.setLocale(QLocale("de_DE"))
    date_field.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    calendar = _open(date_field)
    assert _arrow(date_field).left() < date_field.width() // 2
    assert calendar.firstDayOfWeek() == Qt.DayOfWeek.Monday
    assert (
        find_widget(calendar, AppComboBox, "datePickerMonth").currentText()
        == "Dezember"
    )
    assert date_field.date() == QDate(2026, 12, 13)


def test_alarm_and_calendar_editors_share_the_themed_date_control() -> None:
    alarm = AlarmEditor(AlarmItem(0, "Alarm", PlainDateTime(2026, 12, 13, 8), 0, True))
    calendar = CalendarEditor(CalendarEntryKind.EVENT, None)
    try:
        for editor in (alarm, calendar):
            dates = editor.findChildren(QDateEdit)
            assert dates and all(isinstance(date, AppDateEdit) for date in dates)
    finally:
        alarm.close()
        calendar.close()
