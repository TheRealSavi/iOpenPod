"""Native Genius policy across the catalog and firmware-dependent identification."""

import plistlib

import pytest

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    DeviceEvidence,
    DeviceIdentifier,
    EvidenceAuthority,
    FeatureSupport,
    GeniusCapabilities,
    IdentificationStatus,
    parse_sysinfo,
    parse_sysinfo_extended,
)


def _firmware(
    value: str, authority: EvidenceAuthority = EvidenceAuthority.CURRENT_HARDWARE
) -> DeviceIdentifier[str]:
    return DeviceIdentifier(value, "test RetailOS observation", authority)


def _identify(
    model: str, versions: tuple[DeviceIdentifier[str], ...] = ()
) -> GeniusCapabilities:
    result = DEFAULT_DEVICE_REGISTRY.identify(
        parse_sysinfo(f"ModelNumStr: {model}").merged_with(
            DeviceEvidence(firmware_versions=versions)
        )
    )
    assert result.status is IdentificationStatus.EXACT
    assert result.profile is not None
    assert result.candidates == (result.profile,)
    return result.profile.capabilities.genius


def test_all_marketed_variants_have_their_generations_native_genius_policy() -> None:
    supported = FeatureSupport.SUPPORTED
    unsupported = FeatureSupport.UNSUPPORTED
    expected = {
        ("iPod Classic", "6.5th Gen"): (supported, unsupported),
        ("iPod Classic", "7th Gen"): (supported, FeatureSupport.UNKNOWN),
        ("iPod Nano", "4th Gen"): (supported, unsupported),
        ("iPod Nano", "5th Gen"): (supported, supported),
        ("iPod Nano", "6th Gen"): (supported, supported),
        ("iPod Nano", "7th Gen"): (supported, supported),
    }
    seen: set[tuple[str, str]] = set()
    for profile in DEFAULT_DEVICE_REGISTRY.profiles:
        identity = profile.family, profile.generation
        seen.add(identity)
        genius = profile.capabilities.genius
        assert (genius.playlists, genius.mixes) == expected.get(
            identity, (unsupported, unsupported)
        ), profile.model_number
        assert genius.mixes_minimum_firmware == (
            (2, 0, 3) if identity == ("iPod Classic", "7th Gen") else None
        )
    assert expected.keys() <= seen


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2.0", FeatureSupport.UNSUPPORTED),
        ("2.0.2", FeatureSupport.UNSUPPORTED),
        ("2.0.3", FeatureSupport.SUPPORTED),
        ("2.0.4", FeatureSupport.SUPPORTED),
        ("2.0.5", FeatureSupport.SUPPORTED),
        ("2.0.10", FeatureSupport.SUPPORTED),
        (" 2.0.3 ", FeatureSupport.SUPPORTED),
        ("", FeatureSupport.UNKNOWN),
        ("2.0.3beta", FeatureSupport.UNKNOWN),
        ("37A40005", FeatureSupport.UNKNOWN),
        ("2.0.3.1", FeatureSupport.UNKNOWN),
        ("2.0.-1", FeatureSupport.UNKNOWN),
    ],
)
def test_classic_7_mix_boundary_uses_numeric_release_versions(
    version: str, expected: FeatureSupport
) -> None:
    genius = _identify("MC293", (_firmware(version),))
    assert genius.playlists is FeatureSupport.SUPPORTED
    assert genius.mixes is expected
    assert genius.mixes_minimum_firmware == (2, 0, 3)


def test_missing_firmware_leaves_conditional_mix_support_unknown() -> None:
    assert _identify("MC297").mixes is FeatureSupport.UNKNOWN


def test_hardware_version_overrides_stale_metadata_without_mutating_catalog() -> None:
    baseline = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MC293")
    assert baseline is not None
    genius = _identify(
        "MC293",
        (
            _firmware("2.0.2", EvidenceAuthority.DEVICE_METADATA),
            _firmware("2.0.4"),
        ),
    )
    assert genius.mixes is FeatureSupport.SUPPORTED
    assert baseline.capabilities.genius.mixes is FeatureSupport.UNKNOWN
    assert DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MC293") is baseline
    assert _identify("MC293", (_firmware("2.0.2"),)).mixes is FeatureSupport.UNSUPPORTED


@pytest.mark.parametrize("hardware", [("2.0.2", "2.0.4"), ("2.0.3", "2.0.4"), ("bad",)])
def test_conflicting_or_invalid_current_versions_do_not_fall_back(
    hardware: tuple[str, ...],
) -> None:
    versions = (
        _firmware("2.0.4", EvidenceAuthority.DEVICE_METADATA),
        *(_firmware(value) for value in hardware),
    )
    assert _identify("MC293", versions).mixes is FeatureSupport.UNKNOWN


def test_consistent_metadata_versions_can_resolve_support() -> None:
    versions = (
        _firmware("2.0.3", EvidenceAuthority.DEVICE_METADATA),
        _firmware("2.0.3", EvidenceAuthority.DEVICE_METADATA),
    )
    assert _identify("MC293", versions).mixes is FeatureSupport.SUPPORTED


@pytest.mark.parametrize("model", ["MB029", "MB565", "MB598"])
def test_a_new_version_string_cannot_enable_mixes_on_an_unsupported_model(
    model: str,
) -> None:
    assert _identify(model, (_firmware("2.0.4"),)).mixes is FeatureSupport.UNSUPPORTED


def test_transport_revision_and_internal_build_do_not_enable_classic_mixes() -> None:
    evidence = parse_sysinfo_extended(
        plistlib.dumps(
            {"ModelNumStr": "MC293", "FireWireVersion": "9.99", "BuildID": "9.0.1"}
        ),
        authority=EvidenceAuthority.CURRENT_HARDWARE,
    )
    assert evidence.firmware_versions == ()
    assert evidence.transport_revisions[0].value == "9.99"
    result = DEFAULT_DEVICE_REGISTRY.identify(evidence)
    assert result.profile is not None
    assert result.profile.capabilities.genius.mixes is FeatureSupport.UNKNOWN


def test_visible_release_wins_over_transport_revision_and_build_number() -> None:
    evidence = parse_sysinfo_extended(
        plistlib.dumps(
            {
                "ModelNumStr": "MC293",
                "VisibleBuildID": "2.0.2",
                "FireWireVersion": "1.62",
                "BuildID": "9.0.2",
            }
        ),
        authority=EvidenceAuthority.CURRENT_HARDWARE,
    )
    result = DEFAULT_DEVICE_REGISTRY.identify(evidence)
    assert result.profile is not None
    assert result.profile.capabilities.genius.mixes is FeatureSupport.UNSUPPORTED
    assert evidence.firmware_versions[0].value == "2.0.2"
    assert evidence.transport_revisions[0].value == "1.62"


def test_negative_firmware_requirement_is_invalid() -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        GeniusCapabilities(mixes_minimum_firmware=(2, 0, -1))
