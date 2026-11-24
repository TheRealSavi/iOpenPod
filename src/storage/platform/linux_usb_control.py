"""Retained Linux libusb control access, following Rockbox's DFU USB backend.

The packaged library is used explicitly. A one-time polkit helper may install
a scoped udev rule; all opens and USB transfers run as the ordinary desktop user.
"""

from __future__ import annotations

import ctypes
import os
from typing import TYPE_CHECKING, Any

from storage.errors import DeviceBusyError
from storage.platform import linux_usb_access
from storage.platform.libusb_runtime import load_library
from storage.platform.linux_usb_rules import authorize
from storage.usb_control import (
    UsbControlAuthorizationError,
    UsbControlEndpoint,
    UsbControlError,
    UsbControlRequest,
    UsbControlResponse,
)

if TYPE_CHECKING:
    from uuid import UUID


def check_runtime() -> None:
    """Exercise the included library without enumerating or opening devices."""
    library = load_library()
    # Initializing a libusb context also starts native device discovery.
    if not library.libusb_get_version():
        raise UsbControlError("The bundled libusb runtime could not report its version")


def _require_success(result: int) -> int:
    if result == -6:
        raise DeviceBusyError("The USB interface is busy; close other device tools")
    if result < 0:
        raise UsbControlError(f"The libusb control operation failed ({result})")
    return result


class LinuxUsbControl:
    def discover(
        self, interface_class: UUID, vendor_id: int, product_id: int
    ) -> tuple[UsbControlEndpoint, ...]:
        return tuple(
            UsbControlEndpoint(interface_class, d.path, d.instance, d.vendor, d.product)
            for d in linux_usb_access.devices()
            if (d.vendor, d.product) == (vendor_id, product_id)
        )

    def open(self, endpoint: UsbControlEndpoint) -> LinuxUsbControlChannel:
        if endpoint not in self.discover(
            endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
        ):
            raise UsbControlError("The selected USB connection changed")
        library = load_library()  # Qualify the package before requesting permission.
        try:
            descriptor = linux_usb_access.open_device(
                endpoint.interface_path, endpoint.instance_id
            )
        except PermissionError:
            authorize(endpoint.vendor_id, endpoint.product_id)
            # Reopen as the ordinary user, checking the same sysfs generation.
            try:
                descriptor = linux_usb_access.open_device(
                    endpoint.interface_path, endpoint.instance_id
                )
            except PermissionError as error:
                raise UsbControlAuthorizationError(
                    "USB permissions were installed. Reconnect the device from an "
                    "active local desktop session, then reopen setup."
                ) from error
        channel = LinuxUsbControlChannel(library, descriptor)
        try:
            if endpoint not in self.discover(
                endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
            ):
                raise UsbControlError(
                    "The selected USB connection changed during authorization"
                )
            channel.open()
            return channel
        except BaseException:
            channel.close()
            raise


class LinuxUsbControlChannel:
    def __init__(self, library: Any, descriptor: int) -> None:
        self.library = library
        self._descriptor: int | None = descriptor
        self._context = ctypes.c_void_p()
        self._handle = ctypes.c_void_p()
        self._initialized = False
        self._claimed = False
        self._detached = False

    def open(self) -> None:
        _require_success(self.library.libusb_init(ctypes.byref(self._context)))
        self._initialized = True
        _require_success(
            self.library.libusb_wrap_sys_device(
                self._context, self._descriptor, ctypes.byref(self._handle)
            )
        )
        # Preserve Rockbox's configuration/claim sequence before DFU requests.
        _require_success(self.library.libusb_set_configuration(self._handle, 1))
        active = self.library.libusb_kernel_driver_active(self._handle, 0)
        if active != -12:  # LIBUSB_ERROR_NOT_SUPPORTED
            _require_success(active)
            if active == 1:
                _require_success(
                    self.library.libusb_detach_kernel_driver(self._handle, 0)
                )
                self._detached = True
        _require_success(self.library.libusb_claim_interface(self._handle, 0))
        self._claimed = True

    def execute(self, request: UsbControlRequest) -> UsbControlResponse:
        if self._descriptor is None or not self._claimed:
            raise UsbControlError("The USB Control Session is closed")
        buffer = ctypes.create_string_buffer(max(1, request.transfer_length))
        if request.data_out:
            ctypes.memmove(buffer, request.data_out, len(request.data_out))
        count = _require_success(
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
        if self._descriptor is None:
            return
        descriptor, self._descriptor = self._descriptor, None
        try:
            if self._handle:
                if self._claimed:
                    self.library.libusb_release_interface(self._handle, 0)
                if self._detached:
                    self.library.libusb_attach_kernel_driver(self._handle, 0)
                self.library.libusb_close(self._handle)
        finally:
            if self._initialized:
                self.library.libusb_exit(self._context)
            os.close(descriptor)
