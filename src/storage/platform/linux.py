"""Linux mounted-volume discovery using mountinfo and non-privileged udev data."""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from storage.errors import MountInspectionError
from storage.models import (
    DeviceBus,
    DiscoveryIssue,
    EjectResult,
    FlushResult,
    HardwareIdentifiers,
    HardwareProbeIssue,
    HardwareProbeIssueCode,
    HardwareProbeObservation,
    HardwareProbeResult,
    HardwareProperty,
    MountPoint,
    PhysicalDevice,
    PhysicalDeviceId,
    ScsiVpdPagePlan,
    Volume,
    VolumeId,
    VolumeObservation,
)
from storage.platform.base import ObservationDiscoveryResult
from storage.platform.common import capabilities, disk_usage
from storage.platform.linux_eject import LinuxDeviceEjector
from storage.scsi_vpd import collect_scsi_vpd

_MOUNTINFO = Path("/proc/self/mountinfo")
_UDEV_DATA = Path("/run/udev/data")
_SYS_CLASS_BLOCK = Path("/sys/class/block")
_SG_IO = 0x2285
_SG_DXFER_FROM_DEVICE = -3


class _SgIoHeader(ctypes.Structure):
    _fields_ = [
        ("interface_id", ctypes.c_int),
        ("dxfer_direction", ctypes.c_int),
        ("cmd_len", ctypes.c_ubyte),
        ("mx_sb_len", ctypes.c_ubyte),
        ("iovec_count", ctypes.c_ushort),
        ("dxfer_len", ctypes.c_uint),
        ("dxferp", ctypes.c_void_p),
        ("cmdp", ctypes.c_void_p),
        ("sbp", ctypes.c_void_p),
        ("timeout", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("pack_id", ctypes.c_int),
        ("usr_ptr", ctypes.c_void_p),
        ("status", ctypes.c_ubyte),
        ("masked_status", ctypes.c_ubyte),
        ("msg_status", ctypes.c_ubyte),
        ("sb_len_wr", ctypes.c_ubyte),
        ("host_status", ctypes.c_ushort),
        ("driver_status", ctypes.c_ushort),
        ("resid", ctypes.c_int),
        ("duration", ctypes.c_uint),
        ("info", ctypes.c_uint),
    ]


class _Ioctl(Protocol):
    def __call__(
        self,
        descriptor: int,
        operation: int,
        argument: _SgIoHeader,
        /,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class LinuxMountRecord:
    mount_id: str
    device_number: str
    mount_point: Path
    filesystem_type: str
    source: str
    options: tuple[str, ...]


def parse_mountinfo(content: str) -> tuple[LinuxMountRecord, ...]:
    """Parse Linux mountinfo without assuming fixed desktop mount paths."""

    records: list[LinuxMountRecord] = []
    for line in content.splitlines():
        fields = line.split()
        try:
            separator = fields.index("-")
        except ValueError:
            continue
        if separator < 6 or len(fields) <= separator + 3:
            continue
        mount_options = _unique_options(fields[5], fields[separator + 3])
        records.append(
            LinuxMountRecord(
                mount_id=fields[0],
                device_number=fields[2],
                mount_point=Path(_decode_mountinfo_field(fields[4])),
                filesystem_type=fields[separator + 1].strip().casefold(),
                source=_decode_mountinfo_field(fields[separator + 2]),
                options=mount_options,
            )
        )
    return tuple(records)


def parse_udev_properties(content: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in content.splitlines():
        if not line.startswith("E:") or "=" not in line:
            continue
        key, value = line[2:].split("=", maxsplit=1)
        properties[key] = value
    return properties


class LinuxPlatformAdapter:
    def __init__(self) -> None:
        self._device_ejector = LinuxDeviceEjector()

    @property
    def name(self) -> str:
        return "linux"

    def discover(self) -> ObservationDiscoveryResult:
        issues: list[DiscoveryIssue] = []
        observations: list[VolumeObservation] = []
        try:
            records = self._records()
        except OSError as error:
            return ObservationDiscoveryResult(
                observations=(),
                issues=(DiscoveryIssue("linux.mountinfo", str(error)),),
            )
        for record in records:
            properties = self.udev_properties_for_record(record)
            if not _is_removable(record, properties):
                continue
            try:
                observations.append(self._observation(record, properties))
            except (OSError, ValueError) as error:
                issues.append(
                    DiscoveryIssue(
                        source=os.fspath(record.mount_point),
                        detail=str(error),
                    )
                )
        return ObservationDiscoveryResult(
            observations=tuple(observations),
            issues=tuple(issues),
        )

    def inspect(self, mount_point: Path) -> VolumeObservation:
        requested = Path(os.path.realpath(mount_point))
        try:
            records = self._records()
        except OSError as error:
            raise MountInspectionError(
                f"Could not read the Linux mount table: {error}"
            ) from error
        matching = tuple(
            record
            for record in records
            if requested == record.mount_point
            or requested.is_relative_to(record.mount_point)
        )
        if not matching:
            raise MountInspectionError(f"No mounted Volume contains {requested}")
        record = max(matching, key=lambda item: len(os.fspath(item.mount_point)))
        try:
            return self._observation(
                record,
                self.udev_properties_for_record(record),
            )
        except OSError as error:
            raise MountInspectionError(
                f"Could not inspect the mounted Volume at {requested}: {error}"
            ) from error

    def reinspect(self, retained: VolumeObservation) -> VolumeObservation:
        return self.inspect(retained.mount_point.path)

    def physical_device_id_for_path(self, path: Path) -> PhysicalDeviceId | None:
        requested = Path(os.path.realpath(path))
        try:
            matching = tuple(
                record
                for record in self._records()
                if requested == record.mount_point
                or requested.is_relative_to(record.mount_point)
            )
        except OSError as error:
            raise MountInspectionError(
                f"Could not read the Linux mount table: {error}"
            ) from error
        if not matching:
            raise MountInspectionError(f"No mounted Volume contains {requested}")
        record = max(matching, key=lambda item: len(os.fspath(item.mount_point)))
        identity = _linux_physical_device_identity(
            record,
            self.udev_properties_for_record(record),
            stable_only=True,
        )
        return PhysicalDeviceId(f"linux:{identity}") if identity is not None else None

    def flush(self, observation: VolumeObservation) -> FlushResult:
        if not shutil.which("sync"):
            return FlushResult(False, "the sync utility is unavailable")
        try:
            completed = subprocess.run(
                ["sync", "-f", os.fspath(observation.mount_point.path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return FlushResult(False, f"filesystem flush failed: {error}")
        detail = (completed.stderr or completed.stdout).strip()
        if completed.returncode != 0:
            return FlushResult(
                False,
                detail or f"sync exited with code {completed.returncode}",
            )
        return FlushResult(True, detail or "pending writes flushed")

    def eject(self, observation: VolumeObservation) -> EjectResult:
        mount_id = observation.mount_instance.removeprefix("linux-mount:")
        current = next(
            (
                record
                for record in self._records()
                if record.mount_id == mount_id
                and record.mount_point == observation.mount_point.path
            ),
            None,
        )
        if current is None:
            raise MountInspectionError(
                "The Linux mount changed before safe eject could begin"
            )
        return self._device_ejector.eject(current.source)

    def probe(
        self,
        observation: VolumeObservation,
        page_plan: ScsiVpdPagePlan | None = None,
    ) -> HardwareProbeResult:
        requested = Path(os.path.realpath(observation.mount_point.path))
        try:
            matching = tuple(
                record
                for record in self._records()
                if requested == record.mount_point
                or requested.is_relative_to(record.mount_point)
            )
        except OSError as error:
            return HardwareProbeResult(
                issues=(
                    HardwareProbeIssue(
                        HardwareProbeIssueCode.FAILED,
                        f"The Linux mount table could not be read: {error}",
                    ),
                )
            )
        if not matching:
            return HardwareProbeResult(
                issues=(
                    HardwareProbeIssue(
                        HardwareProbeIssueCode.FAILED,
                        "The Linux mount disappeared before its hardware probe.",
                    ),
                )
            )
        record = max(matching, key=lambda item: len(os.fspath(item.mount_point)))
        properties = self.udev_properties_for_record(record)
        udev_result = probe_from_udev_properties(properties)

        direct: HardwareProbeObservation | None = None
        for candidate in _block_device_candidates(record.source):
            try:
                direct = _probe_linux_scsi(candidate, page_plan)
            except OSError:
                continue
            if direct.vendor_payload or direct.unit_serial:
                break
        if direct is None or not (
            direct.vendor_payload
            or direct.unit_serial
            or direct.vendor
            or direct.product
        ):
            return udev_result

        issues = udev_result.issues
        if direct.unit_serial:
            issues = tuple(
                issue
                for issue in issues
                if issue.code is not HardwareProbeIssueCode.SETUP_REQUIRED
            )
        return HardwareProbeResult(
            observations=(direct, *udev_result.observations),
            issues=issues,
        )

    @staticmethod
    def _records() -> tuple[LinuxMountRecord, ...]:
        return parse_mountinfo(_MOUNTINFO.read_text(encoding="utf-8", errors="replace"))

    @staticmethod
    def _udev_properties(device_number: str) -> dict[str, str]:
        if not re.fullmatch(r"\d+:\d+", device_number):
            return {}
        try:
            content = (_UDEV_DATA / f"b{device_number}").read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return {}
        return parse_udev_properties(content)

    @classmethod
    def udev_properties_for_record(
        cls,
        record: LinuxMountRecord,
    ) -> dict[str, str]:
        """Read and merge whole-disk and mounted-partition udev properties."""

        properties: dict[str, str] = {}
        whole_disk_number = _whole_disk_device_number(record.source)
        if whole_disk_number:
            properties.update(cls._udev_properties(whole_disk_number))
        properties.update(cls._udev_properties(record.device_number))
        return properties

    @staticmethod
    def _observation(
        record: LinuxMountRecord,
        properties: dict[str, str],
    ) -> VolumeObservation:
        total, available = disk_usage(record.mount_point)
        unsafe_reasons: tuple[str, ...] = ()
        if (
            record.filesystem_type in {"hfs", "hfs+", "hfsplus", "hfsx"}
            and "force" in record.options
        ):
            unsafe_reasons = (
                "Linux HFS Volume is mounted with the unsafe 'force' option",
            )

        device_identity = _linux_physical_device_identity(
            record,
            properties,
            stable_only=False,
        )
        assert device_identity is not None
        volume_identity = (
            properties.get("ID_FS_UUID")
            or properties.get("ID_PART_ENTRY_UUID")
            or f"{record.device_number}:{record.source}"
        )
        label = properties.get("ID_FS_LABEL") or record.mount_point.name
        physical_id = PhysicalDeviceId(f"linux:{device_identity}")
        return VolumeObservation(
            physical_device=PhysicalDevice(
                id=physical_id,
                display_name=label or record.source,
                bus=(
                    DeviceBus.USB
                    if properties.get("ID_BUS") == "usb"
                    else DeviceBus.UNKNOWN
                ),
                removable=_is_removable(record, properties),
                identifiers=HardwareIdentifiers(
                    usb_vendor_id=_hex_identifier(properties.get("ID_VENDOR_ID")),
                    usb_product_id=_hex_identifier(properties.get("ID_MODEL_ID")),
                    # A USB mass-storage short serial can identify the transport
                    # rather than the marketed hardware unit.
                    transport_serial=properties.get("ID_SERIAL_SHORT", ""),
                ),
            ),
            volume=Volume(
                id=VolumeId(f"linux:{volume_identity}"),
                physical_device_id=physical_id,
                label=label,
                filesystem_type=record.filesystem_type,
                total_bytes=total,
                available_bytes=available,
                capabilities=capabilities(
                    record.mount_point,
                    filesystem_type=record.filesystem_type,
                    read_only="ro" in record.options,
                    unsafe_write_reasons=unsafe_reasons,
                ),
            ),
            mount_point=MountPoint(record.mount_point),
            mount_instance=f"linux-mount:{record.mount_id}",
        )


def _decode_mountinfo_field(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _unique_options(*values: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        for option in value.split(","):
            if option and option not in result:
                result.append(option)
    return tuple(result)


def _is_removable(
    record: LinuxMountRecord,
    properties: dict[str, str],
) -> bool:
    if properties.get("ID_BUS") in {"usb", "firewire"}:
        return True
    return properties.get("ID_DRIVE_FLASH") == "1" or record.source.startswith(
        "/dev/mmc"
    )


def _hex_identifier(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _linux_physical_device_identity(
    record: LinuxMountRecord,
    properties: dict[str, str],
    *,
    stable_only: bool,
) -> str | None:
    identity = properties.get("ID_SERIAL") or properties.get("ID_PATH")
    if identity:
        return identity
    whole_disk_number = _whole_disk_device_number(record.source)
    if whole_disk_number:
        return f"block:{whole_disk_number}"
    if stable_only:
        return None
    return f"{record.device_number}:{record.source}"


def probe_from_udev_properties(
    properties: dict[str, str],
) -> HardwareProbeResult:
    """Expose generic current udev facts without assigning domain semantics."""

    transport_serial = properties.get("ID_SERIAL_SHORT", "").strip()
    vendor = properties.get("ID_VENDOR", "").replace("_", " ").strip()
    product = properties.get("ID_MODEL", "").replace("_", " ").strip()
    firmware = properties.get("ID_REVISION", "").strip()
    host_properties = tuple(
        HardwareProperty(name, value)
        for name, value in sorted(properties.items())
        if name.strip() and value.strip()
    )
    observations: tuple[HardwareProbeObservation, ...] = ()
    if any((transport_serial, vendor, product, firmware, host_properties)):
        observations = (
            HardwareProbeObservation(
                source="udev",
                vendor=vendor,
                product=product,
                firmware_revision=firmware,
                transport_serial=transport_serial,
                host_properties=host_properties,
            ),
        )
    return HardwareProbeResult(observations=observations)


def _block_device_candidates(source: str) -> tuple[Path, ...]:
    source_path = Path(source)
    if not source.startswith("/dev/"):
        return ()
    resolved = source_path.resolve(strict=False)
    candidates: list[Path] = []
    sysfs_entry = _SYS_CLASS_BLOCK / resolved.name
    try:
        if (sysfs_entry / "partition").is_file():
            parent_name = sysfs_entry.resolve(strict=True).parent.name
            candidates.append(Path("/dev") / parent_name)
    except OSError:
        pass
    for candidate in (resolved, source_path):
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _whole_disk_device_number(source: str) -> str:
    if not source.startswith("/dev/"):
        return ""
    source_name = Path(source).resolve(strict=False).name
    sysfs_entry = _SYS_CLASS_BLOCK / source_name
    try:
        resolved_entry = sysfs_entry.resolve(strict=True)
        whole_disk = (
            resolved_entry.parent
            if (sysfs_entry / "partition").is_file()
            else resolved_entry
        )
        device_number = (whole_disk / "dev").read_text(encoding="ascii").strip()
    except OSError:
        return ""
    return device_number if re.fullmatch(r"\d+:\d+", device_number) else ""


def _probe_linux_scsi(
    device: Path,
    page_plan: ScsiVpdPagePlan | None,
) -> HardwareProbeObservation:
    descriptor = os.open(
        device,
        os.O_RDONLY | getattr(os, "O_NONBLOCK", 0),
    )
    try:

        def inquiry(*, evpd: bool, page: int, alloc_len: int) -> bytes:
            return _linux_scsi_inquiry(
                descriptor,
                evpd=evpd,
                page=page,
                alloc_len=alloc_len,
            )

        return collect_scsi_vpd(
            inquiry,
            source="linux_scsi",
            page_plan=page_plan,
        )
    finally:
        os.close(descriptor)


def _linux_scsi_inquiry(
    descriptor: int,
    *,
    evpd: bool,
    page: int,
    alloc_len: int,
) -> bytes:
    data = ctypes.create_string_buffer(alloc_len)
    sense = ctypes.create_string_buffer(64)
    command = (ctypes.c_ubyte * 6)(
        0x12,
        0x01 if evpd else 0x00,
        page & 0xFF,
        0,
        alloc_len & 0xFF,
        0,
    )
    header = _SgIoHeader()
    header.interface_id = ord("S")
    header.dxfer_direction = _SG_DXFER_FROM_DEVICE
    header.cmd_len = 6
    header.mx_sb_len = len(sense)
    header.dxfer_len = alloc_len
    header.dxferp = ctypes.cast(data, ctypes.c_void_p)
    header.cmdp = ctypes.cast(command, ctypes.c_void_p)
    header.sbp = ctypes.cast(sense, ctypes.c_void_p)
    header.timeout = 10_000

    ioctl = cast("_Ioctl", vars(__import__("fcntl"))["ioctl"])
    ioctl(descriptor, _SG_IO, header)
    status = header.status or header.host_status or header.driver_status
    if status:
        raise OSError(status, f"SCSI INQUIRY failed for page 0x{page:02X}")
    transferred = alloc_len - max(int(header.resid), 0)
    return bytes(data.raw[: max(0, min(transferred, alloc_len))])
