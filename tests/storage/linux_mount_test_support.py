"""Captured Linux mounts over real temporary files; no block-device access."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from storage import HardwareProbeResult, ScsiVpdPagePlan, Storage
from storage.models import VolumeObservation
from storage.platform.linux import (
    LinuxMountRecord,
    LinuxPlatformAdapter,
    probe_from_udev_properties,
)


@dataclass
class LinuxRecoveryLayout:
    ipod: Path
    host: Path
    home: Path
    backing: Path
    records: list[LinuxMountRecord]
    adapter: LinuxPlatformAdapter
    storage: Storage


def linux_recovery_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, backing_on_device: bool = False
) -> LinuxRecoveryLayout:
    ipod, host, home = (tmp_path / name for name in ("ipod", "host", "home"))
    for path in (ipod, host, home):
        path.mkdir()
    backing = (ipod if backing_on_device else host) / ".Private"
    backing.mkdir()
    records = [
        LinuxMountRecord("1", "8:1", host, "ext4", "/dev/fixture-host1", ("rw",)),
        LinuxMountRecord("2", "0:2", home, "ecryptfs", str(backing), ("rw",)),
        LinuxMountRecord("3", "8:17", ipod, "vfat", "/dev/fixture-ipod1", ("rw",)),
    ]
    properties = {
        "ID_BUS": "usb",
        "ID_SERIAL": "Apple_iPod_fixture",
        "ID_FS_UUID": "TEST-0270",
        "ID_VENDOR_ID": "05ac",
        "ID_MODEL_ID": "1261",
        "ID_SERIAL_SHORT": "000A270012345678",
    }

    def udev_properties(record: LinuxMountRecord) -> dict[str, str]:
        return properties.copy() if record.mount_id == "3" else {}

    def whole_disk_number(source: str) -> str:
        return {
            "/dev/fixture-host1": "8:0",
            "/dev/fixture-ipod1": "8:16",
        }.get(source, "")

    def probe(
        observation: VolumeObservation, page_plan: ScsiVpdPagePlan | None = None
    ) -> HardwareProbeResult:
        return probe_from_udev_properties(properties)

    adapter = LinuxPlatformAdapter()
    monkeypatch.setattr(adapter, "_records", lambda: tuple(records))
    monkeypatch.setattr(adapter, "udev_properties_for_record", udev_properties)
    monkeypatch.setattr(adapter, "probe", probe)
    monkeypatch.setattr(
        "storage.platform.linux._whole_disk_device_number", whole_disk_number
    )
    storage = Storage(
        adapter,
        writer_lock_directory=host / "locks",
        transaction_recovery_directory=home / "TransactionRecovery",
    )
    return LinuxRecoveryLayout(ipod, host, home, backing, records, adapter, storage)
