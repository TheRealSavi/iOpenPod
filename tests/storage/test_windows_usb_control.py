"""Native packet ABI, exclusive path binding, and cancellation-buffer lifetime."""

import ctypes
from typing import Any
from uuid import UUID

import pytest

from storage import (
    DeviceBusyError,
    UsbControlEndpoint,
    UsbControlError,
    UsbControlRequest,
)
from storage.platform import windows_usb_control as native

ENDPOINT = UsbControlEndpoint(
    UUID(int=1),
    r"\\?\usb#vid_1234&pid_5678#device#{00000000-0000-0000-0000-000000000001}\usb#hub#mux1",
    "USB\\test",
    0x1234,
    0x5678,
)


class _Kernel:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.pending = False
        self.fail_wait = False
        self.fail_open = False
        self.transfer_count = 9
        self.buffer: Any = None

    def CreateFileW(
        self,
        path: str,
        access: int,
        share: int,
        security: object,
        disposition: int,
        flags: int,
        template: object,
    ) -> int:
        assert (access, share, security, disposition, template) == (
            0xC0000000,
            0,
            None,
            3,
            None,
        )
        self.events.append((path, flags))
        return -1 if self.fail_open else len(self.events) + 100

    def CreateEventW(self, *args: object) -> int:
        assert args == (None, 1, 0, None)
        return 999

    def CloseHandle(self, handle: int) -> bool:
        self.events.append(("close", handle))
        return True

    def ReadFile(
        self, handle: int, packet: Any, length: int, transferred: Any, overlapped: Any
    ) -> bool:
        assert handle == 102
        self.buffer = packet
        assert bytes(packet) == bytes.fromhex("a10500000000010000")
        ctypes.memmove(ctypes.addressof(packet) + 8, b"\x02", 1)
        ctypes.cast(transferred, ctypes.POINTER(ctypes.c_uint32))[0] = (
            self.transfer_count
        )
        self.events.append("read")
        return not self.pending

    def GetOverlappedResultEx(
        self, handle: int, overlapped: Any, count: Any, timeout: int, alertable: int
    ) -> bool:
        assert (handle, timeout, alertable) == (102, 2000, 0)
        self.events.append("wait")
        return not self.fail_wait

    def CancelIoEx(self, handle: int, overlapped: Any) -> bool:
        assert bytes(self.buffer)[8:] == b"\x02"
        self.events.append("cancel")
        return True

    def GetOverlappedResult(
        self, handle: int, overlapped: Any, count: Any, wait: int
    ) -> bool:
        assert wait == 1 and bytes(self.buffer)[8:] == b"\x02"
        self.events.append("drain")
        return False


class _Api(native.WindowsUsbControl):
    def __init__(self, kernel: _Kernel) -> None:
        super().__init__(kernel=kernel, setup=object())
        self.discoveries = 0
        self.change_identity = False

    def discover(
        self, interface_class: UUID, vendor_id: int, product_id: int
    ) -> tuple[UsbControlEndpoint, ...]:
        self.discoveries += 1
        return () if self.change_identity and self.discoveries > 1 else (ENDPOINT,)


def test_exclusive_open_rechecks_identity_and_retains_both_handles() -> None:
    kernel = _Kernel()
    api = _Api(kernel)
    channel = api.open(ENDPOINT)
    assert api.discoveries == 2
    assert kernel.events == [
        (ENDPOINT.interface_path, 0),
        (ENDPOINT.interface_path + "\\PIPE0", 0x40000000),
    ]
    assert channel.execute(UsbControlRequest(0xA1, 5, data_in_length=1)).data == b"\x02"
    channel.close()
    channel.close()
    assert kernel.events[-2:] == [("close", 102), ("close", 101)]


def test_identity_change_closes_both_handles_before_any_transfer() -> None:
    kernel = _Kernel()
    api = _Api(kernel)
    api.change_identity = True
    with pytest.raises(UsbControlError, match="changed"):
        api.open(ENDPOINT)
    assert kernel.events[-2:] == [("close", 102), ("close", 101)]


def test_timeout_cancels_and_drains_before_releasing_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = _Kernel()
    kernel.pending = kernel.fail_wait = True
    errors = iter((997, 258))
    monkeypatch.setattr(native, "_error", lambda: next(errors))
    channel = _Api(kernel).open(ENDPOINT)
    with pytest.raises(UsbControlError, match="timed out"):
        channel.execute(UsbControlRequest(0xA1, 5, data_in_length=1))
    assert kernel.events[-5:] == ["read", "wait", "cancel", "drain", ("close", 999)]
    channel.close()


def test_exclusivity_failure_has_no_shared_access_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = _Kernel()
    kernel.fail_open = True
    # ctypes represents INVALID_HANDLE_VALUE as an unsigned pointer-sized value.
    monkeypatch.setattr(native, "_INVALID", -1)
    monkeypatch.setattr(native, "_error", lambda: 32)
    with pytest.raises(DeviceBusyError):
        _Api(kernel).open(ENDPOINT)
    assert kernel.events == [(ENDPOINT.interface_path, 0)]


@pytest.mark.parametrize("count", [0, 7, 10])
def test_invalid_driver_packet_lengths_are_rejected(count: int) -> None:
    kernel = _Kernel()
    kernel.transfer_count = count
    channel = _Api(kernel).open(ENDPOINT)
    with pytest.raises(UsbControlError):
        channel.execute(UsbControlRequest(0xA1, 5, data_in_length=1))
    channel.close()
