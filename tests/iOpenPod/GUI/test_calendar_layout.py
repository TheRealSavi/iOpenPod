"""Calendar layout keeps its controls and event indicators usable at desktop sizes."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QDate, QLocale, QPoint, QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFrame, QLabel, QSplitter, QTabWidget, QTreeWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.extras_test_support import ExtrasTestController, find_widget

from device_registry import ExtrasSupport
from iOpenPod.app.models.extras import CalendarItem, ExtrasCatalog
from iOpenPod.GUI.pages.calendar_page import CalendarPage
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
from iOpenPod.GUI.widgets.calendar_month import CalendarMarker, MonthGrid
from iOpenPod.GUI.widgets.search_field import SearchField
from iPodDB.calendar import parse_calendar


@pytest.fixture(params=[LIGHT_TOKENS, DARK_TOKENS, ORIGINAL_DARK_TOKENS])
def themed_calendar(request: pytest.FixtureRequest) -> Iterator[CalendarPage]:
    tokens: ThemeTokens = request.param
    controller = ExtrasTestController(
        ExtrasCatalog(support=ExtrasSupport(calendar_write=True))
    )
    page = CalendarPage(controller)
    page.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    try:
        yield page
    finally:
        page.close()


def test_calendar_resizes_without_losing_keyboard_selection(
    themed_calendar: CalendarPage,
) -> None:
    page = themed_calendar
    grid = find_widget(page, MonthGrid, "calendarMonthGrid")
    agenda = find_widget(page, QFrame, "calendarAgenda")
    splitter = find_widget(page, QSplitter, "calendarSplit")
    selector = find_widget(page, AppComboBox, "calendarSelector")
    search = find_widget(page, SearchField, "calendarSearch")
    grid.setSelectedDate(QDate(2026, 11, 13))
    for width, height in [(1440, 900), (760, 850), (1000, 700)]:
        page.resize(width, height)
        page.show()
        APPLICATION.processEvents()
        assert page.width() == width
        assert selector.width() <= LAYOUT.calendar_filter_width
        selector_rect = QRect(selector.mapTo(page, QPoint()), selector.size())
        search_rect = QRect(search.mapTo(page, QPoint()), search.size())
        assert not selector_rect.intersects(search_rect)
        assert grid.selectedDate() == QDate(2026, 11, 13)
        if width < LAYOUT.calendar_stacked_breakpoint:
            assert splitter.orientation() == Qt.Orientation.Vertical
            assert agenda.mapTo(page, QPoint()).y() > grid.mapTo(page, QPoint()).y()
        else:
            assert splitter.orientation() == Qt.Orientation.Horizontal
            assert agenda.width() <= LAYOUT.calendar_agenda_maximum_width
            assert grid.width() > agenda.width()
    grid.setFocus()
    target = grid.focusProxy()
    assert target is not None
    QTest.keyClick(target, Qt.Key.Key_Right)
    assert grid.selectedDate() == QDate(2026, 11, 14)
    assert find_widget(
        page, QLabel, "calendarAgendaTitle"
    ).text() == QLocale().toString(grid.selectedDate(), "dddd, d")


def test_empty_state_follows_the_active_list_and_clears_when_data_arrives() -> None:
    controller = ExtrasTestController()
    page = CalendarPage(controller)
    try:
        page.resize(1000, 700)
        page.show()
        APPLICATION.processEvents()
        empty = find_widget(page, QLabel, "calendarEmpty")
        tabs = find_widget(page, QTabWidget, "calendarTabs")
        for tab, name in [
            (0, "calendarEvents"),
            (1, "calendarTodos"),
            (0, "calendarEvents"),
        ]:
            tabs.setCurrentIndex(tab)
            APPLICATION.processEvents()
            tree = find_widget(page, QTreeWidget, name)
            assert empty.isVisible()
            assert tree.rect().contains(
                tree.mapFromGlobal(empty.mapToGlobal(empty.rect().center()))
            )
        entry = parse_calendar(
            b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            b"UID:test\r\nSUMMARY:Lunch\r\nDTSTART:20261113T120000\r\n"
            b"END:VEVENT\r\nEND:VCALENDAR\r\n"
        ).entries[0]
        find_widget(page, MonthGrid, "calendarMonthGrid").setSelectedDate(
            QDate(2026, 11, 13)
        )
        controller.view = ExtrasCatalog(calendar=(CalendarItem("test.ics", entry),))
        controller.changed.emit()
        assert not empty.isVisible()
        assert find_widget(page, QTreeWidget, "calendarEvents").topLevelItemCount() == 1
    finally:
        page.close()


@pytest.mark.parametrize(("width", "height"), [(56, 48), (96, 64)])
def test_short_day_cells_keep_an_event_indicator(width: int, height: int) -> None:
    date = QDate(2026, 11, 7)
    grid = MonthGrid(today=QDate(2026, 11, 13))

    def render() -> QImage:
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        grid.paintCell(painter, QRect(0, 0, width, height), date)
        painter.end()
        return image

    try:
        without_event = render()
        grid.set_markers((CalendarMarker(date, date, "Lunch"),))
        assert render() != without_event
    finally:
        grid.close()
