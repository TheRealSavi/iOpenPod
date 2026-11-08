"""Qualified recurrence/reminder behavior, independent of a Host timezone."""

from dataclasses import replace

import pytest
from whenever import Date, PlainDateTime

from iPodDB.calendar import (
    CalendarEditError,
    CalendarEntryChanges,
    CalendarEntryDraft,
    CalendarFrequency,
    CalendarProfile,
    CalendarRecurrenceRule,
    CalendarReminderDraft,
    create_calendar,
    editable_reminder,
    parse_calendar,
    project_occurrences,
    serialize_calendar,
    update_entry,
)

MINI = CalendarProfile.MINI_2_1_4_1
CLASSICS = tuple(
    profile for profile in CalendarProfile if profile.name.startswith("CLASSIC")
)
START = PlainDateTime(2026, 11, 1, 9)
END = PlainDateTime(2026, 11, 1, 10)


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
def test_mini_membership_matches_qualified_native_vectors(
    rule: str, offsets: tuple[int, ...]
) -> None:
    raw = _series("RRULE:" + rule)
    document = parse_calendar(raw)
    result = project_occurrences(
        document.entries[0], Date(2026, 10, 30), Date(2026, 12, 8), profile=MINI
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
    result = project_occurrences(
        entry, seed.date(), seed.date().add(days=4), profile=MINI
    )
    assert result.expanded
    assert [occurrence.start.value for occurrence in result.occurrences] == [
        seed.add(days=index, naive_arithmetic_ok=True) for index in range(3)
    ]


@pytest.mark.parametrize(
    "rule",
    (
        "FREQ=MONTHLY",
        "FREQ=YEARLY",
        "FREQ=DAILY;BYDAY=MO",
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
        document.entries[0], Date(2026, 11, 1), Date(2026, 11, 30), profile=MINI
    )
    assert not result.expanded and result.detail
    assert serialize_calendar(document) == raw


@pytest.mark.parametrize("profile", (CalendarProfile.UNKNOWN, *CLASSICS))
def test_mini_expansion_is_not_transferred_to_other_firmwares(
    profile: CalendarProfile,
) -> None:
    entry = parse_calendar(_series("RRULE:FREQ=DAILY;COUNT=3")).entries[0]
    assert not project_occurrences(
        entry, Date(2026, 11, 1), Date(2026, 11, 30), profile=profile
    ).expanded
    with pytest.raises(CalendarEditError):
        create_calendar(
            (
                CalendarEntryDraft(
                    start=START,
                    end=END,
                    recurrence=CalendarRecurrenceRule(CalendarFrequency.DAILY),
                ),
            ),
            profile=profile,
        )


def test_recurrence_edit_changes_only_its_property() -> None:
    raw = _series("RRULE:FREQ=DAILY;COUNT=3")
    document = parse_calendar(raw)
    rule = CalendarRecurrenceRule(CalendarFrequency.WEEKLY, 2, 3)
    updated = update_entry(
        document, 0, CalendarEntryChanges(recurrence=rule), profile=MINI
    )
    assert updated.raw_bytes == raw.replace(
        b"RRULE:FREQ=DAILY;COUNT=3", b"RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=3"
    )
    assert b"X-KEEP:opaque" in updated.raw_bytes
    removed = update_entry(
        document, 0, CalendarEntryChanges(recurrence=None), profile=MINI
    )
    assert removed.raw_bytes == raw.replace(b"RRULE:FREQ=DAILY;COUNT=3\r\n", b"")


@pytest.mark.parametrize("profile", CLASSICS)
def test_classic_creates_only_one_trigger_without_invented_action(
    profile: CalendarProfile,
) -> None:
    draft = CalendarEntryDraft(start=START, end=END, reminder=CalendarReminderDraft(15))
    document = create_calendar((draft,), profile=profile)
    reminder = document.entries[0].reminders[0]
    assert reminder.relative_seconds == -900
    assert reminder.action is None
    assert b"BEGIN:VALARM\r\nTRIGGER:-PT15M\r\nEND:VALARM" in document.raw_bytes
    assert b"ACTION" not in document.raw_bytes
    assert editable_reminder(document.entries[0], profile) == CalendarReminderDraft(15)


def test_existing_reminder_edit_preserves_unknown_fields_and_other_components() -> None:
    raw = _series(
        "BEGIN:VALARM\r\nX-KEEP-ALARM:opaque\r\nACTION:AUDIO\r\nTRIGGER;RELATED=START:-PT15M\r\nEND:VALARM"
    )
    document = parse_calendar(raw)
    updated = update_entry(
        document,
        0,
        CalendarEntryChanges(reminder=CalendarReminderDraft(30)),
        profile=CLASSICS[0],
    )
    assert updated.raw_bytes == raw.replace(
        b"TRIGGER;RELATED=START:-PT15M", b"TRIGGER:-PT30M"
    )
    assert b"ACTION:AUDIO" in updated.raw_bytes
    removed = update_entry(
        document, 0, CalendarEntryChanges(reminder=None), profile=CLASSICS[0]
    )
    assert not removed.entries[0].reminders
    assert b"X-KEEP:opaque" in removed.raw_bytes


@pytest.mark.parametrize(
    "body",
    (
        "BEGIN:VALARM\r\nTRIGGER;VALUE=DATE-TIME:20261101T090000Z\r\nEND:VALARM",
        "BEGIN:VALARM\r\nTRIGGER;RELATED=END:-PT15M\r\nEND:VALARM",
        "BEGIN:VALARM\r\nTRIGGER:-P1W\r\nEND:VALARM",
        "BEGIN:VALARM\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nBEGIN:VALARM\r\nTRIGGER:-PT30M\r\nEND:VALARM",
    ),
)
def test_unsupported_reminders_remain_readonly_and_survive_text_edits(
    body: str,
) -> None:
    raw = _series(body)
    document = parse_calendar(raw)
    assert editable_reminder(document.entries[0], CLASSICS[0]) is None
    text = update_entry(document, 0, CalendarEntryChanges(summary="Changed"))
    assert text.raw_bytes == raw.replace(b"SUMMARY:Keep", b"SUMMARY:Changed")
    with pytest.raises(CalendarEditError):
        update_entry(
            document,
            0,
            CalendarEntryChanges(reminder=CalendarReminderDraft(10)),
            profile=CLASSICS[0],
        )


@pytest.mark.parametrize("profile", (CalendarProfile.UNKNOWN, MINI))
def test_new_reminders_are_not_authorized_by_parser_recognition(
    profile: CalendarProfile,
) -> None:
    with pytest.raises(CalendarEditError):
        create_calendar(
            (
                CalendarEntryDraft(
                    start=START, end=END, reminder=CalendarReminderDraft(15)
                ),
            ),
            profile=profile,
        )


def test_unsupported_all_day_or_multi_day_recurrence_cannot_be_authored() -> None:
    draft = CalendarEntryDraft(
        start=START, end=END, recurrence=CalendarRecurrenceRule(CalendarFrequency.DAILY)
    )
    for changed in (
        replace(draft, start=Date(2026, 11, 1)),
        replace(draft, end=END.add(days=1, naive_arithmetic_ok=True)),
    ):
        with pytest.raises(CalendarEditError):
            create_calendar((changed,), profile=MINI)


def test_legacy_recurrence_does_not_acquire_modern_expansion() -> None:
    raw = _series("RRULE:FREQ=DAILY;COUNT=3").replace(b"VERSION:2.0", b"VERSION:1.0")
    document = parse_calendar(raw)
    assert not project_occurrences(
        document.entries[0], Date(2026, 11, 1), Date(2026, 11, 30), profile=MINI
    ).expanded
    assert serialize_calendar(document) == raw


def test_backend_rejects_reminder_on_a_simultaneously_changed_all_day_event() -> None:
    document = parse_calendar(_series("X-KEEP-EXTRA:opaque"))
    with pytest.raises(CalendarEditError, match="floating"):
        update_entry(
            document,
            0,
            CalendarEntryChanges(
                start=Date(2026, 11, 1),
                end=Date(2026, 11, 2),
                reminder=CalendarReminderDraft(15),
            ),
            profile=CLASSICS[0],
        )


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
                profile=MINI,
            )


def test_occurrence_queries_are_bounded_without_scanning_from_series_origin() -> None:
    raw = _series("RRULE:FREQ=DAILY", start="19000101T090000", end="19000101T100000")
    entry = parse_calendar(raw).entries[0]
    result = project_occurrences(
        entry, Date(2026, 11, 1), Date(2026, 11, 30), profile=MINI
    )
    assert result.expanded and len(result.occurrences) == 30
    with pytest.raises(ValueError, match="63 days"):
        project_occurrences(entry, Date(2026, 1, 1), Date(2026, 12, 31), profile=MINI)


def test_oversized_native_reminder_stays_uninterpreted_instead_of_host_integer_guess() -> (
    None
):
    raw = _series("BEGIN:VALARM\r\nTRIGGER:-P999999D\r\nEND:VALARM")
    document = parse_calendar(raw)
    reminder = document.entries[0].reminders[0]
    assert reminder.relative_seconds is None
    assert reminder.issues
    assert serialize_calendar(document) == raw
