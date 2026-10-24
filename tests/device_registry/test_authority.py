"""Pure tests for iOpenPod SysInfo authority reconciliation."""

import hashlib
import json
import plistlib

import pytest

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    DeviceEvidence,
    DeviceIdentifier,
    EvidenceAuthority,
    UsbIdentifier,
    authority_covers_metadata,
    parse_sysinfo_extended,
    reconcile_device_metadata,
)


def _classic_7_hardware() -> DeviceEvidence:
    return parse_sysinfo_extended(
        plistlib.dumps(
            {
                "ModelNumStr": "MC293",
                "SerialNumber": "TESTSERIAL7G",
                "FireWireGUID": "000A270012345678",
            }
        ),
        authority=EvidenceAuthority.CURRENT_HARDWARE,
    )


def test_reconciliation_does_not_copy_retailos_into_firewire_version() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    live = plistlib.dumps(
        {"VisibleBuildID": "2.0.1", "FireWireVersion": "1.62", "BuildID": "9.0.1"}
    )
    evidence = parse_sysinfo_extended(
        live, authority=EvidenceAuthority.CURRENT_HARDWARE
    )
    plan = reconcile_device_metadata(
        profile=profile,
        evidence=evidence,
        live_sysinfo_extended=live,
        existing_sysinfo=b"visibleBuildID: 1.62\n",
    )
    extended = plistlib.loads(plan.sysinfo_extended)
    assert extended["VisibleBuildID"] == "2.0.1"
    assert extended["FireWireVersion"] == "1.62"
    assert extended["BuildID"] == "9.0.1"
    assert b"visibleBuildID: 2.0.1\n" in plan.sysinfo
    assert b"FireWireVersion: 1.62\n" in plan.sysinfo
    assert (
        parse_sysinfo_extended(plan.sysinfo_extended).firmware_versions[0].value
        == "2.0.1"
    )


def test_transport_revision_retains_live_payload_provenance() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    live = plistlib.dumps({"FireWireVersion": "1.62"})
    plan = reconcile_device_metadata(
        profile=profile,
        evidence=parse_sysinfo_extended(
            live,
            source="windows_scsi",
            authority=EvidenceAuthority.CURRENT_HARDWARE,
        ),
        live_sysinfo_extended=live,
    )
    authority = json.loads(plan.authority)
    assert authority["files"]["SysInfoExtended"]["source"] == "windows_scsi"
    assert authority["fields"]["FireWireVersion"]["source"] == "windows_scsi"
    assert "visibleBuildID" not in authority["fields"]


@pytest.mark.parametrize(
    ("release", "release_authority", "extended_release", "covered"),
    [
        (None, EvidenceAuthority.CURRENT_HARDWARE, None, False),
        ("2.0.4", EvidenceAuthority.DEVICE_METADATA, "2.0.4", False),
        ("1.62", EvidenceAuthority.CURRENT_HARDWARE, None, False),
        ("1.62", EvidenceAuthority.CURRENT_HARDWARE, "2.0.4", False),
        ("2.0.2", EvidenceAuthority.CURRENT_HARDWARE, "2.0.2", True),
        ("2.0.4", EvidenceAuthority.CURRENT_HARDWARE, "2.0.4", True),
    ],
)
def test_firmware_cache_requires_hardware_provenance_and_consistent_files(
    release: str | None,
    release_authority: EvidenceAuthority,
    extended_release: str | None,
    covered: bool,
) -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MC293")
    assert profile is not None
    versions = (
        ()
        if release is None
        else (DeviceIdentifier(release, "test", release_authority),)
    )
    plan = reconcile_device_metadata(
        profile=profile,
        evidence=_classic_7_hardware().merged_with(
            DeviceEvidence(firmware_versions=versions)
        ),
    )
    extended = plistlib.loads(plan.sysinfo_extended)
    if extended_release is None:
        extended.pop("VisibleBuildID", None)
    else:
        extended["VisibleBuildID"] = extended_release
    extended_bytes = plistlib.dumps(extended)
    authority = json.loads(plan.authority)
    # Model a legacy cache with matching hashes, not an external modification.
    authority["file_hashes"]["SysInfoExtended"] = hashlib.sha256(
        extended_bytes
    ).hexdigest()
    authority_bytes = json.dumps(authority)

    assert authority_covers_metadata(
        authority_bytes, sysinfo=plan.sysinfo, sysinfo_extended=extended_bytes
    )
    assert (
        authority_covers_metadata(
            authority_bytes,
            sysinfo=plan.sysinfo,
            sysinfo_extended=extended_bytes,
            require_firmware_version=True,
        )
        is covered
    )


