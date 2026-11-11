"""Saved Calendar Reminder validation and evaluation in civil time."""

from typing import cast

from whenever import Date, Instant, PlainDateTime, Time

from iPodDB.calendar.models import (
    CalendarEditError,
    CalendarEntry,
    CalendarEntryKind,
    CalendarOccurrence,
    CalendarReminder,
    CalendarReminderDraft,
)


def validate_reminder(reminder: CalendarReminderDraft, *, has_end: bool) -> None:
    relative = reminder.relative_seconds
    absolute = reminder.absolute_trigger
    if absolute is not None:
        if (
            not isinstance(cast("object", absolute), (PlainDateTime, Instant))
            or relative is not None
            or reminder.related_to_end
            or (
                absolute.to_tz("UTC").nanosecond
                if isinstance(absolute, Instant)
                else absolute.nanosecond
            )
            != 0
        ):
            raise CalendarEditError(
                "Choose a single absolute reminder at a whole second."
            )
    elif type(relative) is not int or not -(1 << 31) <= relative < (1 << 31):
        raise CalendarEditError("The reminder offset exceeds the supported range.")
    elif reminder.related_to_end and not has_end:
        raise CalendarEditError("A reminder relative to the end needs an event end.")


def editable_reminder(entry: CalendarEntry) -> CalendarReminderDraft | None:
    if (
        not entry.editable
        or entry.kind is not CalendarEntryKind.EVENT
        or entry.start is None
        or entry.start.value is None
        or len(entry.reminders) != 1
    ):
        return None
    saved = entry.reminders[0]
    if saved.issues or saved.component.children:
        return None
    absolute = saved.absolute_trigger.value if saved.absolute_trigger else None
    if saved.absolute_trigger is not None and not isinstance(
        absolute, (PlainDateTime, Instant)
    ):
        return None
    draft = CalendarReminderDraft(
        saved.relative_seconds,
        saved.related_to_end,
        absolute if isinstance(absolute, (PlainDateTime, Instant)) else None,
    )
    try:
        validate_reminder(
            draft, has_end=entry.end is not None and entry.end.value is not None
        )
    except CalendarEditError:
        return None
    return draft


def reminder_civil_time(
    reminder: CalendarReminder, occurrence: CalendarOccurrence
) -> PlainDateTime | None:
    """Evaluate a stored trigger against the given source or occurrence span."""
    if reminder.issues:
        return None
    anchor = reminder.absolute_trigger or (
        occurrence.end if reminder.related_to_end else occurrence.start
    )
    if anchor is None or anchor.value is None:
        return None
    value = anchor.value
    if isinstance(value, Instant):
        value = value.to_tz("UTC").to_plain()
    elif isinstance(value, Date):
        value = value.at(Time(0))
    if reminder.absolute_trigger is not None:
        return value
    if reminder.relative_seconds is None:
        return None
    try:
        return value.add(seconds=reminder.relative_seconds, naive_arithmetic_ok=True)
    except (ValueError, OverflowError):
        return None
