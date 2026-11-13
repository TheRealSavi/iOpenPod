"""Retained Alarm records; calendar coordinates are not asserted UTC instants.

See docs/research/alarms-clickwheel-firmware-2026-11-13.md. Classic and Nano 3-5
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
    offsets. Qualified date, repeat, label, enable and sound fields may change.
    The legacy ``label`` attribute retains token 0x3c; ``tone_name`` states its
    sound meaning. Unknown tags and original order remain preserved.
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
    can_edit_enabled: bool = False
    can_edit_label: bool = False
    can_edit_tone: bool = False
    can_edit_playlist: bool = False

    @property
    def tone_name(self) -> str | None:
        """Native tone collection name retained in token 0x3c."""
        return self.label

    @property
    def enabled(self) -> bool | None:
        """The saved scheduler gate; this does not assert live hardware arming."""
        return None if self.control_word is None else self.control_word != 0

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
        return (
            self.can_edit_date
            or self.can_edit_repeat
            or self.can_edit_enabled
            or self.can_edit_label
            or self.can_edit_tone
            or self.can_edit_playlist
        )


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
    high bits. Mini mode observations use the separate word at file +0xb18;
    enabling requires a zero saved Playlist identity or a caller-qualified native
    Playlist lookup. Disabling does not require a Playlist lookup.
    On latest Video firmware it is a derived next-alarm projection; persistent
    per-city alarms live in Device/clock. Raw field patchability is not device
    workflow qualification (owned by Device Registry and the Application Layer).
    """

    source_bytes: bytes
    format: str
    raw_word: int | None = None
    issues: tuple[str, ...] = ()
    mode_word: int | None = None
    playlist_id: int | None = None

    @property
    def time(self) -> Time | None:
        if self.raw_word is None:
            return None
        minute = self.raw_word & 0xFFF
        return Time(minute // 60, minute % 60) if minute < 1440 else None

    @property
    def editable(self) -> bool:
        return self.raw_word is not None and not self.issues

    @property
    def enabled(self) -> bool | None:
        if self.format not in ("mini", "mini1") or self.mode_word is None:
            return None
        mode = self.mode_word & 0x0C
        if mode == 8:
            return False
        return True if mode in (0, 4) else None

    @property
    def can_edit_enabled(self) -> bool:
        return (
            self.editable
            and self.enabled is not None
            and (self.playlist_id == 0 or self.enabled is True)
        )

    @property
    def can_edit_sound(self) -> bool:
        return self.editable and self.format in ("mini", "mini1")
