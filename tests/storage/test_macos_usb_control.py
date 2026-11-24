"""IOKit interface identity, native request ABI and retained-handle lifecycle."""

import ctypes
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from storage import (
    DeviceBusyError,
    UsbControlEndpoint,
    UsbControlError,
    UsbControlRequest,
)
from storage.platform import macos_usb_control as usb
from storage.platform.macos_usb_control import (
    _RequestTO,  # pyright: ignore[reportPrivateUsage] -- native ABI under test
    _UUIDBytes,  # pyright: ignore[reportPrivateUsage] -- native ABI under test
)

ENDPOINT = UsbControlEndpoint(
    UUID(int=1),
    "iokit-usb:0000000000001234",
    "registry:0000000000001234:location:00100000",
    0x05AC,
    0x1223,
)

type Adapter = tuple[usb.MacOSUsbControl, MagicMock]


def test_native_request_abi_matches_iousblib_header() -> None:
    assert ctypes.sizeof(_UUIDBytes) == 16
    assert _RequestTO.data.offset == 8
    assert _RequestTO.transferred.offset == 8 + ctypes.sizeof(ctypes.c_void_p)
    assert _RequestTO.completion_timeout.offset == 16 + ctypes.sizeof(ctypes.c_void_p)


def test_control_fields_and_payload_are_forwarded_to_device_request_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    payload = bytes(range(256)) * 4

    def call(
        _device: Any, slot: int, _result: Any, _types: list[Any], *arguments: Any
    ) -> int:
        calls.append(slot)
        if slot == 30:
            request = ctypes.cast(arguments[0], ctypes.POINTER(_RequestTO)).contents
            if request.request_type == 0xA0:
                assert (
                    request.request,
                    request.value,
                    request.index,
                    request.length,
                ) == (0xFE, 0xEAFF, 6, 528)
                ctypes.memmove(request.data, b"\x02" * 528, 528)
            else:
                assert (
                    request.request_type,
                    request.request,
                    request.value,
                    request.index,
                ) == (0x21, 1, 9, 0)
                assert ctypes.string_at(request.data, request.length) == payload
            assert request.no_data_timeout == request.completion_timeout == 2000
            request.transferred = request.length
        return 0

    monkeypatch.setattr(usb, "vtable_call", call)
    channel = usb.MacOSUsbControlChannel(ctypes.c_void_p(44))
    channel.opened = True
    assert (
        channel.execute(
            UsbControlRequest(0xA0, 0xFE, 0xEAFF, 6, data_in_length=528)
        ).data
        == b"\x02" * 528
    )
    assert (
        channel.execute(UsbControlRequest(0x21, 1, 9, data_out=payload)).transferred
        == 1024
    )
    channel.close()
    channel.close()
    assert calls == [30, 30, 9, 3]
    with pytest.raises(UsbControlError):
        channel.execute(UsbControlRequest(0xA1, 5, data_in_length=1))


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> Adapter:
    frameworks = MagicMock()
    frameworks.iokit.IOServiceGetMatchingService.return_value = 100
    result = usb.MacOSUsbControl(frameworks=frameworks)

    def endpoint(_service: int, _interface_class: UUID) -> UsbControlEndpoint:
        return ENDPOINT

    def device_interface(_service: int) -> ctypes.c_void_p:
        return ctypes.c_void_p(44)

    monkeypatch.setattr(result, "_endpoint", endpoint)
    monkeypatch.setattr(result, "_interface", device_interface)
    return result, frameworks


def test_open_checks_held_vendor_and_product_and_never_resets(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, frameworks = adapter
    calls: list[int] = []

    def call(
        _device: Any, slot: int, _result: Any, _types: list[Any], *arguments: Any
    ) -> int:
        calls.append(slot)
        if slot in (13, 14):
            ctypes.cast(
                arguments[0], ctypes.POINTER(ctypes.c_uint16)
            ).contents.value = 0x05AC if slot == 13 else 0x1223
        return 0

    monkeypatch.setattr(usb, "vtable_call", call)
    channel = result.open(ENDPOINT)
    channel.close()
    assert calls == [8, 13, 14, 9, 3]
    frameworks.iokit.IOObjectRelease.assert_called_once_with(100)


def test_identity_change_after_open_closes_without_a_transfer(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _frameworks = adapter
    endpoints = iter((ENDPOINT, replace(ENDPOINT, instance_id="reconnected")))

    def next_endpoint(_service: int, _interface_class: UUID) -> UsbControlEndpoint:
        return next(endpoints)

    monkeypatch.setattr(result, "_endpoint", next_endpoint)
    call = MagicMock(return_value=0)
    monkeypatch.setattr(usb, "vtable_call", call)
    with pytest.raises(UsbControlError, match="connection changed"):
        result.open(ENDPOINT)
    assert [c.args[1] for c in call.call_args_list] == [8, 9, 3]


def test_busy_open_does_not_seize_or_retry(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _frameworks = adapter
    call = MagicMock(side_effect=[0xE00002C5, 0])
    monkeypatch.setattr(usb, "vtable_call", call)
    with pytest.raises(DeviceBusyError):
        result.open(ENDPOINT)
    assert [c.args[1] for c in call.call_args_list] == [8, 3]


def test_plugin_query_uses_the_versioned_interface_and_releases_plugin(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, frameworks = adapter
    result = usb.MacOSUsbControl(frameworks=frameworks)

    def endpoint(_service: int, _interface_class: UUID) -> UsbControlEndpoint:
        return ENDPOINT

    monkeypatch.setattr(result, "_endpoint", endpoint)

    def create(
        _service: int, _client: Any, _plugin_type: Any, output: Any, _score: Any
    ) -> int:
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p)).contents.value = 50
        return 0

    def call(
        _plugin: Any, slot: int, _result: Any, _types: list[Any], *arguments: Any
    ) -> int:
        if slot == 1:
            ctypes.cast(
                arguments[1], ctypes.POINTER(ctypes.c_void_p)
            ).contents.value = 44
        elif slot in (13, 14):
            ctypes.cast(
                arguments[0], ctypes.POINTER(ctypes.c_uint16)
            ).contents.value = ENDPOINT.vendor_id if slot == 13 else ENDPOINT.product_id
        return 0

    frameworks.iokit.IOCreatePlugInInterfaceForService.side_effect = create
    call_mock = MagicMock(side_effect=call)
    monkeypatch.setattr(usb, "vtable_call", call_mock)
    channel = result.open(ENDPOINT)
    channel.close()
    assert [c.args[1] for c in call_mock.call_args_list] == [1, 3, 8, 13, 14, 9, 3]
    assert frameworks.uuid_from_bytes.call_args.args == tuple(
        UUID("c809b8d8-0884-11d7-bb96-0003933e3e3e").bytes
    )
