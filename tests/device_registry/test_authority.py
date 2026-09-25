"""Pure tests for iOpenPod SysInfo authority reconciliation."""

import json
import plistlib

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    DeviceEvidence,
    DeviceIdentifier,
    EvidenceAuthority,
    UsbIdentifier,
    authority_covers_metadata,
    reconcile_device_metadata,
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
