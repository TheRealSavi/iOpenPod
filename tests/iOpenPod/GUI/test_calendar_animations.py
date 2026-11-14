"""Calendar motion preserves live selection, direction and interruption behavior."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import (
    QAbstractAnimation,
    QDate,
    QEvent,
    QRect,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QProxyStyle,
    QStyle,
    QStyleHintReturn,
    QStyleOption,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.extras_test_support import ExtrasTestController, find_widget

from iOpenPod.GUI.pages.calendar_page import CalendarPage
from iOpenPod.GUI.widgets.calendar_month import MonthGrid
from iOpenPod.GUI.widgets.calendar_tabs import CalendarTabs


def _pause(owner: QWidget, name: str) -> QVariantAnimation:
    animation = find_widget(owner, QVariantAnimation, name)
    if animation.state() == QAbstractAnimation.State.Running:
        animation.pause()
    return animation


def _day_fill(month: MonthGrid, date: QDate) -> QColor:
    """Sample the painted highlight away from the date, border and focus ring."""
    image = QImage(120, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    month.paintCell(painter, QRect(0, 0, 120, 100), date)
    painter.end()
    return image.pixelColor(60, 70)


def _assert_half_blend(actual: QColor, start: QColor, end: QColor) -> None:
    for value, before, after in (
        (actual.red(), start.red(), end.red()),
        (actual.green(), start.green(), end.green()),
        (actual.blue(), start.blue(), end.blue()),
        (actual.alpha(), start.alpha(), end.alpha()),
    ):
        assert value == pytest.approx((before + after) / 2, abs=1)


@pytest.fixture
def month() -> Iterator[MonthGrid]:
    month = MonthGrid(today=QDate(2026, 11, 13))
    month.resize(800, 600)
    month.show()
    APPLICATION.processEvents()
    yield month
    month.close()


def test_day_highlights_crossfade_and_retarget_without_a_jump(month: MonthGrid) -> None:
    first, second, third = (QDate(2026, 11, day) for day in (13, 14, 15))
    selected, unselected = _day_fill(month, first), _day_fill(month, second)
    assert selected != unselected
    month.setSelectedDate(second)
    fade = _pause(month, "calendarDaySelectionFade")
    assert month.selectedDate() == second
    assert _day_fill(month, first) == selected
    assert _day_fill(month, second) == unselected
    fade.setCurrentTime(fade.duration() // 2)
    before = {day: _day_fill(month, day) for day in (first, second, third)}
    _assert_half_blend(before[first], selected, unselected)
    _assert_half_blend(before[second], unselected, selected)
    month.setSelectedDate(third)
    fade = _pause(month, "calendarDaySelectionFade")
    for day, color in before.items():
        assert _day_fill(month, day) == color
    fade.setCurrentTime(fade.duration() // 2)
    for day in (first, second):
        _assert_half_blend(_day_fill(month, day), before[day], unselected)
    _assert_half_blend(_day_fill(month, third), unselected, selected)
    fade.setCurrentTime(fade.duration())
    assert month.selectedDate() == third
    assert _day_fill(month, third) == selected
    assert all(_day_fill(month, day) == unselected for day in (first, second))


@pytest.mark.parametrize("interrupt", ["hide", "resize", "theme"])
def test_day_fade_interruption_keeps_the_selected_date(
    month: MonthGrid, interrupt: str
) -> None:
    date = QDate(2026, 11, 14)
    selected = _day_fill(month, month.selectedDate())
    month.setSelectedDate(date)
    fade = _pause(month, "calendarDaySelectionFade")
    fade.setCurrentTime(fade.duration() // 2)
    if interrupt == "hide":
        month.hide()
    elif interrupt == "resize":
        month.resize(900, 600)
    else:
        APPLICATION.sendEvent(month, QEvent(QEvent.Type.PaletteChange))
    assert fade.state() == QAbstractAnimation.State.Stopped
    assert month.selectedDate() == date
    assert _day_fill(month, date) == selected


class _ColorPage(QWidget):
    def __init__(self, color: str) -> None:
        super().__init__()
        self.color = QColor(color)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.color)


@pytest.fixture
def tabs() -> Iterator[CalendarTabs]:
    tabs = CalendarTabs()
    tabs.addTab(_ColorPage("red"), "Calendar")
    tabs.addTab(_ColorPage("blue"), "To Dos")
    tabs.resize(700, 450)
    tabs.show()
    APPLICATION.processEvents()
    yield tabs
    tabs.close()


@pytest.mark.parametrize("target", [1, 0])
def test_content_swipes_in_the_requested_direction(
    tabs: CalendarTabs, target: int
) -> None:
    if target == 0:
        tabs.setCurrentIndex(1)
        tabs.cancel_transition()
    bar = tabs.tabBar()
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(target).center())
    assert tabs.currentIndex() == target
    swipe = find_widget(tabs, QWidget, "calendarContentSwipe")
    old_color = QColor("red" if target else "blue")
    assert swipe.grab().toImage().pixelColor(30, 30) == old_color
    APPLICATION.processEvents()
    animation = _pause(tabs, "calendarContentSlide")
    animation.setCurrentTime(animation.duration() // 2)
    image = swipe.grab().toImage()
    assert image.pixelColor(image.width() // 4, image.height() // 2) == QColor("blue")
    assert image.pixelColor(image.width() * 3 // 4, image.height() // 2) == QColor(
        "red"
    )
    animation.setCurrentTime(animation.duration())
    assert not swipe.isVisible()
    assert tabs.currentIndex() == target


def test_fast_tab_reversal_starts_from_the_visible_frame(tabs: CalendarTabs) -> None:
    tabs.setCurrentIndex(1)
    APPLICATION.processEvents()
    animation = _pause(tabs, "calendarContentSlide")
    animation.setCurrentTime(animation.duration() // 2)
    swipe = find_widget(tabs, QWidget, "calendarContentSwipe")
    before = swipe.grab().toImage()
    tabs.setCurrentIndex(0)
    assert swipe.grab().toImage() == before
    APPLICATION.processEvents()
    animation = _pause(tabs, "calendarContentSlide")
    animation.setCurrentTime(animation.duration())
    assert not swipe.isVisible()
    assert tabs.currentIndex() == 0


def test_toggle_indicator_slides_and_supports_keyboard_reversal(
    tabs: CalendarTabs,
) -> None:
    bar = tabs.tabBar()
    bar.setFocus()
    QTest.keyClick(bar, Qt.Key.Key_Right)
    animation = _pause(tabs, "calendarTabSelectionSlide")
    start, end = animation.startValue(), animation.endValue()
    assert isinstance(start, QRectF) and isinstance(end, QRectF)
    assert start.x() < end.x()
    animation.setCurrentTime(animation.duration() // 2)
    middle = animation.currentValue()
    assert isinstance(middle, QRectF)
    assert start.x() < middle.x() < end.x()
    QTest.keyClick(bar, Qt.Key.Key_Left)
    assert animation.startValue() == middle
    assert tabs.currentIndex() == 0
    animation = _pause(tabs, "calendarTabSelectionSlide")
    animation.setCurrentTime(animation.duration())
    assert animation.currentValue() == animation.endValue()


@pytest.mark.parametrize("interrupt", ["hide", "resize", "theme"])
def test_content_swipe_interruption_reveals_the_current_page(
    tabs: CalendarTabs, interrupt: str
) -> None:
    tabs.setCurrentIndex(1)
    APPLICATION.processEvents()
    animation = _pause(tabs, "calendarContentSlide")
    swipe = find_widget(tabs, QWidget, "calendarContentSwipe")
    assert swipe.isVisible()
    if interrupt == "hide":
        tabs.hide()
    elif interrupt == "resize":
        tabs.resize(750, 450)
    else:
        APPLICATION.sendEvent(tabs, QEvent(QEvent.Type.PaletteChange))
    assert not swipe.isVisible()
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert tabs.currentIndex() == 1


class _NoAnimationStyle(QProxyStyle):
    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
        returnData: QStyleHintReturn | None = None,  # noqa: N803 - Qt keyword name
    ) -> int:
        if hint == QStyle.StyleHint.SH_Widget_Animate:
            return 0
        return super().styleHint(hint, option, widget, returnData)


def test_host_disabled_motion_updates_calendar_immediately(
    month: MonthGrid, tabs: CalendarTabs
) -> None:
    for widget in (month, tabs, tabs.tabBar()):
        style = _NoAnimationStyle("Fusion")
        style.setParent(widget)
        widget.setStyle(style)
    date = QDate(2026, 11, 14)
    selected = _day_fill(month, month.selectedDate())
    month.setSelectedDate(date)
    tabs.setCurrentIndex(1)
    APPLICATION.processEvents()
    assert month.selectedDate() == date
    assert _day_fill(month, date) == selected
    for owner, name in [
        (month, "calendarDaySelectionFade"),
        (tabs, "calendarContentSlide"),
        (tabs, "calendarTabSelectionSlide"),
    ]:
        assert _pause(owner, name).state() == QAbstractAnimation.State.Stopped
    assert not find_widget(tabs, QWidget, "calendarContentSwipe").isVisible()


def test_device_updates_discard_old_calendar_frames() -> None:
    controller = ExtrasTestController()
    page = CalendarPage(controller)
    try:
        page.resize(1000, 700)
        page.show()
        APPLICATION.processEvents()
        tabs = find_widget(page, CalendarTabs, "calendarTabs")
        tabs.setCurrentIndex(1)
        swipe = find_widget(tabs, QWidget, "calendarContentSwipe")
        assert swipe.isVisible()
        controller.current = None
        controller.changed.emit()
        assert not swipe.isVisible()
    finally:
        page.close()
