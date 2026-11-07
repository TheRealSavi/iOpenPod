"""Read-only, lossless observations of qualified firmware DST override files.

Classic 120GB RetailOS 2.0.1 reads 205 ordered little-endian rows. Later
firmware has different framing and week selectors; length never selects a profile.
These annual rules are not historical timezone data or clock-write instructions.
"""

from dataclasses import dataclass
from enum import StrEnum

from iPodDB.preferences._source import capture_source
from iPodDB.shared.binary_struct import parse_binary_struct
from iPodDB.shared.chunk import BinaryStruct
from iPodDB.shared.chunk_field import chunk_field as cf

_ROW_BYTES = 16
_ROW_COUNT = 205
_TABLE_BYTES = _ROW_BYTES * _ROW_COUNT


class DSTTableProfile(StrEnum):
    UNKNOWN = "unknown"
    CLASSIC_120GB_2_0_1 = "classic_120gb_2_0_1"
    CLASSIC_UPDATER_35_2_0_4 = "classic_updater_35_2_0_4"
    CLASSIC_UPDATER_38_2_0_5 = "classic_updater_38_2_0_5"

    @property
    def prefix_size(self) -> int:
        return 2 if self in _PREFIXED_PROFILES else 0


_PREFIXED_PROFILES = frozenset(
    (DSTTableProfile.CLASSIC_UPDATER_35_2_0_4, DSTTableProfile.CLASSIC_UPDATER_38_2_0_5)
)


class DSTWeek(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD = "third"
    FOURTH = "fourth"
    LAST = "last"


class DSTTableIssueCode(StrEnum):
    INCOMPLETE = "incomplete"
    TRAILING_DATA = "trailing_data"
    DUPLICATE_CITY = "duplicate_city"
    UNUSUAL_TRANSITION = "unusual_transition"


@dataclass(frozen=True, slots=True)
class DSTTableIssue:
    code: DSTTableIssueCode
    row_index: int | None = None


@dataclass(frozen=True, slots=True)
class DSTTransition:
    """Nominal annual selector, not a calculated instant.

    Sunday is zero. The meaning of week 4/5 depends on the firmware profile.
    Firmware weekday arithmetic has exceptions, so these do not promise a date.
    """

    month: int
    weekday: int
    week: int

    def week_occurrence(self, profile: DSTTableProfile) -> DSTWeek | None:
        if profile is DSTTableProfile.UNKNOWN:
            return None
        if self.week in (1, 2, 3):
            return (DSTWeek.FIRST, DSTWeek.SECOND, DSTWeek.THIRD)[self.week - 1]
        if profile is DSTTableProfile.CLASSIC_120GB_2_0_1:
            return DSTWeek.LAST if self.week == 4 else None
        return {4: DSTWeek.FOURTH, 5: DSTWeek.LAST}.get(self.week)

    def supported(self, profile: DSTTableProfile) -> bool:
        return (
            1 <= self.month <= 12
            and 0 <= self.weekday <= 6
            and self.week_occurrence(profile) is not None
        )


@dataclass(frozen=True, slots=True)
class DSTRule(BinaryStruct):
    """One qualified Classic row; raw values and reserved bytes are retained."""

    city_id: int = cf(0x00, "u16")
    enabled_raw: int = cf(0x02, "u8")
    start_weekday: int = cf(0x03, "u8")
    end_weekday: int = cf(0x04, "u8")
    reserved: bytes = cf(0x05, "raw", size=3)
    start_month: int = cf(0x08, "u16")
    start_week: int = cf(0x0A, "u16")
    end_month: int = cf(0x0C, "u16")
    end_week: int = cf(0x0E, "u16")

    @property
    def enabled(self) -> bool:
        return self.enabled_raw != 0

    @property
    def start(self) -> DSTTransition:
        return DSTTransition(self.start_month, self.start_weekday, self.start_week)

    @property
    def end(self) -> DSTTransition:
        return DSTTransition(self.end_month, self.end_weekday, self.end_week)


@dataclass(frozen=True, slots=True)
class DSTTableDocument:
    source_bytes: bytes
    profile: DSTTableProfile
    rules: tuple[DSTRule, ...] = ()
    issues: tuple[DSTTableIssue, ...] = ()

    @property
    def expected_rows(self) -> int | None:
        return None if self.profile is DSTTableProfile.UNKNOWN else _ROW_COUNT

    @property
    def complete(self) -> bool:
        return self.expected_rows is not None and len(self.rules) == self.expected_rows

    @property
    def prefix_bytes(self) -> bytes:
        """Two bytes retained by later loaders, with no verified numeric meaning."""
        return self.source_bytes[: self.profile.prefix_size]

    @property
    def unparsed_bytes(self) -> bytes:
        """Partial final row and/or bytes beyond the firmware read, without padding."""
        return self.source_bytes[
            self.profile.prefix_size + len(self.rules) * _ROW_BYTES :
        ]

    def rules_for_city(self, city_id: int) -> tuple[DSTRule, ...]:
        """Retain duplicate order and compare the full caller-supplied city ID."""
        return tuple(rule for rule in self.rules if rule.city_id == city_id)

    def serialize(self) -> bytes:
        """Reproduce the captured file; this observation model has no edit writer."""
        return self.source_bytes


def parse_dst_table(
    data: bytes | bytearray, *, profile: DSTTableProfile = DSTTableProfile.UNKNOWN
) -> DSTTableDocument:
    """Capture optional evidence without rejecting short or unusual calendar data."""
    if type(profile) is not DSTTableProfile:
        raise TypeError("profile must be a DSTTableProfile.")
    source = capture_source(data)
    if profile is DSTTableProfile.UNKNOWN:
        return DSTTableDocument(source, profile)
    start = profile.prefix_size
    extent = start + _TABLE_BYTES
    count = max(0, min(len(source) - start, _TABLE_BYTES)) // _ROW_BYTES
    rules = tuple(
        parse_binary_struct(
            source,
            start + index * _ROW_BYTES,
            DSTRule,
            limit=start + (index + 1) * _ROW_BYTES,
        )
        for index in range(count)
    )
    issues: list[DSTTableIssue] = []
    if len(source) < extent:
        issues.append(DSTTableIssue(DSTTableIssueCode.INCOMPLETE))
    elif len(source) > extent:
        issues.append(DSTTableIssue(DSTTableIssueCode.TRAILING_DATA))
    seen: set[int] = set()
    for index, rule in enumerate(rules):
        if rule.city_id in seen:
            issues.append(DSTTableIssue(DSTTableIssueCode.DUPLICATE_CITY, index))
        seen.add(rule.city_id)
        if rule.enabled and not (
            rule.start.supported(profile) and rule.end.supported(profile)
        ):
            issues.append(DSTTableIssue(DSTTableIssueCode.UNUSUAL_TRANSITION, index))
    return DSTTableDocument(source, profile, rules, tuple(issues))
