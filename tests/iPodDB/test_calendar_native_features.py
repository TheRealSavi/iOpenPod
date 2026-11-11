"""Qualified recurrence/reminder behavior, independent of a Host timezone."""

from dataclasses import replace

import pytest
from whenever import Date, Instant, PlainDateTime

from iPodDB.calendar import (
    CalendarDayRule,
    CalendarEditError,
    CalendarEntryChanges,
    CalendarEntryDraft,
    CalendarEntryKind,
    CalendarExceptions,
    CalendarFrequency,
    CalendarOccurrence,
    CalendarRecurrenceRule,
    CalendarReminderDraft,
    CalendarTodoStatus,
    CalendarWeekday,
    add_entry,
    calendar_zone_names,
    create_calendar,
    editable_reminder,
    parse_calendar,
    project_occurrences,
    reminder_civil_time,
    serialize_calendar,
    skip_occurrence,
    update_entry,
)

START = PlainDateTime(2026, 11, 1, 9)
END = PlainDateTime(2026, 11, 1, 10)


def test_native_status_is_not_inferred_from_ignored_completion_metadata() -> None:
    raw = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n"
        b"SUMMARY:Task\r\nCOMPLETED:20261101T090000Z\r\nPERCENT-COMPLETE:100\r\n"
        b"END:VTODO\r\nEND:VCALENDAR\r\n"
    )
    document = parse_calendar(raw)
    assert not document.entries[0].completed
    assert document.entries[0].completed_at is not None
    assert serialize_calendar(document) == raw
    updated = update_entry(document, 0, CalendarEntryChanges(summary="Renamed"))
    assert not updated.entries[0].completed
    assert updated.raw_bytes == raw.replace(b"SUMMARY:Task", b"SUMMARY:Renamed")


def test_native_todo_completion_authors_status_without_host_progress_or_timestamp() -> (
    None
):
    document = create_calendar(
        (
            CalendarEntryDraft(
                kind=CalendarEntryKind.TODO, summary="Task", completed=True
            ),
        ),
    )
    assert b"STATUS:COMPLETED\r\n" in document.raw_bytes
    assert b"\r\nCOMPLETED:" not in document.raw_bytes
    imported = parse_calendar(
        document.raw_bytes.replace(
            b"STATUS:COMPLETED\r\n",
            b"STATUS:COMPLETED\r\nCOMPLETED:20261101T090000Z\r\nPERCENT-COMPLETE:100\r\n",
        )
    )
    reopened = update_entry(imported, 0, CalendarEntryChanges(completed=False))
    assert not reopened.entries[0].completed
    assert b"\r\nSTATUS:" not in reopened.raw_bytes
    assert b"\r\nCOMPLETED:" not in reopened.raw_bytes
    assert b"PERCENT-COMPLETE:100\r\n" in reopened.raw_bytes


def _series(
    rule: str, *, start: str = "20261101T090000", end: str = "20261101T100000"
) -> bytes:
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:seed\r\n"
        f"DTSTART:{start}\r\nDTEND:{end}\r\n{rule}\r\n"
        "SUMMARY:Keep\r\nX-KEEP:opaque\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()


@pytest.mark.parametrize(
    "rule,offsets",
    (
        ("FREQ=DAILY;INTERVAL=2;COUNT=3", (0, 2, 4)),
        ("FREQ=WEEKLY;INTERVAL=2;COUNT=3", (0, 14, 28)),
        ("FREQ=WEEKLY;UNTIL=20261115T090000", (0, 7, 14)),
        ("FREQ=WEEKLY;UNTIL=20261115T085959", (0, 7)),
        ("FREQ=DAILY;COUNT=1", (0,)),
    ),
)
def test_shared_rules_match_native_membership(
    rule: str, offsets: tuple[int, ...]
) -> None:
    raw = _series("RRULE:" + rule)
    document = parse_calendar(raw)
    result = project_occurrences(
        document.entries[0], Date(2026, 10, 30), Date(2026, 12, 8)
    )
    assert result.expanded
    assert [occurrence.start.value for occurrence in result.occurrences] == [
        START.add(days=offset, naive_arithmetic_ok=True) for offset in offsets
    ]
    assert [
        occurrence.end.value if occurrence.end else None
        for occurrence in result.occurrences
    ] == [END.add(days=offset, naive_arithmetic_ok=True) for offset in offsets]
    assert serialize_calendar(document) == raw


