"""Windows removable-volume discovery through checked Win32 calls."""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from storage.errors import MountInspectionError, UnsupportedStorageOperationError
from storage.models import (
    DeviceBus,
    DiscoveryIssue,
    EjectResult,
    FlushResult,
    HardwareProbeIssue,
    HardwareProbeIssueCode,
    HardwareProbeResult,
    MountPoint,
    PhysicalDevice,
    PhysicalDeviceId,
    ScsiVpdPagePlan,
    StorageCapabilities,
    Volume,
    VolumeId,
    VolumeObservation,
)
from storage.platform.base import ObservationDiscoveryResult
from storage.platform.windows_eject import WindowsDeviceEjector
from storage.scsi_vpd import collect_scsi_vpd

_DRIVE_REMOVABLE = 2
_FILE_DEVICE_DISK = 0x00000007
_FILE_READ_ONLY_VOLUME = 0x00080000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_OPEN_EXISTING = 3
_VOLUME_NAME_GUID = 0x00000001
_IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x0004D014
_SCSI_IOCTL_DATA_IN = 1

_VOLUME_GUID_PREFIX = re.compile(
    r"^(\\\\\?\\Volume\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\})(?:\\|$)",
    re.IGNORECASE,
)
_WINDOWS_DISK_ID = re.compile(r"^windows:disk-(\d+)$")


class _StorageDeviceNumber(ctypes.Structure):
    _fields_ = [
        ("device_type", wintypes.DWORD),
        ("device_number", wintypes.DWORD),
        ("partition_number", wintypes.DWORD),
    ]


@dataclass(frozen=True)
class _StorageDeviceIdentity:
    device_type: int
    device_number: int


class _WindowsVolumeApi(Protocol):
    def open_path(self, path: Path) -> int | None: ...

    def final_volume_guid_path(self, handle: int) -> str | None: ...

    def open_volume(self, volume_guid_path: str) -> int | None: ...

    def storage_device(self, handle: int) -> _StorageDeviceIdentity | None: ...

    def close(self, handle: int) -> None: ...


class _WindowsPhysicalDeviceLookup:
    """Resolve a Host path to its containing physical disk without path guessing."""

    def __init__(self, api: _WindowsVolumeApi) -> None:
        self._api = api

    def for_path(self, path: Path) -> PhysicalDeviceId | None:
        path_handle = self._api.open_path(path)
        if path_handle is None:
            return None
        try:
            final_path = self._api.final_volume_guid_path(path_handle)
        finally:
            self._api.close(path_handle)
        if final_path is None:
            return None

        match = _VOLUME_GUID_PREFIX.match(final_path)
        if match is None:
            return None
        volume_handle = self._api.open_volume(match.group(1))
        if volume_handle is None:
            return None
        try:
            device = self._api.storage_device(volume_handle)
        finally:
            self._api.close(volume_handle)
        if device is None or device.device_type != _FILE_DEVICE_DISK:
            return None
        return PhysicalDeviceId(f"windows:disk-{device.device_number}")


