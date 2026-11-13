"""Bounded, lossless Classic/Nano Alarm token parsing and explicit authoring.

The consumer qualifies connected identity/firmware separately. No path is
opened here. Primary byte evidence and independently executed native setters:
docs/research/alarms-clickwheel-firmware-2026-11-13.md.
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
MAX_ALARM_TONE_NAME_BYTES = 254
_SCALARS = (
    (6, "scheduled_seconds"),
    (7, "control_word"),
    (0x3B, "repeat_mode"),
    (0x1F, "selection"),
    (8, "sound_selector"),
)
_KNOWN_IDS = frozenset(token for token, _ in _SCALARS) | {0x3C}
_PREFERENCES_PROFILES = {
    "mini1": PreferencesProfile.MINI_1_1_4_1,
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
                not duplicate
                and values["control_word"] in (0, 4, 8)
                and values["sound_selector"] is not None,
                not duplicate and values["selection"] is not None,
                not duplicate and label is not None,
                not duplicate and values["sound_selector"] is not None,
            )
        )
    return AlarmDocument(source, tuple(records), tuple(issues))


def write_alarms(document: AlarmDocument) -> bytes:
    """Patch qualified fields; unchanged opaque bytes round-trip.

    Record insertion/removal and edits to unqualified fields are rejected.
    Reparse retained source rather than trusting public offset/editable values.
    Unknown native repeat codes survive unrelated edits unchanged. A tone-name
    replacement changes only its length and payload, retaining token framing.
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
    strings: list[tuple[_Field, bytes]] = []
    for before, after, record in zip(
        original.records, document.records, native, strict=True
    ):
        if (
            replace(
                after,
                scheduled_seconds=before.scheduled_seconds,
                repeat_mode=before.repeat_mode,
                control_word=before.control_word,
                selection=before.selection,
                sound_selector=before.sound_selector,
                label=before.label,
            )
            != before
        ):
            raise iPodDBWriteError("Only qualified existing alarm fields are editable.")
        for name, token, allowed in (
            ("scheduled_seconds", 6, before.can_edit_date),
            ("repeat_mode", 0x3B, before.can_edit_repeat),
            ("control_word", 7, before.can_edit_enabled),
            ("selection", 0x1F, before.can_edit_label),
            ("sound_selector", 8, before.can_edit_playlist),
        ):
            value = getattr(after, name)
            if value == getattr(before, name):
                continue
            valid = type(value) is int and (
                value in (0, _enabled_control(after))
                if token == 7
                else 0
                <= value
                <= (
                    0xFFFFFFFE
                    if token == 6
                    else 0xFFFFFFFF
                    if token == 8
                    else 22
                    if token == 0x1F
                    else 6
                )
            )
            if not allowed or not valid:
                raise iPodDBWriteError(
                    "The changed alarm field is not a qualified value.", field=name
                )
            field = _unique(record.fields, token)
            assert field is not None
            struct.pack_into("<I", output, field.offset, value)
        if after.label != before.label:
            if not before.can_edit_tone:
                raise iPodDBWriteError("The retained tone name is not editable.")
            payload = _tone_payload(after.label)
            field = _unique(record.fields, 0x3C)
            assert field is not None
            strings.append((field, payload))
    for field, payload in reversed(strings):
        output[field.offset - 4 : field.offset + field.length] = (
            struct.pack("<I", len(payload)) + payload
        )
    if len(output) > MAX_ALARM_BYTES:
        raise iPodDBWriteError("Alarm collection exceeds the interpretation limit.")
    return bytes(output)


def _tone_payload(name: object) -> bytes:
    if not isinstance(name, str) or "\0" in name:
        raise iPodDBWriteError("Alarm tone names must be text without NUL characters.")
    try:
        payload = name.encode("utf-8")
    except UnicodeEncodeError as error:
        raise iPodDBWriteError("Alarm tone names must be valid UTF-8.") from error
    if len(payload) > MAX_ALARM_TONE_NAME_BYTES:
        raise iPodDBWriteError("Alarm tone name exceeds the native read buffer.")
    return payload + b"\0"


def _alarm_seconds(value: object) -> int:
    if not isinstance(value, PlainDateTime):
        raise TypeError("Alarm dates require a PlainDateTime calendar coordinate.")
    return (
        value.difference(ALARM_EPOCH, naive_arithmetic_ok=True).total("nanoseconds")
        // 1_000_000_000
    )


def _enabled_control(record: AlarmRecord) -> int:
    """Native ToggleAlarm chooses the gate from the retained sound selector."""
    return 8 if record.sound_selector == 0xFFFFFFFF else 4


