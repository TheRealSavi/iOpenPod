"""Device-local Mac dates and UTC Unix instants, without device or clock I/O.

The caller supplies a captured IANA key or effective fixed offset. Whenever's
historical rules interpret that key; neither the Host zone nor clock is consulted.
Native words remain separate from this best-effort interpretation.

Firmware fact: the latest Classics retain calendar-shaped words and cannot encode
a repeated hour's occurrence. IANA history, offset tie-breaking and gap estimates
are Host policy, not recovered device history. See docs/ipod-time.md,
docs/research/classic-datetime-file-map-2026-11-06.md and ADR-0240.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from whenever import Instant, PlainDateTime, TimeDelta, seconds

MAC_EPOCH_UNIX_OFFSET = 2_082_844_800
MAC_EPOCH_MAX = 0xFFFF_FFFF
CORE_DATA_EPOCH_UNIX_OFFSET = 978_307_200
MIN_LOCAL_UNIX_TIME = 1 - MAC_EPOCH_UNIX_OFFSET - 86399
MAX_LOCAL_UNIX_TIME = MAC_EPOCH_MAX - MAC_EPOCH_UNIX_OFFSET + 86399
_MAC_CALENDAR_EPOCH = PlainDateTime(1904, 1, 1)

type CapturedTimezone = str | TimeDelta


class MacTimestampOutOfRangeError(ValueError):
    """Legacy import compatibility; date conversion now bounds values instead."""


class DeviceTimeSource(StrEnum):
    PREFERENCES_OFFSET = "preferences_offset"
    PREFERENCES_CITY = "preferences_city"
    DATABASE_HEADER = "database_header"
    UNRESOLVED = "unresolved"


def valid_offset(value: object) -> bool:
    return type(value) is int and -86400 < value < 86400


def possible_unix_date(value: object) -> bool:
    """Integer dates can always be bounded to the native date range."""
    return type(value) is int


@dataclass(frozen=True, slots=True)
class DeviceTimeContext:
    """A captured IANA key or whole-second fixed offset, with its provenance.

    An IANA key identifies Host interpretation rules, not the firmware's annual
    DST table. The independent database offset is evidence for a fold tie-break;
    neither it nor saved DST/correction is added to a geographical zone's offset.
    Invalid offsets fall back during conversion rather than blocking a Library.
    """

    zone: CapturedTimezone | None = None
    source: DeviceTimeSource = DeviceTimeSource.UNRESOLVED
    timezone_name: str | None = None
    database_offset_seconds: int = 0
    detail: str = ""

    def for_database(self, offset: int) -> DeviceTimeContext:
        if (
            self.source
            in (
                DeviceTimeSource.PREFERENCES_OFFSET,
                DeviceTimeSource.PREFERENCES_CITY,
            )
            and self.zone is not None
        ):
            return replace(self, database_offset_seconds=offset)
        return replace(
            self,
            zone=seconds(offset) if valid_offset(offset) else None,
            source=DeviceTimeSource.DATABASE_HEADER
            if valid_offset(offset)
            else DeviceTimeSource.UNRESOLVED,
            database_offset_seconds=offset,
        )


type TimeConversion = DeviceTimeContext | int | None


def _fixed_offset(context: TimeConversion) -> TimeDelta:
    """Choose captured evidence only; unknown or invalid evidence estimates UTC."""
    offset = (
        context.database_offset_seconds
        if isinstance(context, DeviceTimeContext)
        else context
    )
    return (
        seconds(offset)
        if type(offset) is int and valid_offset(offset)
        else TimeDelta.ZERO
    )


def _zone(context: TimeConversion) -> CapturedTimezone:
    if isinstance(context, DeviceTimeContext):
        if isinstance(context.zone, str):
            return context.zone
        if isinstance(context.zone, TimeDelta):
            nanos = context.zone.total("nanoseconds")
            if nanos % 1_000_000_000 == 0 and valid_offset(nanos // 1_000_000_000):
                return context.zone
    return _fixed_offset(context)


@dataclass(frozen=True, slots=True)
class DateInterpretation:
    """A usable Unix date and an optional explanation of its approximation."""

    value: int
    detail: str = ""


def interpret_mac(
    value: int, context: TimeConversion, *, utc: bool = False
) -> DateInterpretation:
    """Prefer city rules; resolve folds/gaps consistently without rejecting data."""
    if type(value) is not int:
        return DateInterpretation(0, "An invalid date is displayed as missing.")
    if value == 0:
        return DateInterpretation(0)
    bounded = min(MAC_EPOCH_MAX, max(1, value))
    detail = "The date was bounded to the iPod date range." if bounded != value else ""
    if utc:
        return DateInterpretation(bounded - MAC_EPOCH_UNIX_OFFSET, detail)
    zone = _zone(context)
    # This arithmetic decodes a civil coordinate, not elapsed real-world time.
    local = _MAC_CALENDAR_EPOCH.add(seconds=bounded, naive_arithmetic_ok=True)
    if isinstance(zone, str):
        try:
            earlier = local.assume_tz(zone, disambiguation="earlier")
            later = local.assume_tz(zone, disambiguation="later")
        except ValueError:
            # An unavailable/malformed IANA key is optional date evidence too.
            result = local.assume_fixed_offset(_fixed_offset(context)).timestamp()
            detail = "The timezone rules are unavailable; dates use the retained fixed offset or UTC when that offset is invalid."
        else:
            if earlier == later:
                result = earlier.timestamp()
            elif earlier.to_plain() == local:
                # Both occurrences exist. The header breaks a tie, not history.
                offset = (
                    seconds(context.database_offset_seconds)
                    if isinstance(context, DeviceTimeContext)
                    and valid_offset(context.database_offset_seconds)
                    else None
                )
                result = (later if later.offset == offset else earlier).timestamp()
                detail = "A repeated local hour was interpreted using the retained offset when it matches, otherwise its earlier occurrence."
            else:
                # 'later' advances through a gap using the pre-transition offset.
                result = later.timestamp()
                detail = "A skipped local hour was interpreted using the pre-transition offset."
    else:
        result = local.assume_fixed_offset(zone).timestamp()
    if isinstance(context, DeviceTimeContext) and (
        context.zone is None or context.zone != zone
    ):
        detail = "The timezone is unknown; dates use the retained fixed offset or UTC when that offset is invalid."
    elif context is None or (isinstance(context, int) and not valid_offset(context)):
        detail = "The timezone is unknown; dates are interpreted as UTC."
    return DateInterpretation(result, detail)


def mac_to_unix(value: int, context: TimeConversion, *, utc: bool = False) -> int:
    """Decode a best-effort instant, preserving zero as a missing date."""
    return interpret_mac(value, context, utc=utc).value


def project_mac(value: int, context: TimeConversion, *, utc: bool = False) -> int:
    """Project a best-effort date without changing retained native bytes."""
    return mac_to_unix(value, context, utc=utc)


def unix_to_mac(
    value: int, context: TimeConversion, *, utc: bool = False, missing_zero: bool = True
) -> int:
    """Encode Unix seconds, bounding unrepresentable dates without wrapping."""
    if type(value) is not int:
        return 0 if missing_zero else 1
    if value == 0 and missing_zero:
        return 0
    bounded = min(MAX_LOCAL_UNIX_TIME, max(MIN_LOCAL_UNIX_TIME, value))
    instant = Instant.from_timestamp(bounded)
    zone = TimeDelta.ZERO if utc else _zone(context)
    if isinstance(zone, str):
        try:
            local = instant.to_tz(zone).to_plain()
        except ValueError:
            local = instant.to_fixed_offset(_fixed_offset(context)).to_plain()
    else:
        local = instant.to_fixed_offset(zone).to_plain()
    # Reinterpret components solely to encode the native calendar coordinate.
    encoded = local.assume_utc().timestamp() + MAC_EPOCH_UNIX_OFFSET
    return min(MAC_EPOCH_MAX, max(1, encoded))


def unix_to_core_data(value: int) -> int:
    """SQLite dates are UTC seconds since 2001; no device-local adjustment."""
    return value - CORE_DATA_EPOCH_UNIX_OFFSET if value else 0
