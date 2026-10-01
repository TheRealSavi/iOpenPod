"""Device-local Mac dates and UTC Unix instants, without filesystem or clock I/O.

The caller supplies a captured geographical zone or fixed offset. Ambiguous and
nonexistent local times are never silently assigned an instant. Retained binary
values remain in their source documents even when projection is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from enum import StrEnum

MAC_EPOCH_UNIX_OFFSET = 2_082_844_800
MAC_EPOCH_MAX = 0xFFFF_FFFF
CORE_DATA_EPOCH_UNIX_OFFSET = 978_307_200
MIN_LOCAL_UNIX_TIME = 1 - MAC_EPOCH_UNIX_OFFSET - 86399
MAX_LOCAL_UNIX_TIME = MAC_EPOCH_MAX - MAC_EPOCH_UNIX_OFFSET + 86399
_UNIX = datetime(1970, 1, 1)


class MacTimestampOutOfRangeError(ValueError):
    """An instant cannot be represented by a nonzero u32 Mac timestamp."""


class DeviceTimeSource(StrEnum):
    PREFERENCES_OFFSET = "preferences_offset"
    PREFERENCES_CITY = "preferences_city"
    DATABASE_HEADER = "database_header"
    UNRESOLVED = "unresolved"


def valid_offset(value: object) -> bool:
    return type(value) is int and -86400 < value < 86400


def possible_unix_date(value: object) -> bool:
    """Source-neutral envelope; exact range/fold validation needs device rules."""
    return type(value) is int and MIN_LOCAL_UNIX_TIME <= value <= MAX_LOCAL_UNIX_TIME


@dataclass(frozen=True, slots=True)
class DeviceTimeContext:
    """One Library's clock evidence, distinct from its native database header."""

    zone: tzinfo | None = None
    source: DeviceTimeSource = DeviceTimeSource.UNRESOLVED
    timezone_name: str | None = None
    database_offset_seconds: int = 0
    detail: str = ""

    def for_database(self, offset: int) -> DeviceTimeContext:
        if self.source in (
            DeviceTimeSource.PREFERENCES_OFFSET,
            DeviceTimeSource.PREFERENCES_CITY,
        ):
            if self.zone is None:
                raise ValueError("Resolved Preferences require a device timezone.")
            return replace(self, database_offset_seconds=offset)
        return replace(
            self,
            zone=timezone(timedelta(seconds=offset)) if valid_offset(offset) else None,
            source=DeviceTimeSource.DATABASE_HEADER
            if valid_offset(offset)
            else DeviceTimeSource.UNRESOLVED,
            database_offset_seconds=offset,
        )


type TimeConversion = DeviceTimeContext | int | None


def _zone(context: TimeConversion) -> tzinfo:
    if isinstance(context, DeviceTimeContext):
        if context.zone is not None:
            return context.zone
    elif valid_offset(context):
        assert isinstance(context, int)
        return timezone(timedelta(seconds=context))
    raise ValueError("The device timezone is unresolved; this date is unavailable.")


def mac_to_unix(value: int, context: TimeConversion, *, utc: bool = False) -> int:
    """Decode a unique local instant, preserving zero as a missing date."""
    if type(value) is not int or not 0 <= value <= MAC_EPOCH_MAX:
        raise MacTimestampOutOfRangeError("Invalid unsigned iPod date.")
    if value == 0:
        return 0
    if utc:
        return value - MAC_EPOCH_UNIX_OFFSET
    zone = _zone(context)
    local = _UNIX + timedelta(seconds=value - MAC_EPOCH_UNIX_OFFSET)
    candidates: set[int] = set()
    for fold in (0, 1):
        instant = local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == local:
            candidates.add(int((instant.replace(tzinfo=None) - _UNIX).total_seconds()))
    if len(candidates) != 1:
        raise ValueError(
            "The device date is ambiguous or nonexistent at a DST transition."
        )
    return candidates.pop()


def project_mac(value: int, context: TimeConversion, *, utc: bool = False) -> int:
    """Unresolved native dates remain unavailable and retain their source bytes."""
    try:
        return mac_to_unix(value, context, utc=utc)
    except ValueError:
        return 0


def unix_to_mac(
    value: int, context: TimeConversion, *, utc: bool = False, missing_zero: bool = True
) -> int:
    """Encode Unix seconds; reject overflow and loss of DST-fold identity."""
    if type(value) is not int:
        raise ValueError("Dates must be integer Unix seconds.")
    if value == 0 and missing_zero:
        return 0
    try:
        instant = (_UNIX + timedelta(seconds=value)).replace(tzinfo=UTC)
        local = instant if utc else instant.astimezone(_zone(context))
        encoded = (
            int((local.replace(tzinfo=None) - _UNIX).total_seconds())
            + MAC_EPOCH_UNIX_OFFSET
        )
    except (OverflowError, OSError) as error:
        raise MacTimestampOutOfRangeError(
            "This date is outside the unsigned iPod date range."
        ) from error
    if not 0 < encoded <= MAC_EPOCH_MAX:
        raise MacTimestampOutOfRangeError(
            "This date is outside the unsigned iPod date range."
        )
    if mac_to_unix(encoded, context, utc=utc) != value:
        raise ValueError("This date cannot be represented uniquely on the iPod.")
    return encoded


def unix_to_core_data(value: int) -> int:
    """SQLite dates are UTC seconds since 2001; no device-local adjustment."""
    return value - CORE_DATA_EPOCH_UNIX_OFFSET if value else 0
