"""Connection-bound libusb discovery and control access for desktop Hosts.

Keep one context for the process lifetime, as RepriseOS does on Darwin. Retained
device references distinguish reconnects even when a USB address is reused.
No protocol request is replayed and a channel never changes transport.
"""

from __future__ import annotations

import ctypes
import threading
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from storage.errors import DeviceBusyError
from storage.platform.libusb_runtime import load_library
from storage.usb_control import (
    UsbControlEndpoint,
    UsbControlError,
    UsbControlRequest,
    UsbControlResponse,
)

if TYPE_CHECKING:
    from uuid import UUID


class LibusbOpenError(UsbControlError):
    """Opening/claiming failed before a protocol transfer could be submitted."""


def _require_open(result: int) -> None:
    if result in (-4, -6):
        require_success(result)
    if result < 0:
        raise LibusbOpenError(
            f"The installed USB driver could not prepare interface 0 ({result})"
        )


def require_success(result: int) -> int:
    if result == -6:
        raise DeviceBusyError("The USB interface is busy; close other device tools")
    if result < 0:
        raise UsbControlError(f"The libusb control operation failed ({result})")
    return result


@dataclass(frozen=True)
class _ObservedDevice:
    pointer: int
    generation: str
    bus: int
    address: int
    vendor: int
    product: int

    def endpoint(self, interface_class: UUID) -> UsbControlEndpoint:
        return UsbControlEndpoint(
            interface_class,
            f"libusb:{self.bus}:{self.address}",
            self.generation,
            self.vendor,
            self.product,
        )


class LibusbControl:
    def __init__(self, *, library: Any = None) -> None:
        self.library = library if library is not None else load_library()
        self._context = ctypes.c_void_p()
        require_success(self.library.libusb_init(ctypes.byref(self._context)))
        self._devices: dict[int, _ObservedDevice] = {}
        self._lock = threading.RLock()

    def discover(
        self, interface_class: UUID, vendor_id: int, product_id: int
    ) -> tuple[UsbControlEndpoint, ...]:
        with self._lock:
            devices = ctypes.POINTER(ctypes.c_void_p)()
            count = require_success(
                self.library.libusb_get_device_list(
                    self._context, ctypes.byref(devices)
                )
            )
            observed: dict[int, _ObservedDevice] = {}
            try:
                if count > 4096:
                    raise UsbControlError("USB enumeration exceeded its bound")
                for index in range(count):
                    pointer = devices[index]
                    # libusb_device_descriptor is 18 bytes with native-endian u16s.
                    descriptor = ctypes.create_string_buffer(18)
                    result = self.library.libusb_get_device_descriptor(
                        pointer, descriptor
                    )
                    if result < 0:
                        continue  # Device disappeared during enumeration.
                    vendor = ctypes.c_uint16.from_buffer(descriptor, 8).value
                    product = ctypes.c_uint16.from_buffer(descriptor, 10).value
                    if (vendor, product) != (vendor_id, product_id):
                        continue
                    previous = self._devices.get(pointer)
                    observed[pointer] = previous or _ObservedDevice(
                        pointer,
                        uuid.uuid4().hex,
                        self.library.libusb_get_bus_number(pointer),
                        self.library.libusb_get_device_address(pointer),
                        vendor,
                        product,
                    )
                    if previous is None:
                        self.library.libusb_ref_device(pointer)
            except BaseException:
                for pointer in observed.keys() - self._devices.keys():
                    self.library.libusb_unref_device(pointer)
                raise
            finally:
                self.library.libusb_free_device_list(devices, 1)
            # Keep refs until after obtaining the new list so a disconnected
            # object's pointer cannot be recycled into an old endpoint identity.
            for pointer in self._devices.keys() - observed.keys():
                self.library.libusb_unref_device(pointer)
            self._devices = observed
            return tuple(d.endpoint(interface_class) for d in observed.values())

    def open(self, endpoint: UsbControlEndpoint) -> LibusbControlChannel:
        with self._lock:
            if endpoint not in self.discover(
                endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
            ):
                raise UsbControlError("The selected USB connection changed")
            device = next(
                d
                for d in self._devices.values()
                if d.generation == endpoint.instance_id
            )
            handle = ctypes.c_void_p()
            result = self.library.libusb_open(device.pointer, ctypes.byref(handle))
            if result < 0:
                _require_open(result)
            channel = LibusbControlChannel(self.library, handle)
            try:
                channel.claim()
                if endpoint not in self.discover(
                    endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
                ):
                    raise UsbControlError(
                        "The selected USB connection changed while opening"
                    )
                return channel
            except BaseException:
                channel.close()
                raise


class LibusbControlChannel:
    def __init__(self, library: Any, handle: ctypes.c_void_p) -> None:
        self.library = library
        self._handle = handle
        self._claimed = False

    def claim(self) -> None:
        # Auto detach is unsupported on Windows. On macOS permission failures
        # remain actionable errors; no whole-app elevation or USB reset is used.
        result = self.library.libusb_set_auto_detach_kernel_driver(self._handle, 1)
        if result != -12:
            _require_open(result)
        configuration = ctypes.c_int()
        _require_open(
            self.library.libusb_get_configuration(
                self._handle, ctypes.byref(configuration)
            )
        )
        if configuration.value != 1:
            _require_open(self.library.libusb_set_configuration(self._handle, 1))
        result = self.library.libusb_claim_interface(self._handle, 0)
        _require_open(result)
        self._claimed = True

    def execute(self, request: UsbControlRequest) -> UsbControlResponse:
        if not self._handle or not self._claimed:
            raise UsbControlError("The USB Control Session is closed")
        buffer = ctypes.create_string_buffer(max(1, request.transfer_length))
        if request.data_out:
            ctypes.memmove(buffer, request.data_out, len(request.data_out))
        count = require_success(
            self.library.libusb_control_transfer(
                self._handle,
                request.request_type,
                request.request,
                request.value,
                request.index,
                buffer,
                request.transfer_length,
                request.timeout_ms,
            )
        )
        return UsbControlResponse(buffer.raw[:count] if request.is_read else b"", count)

    def close(self) -> None:
        if not self._handle:
            return
        handle, self._handle = self._handle, ctypes.c_void_p()
        try:
            if self._claimed:
                self.library.libusb_release_interface(handle, 0)
        finally:
            self.library.libusb_close(handle)


_control: LibusbControl | None = None
_control_lock = threading.Lock()


def control() -> LibusbControl:
    """Lazy process-lifetime context; startup and smoke checks never enumerate."""
    global _control
    with _control_lock:
        if _control is None:
            _control = LibusbControl()
        return _control
