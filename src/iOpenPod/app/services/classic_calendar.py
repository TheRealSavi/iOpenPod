"""Qualify the four latest Classic calendar contracts from device evidence."""

from dataclasses import dataclass

from device_registry import DeviceProfile, FirmwareTarget, resolve_firmware_target
from iPodDB.preferences import DSTTableProfile, PreferencesProfile


@dataclass(frozen=True, slots=True)
class ClassicCalendarTarget:
    capacities: tuple[str, ...]
    preferences_profile: PreferencesProfile
    dst_profile: DSTTableProfile


_TARGETS = {
    FirmwareTarget.CLASSIC_6_1_1_2: ClassicCalendarTarget(
        ("80GB", "160GB"),
        PreferencesProfile.CLASSIC_6_1_1_2,
        DSTTableProfile.UNKNOWN,
    ),
    FirmwareTarget.CLASSIC_120GB_2_0_1: ClassicCalendarTarget(
        ("120GB",),
        PreferencesProfile.CLASSIC_120GB_2_0_1,
        DSTTableProfile.CLASSIC_120GB_2_0_1,
    ),
    FirmwareTarget.CLASSIC_UPDATER_35_2_0_4: ClassicCalendarTarget(
        ("160GB",),
        PreferencesProfile.CLASSIC_UPDATER_35_2_0_4,
        DSTTableProfile.CLASSIC_UPDATER_35_2_0_4,
    ),
    FirmwareTarget.CLASSIC_UPDATER_38_2_0_5: ClassicCalendarTarget(
        ("160GB",),
        PreferencesProfile.CLASSIC_UPDATER_38_2_0_5,
        DSTTableProfile.CLASSIC_UPDATER_38_2_0_5,
    ),
}


def resolve_classic_calendar(
    profile: DeviceProfile,
    firmware_versions: tuple[str, ...],
    updater_family_ids: tuple[int, ...],
) -> ClassicCalendarTarget | None:
    """Compose qualified identity with clock codecs; never infer an identity here."""
    firmware = resolve_firmware_target(profile, firmware_versions, updater_family_ids)
    target = _TARGETS.get(firmware) if firmware is not None else None
    if target is None or profile.advertised_capacity not in target.capacities:
        return None
    return target
