"""Firmware-qualified recurrence and saved reminder controls for event drafts."""

from PySide6.QtCore import QDate, QEvent
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFormLayout,
    QLabel,
    QSpinBox,
    QWidget,
)
from whenever import Date, PlainDateTime, Time

from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iPodDB.calendar import (
    UNCHANGED,
    CalendarDateForm,
    CalendarEditError,
    CalendarEntry,
    CalendarEntryKind,
    CalendarFrequency,
    CalendarProfile,
    CalendarRecurrenceRule,
    CalendarReminderDraft,
    Unchanged,
    editable_reminder,
    recurrence_rule,
    supports_recurrence,
    supports_reminders,
    validate_calendar_recurrence,
    validate_calendar_reminder,
)


class CalendarOptions(QWidget):
    """Preserve unsupported source state and emit only explicitly changed options."""

    def __init__(
        self,
        profile: CalendarProfile,
        entry: CalendarEntry | None,
        kind: CalendarEntryKind,
        initial_date: Date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self._entry = entry
        self._rule = recurrence_rule(entry, profile) if entry else None
        self._reminder = editable_reminder(entry, profile) if entry else None
        event = kind is CalendarEntryKind.EVENT
        floating = entry is None or bool(
            entry.start and entry.start.form is CalendarDateForm.FLOATING
        )
        self._can_repeat = (
            event
            and supports_recurrence(profile)
            and floating
            and (entry is None or not entry.has_recurrence or self._rule is not None)
        )
        self._can_remind = (
            event
            and supports_reminders(profile)
            and floating
            and (entry is None or not entry.reminders or self._reminder is not None)
        )
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.frequency = AppComboBox(self)
        self.frequency.setObjectName("calendarRepeat")
        self.frequency.addItems(
            [self.tr("Does not repeat"), self.tr("Daily"), self.tr("Weekly")]
        )
        self.interval = QSpinBox(self)
        self.interval.setObjectName("calendarRepeatInterval")
        self.interval.setRange(1, 1000)
        self.limit = AppComboBox(self)
        self.limit.setObjectName("calendarRepeatLimit")
        self.limit.addItems(
            [
                self.tr("Firmware default end"),
                self.tr("After a number of occurrences"),
                self.tr("Through a date"),
            ]
        )
        self.count = QSpinBox(self)
        self.count.setObjectName("calendarRepeatCount")
        self.count.setRange(1, 10000)
        self.count.setValue(3)
        self.until = QDateEdit(self)
        self.until.setObjectName("calendarRepeatUntil")
        self.until.setCalendarPopup(True)
        self.until.setDateRange(QDate(100, 1, 1), QDate(2999, 12, 31))
        self.until.setDate(
            QDate(initial_date.year, initial_date.month, initial_date.day)
        )
        if self._rule is not None:
            rule = self._rule
            self.frequency.setCurrentIndex(
                1 if rule.frequency is CalendarFrequency.DAILY else 2
            )
            self.interval.setValue(rule.interval)
            if rule.count is not None:
                self.limit.setCurrentIndex(1)
                self.count.setValue(rule.count)
            elif rule.until is not None:
                self.limit.setCurrentIndex(2)
                self.until.setDate(
                    QDate(rule.until.year, rule.until.month, rule.until.day)
                )
        if entry is not None and entry.has_recurrence and self._rule is None:
            self.frequency.addItem(self.tr("Imported repeat (preserved)"))
            self.frequency.setCurrentIndex(3)
        repeat_widgets = (
            (self.tr("Repeat"), self.frequency),
            (self.tr("Every"), self.interval),
            (self.tr("Repeat ends"), self.limit),
            (self.tr("Occurrences"), self.count),
            (self.tr("Through"), self.until),
        )
        for text, widget in repeat_widgets:
            layout.addRow(text, widget)
            widget.setEnabled(self._can_repeat)
            widget.setVisible(supports_recurrence(profile) and event)
            label = layout.labelForField(widget)
            label.setVisible(supports_recurrence(profile) and event)
        self.reminder = QCheckBox(self.tr("Saved reminder before event start"), self)
        self.reminder.setObjectName("calendarReminder")
        self.minutes = QSpinBox(self)
        self.minutes.setObjectName("calendarReminderMinutes")
        self.minutes.setRange(0, 10080)
        self.minutes.setValue(self._reminder.minutes_before if self._reminder else 15)
        self.reminder.setChecked(
            bool(self._reminder is not None or (entry and entry.reminders))
        )
        layout.addRow(self.reminder)
        layout.addRow(self.tr("Minutes before start"), self.minutes)
        for reminder_widget in (self.reminder, self.minutes):
            reminder_widget.setEnabled(self._can_remind)
            reminder_widget.setVisible(supports_reminders(profile) and event)
        reminder_label = layout.labelForField(self.minutes)
        reminder_label.setVisible(supports_reminders(profile) and event)
        note = QLabel(self)
        note.setWordWrap(True)
        note.setObjectName("calendarFirmwareNote")
        self._note = note
        note.setVisible(event)
        layout.addRow(note)
        self._form = layout
        self._show_repeats = supports_recurrence(profile) and event
        self.frequency.currentIndexChanged.connect(self._update_controls)
        self.limit.currentIndexChanged.connect(self._update_controls)
        self.reminder.toggled.connect(self._update_controls)
        self._update_controls()
        self._initial_repeat = self._repeat_snapshot()
        self._initial_reminder = self._reminder_snapshot()
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        for index, text in enumerate(
            (self.tr("Does not repeat"), self.tr("Daily"), self.tr("Weekly"))
        ):
            self.frequency.setItemText(index, text)
        if self.frequency.count() > 3:
            self.frequency.setItemText(3, self.tr("Imported repeat (preserved)"))
        for index, text in enumerate(
            (
                self.tr("Firmware default end"),
                self.tr("After a number of occurrences"),
                self.tr("Through a date"),
            )
        ):
            self.limit.setItemText(index, text)
        for field, text in (
            (self.frequency, self.tr("Repeat")),
            (self.interval, self.tr("Every")),
            (self.limit, self.tr("Repeat ends")),
            (self.count, self.tr("Occurrences")),
            (self.until, self.tr("Through")),
            (self.minutes, self.tr("Minutes before start")),
        ):
            label = self._form.labelForField(field)
            if isinstance(label, QLabel):
                label.setText(text)
        self.reminder.setText(self.tr("Saved reminder before event start"))
        notes: list[str] = []
        if supports_recurrence(self._profile):
            notes.append(
                self.tr(
                    "Daily/weekly repeats require floating start and end times on the same day, before year 3000. All-day, zoned and complex repeats are preserved."
                )
            )
        if supports_reminders(self._profile):
            notes.append(
                self.tr(
                    "One saved reminder before a floating event's start is supported. This does not confirm live adoption, sound or physical delivery."
                )
            )
        if not notes:
            notes.append(
                self.tr(
                    "Repeat and reminder editing are not qualified for this firmware. Imported settings are preserved."
                )
            )
        self._note.setText("\n\n".join(notes))
        if self.isVisible():
            self._fit_note()

    def _fit_note(self) -> None:
        self._note.setMinimumHeight(
            max(0, self._note.heightForWidth(max(1, self.width())))
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_note"):
            self._fit_note()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _update_controls(self) -> None:
        repeating = self._can_repeat and self.frequency.currentIndex() in (1, 2)
        for field in (self.interval, self.limit, self.count, self.until):
            field.setEnabled(repeating)
        for field, visible in (
            (self.count, self.limit.currentIndex() == 1),
            (self.until, self.limit.currentIndex() == 2),
        ):
            field.setVisible(self._show_repeats and visible and repeating)
            self._form.labelForField(field).setVisible(
                self._show_repeats and visible and repeating
            )
        self.minutes.setEnabled(self._can_remind and self.reminder.isChecked())
        if not self._can_remind:
            self.minutes.hide()
            self._form.labelForField(self.minutes).hide()

    def _repeat_snapshot(self) -> tuple[int, int, int, int, int]:
        return (
            self.frequency.currentIndex(),
            self.interval.value(),
            self.limit.currentIndex(),
            self.count.value(),
            self.until.date().toJulianDay(),
        )

    def _reminder_snapshot(self) -> tuple[bool, int]:
        return self.reminder.isChecked(), self.minutes.value()

    def recurrence_change(self) -> CalendarRecurrenceRule | Unchanged | None:
        if not self._can_repeat or self._repeat_snapshot() == self._initial_repeat:
            return UNCHANGED
        if self.frequency.currentIndex() == 0:
            return None
        until = None
        if self.limit.currentIndex() == 2:
            date = self.until.date()
            until = Date(date.year(), date.month(), date.day()).at(Time(23, 59, 59))
            if (
                self._rule
                and self._rule.until
                and until.date() == self._rule.until.date()
            ):
                until = self._rule.until
        return CalendarRecurrenceRule(
            CalendarFrequency.DAILY
            if self.frequency.currentIndex() == 1
            else CalendarFrequency.WEEKLY,
            self.interval.value(),
            self.count.value() if self.limit.currentIndex() == 1 else None,
            until,
        )

    def reminder_change(self) -> CalendarReminderDraft | Unchanged | None:
        if not self._can_remind or self._reminder_snapshot() == self._initial_reminder:
            return UNCHANGED
        return (
            CalendarReminderDraft(self.minutes.value())
            if self.reminder.isChecked()
            else None
        )

    def validation_error(self, start: object, end: object) -> str:
        try:
            repeat = self.recurrence_change()
            reminder = self.reminder_change()
            if isinstance(repeat, CalendarRecurrenceRule):
                validate_calendar_recurrence(repeat, self._profile, start, end)
            if isinstance(reminder, CalendarReminderDraft):
                if not isinstance(start, PlainDateTime):
                    raise CalendarEditError(
                        self.tr("Saved reminders require a floating event start.")
                    )
                validate_calendar_reminder(
                    reminder, self._profile, has_end=end is not None
                )
        except ValueError as error:
            return str(error)
        return ""
