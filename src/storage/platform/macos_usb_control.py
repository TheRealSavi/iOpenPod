"""IOKit USB control access adapted from Rockbox's mks5lboot backend.

Uses IOUSBDeviceInterface197 for bounded synchronous requests. Interface slots
and UUIDs follow Apple's IOUSBLib.h, with the same open/request path as Rockbox.
"""

from __future__ import annotations

import ctypes
from typing import TYPE_CHECKING, Any
from uuid import UUID

from storage.errors import DeviceBusyError
from storage.platform.macos_iokit import MacFrameworks, registry_int, vtable_call
from storage.usb_control import (
    UsbControlEndpoint,
    UsbControlError,
    UsbControlRequest,
    UsbControlResponse,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_USER_CLIENT = UUID("9dc7b780-9ec0-11d4-a54f-000a27052861")
_DEVICE_INTERFACE = UUID("c809b8d8-0884-11d7-bb96-0003933e3e3e")


class _UUIDBytes(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_uint8 * 16)]


class _RequestTO(ctypes.Structure):
    _fields_ = [
        ("request_type", ctypes.c_uint8),
        ("request", ctypes.c_uint8),
        ("value", ctypes.c_uint16),
        ("index", ctypes.c_uint16),
        ("length", ctypes.c_uint16),
        ("data", ctypes.c_void_p),
        ("transferred", ctypes.c_uint32),
        ("no_data_timeout", ctypes.c_uint32),
        ("completion_timeout", ctypes.c_uint32),
    ]


def _require_success(result: int) -> None:
    code = result & 0xFFFFFFFF
    if code in (0xE00002C5, 0xE00002D5):
        raise DeviceBusyError("The USB device is busy; close other device tools")
    if code:
        raise UsbControlError(f"The IOKit USB control operation failed (0x{code:08x})")


