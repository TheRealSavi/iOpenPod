"""HP Mini identity must retain its own model and serial conventions."""

import json
import plistlib

import pytest

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    DeviceEvidence,
    DeviceIdentifier,
    EvidenceAuthority,
    IdentificationStatus,
    UsbIdentifier,
    normalize_product_serial,
    parse_sysinfo,
    parse_sysinfo_extended,
    reconcile_device_metadata,
)
from device_registry.identifiers import normalize_model_number


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2cd5270k4j", "2CD5270K4J"),
        (" 2CD 5270K4J ", "2CD5270K4J"),
        ("8P840FN62C7", "8P840FN62C7"),
        ("ABCDEFGHIJKL", "ABCDEFGHIJKL"),
        ("4", ""),
        ("2CD5270K4", ""),
        ("2CD5270K4!", ""),
        ("000A270012345678", ""),
        ("2CD5270K4\u00e9", ""),
    ],
)
def test_product_serial_validation_preserves_hp_without_accepting_guid_or_junk(
    value: str, expected: str
) -> None:
    assert normalize_product_serial(value) == expected


@pytest.mark.parametrize(
    ("model", "canonical", "apple_model"),
    [
        ("MP5001", "MP5001", "M9800"),
        ("mp5002", "MP5002", "M9801"),
        ("PW753AA", "MP5001", "M9800"),
        ("PW753AA#ABA", "MP5001", "M9800"),
        ("PX762AA", "MP5002", "M9801"),
        ("PX762AA#ABA", "MP5002", "M9801"),
        ("xP5001", "MP5001", "M9800"),
    ],
)
def test_hp_mini_model_evidence_resolves_without_losing_capacity(
    model: str, canonical: str, apple_model: str
) -> None:
    for evidence in (
        parse_sysinfo(f"ModelNumStr: {model}\n"),
        parse_sysinfo_extended(plistlib.dumps({"ModelNumStr": model})),
    ):
        result = DEFAULT_DEVICE_REGISTRY.identify(evidence)
        assert result.status is IdentificationStatus.EXACT
        profile = result.profile
        apple = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(apple_model)
        assert profile is not None and apple is not None
        assert profile.model_number == canonical
        assert profile.family == "iPod Mini"
        assert profile.generation == "2nd Gen"
        assert profile.finish == "Silver"
        assert profile.advertised_capacity == apple.advertised_capacity
        assert profile.capabilities == apple.capabilities
        assert profile.product_image == apple.product_image


def test_hp_mini_models_do_not_collapse_or_match_incomplete_identifiers() -> None:
    assert normalize_model_number("MP5001") != normalize_model_number("MP5002")
    for value in ("MP500", "MP5003", "PW753", "PX762", "PW753AB"):
        assert DEFAULT_DEVICE_REGISTRY.profile_for_model_number(value) is None


def test_disagreeing_hp_models_remain_conflicting() -> None:
    evidence = parse_sysinfo("ModelNumStr: MP5001\n").merged_with(
        parse_sysinfo_extended(plistlib.dumps({"ModelNumStr": "PX762AA"}))
    )
    assert (
        DEFAULT_DEVICE_REGISTRY.identify(evidence).status
        is IdentificationStatus.CONFLICTING
    )


@pytest.mark.parametrize("serial", ["2CD5270K4J", "2CD5270S41", "2CD52702C7"])
def test_hp_length_serial_never_uses_an_apple_model_suffix(serial: str) -> None:
    evidence = DeviceEvidence(
        product_serials=(
            DeviceIdentifier(serial, "hardware", EvidenceAuthority.CURRENT_HARDWARE),
        ),
        usb_identifiers=(
            DeviceIdentifier(
                UsbIdentifier(0x05AC, 0x1205),
                "hardware",
                EvidenceAuthority.CURRENT_HARDWARE,
            ),
        ),
    )
    result = DEFAULT_DEVICE_REGISTRY.identify(evidence)
    assert result.status is IdentificationStatus.AMBIGUOUS
    assert result.profile is None
    result = DEFAULT_DEVICE_REGISTRY.identify(
        evidence.merged_with(parse_sysinfo("ModelNumStr: MP5001\n"))
    )
    assert result.status is IdentificationStatus.EXACT
    assert result.profile is not None
    assert result.profile.model_number == "MP5001"


def test_hp_reconciliation_preserves_serial_and_model_provenance() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MP5001")
    assert profile is not None
    evidence = parse_sysinfo_extended(
        plistlib.dumps({"ModelNumStr": "PW753AA", "SerialNumber": "2CD5270S41"}),
        source="hardware",
        authority=EvidenceAuthority.CURRENT_HARDWARE,
    )
    plan = reconcile_device_metadata(profile=profile, evidence=evidence)
    round_trip = DEFAULT_DEVICE_REGISTRY.identify(parse_sysinfo(plan.sysinfo))
    assert round_trip.profile == profile
    assert b"pszSerialNumber: 2CD5270S41\n" in plan.sysinfo
    assert json.loads(plan.authority)["fields"]["ModelNumStr"]["source"] == "hardware"


def test_hp_serial_does_not_certify_apple_model_metadata() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("M9800")
    assert profile is not None
    evidence = parse_sysinfo_extended(
        plistlib.dumps({"SerialNumber": "2CD5270S41"}),
        source="hardware",
        authority=EvidenceAuthority.CURRENT_HARDWARE,
    )
    plan = reconcile_device_metadata(profile=profile, evidence=evidence)
    assert json.loads(plan.authority)["fields"]["ModelNumStr"]["authority"] == "derived"
