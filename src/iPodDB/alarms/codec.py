"""Bounded, lossless Classic Alarm token reader and existing-field patcher.

The consumer qualifies connected identity/firmware separately. No path is
opened here. Primary byte evidence: classic-alarm-persistence-2026-11-06.md in
the firmware lab, linked by docs/research/calendar-alarm-firmware-2026-11-06.md.
Whole-file validity and exact source extents are checked again before editing;
unknown fields and containers never need to be reserialized.
"""

import struct
from dataclasses import dataclass, replace

from whenever import PlainDateTime, Time

from iPodDB.alarms.models import (
    ALARM_EPOCH,
    AlarmDocument,
    AlarmRecord,
    PreferencesAlarmDocument,
)
from iPodDB.preferences.definitions import (
    PREFERENCES_ALARM_OFFSET,
    PreferencesProfile,
    matches_preferences_profile,
)
from iPodDB.shared.errors import iPodDBWriteError

MAX_ALARM_BYTES = 16 * 1024 * 1024
_SCALARS = (
    (6, "scheduled_seconds"),
    (7, "control_word"),
    (0x3B, "repeat_mode"),
    (0x1F, "selection"),
    (8, "sound_selector"),
)
_KNOWN_IDS = frozenset(token for token, _ in _SCALARS) | {0x3C}
_PREFERENCES_PROFILES = {
    "mini": PreferencesProfile.MINI_2_1_4_1,
    "video": PreferencesProfile.VIDEO_1_3,
}


@dataclass(frozen=True, slots=True)
class _Field:
    token: int
    offset: int
    length: int


@dataclass(frozen=True, slots=True)
class _Record:
    start: int
    end: int
    fields: tuple[_Field, ...]


def _source(data: object) -> bytes:
    if not isinstance(data, bytes | bytearray):
        raise TypeError("Alarm input must be bytes or bytearray.")
    return bytes(data)


def _u32(source: bytes, offset: int) -> int:
    return int.from_bytes(source[offset : offset + 4], "little")


def _scan(source: bytes) -> tuple[_Record, ...]:
    """Validate complete nested framing, including unknown bounded containers."""
    if not source or len(source) > MAX_ALARM_BYTES:
        raise ValueError("Alarm data is empty or exceeds the interpretation limit.")
    cursor = 0
    stack: list[tuple[int, int]] = []
    records: list[_Record] = []
    fields: list[_Field] = []
    root_closed = False
    while cursor < len(source):
        start = cursor
        if root_closed or cursor + 4 > len(source):
            raise ValueError("Alarm data has trailing or truncated token bytes.")
        word = _u32(source, cursor)
        cursor += 4
        token, kind = word & 0xFFFFFF, word >> 24
        if kind == 0x40:
            if not stack and (start != 0 or token != 0x3A):
                raise ValueError("Alarm data has no recognized outer container.")
            if len(stack) >= 64:
                raise ValueError(
                    "Alarm container nesting exceeds the interpretation limit."
                )
            if len(stack) == 1 and token == 5:
                fields = []
            stack.append((token, start))
        elif kind == 0xC0:
            if not stack or stack[-1][0] != token:
                raise ValueError("Alarm container closing token does not match.")
            _, opening = stack.pop()
            if len(stack) == 1 and token == 5:
                records.append(_Record(opening, cursor, tuple(fields)))
            if not stack:
                root_closed = True
        elif kind == 0:
            if not stack or cursor + 4 > len(source):
                raise ValueError("Alarm field is outside a container or truncated.")
            length = _u32(source, cursor)
            cursor += 4
            end = cursor + length
            if end + 4 > len(source) or _u32(source, end) != 0x80000000 | token:
                raise ValueError("Alarm field length or closing token is invalid.")
            if len(stack) == 2 and stack[-1][0] == 5:
                fields.append(_Field(token, cursor, length))
            cursor = end + 4
        else:
            raise ValueError("Alarm data has an unsupported token framing.")
    if stack or not root_closed:
        raise ValueError("Alarm data has an incomplete container.")
    return tuple(records)


def _unique(fields: tuple[_Field, ...], token: int) -> _Field | None:
    matches = [field for field in fields if field.token == token]
    return matches[0] if len(matches) == 1 else None


def _scalar(source: bytes, fields: tuple[_Field, ...], token: int) -> int | None:
    field = _unique(fields, token)
    return (
        _u32(source, field.offset) if field is not None and field.length == 4 else None
    )


def parse_alarms(data: bytes | bytearray) -> AlarmDocument:
    """Retain arbitrary bytes; unknown/invalid structure yields an opaque document.

    Exact token framing permits field-local interpretation. Repeated known tags
    are ambiguous and observation-only; no last-value guess authorizes a write.
    """
    source = _source(data)
    try:
        native_records = _scan(source)
    except ValueError as error:
        return AlarmDocument(source, issues=(str(error),))
    records: list[AlarmRecord] = []
    issues: list[str] = []
    for index, native in enumerate(native_records):
        values = {
            name: _scalar(source, native.fields, token) for token, name in _SCALARS
        }
        duplicate = any(
            sum(field.token == token for field in native.fields) > 1
            for token in _KNOWN_IDS
        )
        if duplicate:
            issues.append(
                f"Alarm {index + 1} has repeated known fields; its fields are read-only."
            )
        label = None
        text = _unique(native.fields, 0x3C)
        if text is not None:
            raw = source[text.offset : text.offset + text.length]
            if raw.endswith(b"\0") and b"\0" not in raw[:-1]:
                try:
                    label = raw[:-1].decode("utf-8")
                except UnicodeDecodeError:
                    issues.append(
                        f"Alarm {index + 1} has an undecodable retained string."
                    )
        records.append(
            AlarmRecord(
                index,
                native.start,
                native.end,
                values["scheduled_seconds"],
                values["repeat_mode"],
                values["control_word"],
                values["selection"],
                values["sound_selector"],
                label,
                not duplicate and values["scheduled_seconds"] is not None,
                not duplicate and values["repeat_mode"] is not None,
            )
        )
    return AlarmDocument(source, tuple(records), tuple(issues))


