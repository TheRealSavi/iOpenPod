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


def add_linux_block(
    sysfs: Path,
    name: str,
    number: str,
    *,
    parent: Path | None = None,
    virtual: bool = False,
    slaves: tuple[Path, ...] = (),
) -> Path:
    """Create a kernel-shaped block graph, including real sysfs symlinks."""
    root = sysfs / "devices" / ("virtual" if virtual else "pci") / "block"
    node = (parent if parent is not None else root) / name
    node.mkdir(parents=True)
    (node / "dev").write_text(number, encoding="ascii")
    if parent is not None:
        (node / "partition").write_text("1", encoding="ascii")
    else:
        (node / "diskseq").write_text(number.split(":")[1], encoding="ascii")
    (node / "slaves").mkdir()
    if name.startswith("dm-"):
        (node / "dm").mkdir()
        (node / "dm" / "suspended").write_text("0", encoding="ascii")
    if name.startswith("md"):
        (node / "md").mkdir()
        (node / "md" / "raid_disks").write_text(str(len(slaves)), encoding="ascii")
        (node / "md" / "degraded").write_text("0", encoding="ascii")
    links = sysfs / "class" / "block"
    links.mkdir(parents=True, exist_ok=True)
    try:
        (links / name).symlink_to(node, target_is_directory=True)
        for slave in slaves:
            (node / "slaves" / slave.name).symlink_to(slave, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Directory symlinks unavailable: {error}")
    return node


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

    sysfs = tmp_path / "sys"
    host_disk = add_linux_block(sysfs, "fixture-host", "8:0")
    add_linux_block(sysfs, "fixture-host1", "8:1", parent=host_disk)
    ipod_disk = add_linux_block(sysfs, "fixture-ipod", "8:16")
    add_linux_block(sysfs, "fixture-ipod1", "8:17", parent=ipod_disk)

    def probe(
        observation: VolumeObservation, page_plan: ScsiVpdPagePlan | None = None
    ) -> HardwareProbeResult:
        return probe_from_udev_properties(properties)

    adapter = LinuxPlatformAdapter()
    monkeypatch.setattr(adapter, "_records", lambda: tuple(records))
    monkeypatch.setattr(adapter, "udev_properties_for_record", udev_properties)
    monkeypatch.setattr(adapter, "probe", probe)
    monkeypatch.setattr(
        "storage.platform.linux._SYS_CLASS_BLOCK", sysfs / "class" / "block"
    )
    storage = Storage(
        adapter,
        writer_lock_directory=host / "locks",
        transaction_recovery_directory=home / "TransactionRecovery",
    )
    return LinuxRecoveryLayout(ipod, host, home, backing, records, adapter, storage)
