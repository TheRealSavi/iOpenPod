"""Qualify the four latest Classic calendar contracts from device evidence."""

from dataclasses import dataclass

from device_registry import DeviceIdentifier, DeviceProfile
from iPodDB.preferences import DSTTableProfile, PreferencesProfile


@dataclass(frozen=True, slots=True)
class ClassicCalendarTarget:
    updater_family_id: int
    firmware_version: str
    generation: str
    capacities: tuple[str, ...]
    preferences_profile: PreferencesProfile
    dst_profile: DSTTableProfile


_TARGETS = (
    ClassicCalendarTarget(
        24,
        "1.1.2",
        "6th Gen",
        ("80GB", "160GB"),
        PreferencesProfile.CLASSIC_6_1_1_2,
        DSTTableProfile.UNKNOWN,
    ),
    ClassicCalendarTarget(
        33,
        "2.0.1",
        "6.5th Gen",
        ("120GB",),
        PreferencesProfile.CLASSIC_120GB_2_0_1,
        DSTTableProfile.CLASSIC_120GB_2_0_1,
    ),
    ClassicCalendarTarget(
        35,
        "2.0.4",
        "7th Gen",
        ("160GB",),
        PreferencesProfile.CLASSIC_UPDATER_35_2_0_4,
        DSTTableProfile.CLASSIC_UPDATER_35_2_0_4,
    ),
    ClassicCalendarTarget(
        38,
        "2.0.5",
        "7th Gen",
        ("160GB",),
        PreferencesProfile.CLASSIC_UPDATER_38_2_0_5,
        DSTTableProfile.CLASSIC_UPDATER_38_2_0_5,
    ),
)


def strongest_values[T](items: tuple[DeviceIdentifier[T], ...]) -> tuple[T, ...]:
    """A weaker saved observation cannot overrule current hardware evidence."""
    if not items:
        return ()
    authority = max(item.authority for item in items)
    return tuple(item.value for item in items if item.authority == authority)


def resolve_classic_calendar(
    profile: DeviceProfile,
    firmware_versions: tuple[str, ...],
    updater_family_ids: tuple[int, ...],
) -> ClassicCalendarTarget | None:
    """Do not choose a later 160GB branch by SKU, file size or latest-version guess."""
    if profile.family != "iPod Classic":
        return None
    versions, families = set(firmware_versions), set(updater_family_ids)
    for target in _TARGETS:
        if (
            versions == {target.firmware_version}
            and profile.generation == target.generation
            and profile.advertised_capacity in target.capacities
            and (
                families == {target.updater_family_id}
                or (not families and target.updater_family_id in (24, 33))
            )
        ):
            return target
    return None