class _CtypesWindowsVolumeApi:
    def __init__(self, kernel32: object) -> None:
        self._kernel32 = kernel32

    def open_path(self, path: Path) -> int | None:
        handle = cast(
            "object",
            self._kernel32.CreateFileW(  # type: ignore[attr-defined]
                os.fspath(path),
                0,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
                None,
                _OPEN_EXISTING,
                _FILE_FLAG_BACKUP_SEMANTICS,
                None,
            ),
        )
        return _usable_handle(handle)

    def final_volume_guid_path(self, handle: int) -> str | None:
        required = int(
            self._kernel32.GetFinalPathNameByHandleW(  # type: ignore[attr-defined]
                handle,
                None,
                0,
                _VOLUME_NAME_GUID,
            )
        )
        if required <= 0:
            return None
        buffer = ctypes.create_unicode_buffer(required + 1)
        copied = int(
            self._kernel32.GetFinalPathNameByHandleW(  # type: ignore[attr-defined]
                handle,
                buffer,
                len(buffer),
                _VOLUME_NAME_GUID,
            )
        )
        if copied <= 0 or copied >= len(buffer):
            return None
        return buffer.value

    def open_volume(self, volume_guid_path: str) -> int | None:
        handle = cast(
            "object",
            self._kernel32.CreateFileW(  # type: ignore[attr-defined]
                volume_guid_path,
                0,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
                None,
                _OPEN_EXISTING,
                0,
                None,
            ),
        )
        return _usable_handle(handle)

    def storage_device(self, handle: int) -> _StorageDeviceIdentity | None:
        result = _StorageDeviceNumber()
        returned = wintypes.DWORD()
        succeeded = self._kernel32.DeviceIoControl(  # type: ignore[attr-defined]
            handle,
            _IOCTL_STORAGE_GET_DEVICE_NUMBER,
            None,
            0,
            ctypes.byref(result),
            ctypes.sizeof(result),
            ctypes.byref(returned),
            None,
        )
        if not succeeded:
            return None
        return _StorageDeviceIdentity(
            device_type=int(result.device_type),
            device_number=int(result.device_number),
        )

    def close(self, handle: int) -> None:
        self._kernel32.CloseHandle(handle)  # type: ignore[attr-defined]


def _usable_handle(handle: object) -> int | None:
    if handle is None or handle == _INVALID_HANDLE_VALUE:
        return None
    if isinstance(handle, int):
        return handle
    if isinstance(handle, ctypes.c_void_p):
        return handle.value
    return None


class _ScsiPassThroughDirect(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ushort),
        ("scsi_status", ctypes.c_ubyte),
        ("path_id", ctypes.c_ubyte),
        ("target_id", ctypes.c_ubyte),
        ("lun", ctypes.c_ubyte),
        ("cdb_length", ctypes.c_ubyte),
        ("sense_info_length", ctypes.c_ubyte),
        ("data_in", ctypes.c_ubyte),
        ("data_transfer_length", ctypes.c_ulong),
        ("timeout_seconds", ctypes.c_ulong),
        ("data_buffer", ctypes.c_void_p),
        ("sense_info_offset", ctypes.c_ulong),
        ("cdb", ctypes.c_ubyte * 16),
    ]