def write_alarms(document: AlarmDocument) -> bytes:
    """Patch existing date/repeat payloads; unchanged opaque bytes round-trip.

    Record insertion/removal and edits to unqualified fields are rejected.
    Reparse retained source rather than trusting public offset/editable values.
    Unknown native repeat codes survive unrelated date edits unchanged.
    """
    if type(document.source_bytes) is not bytes:
        raise iPodDBWriteError("Alarm source bytes must be immutable.")
    original = parse_alarms(document.source_bytes)
    if document.issues != original.issues or len(document.records) != len(
        original.records
    ):
        raise iPodDBWriteError("Alarm record structure must match its captured source.")
    if document == original:
        return document.source_bytes
    native = _scan(document.source_bytes)
    output = bytearray(document.source_bytes)
    for before, after, record in zip(
        original.records, document.records, native, strict=True
    ):
        if (
            replace(
                after,
                scheduled_seconds=before.scheduled_seconds,
                repeat_mode=before.repeat_mode,
            )
            != before
        ):
            raise iPodDBWriteError(
                "Only existing alarm date and repeat fields are editable."
            )
        for name, token, allowed in (
            ("scheduled_seconds", 6, before.can_edit_date),
            ("repeat_mode", 0x3B, before.can_edit_repeat),
        ):
            value = getattr(after, name)
            if value == getattr(before, name):
                continue
            maximum = 0xFFFFFFFE if token == 6 else 6
            if not allowed or type(value) is not int or not 0 <= value <= maximum:
                raise iPodDBWriteError(
                    "The changed alarm field is not a qualified value.", field=name
                )
            field = _unique(record.fields, token)
            assert field is not None
            struct.pack_into("<I", output, field.offset, value)
    return bytes(output)


def _alarm_seconds(value: object) -> int:
    if not isinstance(value, PlainDateTime):
        raise TypeError("Alarm dates require a PlainDateTime calendar coordinate.")
    return (
        value.difference(ALARM_EPOCH, naive_arithmetic_ok=True).total("nanoseconds")
        // 1_000_000_000
    )


def update_alarm(
    document: AlarmDocument,
    index: int,
    *,
    scheduled: PlainDateTime | None = None,
    repeat_mode: int | None = None,
) -> AlarmDocument:
    """Edit an existing alarm in its civil coordinate, without timezone guessing.

    Whole native seconds floor subsecond input. Unrepresentable new dates are
    an edit validation issue, never a reason to reject captured dates or media.
    """
    if type(index) is not int or not 0 <= index < len(document.records):
        raise IndexError("Alarm index is outside the captured document.")
    record = document.records[index]
    word = record.scheduled_seconds
    if scheduled is not None:
        word = _alarm_seconds(scheduled)
    records = list(document.records)
    records[index] = replace(
        record,
        scheduled_seconds=word,
        repeat_mode=record.repeat_mode if repeat_mode is None else repeat_mode,
    )
    updated = replace(document, records=tuple(records))
    write_alarms(updated)
    return updated


def parse_preferences_alarm(
    data: bytes | bytearray, format: str
) -> PreferencesAlarmDocument:
    """Interpret only exact Mini2 1.4.1 or Video 1.3 framing, never identify a device."""
    source = _source(data)
    profile = _PREFERENCES_PROFILES.get(format)
    if profile is None or not matches_preferences_profile(source, profile):
        return PreferencesAlarmDocument(
            source, format, issues=("Preferences alarm framing is not qualified.",)
        )
    raw = int.from_bytes(
        source[PREFERENCES_ALARM_OFFSET : PREFERENCES_ALARM_OFFSET + 2], "little"
    )
    return PreferencesAlarmDocument(source, format, raw)


def _alarm_minutes(value: object) -> int:
    if not isinstance(value, Time):
        raise TypeError("Alarm time requires Whenever Time.")
    return value.hour * 60 + value.minute


def patch_preferences_alarm(document: PreferencesAlarmDocument, time: Time) -> bytes:
    """Patch minute-of-day only; preserve enable/sound fields and all high bits.

    The firmware field has minute precision. Seconds/subseconds are discarded
    explicitly, independently of any Host timezone or firmware date selection.
    """
    minutes = _alarm_minutes(time)
    original = parse_preferences_alarm(document.source_bytes, document.format)
    if document != original or original.raw_word is None:
        raise iPodDBWriteError(
            "An alarm edit requires unchanged, qualified Preferences evidence."
        )
    output = bytearray(original.source_bytes)
    value = (original.raw_word & 0xF000) | minutes
    struct.pack_into("<H", output, PREFERENCES_ALARM_OFFSET, value)
    return bytes(output)