@pytest.mark.parametrize(
    "start,end",
    (("20240228T090000", "20240228T100000"), ("20261231T230000", "20261231T233000")),
)
def test_native_daily_series_crosses_leap_days_and_years(start: str, end: str) -> None:
    entry = parse_calendar(
        _series("RRULE:FREQ=DAILY;COUNT=3", start=start, end=end)
    ).entries[0]
    seed = entry.start.value if entry.start else None
    assert isinstance(seed, PlainDateTime)
    result = project_occurrences(entry, seed.date(), seed.date().add(days=4))
    assert result.expanded
    assert [occurrence.start.value for occurrence in result.occurrences] == [
        seed.add(days=index, naive_arithmetic_ok=True) for index in range(3)
    ]


@pytest.mark.parametrize(
    "rule",
    (
        "FREQ=DAILY;BYHOUR=9,17;BYSETPOS=-1",
        "FREQ=MONTHLY;BYDAY=MO;BYMONTHDAY=5",
        "FREQ=DAILY;COUNT=3;UNTIL=20261201T090000",
        "FREQ=WEEKLY;INTERVAL=2;COUNT=1000",
        "FREQ=DAILY;INTERVAL=0",
        "FREQ=DAILY;COUNT=bad",
        "FREQ=DAILY;UNTIL=20261115T090000Z",
    ),
)
def test_unqualified_rules_retain_saved_dates_and_bytes(rule: str) -> None:
    raw = _series("RRULE:" + rule)
    document = parse_calendar(raw)
    result = project_occurrences(
        document.entries[0], Date(2026, 11, 1), Date(2026, 11, 30)
    )
    assert not result.expanded and result.detail
    assert serialize_calendar(document) == raw


def test_recurrence_edit_changes_only_its_property() -> None:
    raw = _series("RRULE:FREQ=DAILY;COUNT=3")
    document = parse_calendar(raw)
    rule = CalendarRecurrenceRule(CalendarFrequency.WEEKLY, 2, 3)
    updated = update_entry(document, 0, CalendarEntryChanges(recurrence=rule))
    assert updated.raw_bytes == raw.replace(
        b"RRULE:FREQ=DAILY;COUNT=3", b"RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=3"
    )
    assert b"X-KEEP:opaque" in updated.raw_bytes
    removed = update_entry(document, 0, CalendarEntryChanges(recurrence=None))
    assert removed.raw_bytes == raw.replace(b"RRULE:FREQ=DAILY;COUNT=3\r\n", b"")


def test_creates_one_trigger_without_invented_action() -> None:
    draft = CalendarEntryDraft(
        start=START, end=END, reminder=CalendarReminderDraft(-900)
    )
    document = create_calendar((draft,))
    reminder = document.entries[0].reminders[0]
    assert reminder.relative_seconds == -900
    assert reminder.action is None
    assert b"BEGIN:VALARM\r\nTRIGGER:-PT15M\r\nEND:VALARM" in document.raw_bytes
    assert b"ACTION" not in document.raw_bytes
    assert editable_reminder(document.entries[0]) == CalendarReminderDraft(-900)


def test_existing_reminder_edit_preserves_unknown_fields_and_other_components() -> None:
    raw = _series(
        "BEGIN:VALARM\r\nX-KEEP-ALARM:opaque\r\nACTION:AUDIO\r\nTRIGGER;RELATED=START:-PT15M\r\nEND:VALARM"
    )
    document = parse_calendar(raw)
    updated = update_entry(
        document,
        0,
        CalendarEntryChanges(reminder=CalendarReminderDraft(-1800)),
    )
    assert updated.raw_bytes == raw.replace(
        b"TRIGGER;RELATED=START:-PT15M", b"TRIGGER:-PT30M"
    )
    assert b"ACTION:AUDIO" in updated.raw_bytes
    removed = update_entry(document, 0, CalendarEntryChanges(reminder=None))
    assert not removed.entries[0].reminders
    assert b"X-KEEP:opaque" in removed.raw_bytes


