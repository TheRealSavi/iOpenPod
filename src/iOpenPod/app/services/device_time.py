"""Resolve captured Preferences into timezone evidence for the byte-only codecs."""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from iPodDB.device_time import DeviceTimeContext, DeviceTimeSource
from iPodDB.preferences import (
    CityTimezone,
    FixedOffsetTimezone,
    Nano3Preferences,
    PreferencesDocument,
)


def resolve_device_time(document: PreferencesDocument | None) -> DeviceTimeContext:
    zone = document.timezone if document is not None else None
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
        return DeviceTimeContext(
            rules,
            DeviceTimeSource.PREFERENCES_CITY,
            zone.timezone_name,
            detail=(
                "The nano 3 manual DST setting is retained separately; its interaction with city rules is not established."
                if document is not None
                and isinstance(document.extended_settings, Nano3Preferences)
                else ""
            ),
        )
    return DeviceTimeContext(
        detail="Preferences do not identify a usable device timezone."
    )
