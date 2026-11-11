"""Calendar documents preserve evidence while explicitly supported edits work."""

import pytest
from whenever import Date, Instant, PlainDateTime

from iPodDB.calendar import (
    CalendarDateForm,
    CalendarEditError,
    CalendarEntryChanges,
    CalendarEntryDraft,
    CalendarEntryKind,
    CalendarLimits,
    CalendarValue,
    add_entry,
    create_calendar,
    parse_calendar,
    remove_entry,
    rename_calendar,
    serialize_calendar,
    update_entry,
)

STAMP = Instant.from_utc(2026, 11, 7, 12)


def test_calendar_name_edits_preserve_events_unknown_bytes_and_original_spelling() -> (
    None
):
    raw = calendar(
        b"X-WR-CALNAME:Old\\, name\r\nX-KEEP:opaque\r\n"
        + event(b"SUMMARY:Untouched\r\n")
    )
    document = parse_calendar(raw)
    assert document.components[0].calendar_name == "Old, name"
    assert serialize_calendar(rename_calendar(document, "Old, name")) == raw
    renamed = rename_calendar(document, "Team; 東京")
    assert renamed.components[0].calendar_name == "Team; 東京"
    assert (
        renamed.entries[0].component.raw_bytes
        == document.entries[0].component.raw_bytes
    )
    assert b"X-KEEP:opaque\r\n" in renamed.raw_bytes


def test_missing_calendar_name_is_inserted_before_events() -> None:
    document = create_calendar(
        (CalendarEntryDraft(start=Date(2026, 11, 8)),), stamp=STAMP
    )
    renamed = rename_calendar(document, "Work")
    assert renamed.raw_bytes.index(b"X-WR-CALNAME:Work") < renamed.raw_bytes.index(
        b"BEGIN:VEVENT"
    )
    assert (
        renamed.entries[0].component.raw_bytes
        == document.entries[0].component.raw_bytes
    )


@pytest.mark.parametrize("name", ("", "  ", "one\ntwo", "bad\x00", "x" * 1025))
def test_calendar_name_rejects_empty_control_and_oversized_values(name: str) -> None:
    with pytest.raises(CalendarEditError):
        rename_calendar(create_calendar(), name)


def test_duplicate_calendar_names_are_preserved_without_choosing_a_winner() -> None:
    document = parse_calendar(calendar(b"X-WR-CALNAME:A\r\nX-WR-CALNAME:B\r\n"))
    assert document.components[0].calendar_name is None
    with pytest.raises(CalendarEditError, match="ambiguous"):
        rename_calendar(document, "Replacement")


def calendar(body: bytes, *, version: bytes = b"2.0") -> bytes:
    return (
        b"BEGIN:VCALENDAR\r\nVERSION:" + version + b"\r\n" + body + b"END:VCALENDAR\r\n"
    )


def event(body: bytes) -> bytes:
    return b"BEGIN:VEVENT\r\nUID:original\r\n" + body + b"END:VEVENT\r\n"


@pytest.mark.parametrize(
    ("property_line", "form", "value", "tzid"),
    [
        (
            b"DTSTART;VALUE=DATE:20261101",
            CalendarDateForm.DATE,
            Date(2026, 11, 1),
            None,
        ),
        (
            b"DTSTART:20261101T013000",
            CalendarDateForm.FLOATING,
            PlainDateTime(2026, 11, 1, 1, 30),
            None,
        ),
        (
            b"DTSTART:20261101T013000Z",
            CalendarDateForm.UTC,
            Instant.from_utc(2026, 11, 1, 1, 30),
            None,
        ),
        (
            b"DTSTART;TZID=America/New_York:20261101T013000",
            CalendarDateForm.ZONED,
            PlainDateTime(2026, 11, 1, 1, 30),
            "America/New_York",
        ),
        (
            b"DTSTART;TZID=America/New_York:20260308T023000",
            CalendarDateForm.ZONED,
            PlainDateTime(2026, 3, 8, 2, 30),
            "America/New_York",
        ),
        (
            b'DTSTART;TZID="Custom:Zone;Name":20261101T013000',
            CalendarDateForm.ZONED,
            PlainDateTime(2026, 11, 1, 1, 30),
            "Custom:Zone;Name",
        ),
    ],
)
def test_date_forms_keep_folds_gaps_and_custom_zone_names(
    property_line: bytes, form: CalendarDateForm, value: CalendarValue, tzid: str | None
) -> None:
    raw = calendar(event(property_line + b"\r\n"))
    document = parse_calendar(raw)
    observed = document.entries[0].start
    assert observed is not None
    assert (observed.form, observed.value, observed.tzid) == (form, value, tzid)
    assert serialize_calendar(document) == raw