def test_rewriting_a_legacy_cache_does_not_validate_its_firmware_version() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MC293")
    assert profile is not None
    plan = reconcile_device_metadata(
        profile=profile,
        evidence=_classic_7_hardware().merged_with(
            DeviceEvidence(
                firmware_versions=(
                    DeviceIdentifier(
                        "1.62", "iokit", EvidenceAuthority.CURRENT_HARDWARE
                    ),
                )
            )
        ),
    )
    legacy_authority = json.loads(plan.authority)
    legacy_authority["fields"]["visibleBuildID"].pop("value_kind")
    cached_only = reconcile_device_metadata(
        profile=profile,
        evidence=parse_sysinfo_extended(plan.sysinfo_extended),
        existing_sysinfo=plan.sysinfo,
        existing_sysinfo_extended=plan.sysinfo_extended,
        existing_authority=json.dumps(legacy_authority).encode(),
    )
    assert not authority_covers_metadata(
        cached_only.authority,
        sysinfo=cached_only.sysinfo,
        sysinfo_extended=cached_only.sysinfo_extended,
        require_firmware_version=True,
    )


def test_reconciliation_builds_original_compatible_metadata_and_authority() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    evidence = DeviceEvidence(
        product_serials=(
            DeviceIdentifier(
                "8P840FN62C7",
                "windows_scsi",
                EvidenceAuthority.CURRENT_HARDWARE,
            ),
        ),
        transport_serials=(
            DeviceIdentifier(
                "000A270012345678",
                "windows_scsi",
                EvidenceAuthority.CURRENT_HARDWARE,
            ),
        ),
        usb_identifiers=(
            DeviceIdentifier(
                UsbIdentifier(0x05AC, 0x1261),
                "windows hardware",
                EvidenceAuthority.CURRENT_HARDWARE,
            ),
        ),
        firmware_versions=(
            DeviceIdentifier(
                "2.0.1",
                "windows_scsi",
                EvidenceAuthority.CURRENT_HARDWARE,
            ),
        ),
    )

    plan = reconcile_device_metadata(
        evidence=evidence,
        profile=profile,
        existing_sysinfo=b"CustomKey: keep-me\nModelNumStr: xA123\n",
        existing_sysinfo_extended=b"",
        existing_authority=b"",
        observed_at="2026-08-29T12:00:00+00:00",
    )

    sysinfo = plan.sysinfo.decode("utf-8")
    assert "CustomKey: keep-me\n" in sysinfo
    assert "pszSerialNumber: 8P840FN62C7\n" in sysinfo
    assert "FirewireGuid: 0x000A270012345678\n" in sysinfo
    assert "ModelNumStr: xB565\n" in sysinfo
    assert "ModelFamily: iPod Classic\n" in sysinfo
    assert "Generation: 6.5th Gen\n" in sysinfo
    assert "Capacity: 120GB\n" in sysinfo
    assert "Color: Black\n" in sysinfo
    assert "USBProductID: 0x1261\n" in sysinfo

    extended = plistlib.loads(plan.sysinfo_extended)
    assert extended["SerialNumber"] == "8P840FN62C7"
    assert extended["FireWireGUID"] == "000A270012345678"
    assert extended["ModelNumStr"] == "MB565"
    assert extended["VisibleBuildID"] == "2.0.1"
    assert "FireWireVersion" not in extended
    assert extended["usb_vid"] == 0x05AC
    assert extended["usb_pid"] == 0x1261

    authority = json.loads(plan.authority)
    assert authority["version"] == 1
    assert authority["fields"]["pszSerialNumber"]["source"] == "windows_scsi"
    assert set(authority["file_hashes"]) == {"SysInfo", "SysInfoExtended"}
    assert authority_covers_metadata(
        plan.authority,
        sysinfo=plan.sysinfo,
        sysinfo_extended=plan.sysinfo_extended,
        require_firmware_version=True,
    )
    authority["file_hashes"].pop("SysInfoExtended")
    assert not authority_covers_metadata(
        json.dumps(authority),
        sysinfo=plan.sysinfo,
        sysinfo_extended=plan.sysinfo_extended,
        require_firmware_version=True,
    )