@pytest.mark.parametrize(
    "body",
    (
        "BEGIN:VALARM\r\nTRIGGER:-P1W\r\nEND:VALARM",
        "BEGIN:VALARM\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nBEGIN:VALARM\r\nTRIGGER:-PT30M\r\nEND:VALARM",
    ),
)
def test_unsupported_reminders_remain_readonly_and_survive_text_edits(
    body: str,
) -> None:
    raw = _series(body)
    document = parse_calendar(raw)
    assert editable_reminder(document.entries[0]) is None
    text = update_entry(document, 0, CalendarEntryChanges(summary="Changed"))
    assert text.raw_bytes == raw.replace(b"SUMMARY:Keep", b"SUMMARY:Changed")
    with pytest.raises(CalendarEditError):
        update_entry(
            document,
            0,
            CalendarEntryChanges(reminder=CalendarReminderDraft(-600)),
        )


def test_recurrence_requires_matching_date_forms() -> None:
    draft = CalendarEntryDraft(
        start=START, end=END, recurrence=CalendarRecurrenceRule(CalendarFrequency.DAILY)
    )
    for changed in (
        replace(draft, start=Date(2026, 11, 1)),
        replace(draft, end=Date(2026, 11, 2)),
    ):
        with pytest.raises(CalendarEditError):
            create_calendar((changed,))


def test_legacy_calendar_projects_recurrence_without_rewriting() -> None:
    raw = _series("RRULE:FREQ=DAILY;COUNT=3").replace(b"VERSION:2.0", b"VERSION:1.0")
    document = parse_calendar(raw)
    assert project_occurrences(
        document.entries[0], Date(2026, 11, 1), Date(2026, 11, 30)
    ).expanded
    assert not document.editable
    assert serialize_calendar(document) == raw


def test_native_count_and_whole_second_bounds_apply_to_new_drafts() -> None:
    for rule in (
        CalendarRecurrenceRule(CalendarFrequency.DAILY, count=10001),
        CalendarRecurrenceRule(
            CalendarFrequency.DAILY, until=START.replace(nanosecond=1)
        ),
    ):
        with pytest.raises(CalendarEditError):
            create_calendar(
                (CalendarEntryDraft(start=START, end=END, recurrence=rule),),
            )


def test_occurrence_queries_are_bounded_without_scanning_from_series_origin() -> None:
    raw = _series("RRULE:FREQ=DAILY", start="19000101T090000", end="19000101T100000")
    entry = parse_calendar(raw).entries[0]
    result = project_occurrences(entry, Date(2026, 11, 1), Date(2026, 11, 30))
    assert result.expanded and len(result.occurrences) == 30
    with pytest.raises(ValueError, match="63 days"):
        project_occurrences(entry, Date(2026, 1, 1), Date(2026, 12, 31))


def test_oversized_native_reminder_stays_uninterpreted_instead_of_host_integer_guess() -> (
    None
):
    raw = _series("BEGIN:VALARM\r\nTRIGGER:-P999999D\r\nEND:VALARM")
    document = parse_calendar(raw)
    reminder = document.entries[0].reminders[0]
    assert reminder.relative_seconds is None
    assert reminder.issues
    assert serialize_calendar(document) == raw