@pytest.mark.parametrize(
    "value",
    [
        b"20260230T010000",
        b"20261301",
        b"20261101T256199",
        b"00000101",
        b"2026",
        b"20261101T013000+0530",
        b"20261101T013000z",
        b"",
    ],
)
def test_malformed_optional_dates_do_not_block_inspection_or_text_edits(
    value: bytes,
) -> None:
    raw = calendar(
        event(b"SUMMARY:Old\r\nDTSTART:" + value + b"\r\nX-UNKNOWN:keep\r\n")
    )
    document = parse_calendar(raw)
    item = document.entries[0]
    assert item.start is not None and item.start.form is CalendarDateForm.INVALID
    assert item.issues
    assert document.editable and item.editable
    edited = update_entry(document, 0, CalendarEntryChanges(summary="New"))
    assert edited.raw_bytes == raw.replace(b"SUMMARY:Old", b"SUMMARY:New")
    assert document.raw_bytes == raw


def test_text_unfolding_unescaping_and_utf8_split_at_physical_boundary() -> None:
    raw = calendar(
        event(
            b'SUMMARY:Alice "says: caf\xc3\r\n \xa9\\, lunch\\; later\r\nDESCRIPTION:one\\ntwo\\Nthree\\\\four\r\n'
        )
    )
    document = parse_calendar(raw)
    assert document.editable
    item = document.entries[0]
    assert item.summary == 'Alice "says: café, lunch; later'
    assert item.description == "one\ntwo\nthree\\four"
    assert document.raw_bytes == raw


def test_complex_calendar_allows_text_only_and_preserves_unknown_bytes() -> None:
    zone = b"BEGIN:VTIMEZONE\r\nTZID:Custom\r\nBEGIN:STANDARD\r\nX-WEIRD:123\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
    recurring = event(
        b"SUMMARY;LANGUAGE=en;X-KEEP=odd:Old\r\nDTSTART;TZID=Custom:20261101T013000\r\nRRULE:FREQ=DAILY;COUNT=5\r\nX-UNKNOWN:alpha\r\n beta\r\nBEGIN:VALARM\r\nTRIGGER:-PT15M\r\nACTION:DISPLAY\r\nEND:VALARM\r\n"
    )
    other = (
        b"BEGIN:VTODO\r\nUID:todo\r\nSUMMARY:Other\r\nX-BLOB:untouched\r\nEND:VTODO\r\n"
    )
    raw = calendar(zone + recurring + other)
    document = parse_calendar(raw)
    assert document.entries[0].editable
    assert not document.entries[0].timing_editable
    assert document.entries[0].has_recurrence
    edited = update_entry(document, 0, CalendarEntryChanges(summary="Changed"))
    assert edited.raw_bytes == raw.replace(b"X-KEEP=odd:Old", b"X-KEEP=odd:Changed")
    assert zone in edited.raw_bytes and other in edited.raw_bytes
    with pytest.raises(CalendarEditError, match="Timing"):
        update_entry(
            document, 0, CalendarEntryChanges(start=PlainDateTime(2026, 11, 2, 1, 30))
        )


