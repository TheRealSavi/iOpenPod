"""Exercise HP identity through discovery, selection, and metadata repair."""

import plistlib
from pathlib import Path

import pytest

from iOpenPod.app.models.device import DeviceCandidateIssueCode, DeviceReadiness
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.library import WriteTarget, create_empty_library
from storage import (
    HardwareIdentifiers,
    HardwareProbeObservation,
    HardwareProbeResult,
    HardwareProperty,
    Storage,
)
from storage.testing import VirtualStoragePlatform


class _LinuxVirtualStoragePlatform(VirtualStoragePlatform):
    @property
    def name(self) -> str:
        return "linux"


def _ipod_volume(root: Path, *, model_number: str) -> Path:
    device = root / "iPod_Control" / "Device"
    database = root / "iPod_Control" / "iTunes" / "iTunesDB"
    device.mkdir(parents=True)
    database.parent.mkdir(parents=True)
    (device / "SysInfo").write_text(f"ModelNumStr: {model_number}\n", encoding="utf-8")
    result = create_empty_library(
        "HP Mini", WriteTarget(database_version=0x30), supports_podcasts=True
    )
    assert result.prepared is not None, result.issues
    database.write_bytes(result.prepared.itunes)
    return root


@pytest.mark.parametrize("model", ["MP5001", "PW753AA#ABA", "MP5002", "PX762AA"])
@pytest.mark.parametrize("source", ["udev", "linux_scsi"])
def test_hp_mini_discovery_and_selection(
    tmp_path: Path, model: str, source: str
) -> None:
    root = _ipod_volume(tmp_path / "mini", model_number=model)
    sysinfo = root / "iPod_Control" / "Device" / "SysInfo"
    before = sysinfo.read_bytes()
    serial = "2CD5270K4J"
    platform = _LinuxVirtualStoragePlatform()
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(usb_vendor_id=0x05AC, usb_product_id=0x1205),
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source=source,
                    vendor="Apple",
                    product="iPod",
                    unit_serial=serial if source == "linux_scsi" else "",
                    host_properties=(
                        HardwareProperty("ID_IOPENPOD_RULE_VERSION", "2"),
                        HardwareProperty(
                            "ID_IOPENPOD_PRODUCT_SERIAL",
                            serial if source == "udev" else "",
                        ),
                    ),
                ),
            ),
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        candidate = coordinator.discover_devices().candidates[0]
        assert candidate.selectable
        assert sysinfo.read_bytes() == before
        assert not any(
            issue.code is DeviceCandidateIssueCode.HARDWARE_PROBE_FAILED
            for issue in candidate.issues
        )
        active = coordinator.select_device(candidate.id)
        assert active.profile.generation == "2nd Gen"
        assert active.profile.model_number == (
            "MP5001" if model in {"MP5001", "PW753AA#ABA"} else "MP5002"
        )
        assert f"pszSerialNumber: {serial}\n".encode() in sysinfo.read_bytes()
    finally:
        coordinator.close()


@pytest.mark.parametrize("has_model", [True, False])
def test_hp_hardware_evidence_without_sysinfo(tmp_path: Path, has_model: bool) -> None:
    root = _ipod_volume(tmp_path / "mini", model_number="MP5001")
    sysinfo = root / "iPod_Control" / "Device" / "SysInfo"
    sysinfo.unlink()
    platform = _LinuxVirtualStoragePlatform()
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(usb_vendor_id=0x05AC, usb_product_id=0x1205),
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="linux_scsi",
                    vendor="Apple",
                    product="iPod",
                    unit_serial="2CD5270K4J",
                    vendor_payload=(
                        plistlib.dumps({"ModelNumStr": "PW753AA"}) if has_model else b""
                    ),
                ),
            ),
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        candidate = coordinator.discover_devices().candidates[0]
        assert candidate.selectable is has_model
        assert not sysinfo.exists()
        if has_model:
            active = coordinator.select_device(candidate.id)
            assert active.profile.model_number == "MP5001"
            assert b"pszSerialNumber: 2CD5270K4J\n" in sysinfo.read_bytes()
        else:
            assert candidate.readiness is DeviceReadiness.AMBIGUOUS
            assert candidate.profile is None
    finally:
        coordinator.close()
