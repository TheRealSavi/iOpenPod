"""Qualified single relative Calendar Reminders, with exact firmware profiles."""

from iPodDB.calendar.models import (
    CalendarDateForm,
    CalendarEditError,
    CalendarEntry,
    CalendarEntryKind,
    CalendarProfile,
    CalendarReminderDraft,
)

_TARGETS = frozenset(
    (
        CalendarProfile.MINI_1_1_4_1,
        CalendarProfile.MINI_2_1_4_1,
        CalendarProfile.NANO_1_1_3_1,
        CalendarProfile.NANO_3_1_1_3,
        CalendarProfile.NANO_4_1_0_4,
        CalendarProfile.NANO_5_1_0_2,
        CalendarProfile.VIDEO_1_3,
        CalendarProfile.CLASSIC_6_1_1_2,
        CalendarProfile.CLASSIC_120GB_2_0_1,
        CalendarProfile.CLASSIC_UPDATER_35_2_0_4,
        CalendarProfile.CLASSIC_UPDATER_38_2_0_5,
    )
)


def supports_reminders(profile: CalendarProfile) -> bool:
    return type(profile) is CalendarProfile and profile in _TARGETS


def validate_reminder(
    reminder: CalendarReminderDraft, profile: CalendarProfile, *, has_end: bool
) -> None:
    if not supports_reminders(profile):
        raise CalendarEditError(
            "Calendar Reminder edits are not qualified for this firmware."
        )
    if (
        type(reminder.minutes_before) is not int
        or not 0 <= reminder.minutes_before <= 10080
    ):
        raise CalendarEditError(
            "Choose a reminder from zero to 10,080 minutes before the event."
        )
    if reminder.related_to_end is not False:
        raise CalendarEditError(
            "End-relative reminders remain read-only in this qualified subset."
        )


def editable_reminder(
    entry: CalendarEntry, profile: CalendarProfile
) -> CalendarReminderDraft | None:
    if (
        not entry.editable
        or entry.kind is not CalendarEntryKind.EVENT
        or entry.start is None
        or entry.start.form is not CalendarDateForm.FLOATING
        or not supports_reminders(profile)
        or len(entry.reminders) != 1
    ):
        return None
    saved = entry.reminders[0]
    value = saved.relative_seconds
    if (
        saved.issues
        or saved.component.children
        or value is None
        or value > 0
        or value % 60
    ):
        return None
    draft = CalendarReminderDraft(-value // 60, saved.related_to_end)
    try:
        validate_reminder(
            draft,
            profile,
            has_end=entry.end is not None and entry.end.value is not None,
        )
    except CalendarEditError:
        return None
    return draft
