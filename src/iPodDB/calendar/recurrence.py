"""Bounded recurrence matching, qualified by original event-membership probes.

Only floating, same-day DAILY/WEEKLY series are expanded. No RFC recurrence
engine, Host timezone, exception merging or monthly day-clamping is inferred.
See docs/research/calendar-firmware-coverage-2026-11-08.md.
"""

import re
from dataclasses import replace
from typing import cast

from whenever import Date, PlainDateTime

from iPodDB.calendar.models import (
    CalendarDateForm,
    CalendarEditError,
    CalendarEntry,
    CalendarEntryKind,
    CalendarFrequency,
    CalendarOccurrence,
    CalendarOccurrenceResult,
    CalendarProfile,
    CalendarRecurrenceRule,
)


def supports_recurrence(profile: CalendarProfile) -> bool:
    return type(profile) is CalendarProfile and profile in {
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
    }


def validate_recurrence(
    rule: CalendarRecurrenceRule, profile: CalendarProfile, start: object, end: object
) -> None:
    if not supports_recurrence(profile):
        raise CalendarEditError(
            "Recurring Calendar edits are not qualified for this firmware."
        )
    if (
        type(rule.frequency) is not CalendarFrequency
        or type(rule.interval) is not int
        or not 1 <= rule.interval <= 1000
    ):
        raise CalendarEditError("Choose a supported recurrence frequency and interval.")
    if (
        not isinstance(start, PlainDateTime)
        or not isinstance(end, PlainDateTime)
        or start.date() != end.date()
        or end <= start
        or start.year >= 3000
        or start.nanosecond != 0
        or end.nanosecond != 0
    ):
        raise CalendarEditError(
            "Qualified recurrence needs floating start/end times on the same day before year 3000."
        )
    step = rule.interval * (7 if rule.frequency is CalendarFrequency.WEEKLY else 1)
    if rule.count is not None and (
        type(rule.count) is not int
        or rule.count < 1
        or (rule.count - 1) * step >= 10000
    ):
        raise CalendarEditError(
            "This repeat count exceeds the firmware's qualified 10,000-day search."
        )
    if (
        rule.count is not None
        and start.add(days=(rule.count - 1) * step, naive_arithmetic_ok=True).year
        >= 3000
    ):
        raise CalendarEditError("Qualified repeat counts must end before year 3000.")
    if rule.count is not None and rule.until is not None:
        raise CalendarEditError("Combined repeat count and end date are not qualified.")
    until = cast("object", rule.until)
    if until is not None and (
        not isinstance(until, PlainDateTime)
        or until < start
        or until.year >= 3000
        or until.nanosecond != 0
    ):
        raise CalendarEditError(
            "Choose a repeat end date after the start and before year 3000."
        )


def recurrence_rule(
    entry: CalendarEntry, profile: CalendarProfile
) -> CalendarRecurrenceRule | None:
    saved = entry.recurrence
    if (
        not entry.editable
        or saved is None
        or saved.issues
        or entry.kind is not CalendarEntryKind.EVENT
        or entry.start is None
        or entry.end is None
        or entry.start.form is not CalendarDateForm.FLOATING
        or entry.end.form is not CalendarDateForm.FLOATING
    ):
        return None
    if any(
        prop.name in {"EXRULE", "EXDATE", "RDATE", "RECURRENCE-ID", "DURATION"}
        for prop in entry.component.properties
    ):
        return None
    if any(
        prop.parameters
        for prop in entry.component.properties
        if prop.name in {"DTSTART", "DTEND"}
    ):
        return None
    keys = {part.partition("=")[0].upper() for part in saved.raw.split(";")}
    if (
        not keys <= {"FREQ", "INTERVAL", "COUNT", "UNTIL"}
        or saved.interval is None
        or ("COUNT" in keys and saved.count is None)
    ):
        return None
    try:
        until = None
        if saved.until is not None:
            value = saved.until
            if re.fullmatch(r"[0-9]{8}T[0-9]{6}", value) is None:
                return None
            until = PlainDateTime(
                int(value[:4]),
                int(value[4:6]),
                int(value[6:8]),
                int(value[9:11]),
                int(value[11:13]),
                int(value[13:15]),
            )
        rule = CalendarRecurrenceRule(
            CalendarFrequency(saved.frequency or ""), saved.interval, saved.count, until
        )
        validate_recurrence(rule, profile, entry.start.value, entry.end.value)
    except (ValueError, OverflowError):
        return None
    return rule


def project_occurrences(
    entry: CalendarEntry, first: Date, last: Date, *, profile: CalendarProfile
) -> CalendarOccurrenceResult:
    if last < first or last.since(first, total="days") > 62:
        raise ValueError("Calendar occurrence queries must span at most 63 days.")
    fallback = (
        (CalendarOccurrence(entry.start, entry.end),) if entry.start is not None else ()
    )
    if not entry.has_recurrence:
        return CalendarOccurrenceResult(fallback)
    if last.year >= 3000:
        return CalendarOccurrenceResult(
            fallback,
            detail="Occurrence projection is qualified only before year 3000; saved dates are retained.",
        )
    rule = recurrence_rule(entry, profile)
    if rule is None:
        return CalendarOccurrenceResult(
            fallback,
            detail="This firmware or recurrence shape is not qualified for expansion; only saved dates are shown.",
        )
    assert entry.start is not None and entry.end is not None
    start, end = entry.start.value, entry.end.value
    assert isinstance(start, PlainDateTime) and isinstance(end, PlainDateTime)
    step = rule.interval * (7 if rule.frequency is CalendarFrequency.WEEKLY else 1)
    offset = max(0, int(first.since(start.date(), total="days")))
    index = (offset + step - 1) // step
    occurrences: list[CalendarOccurrence] = []
    while rule.count is None or index < rule.count:
        try:
            current = start.add(days=index * step, naive_arithmetic_ok=True)
            if (
                current.year >= 3000
                or current.date() > last
                or (rule.until is not None and current > rule.until)
            ):
                break
            finish = end.add(days=index * step, naive_arithmetic_ok=True)
        except (ValueError, OverflowError):
            break
        occurrences.append(
            CalendarOccurrence(
                replace(entry.start, value=current, raw=current.format_iso(basic=True)),
                replace(entry.end, value=finish, raw=finish.format_iso(basic=True)),
            )
        )
        index += 1
    return CalendarOccurrenceResult(tuple(occurrences), expanded=True)
