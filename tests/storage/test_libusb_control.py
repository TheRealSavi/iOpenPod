"""Retained libusb lifetimes, disconnects and bounded protocol requests."""

import ctypes
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from storage import DeviceBusyError, UsbControlError, UsbControlRequest
from storage.platform import libusb_control as usb
from storage.platform import libusb_runtime


def native_library() -> tuple[MagicMock, list[int]]:
    native = MagicMock()
    connected = [100]
    lists: list[Any] = []

    def initialize(output: Any) -> int:
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = 1
        return 0

    def enumerate_devices(_context: Any, output: Any) -> int:
        devices = (ctypes.c_void_p * (len(connected) + 1))(*connected, None)
        lists.append(devices)
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0] = (
            devices
        )
        return len(connected)

    def descriptor(_device: int, output: Any) -> int:
        ctypes.c_uint16.from_buffer(output, 8).value = 0x05AC
        ctypes.c_uint16.from_buffer(output, 10).value = 0x1223
        return 0

    def open_device(_device: int, output: Any) -> int:
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = 200
        return 0

    def configuration(_handle: Any, output: Any) -> int:
        ctypes.cast(output, ctypes.POINTER(ctypes.c_int))[0] = 1
        return 0

    native.libusb_init.side_effect = initialize
    native.libusb_get_device_list.side_effect = enumerate_devices
    native.libusb_get_device_descriptor.side_effect = descriptor
    native.libusb_get_bus_number.return_value = 1
    native.libusb_get_device_address.return_value = 2
    native.libusb_open.side_effect = open_device
    native.libusb_get_configuration.side_effect = configuration
    native.libusb_set_auto_detach_kernel_driver.return_value = -12
    native.libusb_claim_interface.return_value = 0
    return native, connected


def test_reconnected_device_at_same_address_cannot_reuse_old_endpoint() -> None:
    native, connected = native_library()
    control = usb.LibusbControl(library=native)
    endpoint = control.discover(UUID(int=1), 0x05AC, 0x1223)[0]
    assert control.discover(UUID(int=1), 0x05AC, 0x1223) == (endpoint,)
    native.libusb_ref_device.assert_called_once_with(100)
    connected[:] = [101]
    with pytest.raises(UsbControlError, match="connection changed"):
        control.open(endpoint)
    replacement = control.discover(UUID(int=1), 0x05AC, 0x1223)[0]
    assert replacement.interface_path == endpoint.interface_path
    assert replacement.instance_id != endpoint.instance_id
    native.libusb_unref_device.assert_called_once_with(100)
    native.libusb_open.assert_not_called()


def test_disconnect_during_open_closes_handle_without_protocol_request() -> None:
    native, connected = native_library()
    control = usb.LibusbControl(library=native)
    endpoint = control.discover(UUID(int=1), 0x05AC, 0x1223)[0]

    def claim(_handle: Any, _interface: int) -> int:
        connected.clear()
        return 0

    native.libusb_claim_interface.side_effect = claim
    with pytest.raises(UsbControlError, match="changed while opening"):
        control.open(endpoint)
    native.libusb_close.assert_called_once()
    native.libusb_control_transfer.assert_not_called()


@pytest.mark.parametrize(
    "code,error",
    [
        (-3, usb.LibusbOpenError),
        (-12, usb.LibusbOpenError),
        (-6, DeviceBusyError),
        (-4, UsbControlError),
    ],
)
def test_claim_failure_is_terminal_and_releases_handle(
    code: int, error: type[Exception]
) -> None:
    native, _connected = native_library()
    native.libusb_claim_interface.return_value = code
    control = usb.LibusbControl(library=native)
    endpoint = control.discover(UUID(int=1), 0x05AC, 0x1223)[0]
    with pytest.raises(error):
        control.open(endpoint)
    native.libusb_close.assert_called_once()
    native.libusb_release_interface.assert_not_called()


def test_control_request_fields_and_actual_read_length_are_preserved() -> None:
    native, _connected = native_library()
    control = usb.LibusbControl(library=native)
    endpoint = control.discover(UUID(int=1), 0x05AC, 0x1223)[0]
    channel = control.open(endpoint)

    def transfer(
        _handle: Any,
        kind: int,
        request: int,
        value: int,
        index: int,
        buffer: Any,
        length: int,
        timeout: int,
    ) -> int:
        assert (kind, request, value, index, length, timeout) == (
            0xA0,
            0xFE,
            0xEAFF,
            6,
            528,
            6000,
        )
        ctypes.memmove(buffer, b"data", 4)
        return 4

    native.libusb_control_transfer.side_effect = transfer
    response = channel.execute(
        UsbControlRequest(
            0xA0,
            0xFE,
            0xEAFF,
            6,
            data_in_length=528,
            allow_short_read=True,
            timeout_ms=6000,
        )
    )
    assert response.data == b"data" and response.transferred == 4
    channel.close()
    channel.close()
    native.libusb_close.assert_called_once()
    native.libusb_exit.assert_not_called()
    native.libusb_reset_device.assert_not_called()
    native.libusb_set_configuration.assert_not_called()


def test_discovery_preserves_ambiguity_and_wrong_vendor_is_excluded() -> None:
    native, connected = native_library()
    connected.append(101)
    control = usb.LibusbControl(library=native)
    endpoints = control.discover(UUID(int=1), 0x05AC, 0x1223)
    assert len(endpoints) == 2
    assert endpoints[0].instance_id != endpoints[1].instance_id
    with pytest.raises(UsbControlError):
        control.open(replace(endpoints[0], vendor_id=1))
    native.libusb_open.assert_not_called()


def test_native_bundled_runtime_loads_without_enumeration() -> None:
    libusb_runtime.check_runtime()
