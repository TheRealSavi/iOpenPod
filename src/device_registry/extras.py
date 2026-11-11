"""Pure Extras qualification; never discover devices or authorize filesystem I/O.

Primary per-image evidence and remaining questions:
docs/research/calendar-alarm-firmware-2026-11-06.md. Native app availability
does not establish a safe saved format or a remote sleep-timer command.
"""

from device_registry.firmware import resolve_firmware_target, strongest_values
from device_registry.models import (
    AlarmFormat,
    DeviceEvidence,
    DeviceProfile,
    ExtrasCapabilities,
    ExtrasSupport,
    FeatureSupport,
    FirmwareTarget,
)


def native_extras_capabilities(family: str, generation: str) -> ExtrasCapabilities:
    """Catalog evidence for the researched generations; no capacity guessing."""
    known = (
        (family == "iPod Mini" and generation == "2nd Gen")
        or (family == "iPod" and generation in {"5th Gen", "5.5th Gen"})
        or (
            family == "iPod Classic"
            and generation in {"6th Gen", "6.5th Gen", "7th Gen"}
        )
    )
    support = FeatureSupport.SUPPORTED if known else FeatureSupport.UNKNOWN
    # Nano 2 follows the shared Calendar policy by product decision.
    if (
        family == "iPod Nano"
        and generation in {"1st Gen", "2nd Gen", "3rd Gen", "4th Gen", "5th Gen"}
    ) or (family == "iPod Mini" and generation == "1st Gen"):
        return ExtrasCapabilities(
            calendar=FeatureSupport.SUPPORTED, todos=FeatureSupport.SUPPORTED
        )
    if family == "iPod Nano" and generation in {"6th Gen", "7th Gen"}:
        return ExtrasCapabilities(
            calendar=FeatureSupport.UNSUPPORTED, todos=FeatureSupport.UNSUPPORTED
        )
    return ExtrasCapabilities(support, support, support, support)


def resolve_extras_support(
    profile: DeviceProfile | None, evidence: DeviceEvidence
) -> ExtrasSupport:
    """Resolve Calendar from the model and Clock Alarms from ranked evidence."""
    if profile is None:
        return ExtrasSupport(reason="Select an identified iPod to manage Extras.")
    capabilities = profile.capabilities.extras
    calendar = capabilities.calendar is FeatureSupport.SUPPORTED
    sleep = capabilities.sleep_timer
    firmware = resolve_firmware_target(
        profile,
        strongest_values(evidence.firmware_versions),
        strongest_values(evidence.updater_family_ids),
    )
    # This explicit subset is independent of Preferences authoring support.
    formats = {
        FirmwareTarget.MINI_2_1_4_1: AlarmFormat.MINI,
        FirmwareTarget.VIDEO_1_3: AlarmFormat.VIDEO,
        FirmwareTarget.CLASSIC_6_1_1_2: AlarmFormat.CLASSIC,
        FirmwareTarget.CLASSIC_120GB_2_0_1: AlarmFormat.CLASSIC,
        FirmwareTarget.CLASSIC_UPDATER_35_2_0_4: AlarmFormat.CLASSIC,
        FirmwareTarget.CLASSIC_UPDATER_38_2_0_5: AlarmFormat.CLASSIC,
    }
    target = (
        formats.get(firmware, AlarmFormat.NONE)
        if firmware is not None
        else AlarmFormat.NONE
    )
    return ExtrasSupport(
        calendar_write=calendar,
        alarm_format=target,
        alarm_firmware=firmware if target is not AlarmFormat.NONE else None,
        # Video projects its next alarm into Preferences from the separate
        # per-city Device/clock store. Patching that projection does not edit a
        # persistent Clock Alarm. See preferences-video-complete-2026-11-07.md.
        alarm_write=target in {AlarmFormat.MINI, AlarmFormat.CLASSIC},
        sleep_timer=sleep,
        reason=(
            "Saved clock alarms are managed on the iPod. The displayed time is a read-only snapshot and may be disabled or out of date."
            if target is AlarmFormat.VIDEO
            else "Clock Alarm editing is unavailable for this iPod."
            if target is AlarmFormat.NONE
            else "Existing alarm time fields are editable; new alarms, sound, enable state and remote sleep-timer control are not qualified."
        ),
    )