# Expected candidate days captured on all studied inputs. The full day query
# can still return the saved source span when candidate matching filters it.
@pytest.mark.parametrize(
    "seed,rule,horizon,days",
    (
        (
            "2026-01-01",
            "FREQ=MONTHLY;BYMONTHDAY=-1;COUNT=4",
            160,
            ("2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"),
        ),
        (
            "2026-01-01",
            "FREQ=MONTHLY;BYDAY=MO;COUNT=5",
            90,
            ("2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26", "2026-02-02"),
        ),
        (
            "2026-01-01",
            "FREQ=MONTHLY;BYDAY=1MO;COUNT=4",
            160,
            ("2026-01-05", "2026-02-02", "2026-03-02", "2026-04-06"),
        ),
        (
            "2026-01-01",
            "FREQ=MONTHLY;BYDAY=-1FR;COUNT=4",
            160,
            ("2026-01-30", "2026-02-27", "2026-03-27", "2026-04-24"),
        ),
        (
            "2026-11-04",
            "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6",
            60,
            (
                "2026-11-04",
                "2026-11-09",
                "2026-11-11",
                "2026-11-16",
                "2026-11-18",
                "2026-11-23",
            ),
        ),
        (
            "2026-11-04",
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;WKST=MO;COUNT=6",
            90,
            (
                "2026-11-04",
                "2026-11-16",
                "2026-11-18",
                "2026-11-30",
                "2026-12-02",
                "2026-12-14",
            ),
        ),
        (
            "2026-11-04",
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;WKST=SU;COUNT=6",
            90,
            (
                "2026-11-04",
                "2026-11-16",
                "2026-11-18",
                "2026-11-30",
                "2026-12-02",
                "2026-12-14",
            ),
        ),
        (
            "2026-11-01",
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=SU,MO;WKST=MO;COUNT=6",
            90,
            (
                "2026-11-01",
                "2026-11-09",
                "2026-11-15",
                "2026-11-23",
                "2026-11-29",
                "2026-12-07",
            ),
        ),
        (
            "2026-11-01",
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=SU,MO;WKST=SU;COUNT=6",
            90,
            (
                "2026-11-01",
                "2026-11-02",
                "2026-11-15",
                "2026-11-16",
                "2026-11-29",
                "2026-11-30",
            ),
        ),
        (
            "2026-11-01",
            "FREQ=DAILY;BYDAY=MO;COUNT=3",
            40,
            ("2026-11-02", "2026-11-09", "2026-11-16"),
        ),
        (
            "2026-01-01",
            "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
            160,
            ("2026-01-30", "2026-02-27", "2026-03-31", "2026-04-30", "2026-05-29"),
        ),
        (
            "2026-01-01",
            "FREQ=YEARLY;BYMONTH=11;BYMONTHDAY=1",
            1100,
            ("2026-11-01", "2027-11-01", "2028-11-01"),
        ),
    ),
)
def test_native_advanced_repeat_vectors(
    seed: str, rule: str, horizon: int, days: tuple[str, ...]
) -> None:
    first = Date.parse_iso(seed)
    raw = _series(
        "RRULE:" + rule,
        start=seed.replace("-", "") + "T090000",
        end=seed.replace("-", "") + "T100000",
    )
    document = parse_calendar(raw)
    actual: set[str] = set()
    for offset in range(0, horizon, 63):
        result = project_occurrences(
            document.entries[0],
            first.add(days=offset),
            first.add(days=min(offset + 62, horizon - 1)),
        )
        assert result.expanded, result.detail
        for occurrence in result.occurrences:
            assert occurrence.day is not None
            actual.add(occurrence.day.format_iso())
    assert actual == {seed, *days}
    assert serialize_calendar(document) == raw


@pytest.mark.parametrize(
    "start,end,frequency,expected",
    (
        (
            "20260131T090000",
            "20260131T100000",
            "MONTHLY",
            ("20260131", "20260331", "20260531", "20260731"),
        ),
        (
            "20240229T090000",
            "20240229T100000",
            "YEARLY",
            ("20240229", "20280229", "20320229"),
        ),
    ),
)
def test_finalized_repeat_defaults_skip_invalid_dates(
    start: str, end: str, frequency: str, expected: tuple[str, ...]
) -> None:
    entry = parse_calendar(
        _series(f"RRULE:FREQ={frequency};COUNT={len(expected)}", start=start, end=end)
    ).entries[0]
    first = Date.parse_iso(start[:8])
    through = Date.parse_iso(expected[-1]).add(days=366)
    actual: list[str] = []
    cursor = first
    while cursor <= through:
        result = project_occurrences(entry, cursor, min(cursor.add(days=62), through))
        assert result.expanded
        actual.extend(
            occurrence.day.format_iso(basic=True)
            for occurrence in result.occurrences
            if occurrence.day
        )
        cursor = cursor.add(days=63)
    assert tuple(actual) == expected


@pytest.mark.parametrize("version,delimiter", (("1.0", ","), ("2.0", ";")))
def test_native_exception_lists_merge_and_preserve_seed_fallback(
    version: str, delimiter: str
) -> None:
    raw = _series(
        f"RDATE:20261103T150000{delimiter}20261105T230000\r\n"
        "RDATE:20261106\r\nEXDATE:20261101;20261103\r\n"
        "EXDATE:20261103T230000\r\nRDATE;VALUE=DATE:20261107"
    ).replace(b"VERSION:2.0", f"VERSION:{version}".encode())
    document = parse_calendar(raw)
    result = project_occurrences(
        document.entries[0], Date(2026, 11, 1), Date(2026, 11, 7)
    )
    assert result.expanded
    assert [item.day for item in result.occurrences] == [
        Date(2026, 11, day) for day in (1, 5, 6)
    ]
    assert [item.start.raw for item in result.occurrences] == [
        "20261101T090000",
        "20261105T090000",
        "20261106T090000",
    ]
    assert document.raw_bytes == raw


