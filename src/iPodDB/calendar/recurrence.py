"""Calendar day queries using the shared, observed native recurrence rules."""

from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache
from typing import cast

from whenever import Date, Instant, PlainDateTime, Time

from iPodDB.calendar.models import (
    CalendarDateTime,
    CalendarDayRule,
    CalendarEditError,
    CalendarEntry,
    CalendarEntryKind,
    CalendarExceptions,
    CalendarFrequency,
    CalendarOccurrence,
    CalendarOccurrenceResult,
    CalendarProperty,
    CalendarRecurrenceRule,
    CalendarWeekday,
)

_COUNT_DAYS = 10_000
_YEAR_LIMIT = 3000
_WEEKDAYS = tuple(CalendarWeekday)
_MIDNIGHT = Time(0)
_DATE = re.compile(r"[0-9]{8}")
_DATE_LIST_ITEM = re.compile(r"[0-9]{8}(?:T[0-9]{6})?")
_DATE_TIME = re.compile(r"[0-9]{8}T[0-9]{6}")


def parse_recurrence_rule(raw: str) -> CalendarRecurrenceRule:
    """Read the observed selector combinations from an RRULE or EXRULE value."""
    fields: dict[str, str] = {}
    for part in raw.upper().split(";"):
        key, equals, value = part.partition("=")
        if not equals or key in fields or not value:
            raise CalendarEditError("This repeat rule has a missing or repeated field.")
        fields[key] = value

    def integer(value: str) -> int:
        if re.fullmatch(r"[+-]?[0-9]{1,5}", value) is None:
            raise CalendarEditError("Repeat numbers must be whole numbers.")
        return int(value)

    def numbers(key: str) -> tuple[int, ...]:
        return tuple(map(integer, fields.pop(key).split(","))) if key in fields else ()

    def weekday_rule(token: str) -> CalendarDayRule:
        day = CalendarWeekday(token[-2:])
        return CalendarDayRule(day, integer(token[:-2]) if len(token) > 2 else None)

    try:
        frequency = CalendarFrequency(fields.pop("FREQ", ""))
        interval = integer(fields.pop("INTERVAL", "1"))
        count = integer(fields.pop("COUNT")) if "COUNT" in fields else None
        until_text = fields.pop("UNTIL", None)
        if until_text and not _DATE_TIME.fullmatch(until_text):
            raise CalendarEditError("The repeat end needs a floating date and time.")
        until = PlainDateTime.parse_iso(until_text) if until_text else None
        weekdays = (
            tuple(map(weekday_rule, fields.pop("BYDAY").split(",")))
            if "BYDAY" in fields
            else ()
        )
        month_days = numbers("BYMONTHDAY")
        months = numbers("BYMONTH")
        week_start = CalendarWeekday(fields.pop("WKST")) if "WKST" in fields else None
        positions = numbers("BYSETPOS")
    except CalendarEditError:
        raise
    except ValueError as error:
        raise CalendarEditError(
            "This repeat rule uses an unsupported value."
        ) from error
    if fields or positions not in ((), (-1,)):
        raise CalendarEditError("This repeat rule uses an unsupported selector.")
    rule = CalendarRecurrenceRule(
        frequency,
        interval,
        count,
        until,
        weekdays,
        month_days,
        months,
        week_start,
        bool(positions),
    )
    _validate_selectors(rule)
    return rule


def format_recurrence_rule(rule: CalendarRecurrenceRule) -> str:
    fields = [f"FREQ={rule.frequency.value}", f"INTERVAL={rule.interval}"]
    if rule.count is not None:
        fields.append(f"COUNT={rule.count}")
    if rule.until is not None:
        fields.append("UNTIL=" + rule.until.format_iso(basic=True))
    if rule.weekdays:
        fields.append(
            "BYDAY="
            + ",".join(
                (str(day.ordinal) if day.ordinal is not None else "")
                + day.weekday.value
                for day in rule.weekdays
            )
        )
    if rule.month_days:
        fields.append("BYMONTHDAY=" + ",".join(map(str, rule.month_days)))
    if rule.months:
        fields.append("BYMONTH=" + ",".join(map(str, rule.months)))
    if rule.week_start is not None:
        fields.append("WKST=" + rule.week_start.value)
    if rule.last_matching_weekday:
        fields.append("BYSETPOS=-1")
    return ";".join(fields)