def update_alarm(
    document: AlarmDocument,
    index: int,
    *,
    scheduled: PlainDateTime | None = None,
    repeat_mode: int | None = None,
    enabled: bool | None = None,
    label_index: int | None = None,
    tone_name: str | None = None,
    playlist_selector: int | None = None,
) -> AlarmDocument:
    """Edit an existing alarm in its civil coordinate, without timezone guessing.

    Whole native seconds floor subsecond input. Unrepresentable new dates are
    an edit validation issue, never a reason to reject captured dates or media.
    Sound setters are independent: empty tone name/0xffffffff Playlist clear
    their own field; None retains it. Only an explicit enable transition derives
    a fresh gate from the resulting Playlist selector.
    """
    if type(index) is not int or not 0 <= index < len(document.records):
        raise IndexError("Alarm index is outside the captured document.")
    if enabled is not None and type(enabled) is not bool:
        raise TypeError("Alarm enabled state must be boolean.")
    if playlist_selector is not None and (
        type(playlist_selector) is not int or not 0 <= playlist_selector <= 0xFFFFFFFF
    ):
        raise iPodDBWriteError("Alarm Playlist selector must be an unsigned word.")
    record = document.records[index]
    word = record.scheduled_seconds
    if scheduled is not None:
        word = _alarm_seconds(scheduled)
    if playlist_selector is not None:
        record = replace(record, sound_selector=playlist_selector)
    records = list(document.records)
    records[index] = replace(
        record,
        scheduled_seconds=word,
        repeat_mode=record.repeat_mode if repeat_mode is None else repeat_mode,
        control_word=(
            record.control_word
            if enabled is None or enabled is record.enabled
            else _enabled_control(record)
            if enabled
            else 0
        ),
        selection=record.selection if label_index is None else label_index,
        label=record.label if tone_name is None else tone_name,
    )
    updated = replace(document, records=tuple(records))
    write_alarms(updated)
    return updated


def empty_alarm_document() -> AlarmDocument:
    """Native empty collection framing for an explicitly authored new file."""
    return parse_alarms(struct.pack("<II", 0x4000003A, 0xC000003A))


def _structural_source(document: AlarmDocument) -> bytes:
    source = write_alarms(document)
    if parse_alarms(source).issues:
        raise iPodDBWriteError("Alarm collection framing must be unambiguous.")
    return source


def add_alarm(
    document: AlarmDocument,
    *,
    scheduled: PlainDateTime,
    repeat_mode: int = 0,
    enabled: bool = True,
    label_index: int = 3,
    tone_name: str = "",
    playlist_selector: int = 0xFFFFFFFF,
) -> AlarmDocument:
    """Append one native default alarm, preserving every existing source byte.

    Defaults come from the native constructor: label-menu index 3, no Playlist
    selector, empty tone name and control 8. Explicit sound choices precede the
    native enable transition. Callers choose an audible sound; constructor
    defaults alone do not imply one. Firmware owns notification and live wake.
    """
    source = _structural_source(document)
    seconds = _alarm_seconds(scheduled)
    if not 0 <= seconds <= 0xFFFFFFFE:
        raise iPodDBWriteError("Alarm date is outside the native scheduling range.")
    if type(repeat_mode) is not int or not 0 <= repeat_mode <= 6:
        raise iPodDBWriteError("Alarm repeat mode must be between 0 and 6.")
    if type(enabled) is not bool:
        raise TypeError("Alarm enabled state must be boolean.")
    if type(label_index) is not int or not 0 <= label_index <= 22:
        raise iPodDBWriteError("Alarm label index must be between 0 and 22.")
    if type(playlist_selector) is not int or not 0 <= playlist_selector <= 0xFFFFFFFF:
        raise iPodDBWriteError("Alarm Playlist selector must be an unsigned word.")
    tone = _tone_payload(tone_name)
    record = bytearray(struct.pack("<I", 0x40000005))
    for token, value in (
        (6, seconds),
        (7, (8 if playlist_selector == 0xFFFFFFFF else 4) if enabled else 0),
        (0x3B, repeat_mode),
        (0x1F, label_index),
        (8, playlist_selector),
    ):
        record.extend(struct.pack("<IIII", token, 4, value, 0x80000000 | token))
    record.extend(struct.pack("<II", 0x3C, len(tone)))
    record.extend(tone)
    record.extend(struct.pack("<II", 0x8000003C, 0xC0000005))
    if len(source) + len(record) > MAX_ALARM_BYTES:
        raise iPodDBWriteError("Alarm collection exceeds the interpretation limit.")
    return parse_alarms(source[:-4] + record + source[-4:])


