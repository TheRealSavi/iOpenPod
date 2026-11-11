"""Structured inputs for the shared Calendar repeat and exception formats."""

from collections.abc import Callable

from PySide6.QtCore import QDate, QLocale, Qt, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from whenever import Date, Time

from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from iPodDB.calendar import (
    CalendarDayRule,
    CalendarFrequency,
    CalendarRecurrenceRule,
    CalendarWeekday,
)

_FREQUENCIES = tuple(CalendarFrequency)
_WEEKDAYS = tuple(CalendarWeekday)
_ORDINALS = (None, 1, 2, 3, 4, 5, -1, -2, -3, -4, -5)
_MONTH_DAYS = (*range(1, 32), *range(-1, -32, -1))


def _date(picker: QDateEdit) -> Date:
    value = picker.date()
    return Date(value.year(), value.month(), value.day())


def _setup_date_picker(picker: QDateEdit, date: Date) -> None:
    picker.setCalendarPopup(True)
    picker.setDateRange(QDate(1, 1, 1), QDate(2999, 12, 31))
    picker.setDate(QDate(date.year, date.month, date.day))


def _date_format() -> str:
    pattern = QLocale().dateFormat(QLocale.FormatType.ShortFormat)
    return pattern if "yyyy" in pattern else pattern.replace("yy", "yyyy")


def _label(form: QFormLayout, field: QWidget, text: str) -> None:
    label = form.labelForField(field)
    if isinstance(label, QLabel):
        label.setText(text)
        label.setBuddy(field)
    field.setAccessibleName(text)


