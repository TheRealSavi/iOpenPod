"""Windows Plug and Play safe removal for an exact physical disk number."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Protocol, cast

from storage.errors import EjectError, UnsupportedStorageOperationError
from storage.models import EjectResult

_CR_SUCCESS = 0
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_NO_MORE_ITEMS = 259
_DIGCF_PRESENT = 0x00000002
_DIGCF_DEVICEINTERFACE = 0x00000010
_FILE_DEVICE_DISK = 0x00000007
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
_OPEN_EXISTING = 3
_MAX_PATH = 260


class _Guid(ctypes.Structure):
    _fields_ = (
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", ctypes.c_ubyte * 8),
    )


_GUID_DEVINTERFACE_DISK = _Guid(
    0x53F56307,
    0xB6BF,
    0x11D0,
    (ctypes.c_ubyte * 8)(0x94, 0xF2, 0x00, 0xA0, 0xC9, 0x1E, 0xFB, 0x8B),
)


class _DeviceInterfaceData(ctypes.Structure):
    _fields_ = (
        ("cb_size", wintypes.DWORD),
        ("interface_class_guid", _Guid),
        ("flags", wintypes.DWORD),
        ("reserved", ctypes.c_size_t),
    )


class _DeviceInfoData(ctypes.Structure):
    _fields_ = (
        ("cb_size", wintypes.DWORD),
        ("class_guid", _Guid),
        ("dev_inst", wintypes.DWORD),
        ("reserved", ctypes.c_size_t),
    )


class _StorageDeviceNumber(ctypes.Structure):
    _fields_ = (
        ("device_type", wintypes.DWORD),
        ("device_number", wintypes.DWORD),
        ("partition_number", wintypes.DWORD),
    )


@dataclass(frozen=True, slots=True)
class _EjectReply:
    config_result: int
    veto_type: int
    veto_name: str


class _WindowsEjectApi(Protocol):
    def device_instance_for_disk(self, disk_number: int) -> int | None: ...

    def parent_device_instance(self, device_instance: int) -> int: ...

    def request_eject(self, device_instance: int) -> _EjectReply: ...


class WindowsDeviceEjector:
    """Request removal through Configuration Manager and preserve PnP vetoes."""

    def __init__(self, api: _WindowsEjectApi | None = None) -> None:
        self._api = api or _CtypesWindowsEjectApi()

    def eject(self, disk_number: int) -> EjectResult:
        if disk_number < 0:
            raise ValueError("A Windows physical disk number cannot be negative")
        disk_device_instance = self._api.device_instance_for_disk(disk_number)
        if disk_device_instance is None:
            raise UnsupportedStorageOperationError(
                "Windows could not match this iPod to an exact Plug and Play "
                "device. Use Safely Remove Hardware in the Windows taskbar."
            )
        device_instance = self._api.parent_device_instance(disk_device_instance)
        reply = self._api.request_eject(device_instance)
        if reply.config_result == _CR_SUCCESS:
            return EjectResult(
                "Windows Plug and Play confirmed that the iPod is safe to remove."
            )
        if reply.veto_type == 13:  # PNP_VetoAlreadyRemoved
            return EjectResult(
                "Windows reports that the iPod has already been safely removed."
            )
        raise EjectError(_veto_message(reply))


class _CtypesWindowsEjectApi:
    def __init__(self) -> None:
        win_dll: Any = vars(ctypes)["WinDLL"]
        self._kernel32 = win_dll("kernel32", use_last_error=True)
        self._setupapi = win_dll("setupapi", use_last_error=True)
        self._cfgmgr32 = win_dll("cfgmgr32", use_last_error=True)
        self._configure_api()

    def device_instance_for_disk(self, disk_number: int) -> int | None:
        device_set = self._setupapi.SetupDiGetClassDevsW(
            ctypes.byref(_GUID_DEVINTERFACE_DISK),
            None,
            None,
            _DIGCF_PRESENT | _DIGCF_DEVICEINTERFACE,
        )
        if _handle_value(device_set) == _INVALID_HANDLE_VALUE:
            raise EjectError(
                "Windows could not enumerate storage devices for safe removal "
                f"(Win32 error {_last_error()})."
            )
        try:
            index = 0
            while True:
                interface = _DeviceInterfaceData()
                interface.cb_size = ctypes.sizeof(interface)
                _set_last_error(0)
                found = self._setupapi.SetupDiEnumDeviceInterfaces(
                    device_set,
                    None,
                    ctypes.byref(_GUID_DEVINTERFACE_DISK),
                    index,
                    ctypes.byref(interface),
                )
                if not found:
                    error = _last_error()
                    if error == _ERROR_NO_MORE_ITEMS:
                        return None
                    raise EjectError(
                        "Windows could not enumerate storage devices for safe "
                        f"removal (Win32 error {error})."
                    )
                device_instance = self._device_instance_for_interface(
                    device_set,
                    interface,
                    disk_number,
                )
                if device_instance is not None:
                    return device_instance
                index += 1
        finally:
            self._setupapi.SetupDiDestroyDeviceInfoList(device_set)

    def request_eject(self, device_instance: int) -> _EjectReply:
        veto_type = wintypes.DWORD()
        veto_name = ctypes.create_unicode_buffer(_MAX_PATH)
        config_result = int(
            self._cfgmgr32.CM_Request_Device_EjectW(
                device_instance,
                ctypes.byref(veto_type),
                veto_name,
                len(veto_name),
                0,
            )
        )
        return _EjectReply(config_result, int(veto_type.value), veto_name.value)

    def parent_device_instance(self, device_instance: int) -> int:
        parent = wintypes.DWORD()
        config_result = int(
            self._cfgmgr32.CM_Get_Parent(
                ctypes.byref(parent),
                device_instance,
                0,
            )
        )
        if config_result != _CR_SUCCESS:
            raise EjectError(
                "Windows could not resolve the removable Plug and Play parent "
                "for this iPod "
                f"(Configuration Manager result 0x{config_result:08X})."
            )
        return int(parent.value)

    def _device_instance_for_interface(
        self,
        device_set: object,
        interface: _DeviceInterfaceData,
        expected_disk_number: int,
    ) -> int | None:
        required = wintypes.DWORD()
        _set_last_error(0)
        self._setupapi.SetupDiGetDeviceInterfaceDetailW(
            device_set,
            ctypes.byref(interface),
            None,
            0,
            ctypes.byref(required),
            None,
        )
        error = _last_error()
        if not required.value or error not in {0, _ERROR_INSUFFICIENT_BUFFER}:
            raise EjectError(
                "Windows could not inspect a storage-device interface for safe "
                f"removal (Win32 error {error})."
            )

        detail = ctypes.create_string_buffer(required.value)
        detail_cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
        ctypes.cast(
            detail, ctypes.POINTER(wintypes.DWORD)
        ).contents.value = detail_cb_size
        device_info = _DeviceInfoData()
        device_info.cb_size = ctypes.sizeof(device_info)
        if not self._setupapi.SetupDiGetDeviceInterfaceDetailW(
            device_set,
            ctypes.byref(interface),
            detail,
            required.value,
            None,
            ctypes.byref(device_info),
        ):
            raise EjectError(
                "Windows could not inspect a storage-device interface for safe "
                f"removal (Win32 error {_last_error()})."
            )
        device_path = ctypes.wstring_at(
            ctypes.addressof(detail) + ctypes.sizeof(wintypes.DWORD)
        )
        if self._disk_number_for_path(device_path) != expected_disk_number:
            return None
        return int(device_info.dev_inst)

    def _disk_number_for_path(self, device_path: str) -> int | None:
        handle = self._kernel32.CreateFileW(
            device_path,
            0,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if _handle_value(handle) in {None, _INVALID_HANDLE_VALUE}:
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
        self._setupapi.SetupDiGetClassDevsW.argtypes = [
            ctypes.POINTER(_Guid),
            wintypes.LPCWSTR,
            wintypes.HWND,
            wintypes.DWORD,
        ]
        self._setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
        self._setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_DeviceInfoData),
            ctypes.POINTER(_Guid),
            wintypes.DWORD,
            ctypes.POINTER(_DeviceInterfaceData),
        ]
        self._setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
        self._setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_DeviceInterfaceData),
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPDWORD,
            ctypes.POINTER(_DeviceInfoData),
        ]
        self._setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
        self._setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
        self._setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
        self._cfgmgr32.CM_Request_Device_EjectW.argtypes = [
            wintypes.DWORD,
            wintypes.LPDWORD,
            wintypes.LPWSTR,
            wintypes.ULONG,
            wintypes.ULONG,
        ]
        self._cfgmgr32.CM_Request_Device_EjectW.restype = wintypes.DWORD
        self._cfgmgr32.CM_Get_Parent.argtypes = [
            wintypes.LPDWORD,
            wintypes.DWORD,
            wintypes.ULONG,
        ]
        self._cfgmgr32.CM_Get_Parent.restype = wintypes.DWORD
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
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL


def _handle_value(handle: object) -> int | None:
    if handle is None:
        return None
    if isinstance(handle, int):
        return handle
    if isinstance(handle, ctypes.c_void_p):
        return handle.value
    return cast("int | None", getattr(handle, "value", None))


def _last_error() -> int:
    function: Any = vars(ctypes)["get_last_error"]
    return int(function())


def _set_last_error(value: int) -> None:
    function: Any = vars(ctypes)["set_last_error"]
    function(value)


def _veto_message(reply: _EjectReply) -> str:
    name = reply.veto_name.strip()
    suffix = f" ({name})" if name else ""
    reason = {
        1: "The device does not support the requested Plug and Play operation.",
        2: "Windows is still closing access to the device. Wait a moment and try again.",
        3: f"A Windows application is using the iPod{suffix}. Close it and try again.",
        4: f"A Windows service is using the iPod{suffix}. Stop the service or use Safely Remove Hardware.",
        5: "The iPod still has open files. Close File Explorer windows and other apps using it, then try again.",
        6: f"A connected device rejected the eject request{suffix}.",
        7: f"A Windows driver rejected the eject request{suffix}.",
        8: "This device does not support the requested safe-removal operation.",
        9: "Windows reports insufficient power to complete safe removal.",
        10: "Windows reports that this device cannot be disabled.",
        11: f"A legacy driver cannot complete safe removal{suffix}.",
        12: "This Windows session does not have permission to safely remove the iPod.",
    }.get(
        reply.veto_type,
        "Windows rejected the safe-removal request for an unknown reason.",
    )
    return f"{reason} The iPod was not ejected (Configuration Manager result 0x{reply.config_result:08X})."


__all__ = ["WindowsDeviceEjector"]
