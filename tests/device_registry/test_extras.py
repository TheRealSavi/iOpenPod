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
    FirmwareTarget,
    resolve_extras_support,
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
    "family,generation,firmware,updater,format",
    (
        ("iPod Mini", "2nd Gen", "1.4.1", 7, AlarmFormat.MINI),
        ("iPod Mini", "1st Gen", "1.4.1", 3, AlarmFormat.MINI_1),
        ("iPod Mini", "1st Gen", "1.4.1", 6, AlarmFormat.MINI_1),
        ("iPod Nano", "1st Gen", "1.3.1", 14, AlarmFormat.CLOCK),
        ("iPod Nano", "1st Gen", "1.3.1", 17, AlarmFormat.CLOCK),
        ("iPod Nano", "3rd Gen", "1.1.3", 26, AlarmFormat.CLASSIC),
        ("iPod Nano", "4th Gen", "1.0.4", 31, AlarmFormat.CLASSIC),
        ("iPod Nano", "5th Gen", "1.0.2", 34, AlarmFormat.CLASSIC),
        ("iPod", "5th Gen", "1.3", 13, AlarmFormat.CLOCK),
        ("iPod", "5th Gen", "1.3", 20, AlarmFormat.CLOCK),
        ("iPod", "5.5th Gen", "1.3", 25, AlarmFormat.CLOCK),
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
    assert support.alarm_write
    assert support.sleep_timer is FeatureSupport.SUPPORTED
    assert not support.sleep_timer_write
    without_family = resolve_extras_support(
        profile, DeviceEvidence(firmware_versions=(_id(firmware),))
    )
    assert without_family.alarm_write == (updater not in (35, 38))


def test_missing_versions_only_gate_alarm_writes() -> None:
    profile = _profile("iPod Classic", "6.5th Gen")
    support = resolve_extras_support(
        profile,
        DeviceEvidence(
            transport_revisions=(_id("2.0.1"),), updater_family_ids=(_id(33),)
        ),
    )
    assert support.calendar_write and not support.alarm_write
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


def test_unidentified_device_cannot_write_extras() -> None:
    support = resolve_extras_support(None, DeviceEvidence())
    assert not support.calendar_write and not support.alarm_write


@pytest.mark.parametrize("updater", (19, 29))
def test_nano_2_uses_explicit_clock_compatibility_without_preferences_support(
    updater: int,
) -> None:
    profile = _profile("iPod Nano", "2nd Gen")
    evidence = DeviceEvidence(
        firmware_versions=(_id("1.1.3"),), updater_family_ids=(_id(updater),)
    )
    support = resolve_extras_support(profile, evidence)
    assert profile.capabilities.extras.calendar is FeatureSupport.SUPPORTED
    assert support.calendar_write and support.alarm_write
    assert support.alarm_format is AlarmFormat.CLOCK
    assert support.alarm_firmware is FirmwareTarget.NANO_2_1_1_3
    assert "compatibility" in support.reason
    assert resolve_preferences_support(profile, evidence).target is None
    assert not support.sleep_timer_write


@pytest.mark.parametrize(
    "versions,families",
    (((), (19,)), (("1.1.2",), (19,)), (("1.1.3",), (14,)), (("1.1.3",), (19, 29))),
)
def test_nano_2_compatibility_still_requires_matching_identity(
    versions: tuple[str, ...], families: tuple[int, ...]
) -> None:
    support = resolve_extras_support(
        _profile("iPod Nano", "2nd Gen"),
        DeviceEvidence(
            firmware_versions=tuple(_id(value) for value in versions),
            updater_family_ids=tuple(_id(value) for value in families),
        ),
    )
    assert support.alarm_format is AlarmFormat.NONE and not support.alarm_write


@pytest.mark.parametrize(
    "generation,firmware,updater",
    (("6th Gen", "1.2", 36), ("7th Gen", "1.0.4", 37), ("7th Gen", "1.1.2", 39)),
)
def test_touch_nano_has_no_qualified_alarm_format(
    generation: str, firmware: str, updater: int
) -> None:
    support = resolve_extras_support(
        _profile("iPod Nano", generation),
        DeviceEvidence(
            firmware_versions=(_id(firmware),), updater_family_ids=(_id(updater),)
        ),
    )
    assert not support.calendar_write
    assert not support.alarm_write
    assert support.alarm_format is AlarmFormat.NONE
    assert support.alarm_firmware is None
    assert support.sleep_timer is FeatureSupport.SUPPORTED
    assert not support.sleep_timer_write


@pytest.mark.parametrize(
    "family,generation",
    (
        ("iPod Mini", "1st Gen"),
        ("iPod Mini", "2nd Gen"),
        ("iPod Nano", "1st Gen"),
        ("iPod Nano", "2nd Gen"),
        ("iPod Nano", "3rd Gen"),
        ("iPod Nano", "4th Gen"),
        ("iPod Nano", "5th Gen"),
        ("iPod", "5th Gen"),
        ("iPod", "5.5th Gen"),
        ("iPod Classic", "6th Gen"),
        ("iPod Classic", "6.5th Gen"),
        ("iPod Classic", "7th Gen"),
    ),
)
def test_calendar_availability_does_not_depend_on_firmware_evidence(
    family: str, generation: str
) -> None:
    profile = _profile(family, generation)
    for evidence in (
        DeviceEvidence(),
        DeviceEvidence(
            firmware_versions=(_id("1.0"), _id("2.0")),
            updater_family_ids=(_id(24), _id(33)),
        ),
    ):
        support = resolve_extras_support(profile, evidence)
        assert support.calendar_write
        assert support.alarm_format is AlarmFormat.NONE
        assert not support.alarm_write and not support.sleep_timer_write
