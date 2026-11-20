"""Windows PIPE0 driver adapter for USB setup packets; no firmware protocol.

Wire layout follows Rockbox mks5lboot/ipoddfu.c (GPL-2.0-or-later) and the
pinned Reprise Apple PIPE0 transport (GPL-3.0-only). Win32 I/O is owned here.
"""

from __future__ import annotations

import ctypes
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

from storage.errors import DeviceBusyError
from storage.usb_control import (
    UsbControlEndpoint,
    UsbControlError,
    UsbControlRequest,
    UsbControlResponse,
)

_INVALID = ctypes.c_void_p(-1).value
_U32 = ctypes.c_uint32


class _Guid(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]


class _Interface(ctypes.Structure):
    _fields_ = [
        ("size", _U32),
        ("guid", _Guid),
        ("flags", _U32),
        ("reserved", ctypes.c_size_t),
    ]


class _DeviceInfo(ctypes.Structure):
    _fields_ = [
        ("size", _U32),
        ("guid", _Guid),
        ("instance", _U32),
        ("reserved", ctypes.c_size_t),
    ]


class _Overlapped(ctypes.Structure):
    _fields_ = [
        ("internal", ctypes.c_size_t),
        ("internal_high", ctypes.c_size_t),
        ("offset", _U32),
        ("offset_high", _U32),
        ("event", ctypes.c_void_p),
    ]


def _error() -> int:
    function: Any = vars(ctypes)["get_last_error"]
    return int(function())


class WindowsUsbControl:
    def __init__(self, *, kernel: Any = None, setup: Any = None) -> None:
        if kernel is None:
            loader: Any = vars(ctypes)["WinDLL"]
            kernel = loader("kernel32", use_last_error=True)
            setup = loader("setupapi", use_last_error=True)
            self._bind(kernel, setup)
        self.kernel = kernel
        self.setup = setup

    @staticmethod
    def _bind(kernel: Any, setup: Any) -> None:
        pointer = ctypes.c_void_p
        signatures = {
            "CreateFileW": (
                [ctypes.c_wchar_p, _U32, _U32, pointer, _U32, _U32, pointer],
                pointer,
            ),
            "CloseHandle": ([pointer], ctypes.c_int),
            "CreateEventW": (
                [pointer, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p],
                pointer,
            ),
            "ReadFile": ([pointer, pointer, _U32, pointer, pointer], ctypes.c_int),
            "WriteFile": ([pointer, pointer, _U32, pointer, pointer], ctypes.c_int),
            "GetOverlappedResultEx": (
                [pointer, pointer, pointer, _U32, ctypes.c_int],
                ctypes.c_int,
            ),
            "GetOverlappedResult": (
                [pointer, pointer, pointer, ctypes.c_int],
                ctypes.c_int,
            ),
            "CancelIoEx": ([pointer, pointer], ctypes.c_int),
        }
        for name, (args, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes, function.restype = args, result
        signatures = {
            "SetupDiGetClassDevsW": (
                [pointer, ctypes.c_wchar_p, pointer, _U32],
                pointer,
            ),
            "SetupDiEnumDeviceInterfaces": (
                [pointer, pointer, pointer, _U32, pointer],
                ctypes.c_int,
            ),
            "SetupDiGetDeviceInterfaceDetailW": (
                [pointer, pointer, pointer, _U32, pointer, pointer],
                ctypes.c_int,
            ),
            "SetupDiGetDeviceInstanceIdW": (
                [pointer, pointer, pointer, _U32, pointer],
                ctypes.c_int,
            ),
            "SetupDiDestroyDeviceInfoList": ([pointer], ctypes.c_int),
        }
        for name, (args, result) in signatures.items():
            function = getattr(setup, name)
            function.argtypes, function.restype = args, result

    def discover(
        self,
        interface_class: uuid.UUID,
        vendor_id: int,
        product_id: int,
    ) -> tuple[UsbControlEndpoint, ...]:
        if any(
            type(x) is not int or not 0 <= x <= 65535 for x in (vendor_id, product_id)
        ):
            raise ValueError("USB identifiers must fit unsigned 16 bits")
        guid = _Guid.from_buffer_copy(interface_class.bytes_le)
        devices = self.setup.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x12)
        if devices in (None, _INVALID):
            raise UsbControlError(f"USB interface enumeration failed ({_error()})")
        endpoints: list[UsbControlEndpoint] = []
        try:
            for index in range(256):
                interface = _Interface()
                interface.size = ctypes.sizeof(interface)
                if not self.setup.SetupDiEnumDeviceInterfaces(
                    devices, None, ctypes.byref(guid), index, ctypes.byref(interface)
                ):
                    if _error() == 259:
                        return tuple(endpoints)
                    raise UsbControlError(
                        f"USB interface enumeration failed ({_error()})"
                    )
                required = _U32()
                self.setup.SetupDiGetDeviceInterfaceDetailW(
                    devices,
                    ctypes.byref(interface),
                    None,
                    0,
                    ctypes.byref(required),
                    None,
                )
                if _error() != 122 or not 8 <= required.value <= 65536:
                    raise UsbControlError("Invalid USB interface path size")
                detail = ctypes.create_string_buffer(required.value)
                ctypes.cast(detail, ctypes.POINTER(_U32))[0] = (
                    8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                )
                info = _DeviceInfo()
                info.size = ctypes.sizeof(info)
                if not self.setup.SetupDiGetDeviceInterfaceDetailW(
                    devices,
                    ctypes.byref(interface),
                    detail,
                    required.value,
                    None,
                    ctypes.byref(info),
                ):
                    raise UsbControlError(
                        f"USB interface path read failed ({_error()})"
                    )
                encoded = bytes(detail)[4:]
                if len(encoded) % 2:
                    raise UsbControlError("Malformed USB interface path")
                path = encoded.decode("utf-16-le").split("\0", 1)[0]
                prefix = rf"\\?\usb#vid_{vendor_id:04x}&pid_{product_id:04x}#"
                if not path.lower().startswith(prefix):
                    continue
                instance = ctypes.create_unicode_buffer(4096)
                if not self.setup.SetupDiGetDeviceInstanceIdW(
                    devices, ctypes.byref(info), instance, len(instance), None
                ):
                    raise UsbControlError(
                        f"USB instance identity read failed ({_error()})"
                    )
                endpoints.append(
                    UsbControlEndpoint(
                        interface_class, path, instance.value, vendor_id, product_id
                    )
                )
            raise UsbControlError("USB interface enumeration exceeded its bound")
        finally:
            self.setup.SetupDiDestroyDeviceInfoList(devices)

    def open(self, endpoint: UsbControlEndpoint) -> WindowsUsbControlChannel:
        # Re-enumerate the full opaque identity immediately before native open.
        if endpoint not in self.discover(
            endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
        ):
            raise UsbControlError("The selected USB interface disconnected or changed")
        # Apple's installed driver can append a USB hub/mux component. Accept
        # only the complete path just returned by SetupAPI, without rewriting it.
        prefix = rf"\\?\usb#vid_{endpoint.vendor_id:04x}&pid_{endpoint.product_id:04x}#"
        if (
            not endpoint.interface_path.lower().startswith(prefix)
            or "\0" in endpoint.interface_path
        ):
            raise UsbControlError("Invalid native USB interface path")
        handles: list[int] = []
        try:
            for path, flags in (
                (endpoint.interface_path, 0),
                (endpoint.interface_path + "\\PIPE0", 0x40000000),
            ):
                # Request no sharing, with no fallback. Some USB drivers ignore
                # this flag; the Host lease covers cooperating Storage clients.
                handle = self.kernel.CreateFileW(
                    path, 0xC0000000, 0, None, 3, flags, None
                )
                if handle in (None, _INVALID):
                    code = _error()
                    if code in (5, 32, 33):
                        raise DeviceBusyError(
                            "USB control interface is busy or exclusive access is unavailable"
                        )
                    raise UsbControlError(f"Exclusive USB control open failed ({code})")
                handles.append(handle)
            if endpoint not in self.discover(
                endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
            ):
                raise UsbControlError("USB identity changed while opening its handles")
            return WindowsUsbControlChannel(self.kernel, handles[0], handles[1])
        except BaseException:
            for handle in reversed(handles):
                self.kernel.CloseHandle(handle)
            raise


