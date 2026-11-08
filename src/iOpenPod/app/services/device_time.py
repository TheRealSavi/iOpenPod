"""Resolve captured Preferences into timezone evidence for the byte-only codecs."""

from whenever import Instant, seconds

from iPodDB.device_time import DeviceTimeContext, DeviceTimeSource
from iPodDB.preferences import (
    CityTimezone,
    ClassicClockPreferences,
    FixedOffsetTimezone,
    NamedClockEvidence,
    Nano3Preferences,
    PreferencesDocument,
)


def resolve_device_time(document: PreferencesDocument | None) -> DeviceTimeContext:
    if document is not None and document.reset_requested:
        return DeviceTimeContext(
            detail="The saved Preferences request a reset. Their clock settings may be discarded; dates use the database offset or a UTC estimate."
        )
    zone = document.timezone if document is not None else None
    if document is not None and document.has_video13_framing:
        return DeviceTimeContext(
            detail="Video 1.3 saved settings do not identify a verified timezone."
        )
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


def resolve_named_device_time(evidence: NamedClockEvidence) -> DeviceTimeContext:
    """Apply qualified Nano city evidence as Host interpretation policy.

    A packaged base offset is not a captured effective offset. Neither it nor
    saved bias/DST is added to dates, which already encode the device calendar.
    The context is shared by reading and authoring; it does not set the clock.
    """
    detail = " ".join(evidence.issues)
    zone = evidence.iana_timezone
    if zone is None:
        return DeviceTimeContext(
            detail=detail
            or "The Nano clock setting has no qualified timezone interpretation."
        )
    try:
        Instant.from_timestamp(0).to_tz(zone)
    except ValueError:
        return DeviceTimeContext(
            detail="The Nano clock setting names unavailable timezone rules. " + detail
        )
    profile = evidence.profile.value if evidence.profile is not None else "unknown"
    policy = (
        f"Captured {profile} city {evidence.city_id} ({evidence.city_label}). "
        "Library dates use Host timezone rules for this qualified city mapping. "
        "These rules are an estimate: firmware rules, overrides, earlier city selections and manual clock changes may differ. "
        "Saved base offsets, DST and clock correction are not added again."
    )
    return DeviceTimeContext(
        zone,
        DeviceTimeSource.PREFERENCES_CITY,
        zone,
        detail=policy + (" " + detail if detail else ""),
    )