def test_simple_authoring_add_update_remove_and_todo_completion() -> None:
    document = create_calendar(
        [
            CalendarEntryDraft(
                summary="Trip",
                uid="event",
                start=Date(2026, 11, 7),
                end=Date(2026, 11, 8),
            )
        ],
        stamp=STAMP,
    )
    document = add_entry(
        document,
        CalendarEntryDraft(
            kind=CalendarEntryKind.TODO,
            summary="Pack",
            uid="todo",
            due=Date(2026, 11, 6),
        ),
        stamp=STAMP,
    )
    assert [entry.kind for entry in document.entries] == [
        CalendarEntryKind.EVENT,
        CalendarEntryKind.TODO,
    ]
    original_event = document.entries[0].component.raw_bytes
    completed = update_entry(document, 1, CalendarEntryChanges(completed=True))
    assert completed.entries[1].completed
    assert completed.entries[1].completed_at is None
    assert completed.entries[0].component.raw_bytes == original_event
    reopened = update_entry(
        completed, 1, CalendarEntryChanges(completed=False, due=None)
    )
    assert not reopened.entries[1].completed
    assert reopened.entries[1].completed_at is None
    assert reopened.entries[1].due is None
    removed = remove_entry(reopened, 1)
    assert removed.entries[0].component.raw_bytes == original_event
    assert len(removed.entries) == 1
    assert remove_entry(removed, 0).entries == ()


def test_authored_utc_and_floating_forms_do_not_use_host_zone() -> None:
    document = create_calendar(
        [
            CalendarEntryDraft(start=PlainDateTime(2026, 3, 8, 2, 30)),
            CalendarEntryDraft(start=Instant.from_utc(2026, 11, 1, 1, 30)),
        ],
        stamp=STAMP,
    )
    assert document.entries[0].start is not None
    assert document.entries[0].start.form is CalendarDateForm.FLOATING
    assert document.entries[1].start is not None
    assert document.entries[1].start.form is CalendarDateForm.UTC
    assert b"DTSTART:20260308T023000\r\n" in document.raw_bytes
    assert b"DTSTART:20261101T013000Z\r\n" in document.raw_bytes


def test_authoring_folds_utf8_and_escapes_text_without_injection() -> None:
    summary = "😀é" * 40 + ", semi; back\\line\nEND:VEVENT\nBEGIN:VTODO"
    document = create_calendar(
        [CalendarEntryDraft(summary=summary, start=Date(2026, 11, 7))], stamp=STAMP
    )
    assert len(document.entries) == 1
    assert document.entries[0].summary == summary
    assert all(len(line) <= 75 for line in document.raw_bytes.split(b"\r\n"))
    for line in document.raw_bytes.split(b"\r\n"):
        line.decode("utf-8")


@pytest.mark.parametrize(
    "raw",
    [
        calendar(event(b"DTSTART:20261101T013000\r\n"), version=b"1.0"),
        b"unrecognized\x00\xff\nnot-a-calendar",
        calendar(event(b"SUMMARY;ENCODING=QUOTED-PRINTABLE:ol=E9\r\n")),
        calendar(event(b"SUMMARY:One\r\nSUMMARY:Two\r\n")),
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nSUMMARY:Missing ends\r\n",
        calendar(event(b"SUMMARY:\xff\r\n")),
    ],
)
def test_unusual_inputs_remain_lossless_and_unsupported_field_edits_are_rejected(
    raw: bytes,
) -> None:
    document = parse_calendar(raw)
    assert document.raw_bytes == raw
    assert serialize_calendar(document) == raw
    if document.entries:
        assert not document.editable or not document.entries[0].editable
        with pytest.raises(CalendarEditError):
            update_entry(document, 0, CalendarEntryChanges(summary="New"))


@pytest.mark.parametrize(
    "limits",
    [
        CalendarLimits(max_bytes=10),
        CalendarLimits(max_lines=2),
        CalendarLimits(max_line_bytes=5),
        CalendarLimits(max_components=1),
        CalendarLimits(max_depth=1),
    ],
)
def test_resource_limits_return_opaque_original_bytes(limits: CalendarLimits) -> None:
    raw = calendar(event(b"SUMMARY:Some long title\r\n"))
    document = parse_calendar(raw, limits=limits)
    assert document.raw_bytes == raw
    assert document.entries == ()
    assert not document.editable and document.issues


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (Date(2026, 11, 7), Date(2026, 11, 7)),
        (PlainDateTime(2026, 11, 7, 12), PlainDateTime(2026, 11, 7, 11)),
        (Date(2026, 11, 7), PlainDateTime(2026, 11, 8)),
    ],
)
def test_new_event_ranges_use_exclusive_all_day_end_and_consistent_forms(
    start: CalendarValue, end: CalendarValue
) -> None:
    with pytest.raises(CalendarEditError):
        create_calendar([CalendarEntryDraft(start=start, end=end)], stamp=STAMP)