class MacOSUsbControl:
    def __init__(self, *, frameworks: Any = None) -> None:
        self.frameworks = frameworks if frameworks is not None else MacFrameworks()
        iokit = self.frameworks.iokit
        iokit.IORegistryEntryGetRegistryEntryID.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint64),
        ]
        iokit.IORegistryEntryGetRegistryEntryID.restype = ctypes.c_int32
        iokit.IORegistryEntryIDMatching.argtypes = [ctypes.c_uint64]
        iokit.IORegistryEntryIDMatching.restype = ctypes.c_void_p
        iokit.IOServiceGetMatchingService.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        iokit.IOServiceGetMatchingService.restype = ctypes.c_uint32
        self.frameworks.cf.CFUUIDGetUUIDBytes.argtypes = [ctypes.c_void_p]
        self.frameworks.cf.CFUUIDGetUUIDBytes.restype = _UUIDBytes

    def _services(self) -> Iterator[int]:
        iokit = self.frameworks.iokit
        iterator = ctypes.c_uint32()
        match = iokit.IOServiceMatching(b"IOUSBDevice")
        if not match:
            raise UsbControlError("macOS could not create its USB device query")
        _require_success(
            iokit.IOServiceGetMatchingServices(0, match, ctypes.byref(iterator))
        )
        try:
            while service := iokit.IOIteratorNext(iterator):
                try:
                    yield service
                finally:
                    iokit.IOObjectRelease(service)
        finally:
            iokit.IOObjectRelease(iterator)

    def _endpoint(self, service: int, interface_class: UUID) -> UsbControlEndpoint:
        registry_id = ctypes.c_uint64()
        _require_success(
            self.frameworks.iokit.IORegistryEntryGetRegistryEntryID(
                service, ctypes.byref(registry_id)
            )
        )
        vendor = registry_int(self.frameworks, service, "idVendor")
        product = registry_int(self.frameworks, service, "idProduct")
        location = registry_int(self.frameworks, service, "locationID")
        if vendor is None or product is None or location is None:
            raise UsbControlError(
                "macOS did not provide a complete USB device identity"
            )
        return UsbControlEndpoint(
            interface_class,
            f"iokit-usb:{registry_id.value:016x}",
            f"registry:{registry_id.value:016x}:location:{location & 0xFFFFFFFF:08x}",
            vendor,
            product,
        )

    def discover(
        self, interface_class: UUID, vendor_id: int, product_id: int
    ) -> tuple[UsbControlEndpoint, ...]:
        result: list[UsbControlEndpoint] = []
        for service in self._services():
            if (
                registry_int(self.frameworks, service, "idVendor"),
                registry_int(self.frameworks, service, "idProduct"),
            ) != (vendor_id, product_id):
                continue
            result.append(self._endpoint(service, interface_class))
        return tuple(result)

    def open(self, endpoint: UsbControlEndpoint) -> MacOSUsbControlChannel:
        if not endpoint.interface_path.startswith("iokit-usb:"):
            raise UsbControlError("Expected a retained IOKit USB device")
        registry_id = int(endpoint.interface_path.removeprefix("iokit-usb:"), 16)
        iokit = self.frameworks.iokit
        match = iokit.IORegistryEntryIDMatching(registry_id)
        if not match:
            raise UsbControlError("macOS could not identify the retained USB device")
        service = iokit.IOServiceGetMatchingService(0, match)
        if not service:
            raise UsbControlError("The selected USB connection changed")
        try:
            if self._endpoint(service, endpoint.interface_class) != endpoint:
                raise UsbControlError("The selected USB device identity changed")
            device = self._interface(service)
            channel = MacOSUsbControlChannel(device)
            try:
                _require_success(vtable_call(device, 8, ctypes.c_int32, []))
                channel.opened = True
                if self._endpoint(service, endpoint.interface_class) != endpoint:
                    raise UsbControlError(
                        "The selected USB connection changed while opening it"
                    )
                for slot, expected in (
                    (13, endpoint.vendor_id),
                    (14, endpoint.product_id),
                ):
                    value = ctypes.c_uint16()
                    _require_success(
                        vtable_call(
                            device,
                            slot,
                            ctypes.c_int32,
                            [ctypes.POINTER(ctypes.c_uint16)],
                            ctypes.byref(value),
                        )
                    )
                    if value.value != expected:
                        raise UsbControlError(
                            "The held USB device does not match the selection"
                        )
                return channel
            except BaseException:
                channel.close()
                raise
        finally:
            iokit.IOObjectRelease(service)

    def _interface(self, service: int) -> ctypes.c_void_p:
        frameworks = self.frameworks
        plugin = ctypes.c_void_p()
        score = ctypes.c_int32()
        _require_success(
            frameworks.iokit.IOCreatePlugInInterfaceForService(
                service,
                frameworks.uuid_from_bytes(*_USER_CLIENT.bytes),
                frameworks.plugin_uuid,
                ctypes.byref(plugin),
                ctypes.byref(score),
            )
        )
        if not plugin:
            raise UsbControlError("macOS did not provide a USB plugin")
        device = ctypes.c_void_p()
        try:
            _require_success(
                vtable_call(
                    plugin,
                    1,
                    ctypes.c_int32,
                    [_UUIDBytes, ctypes.POINTER(ctypes.c_void_p)],
                    frameworks.cf.CFUUIDGetUUIDBytes(
                        frameworks.uuid_from_bytes(*_DEVICE_INTERFACE.bytes)
                    ),
                    ctypes.byref(device),
                )
            )
            if not device:
                raise UsbControlError("macOS did not provide the USB device interface")
            return device
        finally:
            vtable_call(plugin, 3, ctypes.c_uint32, [])


class MacOSUsbControlChannel:
    def __init__(self, device: ctypes.c_void_p) -> None:
        self._device: ctypes.c_void_p | None = device
        self.opened = False

    def execute(self, request: UsbControlRequest) -> UsbControlResponse:
        if self._device is None or not self.opened:
            raise UsbControlError("The USB Control Session is closed")
        buffer = ctypes.create_string_buffer(max(1, request.transfer_length))
        if request.data_out:
            ctypes.memmove(buffer, request.data_out, len(request.data_out))
        native = _RequestTO(
            request.request_type,
            request.request,
            request.value,
            request.index,
            request.transfer_length,
            ctypes.cast(buffer, ctypes.c_void_p),
            0,
            request.timeout_ms,
            request.timeout_ms,
        )
        _require_success(
            vtable_call(
                self._device,
                30,
                ctypes.c_int32,
                [ctypes.POINTER(_RequestTO)],
                ctypes.byref(native),
            )
        )
        return UsbControlResponse(
            buffer.raw[: native.transferred] if request.is_read else b"",
            native.transferred,
        )

    def close(self) -> None:
        if self._device is None:
            return
        device, self._device = self._device, None
        try:
            if self.opened:
                vtable_call(device, 9, ctypes.c_int32, [])
        finally:
            vtable_call(device, 3, ctypes.c_uint32, [])