def test_exclusion_rule_can_skip_repeats_and_keep_the_saved_seed() -> None:
    entry = parse_calendar(
        _series("RRULE:FREQ=DAILY;COUNT=10\r\nEXRULE:FREQ=WEEKLY")
    ).entries[0]
    result = project_occurrences(entry, Date(2026, 11, 1), Date(2026, 11, 10))
    assert [item.day for item in result.occurrences] == [
        Date(2026, 11, day) for day in range(1, 11) if day != 8
    ]


def test_all_day_repeats_keep_their_exclusive_end() -> None:
    document = create_calendar(
        (
            CalendarEntryDraft(
                start=Date(2026, 11, 1),
                end=Date(2026, 11, 2),
                recurrence=CalendarRecurrenceRule(CalendarFrequency.WEEKLY),
                exceptions=CalendarExceptions(added=(Date(2026, 11, 3),)),
            ),
        )
    )
    result = project_occurrences(
        document.entries[0], Date(2026, 11, 1), Date(2026, 11, 9)
    )
    assert result.expanded
    assert [
        (item.day, item.end.value if item.end else None) for item in result.occurrences
    ] == [(Date(2026, 11, day), Date(2026, 11, day + 1)) for day in (1, 3, 8)]


def test_multiday_query_returns_the_first_overlapping_native_span() -> None:
    entry = parse_calendar(
        _series("RRULE:FREQ=WEEKLY", start="20261101T230000", end="20261103T010000")
    ).entries[0]
    result = project_occurrences(entry, Date(2026, 11, 2), Date(2026, 11, 5))
    assert result.expanded
    assert [
        (item.day, item.start.raw, item.end.raw if item.end else None)
        for item in result.occurrences
    ] == [
        (Date(2026, 11, 2), "20261101T230000", "20261103T010000"),
        (Date(2026, 11, 3), "20261101T230000", "20261103T010000"),
        (Date(2026, 11, 4), "20261102T230000", "20261104T010000"),
    ]


def test_explicit_exception_edit_keeps_other_event_properties() -> None:
    raw = _series("RRULE:FREQ=DAILY;COUNT=5\r\nRDATE:20261103\r\nRDATE:20261107")
    document = parse_calendar(raw)
    updated = update_entry(
        document,
        0,
        CalendarEntryChanges(
            exceptions=CalendarExceptions(
                added=(Date(2026, 11, 8), Date(2026, 11, 6)),
                excluded=(Date(2026, 11, 3),),
            )
        ),
    )
    assert b"RDATE:20261106;20261108\r\n" in updated.raw_bytes
    assert updated.raw_bytes.count(b"RDATE:") == 1
    assert b"EXDATE:20261103\r\n" in updated.raw_bytes
    assert b"RRULE:FREQ=DAILY;COUNT=5\r\n" in updated.raw_bytes
    assert b"X-KEEP:opaque\r\n" in updated.raw_bytes
    assert document.raw_bytes == raw


def test_editing_one_exception_list_preserves_other_lists_and_inert_properties() -> (
    None
):
    raw = _series(
        "RRULE:FREQ=DAILY;COUNT=5\r\nRDATE;VALUE=DATE-TIME:20261107T190000\r\n"
        "EXDATE;VALUE=DATE:20261104\r\nEXDATE:20261103\r\nEXRULE:FREQ=WEEKLY;BYDAY=MO"
    )
    updated = update_entry(
        parse_calendar(raw),
        0,
        CalendarEntryChanges(
            exceptions=CalendarExceptions(
                added=(Date(2026, 11, 7),),
                excluded=(Date(2026, 11, 5),),
                exclusion_rule=CalendarRecurrenceRule(
                    CalendarFrequency.WEEKLY,
                    weekdays=(CalendarDayRule(CalendarWeekday.MONDAY),),
                ),
            )
        ),
    )
    assert b"RDATE;VALUE=DATE-TIME:20261107T190000\r\n" in updated.raw_bytes
    assert b"EXDATE;VALUE=DATE:20261104\r\n" in updated.raw_bytes
    assert b"EXRULE:FREQ=WEEKLY;BYDAY=MO\r\n" in updated.raw_bytes
    assert b"EXDATE:20261103\r\n" not in updated.raw_bytes
    assert b"EXDATE:20261105\r\n" in updated.raw_bytes


