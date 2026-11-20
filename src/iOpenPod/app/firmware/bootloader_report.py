"""Current USB reports of NOR measured at boot, separate from saved DFU receipts.

The running firmware is the reporter, not a cryptographic attestation authority.
Only current transport bytes enter this parser; saved SysInfo files never do.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import IntEnum

from .bootloader_identity import BootloaderIdentity, decode_bootloader_marker
from .bootloader_targets import CLASSIC_BOOTLOADERS
from .shared_bootloader import BODY_SHA256, VERSION

REPORT_KEY = "iOpenPodBootReport"
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?")


class BootloaderReportStatus(IntEnum):
    INVALID = 0
    READ_ERROR = 1
    UNSUPPORTED = 2
    ENCRYPTED = 3
    MEASURED = 4


@dataclass(frozen=True)
class BootloaderReport:
    status: BootloaderReportStatus
    mod_version: str = ""
    serial: str = ""
    model: str = ""
    hardware: int = 0
    body_sha256: str = ""
    marker: BootloaderIdentity | None = None

    @property
    def version(self) -> str:
        return self.marker.version if self.marker is not None else ""

    @property
    def hardware_family(self) -> int | None:
        return next(
            (
                target.family
                for target in CLASSIC_BOOTLOADERS
                if target.hardware == self.hardware and self.model in target.models
            ),
            None,
        )


def _dictionary(node: ET.Element) -> dict[str, ET.Element]:
    children = list(node)
    if node.tag != "dict" or len(children) % 2:
        raise ValueError("Invalid report dictionary")
    result: dict[str, ET.Element] = {}
    for key, value in zip(children[::2], children[1::2], strict=True):
        if key.tag != "key" or len(key) or not key.text or key.text in result:
            raise ValueError("Invalid or duplicate report key")
        result[key.text] = value
    return result


def _string(data: dict[str, ET.Element], key: str, max_length: int) -> str:
    value = data[key]
    text = value.text or ""
    if value.tag != "string" or len(value) or not 0 < len(text) <= max_length:
        raise ValueError("Invalid report string")
    return text


def _integer(data: dict[str, ET.Element], key: str) -> int:
    value = data[key]
    text = value.text or ""
    if (
        value.tag != "integer"
        or len(value)
        or re.fullmatch(r"[0-9]{1,10}", text) is None
    ):
        raise ValueError("Invalid report integer")
    result = int(text)
    if result > 0xFFFFFFFF:
        raise ValueError("Report integer out of range")
    return result


def read_bootloader_report(
    payload: bytes, *, serial: str, model: str
) -> BootloaderReport | None:
    """Absent report means legacy firmware; a broken report never means absent."""
    if REPORT_KEY.encode() not in payload:
        return None
    invalid = BootloaderReport(BootloaderReportStatus.INVALID)
    if len(payload) > 1024 * 1024 or b"<!ENTITY" in payload.upper():
        return invalid
    try:
        root = ET.fromstring(payload)
        if root.tag != "plist" or len(root) != 1:
            return invalid
        data = _dictionary(_dictionary(root[0])[REPORT_KEY])
        if _integer(data, "Schema") != 1:
            return invalid
        status = BootloaderReportStatus(_integer(data, "Status"))
        version = _string(data, "ModVersion", 31)
        if (
            status is BootloaderReportStatus.INVALID
            or _VERSION.fullmatch(version) is None
        ):
            return invalid
        if status in (
            BootloaderReportStatus.READ_ERROR,
            BootloaderReportStatus.UNSUPPORTED,
        ):
            return BootloaderReport(status, version)
        device_serial = _string(data, "DeviceSerial", 15)
        device_model = _string(data, "DeviceModel", 15)
        if (device_serial, device_model) != (serial, model):
            return invalid
        hardware = _integer(data, "HardwareRevision")
        digest = ""
        marker = None
        if status is BootloaderReportStatus.MEASURED:
            digest = _string(data, "BodySHA256", 64)
            raw_marker = _string(data, "Marker", 128)
            if (
                re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or re.fullmatch(r"[0-9a-f]{128}", raw_marker) is None
            ):
                return invalid
            marker = decode_bootloader_marker(bytes.fromhex(raw_marker))
        report = BootloaderReport(
            status, version, device_serial, device_model, hardware, digest, marker
        )
        return report if report.hardware_family is not None else invalid
    except (ET.ParseError, KeyError, ValueError):
        return invalid


def require_reported_bootloader(
    report: BootloaderReport, *, serial: str, model: str
) -> int:
    """Qualify the complete measured executable and its matching identity marker."""
    family = report.hardware_family
    if (
        report.status is not BootloaderReportStatus.MEASURED
        or (report.serial, report.model) != (serial, model)
        or report.body_sha256 != BODY_SHA256
        or report.marker != BootloaderIdentity(2, 2, 0x43534C43, 15, VERSION)
        or family is None
    ):
        raise ValueError(
            f"The current firmware report does not verify Bootloader {VERSION}; "
            "use bootloader setup to check or upgrade it"
        )
    return family
