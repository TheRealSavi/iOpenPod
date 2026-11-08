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
    return ExtrasCapabilities(support, support, support, support)


def resolve_extras_support(
    profile: DeviceProfile | None, evidence: DeviceEvidence
) -> ExtrasSupport:
    """Qualify only studied latest releases, preserving strongest-level conflicts.

    Transport revisions never substitute for RetailOS. Later MC293/MC297 SKUs
    alone cannot distinguish updater 35 from 38 (ADR-0242). Unknown evidence
    leaves optional Extras read-only and never blocks Library operations.
    """
    if profile is None:
        return ExtrasSupport(reason="Select an identified iPod to manage Extras.")
    sleep = profile.capabilities.extras.sleep_timer
    versions = {value.strip() for value in strongest_values(evidence.firmware_versions)}
    families = set(strongest_values(evidence.updater_family_ids))
    if len(versions) != 1 or len(families) > 1:
        return ExtrasSupport(
            sleep_timer=sleep,
            reason="Missing or conflicting firmware evidence leaves Extras read-only.",
        )
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
    target = formats.get(firmware) if firmware is not None else None
    if target is None:
        return ExtrasSupport(
            sleep_timer=sleep,
            reason="This model and firmware combination is not qualified for Extras editing.",
        )
    return ExtrasSupport(
        calendar_write=True,
        calendar_firmware=firmware,
        alarm_format=target,
        # Video projects its next alarm into Preferences from the separate
        # per-city Device/clock store. Patching that projection does not edit a
        # persistent Clock Alarm. See preferences-video-complete-2026-11-07.md.
        alarm_write=target is not AlarmFormat.VIDEO,
        sleep_timer=sleep,
        reason=(
            "Saved clock alarms are managed on the iPod. The displayed time is a read-only snapshot and may be disabled or out of date."
            if target is AlarmFormat.VIDEO
            else "Existing alarm time fields are editable; new alarms, sound, enable state and remote sleep-timer control are not qualified."
        ),
    )