@pytest.mark.parametrize("kind", [CalendarEntryKind.EVENT, CalendarEntryKind.TODO])
@pytest.mark.parametrize(
    ("start", "later"),
    [
        (Date(2026, 11, 7), Date(2026, 11, 8)),
        (PlainDateTime(2026, 11, 7, 12), PlainDateTime(2026, 11, 7, 12, 1)),
        (STAMP, Instant.from_utc(2026, 11, 7, 12, 1)),
    ],
)
def test_authored_end_and_due_must_be_strictly_later_than_start(
    kind: CalendarEntryKind, start: CalendarValue, later: CalendarValue
) -> None:
    is_event = kind is CalendarEntryKind.EVENT
    with pytest.raises(CalendarEditError, match="later than start"):
        create_calendar(
            [
                CalendarEntryDraft(
                    kind=kind,
                    start=start,
                    end=start if is_event else None,
                    due=None if is_event else start,
                )
            ],
            stamp=STAMP,
        )
    document = create_calendar(
        [
            CalendarEntryDraft(
                kind=kind,
                start=start,
                end=later if is_event else None,
                due=None if is_event else later,
            )
        ],
        stamp=STAMP,
    )
    raw = document.raw_bytes
    # The retained start participates even when only the end or due date changes.
    equal_end = (
        CalendarEntryChanges(end=start) if is_event else CalendarEntryChanges(due=start)
    )
    with pytest.raises(CalendarEditError, match="later than start"):
        update_entry(document, 0, equal_end)
    with pytest.raises(CalendarEditError, match="later than start"):
        update_entry(document, 0, CalendarEntryChanges(start=later))
    assert document.raw_bytes == raw
    absent_end = (
        CalendarEntryChanges(end=None) if is_event else CalendarEntryChanges(due=None)
    )
    without_end = update_entry(document, 0, absent_end)
    assert without_end.entries[0].start is not None
    assert without_end.entries[0].end is None
    assert without_end.entries[0].due is None


@pytest.mark.parametrize("kind", [CalendarEntryKind.EVENT, CalendarEntryKind.TODO])
@pytest.mark.parametrize(
    "start", [Date(2026, 11, 7), PlainDateTime(2026, 11, 7, 12), STAMP]
)
def test_authoring_without_an_end_or_due_is_allowed(
    kind: CalendarEntryKind, start: CalendarValue
) -> None:
    document = create_calendar(
        [CalendarEntryDraft(kind=kind, start=start)], stamp=STAMP
    )
    assert document.entries[0].start is not None
    assert document.entries[0].start.value == start
    assert document.entries[0].end is None
    assert document.entries[0].due is None


@pytest.mark.parametrize("kind", [CalendarEntryKind.EVENT, CalendarEntryKind.TODO])
@pytest.mark.parametrize(
    "value", [b"20261107", b"20261107T120000", b"20261107T120000Z"]
)
def test_equal_or_invalid_imported_ranges_survive_unrelated_edits(
    kind: CalendarEntryKind, value: bytes
) -> None:
    component = kind.value.encode("ascii")
    end_name = b"DTEND" if kind is CalendarEntryKind.EVENT else b"DUE"
    for end in (value, b"not-a-date"):
        raw = calendar(
            b"BEGIN:"
            + component
            + b"\r\nSUMMARY:Old\r\nDTSTART:"
            + value
            + b"\r\n"
            + end_name
            + b":"
            + end
            + b"\r\nEND:"
            + component
            + b"\r\n"
        )
        document = parse_calendar(raw)
        assert serialize_calendar(document) == raw
        assert update_entry(document, 0, CalendarEntryChanges()).raw_bytes == raw
        updated = update_entry(document, 0, CalendarEntryChanges(summary="New"))
        assert updated.raw_bytes == raw.replace(b"SUMMARY:Old", b"SUMMARY:New")


