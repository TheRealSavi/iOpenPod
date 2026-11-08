"""Native Extras availability is separate from exact firmware write qualification."""

import pytest

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    AlarmFormat,
    DeviceEvidence,
    DeviceIdentifier,
    DeviceProfile,
    EvidenceAuthority,
    FeatureSupport,
    resolve_extras_support,
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
    "family,generation,firmware,updater,format",
    (
        ("iPod Mini", "2nd Gen", "1.4.1", 7, AlarmFormat.MINI),
        ("iPod", "5th Gen", "1.3", 13, AlarmFormat.VIDEO),
        ("iPod", "5th Gen", "1.3", 20, AlarmFormat.VIDEO),
        ("iPod", "5.5th Gen", "1.3", 25, AlarmFormat.VIDEO),
        ("iPod Classic", "6th Gen", "1.1.2", 24, AlarmFormat.CLASSIC),
        ("iPod Classic", "6.5th Gen", "2.0.1", 33, AlarmFormat.CLASSIC),
        ("iPod Classic", "7th Gen", "2.0.4", 35, AlarmFormat.CLASSIC),
        ("iPod Classic", "7th Gen", "2.0.5", 38, AlarmFormat.CLASSIC),
    ),
)
def test_each_latest_target_qualifies_independently_without_enabling_sleep_control(
    family: str, generation: str, firmware: str, updater: int, format: AlarmFormat
) -> None:
    profile = _profile(family, generation)
    native = profile.capabilities.extras
    assert (
        native.calendar
        is native.todos
        is native.alarms
        is native.sleep_timer
        is FeatureSupport.SUPPORTED
    )
    evidence = DeviceEvidence(
        firmware_versions=(_id(firmware),), updater_family_ids=(_id(updater),)
    )
    support = resolve_extras_support(profile, evidence)
    assert support.calendar_write and support.alarm_format is format
    assert support.alarm_write is (format is not AlarmFormat.VIDEO)
    assert support.sleep_timer is FeatureSupport.SUPPORTED
    assert not support.sleep_timer_write
    without_family = resolve_extras_support(
        profile, DeviceEvidence(firmware_versions=(_id(firmware),))
    )
    assert without_family.alarm_write == (
        updater not in (35, 38) and format is not AlarmFormat.VIDEO
    )


def test_missing_versions_do_not_turn_native_support_into_write_permission() -> None:
    profile = _profile("iPod Classic", "6.5th Gen")
    support = resolve_extras_support(
        profile,
        DeviceEvidence(
            transport_revisions=(_id("2.0.1"),), updater_family_ids=(_id(33),)
        ),
    )
    assert not support.calendar_write and not support.alarm_write
    assert support.alarm_format is AlarmFormat.NONE
    assert profile.capabilities.extras.alarms is FeatureSupport.SUPPORTED


def test_strongest_evidence_ignores_stale_cache_but_keeps_equal_rank_conflicts() -> (
    None
):
    profile = _profile("iPod Classic", "6.5th Gen")
    evidence = DeviceEvidence(
        firmware_versions=(
            _id("2.0.1"),
            _id("1.62", EvidenceAuthority.DEVICE_METADATA),
        ),
        updater_family_ids=(_id(33), _id(24, EvidenceAuthority.DEVICE_METADATA)),
    )
    assert resolve_extras_support(profile, evidence).alarm_write
    for conflict in (
        DeviceEvidence(firmware_versions=(_id("2.0.5"),)),
        DeviceEvidence(updater_family_ids=(_id(35),)),
    ):
        assert not resolve_extras_support(
            profile, evidence.merged_with(conflict)
        ).alarm_write


def test_wrong_family_or_historical_release_does_not_qualify() -> None:
    for firmware, updater in (("2.0.1", 35), ("2.0.0", 33), ("37A40005", 33)):
        evidence = DeviceEvidence(
            firmware_versions=(_id(firmware),), updater_family_ids=(_id(updater),)
        )
        assert not resolve_extras_support(
            _profile("iPod Classic", "6.5th Gen"), evidence
        ).alarm_write


def test_unstudied_generation_remains_unknown_and_unidentified_device_cannot_write() -> (
    None
):
    profile = _profile("iPod Nano", "5th Gen")
    assert profile.capabilities.extras.calendar is FeatureSupport.UNKNOWN
    assert not resolve_extras_support(
        profile, DeviceEvidence(firmware_versions=(_id("1.3"),))
    ).calendar_write
    assert not resolve_extras_support(None, DeviceEvidence()).alarm_write