class WindowsPlatformAdapter:
    def __init__(self) -> None:
        win_dll: Any = vars(ctypes)["WinDLL"]
        self._kernel32: Any = win_dll("kernel32", use_last_error=True)
        self._configure_api()
        self._physical_device_lookup = _WindowsPhysicalDeviceLookup(
            _CtypesWindowsVolumeApi(self._kernel32)
        )
        self._device_ejector = WindowsDeviceEjector()

    @property
    def name(self) -> str:
        return "windows"

    def discover(self) -> ObservationDiscoveryResult:
        observations: list[VolumeObservation] = []
        issues: list[DiscoveryIssue] = []
        bitmask = int(self._kernel32.GetLogicalDrives())
        for index in range(26):
            if not bitmask & (1 << index):
                continue
            root = Path(f"{chr(65 + index)}:\\")
            if int(self._kernel32.GetDriveTypeW(os.fspath(root))) != _DRIVE_REMOVABLE:
                continue
            try:
                observations.append(self.inspect(root))
            except MountInspectionError as error:
                issues.append(DiscoveryIssue(os.fspath(root), str(error)))
        return ObservationDiscoveryResult(tuple(observations), tuple(issues))

    def inspect(self, mount_point: Path) -> VolumeObservation:
        root = _volume_root(mount_point)
        volume_label = ctypes.create_unicode_buffer(261)
        filesystem_name = ctypes.create_unicode_buffer(261)
        serial = wintypes.DWORD()
        max_component = wintypes.DWORD()
        flags = wintypes.DWORD()
        succeeded = self._kernel32.GetVolumeInformationW(
            os.fspath(root),
            volume_label,
            len(volume_label),
            ctypes.byref(serial),
            ctypes.byref(max_component),
            ctypes.byref(flags),
            filesystem_name,
            len(filesystem_name),
        )
        if not succeeded:
            raise _windows_error(f"Could not inspect Windows Volume {root}")

        volume_name = ctypes.create_unicode_buffer(1024)
        has_volume_name = self._kernel32.GetVolumeNameForVolumeMountPointW(
            os.fspath(root), volume_name, len(volume_name)
        )
        volume_guid = volume_name.value if has_volume_name else ""
        if not volume_guid:
            raise MountInspectionError(
                f"Windows did not provide a stable Volume identity for {root}"
            )

        sectors_per_cluster = wintypes.DWORD()
        bytes_per_sector = wintypes.DWORD()
        free_clusters = wintypes.DWORD()
        total_clusters = wintypes.DWORD()
        has_geometry = self._kernel32.GetDiskFreeSpaceW(
            os.fspath(root),
            ctypes.byref(sectors_per_cluster),
            ctypes.byref(bytes_per_sector),
            ctypes.byref(free_clusters),
            ctypes.byref(total_clusters),
        )
        allocation_unit = (
            int(sectors_per_cluster.value * bytes_per_sector.value)
            if has_geometry
            else None
        )

        free_to_caller = ctypes.c_ulonglong()
        total_bytes = ctypes.c_ulonglong()
        total_free = ctypes.c_ulonglong()
        has_usage = self._kernel32.GetDiskFreeSpaceExW(
            os.fspath(root),
            ctypes.byref(free_to_caller),
            ctypes.byref(total_bytes),
            ctypes.byref(total_free),
        )
        if not has_usage:
            raise _windows_error(f"Could not inspect free space for {root}")

        device_number = self._device_number(root)
        physical_key = (
            f"disk-{device_number}" if device_number is not None else volume_guid
        )
        physical_id = PhysicalDeviceId(f"windows:{physical_key}")
        filesystem_type = filesystem_name.value.strip().casefold()
        read_only = bool(flags.value & _FILE_READ_ONLY_VOLUME)
        removable = (
            int(self._kernel32.GetDriveTypeW(os.fspath(root))) == _DRIVE_REMOVABLE
        )
        label = volume_label.value.strip() or root.drive
        max_file_size = (
            4 * 1024**3 - 1 if filesystem_type in {"fat32", "vfat", "msdos"} else None
        )
        return VolumeObservation(
            physical_device=PhysicalDevice(
                id=physical_id,
                display_name=label,
                bus=DeviceBus.UNKNOWN,
                removable=removable,
            ),
            volume=Volume(
                id=VolumeId(f"windows:{volume_guid}:{serial.value:08X}"),
                physical_device_id=physical_id,
                label=label,
                filesystem_type=filesystem_type,
                total_bytes=int(total_bytes.value),
                available_bytes=int(free_to_caller.value),
                capabilities=StorageCapabilities(
                    readable=os.access(root, os.R_OK),
                    writable=not read_only and os.access(root, os.W_OK),
                    case_sensitive=False,
                    max_file_size_bytes=max_file_size,
                    max_component_length=(
                        int(max_component.value) if max_component.value else None
                    ),
                    allocation_unit_size=(
                        allocation_unit
                        if allocation_unit and allocation_unit > 0
                        else None
                    ),
                ),
            ),
            mount_point=MountPoint(root),
            mount_instance=f"windows-volume:{volume_guid}",
        )

    def reinspect(self, retained: VolumeObservation) -> VolumeObservation:
        return self.inspect(retained.mount_point.path)

    def set_volume_label(self, observation: VolumeObservation, label: str) -> str:
        if observation.volume.label == label:
            return label
        function = self._kernel32.SetVolumeLabelW
        function.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        function.restype = wintypes.BOOL
        # A retained Volume GUID cannot be redirected by reassigning a drive letter.
        root = observation.mount_instance.removeprefix("windows-volume:")
        if not root.startswith("\\\\?\\Volume{") or not root.endswith("}\\"):
            raise MountInspectionError("Missing Windows Volume GUID")
        if not function(root, label):
            raise _windows_error("Could not update the Volume label")
        return self.inspect(observation.mount_point.path).volume.label

    def enable_volume_icon(self, observation: VolumeObservation) -> None:
        # Explorer reads the ordinary autorun.inf companion; no native flag is needed.
        pass

    def physical_device_id_for_path(self, path: Path) -> PhysicalDeviceId | None:
        return self._physical_device_lookup.for_path(path)

    def flush(self, observation: VolumeObservation) -> FlushResult:
        if not observation.volume.capabilities.writable:
            return FlushResult(True, "read-only Volume has no application writes")
        root = observation.mount_point.path
        device_path = f"\\\\.\\{root.drive.rstrip(':')}:"
        handle = self._kernel32.CreateFileW(
            device_path,
            _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            error = _last_error()
            return FlushResult(
                False, f"volume flush could not open the Volume: {error}"
            )
        try:
            if not self._kernel32.FlushFileBuffers(handle):
                error = _last_error()
                return FlushResult(False, f"FlushFileBuffers failed: {error}")
        finally:
            self._kernel32.CloseHandle(handle)
        return FlushResult(True, "pending writes flushed")

    def eject(self, observation: VolumeObservation) -> EjectResult:
        match = _WINDOWS_DISK_ID.fullmatch(observation.physical_device.id.value)
        if match is None:
            raise UnsupportedStorageOperationError(
                "Windows could not identify the iPod's exact physical disk. "
                "Use Safely Remove Hardware in the Windows taskbar."
            )
        return self._device_ejector.eject(int(match.group(1)))

    def probe(
        self,
        observation: VolumeObservation,
        page_plan: ScsiVpdPagePlan | None = None,
    ) -> HardwareProbeResult:
        root = observation.mount_point.path
        device_path = f"\\\\.\\{root.drive.rstrip(':')}:"
        handle = self._kernel32.CreateFileW(
            device_path,
            _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            error = _last_error()
            code = (
                HardwareProbeIssueCode.ACCESS_DENIED
                if error == 5
                else HardwareProbeIssueCode.FAILED
            )
            return HardwareProbeResult(
                issues=(
                    HardwareProbeIssue(
                        code,
                        "Windows could not open the selected Volume for a "
                        f"read-only SCSI identity probe (error {error}).",
                    ),
                )
            )
        try:

            def inquiry(*, evpd: bool, page: int, alloc_len: int) -> bytes:
                return self._scsi_inquiry(
                    handle,
                    evpd=evpd,
                    page=page,
                    alloc_len=alloc_len,
                )

            observation_result = collect_scsi_vpd(
                inquiry,
                source="windows_scsi",
                page_plan=page_plan,
            )
        finally:
            self._kernel32.CloseHandle(handle)

        if any(
            (
                observation_result.vendor,
                observation_result.product,
                observation_result.firmware_revision,
                observation_result.unit_serial,
                observation_result.vendor_payload,
            )
        ):
            return HardwareProbeResult(observations=(observation_result,))
        return HardwareProbeResult(
            issues=(
                HardwareProbeIssue(
                    HardwareProbeIssueCode.FAILED,
                    "The selected Windows device did not return SCSI identity data.",
                ),
            )
        )

    def _scsi_inquiry(
        self,
        handle: int,
        *,
        evpd: bool,
        page: int,
        alloc_len: int,
    ) -> bytes:
        data = ctypes.create_string_buffer(alloc_len)
        request = _ScsiPassThroughDirect()
        request.length = ctypes.sizeof(_ScsiPassThroughDirect)
        request.cdb_length = 6
        request.data_in = _SCSI_IOCTL_DATA_IN
        request.data_transfer_length = alloc_len
        request.timeout_seconds = 10
        request.data_buffer = ctypes.cast(data, ctypes.c_void_p)
        command = bytes(
            (0x12, 0x01 if evpd else 0x00, page & 0xFF, 0, alloc_len & 0xFF, 0)
        )
        for index, byte in enumerate(command):
            request.cdb[index] = byte

        returned = wintypes.DWORD()
        succeeded = self._kernel32.DeviceIoControl(
            handle,
            _IOCTL_SCSI_PASS_THROUGH_DIRECT,
            ctypes.byref(request),
            ctypes.sizeof(request),
            ctypes.byref(request),
            ctypes.sizeof(request),
            ctypes.byref(returned),
            None,
        )
        if not succeeded:
            error = _last_error()
            raise OSError(
                error,
                f"SCSI INQUIRY failed for page 0x{page:02X}",
            )
        if request.scsi_status:
            raise OSError(
                request.scsi_status,
                f"SCSI status for page 0x{page:02X}",
            )
        transferred = min(int(request.data_transfer_length), alloc_len)
        return bytes(data.raw[:transferred])

    def _device_number(self, root: Path) -> int | None:
        device_path = f"\\\\.\\{root.drive.rstrip(':')}:"
        handle = self._kernel32.CreateFileW(
            device_path,
            0,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            return None
        result = _StorageDeviceNumber()
        returned = wintypes.DWORD()
        try:
            succeeded = self._kernel32.DeviceIoControl(
                handle,
                _IOCTL_STORAGE_GET_DEVICE_NUMBER,
                None,
                0,
                ctypes.byref(result),
                ctypes.sizeof(result),
                ctypes.byref(returned),
                None,
            )
        finally:
            self._kernel32.CloseHandle(handle)
        if not succeeded or int(result.device_type) != _FILE_DEVICE_DISK:
            return None
        return int(result.device_number)

    def _configure_api(self) -> None:
        self._kernel32.GetLogicalDrives.argtypes = []
        self._kernel32.GetLogicalDrives.restype = wintypes.DWORD
        self._kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetDriveTypeW.restype = wintypes.UINT
        self._kernel32.GetVolumeInformationW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.LPDWORD,
            wintypes.LPDWORD,
            wintypes.LPDWORD,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        self._kernel32.GetVolumeInformationW.restype = wintypes.BOOL
        self._kernel32.GetVolumeNameForVolumeMountPointW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        self._kernel32.GetVolumeNameForVolumeMountPointW.restype = wintypes.BOOL
        self._kernel32.GetDiskFreeSpaceW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPDWORD,
            wintypes.LPDWORD,
            wintypes.LPDWORD,
            wintypes.LPDWORD,
        ]
        self._kernel32.GetDiskFreeSpaceW.restype = wintypes.BOOL
        ulonglong_pointer = ctypes.POINTER(ctypes.c_ulonglong)
        self._kernel32.GetDiskFreeSpaceExW.argtypes = [
            wintypes.LPCWSTR,
            ulonglong_pointer,
            ulonglong_pointer,
            ulonglong_pointer,
        ]
        self._kernel32.GetDiskFreeSpaceExW.restype = wintypes.BOOL
        self._kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.GetFinalPathNameByHandleW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        self._kernel32.DeviceIoControl.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPDWORD,
            wintypes.LPVOID,
        ]
        self._kernel32.DeviceIoControl.restype = wintypes.BOOL
        self._kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        self._kernel32.FlushFileBuffers.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL


def _volume_root(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    drive = absolute.drive
    if not drive:
        raise MountInspectionError(f"Windows path has no drive root: {path}")
    return Path(f"{drive}\\")


def _windows_error(message: str) -> MountInspectionError:
    code = _last_error()
    detail = _format_error(code) if code else "unknown Windows error"
    return MountInspectionError(f"{message}: {detail}")


def _last_error() -> int:
    function: Any = vars(ctypes)["get_last_error"]
    return int(function())


def _format_error(code: int) -> str:
    function: Any = vars(ctypes)["FormatError"]
    detail: object = function(code)
    if isinstance(detail, str):
        return detail.strip() or f"Windows error {code}"
    return f"Windows error {code}"
