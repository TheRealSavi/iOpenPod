"""Windows chooses a transport only before the first protocol request."""

from dataclasses import replace
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from storage import (
    DeviceBusyError,
    UsbControlDriverError,
    UsbControlEndpoint,
    UsbControlError,
    UsbControlRequest,
)
from storage.platform import libusb_control
from storage.platform import windows_usb_backend as usb
from storage.platform.libusb_control import LibusbOpenError

ENDPOINT = UsbControlEndpoint(UUID(int=1), "libusb:1:2", "generation", 0x05AC, 0x1223)
APPLE = replace(ENDPOINT, interface_path="apple-path", instance_id="apple-instance")


@pytest.fixture
def backends(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    libusb, apple = MagicMock(), MagicMock()
    libusb.discover.return_value = (ENDPOINT,)
    apple.discover.return_value = (APPLE,)
    monkeypatch.setattr(libusb_control, "control", lambda: libusb)
    monkeypatch.setattr(usb, "WindowsUsbControl", lambda: apple)
    return libusb, apple


def test_libusb_is_preferred_and_device_is_not_counted_twice(
    backends: tuple[MagicMock, MagicMock],
) -> None:
    libusb, apple = backends
    adapter = usb.WindowsUsbBackend()
    assert adapter.discover(UUID(int=1), 0x05AC, 0x1223) == (ENDPOINT,)
    assert adapter.open(ENDPOINT) is libusb.open.return_value
    apple.open.assert_not_called()


def test_unavailable_apple_api_does_not_block_libusb(
    backends: tuple[MagicMock, MagicMock],
) -> None:
    libusb, apple = backends
    apple.discover.side_effect = UsbControlError("Apple interface enumeration failed")
    adapter = usb.WindowsUsbBackend()
    assert adapter.discover(UUID(int=1), 0x05AC, 0x1223) == (ENDPOINT,)
    assert adapter.open(ENDPOINT) is libusb.open.return_value


def test_apple_only_enumeration_can_open_the_installed_driver(
    backends: tuple[MagicMock, MagicMock],
) -> None:
    libusb, apple = backends
    libusb.discover.return_value = ()
    adapter = usb.WindowsUsbBackend()
    assert adapter.discover(UUID(int=1), 0x05AC, 0x1223) == (APPLE,)
    assert adapter.open(APPLE) is apple.open.return_value
    libusb.open.assert_not_called()


def test_apple_fallback_only_after_open_failure(
    backends: tuple[MagicMock, MagicMock],
) -> None:
    libusb, apple = backends
    libusb.open.side_effect = LibusbOpenError("unsupported driver")
    assert usb.WindowsUsbBackend().open(ENDPOINT) is apple.open.return_value
    apple.open.assert_called_once_with(APPLE)


@pytest.mark.parametrize(
    "error", [DeviceBusyError("busy"), UsbControlError("disconnected")]
)
def test_busy_or_changed_connection_never_tries_another_driver(
    backends: tuple[MagicMock, MagicMock], error: Exception
) -> None:
    libusb, apple = backends
    libusb.open.side_effect = error
    with pytest.raises(type(error)):
        usb.WindowsUsbBackend().open(ENDPOINT)
    apple.open.assert_not_called()


def test_transfer_failure_never_falls_back_or_replays(
    backends: tuple[MagicMock, MagicMock],
) -> None:
    libusb, apple = backends
    channel = usb.WindowsUsbBackend().open(ENDPOINT)
    libusb.open.return_value.execute.side_effect = UsbControlError("timeout")
    with pytest.raises(UsbControlError):
        channel.execute(UsbControlRequest(0x21, 1, data_out=b"writer"))
    libusb.open.return_value.execute.assert_called_once()
    apple.open.assert_not_called()


def test_missing_drivers_explains_apple_device_support(
    backends: tuple[MagicMock, MagicMock],
) -> None:
    libusb, apple = backends
    libusb.open.side_effect = LibusbOpenError("unsupported")
    apple.discover.return_value = ()
    with pytest.raises(UsbControlDriverError, match="No compatible"):
        usb.WindowsUsbBackend().open(ENDPOINT)


def test_ambiguous_apple_candidates_are_never_chosen(
    backends: tuple[MagicMock, MagicMock],
) -> None:
    libusb, apple = backends
    libusb.open.side_effect = LibusbOpenError("unsupported")
    apple.discover.return_value = (APPLE, replace(APPLE, instance_id="other"))
    assert len(usb.WindowsUsbBackend().discover(UUID(int=1), 0x05AC, 0x1223)) == 2
    with pytest.raises(UsbControlError, match="only the selected"):
        usb.WindowsUsbBackend().open(ENDPOINT)
    apple.open.assert_not_called()


def test_disconnect_during_fallback_closes_apple_handle(
    backends: tuple[MagicMock, MagicMock],
) -> None:
    libusb, apple = backends
    libusb.open.side_effect = LibusbOpenError("unsupported")
    libusb.discover.side_effect = [(ENDPOINT,), ()]
    with pytest.raises(UsbControlError, match="changed during"):
        usb.WindowsUsbBackend().open(ENDPOINT)
    apple.open.return_value.close.assert_called_once()
