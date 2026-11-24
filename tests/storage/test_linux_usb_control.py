"""Linux libusb transfer fidelity, retained identity and authorization boundaries."""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from storage import (
    DeviceBusyError,
    UsbControlAuthorizationError,
    UsbControlEndpoint,
    UsbControlError,
    UsbControlRequest,
)
from storage.platform import libusb_runtime, linux_usb_access, linux_usb_control
from storage.platform.linux_usb_control import LinuxUsbControl, LinuxUsbControlChannel

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

type Channel = tuple[LinuxUsbControlChannel, MagicMock, int]

DEVICE = linux_usb_access.LinuxUsbDevice(
    "/dev/bus/usb/001/002", "sysfs-generation", 0x05AC, 0x1223
)
ENDPOINT = UsbControlEndpoint(
    UUID(int=1), DEVICE.path, DEVICE.instance, DEVICE.vendor, DEVICE.product
)


def library() -> MagicMock:
    native = MagicMock()

    def initialize(output: Any) -> int:
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents.value = 10
        return 0

    def wrap(_context: Any, _descriptor: int, output: Any) -> int:
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents.value = 20
        return 0

    native.libusb_init.side_effect = initialize
    native.libusb_wrap_sys_device.side_effect = wrap
    for name in (
        "set_configuration",
        "kernel_driver_active",
        "detach_kernel_driver",
        "claim_interface",
    ):
        getattr(native, "libusb_" + name).return_value = 0
    return native


@pytest.fixture
def channel(tmp_path: Path) -> Iterator[Channel]:
    path = tmp_path / "handle"
    path.touch()
    descriptor = os.open(path, os.O_RDWR)
    native = library()
    result = LinuxUsbControlChannel(native, descriptor)
    result.open()
    try:
        yield result, native, descriptor
    finally:
        result.close()


def test_exploit_control_fields_timeouts_and_actual_lengths_are_preserved(
    channel: Channel,
) -> None:
    transport, native, descriptor = channel

    def transfer(
        _handle: Any,
        kind: int,
        request: int,
        value: int,
        index: int,
        buffer: Any,
        size: int,
        timeout: int,
    ) -> int:
        assert (kind, request, value, index, size, timeout) == (
            0xA0,
            0xFE,
            0xEAFF,
            6,
            528,
            2000,
        )
        ctypes.memmove(buffer, b"\x02" * 528, 528)
        return 528

    native.libusb_control_transfer.side_effect = transfer
    request = UsbControlRequest(0xA0, 0xFE, 0xEAFF, 6, data_in_length=528)
    assert transport.execute(request).data == b"\x02" * 528
    native.libusb_wrap_sys_device.assert_called_once()
    assert native.libusb_wrap_sys_device.call_args.args[1] == descriptor
    names = [call[0] for call in native.mock_calls]
    assert names[:5] == [
        "libusb_init",
        "libusb_wrap_sys_device",
        "libusb_set_configuration",
        "libusb_kernel_driver_active",
        "libusb_claim_interface",
    ]


def test_write_payload_is_exact_and_close_does_not_reset_or_send_requests(
    channel: Channel,
) -> None:
    transport, native, descriptor = channel
    payload = bytes(range(256)) * 4

    def transfer(
        _handle: Any,
        kind: int,
        request: int,
        value: int,
        index: int,
        buffer: Any,
        size: int,
        timeout: int,
    ) -> int:
        assert (kind, request, value, index, size, timeout) == (
            0x21,
            1,
            7,
            0,
            1024,
            6000,
        )
        assert ctypes.string_at(buffer, size) == payload
        return size

    native.libusb_control_transfer.side_effect = transfer
    assert (
        transport.execute(
            UsbControlRequest(0x21, 1, 7, data_out=payload, timeout_ms=6000)
        ).transferred
        == 1024
    )
    transport.close()
    transport.close()
    native.libusb_control_transfer.assert_called_once()
    native.libusb_close.assert_called_once()
    native.libusb_release_interface.assert_called_once()
    native.libusb_reset_device.assert_not_called()
    with pytest.raises(OSError):
        os.fstat(descriptor)
    with pytest.raises(UsbControlError):
        transport.execute(UsbControlRequest(0xA1, 5, data_in_length=1))


@pytest.mark.parametrize(
    "code,error",
    [
        (-3, UsbControlError),
        (-4, UsbControlError),
        (-6, DeviceBusyError),
        (-7, UsbControlError),
    ],
)
def test_transfer_error_is_reported_without_retry(
    channel: Channel, code: int, error: type[Exception]
) -> None:
    transport, native, _descriptor = channel
    native.libusb_control_transfer.return_value = code
    with pytest.raises(error):
        transport.execute(UsbControlRequest(0xA1, 5, data_in_length=1))
    native.libusb_control_transfer.assert_called_once()


