"""Parse Host date input with an explicit policy for missing timezone information.

This is not the native iPod clock decoder: device-local words must use iPodDB's
DeviceTimeContext and preservation rules. Editors interpret unqualified input in
the Host zone; media tags use UTC. Callers choose that policy explicitly.
"""

from __future__ import annotations

from enum import Enum

from whenever import (
    SYSTEM_TZ,
    Date,
    Instant,
    OffsetDateTime,
    PlainDateTime,
    Time,
    TimeDelta,
    reset_system_tz,
)


class HostDateZone(Enum):
    """Explicit Host-zone policy without exposing Whenever's sentinel as a type.

    Mypy does not yet accept the 0.11 SYSTEM_TZ sentinel in type annotations.
    Keep the compatibility choice here; actual resolution still uses Whenever.
    """

    SYSTEM = "system"


def refresh_host_timezone() -> bool:
    """Refresh Whenever's cached Host zone at lifecycle/calendar boundaries.

    Activation and background delivery can follow a Host timezone change. Avoid
    refreshing in each table cell, and never change captured DeviceTimeContext
    evidence. A failed reset can retain Whenever's last usable zone, so callers
    authoring dates must check the result. Displays can retain that projection;
    delivery can wait without blocking Library Sync.
    """
    try:
        reset_system_tz()
    except (OSError, OverflowError, ValueError):
        return False
    return True


def parse_iso_instant(
    text: str, *, naive_zone: str | HostDateZone | TimeDelta
) -> Instant:
    """Read ISO text, keeping explicit offsets and resolving local gaps/folds.

    Date-only values mean midnight. For unqualified local times, ``compatible``
    chooses the earlier occurrence of a repeated time and moves a missing time
    forward by the transition gap. This deterministic input policy cannot recover
    a device's historical clock setting. Invalid syntax remains a ValueError for
    the caller's existing validation/fallback path. If the requested Host zone
    is unavailable, valid civil fields instead estimate UTC (ADR-0240). An
    explicitly supplied fixed offset remains a caller contract and is validated.
    Converting to integer seconds floors fractions, including before 1970.
    """
    try:
        return OffsetDateTime.parse_iso(text).to_instant()
    except ValueError:
        pass
    try:
        local = PlainDateTime.parse_iso(text)
    except ValueError:
        local = Date.parse_iso(text).at(Time())
    if isinstance(naive_zone, TimeDelta):
        return local.assume_fixed_offset(naive_zone).to_instant()
    try:
        if naive_zone is HostDateZone.SYSTEM:
            # Input acceptance is another calendar boundary, not a table-cell
            # conversion. Check reset's result: failure may leave a stale zone.
            if not refresh_host_timezone():
                return local.assume_utc()
            return local.assume_tz(SYSTEM_TZ, disambiguation="compatible").to_instant()
        return local.assume_tz(naive_zone, disambiguation="compatible").to_instant()
    except (OSError, OverflowError, ValueError):
        return local.assume_utc()