class WindowsUsbControlChannel:
    def __init__(self, kernel: Any, device: int, pipe: int) -> None:
        self.kernel = kernel
        self.device: int | None = device
        self.pipe: int | None = pipe

    def execute(self, request: UsbControlRequest) -> UsbControlResponse:
        if self.pipe is None:
            raise UsbControlError("USB pipe is closed")
        wire = request.setup_packet() + (
            bytes(request.data_in_length) if request.is_read else request.data_out
        )
        packet = ctypes.create_string_buffer(wire, len(wire))
        event = self.kernel.CreateEventW(None, 1, 0, None)
        if not event:
            raise UsbControlError(f"USB event allocation failed ({_error()})")
        overlapped = _Overlapped(event=event)
        transferred = _U32()
        pending = False
        try:
            operation = (
                self.kernel.ReadFile if request.is_read else self.kernel.WriteFile
            )
            if not operation(
                self.pipe,
                packet,
                len(wire),
                ctypes.byref(transferred),
                ctypes.byref(overlapped),
            ):
                code = _error()
                if code != 997:
                    raise UsbControlError(f"USB control transfer failed ({code})")
                pending = True
                if not self.kernel.GetOverlappedResultEx(
                    self.pipe,
                    ctypes.byref(overlapped),
                    ctypes.byref(transferred),
                    request.timeout_ms,
                    0,
                ):
                    code = _error()
                    raise UsbControlError(
                        f"USB completion failed or timed out ({code})"
                    )
                pending = False
            if not 8 <= transferred.value <= len(wire):
                raise UsbControlError("Invalid native USB packet transfer length")
            count = transferred.value - 8
            return UsbControlResponse(
                bytes(packet)[8 : 8 + count] if request.is_read else b"", count
            )
        finally:
            if pending or overlapped.internal == 0x103:  # STATUS_PENDING
                # Also covers interruption while waiting. Native buffers and
                # OVERLAPPED remain alive until the cancellation completes.
                self.kernel.CancelIoEx(self.pipe, ctypes.byref(overlapped))
                self.kernel.GetOverlappedResult(
                    self.pipe, ctypes.byref(overlapped), ctypes.byref(transferred), 1
                )
            self.kernel.CloseHandle(event)

    def close(self) -> None:
        pipe, device = self.pipe, self.device
        self.pipe = self.device = None
        for handle in (pipe, device):
            if handle is not None:
                self.kernel.CloseHandle(handle)