def test_reconciliation_is_stable_and_detects_external_modification() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    evidence = DeviceEvidence(
        product_serials=(
            DeviceIdentifier(
                "8P840FN62C7",
                "udev_scsi_id",
                EvidenceAuthority.CURRENT_HARDWARE,
            ),
        ),
    )
    first = reconcile_device_metadata(
        evidence=evidence,
        profile=profile,
        observed_at="2026-08-29T12:00:00+00:00",
    )

    second = reconcile_device_metadata(
        evidence=evidence,
        profile=profile,
        existing_sysinfo=first.sysinfo,
        existing_sysinfo_extended=first.sysinfo_extended,
        existing_authority=first.authority,
        observed_at="2026-08-29T13:00:00+00:00",
    )

    assert not second.sysinfo_changed
    assert not second.sysinfo_extended_changed
    assert not second.authority_changed
    assert second.authority == first.authority
    assert not authority_covers_metadata(
        first.authority,
        sysinfo=first.sysinfo + b"tampered",
        sysinfo_extended=first.sysinfo_extended,
    )


def test_reconciliation_does_not_downgrade_matching_hardware_provenance() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    hardware = DeviceEvidence(
        product_serials=(
            DeviceIdentifier(
                "8P840FN62C7",
                "windows_scsi",
                EvidenceAuthority.CURRENT_HARDWARE,
            ),
        ),
        transport_serials=(
            DeviceIdentifier(
                "000A270012345678",
                "windows_scsi",
                EvidenceAuthority.CURRENT_HARDWARE,
            ),
        ),
    )
    first = reconcile_device_metadata(
        evidence=hardware,
        profile=profile,
        observed_at="2026-08-29T12:00:00+00:00",
    )
    metadata_only = DeviceEvidence(
        product_serials=(
            DeviceIdentifier(
                "8P840FN62C7",
                "SysInfo",
                EvidenceAuthority.DEVICE_METADATA,
            ),
        ),
        transport_serials=(
            DeviceIdentifier(
                "000A270012345678",
                "SysInfo",
                EvidenceAuthority.DEVICE_METADATA,
            ),
        ),
        model_numbers=(
            DeviceIdentifier(
                "MB565",
                "SysInfo",
                EvidenceAuthority.DEVICE_METADATA,
            ),
        ),
    )

    second = reconcile_device_metadata(
        evidence=metadata_only,
        profile=profile,
        existing_sysinfo=first.sysinfo,
        existing_sysinfo_extended=first.sysinfo_extended,
        existing_authority=first.authority,
        observed_at="2026-08-29T13:00:00+00:00",
    )

    assert not second.changed
    assert second.authority == first.authority
    fields = json.loads(second.authority)["fields"]
    assert fields["pszSerialNumber"]["authority"] == "current_hardware"
    assert fields["ModelNumStr"]["authority"] == "current_hardware"


def test_metadata_only_authority_never_suppresses_future_hardware_probes() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    metadata = DeviceEvidence(
        product_serials=(
            DeviceIdentifier(
                "8P840FN62C7",
                "SysInfo",
                EvidenceAuthority.DEVICE_METADATA,
            ),
        ),
        transport_serials=(
            DeviceIdentifier(
                "000A270012345678",
                "SysInfo",
                EvidenceAuthority.DEVICE_METADATA,
            ),
        ),
        model_numbers=(
            DeviceIdentifier(
                "MB565",
                "SysInfo",
                EvidenceAuthority.DEVICE_METADATA,
            ),
        ),
    )
    plan = reconcile_device_metadata(
        evidence=metadata,
        profile=profile,
        observed_at="2026-08-29T12:00:00+00:00",
    )

    assert not authority_covers_metadata(
        plan.authority,
        sysinfo=plan.sysinfo,
        sysinfo_extended=plan.sysinfo_extended,
    )


def test_reconciliation_replaces_a_malformed_sysinfo_extended_payload() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    evidence = DeviceEvidence(
        model_numbers=(
            DeviceIdentifier(
                "MB565",
                "SysInfo",
                EvidenceAuthority.DEVICE_METADATA,
            ),
        )
    )

    plan = reconcile_device_metadata(
        evidence=evidence,
        profile=profile,
        existing_sysinfo=b"ModelNumStr: xB565\n",
        existing_sysinfo_extended=b"<plist><dict><key>broken</key>",
        observed_at="2026-08-29T12:00:00+00:00",
    )

    assert plan.sysinfo_extended_changed
    assert plistlib.loads(plan.sysinfo_extended)["ModelNumStr"] == "MB565"
