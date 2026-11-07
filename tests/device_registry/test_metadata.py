"""Tests for pure iPod metadata-to-evidence adapters."""

import plistlib

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    ConnectionMode,
    DeviceEvidence,
    DeviceIdentifier,
    EvidenceAuthority,
    IdentificationStatus,
    UsbIdentifier,
    parse_sysinfo,
    parse_sysinfo_extended,
)


def test_sysinfo_parser_preserves_identifier_meanings_and_provenance() -> None:
    evidence = parse_sysinfo(
        b"""
        BoardHwName: n121
        pszSerialNumber: 8P840FN62C7
        FirewireGuid: 0x000A270012345678
        visibleBuildID: 2.0.1
        ModelNumStr: xB565
        USBProductID: 1261
        FamilyID: 6
        UpdaterFamilyID: 3
        """
    )

    assert evidence.model_numbers[0].value == "MB565"
    assert evidence.product_serials[0].value == "8P840FN62C7"
    assert evidence.transport_serials[0].value == "000A270012345678"
    assert evidence.product_serials[0] != evidence.transport_serials[0]
    assert evidence.usb_identifiers[0].value == UsbIdentifier(0x05AC, 0x1261)
    assert evidence.board_hardware_names[0].value == "n121"
    assert evidence.firmware_versions[0].value == "2.0.1"
    assert evidence.family_ids[0].value == 6
    assert evidence.updater_family_ids[0].value == 3
    assert all(
        identifier.authority is EvidenceAuthority.DEVICE_METADATA
        for identifier in (
            *evidence.model_numbers,
            *evidence.product_serials,
            *evidence.transport_serials,
            *evidence.usb_identifiers,
        )
    )


def test_metadata_evidence_can_merge_with_current_host_evidence() -> None:
    cached = parse_sysinfo("ModelNumStr: xB565\npszSerialNumber: 8P840FN62C7\n")
    current = DeviceEvidence(
        usb_identifiers=(
            DeviceIdentifier(
                value=UsbIdentifier(vendor_id=0x05AC, product_id=0x1261),
                source="host USB API",
                authority=EvidenceAuthority.CURRENT_HARDWARE,
            ),
        )
    )

    result = DEFAULT_DEVICE_REGISTRY.identify(cached.merged_with(current))

    assert result.status is IdentificationStatus.EXACT
    assert result.connection_mode is ConnectionMode.NORMAL
    assert result.profile is not None
    assert result.profile.model_number == "MB565"


def test_malformed_or_empty_sysinfo_values_are_ignored() -> None:
    evidence = parse_sysinfo(
        """
        # captured file with partial data
        malformed line
        ModelNumStr:
        USBProductID: not-a-number
        FirewireGuid: 0000000000000000
        """
    )

    assert evidence == DeviceEvidence()


def test_sysinfo_extended_plist_maps_identity_without_reading_a_path() -> None:
    evidence = parse_sysinfo_extended(
        plistlib.dumps(
            {
                "SerialNumber": "8P840FN62C7",
                "FireWireGUID": "000A270012345678",
                "ModelNumStr": "xB565",
                "BoardHwName": "n121",
                "VisibleBuildID": "2.0.1",
                "FamilyID": 6,
                "UpdaterFamilyID": 3,
                "usb_vid": 0x05AC,
                "usb_pid": 0x1261,
            }
        )
    )

    assert evidence.model_numbers[0].value == "MB565"
    assert evidence.product_serials[0].value == "8P840FN62C7"
    assert evidence.transport_serials[0].value == "000A270012345678"
    assert evidence.usb_identifiers[0].value == UsbIdentifier(0x05AC, 0x1261)
    assert evidence.family_ids[0].value == 6


def test_sysinfo_extended_uses_bounded_scalar_fallback() -> None:
    evidence = parse_sysinfo_extended(
        b"transport-prefix<plist><dict>"
        b"<key>ModelNumStr</key><string>MB565</string>"
        b"<key>SerialNumber</key><string>RAND1234</string>"
    )

    assert evidence.model_numbers[0].value == "MB565"
    assert evidence.product_serials == ()


def test_sysinfo_keeps_release_and_transport_revision_separate_when_merged() -> None:
    first = parse_sysinfo("visibleBuildID: 2.0.1\nFireWireVersion: 1.62\n")
    second = parse_sysinfo_extended(
        plistlib.dumps({"VisibleBuildID": "2.0.1", "scsi_revision": "1.62"}),
        authority=EvidenceAuthority.CURRENT_HARDWARE,
    )
    merged = first.merged_with(second)
    assert [item.value for item in merged.firmware_versions] == ["2.0.1", "2.0.1"]
    assert [item.value for item in merged.transport_revisions] == ["1.62", "1.62"]
    assert (
        merged.transport_revisions[-1].authority is EvidenceAuthority.CURRENT_HARDWARE
    )
    assert parse_sysinfo("BuildID: 9.0.1\n").firmware_versions == ()


def test_scalar_fallback_keeps_release_distinct_from_transport_revision() -> None:
    evidence = parse_sysinfo_extended(
        b"<plist><dict><key>FireWireVersion</key><string>1.62</string>"
        b"<key>VisibleBuildID</key><string>2.0.1</string>"
        b"<key>ImageSpecifications</key><array><key>1067</key><dict/>"
        b"</array></dict></plist>"
    )
    assert evidence.firmware_versions[0].value == "2.0.1"
    assert evidence.transport_revisions[0].value == "1.62"