def test_noop_and_unrelated_lf_bytes_are_exact() -> None:
    raw = b"\xef\xbb\xbf" + calendar(
        event(b"SUMMARY:Old\r\nX-FOO:unknown\r\n")
    ).replace(b"\r\n", b"\n")
    document = parse_calendar(raw)
    assert update_entry(document, 0, CalendarEntryChanges()) is document
    assert update_entry(
        document, 0, CalendarEntryChanges(summary="New")
    ).raw_bytes == raw.replace(b"SUMMARY:Old", b"SUMMARY:New")


def test_explicit_date_repair_does_not_rewrite_other_properties() -> None:
    raw = calendar(event(b"DTSTART:20269999T999999\r\nX-KEEP:opaque\r\n"))
    updated = update_entry(
        parse_calendar(raw),
        0,
        CalendarEntryChanges(start=Date(2026, 11, 7), end=Date(2026, 11, 8)),
    )
    assert updated.entries[0].start is not None
    assert updated.entries[0].start.value == Date(2026, 11, 7)
    assert b"X-KEEP:opaque\r\n" in updated.raw_bytes


def test_date_parameter_conflicts_remain_nonblocking() -> None:
    raw = calendar(
        event(
            b"DTSTART;VALUE=DATE;TZID=Custom:20261101\r\nDTEND;TZID=One;TZID=Two:20261102T120000\r\n"
        )
    )
    document = parse_calendar(raw)
    assert document.entries[0].start is not None
    assert document.entries[0].start.form is CalendarDateForm.INVALID
    assert document.entries[0].end is not None
    assert document.entries[0].end.form is CalendarDateForm.INVALID
    assert serialize_calendar(document) == raw


def test_entry_ids_are_document_local_and_invalid_targets_do_not_mutate() -> None:
    document = create_calendar(
        [CalendarEntryDraft(start=Date(2026, 11, 7))], stamp=STAMP
    )
    with pytest.raises(CalendarEditError, match="no longer present"):
        remove_entry(document, 99)
    with pytest.raises(CalendarEditError, match="no longer present"):
        update_entry(document, 99, CalendarEntryChanges(summary="Gone"))


def test_repeated_text_edit_preserves_original_folding_and_parameters() -> None:
    raw = calendar(
        event(b"SUMMARY;LANGUAGE=en:Long\r\n  title\r\nDTSTART:20261107\r\n")
    )
    document = parse_calendar(raw)
    assert document.entries[0].summary == "Long title"
    assert (
        update_entry(document, 0, CalendarEntryChanges(summary="Long title")).raw_bytes
        == raw
    )


def test_unknown_datetime_parameters_survive_text_edits_and_prohibit_lossy_replacement() -> (
    None
):
    raw = calendar(
        event(b"SUMMARY:Old\r\nDTSTART;X-DEVICE-RULE=retain:20261107T120000\r\n")
    )
    document = parse_calendar(raw)
    assert not document.entries[0].timing_editable
    assert update_entry(
        document, 0, CalendarEntryChanges(summary="New")
    ).raw_bytes == raw.replace(b"SUMMARY:Old", b"SUMMARY:New")
    with pytest.raises(CalendarEditError, match="Timing"):
        update_entry(document, 0, CalendarEntryChanges(start=Date(2026, 11, 8)))


def test_completed_timestamp_without_status_is_visible_and_explicit_edits_stay_consistent() -> (
    None
):
    raw = calendar(
        b"BEGIN:VTODO\r\nSUMMARY:Done\r\nCOMPLETED:20261107T120000Z\r\nEND:VTODO\r\n"
    )
    document = parse_calendar(raw)
    assert not document.entries[0].completed
    assert document.entries[0].completed_at is not None
    with pytest.raises(CalendarEditError, match="conflicts"):
        update_entry(
            document, 0, CalendarEntryChanges(completed=False, completed_at=STAMP)
        )
    without_stamp = update_entry(document, 0, CalendarEntryChanges(completed=False))
    restored = update_entry(without_stamp, 0, CalendarEntryChanges(completed_at=STAMP))
    assert restored.entries[0].completed
    assert b"STATUS:COMPLETED\r\n" in restored.raw_bytes