def _validate_selectors(rule: CalendarRecurrenceRule) -> None:
    frequency = rule.frequency
    if (
        type(frequency) is not CalendarFrequency
        or type(rule.interval) is not int
        or not 1 <= rule.interval <= 1000
        or len(rule.weekdays) > 31
        or len(rule.month_days) > 31
        or len(rule.months) > 12
        or any(type(d) is not int or not 1 <= abs(d) <= 31 for d in rule.month_days)
        or any(type(m) is not int or not 1 <= m <= 12 for m in rule.months)
        or any(
            type(day.weekday) is not CalendarWeekday
            or (
                day.ordinal is not None
                and (
                    type(day.ordinal) is not int
                    or frequency is not CalendarFrequency.MONTHLY
                    or not 1 <= abs(day.ordinal) <= 5
                )
            )
            for day in rule.weekdays
        )
    ):
        raise CalendarEditError(
            "Choose a supported recurrence interval and repeat dates."
        )
    if (
        (
            rule.week_start is not None
            and (
                type(rule.week_start) is not CalendarWeekday
                or frequency is not CalendarFrequency.WEEKLY
            )
        )
        or (rule.months and frequency is not CalendarFrequency.YEARLY)
        or (
            rule.month_days
            and frequency not in (CalendarFrequency.MONTHLY, CalendarFrequency.YEARLY)
        )
        or (
            rule.weekdays and (rule.month_days or frequency is CalendarFrequency.YEARLY)
        )
        or (
            rule.last_matching_weekday
            and (
                frequency is not CalendarFrequency.MONTHLY
                or not rule.weekdays
                or any(day.ordinal is not None for day in rule.weekdays)
            )
        )
    ):
        raise CalendarEditError("These repeat options cannot be combined.")


def _days(left: Date, right: Date) -> int:
    return int(left.since(right, total="days"))


def _weekday(day: Date) -> CalendarWeekday:
    return _WEEKDAYS[day.day_of_week().value - 1]


