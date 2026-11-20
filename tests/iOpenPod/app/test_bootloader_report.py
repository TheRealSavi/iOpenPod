"""Current wire evidence must not silently degrade into historical evidence."""

from dataclasses import replace
from hashlib import sha256

import pytest
from tests.iOpenPod.boot_report_helpers import REPORT_XML, report_xml

from iOpenPod.app.firmware.bootloader_report import (
    BootloaderReportStatus,
    read_bootloader_report,
    require_reported_bootloader,
)
from iOpenPod.app.firmware.bootloader_targets import bootloader_target


@pytest.mark.parametrize("family", [24, 33, 35, 38])
def test_actual_native_xml_qualifies_measured_code_for_each_hardware(
    family: int,
) -> None:
    target = bootloader_target(family)
    report = read_bootloader_report(
        report_xml(DeviceModel=target.models[0], HardwareRevision=target.hardware),
        serial="TEST12345678",
        model=target.models[0],
    )
    assert report is not None and report.version == "2.1.0"
    assert report.mod_version == "0.6.0-dev"
    assert (
        require_reported_bootloader(
            report, serial="TEST12345678", model=target.models[0]
        )
        == family
    )


def test_legacy_payload_is_absent_not_an_error() -> None:
    assert (
        read_bootloader_report(b"<plist><dict/></plist>", serial="", model="") is None
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"iOpenPodBootReport",
        REPORT_XML[:-10],
        REPORT_XML + b" " * 1024 * 1024,
        REPORT_XML.replace(b"<!DOCTYPE", b'<!ENTITY x "y"><!DOCTYPE'),
        REPORT_XML.replace(b"<dict>", b"<array>", 1),
        REPORT_XML.replace(b"<key>Schema</key>", b"<key>Status</key>"),
        REPORT_XML.replace(b"<integer>1</integer>", b"<integer>-1</integer>"),
        report_xml(Schema=2),
        report_xml(Schema="1"),
        report_xml(Status=0),
        report_xml(Status=99),
        report_xml(ModVersion="garbage"),
        report_xml(DeviceSerial="OTHER1234567"),
        report_xml(DeviceModel="MC297"),
        report_xml(HardwareRevision=0x130300),
        report_xml(HardwareRevision=0x100000000),
        report_xml(BodySHA256="A" * 64),
        report_xml(BodySHA256="0" * 63),
        report_xml(Marker="00" * 63),
        REPORT_XML.replace(b"322e312e300000", b"322e312e300001"),
    ],
    ids=lambda payload: sha256(payload).hexdigest()[:12],
)
def test_present_but_invalid_report_is_never_absent(payload: bytes) -> None:
    report = read_bootloader_report(payload, serial="TEST12345678", model="MB565")
    assert report is not None and report.status is BootloaderReportStatus.INVALID
    with pytest.raises(ValueError, match="current firmware report"):
        require_reported_bootloader(report, serial="TEST12345678", model="MB565")


@pytest.mark.parametrize(
    "fields",
    [
        {"Status": 1},
        {"Status": 2},
        {"Status": 3},
        {"BodySHA256": "0" * 64},
        {"Marker": "00" * 64},
    ],
)
def test_read_failure_encrypted_or_unknown_code_never_qualifies(
    fields: dict[str, str | int],
) -> None:
    report = read_bootloader_report(
        report_xml(**fields), serial="TEST12345678", model="MB565"
    )
    assert report is not None and report.status is not BootloaderReportStatus.INVALID
    with pytest.raises(ValueError):
        require_reported_bootloader(report, serial="TEST12345678", model="MB565")


def test_a_marker_or_a_matching_hash_alone_is_insufficient() -> None:
    report = read_bootloader_report(REPORT_XML, serial="TEST12345678", model="MB565")
    assert report is not None and report.marker is not None
    for changed in (
        replace(report, serial="ANOTHER"),
        replace(report, model="MB562"),
        replace(report, marker=replace(report.marker, version="2.0.0")),
        replace(report, marker=replace(report.marker, abi=1)),
    ):
        with pytest.raises(ValueError):
            require_reported_bootloader(changed, serial="TEST12345678", model="MB565")
