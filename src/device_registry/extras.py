"""Pure Extras qualification; never discover devices or authorize filesystem I/O.

Primary per-image evidence and remaining questions:
docs/alarms.md and its per-family firmware reports. Native app availability
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
        (family == "iPod Mini" and generation in {"1st Gen", "2nd Gen"})
        or (family == "iPod" and generation in {"5th Gen", "5.5th Gen"})
        or (
            family == "iPod Nano"
            and generation in {"1st Gen", "2nd Gen", "3rd Gen", "4th Gen", "5th Gen"}
        )
        or (
            family == "iPod Classic"
            and generation in {"6th Gen", "6.5th Gen", "7th Gen"}
        )
    )
    support = FeatureSupport.SUPPORTED if known else FeatureSupport.UNKNOWN
    if family == "iPod Nano" and generation in {"6th Gen", "7th Gen"}:
        return ExtrasCapabilities(
            calendar=FeatureSupport.UNSUPPORTED,
            todos=FeatureSupport.UNSUPPORTED,
            alarms=FeatureSupport.UNSUPPORTED,
            sleep_timer=FeatureSupport.SUPPORTED,
            custom_tones=FeatureSupport.UNSUPPORTED,
        )
    tones = (
        family == "iPod Classic" and generation in {"6th Gen", "6.5th Gen", "7th Gen"}
    ) or (family == "iPod Nano" and generation in {"3rd Gen", "4th Gen", "5th Gen"})
    return ExtrasCapabilities(
        support,
        support,
        support,
        support,
        FeatureSupport.SUPPORTED
        if tones
        else FeatureSupport.UNSUPPORTED
        if known
        else FeatureSupport.UNKNOWN,
    )


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
    # Nano 2 uses Nano 1 behavior by user-directed compatibility policy, not
    # decrypted firmware evidence (ADR-0261). The clock codec still checks framing.
    formats = {
        FirmwareTarget.MINI_1_1_4_1: AlarmFormat.MINI_1,
        FirmwareTarget.MINI_2_1_4_1: AlarmFormat.MINI,
        FirmwareTarget.VIDEO_1_3: AlarmFormat.CLOCK,
        FirmwareTarget.NANO_1_1_3_1: AlarmFormat.CLOCK,
        FirmwareTarget.NANO_2_1_1_3: AlarmFormat.CLOCK,
        FirmwareTarget.NANO_3_1_1_3: AlarmFormat.CLASSIC,
        FirmwareTarget.NANO_4_1_0_4: AlarmFormat.CLASSIC,
        FirmwareTarget.NANO_5_1_0_2: AlarmFormat.CLASSIC,
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
        alarm_write=target
        in {
            AlarmFormat.MINI,
            AlarmFormat.MINI_1,
            AlarmFormat.CLASSIC,
            AlarmFormat.CLOCK,
        },
        sleep_timer=sleep,
        reason=(
            "Clock Alarm editing is unavailable for this iPod."
            if target is AlarmFormat.NONE
            else "Saved alarms use Nano 1 compatibility behavior for this iPod."
            if firmware is FirmwareTarget.NANO_2_1_1_3
            else "Saved alarm editing is supported for this firmware."
        ),
    )
