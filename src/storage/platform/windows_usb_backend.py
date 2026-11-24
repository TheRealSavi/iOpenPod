"""Prefer bundled libusb; fall back to the installed Apple PIPE0 transport."""

from __future__ import annotations

from typing import TYPE_CHECKING

from storage.platform import libusb_control
from storage.platform.libusb_control import LibusbOpenError
from storage.platform.windows_usb_control import WindowsUsbControl
from storage.usb_control import UsbControlDriverError, UsbControlError

if TYPE_CHECKING:
    from uuid import UUID

    from storage.usb_control import UsbControlChannel, UsbControlEndpoint


class WindowsUsbBackend:
    def discover(
        self, interface_class: UUID, vendor_id: int, product_id: int
    ) -> tuple[UsbControlEndpoint, ...]:
        endpoints = libusb_control.control().discover(
            interface_class, vendor_id, product_id
        )
        try:
            apple = WindowsUsbControl().discover(interface_class, vendor_id, product_id)
        except UsbControlError:
            if endpoints:
                return endpoints
            raise
        # The same device can be visible to both APIs. Never publish it twice,
        # but preserve an ambiguous Apple enumeration so the caller rejects it.
        return apple if len(apple) > len(endpoints) else endpoints

    def open(self, endpoint: UsbControlEndpoint) -> UsbControlChannel:
        native = libusb_control.control()
        if endpoint.interface_path.startswith("libusb:"):
            try:
                return native.open(endpoint)
            except LibusbOpenError:
                pass  # Only open/claim failures, never transfer failures.
            current = native.discover(
                endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
            )
            if current != (endpoint,):
                raise UsbControlError(
                    "The selected USB connection changed or is ambiguous"
                )
            apple = WindowsUsbControl()
            candidates = apple.discover(
                endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
            )
            if not candidates:
                raise UsbControlDriverError(
                    "No compatible USB control driver is available"
                )
            if len(candidates) != 1:
                raise UsbControlError(
                    "Connect only the selected device while setting up USB access"
                )
            channel = apple.open(candidates[0])
            try:
                if native.discover(
                    endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
                ) != (endpoint,):
                    raise UsbControlError(
                        "The selected USB connection changed during driver fallback"
                    )
                return channel
            except BaseException:
                channel.close()
                raise
        # libusb could not enumerate this driver's device. Do not switch to a
        # different libusb endpoint discovered since the user's selection.
        if native.discover(
            endpoint.interface_class, endpoint.vendor_id, endpoint.product_id
        ):
            raise UsbControlError("USB access changed; reconnect and reopen setup")
        return WindowsUsbControl().open(endpoint)