def test_skipping_a_repeat_excludes_its_start_and_only_appends_one_property() -> None:
    raw = _series(
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEXDATE:20261115\r\nRDATE:20261123",
        end="20261102T100000",
    )
    document = parse_calendar(raw)
    seed, start, selected = Date(2026, 11, 1), Date(2026, 11, 8), Date(2026, 11, 9)
    with pytest.raises(CalendarEditError, match="no longer be skipped"):
        skip_occurrence(document, 0, seed, seed)
    with pytest.raises(CalendarEditError, match="no longer be skipped"):
        skip_occurrence(document, 0, selected, selected)
    updated = skip_occurrence(document, 0, selected, start)
    assert updated.raw_bytes == raw.replace(
        b"END:VEVENT", b"EXDATE:20261108\r\nEND:VEVENT"
    )
    result = project_occurrences(updated.entries[0], start, selected)
    assert result.expanded and not result.occurrences
    with pytest.raises(CalendarEditError, match="no longer be skipped"):
        skip_occurrence(updated, 0, selected, start)


@pytest.mark.parametrize(
    "draft,line,expected",
    (
        (
            CalendarReminderDraft(-905, related_to_end=True),
            b"TRIGGER;RELATED=END:-PT15M5S",
            PlainDateTime(2026, 11, 1, 9, 44, 55),
        ),
        (
            CalendarReminderDraft(25),
            b"TRIGGER:PT25S",
            PlainDateTime(2026, 11, 1, 9, 0, 25),
        ),
        (
            CalendarReminderDraft(absolute_trigger=Instant.from_utc(2026, 11, 3, 2)),
            b"TRIGGER;VALUE=DATE-TIME:20261103T020000Z",
            PlainDateTime(2026, 11, 3, 2),
        ),
    ),
)
def test_saved_reminder_forms_round_trip_and_evaluate(
    draft: CalendarReminderDraft, line: bytes, expected: PlainDateTime
) -> None:
    document = create_calendar(
        (CalendarEntryDraft(start=START, end=END, reminder=draft),)
    )
    entry = document.entries[0]
    assert line in document.raw_bytes
    assert b"ACTION:" not in document.raw_bytes
    assert editable_reminder(entry) == draft
    assert entry.start is not None
    assert (
        reminder_civil_time(
            entry.reminders[0], CalendarOccurrence(entry.start, entry.end)
        )
        == expected
    )


def test_end_relative_reminder_requires_saved_end() -> None:
    with pytest.raises(CalendarEditError, match="event end"):
        create_calendar(
            (
                CalendarEntryDraft(
                    start=START, reminder=CalendarReminderDraft(5, related_to_end=True)
                ),
            )
        )


@pytest.mark.parametrize(
    "start,end,zone_first,expected",
    (
        (
            ";TZID=synthetic/eastern",
            ";TZID=Synthetic/Eastern",
            True,
            "Synthetic/Eastern",
        ),
        (";TZID=Synthetic/Eastern", ";TZID=Missing/Zone", True, "Synthetic/Eastern"),
        (";TZID=Synthetic/Eastern", ";TZID=Synthetic/Eastern", False, None),
        (";TZID=Synthetic/Eastern ", ";TZID=Synthetic/Eastern ", True, None),
        (";TZID=UTC", ";TZID=UTC", True, None),
        (";TZID=Z", ";TZID=Z", True, "Z"),
        ("", "", True, None),
    ),
)
def test_native_zone_binding_uses_only_prior_definitions(
    start: str, end: str, zone_first: bool, expected: str | None
) -> None:
    zone = (
        b"BEGIN:VTIMEZONE\r\nTZID:Synthetic/Eastern\r\nBEGIN:STANDARD\r\n"
        b"DTSTART:20201101T020000\r\nTZOFFSETFROM:-0400\r\nTZOFFSETTO:-0500\r\n"
        b"END:STANDARD\r\nEND:VTIMEZONE\r\n"
    )
    raw = _series("X-WR-KEEP:yes").replace(b"DTSTART:", f"DTSTART{start}:".encode())
    raw = raw.replace(b"DTEND:", f"DTEND{end}:".encode())
    boundary = b"BEGIN:VEVENT" if zone_first else b"END:VCALENDAR"
    raw = raw.replace(boundary, zone + boundary)
    document = parse_calendar(raw)
    bound = document.entries[0].zone
    assert (bound.name if bound else None) == expected
    if bound is not None:
        assert bound.standard_offset == (
            -18000 if expected == "Synthetic/Eastern" else 0
        )
    assert document.raw_bytes == raw