def remove_alarm(document: AlarmDocument, index: int) -> AlarmDocument:
    """Remove exactly the selected record's span, retaining unknown siblings."""
    source = _structural_source(document)
    original = parse_alarms(source)
    if type(index) is not int or not 0 <= index < len(original.records):
        raise IndexError("Alarm index is outside the captured document.")
    record = original.records[index]
    return parse_alarms(source[: record.source_offset] + source[record.source_end :])


def parse_preferences_alarm(
    data: bytes | bytearray, format: str
) -> PreferencesAlarmDocument:
    """Interpret exact Mini 1/2 1.4.1 or Video 1.3 framing, not device identity."""
    source = _source(data)
    profile = _PREFERENCES_PROFILES.get(format)
    if profile is None or not matches_preferences_profile(source, profile):
        return PreferencesAlarmDocument(
            source, format, issues=("Preferences alarm framing is not qualified.",)
        )
    raw = int.from_bytes(
        source[PREFERENCES_ALARM_OFFSET : PREFERENCES_ALARM_OFFSET + 2], "little"
    )
    return PreferencesAlarmDocument(
        source,
        format,
        raw,
        mode_word=int.from_bytes(source[0xB18:0xB1A], "little"),
        playlist_id=int.from_bytes(source[0xB24:0xB2C], "little"),
    )


def _alarm_minutes(value: object) -> int:
    if not isinstance(value, Time):
        raise TypeError("Alarm time requires Whenever Time.")
    return value.hour * 60 + value.minute


def patch_preferences_alarm(
    document: PreferencesAlarmDocument,
    time: Time | None = None,
    *,
    enabled: bool | None = None,
    sound_playlist_id: int | None = None,
    sound_playlist_index: int | None = None,
    playlist_index: int | None = None,
) -> bytes:
    """Patch Mini time, native sound selection and qualified enable transitions.

    The firmware field has minute precision. Seconds/subseconds are discarded
    explicitly, independently of any Host timezone or firmware date selection.
    Sound selection uses a caller-qualified native index/ID pair (index zero is
    the Master Playlist/Beep row), and enables before applying explicit enabled.
    Enabling a retained nonzero ID needs its current native lookup result.
    """
    minutes = None if time is None else _alarm_minutes(time)
    if enabled is not None and type(enabled) is not bool:
        raise TypeError("Alarm enabled state requires a boolean.")
    original = parse_preferences_alarm(document.source_bytes, document.format)
    if document != original or original.raw_word is None:
        raise iPodDBWriteError(
            "An alarm edit requires unchanged, qualified Preferences evidence."
        )
    output = bytearray(original.source_bytes)
    if minutes is not None:
        value = (original.raw_word & 0xF000) | minutes
        struct.pack_into("<H", output, PREFERENCES_ALARM_OFFSET, value)
    selecting = sound_playlist_id is not None or sound_playlist_index is not None
    if selecting or enabled is not None:
        if original.format not in ("mini", "mini1") or original.mode_word is None:
            raise iPodDBWriteError("This saved alarm's control fields are unqualified.")
        mode = original.mode_word & 0x0C
        current_id = original.playlist_id
        lookup = playlist_index
        if lookup is not None and (
            type(lookup) is not int or not -1 <= lookup <= 0x7FFFFFFF
        ):
            raise iPodDBWriteError(
                "Mini Playlist lookup must be a native signed index."
            )
        if selecting:
            if (
                type(sound_playlist_id) is not int
                or not 0 <= sound_playlist_id <= 0xFFFFFFFFFFFFFFFF
                or type(sound_playlist_index) is not int
                or not 0 <= sound_playlist_index <= 0x7FFFFFFF
            ):
                raise iPodDBWriteError(
                    "Mini sound selection needs a qualified Playlist ID and index."
                )
            mode = 0 if sound_playlist_index == 0 else 4
            current_id, lookup = sound_playlist_id, sound_playlist_index
            struct.pack_into("<Q", output, 0xB24, current_id)
        if enabled is not None:
            if mode not in (0, 4, 8):
                raise iPodDBWriteError(
                    "This saved alarm's enable transition is unqualified."
                )
            if not enabled:
                mode = 8
            elif mode == 8:
                if lookup is None:
                    if current_id != 0:
                        raise iPodDBWriteError(
                            "Enabling this alarm needs its native Playlist lookup."
                        )
                    lookup = -1
                mode = 4 if lookup > 0 else 0
        struct.pack_into("<H", output, 0xB18, original.mode_word & ~0x0C | mode)
    return bytes(output)
