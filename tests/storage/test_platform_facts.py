"""Deterministic tests for native-platform parsing and filesystem facts."""

import plistlib
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from storage import (
    MountInspectionError,
    PhysicalDeviceId,
    Storage,
    VolumeIdentityChangedError,
)
from storage.platform import macos_vpd
from storage.platform.common import capabilities
from storage.platform.linux import (
    LinuxMountRecord,
    LinuxPlatformAdapter,
    parse_mountinfo,
    parse_udev_properties,
    probe_from_udev_properties,
)
from storage.platform.macos import MacOSPlatformAdapter

_MACOS_IOREG_MEDIA = b"""\
+-o AppleUSBKeyboard@14100000  <class IOUSBHostDevice, ...>
  |   \"USB Serial Number\" = \"KBD-ABCDEF\"
+-o iPod@01130000  <class IOUSBHostDevice, ...>
  |   \"USB Serial Number\" = \"000A270018A1F847\"
  +-o IOUSBMassStorageDriver  <class IOUSBMassStorageDriver, ...>
    +-o Apple iPod Media  <class IOMedia, ...>
    |   \"BSD Name\" = \"disk4\"
"""


class _RecordingIOKit:
    def __init__(self) -> None:
        self.matching_classes: list[bytes] = []

    def IOServiceMatching(self, name: bytes) -> None:
        self.matching_classes.append(name)


class _RecordingFrameworks:
    def __init__(self) -> None:
        self.iokit = _RecordingIOKit()


