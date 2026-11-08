"""Calendar file values, without filesystem authority or Host timezone policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum

from whenever import Date, Instant, PlainDateTime

type CalendarValue = Date | PlainDateTime | Instant


class CalendarProfile(StrEnum):
    UNKNOWN = "unknown"
    MINI_2_1_4_1 = "mini_2_1_4_1"
    CLASSIC_6_1_1_2 = "classic_6_1_1_2"
    CLASSIC_120GB_2_0_1 = "classic_120gb_2_0_1"
    CLASSIC_UPDATER_35_2_0_4 = "classic_updater_35_2_0_4"
    CLASSIC_UPDATER_38_2_0_5 = "classic_updater_38_2_0_5"


class CalendarFrequency(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"


@dataclass(frozen=True, slots=True)
class CalendarRecurrenceRule:
    frequency: CalendarFrequency
    interval: int = 1
    count: int | None = None
    until: PlainDateTime | None = None


@dataclass(frozen=True, slots=True)
class CalendarReminderDraft:
    minutes_before: int
    related_to_end: bool = False


class CalendarEntryKind(StrEnum):
    EVENT = "VEVENT"
    TODO = "VTODO"


class CalendarDateForm(StrEnum):
    DATE = "date"
    FLOATING = "floating"
    UTC = "utc"
    ZONED = "zoned"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class CalendarDateTime:
    """Original value plus optional interpretation; TZID never resolves on Host.

    ZONED values deliberately contain PlainDateTime and a retained identifier.
    A fold, gap or unknown identifier therefore cannot make parsing fail.
    """

    form: CalendarDateForm
    value: CalendarValue | None
    raw: str
    tzid: str | None = None
    issue: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarParameter:
    name: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalendarProperty:
    name: str
    parameters: tuple[CalendarParameter, ...]
    value: str
    raw_bytes: bytes
    start_offset: int
    end_offset: int

    def parameter_values(self, name: str) -> tuple[str, ...]:
        return tuple(
            value
            for parameter in self.parameters
            if parameter.name == name.upper()
            for value in parameter.values
        )


@dataclass(frozen=True, slots=True)
class CalendarComponent:
    name: str
    properties: tuple[CalendarProperty, ...]
    children: tuple[CalendarComponent, ...]
    raw_bytes: bytes
    start_offset: int
    end_offset: int
    end_line_start: int

    @property
    def calendar_name(self) -> str | None:
        """Unique retained X-WR-CALNAME text; filenames never supply this value."""
        import re

        names = [prop for prop in self.properties if prop.name == "X-WR-CALNAME"]
        if len(names) != 1:
            return None
        return re.sub(
            r"\\([nN,;\\])",
            lambda match: "\n" if match[1] in "nN" else match[1],
            names[0].value,
        )


@dataclass(frozen=True, slots=True)
class CalendarRecurrence:
    """Saved recurrence observation, independent of expansion qualification."""

    frequency: str | None
    interval: int | None
    count: int | None
    until: str | None
    raw: str
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CalendarReminder:
    """One retained VALARM; parsed trigger fields do not grant edit permission."""

    component: CalendarComponent
    relative_seconds: int | None = None
    related_to_end: bool = False
    absolute_trigger: CalendarDateTime | None = None
    action: str | None = None
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """A document-local row, not an expanded recurrence occurrence."""

    entry_id: int
    kind: CalendarEntryKind
    uid: str | None
    summary: str
    description: str
    location: str
    start: CalendarDateTime | None
    end: CalendarDateTime | None
    due: CalendarDateTime | None
    completed_at: CalendarDateTime | None
    completed: bool
    editable: bool
    timing_editable: bool
    has_recurrence: bool
    issues: tuple[str, ...]
    component: CalendarComponent
    recurrence: CalendarRecurrence | None = None
    reminders: tuple[CalendarReminder, ...] = ()


@dataclass(frozen=True, slots=True)
class CalendarDocument:
    raw_bytes: bytes
    components: tuple[CalendarComponent, ...]
    entries: tuple[CalendarEntry, ...]
    version: str | None
    editable: bool
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalendarLimits:
    max_bytes: int = 4 * 1024 * 1024
    max_lines: int = 100_000
    max_line_bytes: int = 64 * 1024
    max_components: int = 20_000
    max_depth: int = 16


@dataclass(frozen=True, slots=True, kw_only=True)
class CalendarEntryDraft:
    kind: CalendarEntryKind = CalendarEntryKind.EVENT
    summary: str = ""
    description: str = ""
    location: str = ""
    start: CalendarValue | None = None
    end: CalendarValue | None = None
    due: CalendarValue | None = None
    completed: bool = False
    completed_at: Instant | None = None
    uid: str | None = None
    recurrence: CalendarRecurrenceRule | None = None
    reminder: CalendarReminderDraft | None = None


class Unchanged(Enum):
    VALUE = "unchanged"


UNCHANGED = Unchanged.VALUE


@dataclass(frozen=True, slots=True, kw_only=True)
class CalendarEntryChanges:
    """Explicit changed fields; None clears dates, empty strings clear text.

    Text/boolean None means unchanged. Timing UNCHANGED means unchanged, so a
    summary edit never replaces a retained malformed, zoned or recurring date.
    """

    summary: str | None = None
    description: str | None = None
    location: str | None = None
    start: CalendarValue | Unchanged | None = UNCHANGED
    end: CalendarValue | Unchanged | None = UNCHANGED
    due: CalendarValue | Unchanged | None = UNCHANGED
    completed: bool | None = None
    completed_at: Instant | Unchanged | None = UNCHANGED
    recurrence: CalendarRecurrenceRule | Unchanged | None = UNCHANGED
    reminder: CalendarReminderDraft | Unchanged | None = UNCHANGED


class CalendarEditError(ValueError):
    """An explicit Calendar edit needs different input or an unsupported writer.

    Parsing optional Calendar metadata never raises this error; it is separate
    from Library loading/saving and retained malformed datetime evidence.
    """


@dataclass(frozen=True, slots=True)
class CalendarOccurrence:
    """One projected civil occurrence; editing always targets its source series."""

    start: CalendarDateTime
    end: CalendarDateTime | None


@dataclass(frozen=True, slots=True)
class CalendarOccurrenceResult:
    occurrences: tuple[CalendarOccurrence, ...] = ()
    expanded: bool = False
    detail: str = ""
