"""USB request bounds, exclusive lifecycle, and terminal transfer failures."""

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from storage import (
    DeviceBusyError,
    Storage,
    UsbControlEndpoint,
    UsbControlError,
    UsbControlRequest,
    UsbControlResponse,
)
from storage.testing import VirtualStoragePlatform

ENDPOINT = UsbControlEndpoint(UUID(int=1), "test-interface", "test-instance", 1, 2)
READ = UsbControlRequest(0xA1, 5, data_in_length=1)


class _Channel:
    def __init__(self) -> None:
        self.requests: list[UsbControlRequest] = []
        self.response: UsbControlResponse | Exception = UsbControlResponse(b"\x02", 1)
        self.closed = 0

    def execute(self, request: UsbControlRequest) -> UsbControlResponse:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def close(self) -> None:
        self.closed += 1


class _Platform(VirtualStoragePlatform):
    def __init__(self) -> None:
        super().__init__()
        self.channel = _Channel()
        self.fail_open = False

    def discover_usb_control(
        self, guid: UUID, vendor: int, product: int
    ) -> tuple[UsbControlEndpoint, ...]:
        return (ENDPOINT,)

    def open_usb_control_channel(self, endpoint: UsbControlEndpoint) -> _Channel:
        assert endpoint == ENDPOINT
        if self.fail_open:
            raise DeviceBusyError("native handle is busy")
        return self.channel


def test_usb_access_excludes_other_sessions_and_close_sends_no_commands(
    tmp_path: Path,
) -> None:
    platform = _Platform()
    platform.add_volume(tmp_path)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    mounted = storage.inspect(tmp_path)
    with storage.open_session(mounted), pytest.raises(DeviceBusyError):
        storage.open_usb_control_session(ENDPOINT)
    with storage.open_usb_control_session(ENDPOINT) as session:
        assert session.execute(READ).data == b"\x02"
        with pytest.raises(DeviceBusyError):
            storage.open_usb_control_session(ENDPOINT)
        with pytest.raises(DeviceBusyError):
            storage.open_session(mounted)
        with pytest.raises(DeviceBusyError):
            storage.probe_hardware(mounted)
    assert platform.channel.requests == [READ]
    assert platform.channel.closed == 1
    with pytest.raises(UsbControlError):
        session.execute(READ)
    with storage.open_session(mounted):
        pass


@pytest.mark.parametrize(
    "response",
    [
        UsbControlResponse(b"", 0),
        UsbControlResponse(b"xx", 1),
        UsbControlResponse(b"xx", 2),
        OSError("disconnected"),
        TimeoutError("uncertain"),
    ],
)
def test_failure_closes_without_retry_and_releases_lease(
    tmp_path: Path, response: UsbControlResponse | Exception
) -> None:
    platform = _Platform()
    platform.channel.response = response
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    session = storage.open_usb_control_session(ENDPOINT)
    with pytest.raises((UsbControlError, OSError)):
        session.execute(READ)
    with pytest.raises(UsbControlError):
        session.execute(READ)
    assert platform.channel.requests == [READ]
    assert platform.channel.closed == 1
    with storage.open_usb_control_session(ENDPOINT) as replacement:
        assert replacement.connection_generation != session.connection_generation


def test_open_failure_releases_reservation_and_short_reads_need_opt_in(
    tmp_path: Path,
) -> None:
    platform = _Platform()
    platform.fail_open = True
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with pytest.raises(DeviceBusyError):
        storage.open_usb_control_session(ENDPOINT)
    platform.fail_open = False
    platform.channel.response = UsbControlResponse(b"", 0)
    with storage.open_usb_control_session(ENDPOINT) as session:
        assert session.execute(replace(READ, allow_short_read=True)).transferred == 0


def test_setup_packet_preserves_request_fields_and_validates_direction() -> None:
    request = UsbControlRequest(0xA0, 0xFE, 0xEAFF, 6, data_in_length=528)
    assert request.setup_packet() == bytes.fromhex("a0feffea06001002")
    assert UsbControlRequest(0x21, 1).setup_packet() == bytes.fromhex(
        "2101000000000000"
    )
    for changes in (
        {"data_out": b"x"},
        {"value": 65536},
        {"index": -1},
        {"data_in_length": 65536},
        {"timeout_ms": 0},
        {"request": True},
    ):
        with pytest.raises(ValueError):
            replace(READ, **changes)
    with pytest.raises(ValueError):
        UsbControlRequest(0x21, 1, data_in_length=1)
    with pytest.raises(ValueError):
        UsbControlRequest(0x21, 1, allow_short_read=True)