class _RepeatList[T](QWidget):
    """Select a typed value and manage the list of values applied to a rule."""

    changed = Signal()

    def __init__(
        self,
        name: str,
        fields: tuple[QWidget, ...],
        read: Callable[[], T],
        describe: Callable[[T], str],
        values: tuple[T, ...],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(name)
        self._read = read
        self._describe = describe
        self._values = list(values)
        self._list = QListWidget(self)
        self._list.setObjectName(name + "List")
        self._list.setMaximumHeight(72)
        self._add = ActionButton(parent=self)
        self._add.setObjectName(name + "Add")
        self._add.setAutoDefault(False)
        self._remove = ActionButton(parent=self)
        self._remove.setObjectName(name + "Remove")
        self._remove.setAutoDefault(False)
        actions = QHBoxLayout()
        for field in fields:
            actions.addWidget(field, 1)
        actions.addWidget(self._add)
        selection = QHBoxLayout()
        selection.addWidget(self._list, 1)
        selection.addWidget(self._remove, alignment=Qt.AlignmentFlag.AlignTop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(actions)
        layout.addLayout(selection)
        self.setFocusProxy(fields[0])
        self._add.clicked.connect(self._add_value)
        self._remove.clicked.connect(self._remove_value)
        self._list.currentRowChanged.connect(self._selection_changed)

    def values(self) -> tuple[T, ...]:
        return tuple(self._values)

    def set_values(self, values: tuple[T, ...]) -> None:
        if values != self.values():
            self._values = list(values)
            self._refresh_rows()
            self.changed.emit()

    def retranslate_ui(self, label: str) -> None:
        self._list.setAccessibleName(label)
        self._add.setText(self.tr("Add"))
        self._remove.setText(self.tr("Remove"))
        self._add.setAccessibleName(self.tr("Add to {list}").format(list=label))
        self._remove.setAccessibleName(self.tr("Remove from {list}").format(list=label))
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        selected = self._list.currentRow()
        self._list.clear()
        self._list.addItems([self._describe(value) for value in self._values])
        self._list.setCurrentRow(min(selected, len(self._values) - 1))
        self._list.setVisible(bool(self._values))
        self._remove.setVisible(bool(self._values))
        self._selection_changed()

    def _selection_changed(self) -> None:
        self._remove.setEnabled(self._list.currentRow() >= 0)

    def _add_value(self) -> None:
        value = self._read()
        if value not in self._values:
            self.set_values((*self._values, value))
        self._list.setCurrentRow(self._values.index(value))

    def _remove_value(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self.set_values((*self._values[:row], *self._values[row + 1 :]))


class CalendarDateList(_RepeatList[Date]):
    """Choose civil dates to add to or exclude from the saved event."""

    def __init__(
        self, name: str, date: Date, values: tuple[Date, ...], parent: QWidget
    ) -> None:
        self._picker = QDateEdit(parent)
        self._picker.setObjectName(name + "Picker")
        _setup_date_picker(self._picker, date)
        super().__init__(
            name,
            (self._picker,),
            lambda: _date(self._picker),
            self._display,
            values,
            parent,
        )

    @staticmethod
    def _display(day: Date) -> str:
        return QLocale().toString(QDate(day.year, day.month, day.day), _date_format())

    def retranslate_ui(self, label: str) -> None:
        self._picker.setAccessibleName(label)
        self._picker.setDisplayFormat(_date_format())
        super().retranslate_ui(label)


class CalendarRepeatEditor(QWidget):
    """Edit one include or exclude rule, using the same supported selectors."""

    def __init__(
        self,
        name: str,
        date: Date,
        rule: CalendarRecurrenceRule | None,
        parent: QWidget,
        *,
        exclusion: bool = False,
        locked: bool = False,
        advanced_toggle: QCheckBox | None = None,
    ) -> None:
        super().__init__(parent)
        self._exclusion = exclusion
        self._locked = locked
        self._advanced = False
        self._form = QFormLayout(self)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.frequency = self._choice(name, 6 if locked else 5)
        self.interval = QSpinBox(self)
        self.interval.setObjectName(name + "Interval")
        self.interval.setRange(1, 1000)
        self.limit = self._choice(name + "Limit", 3)
        self.count = QSpinBox(self)
        self.count.setObjectName(name + "Count")
        self.count.setRange(1, 10000)
        self.count.setValue(3)
        until = rule.until if rule else None
        self.until = QDateEdit(self)
        self.until.setObjectName(name + "Until")
        _setup_date_picker(self.until, until.date() if until else date)
        self.until_time = QTimeEdit(self)
        self.until_time.setObjectName(name + "UntilTime")
        self.until_time.setDisplayFormat("HH:mm:ss")
        self.until_time.setTime(
            QTime(until.hour, until.minute, until.second)
            if until
            else QTime(23, 59, 59)
        )
        self._month_mode = self._choice(name + "MonthMode", 2)
        self._weekday = self._choice(name + "WeekdaysPicker", len(_WEEKDAYS))
        self._ordinal = self._choice(name + "WeekdaysOrdinal", len(_ORDINALS))
        for choice in (self._weekday, self._ordinal):
            choice.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            choice.setMinimumContentsLength(6)
        self._weekdays = _RepeatList(
            name + "Weekdays",
            (self._weekday, self._ordinal),
            self._picked_weekday,
            self._day_label,
            rule.weekdays if rule else (),
            self,
        )
        self._month_day = self._choice(name + "MonthDaysPicker", len(_MONTH_DAYS))
        self._month_days = _RepeatList(
            name + "MonthDays",
            (self._month_day,),
            lambda: _MONTH_DAYS[self._month_day.currentIndex()],
            self._month_day_label,
            rule.month_days if rule else (),
            self,
        )
        self._month = self._choice(name + "MonthsPicker", 12)
        self._months = _RepeatList(
            name + "Months",
            (self._month,),
            lambda: self._month.currentIndex() + 1,
            self._month_label,
            rule.months if rule else (),
            self,
        )
        self._week_start = self._choice(name + "WeekStart", 1 + len(_WEEKDAYS))
        self._last_weekday = QCheckBox(self)
        self._last_weekday.setObjectName(name + "LastWeekday")
        field: QWidget
        for field in (
            self.frequency,
            self.interval,
            self.limit,
            self.count,
            self.until,
            self.until_time,
        ):
            self._form.addRow(QLabel(self), field)
        if advanced_toggle is not None:
            self._form.addRow(advanced_toggle)
        for field in (
            self._month_mode,
            self._weekdays,
            self._month_days,
            self._months,
            self._week_start,
        ):
            self._form.addRow(QLabel(self), field)
        self._form.addRow(self._last_weekday)
        if rule is not None:
            self.frequency.setCurrentIndex(1 + _FREQUENCIES.index(rule.frequency))
            self.interval.setValue(rule.interval)
            if rule.count is not None:
                self.limit.setCurrentIndex(1)
                self.count.setValue(rule.count)
            elif until is not None:
                self.limit.setCurrentIndex(2)
            if rule.month_days:
                self._month_mode.setCurrentIndex(1)
            if rule.week_start is not None:
                self._week_start.setCurrentIndex(1 + _WEEKDAYS.index(rule.week_start))
            self._last_weekday.setChecked(rule.last_matching_weekday)
        elif locked:
            self.frequency.setCurrentIndex(len(_FREQUENCIES) + 1)
            self.frequency.setEnabled(False)
        self.frequency.currentIndexChanged.connect(self._update_controls)
        self.limit.currentIndexChanged.connect(self._update_controls)
        self._month_mode.currentIndexChanged.connect(self._update_controls)
        self._weekdays.changed.connect(self._update_controls)
        self._last_weekday.toggled.connect(self._update_controls)
        self._update_controls()

    def _choice(self, name: str, count: int) -> AppComboBox:
        combo = AppComboBox(self)
        combo.setObjectName(name)
        combo.addItems([""] * count)
        return combo

    def set_advanced(self, enabled: bool) -> None:
        self._advanced = enabled
        self._update_controls()

    def _frequency(self) -> CalendarFrequency | None:
        index = self.frequency.currentIndex()
        return _FREQUENCIES[index - 1] if 1 <= index <= len(_FREQUENCIES) else None

    def _update_controls(self) -> None:
        frequency = self._frequency()
        active = frequency is not None
        monthly = frequency is CalendarFrequency.MONTHLY
        weekly = frequency is CalendarFrequency.WEEKLY
        yearly = frequency is CalendarFrequency.YEARLY
        on_weekdays = self._month_mode.currentIndex() == 0
        weekdays = self._weekdays.values()
        if frequency in (CalendarFrequency.DAILY, CalendarFrequency.WEEKLY) and any(
            day.ordinal is not None for day in weekdays
        ):
            self._weekdays.set_values(
                tuple(dict.fromkeys(CalendarDayRule(day.weekday) for day in weekdays))
            )
        weekdays = self._weekdays.values()
        can_use_last = bool(weekdays) and all(day.ordinal is None for day in weekdays)
        if not can_use_last:
            self._last_weekday.setChecked(False)
        self._last_weekday.setEnabled(can_use_last)
        self._ordinal.setVisible(monthly and not self._last_weekday.isChecked())
        through = active and self.limit.currentIndex() == 2
        advanced = self._advanced and active
        for field, visible in (
            (self.interval, active),
            (self.limit, active),
            (self.count, active and self.limit.currentIndex() == 1),
            (self.until, through),
            (self.until_time, through),
            (self._month_mode, advanced and monthly),
            (self._weekdays, advanced and not yearly and (not monthly or on_weekdays)),
            (self._month_days, advanced and (yearly or (monthly and not on_weekdays))),
            (self._months, advanced and yearly),
            (self._week_start, advanced and weekly),
            (self._last_weekday, advanced and monthly and on_weekdays),
        ):
            self._form.setRowVisible(field, visible)

    def rule(self) -> CalendarRecurrenceRule | None:
        frequency = self._frequency()
        if frequency is None:
            return None
        monthly = frequency is CalendarFrequency.MONTHLY
        yearly = frequency is CalendarFrequency.YEARLY
        on_weekdays = self._month_mode.currentIndex() == 0
        limit = self.limit.currentIndex()
        time = self.until_time.time()
        week_start = self._week_start.currentIndex()
        return CalendarRecurrenceRule(
            frequency,
            interval=self.interval.value(),
            count=self.count.value() if limit == 1 else None,
            until=_date(self.until).at(Time(time.hour(), time.minute(), time.second()))
            if limit == 2
            else None,
            weekdays=self._weekdays.values()
            if not yearly and (not monthly or on_weekdays)
            else (),
            month_days=self._month_days.values()
            if yearly or (monthly and not on_weekdays)
            else (),
            months=self._months.values() if yearly else (),
            week_start=_WEEKDAYS[week_start - 1]
            if frequency is CalendarFrequency.WEEKLY and week_start
            else None,
            last_matching_weekday=monthly
            and on_weekdays
            and self._last_weekday.isChecked(),
        )

    def _picked_weekday(self) -> CalendarDayRule:
        ordinal = (
            _ORDINALS[self._ordinal.currentIndex()]
            if self._frequency() is CalendarFrequency.MONTHLY
            and not self._last_weekday.isChecked()
            else None
        )
        return CalendarDayRule(_WEEKDAYS[self._weekday.currentIndex()], ordinal)

    @staticmethod
    def _weekday_label(day: CalendarWeekday) -> str:
        return QLocale().dayName(1 + _WEEKDAYS.index(day))

    @staticmethod
    def _month_label(month: int) -> str:
        return QLocale().standaloneMonthName(month)

    def _month_day_label(self, day: int) -> str:
        number = QLocale().toString(abs(day))
        return self.tr("{number} from end").format(number=number) if day < 0 else number

    def _ordinal_label(self, ordinal: int) -> str:
        if ordinal == -1:
            return self.tr("Last")
        if ordinal < 0:
            return self.tr("{number} from end").format(
                number=QLocale().toString(-ordinal)
            )
        return (
            self.tr("First"),
            self.tr("Second"),
            self.tr("Third"),
            self.tr("Fourth"),
            self.tr("Fifth"),
        )[ordinal - 1]

    def _day_label(self, day: CalendarDayRule) -> str:
        weekday = self._weekday_label(day.weekday)
        if day.ordinal is None:
            return weekday
        return self.tr("{position} · {weekday}").format(
            position=self._ordinal_label(day.ordinal), weekday=weekday
        )

    def retranslate_ui(self) -> None:
        choices = (
            (
                self.frequency,
                (
                    self.tr("No exclusion rule")
                    if self._exclusion
                    else self.tr("Does not repeat"),
                    self.tr("Daily"),
                    self.tr("Weekly"),
                    self.tr("Monthly"),
                    self.tr("Yearly"),
                ),
            ),
            (
                self.limit,
                (
                    self.tr("No end date"),
                    self.tr("After a number of occurrences"),
                    self.tr("Through a date and time"),
                ),
            ),
            (
                self._month_mode,
                (self.tr("On weekdays"), self.tr("On days of the month")),
            ),
            (self._weekday, tuple(map(self._weekday_label, _WEEKDAYS))),
            (
                self._ordinal,
                (
                    self.tr("Any position"),
                    *(self._ordinal_label(n) for n in _ORDINALS if n is not None),
                ),
            ),
            (self._month_day, tuple(map(self._month_day_label, _MONTH_DAYS))),
            (self._month, tuple(self._month_label(month) for month in range(1, 13))),
            (
                self._week_start,
                (self.tr("Default"), *map(self._weekday_label, _WEEKDAYS)),
            ),
        )
        for combo, labels in choices:
            for index, text in enumerate(labels):
                combo.setItemText(index, text)
        if self._locked:
            self.frequency.setItemText(
                len(_FREQUENCIES) + 1, self.tr("Imported repeat")
            )
        for field, text in (
            (
                self.frequency,
                self.tr("Skip repeat rule") if self._exclusion else self.tr("Repeat"),
            ),
            (self.interval, self.tr("Every")),
            (self.limit, self.tr("Repeat ends")),
            (self.count, self.tr("Occurrences")),
            (self.until, self.tr("Through date")),
            (self.until_time, self.tr("Through time")),
            (self._month_mode, self.tr("Monthly selection")),
            (self._week_start, self.tr("Week starts on")),
        ):
            _label(self._form, field, text)
        for picker, label in (
            (self._weekdays, self.tr("Weekdays")),
            (self._month_days, self.tr("Days of month")),
            (self._months, self.tr("Months")),
        ):
            _label(self._form, picker, label)
        self._weekdays.retranslate_ui(self.tr("Weekdays"))
        self._month_days.retranslate_ui(self.tr("Days of month"))
        self._months.retranslate_ui(self.tr("Months"))
        self._weekday.setAccessibleName(self.tr("Weekday"))
        self._ordinal.setAccessibleName(self.tr("Position in the month"))
        self._month_day.setAccessibleName(self.tr("Day of month"))
        self._month.setAccessibleName(self.tr("Month"))
        self._last_weekday.setText(
            self.tr("Use only the last matching weekday of each month")
        )
        self.until.setDisplayFormat(_date_format())