def _matches(rule: CalendarRecurrenceRule, seed: Date, day: Date, offset: int) -> bool:
    frequency = rule.frequency
    if frequency is CalendarFrequency.DAILY:
        return offset % rule.interval == 0 and (
            not rule.weekdays or any(d.weekday == _weekday(day) for d in rule.weekdays)
        )
    if frequency is CalendarFrequency.WEEKLY:
        week_start = rule.week_start or CalendarWeekday.MONDAY
        weekday_offset = (
            seed.day_of_week().value - 1 - _WEEKDAYS.index(week_start)
        ) % 7
        if (offset + weekday_offset) // 7 % rule.interval:
            return False
        weekday = _weekday(day)
        return (
            any(d.weekday == weekday for d in rule.weekdays)
            if rule.weekdays
            else weekday == _weekday(seed)
        )
    if frequency is CalendarFrequency.MONTHLY:
        month_delta = (day.year - seed.year) * 12 + day.month - seed.month
        if month_delta % rule.interval:
            return False
    elif (day.year - seed.year) % rule.interval or day.month not in (
        rule.months or (seed.month,)
    ):
        return False
    if rule.month_days:
        return (
            day.day in rule.month_days
            or day.day - day.days_in_month() - 1 in rule.month_days
        )
    if not rule.weekdays:
        return day.day == seed.day
    days_in_month = day.days_in_month()
    weekday = _weekday(day)
    if not any(
        d.weekday == weekday
        and d.ordinal
        in (None, (day.day - 1) // 7 + 1, -((days_in_month - day.day) // 7 + 1))
        for d in rule.weekdays
    ):
        return False
    if rule.last_matching_weekday:
        for later in range(1, min(7, days_in_month - day.day) + 1):
            if any(d.weekday == _weekday(day.add(days=later)) for d in rule.weekdays):
                return False
    return True


@lru_cache(maxsize=1024)
def _count_end(rule: CalendarRecurrenceRule, seed: Date) -> int:
    """Find the last counted candidate within the observed native search bound."""
    assert rule.count is not None
    if (
        rule.frequency in (CalendarFrequency.DAILY, CalendarFrequency.WEEKLY)
        and not rule.weekdays
    ):
        step = rule.interval * (7 if rule.frequency is CalendarFrequency.WEEKLY else 1)
        offset = (rule.count - 1) * step
        if offset < _COUNT_DAYS and seed.add(days=offset).year < _YEAR_LIMIT:
            return offset
    else:
        remaining = rule.count
        for offset in range(_COUNT_DAYS):
            day = seed.add(days=offset)
            if day.year >= _YEAR_LIMIT:
                break
            if _matches(rule, seed, day, offset):
                remaining -= 1
                if remaining == 0:
                    return offset
    raise CalendarEditError("This repeat count exceeds the 10,000-day search.")


def _civil(value: object) -> PlainDateTime | None:
    if isinstance(value, PlainDateTime):
        return value
    if isinstance(value, Instant):
        return value.to_tz("UTC").to_plain()
    if isinstance(value, Date):
        return value.at(_MIDNIGHT)
    return None


def _event_span(start: object, end: object) -> tuple[PlainDateTime, PlainDateTime]:
    first, last = _civil(start), _civil(end)
    if (
        first is None
        or last is None
        or isinstance(start, Date) != isinstance(end, Date)
        or last <= first
        or last.year >= _YEAR_LIMIT
        or first.nanosecond != 0
        or last.nanosecond != 0
        or _days(last.date(), first.date()) >= _COUNT_DAYS
    ):
        raise CalendarEditError(
            "Repeats need a valid start and end before year 3000 and a span under 10,000 days."
        )
    return first, last


def _validate_limits(rule: CalendarRecurrenceRule, start: PlainDateTime) -> None:
    if rule.count is not None and (
        type(rule.count) is not int
        or not 1 <= rule.count <= _COUNT_DAYS
        or rule.until is not None
    ):
        raise CalendarEditError("Choose a valid occurrence count or end date.")
    if rule.until is not None and (
        not isinstance(cast("object", rule.until), PlainDateTime)
        or rule.until < start
        or rule.until.year >= _YEAR_LIMIT
        or rule.until.nanosecond != 0
    ):
        raise CalendarEditError(
            "Choose a repeat end on or after the start and before year 3000."
        )
    if rule.count is not None:
        _count_end(rule, start.date())


def validate_recurrence(
    rule: CalendarRecurrenceRule, start: object, end: object
) -> None:
    first, _ = _event_span(start, end)
    _validate_selectors(rule)
    _validate_limits(rule, first)


def _saved_rule(
    properties: tuple[CalendarProperty, ...], name: str
) -> CalendarRecurrenceRule | None:
    props = [prop for prop in properties if prop.name == name]
    if not props:
        return None
    if len(props) != 1 or props[0].parameters:
        raise CalendarEditError("Repeated or parameterized repeat rules are preserved.")
    return parse_recurrence_rule(props[0].value)


def _date_list(
    properties: tuple[CalendarProperty, ...], name: str, version: str
) -> tuple[Date, ...]:
    separator, other = (",", ";") if version == "1.0" else (";", ",")
    result: set[Date] = set()
    for prop in properties:
        if prop.name != name:
            continue
        value_type = tuple(value.upper() for value in prop.parameter_values("VALUE"))
        if value_type in (("DATE",), ("PERIOD",)):
            continue
        if value_type not in ((), ("DATE-TIME",)) or any(
            param.name not in {"VALUE", "TZID"} for param in prop.parameters
        ):
            raise CalendarEditError("This date list uses unsupported parameters.")
        for item in prop.value.partition(other)[0].split(separator):
            if not item:
                continue
            if not _DATE_LIST_ITEM.fullmatch(item):
                raise CalendarEditError("This date list uses an unsupported date.")
            # Native date-list membership uses the civil day. Validate the
            # complete value before interpreting its date part.
            if _DATE.fullmatch(item):
                result.add(Date.parse_iso(item))
            else:
                result.add(PlainDateTime.parse_iso(item).date())
    return tuple(sorted(result))


def recurrence_exceptions(entry: CalendarEntry) -> CalendarExceptions:
    """Read the date lists and optional exclusion rule in native file order."""
    version = entry.calendar_version
    if version not in ("1.0", "2.0"):
        raise CalendarEditError("This Calendar version cannot project repeat dates.")
    properties = entry.component.properties
    return CalendarExceptions(
        _date_list(properties, "RDATE", version),
        _date_list(properties, "EXDATE", version),
        _saved_rule(properties, "EXRULE"),
    )


def validate_exceptions(
    exceptions: CalendarExceptions, start: object, end: object
) -> None:
    first, _ = _event_span(start, end)
    for day in (*exceptions.added, *exceptions.excluded):
        if not isinstance(cast("object", day), Date) or day.year >= _YEAR_LIMIT:
            raise CalendarEditError("Choose exception dates before year 3000.")
    if any(day < first.date() for day in exceptions.added):
        raise CalendarEditError(
            "Added repeat dates must be on or after the event start."
        )
    if exceptions.exclusion_rule is not None:
        validate_recurrence(exceptions.exclusion_rule, start, end)


def recurrence_rule(entry: CalendarEntry) -> CalendarRecurrenceRule | None:
    if not entry.editable or entry.kind is not CalendarEntryKind.EVENT:
        return None
    try:
        rule = _saved_rule(entry.component.properties, "RRULE")
        if rule is not None:
            validate_recurrence(
                rule, entry.start and entry.start.value, entry.end and entry.end.value
            )
        return rule
    except ValueError:
        return None


def _shift(value: CalendarDateTime, offset: int) -> CalendarDateTime:
    saved = value.value
    if isinstance(saved, PlainDateTime):
        shifted = saved.add(days=offset, naive_arithmetic_ok=True)
        return replace(value, value=shifted, raw=shifted.format_iso(basic=True))
    if isinstance(saved, Instant):
        shifted_utc = (
            saved.to_tz("UTC")
            .to_plain()
            .add(days=offset, naive_arithmetic_ok=True)
            .assume_utc()
        )
        return replace(value, value=shifted_utc, raw=shifted_utc.format_iso(basic=True))
    assert isinstance(saved, Date)
    shifted_date = saved.add(days=offset)
    return replace(value, value=shifted_date, raw=shifted_date.format_iso(basic=True))


def _match_end(rule: CalendarRecurrenceRule, start: PlainDateTime) -> int | None:
    if rule.count is not None:
        return _count_end(rule, start.date())
    if rule.until is not None:
        days = _days(rule.until.date(), start.date())
        return days - (rule.until.time() < start.time())
    return None


def _included(
    rule: CalendarRecurrenceRule | None,
    cutoff: int | None,
    seed: Date,
    day: Date,
    offset: int,
) -> bool:
    return (
        rule is not None
        and (cutoff is None or offset <= cutoff)
        and _matches(rule, seed, day, offset)
    )


def project_occurrences(
    entry: CalendarEntry, first: Date, last: Date
) -> CalendarOccurrenceResult:
    """Return the first native-style matching span for each requested civil day."""
    if last < first or _days(last, first) > 62:
        raise ValueError("Calendar occurrence queries must span at most 63 days.")
    fallback = (
        (CalendarOccurrence(entry.start, entry.end),) if entry.start is not None else ()
    )
    if not entry.has_recurrence or entry.kind is not CalendarEntryKind.EVENT:
        return CalendarOccurrenceResult(fallback)
    try:
        if (
            entry.start is None
            or entry.end is None
            or last.year >= _YEAR_LIMIT
            or any(prop.name == "DURATION" for prop in entry.component.properties)
            or any(
                sum(prop.name == name for prop in entry.component.properties) != 1
                for name in ("DTSTART", "DTEND")
            )
        ):
            raise CalendarEditError("Saved repeat timing cannot be projected.")
        start, end = _event_span(entry.start.value, entry.end.value)
        rule = _saved_rule(entry.component.properties, "RRULE")
        exceptions = recurrence_exceptions(entry)
        excluded_rule = exceptions.exclusion_rule
        for parsed_rule in (rule, excluded_rule):
            if parsed_rule is not None:
                _validate_limits(parsed_rule, start)
    except ValueError as error:
        return CalendarOccurrenceResult(fallback, detail=str(error))
    seed = start.date()
    first_offset = _days(first, seed)
    last_offset = _days(last, seed)
    extent = _days(end.date(), seed)
    last_covered = extent - (end.time() == _MIDNIGHT)
    added, excluded = set(exceptions.added), set(exceptions.excluded)
    include_end = _match_end(rule, start) if rule is not None else None
    exclude_end = (
        _match_end(excluded_rule, start) if excluded_rule is not None else None
    )
    matches: dict[int, CalendarOccurrence] = {}
    visible_days = last_offset - first_offset + 1
    active_repeat = rule is not None or excluded_rule is not None or added or excluded
    candidates = range(max(0, first_offset - last_covered), last_offset + 1)
    for offset in candidates if active_repeat else ():
        if len(matches) == visible_days:
            break
        candidate = seed.add(days=offset)
        if (
            (
                offset >= extent
                and candidate not in added
                and not _included(rule, include_end, seed, candidate, offset)
            )
            or candidate in excluded
            or _included(excluded_rule, exclude_end, seed, candidate, offset)
        ):
            continue
        for day_offset in range(
            max(first_offset, offset), min(last_offset, offset + last_covered) + 1
        ):
            if day_offset not in matches:
                matches[day_offset] = CalendarOccurrence(
                    _shift(entry.start, offset),
                    _shift(entry.end, offset),
                    seed.add(days=day_offset),
                )
    # The native full query falls back to the saved span on a day for which
    # candidate matching found nothing, including an excluded source date.
    for day_offset in range(max(first_offset, 0), min(last_offset, last_covered) + 1):
        matches.setdefault(
            day_offset,
            CalendarOccurrence(entry.start, entry.end, seed.add(days=day_offset)),
        )
    return CalendarOccurrenceResult(
        tuple(matches[offset] for offset in sorted(matches)), expanded=True
    )


def skippable_occurrence_start(
    entry: CalendarEntry, occurrence: CalendarOccurrence
) -> Date | None:
    """Find the date to exclude, accounting for native saved-span fallback."""
    if (
        not entry.editable
        or entry.calendar_version != "2.0"
        or not entry.has_recurrence
        or occurrence.day is None
        or entry.start is None
        or any(prop.name == "RECURRENCE-ID" for prop in entry.component.properties)
    ):
        return None
    seed, start = _civil(entry.start.value), _civil(occurrence.start.value)
    if seed is None or start is None or start.date() <= seed.date():
        return None
    return start.date()