def test_named_timezone_authoring_uses_the_destination_definition() -> None:
    zone = (
        b"BEGIN:VTIMEZONE\r\nTZID:Home/West\r\nBEGIN:STANDARD\r\n"
        b"DTSTART:20201101T020000\r\nTZOFFSETFROM:-0400\r\nTZOFFSETTO:-0500\r\n"
        b"END:STANDARD\r\nEND:VTIMEZONE\r\n"
    )
    empty = create_calendar(name="Home")
    raw = empty.raw_bytes.replace(b"END:VCALENDAR", zone + b"END:VCALENDAR")
    document = parse_calendar(raw)
    assert calendar_zone_names(document.components[0]) == ("Home/West",)
    draft = CalendarEntryDraft(start=START, end=END, tzid="Home/West")
    with pytest.raises(CalendarEditError, match="destination Calendar"):
        add_entry(empty, draft)
    authored = add_entry(document, draft)
    assert authored.entries[0].zone is not None
    assert b"DTSTART;TZID=Home/West:20261101T090000\r\n" in authored.raw_bytes
    assert authored.entries[0].timing_editable
    edited = update_entry(
        authored, 0, CalendarEntryChanges(start=START.replace(minute=30))
    )
    assert edited.raw_bytes == authored.raw_bytes.replace(
        b"20261101T090000", b"20261101T093000"
    )
    assert zone in edited.raw_bytes


def test_timezone_change_checks_stream_position_and_rewrites_only_event_dates() -> None:
    zone = (
        b"BEGIN:VTIMEZONE\r\nTZID:Home/West\r\nBEGIN:STANDARD\r\n"
        b"TZOFFSETTO:-0500\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
    )
    raw = (
        _series("RRULE:FREQ=DAILY;COUNT=3")
        .replace(b"BEGIN:VEVENT", zone + b"BEGIN:VEVENT")
        .replace(
            b"END:VCALENDAR",
            zone.replace(b"Home/West", b"Late/Zone") + b"END:VCALENDAR",
        )
    )
    document = parse_calendar(raw)
    assert calendar_zone_names(
        document.components[0], before_offset=document.entries[0].component.start_offset
    ) == ("Home/West",)
    with pytest.raises(CalendarEditError, match="defined before this event"):
        update_entry(document, 0, CalendarEntryChanges(tzid="Late/Zone"))
    zoned = update_entry(document, 0, CalendarEntryChanges(tzid="Home/West"))
    assert zoned.raw_bytes == raw.replace(
        b"DTSTART:20261101", b"DTSTART;TZID=Home/West:20261101"
    ).replace(b"DTEND:20261101", b"DTEND;TZID=Home/West:20261101")
    utc = update_entry(
        zoned,
        0,
        CalendarEntryChanges(tzid=None, start=START.assume_utc(), end=END.assume_utc()),
    )
    assert utc.raw_bytes == raw.replace(b"T090000\r\n", b"T090000Z\r\n").replace(
        b"T100000\r\n", b"T100000Z\r\n"
    )
    local = update_entry(utc, 0, CalendarEntryChanges(tzid=None, start=START, end=END))
    assert local.raw_bytes == raw


@pytest.mark.parametrize("status", tuple(CalendarTodoStatus))
def test_native_todo_states_are_written_and_reopen_without_progress_changes(
    status: CalendarTodoStatus,
) -> None:
    raw = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n"
        b"SUMMARY:Task\r\nPERCENT-COMPLETE:40\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
    )
    state = update_entry(
        parse_calendar(raw), 0, CalendarEntryChanges(todo_status=status)
    )
    assert state.entries[0].todo_status is status
    assert state.entries[0].completed is (status is CalendarTodoStatus.COMPLETED)
    assert f"STATUS:{status.value}\r\n".encode() in state.raw_bytes
    assert b"COMPLETED:" not in state.raw_bytes
    reopened = update_entry(state, 0, CalendarEntryChanges(todo_status=None))
    assert reopened.raw_bytes == raw
