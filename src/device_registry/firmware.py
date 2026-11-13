"""Studied RetailOS identities, independent of file formats and edit permission.

The same model/release/updater qualification serves Preferences, Extras and
captured clock evidence. Consumers keep separate capability allowlists; a new
studied firmware target never implicitly enables another workflow.
"""

from device_registry.models import DeviceIdentifier, DeviceProfile, FirmwareTarget


def strongest_values[T](items: tuple[DeviceIdentifier[T], ...]) -> tuple[T, ...]:
    """Retain all equally authoritative observations, including conflicts."""
    if not items:
        return ()
    authority = max(item.authority for item in items)
    return tuple(item.value for item in items if item.authority == authority)


def resolve_firmware_target(
    profile: DeviceProfile,
    firmware_versions: tuple[str, ...],
    updater_family_ids: tuple[int, ...],
) -> FirmwareTarget | None:
    """Match already-ranked evidence without guessing through conflicts.

    Callers with Device Evidence first select strongest_values for each kind.
    Transport revisions never substitute for RetailOS. Later Classic and Nano
    7 releases require an updater family; earlier targets still reject a
    contradictory family when one is observed.
    """
    versions = {value.strip() for value in firmware_versions}
    families = set(updater_family_ids)
    if len(versions) != 1 or len(families) > 1:
        return None
    identity = (profile.family, profile.generation, next(iter(versions)))
    targets = {
        ("iPod Mini", "1st Gen", "1.4.1"): (FirmwareTarget.MINI_1_1_4_1, {3, 6}),
        ("iPod Mini", "2nd Gen", "1.4.1"): (FirmwareTarget.MINI_2_1_4_1, {7}),
        ("iPod Nano", "1st Gen", "1.3.1"): (FirmwareTarget.NANO_1_1_3_1, {14, 17}),
        ("iPod Nano", "2nd Gen", "1.1.3"): (FirmwareTarget.NANO_2_1_1_3, {19, 29}),
        ("iPod Nano", "3rd Gen", "1.1.3"): (FirmwareTarget.NANO_3_1_1_3, {26}),
        ("iPod Nano", "4th Gen", "1.0.4"): (FirmwareTarget.NANO_4_1_0_4, {31}),
        ("iPod Nano", "5th Gen", "1.0.2"): (FirmwareTarget.NANO_5_1_0_2, {34}),
        ("iPod Nano", "6th Gen", "1.2"): (FirmwareTarget.NANO_6_1_2, {36}),
        ("iPod Nano", "7th Gen", "1.0.4"): (FirmwareTarget.NANO_7_1_0_4, {37}),
        ("iPod Nano", "7th Gen", "1.1.2"): (
            FirmwareTarget.NANO_UPDATER_39_1_1_2,
            {39},
        ),
        ("iPod", "5th Gen", "1.3"): (FirmwareTarget.VIDEO_1_3, {13, 20}),
        ("iPod", "5.5th Gen", "1.3"): (FirmwareTarget.VIDEO_1_3, {25}),
        ("iPod Classic", "6th Gen", "1.1.2"): (
            FirmwareTarget.CLASSIC_6_1_1_2,
            {24},
        ),
        ("iPod Classic", "6.5th Gen", "2.0.1"): (
            FirmwareTarget.CLASSIC_120GB_2_0_1,
            {33},
        ),
        ("iPod Classic", "7th Gen", "2.0.4"): (
            FirmwareTarget.CLASSIC_UPDATER_35_2_0_4,
            {35},
        ),
        ("iPod Classic", "7th Gen", "2.0.5"): (
            FirmwareTarget.CLASSIC_UPDATER_38_2_0_5,
            {38},
        ),
    }
    candidate = targets.get(identity)
    if candidate is not None:
        target, expected = candidate
        family_required = target in {
            FirmwareTarget.CLASSIC_UPDATER_35_2_0_4,
            FirmwareTarget.CLASSIC_UPDATER_38_2_0_5,
            FirmwareTarget.NANO_7_1_0_4,
            FirmwareTarget.NANO_UPDATER_39_1_1_2,
        }
        if not (family_required and not families) and (
            not families or families <= expected
        ):
            return target
    return None