def test_authorization_rechecks_the_selected_connection_before_libusb_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "held"
    path.touch()
    descriptor = os.open(path, os.O_RDWR)
    native = library()
    monkeypatch.setattr(linux_usb_control, "load_library", lambda: native)
    current = [DEVICE]
    monkeypatch.setattr(linux_usb_access, "devices", lambda: tuple(current))

    opens = 0

    def denied(_path: str, _instance: str) -> int:
        nonlocal opens
        opens += 1
        if opens == 1:
            raise PermissionError("device access denied")
        return descriptor

    def authorize(_vendor: int, _product: int) -> None:
        current[:] = [replace(DEVICE, instance="replacement")]

    monkeypatch.setattr(linux_usb_access, "open_device", denied)
    monkeypatch.setattr(linux_usb_control, "authorize", authorize)
    with pytest.raises(UsbControlError, match="changed during authorization"):
        LinuxUsbControl().open(ENDPOINT)
    native.libusb_wrap_sys_device.assert_not_called()
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_claim_failure_closes_native_and_os_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "held"
    path.touch()
    descriptor = os.open(path, os.O_RDWR)
    native = library()
    native.libusb_claim_interface.return_value = -6

    def open_device(_path: str, _instance: str) -> int:
        return descriptor

    monkeypatch.setattr(linux_usb_control, "load_library", lambda: native)
    monkeypatch.setattr(linux_usb_access, "devices", lambda: (DEVICE,))
    monkeypatch.setattr(linux_usb_access, "open_device", open_device)
    with pytest.raises(DeviceBusyError):
        LinuxUsbControl().open(ENDPOINT)
    native.libusb_close.assert_called_once()
    native.libusb_exit.assert_called_once()
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_first_permission_setup_reopens_as_user_without_elevated_usb_transfer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "held"
    path.touch()
    descriptor = os.open(path, os.O_RDWR)
    native = library()
    opened = MagicMock(side_effect=[PermissionError("denied"), descriptor])
    authorize = MagicMock()
    monkeypatch.setattr(linux_usb_control, "load_library", lambda: native)
    monkeypatch.setattr(linux_usb_access, "devices", lambda: (DEVICE,))
    monkeypatch.setattr(linux_usb_access, "open_device", opened)
    monkeypatch.setattr(linux_usb_control, "authorize", authorize)
    channel = LinuxUsbControl().open(ENDPOINT)
    try:
        authorize.assert_called_once_with(DEVICE.vendor, DEVICE.product)
        assert opened.call_count == 2
        assert all(
            call.args == (DEVICE.path, DEVICE.instance)
            for call in opened.call_args_list
        )
        assert native.libusb_wrap_sys_device.call_args.args[1] == descriptor
        native.libusb_control_transfer.assert_not_called()
    finally:
        channel.close()


def test_permission_denial_never_opens_libusb_or_prompts_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = library()
    opened = MagicMock(side_effect=PermissionError("denied"))
    authorize = MagicMock(side_effect=UsbControlAuthorizationError("denied"))
    monkeypatch.setattr(linux_usb_control, "load_library", lambda: native)
    monkeypatch.setattr(linux_usb_access, "devices", lambda: (DEVICE,))
    monkeypatch.setattr(linux_usb_access, "open_device", opened)
    monkeypatch.setattr(linux_usb_control, "authorize", authorize)
    with pytest.raises(UsbControlAuthorizationError):
        LinuxUsbControl().open(ENDPOINT)
    authorize.assert_called_once()
    opened.assert_called_once()
    native.libusb_init.assert_not_called()


def test_missing_packaged_library_never_falls_back_to_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = MagicMock()
    package.get_library_path.return_value = None

    def imported_package(_name: str) -> MagicMock:
        return package

    monkeypatch.setattr(libusb_runtime, "import_module", imported_package)
    with pytest.raises(UsbControlError, match="bundled libusb"):
        libusb_runtime.load_library()
    package.find_library.assert_not_called()


def test_discovery_preserves_multiple_devices_and_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, address in (("1-1", 2), ("1-2", 3)):
        device = tmp_path / name
        device.mkdir()
        for filename, value in (
            ("busnum", "1"),
            ("devnum", str(address)),
            ("idVendor", "05ac"),
            ("idProduct", "1223"),
        ):
            (device / filename).write_text(value)
    monkeypatch.setattr(linux_usb_access, "USB_DEVICES", tmp_path)
    endpoints = LinuxUsbControl().discover(UUID(int=1), 0x05AC, 0x1223)
    assert len(endpoints) == 2
    first = endpoints[0]
    (tmp_path / "1-1/devnum").write_text("4")
    assert first not in LinuxUsbControl().discover(UUID(int=1), 0x05AC, 0x1223)


@pytest.mark.skipif(
    sys.platform != "linux", reason="Requires the packaged Linux library"
)
def test_bundled_libusb_loads_without_device_access() -> None:
    linux_usb_control.check_runtime()


def test_runtime_smoke_check_does_not_initialize_device_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = library()
    native.libusb_get_version.return_value = 123
    monkeypatch.setattr(linux_usb_control, "load_library", lambda: native)
    linux_usb_control.check_runtime()
    native.libusb_get_version.assert_called_once()
    native.libusb_init.assert_not_called()
