"""Resolve captured Preferences into timezone evidence for the byte-only codecs."""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from iPodDB.device_time import DeviceTimeContext, DeviceTimeSource
from iPodDB.preferences import (
    CityTimezone,
    Classic201ClockPreferences,
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
            timezone(timedelta(seconds=zone.offset_seconds)),
            DeviceTimeSource.PREFERENCES_OFFSET,
        )
    if isinstance(zone, CityTimezone) and zone.timezone_name is not None:
        try:
            rules = ZoneInfo(zone.timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            return DeviceTimeContext(
                detail="The iPod city has no available timezone rules."
            )
        detail = ""
        extension = document.extended_settings if document is not None else None
        if isinstance(extension, Nano3Preferences):
            detail = "The nano 3 manual DST setting is retained separately; its interaction with city rules is not established."
        elif isinstance(extension, Classic201ClockPreferences):
            detail = "Classic 2.0.1 has firmware DST rules and a manual switch. Library dates use historical rules for the saved city; saved DST and clock correction do not establish past settings."
        return DeviceTimeContext(
            rules,
            DeviceTimeSource.PREFERENCES_CITY,
            zone.timezone_name,
            detail=detail,
        )
    return DeviceTimeContext(
        detail="Preferences do not identify a usable device timezone."
    )
