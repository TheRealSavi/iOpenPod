"""Preferences identity qualification never substitutes for saved-format validation."""

import pytest

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    DeviceEvidence,
    DeviceIdentifier,
    DeviceProfile,
    EvidenceAuthority,
    FirmwareTarget,
    resolve_preferences_support,
)


def _profile(family: str, generation: str) -> DeviceProfile:
    return next(
        profile
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if (profile.family, profile.generation) == (family, generation)
    )


def _id[T](
    value: T, authority: EvidenceAuthority = EvidenceAuthority.CURRENT_HARDWARE
) -> DeviceIdentifier[T]:
    return DeviceIdentifier(value, "test observation", authority)


@pytest.mark.parametrize(
    "family,generation,release,updater,target",
    [
        ("iPod Mini", "1st Gen", "1.4.1", 3, FirmwareTarget.MINI_1_1_4_1),
        ("iPod Mini", "1st Gen", "1.4.1", 6, FirmwareTarget.MINI_1_1_4_1),
        ("iPod Mini", "2nd Gen", "1.4.1", 7, FirmwareTarget.MINI_2_1_4_1),
        ("iPod Nano", "1st Gen", "1.3.1", 14, FirmwareTarget.NANO_1_1_3_1),
        ("iPod Nano", "1st Gen", "1.3.1", 17, FirmwareTarget.NANO_1_1_3_1),
        ("iPod Nano", "3rd Gen", "1.1.3", 26, FirmwareTarget.NANO_3_1_1_3),
        ("iPod Nano", "4th Gen", "1.0.4", 31, FirmwareTarget.NANO_4_1_0_4),
        ("iPod Nano", "5th Gen", "1.0.2", 34, FirmwareTarget.NANO_5_1_0_2),
        ("iPod Nano", "6th Gen", "1.2", 36, FirmwareTarget.NANO_6_1_2),
        ("iPod Nano", "7th Gen", "1.0.4", 37, FirmwareTarget.NANO_7_1_0_4),
        ("iPod Nano", "7th Gen", "1.1.2", 39, FirmwareTarget.NANO_UPDATER_39_1_1_2),
        ("iPod", "5th Gen", "1.3", 13, FirmwareTarget.VIDEO_1_3),
        ("iPod", "5th Gen", "1.3", 20, FirmwareTarget.VIDEO_1_3),
        ("iPod", "5.5th Gen", "1.3", 25, FirmwareTarget.VIDEO_1_3),
        ("iPod Classic", "6th Gen", "1.1.2", 24, FirmwareTarget.CLASSIC_6_1_1_2),
        (
            "iPod Classic",
            "6.5th Gen",
            "2.0.1",
            33,
            FirmwareTarget.CLASSIC_120GB_2_0_1,
        ),
        (
            "iPod Classic",
            "7th Gen",
            "2.0.4",
            35,
            FirmwareTarget.CLASSIC_UPDATER_35_2_0_4,
        ),
        (
            "iPod Classic",
            "7th Gen",
            "2.0.5",
            38,
            FirmwareTarget.CLASSIC_UPDATER_38_2_0_5,
        ),
    ],
)
def test_exact_latest_targets_and_missing_updater_policy(
    family: str,
    generation: str,
    release: str,
    updater: int,
    target: FirmwareTarget,
) -> None:
    profile = _profile(family, generation)
    evidence = DeviceEvidence(
        firmware_versions=(_id(release),), updater_family_ids=(_id(updater),)
    )
    assert resolve_preferences_support(profile, evidence).target is target
    # Repeated independent observations agree; they are not peer conflicts.
    assert (
        resolve_preferences_support(profile, evidence.merged_with(evidence)).target
        is target
    )
    without_family = resolve_preferences_support(
        profile, DeviceEvidence(firmware_versions=(_id(release),))
    )
    assert without_family.target is (None if updater in (35, 37, 38, 39) else target)
    assert (
        resolve_preferences_support(
            profile,
            DeviceEvidence(
                firmware_versions=(_id(release),), updater_family_ids=(_id(999),)
            ),
        ).target
        is None
    )


def test_strongest_authority_resolves_stale_values_but_not_peer_conflicts() -> None:
    profile = _profile("iPod", "5.5th Gen")
    evidence = DeviceEvidence(
        firmware_versions=(_id("1.3"), _id("1.2", EvidenceAuthority.DEVICE_METADATA)),
        updater_family_ids=(_id(25), _id(13, EvidenceAuthority.DEVICE_METADATA)),
    )
    assert (
        resolve_preferences_support(profile, evidence).target
        is FirmwareTarget.VIDEO_1_3
    )
    for conflicting in (
        DeviceEvidence(firmware_versions=(_id("1.2"),)),
        DeviceEvidence(updater_family_ids=(_id(13),)),
    ):
        assert (
            resolve_preferences_support(
                profile, evidence.merged_with(conflicting)
            ).target
            is None
        )


@pytest.mark.parametrize("release", ["1.4", "1.3", "7.2.6.1", ""])
def test_historical_release_and_internal_build_are_not_retailos(release: str) -> None:
    assert (
        resolve_preferences_support(
            _profile("iPod Mini", "2nd Gen"),
            DeviceEvidence(
                firmware_versions=(_id(release),), updater_family_ids=(_id(7),)
            ),
        ).target
        is None
    )


def test_transport_revision_and_unstudied_generation_do_not_authorize_target() -> None:
    evidence = DeviceEvidence(transport_revisions=(_id("1.4.1"),))
    assert (
        resolve_preferences_support(_profile("iPod Mini", "2nd Gen"), evidence).target
        is None
    )
    assert (
        resolve_preferences_support(
            _profile("iPod Mini", "1st Gen"),
            DeviceEvidence(
                firmware_versions=(_id("1.4.1"),), updater_family_ids=(_id(7),)
            ),
        ).target
        is None
    )
    assert resolve_preferences_support(None, DeviceEvidence()).target is None
