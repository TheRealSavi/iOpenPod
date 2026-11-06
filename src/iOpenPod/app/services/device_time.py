"""Resolve captured Preferences into timezone evidence for the byte-only codecs."""

from whenever import Instant, seconds

from iPodDB.device_time import DeviceTimeContext, DeviceTimeSource
from iPodDB.preferences import (
    CityTimezone,
    ClassicClockPreferences,
    FixedOffsetTimezone,
    Nano3Preferences,
    PreferencesDocument,
)


def resolve_device_time(document: PreferencesDocument | None) -> DeviceTimeContext:
    zone = document.timezone if document is not None else None
    if isinstance(zone, CityTimezone) and zone.timezone_name is None and zone.detail:
        return DeviceTimeContext(detail=zone.detail)
    if isinstance(zone, FixedOffsetTimezone):
        return DeviceTimeContext(
            seconds(zone.offset_seconds),
            DeviceTimeSource.PREFERENCES_OFFSET,
        )
    if isinstance(zone, CityTimezone) and zone.timezone_name is not None:
        try:
            # Validate availability without asking for the Host zone or clock.
            # Store the key, not this arbitrary instant or its one-date offset.
            Instant.from_timestamp(0).to_tz(zone.timezone_name)
        except ValueError:
            return DeviceTimeContext(
                detail="The iPod city has no available timezone rules."
            )
        detail = ""
        extension = document.extended_settings if document is not None else None
        if isinstance(extension, Nano3Preferences):
            detail = "The nano 3 manual DST setting is retained separately; its interaction with city rules is not established."
        elif isinstance(extension, ClassicClockPreferences):
            detail = "Classic firmware can change the saved city during clock synchronization. Library dates use historical rules for that city; saved DST, annual firmware DST rules and clock correction do not establish past settings."
        return DeviceTimeContext(
            zone.timezone_name,
            DeviceTimeSource.PREFERENCES_CITY,
            zone.timezone_name,
            detail=detail,
        )
    return DeviceTimeContext(
        detail="Preferences do not identify a usable device timezone."
    )