def test_macos_inspection_correlates_bsd_disk_with_usb_hardware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disk_info: dict[str, object] = {
        "MountPoint": str(tmp_path),
        "DeviceIdentifier": "disk4s2",
        "ParentWholeDisk": "disk4",
        "VolumeUUID": "12345678-1234-5678-9ABC-DEF012345678",
        "FilesystemType": "msdos",
        "VolumeName": "John's iPod",
        "RemovableMedia": True,
        "BusProtocol": "USB",
        "Writable": True,
        "AllocationBlockSize": 4096,
    }
    usb_devices: list[dict[str, object]] = [
        {
            "idVendor": 0x05AC,
            "idProduct": 0x1261,
            "USB Serial Number": "000A270018A1F847",
        },
        {
            "idVendor": 0x05AC,
            "idProduct": 0x0220,
            "USB Serial Number": "KBD-ABCDEF",
        },
    ]

    def run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        if command[:2] == ["diskutil", "info"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=plistlib.dumps(disk_info),
                stderr=b"",
            )
        if command == ["ioreg", "-r", "-c", "IOMedia"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=_MACOS_IOREG_MEDIA,
                stderr=b"",
            )
        if command == ["ioreg", "-a", "-r", "-c", "IOUSBHostDevice"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=plistlib.dumps(usb_devices),
                stderr=b"",
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("storage.platform.macos.subprocess.run", run)

    def no_kernel_snapshot(_path: Path) -> None:
        raise MountInspectionError("captured diskutil-only fixture")

    monkeypatch.setattr("storage.platform.macos._read_statfs", no_kernel_snapshot)

    adapter = MacOSPlatformAdapter()
    observation = adapter.inspect(tmp_path)

    identifiers = observation.physical_device.identifiers
    assert identifiers.usb_vendor_id == 0x05AC
    assert identifiers.usb_product_id == 0x1261
    assert identifiers.transport_serial == "000A270018A1F847"
    assert adapter.physical_device_id_for_path(tmp_path) == (
        observation.physical_device.id
    )


def test_macos_scsi_probe_targets_the_ipod_task_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frameworks = _RecordingFrameworks()
    monkeypatch.setattr("storage.platform.macos_vpd.sys.platform", "darwin")
    monkeypatch.setattr(macos_vpd, "_MacFrameworks", lambda: frameworks)

    macos_vpd.probe_macos_scsi(
        usb_product_id=0x1261,
        transport_serial="000A270018A1F847",
        target_bsd_name="disk4",
    )

    assert frameworks.iokit.matching_classes == [b"com_apple_driver_iPodSBCNub"]


def test_linux_mountinfo_preserves_mount_identity_and_decodes_paths() -> None:
    content = (
        "42 35 8:17 / /run/media/john/IPOD\\040CLASSIC "
        "rw,nosuid,nodev shared:11 - vfat /dev/sdb1 "
        "rw,uid=1000,gid=1000,flush,errors=remount-ro\n"
        "malformed mount table row\n"
    )

    records = parse_mountinfo(content)

    assert len(records) == 1
    record = records[0]
    assert record.mount_id == "42"
    assert record.device_number == "8:17"
    assert record.mount_point == Path("/run/media/john/IPOD CLASSIC")
    assert record.filesystem_type == "vfat"
    assert record.source == "/dev/sdb1"
    assert "rw" in record.options
    assert "flush" in record.options


def test_linux_udev_parser_ignores_non_property_rows() -> None:
    properties = parse_udev_properties(
        "I:123\nE:ID_BUS=usb\nE:ID_VENDOR_ID=05ac\nE:ID_MODEL_ID=1261\nG:systemd\n"
    )

    assert properties == {
        "ID_BUS": "usb",
        "ID_VENDOR_ID": "05ac",
        "ID_MODEL_ID": "1261",
    }


def test_linux_udev_product_serial_is_live_probe_evidence() -> None:
    result = probe_from_udev_properties(
        {
            "ID_VENDOR_ID": "05ac",
            "ID_MODEL_ID": "1261",
            "ID_SERIAL_SHORT": "000A270012345678",
            "ID_IOPENPOD_RULE_VERSION": "2",
            "ID_IOPENPOD_PRODUCT_SERIAL": "8P840FN62C7",
        }
    )

    assert result.observations[0].source == "udev"
    assert result.observations[0].unit_serial == ""
    assert result.observations[0].transport_serial == "000A270012345678"
    properties = {
        property_.name: property_.value
        for property_ in result.observations[0].host_properties
    }
    assert properties["ID_IOPENPOD_PRODUCT_SERIAL"] == "8P840FN62C7"
    assert result.issues == ()


def test_linux_probe_includes_whole_disk_udev_properties(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import storage.platform.linux as linux

    udev_data = tmp_path / "udev"
    udev_data.mkdir()
    (udev_data / "b8:0").write_text(
        "E:ID_IOPENPOD_RULE_VERSION=2\nE:ID_IOPENPOD_PRODUCT_SERIAL=8P840FN62C7\n",
        encoding="utf-8",
    )
    (udev_data / "b8:1").write_text(
        "E:ID_FS_UUID=volume-id\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(linux, "_UDEV_DATA", udev_data)

    def whole_disk_device_number(_source: str) -> str:
        return "8:0"

    monkeypatch.setattr(
        linux,
        "_whole_disk_device_number",
        whole_disk_device_number,
    )
    record = LinuxMountRecord(
        mount_id="12",
        device_number="8:1",
        mount_point=tmp_path,
        filesystem_type="vfat",
        source="/dev/sda1",
        options=("rw",),
    )

    properties = LinuxPlatformAdapter.udev_properties_for_record(record)

    assert properties["ID_IOPENPOD_PRODUCT_SERIAL"] == "8P840FN62C7"
    assert properties["ID_FS_UUID"] == "volume-id"


@pytest.mark.parametrize(
    "missing_properties",
    [
        ("ID_SERIAL",),
        ("ID_FS_UUID",),
        ("ID_BUS", "ID_SERIAL", "ID_FS_UUID"),
    ],
)
def test_linux_session_survives_transient_missing_udev_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_properties: tuple[str, ...],
) -> None:
    import storage.platform.linux as linux

    record = LinuxMountRecord(
        mount_id="42",
        device_number="8:17",
        mount_point=tmp_path,
        filesystem_type="vfat",
        source="/dev/sdb1",
        options=("rw",),
    )
    properties = {
        "ID_BUS": "usb",
        "ID_SERIAL": "Apple_iPod_Classic_000A270012345678",
        "ID_FS_UUID": "ABCD-1234",
    }

    def udev_properties_for_record(_record: LinuxMountRecord) -> dict[str, str]:
        return properties.copy()

    def whole_disk_device_number(_source: str) -> str:
        return "8:16"

    adapter = LinuxPlatformAdapter()
    monkeypatch.setattr(adapter, "_records", lambda: (record,))
    monkeypatch.setattr(
        adapter, "udev_properties_for_record", udev_properties_for_record
    )
    monkeypatch.setattr(linux, "_whole_disk_device_number", whole_disk_device_number)
    storage = Storage(adapter)
    mounted = storage.discover().volumes[0]

    # udev may briefly omit optional identity properties while the same kernel
    # mount and block device remain connected.
    for name in missing_properties:
        del properties[name]
    with storage.open_session(mounted) as session:
        assert session.is_active

    assert (
        storage.discover().volumes[0].connection_generation
        == mounted.connection_generation
    )
    assert adapter.physical_device_id_for_path(tmp_path) == mounted.physical_device.id
    with storage.open_session(mounted) as session:
        assert session.mounted_volume.mount_instance == "linux-mount:42"


@pytest.mark.parametrize(
    "change", ["remount", "different_serial", "discovered_disconnect"]
)
def test_linux_new_connection_expires_cached_udev_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    import storage.platform.linux as linux

    record = LinuxMountRecord(
        mount_id="42",
        device_number="8:17",
        mount_point=tmp_path,
        filesystem_type="vfat",
        source="/dev/sdb1",
        options=("rw",),
    )
    properties = {
        "ID_BUS": "usb",
        "ID_SERIAL": "Apple_iPod_Classic_000A270012345678",
        "ID_FS_UUID": "ABCD-1234",
    }

    def udev_properties_for_record(_record: LinuxMountRecord) -> dict[str, str]:
        return properties.copy()

    def whole_disk_device_number(_source: str) -> str:
        return "8:16"

    adapter = LinuxPlatformAdapter()
    monkeypatch.setattr(adapter, "_records", lambda: (record,))
    monkeypatch.setattr(
        adapter, "udev_properties_for_record", udev_properties_for_record
    )
    monkeypatch.setattr(linux, "_whole_disk_device_number", whole_disk_device_number)
    storage = Storage(adapter)
    old = storage.discover().volumes[0]

    if change == "remount":
        record = replace(record, mount_id="43")
        del properties["ID_SERIAL"]
    elif change == "different_serial":
        properties["ID_SERIAL"] = "Apple_iPod_Classic_different"
    else:
        monkeypatch.setattr(adapter, "_records", lambda: ())
        assert storage.discover().volumes == ()
        monkeypatch.setattr(adapter, "_records", lambda: (record,))
        del properties["ID_SERIAL"]
    current = storage.discover().volumes[0]

    assert current.connection_generation != old.connection_generation
    if change == "discovered_disconnect":
        assert current.physical_device.id != old.physical_device.id
    with pytest.raises(VolumeIdentityChangedError):
        storage.open_session(old)


def test_linux_host_path_identity_collapses_sibling_partitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import storage.platform.linux as linux

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = LinuxMountRecord(
        mount_id="12",
        device_number="8:1",
        mount_point=first_root,
        filesystem_type="vfat",
        source="/dev/sdb1",
        options=("rw",),
    )
    second = LinuxMountRecord(
        mount_id="13",
        device_number="8:2",
        mount_point=second_root,
        filesystem_type="vfat",
        source="/dev/sdb2",
        options=("rw",),
    )
    adapter = LinuxPlatformAdapter()

    def no_udev_properties(_record: LinuxMountRecord) -> dict[str, str]:
        return {}

    def whole_disk_device_number(_source: str) -> str:
        return "8:0"

    monkeypatch.setattr(adapter, "_records", lambda: (first, second))
    monkeypatch.setattr(adapter, "udev_properties_for_record", no_udev_properties)
    monkeypatch.setattr(linux, "_whole_disk_device_number", whole_disk_device_number)

    retained = adapter._observation(first, {})  # pyright: ignore[reportPrivateUsage]

    assert adapter.physical_device_id_for_path(second_root) == (
        retained.physical_device.id
    )


def test_windows_host_path_identity_uses_physical_disk_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import storage.platform.windows as windows

    class _Lookup:
        def for_path(self, path: Path) -> PhysicalDeviceId:
            assert path == tmp_path
            return PhysicalDeviceId("windows:disk-7")

    adapter = object.__new__(windows.WindowsPlatformAdapter)
    monkeypatch.setattr(
        adapter,
        "_physical_device_lookup",
        _Lookup(),
        raising=False,
    )

    identity = adapter.physical_device_id_for_path(tmp_path)

    assert identity is not None
    assert identity.value == "windows:disk-7"


def test_linux_adapter_does_not_assign_domain_meaning_to_missing_properties() -> None:
    result = probe_from_udev_properties(
        {
            "ID_VENDOR_ID": "05ac",
            "ID_MODEL_ID": "1261",
            "ID_SERIAL_SHORT": "000A270012345678",
        }
    )

    assert result.observations[0].transport_serial == "000A270012345678"
    assert result.issues == ()


def test_common_capability_rules_capture_fat_limits_and_unsafe_mounts(
    tmp_path: Path,
) -> None:
    safe = capabilities(
        tmp_path,
        filesystem_type="fat32",
        read_only=False,
        known_allocation_unit=4096,
        known_component_limit=255,
    )
    unsafe = capabilities(
        tmp_path,
        filesystem_type="hfsplus",
        read_only=False,
        unsafe_write_reasons=("mounted with force",),
    )

    assert safe.safe_for_writes
    assert safe.max_file_size_bytes == 4 * 1024**3 - 1
    assert safe.allocation_unit_size == 4096
    assert safe.max_component_length == 255
    assert not unsafe.safe_for_writes


def test_common_capabilities_prefer_known_case_sensitivity(tmp_path: Path) -> None:
    known_true = capabilities(
        tmp_path,
        filesystem_type="hfsx",
        read_only=False,
        known_case_sensitive=True,
    )
    known_false = capabilities(
        tmp_path,
        filesystem_type="apfs",
        read_only=False,
        known_case_sensitive=False,
    )
    inferred_fat = capabilities(
        tmp_path,
        filesystem_type="msdosfs",
        read_only=False,
    )
    unknown = capabilities(
        tmp_path,
        filesystem_type="apfs",
        read_only=False,
    )

    assert known_true.case_sensitive is True
    assert known_false.case_sensitive is False
    assert inferred_fat.case_sensitive is False
    assert unknown.case_sensitive is None
