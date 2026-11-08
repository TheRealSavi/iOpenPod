"""Bounded Calendar inspection and surgical iCalendar 2.0 edits.

Unmodified documents always return their original bytes. Unknown components,
properties, folding, line endings and legacy vCalendar data are retained. This
is not a recurrence engine or an implementation of firmware's permissive parser.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from whenever import Date, Instant, PlainDateTime

from iPodDB.calendar.models import (
    UNCHANGED,
    CalendarComponent,
    CalendarDateForm,
    CalendarDateTime,
    CalendarDocument,
    CalendarEditError,
    CalendarEntry,
    CalendarEntryChanges,
    CalendarEntryDraft,
    CalendarEntryKind,
    CalendarLimits,
    CalendarParameter,
    CalendarProfile,
    CalendarProperty,
    CalendarRecurrence,
    CalendarRecurrenceRule,
    CalendarReminder,
    CalendarReminderDraft,
    CalendarValue,
    Unchanged,
)
from iPodDB.calendar.recurrence import recurrence_rule, validate_recurrence
from iPodDB.calendar.reminders import (
    editable_reminder,
    supports_reminders,
    validate_reminder,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_NAME = re.compile(r"[A-Za-z0-9-]+\Z")
_DATE = re.compile(r"[0-9]{8}\Z")
_DATETIME = re.compile(r"[0-9]{8}T[0-9]{6}Z?\Z")
_PHYSICAL = re.compile(rb"[^\r\n]*(?:\r\n|\r|\n|$)")
_DEFAULT_LIMITS = CalendarLimits()
_RECURRENCE = frozenset(("RRULE", "EXRULE", "RDATE", "EXDATE", "RECURRENCE-ID"))
_SINGULAR = frozenset(
    (
        "UID",
        "SUMMARY",
        "DESCRIPTION",
        "LOCATION",
        "DTSTART",
        "DTEND",
        "DUE",
        "COMPLETED",
        "STATUS",
        "PERCENT-COMPLETE",
    )
)


@dataclass(slots=True)
class _Line:
    start: int
    end: int
    payload: bytes


@dataclass(slots=True)
class _Node:
    name: str
    start: int
    properties: list[CalendarProperty] = field(default_factory=list[CalendarProperty])
    children: list[CalendarComponent] = field(default_factory=list[CalendarComponent])


class _BoundExceededError(Exception):
    pass


def _split_quoted(value: str, separator: str) -> list[str]:
    parts: list[str] = []
    quoted = False
    start = 0
    for index, character in enumerate(value):
        if character == '"':
            quoted = not quoted
        elif character == separator and not quoted:
            parts.append(value[start:index])
            start = index + 1
    if quoted:
        raise ValueError("Unclosed parameter quote")
    parts.append(value[start:])
    return parts


def _lines(data: bytes, limits: CalendarLimits) -> list[_Line]:
    result: list[_Line] = []
    physical_count = 0
    for match in _PHYSICAL.finditer(data):
        if match.start() == match.end():
            continue
        physical_count += 1
        if physical_count > limits.max_lines:
            raise _BoundExceededError(
                "Calendar has too many lines; original bytes retained."
            )
        payload = match.group().rstrip(b"\r\n")
        if payload.startswith((b" ", b"\t")) and result:
            previous = result[-1]
            previous.payload += payload[1:]
            previous.end = match.end()
        else:
            result.append(_Line(match.start(), match.end(), payload))
        if len(result[-1].payload) > limits.max_line_bytes:
            raise _BoundExceededError(
                "Calendar line exceeds the inspection limit; original bytes retained."
            )
    return result


def _partition_property(text: str) -> tuple[str, str]:
    # Quotes are syntax only in parameters, not in the property's free text.
    quoted = False
    for index, character in enumerate(text):
        if character == '"':
            quoted = not quoted
        elif character == ":" and not quoted:
            return text[:index], text[index + 1 :]
    raise ValueError("Missing property delimiter")


def _property(line: _Line, data: bytes) -> CalendarProperty:
    text = line.payload.decode("utf-8")
    header, value = _partition_property(text)
    fields = _split_quoted(header, ";")
    name = fields[0].upper()
    if not _NAME.fullmatch(name):
        raise ValueError("Unsupported property name")
    parameters: list[CalendarParameter] = []
    for field_text in fields[1:]:
        key, separator, contents = field_text.partition("=")
        if not separator or not _NAME.fullmatch(key):
            raise ValueError("Unsupported property parameter")
        values = tuple(
            part.removeprefix('"').removesuffix('"')
            for part in _split_quoted(contents, ",")
        )
        parameters.append(CalendarParameter(key.upper(), values))
    return CalendarProperty(
        name,
        tuple(parameters),
        value,
        data[line.start : line.end],
        line.start,
        line.end,
    )


def parse_calendar(
    data: bytes, *, limits: CalendarLimits = _DEFAULT_LIMITS
) -> CalendarDocument:
    """Inspect bounded bytes, returning an opaque retained document on bad framing.

    Optional malformed dates project as INVALID values. A legacy or unknown file
    remains importable/preservable even when the supported writer is unavailable.
    """
    if (
        min(
            limits.max_bytes,
            limits.max_lines,
            limits.max_line_bytes,
            limits.max_components,
            limits.max_depth,
        )
        < 1
    ):
        raise ValueError("Calendar limits must be positive")
    data = bytes(data)
    if len(data) > limits.max_bytes:
        return CalendarDocument(
            data,
            (),
            (),
            None,
            False,
            ("Calendar exceeds the inspection size limit; original bytes retained.",),
        )
    try:
        lines = _lines(data, limits)
    except _BoundExceededError as error:
        return CalendarDocument(data, (), (), None, False, (str(error),))
    roots: list[CalendarComponent] = []
    stack: list[_Node] = []
    issues: list[str] = []
    count = 0
    for line in lines:
        if line.start == 0 and line.payload.startswith(b"\xef\xbb\xbf"):
            line.payload = line.payload[3:]
        if not line.payload:
            continue
        try:
            prop = _property(line, data)
        except (UnicodeError, ValueError):
            issues.append(
                "Unsupported Calendar line or encoding; original bytes retained."
            )
            continue
        if prop.name == "BEGIN":
            count += 1
            if len(stack) >= limits.max_depth or count > limits.max_components:
                return CalendarDocument(
                    data,
                    (),
                    (),
                    None,
                    False,
                    ("Calendar component limit exceeded; original bytes retained.",),
                )
            if prop.parameters or not _NAME.fullmatch(prop.value):
                issues.append("Unsupported component framing.")
            stack.append(_Node(prop.value.upper(), line.start))
        elif prop.name == "END":
            if not stack or stack[-1].name != prop.value.upper() or prop.parameters:
                issues.append("Unmatched Calendar component ending.")
                continue
            node = stack.pop()
            component = CalendarComponent(
                node.name,
                tuple(node.properties),
                tuple(node.children),
                data[node.start : line.end],
                node.start,
                line.end,
                line.start,
            )
            if stack:
                stack[-1].children.append(component)
            else:
                roots.append(component)
        elif stack:
            stack[-1].properties.append(prop)
        else:
            issues.append("Calendar contains data outside a component.")
    if stack:
        issues.append("Unclosed Calendar component; original bytes retained.")
    calendars = [component for component in roots if component.name == "VCALENDAR"]
    versions = [
        prop.value
        for component in calendars
        for prop in component.properties
        if prop.name == "VERSION"
    ]
    version = versions[0] if len(versions) == 1 else None
    editable = not issues and len(roots) == len(calendars) == 1 and version == "2.0"
    if not calendars:
        issues.append("No complete Calendar component was found.")
    elif version != "2.0":
        issues.append("This Calendar version is retained without field editing.")
    entries: list[CalendarEntry] = []
    for calendar in calendars:
        for component in calendar.children:
            if component.name in (CalendarEntryKind.EVENT, CalendarEntryKind.TODO):
                entries.append(_entry(len(entries), component, editable))
    return CalendarDocument(
        data,
        tuple(roots),
        tuple(entries),
        version,
        editable,
        tuple(dict.fromkeys(issues)),
    )


def _unescape(value: str) -> str:
    return re.sub(
        r"\\([nN,;\\])", lambda match: "\n" if match[1] in "nN" else match[1], value
    )


def _date(prop: CalendarProperty | None) -> CalendarDateTime | None:
    if prop is None:
        return None
    value = prop.value
    zone_values = prop.parameter_values("TZID")
    type_values = prop.parameter_values("VALUE")
    tzid = zone_values[0] if len(zone_values) == 1 else None
    try:
        if len(zone_values) > 1 or len(type_values) > 1 or (zone_values and not tzid):
            raise ValueError("Ambiguous date parameters")
        type_name = type_values[0].upper() if type_values else None
        if _DATE.fullmatch(value) and type_name in (None, "DATE") and not zone_values:
            return CalendarDateTime(
                CalendarDateForm.DATE,
                Date(int(value[:4]), int(value[4:6]), int(value[6:8])),
                value,
            )
        if (
            not _DATETIME.fullmatch(value)
            or type_name not in (None, "DATE-TIME")
            or (tzid and value.endswith("Z"))
        ):
            raise ValueError("Unsupported Calendar date form")
        local = PlainDateTime(
            int(value[:4]),
            int(value[4:6]),
            int(value[6:8]),
            int(value[9:11]),
            int(value[11:13]),
            int(value[13:15]),
        )
        if value.endswith("Z"):
            return CalendarDateTime(CalendarDateForm.UTC, local.assume_utc(), value)
        return CalendarDateTime(
            CalendarDateForm.ZONED if tzid else CalendarDateForm.FLOATING,
            local,
            value,
            tzid,
        )
    except (ValueError, OverflowError):
        return CalendarDateTime(
            CalendarDateForm.INVALID,
            None,
            value,
            tzid,
            "Date could not be interpreted; original value retained.",
        )


def _entry(index: int, component: CalendarComponent, editable: bool) -> CalendarEntry:
    properties = {prop.name: prop for prop in reversed(component.properties)}
    counts = Counter(prop.name for prop in component.properties)
    issues: list[str] = []
    if any(counts[name] > 1 for name in _SINGULAR):
        editable = False
        issues.append("Repeated entry fields are retained without field editing.")
    if any(
        prop.parameter_values("ENCODING") or prop.parameter_values("CHARSET")
        for prop in component.properties
    ):
        editable = False
        issues.append("Legacy property encoding is retained without field editing.")
    dates = tuple(
        _date(properties.get(name)) for name in ("DTSTART", "DTEND", "DUE", "COMPLETED")
    )
    for name, date_value in zip(
        ("DTSTART", "DTEND", "DUE", "COMPLETED"), dates, strict=True
    ):
        if date_value and date_value.issue:
            issues.append(f"{name}: {date_value.issue}")
    recurring = bool(_RECURRENCE.intersection(properties))
    timing_editable = (
        editable
        and not recurring
        and "DURATION" not in properties
        and not component.children
        and not any(value and value.tzid for value in dates)
        and not any(
            parameter.name not in ("VALUE", "TZID")
            for prop in component.properties
            if prop.name in ("DTSTART", "DTEND", "DUE")
            for parameter in prop.parameters
        )
    )
    status = properties.get("STATUS")

    def text(name: str) -> str:
        return _unescape(properties[name].value) if name in properties else ""

    return CalendarEntry(
        index,
        CalendarEntryKind(component.name),
        text("UID") or None,
        text("SUMMARY"),
        text("DESCRIPTION"),
        text("LOCATION"),
        dates[0],
        dates[1],
        dates[2],
        dates[3],
        bool(status and status.value.upper() == "COMPLETED")
        or (status is None and "COMPLETED" in properties),
        editable,
        timing_editable,
        recurring,
        tuple(issues),
        component,
        _recurrence(component),
        _reminders(component),
    )


def serialize_calendar(document: CalendarDocument) -> bytes:
    return document.raw_bytes


def _escape(value: str) -> str:
    if "\x00" in value:
        raise CalendarEditError("Calendar text cannot contain NUL.")
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _fold(value: str, newline: bytes = b"\r\n") -> bytes:
    """Fold at 75 octets without splitting a UTF-8 character."""
    chunks: list[bytes] = []
    current = bytearray()
    for character in value:
        encoded = character.encode("utf-8")
        if len(current) + len(encoded) > 75:
            chunks.append(bytes(current))
            current = bytearray(b" ")
        current.extend(encoded)
    chunks.append(bytes(current))
    return newline.join(chunks) + newline


def _date_line(name: str, value: object, newline: bytes) -> bytes:
    if isinstance(value, Date):
        return _fold(f"{name};VALUE=DATE:{value.format_iso(basic=True)}", newline)
    if isinstance(value, (PlainDateTime, Instant)):
        return _fold(f"{name}:{value.format_iso(basic=True, unit='second')}", newline)
    raise CalendarEditError("Use a date, floating local time, or UTC instant.")


def _validate_pair(start: CalendarValue | None, end: CalendarValue | None) -> None:
    if start is None or end is None:
        return
    if type(start) is not type(end):
        raise CalendarEditError("Start and end must use the same date form.")
    # RFC 5545 requires authored DTEND/DUE to be strictly later than DTSTART.
    # Imported ranges are inspected without this validation until timing is edited.
    # Whenever prohibits mixing date forms; compare only an explicitly matched pair.
    if isinstance(start, Date) and isinstance(end, Date) and end <= start:
        raise CalendarEditError("End or due date must be later than start.")
    if (
        isinstance(start, PlainDateTime)
        and isinstance(end, PlainDateTime)
        and end <= start
    ):
        raise CalendarEditError("End or due date must be later than start.")
    if isinstance(start, Instant) and isinstance(end, Instant) and end <= start:
        raise CalendarEditError("End or due date must be later than start.")


def _draft_bytes(
    draft: CalendarEntryDraft,
    *,
    stamp: Instant,
    newline: bytes,
    profile: CalendarProfile = CalendarProfile.UNKNOWN,
) -> bytes:
    if draft.kind is CalendarEntryKind.EVENT:
        if draft.start is None:
            raise CalendarEditError("An event needs a start date.")
        if draft.due is not None or draft.completed or draft.completed_at is not None:
            raise CalendarEditError("Due dates and completion belong to To Dos.")
        _validate_pair(draft.start, draft.end)
    elif draft.end is not None:
        raise CalendarEditError("Use a due date for a To Do.")
    elif draft.completed_at is not None and not draft.completed:
        raise CalendarEditError("A completion date requires a completed To Do.")
    if draft.kind is CalendarEntryKind.TODO:
        _validate_pair(draft.start, draft.due)
    uid = draft.uid or f"{uuid4()}@iopenpod"
    rows = [
        _fold(f"BEGIN:{draft.kind.value}", newline),
        _fold(f"UID:{_escape(uid)}", newline),
        _date_line("DTSTAMP", stamp, newline),
    ]
    for name, text in (
        ("SUMMARY", draft.summary),
        ("DESCRIPTION", draft.description),
        ("LOCATION", draft.location),
    ):
        if text:
            rows.append(_fold(f"{name}:{_escape(text)}", newline))
    for name, value in (
        ("DTSTART", draft.start),
        ("DTEND", draft.end),
        ("DUE", draft.due),
    ):
        if value is not None:
            rows.append(_date_line(name, value, newline))
    if draft.kind is CalendarEntryKind.TODO and draft.completed:
        rows.append(_fold("STATUS:COMPLETED", newline))
        rows.append(_date_line("COMPLETED", draft.completed_at or stamp, newline))
    if draft.recurrence is not None:
        if draft.kind is not CalendarEntryKind.EVENT:
            raise CalendarEditError("Qualified recurrence belongs to events.")
        validate_recurrence(draft.recurrence, profile, draft.start, draft.end)
        rows.append(_recurrence_bytes(draft.recurrence, newline))
    if draft.reminder is not None:
        if draft.kind is not CalendarEntryKind.EVENT or not isinstance(
            draft.start, PlainDateTime
        ):
            raise CalendarEditError(
                "Qualified Calendar Reminders require a floating event start."
            )
        rows.append(
            _reminder_bytes(
                draft.reminder, profile, newline, has_end=draft.end is not None
            )
        )
    rows.append(_fold(f"END:{draft.kind.value}", newline))
    return b"".join(rows)


def create_calendar(
    entries: Sequence[CalendarEntryDraft] = (),
    *,
    stamp: Instant | None = None,
    name: str | None = None,
    profile: CalendarProfile = CalendarProfile.UNKNOWN,
) -> CalendarDocument:
    """Author iCalendar 2.0; stamp is an explicit UTC metadata clock, never a zone.

    Supplying stamp makes authoring deterministic. Its default is used only for
    new DTSTAMP/COMPLETED metadata, never when interpreting retained event times.
    """
    current = stamp or Instant.now()
    body = b"".join(
        _draft_bytes(entry, stamp=current, newline=b"\r\n", profile=profile)
        for entry in entries
    )
    return _authored(
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//iOpenPod//Calendar//EN\r\n"
        + (
            _fold("X-WR-CALNAME:" + _escape(_calendar_name(name)))
            if name is not None
            else b""
        )
        + body
        + b"END:VCALENDAR\r\n"
    )


def _authored(data: bytes) -> CalendarDocument:
    document = parse_calendar(data)
    if not document.editable:
        raise CalendarEditError(
            "The edited Calendar exceeds the supported format or size limits."
        )
    return document


def _calendar(document: CalendarDocument) -> CalendarComponent:
    if not document.editable:
        raise CalendarEditError(
            "This Calendar can be preserved or imported, but its format cannot be edited."
        )
    return document.components[0]


def _newline(document: CalendarDocument) -> bytes:
    return b"\r\n" if b"\r\n" in document.raw_bytes else b"\n"


def add_entry(
    document: CalendarDocument,
    draft: CalendarEntryDraft,
    *,
    stamp: Instant | None = None,
    profile: CalendarProfile = CalendarProfile.UNKNOWN,
) -> CalendarDocument:
    calendar = _calendar(document)
    content = _draft_bytes(
        draft, stamp=stamp or Instant.now(), newline=_newline(document), profile=profile
    )
    offset = calendar.end_line_start
    return _authored(
        document.raw_bytes[:offset] + content + document.raw_bytes[offset:]
    )


def _find_entry(document: CalendarDocument, entry_id: int) -> CalendarEntry:
    for entry in document.entries:
        if entry.entry_id == entry_id:
            return entry
    raise CalendarEditError("The Calendar entry is no longer present.")


def remove_entry(document: CalendarDocument, entry_id: int) -> CalendarDocument:
    _calendar(document)
    component = _find_entry(document, entry_id).component
    return _authored(
        document.raw_bytes[: component.start_offset]
        + document.raw_bytes[component.end_offset :]
    )


def update_entry(
    document: CalendarDocument,
    entry_id: int,
    changes: CalendarEntryChanges,
    *,
    stamp: Instant | None = None,
    profile: CalendarProfile = CalendarProfile.UNKNOWN,
) -> CalendarDocument:
    _calendar(document)
    entry = _find_entry(document, entry_id)
    if not entry.editable:
        raise CalendarEditError(
            "This entry's field encoding or repeated properties cannot be edited safely."
        )
    temporal = (
        ("DTSTART", changes.start),
        ("DTEND", changes.end),
        ("DUE", changes.due),
    )
    timing_changed = any(not isinstance(value, Unchanged) for _, value in temporal)
    if timing_changed and not entry.timing_editable:
        raise CalendarEditError(
            "Timing for this recurring, zoned, or alarm-bearing entry is preserved. Edit its text or create a separate entry."
        )
    if entry.kind is CalendarEntryKind.EVENT and (
        changes.due is not UNCHANGED
        or changes.completed is not None
        or changes.completed_at is not UNCHANGED
    ):
        raise CalendarEditError("Due dates and completion belong to To Dos.")
    if entry.kind is CalendarEntryKind.TODO and changes.end is not UNCHANGED:
        raise CalendarEditError("Use a due date for a To Do.")
    if changes.completed is False and isinstance(changes.completed_at, Instant):
        raise CalendarEditError("A completion date conflicts with an incomplete To Do.")
    if timing_changed:
        start = entry.start.value if entry.start else None
        end = entry.end.value if entry.end else None
        if not isinstance(changes.start, Unchanged):
            start = changes.start
        if not isinstance(changes.end, Unchanged):
            end = changes.end
        if entry.kind is CalendarEntryKind.EVENT:
            if start is None:
                raise CalendarEditError(
                    "An event needs a valid start date when its timing is changed."
                )
            _validate_pair(start, end)
        else:
            due = entry.due.value if entry.due else None
            if not isinstance(changes.due, Unchanged):
                due = changes.due
            _validate_pair(start, due)
    newline = _newline(document)
    replacements: dict[str, bytes] = {}
    for name, text, previous in (
        ("SUMMARY", changes.summary, entry.summary),
        ("DESCRIPTION", changes.description, entry.description),
        ("LOCATION", changes.location, entry.location),
    ):
        if text is not None and text != previous:
            replacements[name] = (
                _fold(f"{name}:{_escape(text)}", newline) if text else b""
            )
    for name, value in (*temporal, ("COMPLETED", changes.completed_at)):
        if not isinstance(value, Unchanged):
            replacements[name] = (
                _date_line(name, value, newline) if value is not None else b""
            )
    if changes.completed is not None:
        replacements["STATUS"] = _fold(
            "STATUS:COMPLETED" if changes.completed else "STATUS:NEEDS-ACTION", newline
        )
        if not changes.completed:
            replacements["COMPLETED"] = b""
        elif changes.completed_at is UNCHANGED and not entry.completed:
            replacements["COMPLETED"] = _date_line(
                "COMPLETED", stamp or Instant.now(), newline
            )
    elif isinstance(changes.completed_at, Instant):
        replacements["STATUS"] = _fold("STATUS:COMPLETED", newline)
    if changes.completed is not None or isinstance(changes.completed_at, Instant):
        # RFC 5545 completion consistency, not a claim about firmware handling.
        # Reopening does not imply zero progress; omit the optional percentage.
        # Unrelated edits retain its original bytes, including unknown parameters.
        for prop in entry.component.properties:
            if prop.name == "PERCENT-COMPLETE":
                if changes.completed is False:
                    replacements[prop.name] = b""
                else:
                    header, _ = _partition_property(
                        _lines(prop.raw_bytes, _DEFAULT_LIMITS)[0].payload.decode(
                            "utf-8"
                        )
                    )
                    replacements[prop.name] = _fold(f"{header}:100", newline)
    new_reminder = b""
    extra_patches: list[tuple[int, int, bytes]] = []
    if changes.recurrence is not UNCHANGED:
        if any(
            prop.name in {"DURATION", "EXRULE", "EXDATE", "RDATE", "RECURRENCE-ID"}
            or (prop.name in {"DTSTART", "DTEND"} and prop.parameters)
            for prop in entry.component.properties
        ):
            raise CalendarEditError(
                "Unsupported source recurrence or timing is preserved without editing."
            )
        if entry.kind is not CalendarEntryKind.EVENT:
            raise CalendarEditError("Qualified recurrence belongs to events.")
        if entry.has_recurrence and recurrence_rule(entry, profile) is None:
            raise CalendarEditError("This recurrence is preserved without editing.")
        if changes.recurrence is None:
            if not entry.has_recurrence:
                pass
            else:
                replacements["RRULE"] = b""
        else:
            assert isinstance(changes.recurrence, CalendarRecurrenceRule)
            start = entry.start.value if entry.start else None
            end = entry.end.value if entry.end else None
            if not isinstance(changes.start, Unchanged):
                start = changes.start
            if not isinstance(changes.end, Unchanged):
                end = changes.end
            validate_recurrence(changes.recurrence, profile, start, end)
            replacements["RRULE"] = _recurrence_bytes(changes.recurrence, newline)
    if changes.reminder is not UNCHANGED:
        effective_start = entry.start.value if entry.start else None
        if not isinstance(changes.start, Unchanged):
            effective_start = changes.start
        if not isinstance(effective_start, PlainDateTime):
            raise CalendarEditError(
                "Qualified Calendar Reminders require a floating event start."
            )
        if (
            not supports_reminders(profile)
            or entry.kind is not CalendarEntryKind.EVENT
            or entry.start is None
            or entry.start.form is not CalendarDateForm.FLOATING
        ):
            raise CalendarEditError(
                "Calendar Reminder edits are not qualified for this target or event."
            )
        if entry.reminders and editable_reminder(entry, profile) is None:
            raise CalendarEditError(
                "This imported reminder is preserved without editing."
            )
        content = (
            b""
            if changes.reminder is None
            else _reminder_bytes(
                changes.reminder,
                profile,
                newline,
                has_end=entry.end is not None and entry.end.value is not None,
            )
        )
        if entry.reminders:
            component = entry.reminders[0].component
            if changes.reminder is None:
                extra_patches.append(
                    (component.start_offset, component.end_offset, b"")
                )
            else:
                assert isinstance(changes.reminder, CalendarReminderDraft)
                trigger = next(
                    prop for prop in component.properties if prop.name == "TRIGGER"
                )
                extra_patches.append(
                    (
                        trigger.start_offset,
                        trigger.end_offset,
                        _fold(
                            f"TRIGGER:-PT{changes.reminder.minutes_before}M", newline
                        ),
                    )
                )
        elif content:
            new_reminder = content
    if not replacements and not extra_patches and not new_reminder:
        return document
    # Retain unknown parameters such as LANGUAGE/ALTREP when changing text.
    text_changes = {
        "SUMMARY": changes.summary,
        "DESCRIPTION": changes.description,
        "LOCATION": changes.location,
    }
    for prop in entry.component.properties:
        text = text_changes.get(prop.name)
        if prop.name in replacements and text is not None and text:
            header, _ = _partition_property(
                _lines(prop.raw_bytes, _DEFAULT_LIMITS)[0].payload.decode("utf-8")
            )
            replacements[prop.name] = _fold(f"{header}:{_escape(text)}", newline)
    patches = extra_patches + [
        (prop.start_offset, prop.end_offset, replacements.pop(prop.name))
        for prop in entry.component.properties
        if prop.name in replacements
    ]
    if replacements or new_reminder:
        patches.append(
            (
                entry.component.end_line_start,
                entry.component.end_line_start,
                b"".join(replacements.values()) + new_reminder,
            )
        )
    data = document.raw_bytes
    for start_offset, end_offset, replacement in sorted(patches, reverse=True):
        data = data[:start_offset] + replacement + data[end_offset:]
    return _authored(data)


def _calendar_name(name: str) -> str:
    if not name.strip() or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise CalendarEditError("Enter a calendar name without control characters.")
    if len(name.encode("utf-8")) > 1024:
        raise CalendarEditError("The calendar name is too long.")
    return name


def rename_calendar(document: CalendarDocument, name: str) -> CalendarDocument:
    """Replace only the calendar name, preserving every event and unknown byte."""
    calendar = _calendar(document)
    value = _calendar_name(name)
    names = [prop for prop in calendar.properties if prop.name == "X-WR-CALNAME"]
    if len(names) > 1 or any(prop.parameters for prop in names):
        raise CalendarEditError("This calendar has ambiguous name metadata.")
    if names and calendar.calendar_name == value:
        return document
    content = _fold("X-WR-CALNAME:" + _escape(value), _newline(document))
    if names:
        start, end = names[0].start_offset, names[0].end_offset
    else:
        # The native parser selects a calendar before attaching its first event.
        version = next(prop for prop in calendar.properties if prop.name == "VERSION")
        start = end = version.end_offset
    return _authored(document.raw_bytes[:start] + content + document.raw_bytes[end:])


def _recurrence(component: CalendarComponent) -> CalendarRecurrence | None:
    rules = [prop for prop in component.properties if prop.name == "RRULE"]
    if not rules:
        return None
    raw = rules[0].value
    if len(rules) != 1 or rules[0].parameters:
        return CalendarRecurrence(
            None,
            None,
            None,
            None,
            raw,
            ("Ambiguous recurrence is preserved without expansion.",),
        )
    fields: dict[str, str] = {}
    for part in raw.split(";"):
        key, separator, value = part.partition("=")
        key = key.upper()
        if not separator or key in fields or not value:
            return CalendarRecurrence(
                None,
                None,
                None,
                None,
                raw,
                ("Malformed recurrence is preserved without expansion.",),
            )
        fields[key] = value

    def positive(key: str, default: int | None) -> int | None:
        value = fields.get(key)
        if value is None:
            return default
        return (
            int(value)
            if re.fullmatch(r"[0-9]{1,9}", value) and int(value) > 0
            else None
        )

    return CalendarRecurrence(
        fields.get("FREQ", "").upper() or None,
        positive("INTERVAL", 1),
        positive("COUNT", None),
        fields.get("UNTIL"),
        raw,
    )


def _reminders(component: CalendarComponent) -> tuple[CalendarReminder, ...]:
    result: list[CalendarReminder] = []
    for child in component.children:
        if child.name != "VALARM":
            continue
        triggers = [prop for prop in child.properties if prop.name == "TRIGGER"]
        actions = [prop.value for prop in child.properties if prop.name == "ACTION"]
        action = actions[0] if len(actions) == 1 else None
        if len(triggers) != 1:
            result.append(
                CalendarReminder(
                    child,
                    action=action,
                    issues=(
                        "Reminder trigger is absent or ambiguous; original bytes retained.",
                    ),
                )
            )
            continue
        trigger = triggers[0]
        related = trigger.parameter_values("RELATED")
        value_type = trigger.parameter_values("VALUE")
        if (
            related not in ((), ("START",), ("END",))
            or value_type not in ((), ("DURATION",), ("DATE-TIME",))
            or any(
                param.name not in ("RELATED", "VALUE") for param in trigger.parameters
            )
        ):
            result.append(
                CalendarReminder(
                    child,
                    action=action,
                    issues=(
                        "Unsupported reminder parameters; original bytes retained.",
                    ),
                )
            )
            continue
        if value_type == ("DATE-TIME",):
            result.append(
                CalendarReminder(child, absolute_trigger=_date(trigger), action=action)
            )
            continue
        match = re.fullmatch(
            r"(-?)P(?:(\d{1,6})D)?(?:T(?:(\d{1,6})H)?(?:(\d{1,6})M)?(?:(\d{1,6})S)?)?",
            trigger.value,
        )
        if match is None or not any(match[index] is not None for index in range(2, 6)):
            result.append(
                CalendarReminder(
                    child,
                    action=action,
                    issues=("Unsupported reminder duration; original bytes retained.",),
                )
            )
            continue
        seconds = sum(
            int(match[index] or 0) * scale
            for index, scale in ((2, 86400), (3, 3600), (4, 60), (5, 1))
        )
        if match[1]:
            seconds = -seconds
        if not -(1 << 31) <= seconds < (1 << 31):
            result.append(
                CalendarReminder(
                    child,
                    action=action,
                    issues=(
                        "Reminder duration exceeds the qualified native integer range; original bytes retained.",
                    ),
                )
            )
            continue
        result.append(
            CalendarReminder(
                child,
                relative_seconds=seconds,
                related_to_end=related == ("END",),
                action=action,
            )
        )
    return tuple(result)


def _recurrence_bytes(rule: CalendarRecurrenceRule, newline: bytes) -> bytes:
    value = f"RRULE:FREQ={rule.frequency.value};INTERVAL={rule.interval}"
    if rule.count is not None:
        value += f";COUNT={rule.count}"
    if rule.until is not None:
        value += ";UNTIL=" + rule.until.format_iso(basic=True)
    return _fold(value, newline)


def _reminder_bytes(
    reminder: CalendarReminderDraft,
    profile: CalendarProfile,
    newline: bytes,
    *,
    has_end: bool,
) -> bytes:
    validate_reminder(reminder, profile, has_end=has_end)
    return (
        _fold("BEGIN:VALARM", newline)
        + _fold(f"TRIGGER:-PT{reminder.minutes_before}M", newline)
        + _fold("END:VALARM", newline)
    )