@pytest.mark.parametrize(
    "changes",
    [CalendarEntryChanges(completed=True), CalendarEntryChanges(completed_at=STAMP)],
)
def test_completion_preserves_existing_percentage_and_its_parameters(
    changes: CalendarEntryChanges,
) -> None:
    percentage = b'PERCENT-COMPLETE;X-KEEP="part:one":4\r\n 0\r\n'
    raw = calendar(
        b"BEGIN:VTODO\r\nSUMMARY:Task\r\n"
        + percentage
        + b"X-UNKNOWN:preserved\r\nEND:VTODO\r\n"
    )
    original = parse_calendar(raw)
    completed = update_entry(original, 0, changes)
    assert completed.entries[0].completed
    assert (completed.entries[0].completed_at is not None) is (
        changes.completed_at == STAMP
    )
    assert percentage in completed.raw_bytes
    assert b"X-UNKNOWN:preserved\r\n" in completed.raw_bytes
    assert original.raw_bytes == raw


def test_reopening_preserves_percentage_metadata() -> None:
    raw = calendar(
        b"BEGIN:VTODO\r\nSUMMARY:Task\r\nSTATUS:COMPLETED\r\n"
        b"COMPLETED:20261107T120000Z\r\nPERCENT-COMPLETE;X-KEEP=old:100\r\n"
        b"X-UNKNOWN:preserved\r\nEND:VTODO\r\n"
    )
    reopened = update_entry(
        parse_calendar(raw), 0, CalendarEntryChanges(completed=False)
    )
    assert not reopened.entries[0].completed
    assert reopened.entries[0].completed_at is None
    assert b"PERCENT-COMPLETE;X-KEEP=old:100\r\n" in reopened.raw_bytes
    assert b"STATUS:" not in reopened.raw_bytes
    assert b"X-UNKNOWN:preserved\r\n" in reopened.raw_bytes


def test_completion_does_not_add_absent_percentage() -> None:
    original = parse_calendar(calendar(b"BEGIN:VTODO\r\nSUMMARY:Task\r\nEND:VTODO\r\n"))
    completed = update_entry(original, 0, CalendarEntryChanges(completed=True))
    reopened = update_entry(completed, 0, CalendarEntryChanges(completed=False))
    assert b"PERCENT-COMPLETE" not in completed.raw_bytes
    assert b"PERCENT-COMPLETE" not in reopened.raw_bytes


@pytest.mark.parametrize(
    "changes",
    [
        CalendarEntryChanges(),
        CalendarEntryChanges(summary="Renamed"),
        CalendarEntryChanges(due=Date(2026, 11, 8)),
        CalendarEntryChanges(completed_at=None),
    ],
)
def test_unrelated_edits_preserve_percentage_bytes(
    changes: CalendarEntryChanges,
) -> None:
    percentage = b'PERCENT-COMPLETE;X-KEEP="part:one":4\r\n 0\r\n'
    raw = calendar(b"BEGIN:VTODO\r\nSUMMARY:Task\r\n" + percentage + b"END:VTODO\r\n")
    updated = update_entry(parse_calendar(raw), 0, changes)
    assert percentage in updated.raw_bytes
    if changes == CalendarEntryChanges():
        assert updated.raw_bytes == raw


def test_duplicate_percentages_are_retained_read_only() -> None:
    raw = calendar(
        b"BEGIN:VTODO\r\nSUMMARY:Task\r\nPERCENT-COMPLETE:40\r\n"
        b"percent-complete:100\r\nEND:VTODO\r\n"
    )
    document = parse_calendar(raw)
    assert document.editable and not document.entries[0].editable
    assert serialize_calendar(document) == raw
    for changes in (
        CalendarEntryChanges(completed=True),
        CalendarEntryChanges(completed=False),
        CalendarEntryChanges(summary="Renamed"),
    ):
        with pytest.raises(CalendarEditError, match="repeated properties"):
            update_entry(document, 0, changes)
    assert document.raw_bytes == raw


def test_multiple_calendars_can_be_inspected_but_are_not_rewritten_as_one() -> None:
    raw = calendar(event(b"SUMMARY:One\r\n")) + calendar(event(b"SUMMARY:Two\r\n"))
    document = parse_calendar(raw)
    assert [item.summary for item in document.entries] == ["One", "Two"]
    assert not document.editable
    assert serialize_calendar(document) == raw
    with pytest.raises(CalendarEditError):
        remove_entry(document, 0)
