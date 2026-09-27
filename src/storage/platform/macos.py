"""macOS kernel reinspection with discovery-grade diskutil/IOKit enrichment."""

from __future__ import annotations

import ctypes
import functools
import logging
import os
import plistlib
import re
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from storage.errors import MountInspectionError
from storage.models import (
    DeviceBus,
    DiscoveryIssue,
    EjectResult,
    FlushResult,
    HardwareIdentifiers,
    HardwareProbeResult,
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
from storage.platform.macos_eject import MacOSDeviceEjector
from storage.platform.macos_vpd import probe_macos_scsi

if TYPE_CHECKING:
    from collections.abc import Mapping

_VOLUMES_DIRECTORY = Path("/Volumes")
_ATTR_CMN_RETURNED_ATTRS = 0x80000000
_ATTR_VOL_INFO = 0x80000000
_ATTR_VOL_CAPABILITIES = 0x00020000
_ATTR_VOL_UUID = 0x00040000
_VOL_CAP_FMT_CASE_SENSITIVE = 0x00000100
_MNT_RDONLY = 0x00000001
_MNT_NOFOLLOW = 0x08000000
_MNT_NOATIME = 0x10000000
_BSD_SOURCE_PATTERN = re.compile(r"^/dev/(disk\d+(?:s\d+)*)$")
_BSD_IDENTIFIER_PATTERN = re.compile(r"^(disk\d+)(?:s\d+)*$")
logger = logging.getLogger(__name__)


class _DarwinFSID(ctypes.Structure):
    _fields_ = (("val", ctypes.c_int32 * 2),)


class _DarwinStatFS(ctypes.Structure):
    _fields_ = (
        ("f_bsize", ctypes.c_uint32),
        ("f_iosize", ctypes.c_int32),
        ("f_blocks", ctypes.c_uint64),
        ("f_bfree", ctypes.c_uint64),
        ("f_bavail", ctypes.c_uint64),
        ("f_files", ctypes.c_uint64),
        ("f_ffree", ctypes.c_uint64),
        ("f_fsid", _DarwinFSID),
        ("f_owner", ctypes.c_uint32),
        ("f_type", ctypes.c_uint32),
        ("f_flags", ctypes.c_uint32),
        ("f_fssubtype", ctypes.c_uint32),
        ("f_fstypename", ctypes.c_char * 16),
        ("f_mntonname", ctypes.c_char * 1024),
        ("f_mntfromname", ctypes.c_char * 1024),
        ("f_flags_ext", ctypes.c_uint32),
        ("f_reserved", ctypes.c_uint32 * 7),
    )


class _DarwinAttrList(ctypes.Structure):
    _fields_ = (
        ("bitmapcount", ctypes.c_ushort),
        ("reserved", ctypes.c_ushort),
        ("commonattr", ctypes.c_uint32),
        ("volattr", ctypes.c_uint32),
        ("dirattr", ctypes.c_uint32),
        ("fileattr", ctypes.c_uint32),
        ("forkattr", ctypes.c_uint32),
    )


class _DarwinAttributeSet(ctypes.Structure):
    _fields_ = (
        ("commonattr", ctypes.c_uint32),
        ("volattr", ctypes.c_uint32),
        ("dirattr", ctypes.c_uint32),
        ("fileattr", ctypes.c_uint32),
        ("forkattr", ctypes.c_uint32),
    )


class _DarwinVolumeCapabilities(ctypes.Structure):
    _fields_ = (
        ("capabilities", ctypes.c_uint32 * 4),
        ("valid", ctypes.c_uint32 * 4),
    )


class _DarwinVolumeAttributeBuffer(ctypes.Structure):
    _fields_ = (
        ("length", ctypes.c_uint32),
        ("returned", _DarwinAttributeSet),
        ("volume_capabilities", _DarwinVolumeCapabilities),
        ("volume_uuid", ctypes.c_ubyte * 16),
    )


class _StatFSFunction(Protocol):
    argtypes: tuple[object, ...]
    restype: object

    def __call__(self, path: bytes, result: object, /) -> int: ...


class _GetAttrListFunction(Protocol):
    argtypes: tuple[object, ...]
    restype: object

    def __call__(
        self,
        path: bytes,
        request: object,
        result: object,
        result_size: int,
        options: int,
        /,
    ) -> int: ...


class MacOSPlatformAdapter:
    def __init__(self) -> None:
        self._device_ejector = MacOSDeviceEjector()

    @property
    def name(self) -> str:
        return "macos"

    def discover(self) -> ObservationDiscoveryResult:
        observations: list[VolumeObservation] = []
        issues: list[DiscoveryIssue] = []
        hardware_by_bsd_name = _ioreg_hardware_index()
        try:
            candidates = tuple(_VOLUMES_DIRECTORY.iterdir())
        except OSError as error:
            return ObservationDiscoveryResult(
                observations=(),
                issues=(DiscoveryIssue("macos.volumes", str(error)),),
            )
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            try:
                observation = self._inspect_full(candidate, hardware_by_bsd_name)
            except MountInspectionError as error:
                issues.append(DiscoveryIssue(os.fspath(candidate), str(error)))
                continue
            if observation.physical_device.removable:
                observations.append(observation)
        return ObservationDiscoveryResult(tuple(observations), tuple(issues))

    def inspect(self, mount_point: Path) -> VolumeObservation:
        return self._inspect_full(mount_point, _ioreg_hardware_index())

    def reinspect(self, retained: VolumeObservation) -> VolumeObservation:
        try:
            first = _read_statfs(retained.mount_point.path)
            _validate_statfs(first)
        except MountInspectionError:
            if retained.mount_instance.startswith("macos-vfs:"):
                raise
            return self._inspect_full(retained.mount_point.path, {}, retained)

        volume_uuid, case_sensitive = _read_volume_attributes(
            _statfs_mount_point(first)
        )
        if volume_uuid is None:
            info = _diskutil_info(_statfs_device_node(first))
            volume_uuid = _validate_diskutil_fallback(info, first)

        second = _read_statfs(_statfs_mount_point(first))
        _validate_statfs(second)
        _require_same_snapshot(first, second)
        return _observation_from_kernel(
            second,
            volume_uuid=volume_uuid,
            case_sensitive=case_sensitive,
            retained=retained,
        )

    def physical_device_id_for_path(self, path: Path) -> PhysicalDeviceId | None:
        identity = self.inspect(path).physical_device.id
        native = identity.value.removeprefix("macos:").removeprefix("/dev/")
        return identity if re.fullmatch(r"disk\d+", native) is not None else None

    def set_volume_label(self, observation: VolumeObservation, label: str) -> str:
        from storage.platform.macos_volume_metadata import set_label

        return set_label(observation.mount_point.path, label)

    def enable_volume_icon(self, observation: VolumeObservation) -> None:
        from storage.platform.macos_volume_metadata import enable_icon

        enable_icon(observation.mount_point.path)

    def _inspect_full(
        self,
        mount_point: Path,
        hardware_by_bsd_name: Mapping[str, HardwareIdentifiers],
        retained: VolumeObservation | None = None,
    ) -> VolumeObservation:
        first: _DarwinStatFS | None = None
        try:
            candidate = _read_statfs(mount_point)
            _validate_statfs(candidate)
            first = candidate
        except MountInspectionError:
            pass

        target = _statfs_device_node(first) if first is not None else mount_point
        info = _diskutil_info(target)
        if first is not None:
            try:
                volume_uuid, case_sensitive = _read_volume_attributes(
                    _statfs_mount_point(first)
                )
            except MountInspectionError:
                volume_uuid, case_sensitive = None, None
            fallback_uuid = _validate_diskutil_fallback(
                info,
                first,
                kernel_uuid=volume_uuid,
            )
            second = _read_statfs(_statfs_mount_point(first))
            _validate_statfs(second)
            _require_same_snapshot(first, second)
            return _observation_from_kernel(
                second,
                volume_uuid=volume_uuid or fallback_uuid,
                case_sensitive=case_sensitive,
                info=info,
                hardware_by_bsd_name=hardware_by_bsd_name,
                retained=retained,
            )
        return _observation_from_diskutil(info, mount_point, hardware_by_bsd_name)

    def flush(self, observation: VolumeObservation) -> FlushResult:
        del observation
        sync = vars(os).get("sync")
        if not callable(sync):
            return FlushResult(False, "filesystem flush is unavailable")
        try:
            sync()
        except OSError as error:
            return FlushResult(False, f"filesystem flush failed: {error}")
        return FlushResult(True, "pending writes flushed")

    def eject(self, observation: VolumeObservation) -> EjectResult:
        whole_disk = observation.physical_device.id.value.removeprefix("macos:")
        return self._device_ejector.eject(whole_disk)

    def probe(
        self,
        observation: VolumeObservation,
        page_plan: ScsiVpdPagePlan | None = None,
    ) -> HardwareProbeResult:
        identifiers = observation.physical_device.identifiers
        target_bsd_name = observation.physical_device.id.value.removeprefix(
            "macos:"
        ).removeprefix("/dev/")
        return probe_macos_scsi(
            usb_product_id=identifiers.usb_product_id,
            transport_serial=identifiers.transport_serial,
            target_bsd_name=target_bsd_name,
            page_plan=page_plan,
        )


def _observation_from_diskutil(
    info: dict[str, object],
    requested_mount: Path,
    hardware_by_bsd_name: Mapping[str, HardwareIdentifiers],
) -> VolumeObservation:
    actual_mount_text = _text(info, "MountPoint")
    if not actual_mount_text:
        raise MountInspectionError(f"No mounted Volume exists at {requested_mount}")
    actual_mount = Path(os.path.realpath(actual_mount_text))
    device_identifier = _text(info, "DeviceIdentifier")
    physical_identifier = (
        _text(info, "ParentWholeDisk") or _text(info, "DeviceNode") or device_identifier
    )
    volume_identifier = (
        _text(info, "VolumeUUID")
        or _text(info, "DiskUUID")
        or _text(info, "MediaUUID")
        or device_identifier
    )
    if not device_identifier or not physical_identifier or not volume_identifier:
        raise MountInspectionError(
            "diskutil did not provide complete device and Volume identity"
        )

    filesystem_type = (
        _text(info, "FilesystemType")
        or _text(info, "FilesystemName")
        or _text(info, "FilesystemPersonality")
    ).casefold()
    label = _text(info, "VolumeName") or actual_mount.name
    removable = (
        info.get("Internal") is False
        or info.get("RemovableMedia") is True
        or info.get("Ejectable") is True
    )
    protocol = (_text(info, "BusProtocol") or _text(info, "Protocol")).casefold()
    if protocol == "usb":
        bus = DeviceBus.USB
    elif protocol == "firewire":
        bus = DeviceBus.FIREWIRE
    else:
        bus = DeviceBus.UNKNOWN
    read_only = (
        info.get("Writable") is False
        or info.get("VolumeReadOnly") is True
        or info.get("ReadOnlyVolume") is True
    )
    allocation = _positive_int(info.get("AllocationBlockSize"))
    total, available = disk_usage(actual_mount)
    physical_id = PhysicalDeviceId(f"macos:{physical_identifier}")
    ioreg_identifiers = hardware_by_bsd_name.get(
        _bsd_name(physical_identifier),
        HardwareIdentifiers(),
    )
    return VolumeObservation(
        physical_device=PhysicalDevice(
            id=physical_id,
            display_name=label or physical_identifier,
            bus=bus,
            removable=removable,
            identifiers=HardwareIdentifiers(
                usb_vendor_id=(
                    _identifier(info, "USBVendorID", "VendorID")
                    or ioreg_identifiers.usb_vendor_id
                ),
                usb_product_id=(
                    _identifier(info, "USBProductID", "ProductID")
                    or ioreg_identifiers.usb_product_id
                ),
                transport_serial=(
                    _first_text(info, "USBSerialNumber")
                    or ioreg_identifiers.transport_serial
                ),
            ),
        ),
        volume=Volume(
            id=VolumeId(f"macos:{volume_identifier}"),
            physical_device_id=physical_id,
            label=label,
            filesystem_type=filesystem_type,
            total_bytes=total,
            available_bytes=available,
            capabilities=capabilities(
                actual_mount,
                filesystem_type=filesystem_type,
                read_only=read_only,
                known_allocation_unit=allocation,
            ),
        ),
        mount_point=MountPoint(actual_mount),
        mount_instance=f"macos-disk:{device_identifier}",
    )


def _observation_from_kernel(
    snapshot: _DarwinStatFS,
    *,
    volume_uuid: str,
    case_sensitive: bool | None,
    retained: VolumeObservation | None = None,
    info: dict[str, object] | None = None,
    hardware_by_bsd_name: Mapping[str, HardwareIdentifiers] | None = None,
) -> VolumeObservation:
    _validate_statfs(snapshot)
    mount_point = _statfs_mount_point(snapshot)
    device_identifier, whole_disk = _statfs_bsd_identifiers(snapshot)
    filesystem_type = _statfs_filesystem_type(snapshot)
    total, available = _statfs_byte_counts(snapshot)
    fsid_first, fsid_second = _statfs_fsid(snapshot)
    physical_id = PhysicalDeviceId(f"macos:{whole_disk}")
    volume_id = VolumeId(f"macos:{volume_uuid}")

    if retained is not None and retained.physical_device.id == physical_id:
        physical_device = retained.physical_device
    elif info is not None:
        label = _text(info, "VolumeName") or mount_point.name
        protocol = (_text(info, "BusProtocol") or _text(info, "Protocol")).casefold()
        bus = {
            "usb": DeviceBus.USB,
            "firewire": DeviceBus.FIREWIRE,
        }.get(protocol, DeviceBus.UNKNOWN)
        indexed = (hardware_by_bsd_name or {}).get(
            whole_disk,
            HardwareIdentifiers(),
        )
        physical_device = PhysicalDevice(
            id=physical_id,
            display_name=label or whole_disk,
            bus=bus,
            removable=(
                info.get("Internal") is False
                or info.get("RemovableMedia") is True
                or info.get("Ejectable") is True
            ),
            identifiers=HardwareIdentifiers(
                usb_vendor_id=(
                    _identifier(info, "USBVendorID", "VendorID")
                    or indexed.usb_vendor_id
                ),
                usb_product_id=(
                    _identifier(info, "USBProductID", "ProductID")
                    or indexed.usb_product_id
                ),
                transport_serial=(
                    _first_text(info, "USBSerialNumber") or indexed.transport_serial
                ),
            ),
        )
    else:
        physical_device = PhysicalDevice(
            id=physical_id,
            display_name=whole_disk,
            bus=DeviceBus.UNKNOWN,
            removable=False,
        )

    label = _text(info, "VolumeName") if info is not None else ""
    if (
        retained is not None
        and retained.physical_device.id == physical_id
        and retained.volume.id == volume_id
    ):
        label = retained.volume.label
    return VolumeObservation(
        physical_device=physical_device,
        volume=Volume(
            id=volume_id,
            physical_device_id=physical_id,
            label=label,
            filesystem_type=filesystem_type,
            total_bytes=total,
            available_bytes=available,
            capabilities=capabilities(
                mount_point,
                filesystem_type=filesystem_type,
                read_only=bool(snapshot.f_flags & _MNT_RDONLY),
                known_allocation_unit=int(snapshot.f_bsize),
                known_case_sensitive=case_sensitive,
            ),
        ),
        mount_point=MountPoint(mount_point),
        mount_instance=(
            f"macos-vfs:{device_identifier}:"
            f"{fsid_first & 0xFFFFFFFF:08x}:{fsid_second & 0xFFFFFFFF:08x}"
        ),
    )


@functools.lru_cache(maxsize=1)
def _load_libc() -> ctypes.CDLL:
    try:
        return ctypes.CDLL(None, use_errno=True)
    except (OSError, TypeError) as error:
        raise MountInspectionError(f"Could not load macOS Libc: {error}") from error


def _bind_statfs(libc: object) -> _StatFSFunction:
    function: _StatFSFunction | None = None
    for symbol in ("statfs$INODE64", "statfs"):
        try:
            function = cast("_StatFSFunction", getattr(libc, symbol))
        except AttributeError:
            continue
        break
    if function is None:
        raise MountInspectionError("macOS Libc does not expose a usable statfs")
    function.argtypes = (
        ctypes.c_char_p,
        ctypes.POINTER(_DarwinStatFS),
    )
    function.restype = ctypes.c_int
    return function


@functools.lru_cache(maxsize=1)
def _statfs_function() -> _StatFSFunction:
    return _bind_statfs(_load_libc())


def _bind_getattrlist(libc: object) -> _GetAttrListFunction:
    try:
        function = cast("_GetAttrListFunction", cast("Any", libc).getattrlist)
    except AttributeError as error:
        raise MountInspectionError("macOS Libc does not expose getattrlist") from error
    function.argtypes = (
        ctypes.c_char_p,
        ctypes.POINTER(_DarwinAttrList),
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    return function


@functools.lru_cache(maxsize=1)
def _getattrlist_function() -> _GetAttrListFunction:
    return _bind_getattrlist(_load_libc())


def _read_statfs(path: Path) -> _DarwinStatFS:
    snapshot = _DarwinStatFS()
    ctypes.set_errno(0)
    result = int(_statfs_function()(os.fsencode(path), ctypes.byref(snapshot)))
    if result == -1:
        error_number = ctypes.get_errno()
        detail = os.strerror(error_number) if error_number else "unknown error"
        raise MountInspectionError(f"statfs failed for {path}: {detail}")
    if result != 0:
        raise MountInspectionError(
            f"statfs returned unexpected result {result} for {path}"
        )
    return snapshot


def _read_volume_attributes(path: Path) -> tuple[str | None, bool | None]:
    request = _DarwinAttrList(
        bitmapcount=5,
        reserved=0,
        commonattr=_ATTR_CMN_RETURNED_ATTRS,
        volattr=_ATTR_VOL_INFO | _ATTR_VOL_CAPABILITIES | _ATTR_VOL_UUID,
        dirattr=0,
        fileattr=0,
        forkattr=0,
    )
    result_buffer = _DarwinVolumeAttributeBuffer()
    ctypes.set_errno(0)
    result = int(
        _getattrlist_function()(
            os.fsencode(path),
            ctypes.byref(request),
            ctypes.byref(result_buffer),
            ctypes.sizeof(result_buffer),
            0,
        )
    )
    if result == -1:
        error_number = ctypes.get_errno()
        detail = os.strerror(error_number) if error_number else "unknown error"
        raise MountInspectionError(f"getattrlist failed for {path}: {detail}")
    if result != 0:
        raise MountInspectionError(
            f"getattrlist returned unexpected result {result} for {path}"
        )
    return _parse_volume_attributes(result_buffer)


def _parse_volume_attributes(
    result: _DarwinVolumeAttributeBuffer,
) -> tuple[str | None, bool | None]:
    length = int(result.length)
    returned_end = _DarwinVolumeAttributeBuffer.returned.offset + ctypes.sizeof(
        _DarwinAttributeSet
    )
    if length < returned_end or length > ctypes.sizeof(result):
        return None, None

    returned = int(result.returned.volattr)
    case_sensitive: bool | None = None
    capabilities_end = (
        _DarwinVolumeAttributeBuffer.volume_capabilities.offset
        + ctypes.sizeof(_DarwinVolumeCapabilities)
    )
    if returned & _ATTR_VOL_CAPABILITIES and length >= capabilities_end:
        valid = int(result.volume_capabilities.valid[0])
        if valid & _VOL_CAP_FMT_CASE_SENSITIVE:
            case_sensitive = bool(
                result.volume_capabilities.capabilities[0] & _VOL_CAP_FMT_CASE_SENSITIVE
            )

    volume_uuid: str | None = None
    uuid_end = _DarwinVolumeAttributeBuffer.volume_uuid.offset + ctypes.sizeof(
        result.volume_uuid
    )
    if returned & _ATTR_VOL_UUID and length >= uuid_end:
        raw_uuid = bytes(result.volume_uuid)
        if any(raw_uuid):
            volume_uuid = str(uuid.UUID(bytes=raw_uuid)).upper()
    return volume_uuid, case_sensitive


def _decode_required_c_string(
    value: bytes,
    *,
    name: str,
    filesystem_type: bool = False,
) -> str:
    raw = value.split(b"\0", maxsplit=1)[0]
    if filesystem_type:
        decoded = raw.decode("ascii", errors="replace").casefold()
    else:
        decoded = os.fsdecode(raw)
    if not decoded:
        raise MountInspectionError(f"statfs returned an empty {name}")
    return decoded


def _statfs_mount_point(snapshot: _DarwinStatFS) -> Path:
    text = _decode_required_c_string(
        bytes(snapshot.f_mntonname),
        name="Mount Point",
    )
    return Path(os.path.realpath(text))


def _statfs_mounted_source(snapshot: _DarwinStatFS) -> str:
    return _decode_required_c_string(
        bytes(snapshot.f_mntfromname),
        name="mounted source",
    )


def _statfs_filesystem_type(snapshot: _DarwinStatFS) -> str:
    return _decode_required_c_string(
        bytes(snapshot.f_fstypename),
        name="filesystem type",
        filesystem_type=True,
    )


def _bsd_identifiers(mounted_source: str) -> tuple[str, str]:
    source_match = _BSD_SOURCE_PATTERN.fullmatch(mounted_source)
    if source_match is None:
        raise MountInspectionError(
            f"The mounted source is not a local BSD device: {mounted_source}"
        )
    device_identifier = source_match.group(1)
    identifier_match = _BSD_IDENTIFIER_PATTERN.fullmatch(device_identifier)
    if identifier_match is None:
        raise MountInspectionError(
            f"The BSD device identifier is malformed: {device_identifier}"
        )
    return device_identifier, identifier_match.group(1)


def _statfs_bsd_identifiers(snapshot: _DarwinStatFS) -> tuple[str, str]:
    return _bsd_identifiers(_statfs_mounted_source(snapshot))


def _statfs_device_node(snapshot: _DarwinStatFS) -> Path:
    device_identifier, _ = _statfs_bsd_identifiers(snapshot)
    return Path(f"/dev/{device_identifier}")


def _statfs_fsid(snapshot: _DarwinStatFS) -> tuple[int, int]:
    return int(snapshot.f_fsid.val[0]), int(snapshot.f_fsid.val[1])


def _statfs_byte_counts(snapshot: _DarwinStatFS) -> tuple[int, int]:
    block_size = int(snapshot.f_bsize)
    if block_size <= 0:
        raise MountInspectionError("statfs returned a non-positive block size")
    total = block_size * int(snapshot.f_blocks)
    available = block_size * int(snapshot.f_bavail)
    if available > total:
        raise MountInspectionError(
            "statfs returned available bytes greater than total bytes"
        )
    return total, available


def _validate_statfs(snapshot: _DarwinStatFS) -> None:
    _statfs_mount_point(snapshot)
    _statfs_bsd_identifiers(snapshot)
    _statfs_filesystem_type(snapshot)
    _statfs_byte_counts(snapshot)
    if _statfs_fsid(snapshot) == (0, 0):
        raise MountInspectionError("statfs returned an incomplete mount identity")


def _snapshot_identity(snapshot: _DarwinStatFS) -> tuple[str, str, int, int, str]:
    device_identifier, _ = _statfs_bsd_identifiers(snapshot)
    fsid_first, fsid_second = _statfs_fsid(snapshot)
    return (
        os.path.normcase(os.fspath(_statfs_mount_point(snapshot))),
        device_identifier,
        fsid_first,
        fsid_second,
        _statfs_filesystem_type(snapshot),
    )


def _require_same_snapshot(
    first: _DarwinStatFS,
    second: _DarwinStatFS,
) -> None:
    if _snapshot_identity(first) != _snapshot_identity(second):
        raise MountInspectionError(
            "The mounted Volume changed while macOS was inspecting it"
        )


def _normalized_uuid(value: str) -> str:
    try:
        parsed = uuid.UUID(value.strip())
    except (AttributeError, ValueError) as error:
        raise MountInspectionError(
            "diskutil did not provide a valid Volume UUID"
        ) from error
    if parsed.int == 0:
        raise MountInspectionError("diskutil returned an all-zero Volume UUID")
    return str(parsed).upper()


def _fallback_uuid(info: dict[str, object]) -> str:
    value = (
        _text(info, "VolumeUUID") or _text(info, "DiskUUID") or _text(info, "MediaUUID")
    )
    if not value:
        raise MountInspectionError("diskutil did not provide a stable Volume identity")
    return _normalized_uuid(value)


def _validate_diskutil_fallback(
    info: dict[str, object],
    snapshot: _DarwinStatFS,
    *,
    kernel_uuid: str | None = None,
) -> str:
    device_identifier, whole_disk = _statfs_bsd_identifiers(snapshot)
    if _text(info, "DeviceIdentifier") != device_identifier:
        raise MountInspectionError(
            "diskutil described a different BSD device than statfs"
        )
    device_node = _text(info, "DeviceNode")
    if device_node and device_node != f"/dev/{device_identifier}":
        raise MountInspectionError(
            "diskutil described a different device node than statfs"
        )
    parent_whole_disk = _text(info, "ParentWholeDisk")
    if parent_whole_disk and parent_whole_disk != whole_disk:
        raise MountInspectionError(
            "diskutil described a different whole disk than statfs"
        )
    fallback_mount = _text(info, "MountPoint")
    if fallback_mount and (
        os.path.normcase(os.path.realpath(fallback_mount))
        != os.path.normcase(os.fspath(_statfs_mount_point(snapshot)))
    ):
        raise MountInspectionError(
            "diskutil described a different Mount Point than statfs"
        )
    fallback_uuid = _fallback_uuid(info)
    if kernel_uuid is not None and fallback_uuid != _normalized_uuid(kernel_uuid):
        raise MountInspectionError(
            "diskutil and the kernel reported different Volume identities"
        )
    return fallback_uuid


def _diskutil_info(target: Path) -> dict[str, object]:
    try:
        completed = subprocess.run(
            ["diskutil", "info", "-plist", os.fspath(target)],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MountInspectionError(f"Could not run diskutil: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode(
            "utf-8", errors="replace"
        )
        raise MountInspectionError(detail.strip() or "diskutil info failed")
    try:
        parsed = plistlib.loads(completed.stdout)
    except (plistlib.InvalidFileException, TypeError, ValueError) as error:
        raise MountInspectionError(
            f"Could not parse diskutil output: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise MountInspectionError("diskutil returned an unexpected response")
    return cast("dict[str, object]", parsed)


def _ioreg_hardware_index() -> dict[str, HardwareIdentifiers]:
    """Correlate mounted BSD disks with generic USB hardware observations."""

    media_output = _run_ioreg(["ioreg", "-r", "-c", "IOMedia"])
    devices_output = _run_ioreg(["ioreg", "-a", "-r", "-c", "IOUSBHostDevice"])
    if not media_output or not devices_output:
        return {}
    bsd_to_serial = _parse_ioreg_media_serials(
        media_output.decode("utf-8", errors="replace")
    )
    serial_to_identifiers = _parse_ioreg_usb_devices(devices_output)
    return {
        bsd_name: identifiers
        for bsd_name, serial in bsd_to_serial.items()
        if (identifiers := serial_to_identifiers.get(serial)) is not None
    }


def _run_ioreg(command: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.debug("Could not inspect the macOS I/O Registry: %s", error)
        return b""
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode(
            "utf-8",
            errors="replace",
        )
        logger.debug("ioreg failed: %s", detail.strip())
        return b""
    return completed.stdout


def _parse_ioreg_media_serials(text: str) -> dict[str, str]:
    """Map each BSD whole disk to its owning USB transport serial."""

    result: dict[str, str] = {}
    current_serial = ""
    pending_serial = ""
    for line in text.splitlines():
        if "<class IOUSBHostDevice" in line:
            current_serial = ""
            pending_serial = ""
        serial_match = re.search(
            r'"USB Serial Number"\s*=\s*"([^"]+)"',
            line,
        )
        if serial_match is not None:
            current_serial = _normalized_transport_serial(serial_match.group(1))
            continue
        if "<class IOMedia" in line:
            pending_serial = current_serial
            continue
        bsd_match = re.search(r'"BSD Name"\s*=\s*"(disk\d+)"', line)
        if bsd_match is not None and pending_serial:
            result[bsd_match.group(1)] = pending_serial
            pending_serial = ""
    return result


def _parse_ioreg_usb_devices(payload: bytes) -> dict[str, HardwareIdentifiers]:
    try:
        parsed: object = plistlib.loads(payload)
    except (plistlib.InvalidFileException, TypeError, ValueError):
        return {}

    result: dict[str, HardwareIdentifiers] = {}

    def collect(node: object) -> None:
        if isinstance(node, list):
            for item in cast("list[object]", node):
                collect(item)
            return
        if not isinstance(node, dict):
            return
        properties = cast("dict[object, object]", node)
        serial_value = properties.get("USB Serial Number") or properties.get(
            "kUSBSerialNumberString"
        )
        serial = (
            _normalized_transport_serial(serial_value)
            if isinstance(serial_value, str)
            else ""
        )
        vendor_id = _object_identifier(properties.get("idVendor"))
        product_id = _object_identifier(properties.get("idProduct"))
        if serial and vendor_id is not None and product_id is not None:
            result[serial] = HardwareIdentifiers(
                usb_vendor_id=vendor_id,
                usb_product_id=product_id,
                transport_serial=serial,
            )
        children = properties.get("IORegistryEntryChildren")
        if isinstance(children, list):
            collect(cast("list[object]", children))

    collect(parsed)
    return result


def _bsd_name(value: str) -> str:
    normalized = value.removeprefix("/dev/")
    match = re.match(r"^(disk\d+)", normalized)
    return match.group(1) if match is not None else normalized


def _normalized_transport_serial(value: str) -> str:
    return value.replace(" ", "").strip().upper()


def _object_identifier(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 0xFFFF else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    for base in (0, 16):
        try:
            parsed = int(text, base)
        except ValueError:
            continue
        return parsed if 0 <= parsed <= 0xFFFF else None
    return None


def _text(info: dict[str, object], key: str) -> str:
    value = info.get(key)
    return value.strip() if isinstance(value, str) else ""


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | str):
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _identifier(info: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        value = info.get(key)
        if isinstance(value, str):
            text = value.strip()
            try:
                parsed = int(text, 0)
            except ValueError:
                try:
                    parsed = int(text, 16)
                except ValueError:
                    continue
        elif isinstance(value, int) and not isinstance(value, bool):
            parsed = value
        else:
            continue
        if 0 <= parsed <= 0xFFFF:
            return parsed
    return None


def _first_text(info: dict[str, object], *keys: str) -> str:
    return next((value for key in keys if (value := _text(info, key))), "")
