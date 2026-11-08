"""Retained Alarm records; calendar coordinates are not asserted UTC instants.

See docs/research/calendar-alarm-firmware-2026-11-06.md. The latest Classics
store seconds from a 1970 civil epoch, unlike 1904 media dates. Zero is a real
coordinate; 0xffffffff is retained but is not selected by the native scheduler.
"""

from dataclasses import dataclass

from whenever import PlainDateTime, Time

ALARM_EPOCH = PlainDateTime(1970, 1, 1)


@dataclass(frozen=True, slots=True)
class AlarmRecord:
    """One existing token container; unidentified values remain observations.

    source_offset/source_end identify its retained extent, not fixed field
    offsets. Only date and repeat payloads may change. Label, control values,
    unknown tags and original order are preserved without invented defaults.
    """

    index: int
    source_offset: int
    source_end: int
    scheduled_seconds: int | None
    repeat_mode: int | None
    control_word: int | None
    selection: int | None
    sound_selector: int | None
    label: str | None
    can_edit_date: bool
    can_edit_repeat: bool

    @property
    def scheduled(self) -> PlainDateTime | None:
        """The raw calendar coordinate, without Host zone or fold resolution."""
        if (
            self.scheduled_seconds is None
            or not 0 <= self.scheduled_seconds <= 0xFFFFFFFF
        ):
            return None
        return ALARM_EPOCH.add(seconds=self.scheduled_seconds, naive_arithmetic_ok=True)

    @property
    def repeat(self) -> int | None:
        return self.repeat_mode

    @property
    def editable(self) -> bool:
        return self.can_edit_date or self.can_edit_repeat


@dataclass(frozen=True, slots=True)
class AlarmDocument:
    """Captured bytes and optional interpretation; invalid framing stays opaque."""

    source_bytes: bytes
    records: tuple[AlarmRecord, ...] = ()
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreferencesAlarmDocument:
    """One exact Mini/Video saved format; full source bytes remain authoritative.

    The u16 at file +0xb22 contains low-12-bit minute-of-day and four retained
    high bits. This observation does not infer the alarm's enable or sound mode.
    On latest Video firmware it is a derived next-alarm projection; persistent
    per-city alarms live in Device/clock. Raw field patchability is not device
    workflow qualification (owned by Device Registry and the Application Layer).
    """

    source_bytes: bytes
    format: str
    raw_word: int | None = None
    issues: tuple[str, ...] = ()

    @property
    def time(self) -> Time | None:
        if self.raw_word is None:
            return None
        minute = self.raw_word & 0xFFF
        return Time(minute // 60, minute % 60) if minute < 1440 else None

    @property
    def editable(self) -> bool:
        return self.raw_word is not None and not self.issues
