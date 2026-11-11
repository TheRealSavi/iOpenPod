"""Repeat and saved reminder controls for Calendar event drafts."""

from PySide6.QtCore import QDate, QEvent, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTimeEdit,
    QWidget,
)
from whenever import Date, Instant, PlainDateTime

from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.calendar_repeat_editor import (
    CalendarDateList,
    CalendarRepeatEditor,
)
from iPodDB.calendar import (
    UNCHANGED,
    CalendarEditError,
    CalendarEntry,
    CalendarEntryKind,
    CalendarExceptions,
    CalendarRecurrenceRule,
    CalendarReminderDraft,
    Unchanged,
    editable_reminder,
    recurrence_exceptions,
    recurrence_rule,
    validate_calendar_recurrence,
    validate_calendar_reminder,
    validate_exceptions,
)

_ABSOLUTE = 4


class CalendarOptions(QWidget):
    """Edit recognized event options and keep other imported properties intact."""

    def __init__(
        self,
        entry: CalendarEntry | None,
        kind: CalendarEntryKind,
        initial_date: Date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entry = entry
        rule = recurrence_rule(entry) if entry else None
        self._reminder = editable_reminder(entry) if entry else None
        event = kind is CalendarEntryKind.EVENT
        properties: set[str] = (
            {prop.name for prop in entry.component.properties} if entry else set()
        )
        can_edit_repeats = event and not ({"DURATION", "RECURRENCE-ID"} & properties)
        self._can_repeat = can_edit_repeats and (
            "RRULE" not in properties or rule is not None
        )
        self._can_exceptions = can_edit_repeats
        exceptions = CalendarExceptions()
        if entry is not None and self._can_exceptions:
            try:
                saved = recurrence_exceptions(entry)
                if saved != CalendarExceptions():
                    validate_exceptions(
                        saved,
                        entry.start.value if entry.start else None,
                        entry.end.value if entry.end else None,
                    )
                exceptions = saved
            except ValueError:
                self._can_exceptions = False
        self._can_remind = event and (
            entry is None
            or (
                entry.start is not None
                and entry.start.value is not None
                and (not entry.reminders or self._reminder is not None)
            )
        )

        self._form = QFormLayout(self)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.advanced = QCheckBox(self)
        self.advanced.setObjectName("calendarAdvancedRepeat")
        self._repeat = CalendarRepeatEditor(
            "calendarRepeat",
            initial_date,
            rule if self._can_repeat else None,
            self,
            locked="RRULE" in properties and not self._can_repeat,
            advanced_toggle=self.advanced,
        )
        self._repeat.frequency.setEnabled(self._can_repeat)
        self.added_dates = CalendarDateList(
            "calendarAddedDates", initial_date, exceptions.added, self
        )
        self.excluded_dates = CalendarDateList(
            "calendarExcludedDates", initial_date, exceptions.excluded, self
        )
        self._exclusion = CalendarRepeatEditor(
            "calendarExclusionRule",
            initial_date,
            exceptions.exclusion_rule,
            self,
            exclusion=True,
        )
        self.advanced.setChecked(
            exceptions != CalendarExceptions()
            or bool(
                rule
                and (rule.weekdays or rule.month_days or rule.months or rule.week_start)
            )
        )
        self._form.addRow(self._repeat)
        self._form.addRow(QLabel(self), self.added_dates)
        self._form.addRow(QLabel(self), self.excluded_dates)
        self._form.addRow(self._exclusion)

        self.reminder = QCheckBox(self)
        self.reminder.setObjectName("calendarReminder")
        self.reminder_mode = AppComboBox(self)
        self.reminder_mode.setObjectName("calendarReminderMode")
        self.reminder_mode.addItems([""] * 5)
        self.minutes = QSpinBox(self)
        self.minutes.setObjectName("calendarReminderMinutes")
        self.minutes.setRange(0, (1 << 31) // 60)
        self.seconds = QSpinBox(self)
        self.seconds.setObjectName("calendarReminderSeconds")
        self.seconds.setRange(0, 59)
        saved_absolute = self._reminder.absolute_trigger if self._reminder else None
        civil = (
            saved_absolute.to_tz("UTC").to_plain()
            if isinstance(saved_absolute, Instant)
            else saved_absolute
        )
        self.reminder_date = self._date_picker(
            civil.date() if civil else initial_date, "calendarReminderDate"
        )
        self.reminder_time = QTimeEdit(self)
        self.reminder_time.setObjectName("calendarReminderTime")
        self.reminder_time.setDisplayFormat("HH:mm:ss")
        self.reminder_time.setTime(
            QTime(civil.hour, civil.minute, civil.second) if civil else QTime(9, 0)
        )
        self.reminder_utc = QCheckBox("UTC", self)
        self.reminder_utc.setChecked(isinstance(saved_absolute, Instant))
        offset = self._reminder.relative_seconds if self._reminder else -900
        minutes, seconds = divmod(abs(offset or 0), 60)
        self.minutes.setValue(minutes)
        self.seconds.setValue(seconds)
        if saved_absolute is not None:
            self.reminder_mode.setCurrentIndex(_ABSOLUTE)
        elif self._reminder is not None:
            self.reminder_mode.setCurrentIndex(
                2 * self._reminder.related_to_end + ((offset or 0) > 0)
            )
        self.reminder.setChecked(bool(entry and entry.reminders))
        self.reminder.setEnabled(self._can_remind)
        self._form.addRow(self.reminder)
        for widget in (
            self.reminder_mode,
            self.minutes,
            self.seconds,
            self.reminder_date,
            self.reminder_time,
        ):
            self._form.addRow(QLabel(self), widget)
        self._form.addRow(self.reminder_utc)
        self._note = QLabel(self)
        self._note.setObjectName("calendarOptionsNote")
        self._note.setWordWrap(True)
        self._form.addRow(self._note)
        self.setVisible(event)
        self._repeat.frequency.currentIndexChanged.connect(self._update_controls)
        self.advanced.toggled.connect(self._update_controls)
        self.reminder.toggled.connect(self._update_controls)
        self.reminder_mode.currentIndexChanged.connect(self._update_controls)
        self._update_controls()
        self._initial_repeat = self._repeat.rule()
        self._initial_exceptions = self._exceptions()
        self._initial_reminder = self._reminder_snapshot()
        self.retranslate_ui()

    def _date_picker(self, day: Date, name: str) -> QDateEdit:
        picker = QDateEdit(self)
        picker.setObjectName(name)
        picker.setCalendarPopup(True)
        picker.setDateRange(QDate(100, 1, 1), QDate(9999, 12, 31))
        picker.setDate(QDate(day.year, day.month, day.day))
        return picker

    def retranslate_ui(self) -> None:
        self._repeat.retranslate_ui()
        self._exclusion.retranslate_ui()
        self.added_dates.retranslate_ui(self.tr("Added repeat dates"))
        self.excluded_dates.retranslate_ui(self.tr("Skipped repeat dates"))
        for index, text in enumerate(
            (
                self.tr("Before start"),
                self.tr("After start"),
                self.tr("Before end"),
                self.tr("After end"),
                self.tr("At a date and time"),
            )
        ):
            self.reminder_mode.setItemText(index, text)
        for widget, text in (
            (self.added_dates, self.tr("Added repeat dates")),
            (self.excluded_dates, self.tr("Skipped repeat dates")),
            (self.reminder_mode, self.tr("Remind me")),
            (self.minutes, self.tr("Minutes")),
            (self.seconds, self.tr("Seconds")),
            (self.reminder_date, self.tr("Date")),
            (self.reminder_time, self.tr("Time")),
        ):
            label = self._form.labelForField(widget)
            if isinstance(label, QLabel):
                label.setText(text)
                label.setBuddy(widget)
        self.advanced.setText(self.tr("Advanced repeat options"))
        self.reminder.setText(self.tr("Saved reminder"))
        notes: list[str] = []
        if self._entry and self._entry.reminders and not self._can_remind:
            notes.append(self.tr("This imported reminder is preserved."))
        if self._entry and self._entry.recurrence and not self._can_repeat:
            notes.append(self.tr("This imported repeat rule is preserved."))
        if (
            self._entry
            and not self._can_exceptions
            and any(
                prop.name in {"RDATE", "EXDATE", "EXRULE"}
                for prop in self._entry.component.properties
            )
        ):
            notes.append(self.tr("These imported repeat exceptions are preserved."))
        self._note.setText("\n".join(notes))
        self._note.setVisible(bool(self._note.text()))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _update_controls(self) -> None:
        repeating = self._can_repeat and self._repeat.rule() is not None
        advanced = self.advanced.isChecked()
        self.advanced.setVisible(repeating or self._can_exceptions)
        self._repeat.set_advanced(advanced)
        self._exclusion.set_advanced(advanced)
        widget: QWidget
        for widget in (self.added_dates, self.excluded_dates, self._exclusion):
            self._form.setRowVisible(widget, advanced and self._can_exceptions)
        enabled = self._can_remind and self.reminder.isChecked()
        absolute = self.reminder_mode.currentIndex() == _ABSOLUTE
        self._form.setRowVisible(self.reminder_mode, enabled)
        for widget in (self.minutes, self.seconds):
            self._form.setRowVisible(widget, enabled and not absolute)
        for widget in (self.reminder_date, self.reminder_time, self.reminder_utc):
            self._form.setRowVisible(widget, enabled and absolute)

    def _exceptions(self) -> CalendarExceptions:
        return CalendarExceptions(
            tuple(sorted(self.added_dates.values())),
            tuple(sorted(self.excluded_dates.values())),
            self._exclusion.rule(),
        )

    def _reminder_snapshot(self) -> tuple[object, ...]:
        return (
            self.reminder.isChecked(),
            self.reminder_mode.currentIndex(),
            self.minutes.value(),
            self.seconds.value(),
            self.reminder_date.date().toJulianDay(),
            self.reminder_time.time().msecsSinceStartOfDay(),
            self.reminder_utc.isChecked(),
        )

    def recurrence_change(self) -> CalendarRecurrenceRule | Unchanged | None:
        rule = self._repeat.rule()
        return rule if self._can_repeat and rule != self._initial_repeat else UNCHANGED

    def exceptions_change(self) -> CalendarExceptions | Unchanged:
        values = self._exceptions()
        return (
            values
            if self._can_exceptions and values != self._initial_exceptions
            else UNCHANGED
        )

    def reminder_change(self) -> CalendarReminderDraft | Unchanged | None:
        if not self._can_remind or self._reminder_snapshot() == self._initial_reminder:
            return UNCHANGED
        if not self.reminder.isChecked():
            return None
        mode = self.reminder_mode.currentIndex()
        if mode == _ABSOLUTE:
            day, time = self.reminder_date.date(), self.reminder_time.time()
            value = PlainDateTime(
                day.year(),
                day.month(),
                day.day(),
                time.hour(),
                time.minute(),
                time.second(),
            )
            return CalendarReminderDraft(
                absolute_trigger=value.assume_utc()
                if self.reminder_utc.isChecked()
                else value
            )
        offset = self.minutes.value() * 60 + self.seconds.value()
        return CalendarReminderDraft(
            offset if mode % 2 else -offset, related_to_end=mode >= 2
        )

    def validation_error(self, start: object, end: object) -> str:
        try:
            repeat = self.recurrence_change()
            exceptions = self.exceptions_change()
            reminder = self.reminder_change()
            if isinstance(repeat, CalendarRecurrenceRule):
                validate_calendar_recurrence(repeat, start, end)
            if isinstance(exceptions, CalendarExceptions):
                validate_exceptions(exceptions, start, end)
            if isinstance(reminder, CalendarReminderDraft):
                if start is None:
                    raise CalendarEditError(
                        self.tr("Choose an event start for the reminder.")
                    )
                validate_calendar_reminder(reminder, has_end=end is not None)
        except ValueError as error:
            return str(error)
        return ""
