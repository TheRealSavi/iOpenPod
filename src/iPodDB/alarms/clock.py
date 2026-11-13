"""Lossless per-city Clock Alarm observations, time and sound edits.

Latest Nano 1 and Video firmware use a tagged ``Device/clock`` collection,
independent of the next-alarm projection in Preferences. See
docs/research/alarms-legacy-firmware-2026-11-13.md for native framing evidence.
This module performs no I/O and does not qualify connected device identity.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace

from whenever import Time

from iPodDB.alarms._inputs import capture_bytes
from iPodDB.alarms.cities import CLOCK_CITIES, ClockCity
from iPodDB.shared.errors import iPodDBWriteError

_MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ClockAlarmRecord:
    """One saved city and its alarm; identifiers are resource-local observations."""

    index: int
    source_offset: int
    source_end: int
    region: int | None
    city: int | None
    daylight_saving: int | None
    minutes: int | None
    kind: int | None
    selection: int | None
    sound_selector: int | None
    editable: bool

    @property
    def time(self) -> Time | None:
        if self.minutes is None or not 0 <= self.minutes < 1440:
            return None
        return Time(self.minutes // 60, self.minutes % 60)

    @property
    def enabled(self) -> bool | None:
        """Saved canonical kind only, not a prediction of the pending alarm."""
        if self.kind == 8:
            return False
        return True if self.kind in (0, 4, 12) else None

    @property
    def can_edit_enabled(self) -> bool:
        return self.editable and self.kind in (0, 4, 8, 12)

    @property
    def sound_mode(self) -> int | None:
        """Saved sound choice: 0 Beep, 4 Playlist, 12 accessory Radio."""
        return self.selection

    @property
    def can_edit_sound(self) -> bool:
        return self.editable


@dataclass(frozen=True, slots=True)
class ClockAlarmDocument:
    source_bytes: bytes
    records: tuple[ClockAlarmRecord, ...] = ()
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Node:
    tag: int
    start: int
    end: int
    payload: int | None
    children: tuple[_Node, ...] = ()


def _word(source: bytes, offset: int) -> int:
    return int.from_bytes(source[offset : offset + 4], "little")


def _node(source: bytes, start: int, depth: int) -> _Node:
    if depth >= 64 or start + 4 > len(source):
        raise ValueError("Clock data is truncated or exceeds the nesting limit.")
    word = _word(source, start)
    tag, kind = word & 0xFFFFFF, word >> 24
    if kind == 0:
        if start + 8 > len(source):
            raise ValueError("Clock field has a truncated length.")
        end = start + 8 + _word(source, start + 4)
        if end + 4 > len(source) or _word(source, end) != 0x80000000 | tag:
            raise ValueError("Clock field length or closing token is invalid.")
        return _Node(tag, start, end + 4, start + 8)
    if kind != 0x40:
        raise ValueError("Clock data has an unsupported token framing.")
    cursor = start + 4
    children: list[_Node] = []
    while cursor + 4 <= len(source):
        if _word(source, cursor) == 0xC0000000 | tag:
            return _Node(tag, start, cursor + 4, None, tuple(children))
        child = _node(source, cursor, depth + 1)
        children.append(child)
        cursor = child.end
    raise ValueError("Clock data has an incomplete container.")


def _root(source: bytes) -> _Node:
    if not source or len(source) > _MAX_BYTES:
        raise ValueError("Clock data is empty or exceeds the interpretation limit.")
    root = _node(source, 0, 0)
    if root.tag != 0 or root.payload is not None or root.end != len(source):
        raise ValueError("Clock data has no complete, recognized outer container.")
    return root


def _unique(node: _Node, tag: int) -> _Node | None:
    matches = [child for child in node.children if child.tag == tag]
    return matches[0] if len(matches) == 1 else None


def _scalar(source: bytes, node: _Node, tag: int, width: int = 4) -> int | None:
    field = _unique(node, tag)
    if field is None or field.payload is None or field.end - field.payload != width + 4:
        return None
    return int.from_bytes(source[field.payload : field.payload + width], "little")


def _cities(root: _Node) -> tuple[_Node, ...]:
    return tuple(child for child in root.children if child.tag == 1)


def parse_clock_alarms(data: bytes | bytearray) -> ClockAlarmDocument:
    """Observe complete tagged sources; preserve ambiguous or malformed bytes."""
    source = capture_bytes(data, label="Clock input")
    if not source:
        return ClockAlarmDocument(source)
    try:
        root = _root(source)
    except ValueError as error:
        return ClockAlarmDocument(source, issues=(str(error),))
    records: list[ClockAlarmRecord] = []
    issues: list[str] = []
    for index, city in enumerate(_cities(root)):
        alarm = _unique(city, 5)
        values = (
            tuple(_scalar(source, alarm, tag) for tag in (6, 7, 0x1F, 8))
            if alarm is not None and alarm.payload is None
            else (None, None, None, None)
        )
        region = _scalar(source, city, 2)
        city_id = _scalar(source, city, 3)
        daylight = _scalar(source, city, 0x14, 1)
        editable = all(
            value is not None for value in (region, city_id, daylight, *values)
        )
        if not editable:
            issues.append(
                f"Clock {index + 1} has missing, repeated or invalid known fields; "
                "its alarm is read-only."
            )
        records.append(
            ClockAlarmRecord(
                index,
                city.start,
                city.end,
                region,
                city_id,
                daylight,
                values[0],
                values[1],
                values[2],
                values[3],
                editable,
            )
        )
    return ClockAlarmDocument(source, tuple(records), tuple(issues))


def _enabled_kind(record: ClockAlarmRecord, enabled: bool) -> int:
    if not record.can_edit_enabled or record.sound_selector is None:
        raise iPodDBWriteError("Clock Alarm enabled state is read-only.")
    if record.enabled is enabled:
        assert record.kind is not None
        return record.kind
    if not enabled:
        return 8
    # Native on-toggle reads tag 8 as a signed i32 Playlist selection.
    return 4 if 0 < record.sound_selector <= 0x7FFFFFFF else 0


def write_clock_alarms(document: ClockAlarmDocument) -> bytes:
    """Patch qualified existing payloads; retain every unrelated source byte."""
    if type(document.source_bytes) is not bytes:
        raise iPodDBWriteError("Clock source bytes must be immutable.")
    original = parse_clock_alarms(document.source_bytes)
    if document == original:
        return document.source_bytes
    if document.issues != original.issues or len(document.records) != len(
        original.records
    ):
        raise iPodDBWriteError("Clock edits cannot change source interpretation.")
    output = bytearray(document.source_bytes)
    cities = _cities(_root(original.source_bytes))
    for before, after, city in zip(
        original.records, document.records, cities, strict=True
    ):
        if (
            replace(
                after,
                minutes=before.minutes,
                kind=before.kind,
                selection=before.selection,
                sound_selector=before.sound_selector,
                daylight_saving=before.daylight_saving,
            )
            != before
        ):
            raise iPodDBWriteError(
                "Only Clock Alarm time, daylight saving, enabled state and sound may change."
            )
        alarm = _unique(city, 5)
        if before.daylight_saving != after.daylight_saving:
            if (
                not before.editable
                or type(after.daylight_saving) is not int
                or after.daylight_saving not in (0, 1)
            ):
                raise iPodDBWriteError("Choose a valid Clock daylight-saving setting.")
            field = _unique(city, 0x14)
            if field is None or field.payload is None:
                raise iPodDBWriteError("Clock has no unique daylight-saving field.")
            output[field.payload] = after.daylight_saving
        if before.minutes != after.minutes:
            if (
                not before.editable
                or type(after.minutes) is not int
                or not 0 <= after.minutes < 1440
            ):
                raise iPodDBWriteError(
                    "Clock Alarm time is unqualified or out of range."
                )
            field = _unique(alarm, 6) if alarm is not None else None
            if field is None or field.payload is None:
                raise iPodDBWriteError("Clock Alarm has no unique minute field.")
            struct.pack_into("<I", output, field.payload, after.minutes)
        sound_changed = (before.selection, before.sound_selector) != (
            after.selection,
            after.sound_selector,
        )
        if sound_changed:
            if (
                not before.can_edit_sound
                or not _native_sound_choice(after)
                or after.kind not in (after.selection, 8)
            ):
                raise iPodDBWriteError("Clock Alarm sound is not a native selection.")
            for tag, value in ((0x1F, after.selection), (8, after.sound_selector)):
                field = _unique(alarm, tag) if alarm is not None else None
                if field is None or field.payload is None or value is None:
                    raise iPodDBWriteError("Clock Alarm has no unique sound field.")
                struct.pack_into("<I", output, field.payload, value)
        if before.kind != after.kind:
            if type(after.kind) is not int or after.kind not in (0, 4, 8, 12):
                raise iPodDBWriteError("Clock Alarm kind is not a native change.")
            if not sound_changed and not (
                # Selecting the retained sound again also enables it natively.
                (
                    before.can_edit_sound
                    and _native_sound_choice(after)
                    and after.kind == after.selection
                )
                or after.kind == _enabled_kind(before, after.kind != 8)
                or (
                    before.can_edit_enabled
                    and after.kind
                    == (
                        4
                        if before.sound_selector is not None
                        and 0 < before.sound_selector <= 0x7FFFFFFF
                        else 0
                    )
                )
            ):
                raise iPodDBWriteError(
                    "Clock Alarm kind is not a native enable change."
                )
            field = _unique(alarm, 7) if alarm is not None else None
            if field is None or field.payload is None:
                raise iPodDBWriteError("Clock Alarm has no unique kind field.")
            struct.pack_into("<I", output, field.payload, after.kind)
    return bytes(output)


def _native_sound_choice(record: ClockAlarmRecord) -> bool:
    return (
        type(record.selection) is int
        and type(record.sound_selector) is int
        and (
            (record.selection == 0 and record.sound_selector == 0xFFFFFFFF)
            or (record.selection == 4 and 0 < record.sound_selector <= 0x7FFFFFFF)
        )
    )


def _clock_minutes(value: object) -> int:
    if not isinstance(value, Time):
        raise TypeError("Clock Alarm time requires Whenever Time.")
    return value.hour * 60 + value.minute


def update_clock_alarm(
    document: ClockAlarmDocument,
    index: int,
    *,
    time: Time | None = None,
    enabled: bool | None = None,
    sound_playlist_index: int | None = None,
    daylight_saving: bool | None = None,
) -> ClockAlarmDocument:
    """Edit saved values; sound selection enables before explicit enable intent.

    Sound -1 selects Beep; positive indices identify the qualified native Playlist
    array. The application owns source-checked index qualification. None retains
    the saved sound. Accessory Radio remains an observation, not a new choice.
    """
    minutes = _clock_minutes(time) if time is not None else None
    if enabled is not None and type(enabled) is not bool:
        raise TypeError("Clock Alarm enabled state requires a boolean.")
    if daylight_saving is not None and type(daylight_saving) is not bool:
        raise TypeError("Clock daylight saving requires a boolean.")
    if type(index) is not int or not 0 <= index < len(document.records):
        raise IndexError("Clock Alarm index is out of range.")
    records = list(document.records)
    record = records[index]
    if not record.editable:
        raise iPodDBWriteError("Clock Alarm time is read-only.")
    if sound_playlist_index is not None:
        if type(sound_playlist_index) is not int or not (
            sound_playlist_index == -1 or 0 < sound_playlist_index <= 0x7FFFFFFF
        ):
            raise iPodDBWriteError("Choose Beep or a valid native Playlist index.")
        mode = 0 if sound_playlist_index == -1 else 4
        record = replace(
            record,
            kind=mode,
            selection=mode,
            sound_selector=sound_playlist_index & 0xFFFFFFFF,
        )
    records[index] = replace(
        record,
        minutes=record.minutes if minutes is None else minutes,
        kind=record.kind if enabled is None else _enabled_kind(record, enabled),
        daylight_saving=record.daylight_saving
        if daylight_saving is None
        else int(daylight_saving),
    )
    result = replace(document, records=tuple(records))
    write_clock_alarms(result)
    return result


def empty_clock_document() -> ClockAlarmDocument:
    """An empty native Clock collection, with no fabricated fallback city."""
    return parse_clock_alarms(struct.pack("<II", 0x40000000, 0xC0000000))


def _field(tag: int, payload: bytes) -> bytes:
    return (
        struct.pack("<II", tag, len(payload))
        + payload
        + struct.pack("<I", 0x80000000 | tag)
    )


def add_clock_alarm(
    document: ClockAlarmDocument, city: ClockCity, *, daylight_saving: bool
) -> ClockAlarmDocument:
    """Append the native city/disabled-midnight alarm, preserving existing bytes.

    City ordinals are shared by the qualified Nano 1 and Video images. The
    caller explicitly chooses the manual DST flag; Host timezone rules are not
    consulted. Sound/time/enable edits use update_clock_alarm afterward.
    """
    if city not in CLOCK_CITIES:
        raise iPodDBWriteError("Choose a city from the iPod's Clock catalog.")
    if type(daylight_saving) is not bool:
        raise TypeError("Clock daylight saving requires a boolean.")
    source = write_clock_alarms(document)
    if document.issues:
        raise iPodDBWriteError("The Clock collection has unsupported records.")
    if not source:
        source = empty_clock_document().source_bytes
    root = _root(source)
    record = (
        struct.pack("<I", 0x40000001)
        + _field(2, struct.pack("<I", city.region))
        + _field(3, struct.pack("<I", city.ordinal))
        + _field(0x14, bytes((int(daylight_saving),)))
        + struct.pack("<I", 0x40000005)
        + b"".join(
            _field(tag, struct.pack("<I", value))
            for tag, value in ((6, 0), (7, 8), (0x1F, 0), (8, 0))
        )
        + struct.pack("<II", 0xC0000005, 0xC0000001)
    )
    if len(source) + len(record) > _MAX_BYTES:
        raise iPodDBWriteError("The Clock collection exceeds the supported size.")
    return parse_clock_alarms(source[: root.end - 4] + record + source[root.end - 4 :])


def remove_clock_alarm(document: ClockAlarmDocument, index: int) -> ClockAlarmDocument:
    """Remove exactly one city and its alarm, including the final city."""
    source = write_clock_alarms(document)
    if type(index) is not int or not 0 <= index < len(document.records):
        raise IndexError("Clock Alarm index is out of range.")
    record = parse_clock_alarms(source).records[index]
    if not record.editable:
        raise iPodDBWriteError("This Clock has an unsupported record layout.")
    return parse_clock_alarms(
        source[: record.source_offset] + source[record.source_end :]
    )
