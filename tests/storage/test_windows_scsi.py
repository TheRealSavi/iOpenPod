"""Exercise the Windows ABI and exclusive handle with a simulated kernel API."""

import ctypes
import struct
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from storage import (
    DeviceBusyError,
    PhysicalDeviceId,
    ScsiCommand,
    ScsiCommandError,
    ScsiIdentity,
    ScsiSessionError,
    VolumeId,
    VolumeIdentityChangedError,
)
from storage.models import VolumeObservation
from storage.platform.windows_scsi import (
    WindowsScsiChannel,
    _Packet,  # pyright: ignore[reportPrivateUsage] -- native ABI under test
    _PassThrough,  # pyright: ignore[reportPrivateUsage] -- native ABI under test
)
from storage.scsi import checked_response
from storage.testing import VirtualStoragePlatform

IDENTITY = ScsiIdentity("Apple", "iPod", "test-serial")
GUID = "\\\\?\\Volume{01234567-89ab-cdef-0123-456789abcdef}\\"


def _observation(tmp_path: Path) -> VolumeObservation:
    platform = VirtualStoragePlatform()
    original = platform.add_volume(tmp_path)
    device_id = PhysicalDeviceId("windows:disk-2")
    return replace(
        original,
        physical_device=replace(original.physical_device, id=device_id),
        volume=replace(
            original.volume,
            id=VolumeId(f"windows:{GUID}:0123ABCD"),
            physical_device_id=device_id,
        ),
    )


class _Kernel:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.closed: list[int] = []
        self.controls: list[int] = []
        self.commands: list[bytes] = []
        self.payloads: list[bytes] = []
        self.disk_number = 2
        self.serial = IDENTITY.serial
        self.changed_serial_after_lock = False
        self.fail_control: int | None = None
        self.mask = 4095
        self.maximum = 65536
        self.status = 0
        self.sense = b""
        self.transfer_delta = 0
        self.response_header_size = ctypes.sizeof(_Packet)
        self.returned_sense_length = 64

    def CreateFileW(self, path: str, *args: object) -> int:
        assert args == (0xC0000000, 3, None, 3, 0, None)
        self.opened.append(path)
        return 123

    def CloseHandle(self, handle: int) -> bool:
        self.closed.append(handle)
        return True

    def DeviceIoControl(
        self,
        handle: int,
        control: int,
        input_buffer: Any,
        input_length: int,
        output_buffer: Any,
        output_length: int,
        returned_pointer: Any,
        overlapped: object,
    ) -> bool:
        assert handle == 123 and overlapped is None
        self.controls.append(control)
        if self.fail_control == control:
            return False
        returned = ctypes.cast(returned_pointer, ctypes.POINTER(ctypes.c_uint32))
        if control == 0x2D1080:
            ctypes.memmove(
                output_buffer, struct.pack("<III", 7, self.disk_number, 1), 12
            )
            returned[0] = 12
        elif control == 0x2D1400:
            assert ctypes.string_at(input_buffer, input_length) == struct.pack(
                "<III", 1, 0, 0
            )
            descriptor = struct.pack("<IIIII", 32, 32, self.maximum, 17, self.mask)
            ctypes.memmove(output_buffer, descriptor, 20)
            returned[0] = 32
        elif control == 0x90018:
            assert input_length == output_length == 0
            if self.changed_serial_after_lock:
                self.serial = "replacement"
            returned[0] = 0
        elif control == 0x4D014:
            assert input_length == output_length == ctypes.sizeof(_Packet)
            packet = ctypes.cast(input_buffer, ctypes.POINTER(_Packet)).contents
            request = packet.request
            assert request.length == ctypes.sizeof(_PassThrough)
            assert request.sense_offset == _Packet.sense.offset
            assert request.sense_length == 64
            assert 1 <= request.timeout <= 60
            command = bytes(request.cdb[: request.cdb_length])
            self.commands.append(command)
            if request.transfer_length:
                assert request.data_buffer is not None
                assert request.data_buffer & max(self.mask, 4095) == 0
            if command[0] == 0x12:
                assert request.data_in == 1
                if command[2] == 0x80:
                    # Reproduce the Classic's longer declared length and short
                    # actual transfer, including NUL padding when supplied.
                    data = b"\0\x80\0\x20" + self.serial.encode("ascii")
                else:
                    data = b"\0" * 8 + b"Apple   " + b"iPod            " + b"1.00"
                ctypes.memmove(request.data_buffer, data, len(data))
                request.transfer_length = len(data)
            else:
                if request.data_in == 0:
                    self.payloads.append(
                        ctypes.string_at(request.data_buffer, request.transfer_length)
                    )
                elif request.data_in == 1:
                    ctypes.memset(request.data_buffer, 0x5A, request.transfer_length)
                request.transfer_length += self.transfer_delta
                request.status = self.status
                packet.sense[: len(self.sense)] = self.sense
                request.sense_length = self.returned_sense_length
            returned[0] = self.response_header_size
        else:
            pytest.fail(f"Unexpected control code: {control:x}")
        return True


def test_abi_has_native_windows_offsets() -> None:
    pointer_bytes = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(_PassThrough) == (56 if pointer_bytes == 8 else 44)
    assert _PassThrough.transfer_length.offset == 12
    assert _PassThrough.data_buffer.offset == (24 if pointer_bytes == 8 else 20)
    assert _Packet.sense.offset == ctypes.sizeof(_PassThrough)


def test_pinned_guid_identity_lock_alignment_and_cleanup(tmp_path: Path) -> None:
    kernel = _Kernel()
    channel = WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    assert kernel.opened == [GUID.rstrip("\\")]
    assert kernel.controls.count(0x90018) == 1
    assert [command[0] for command in kernel.commands] == [0x12] * 4
    command = ScsiCommand(b"\xc6\x91" + b"\0" * 8, data_out=b"firmware" * 4096)
    response = checked_response(command, channel.execute(command))
    assert response.transferred == 32768
    assert kernel.payloads == [command.data_out]
    before_close = kernel.commands.copy()
    channel.close()
    channel.close()
    assert kernel.commands == before_close
    assert kernel.closed == [123]
    with pytest.raises(ScsiSessionError):
        channel.execute(command)


@pytest.mark.parametrize("error", [5, 32, 1167])
def test_only_initial_access_denial_requests_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: int,
) -> None:
    from storage.platform import windows_scsi

    kernel = _Kernel()
    requests: list[tuple[str, int]] = []

    def authorize(volume: str, disk: int) -> int:
        requests.append((volume, disk))
        assert kernel.controls == [] and kernel.commands == []
        return 123

    def denied_open(*_args: object) -> int | None:
        return ctypes.c_void_p(-1).value

    monkeypatch.setattr(kernel, "CreateFileW", denied_open)
    monkeypatch.setattr(windows_scsi, "last_error", lambda: error)
    monkeypatch.setattr(windows_scsi, "authorized_open", authorize)
    if error == 5:
        channel = WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
        assert requests == [(GUID.rstrip("\\"), 2)]
        assert kernel.controls.count(0x90018) == 1
        assert len(kernel.commands) == 4
        channel.close()
        assert kernel.closed == [123]
    else:
        with pytest.raises(ScsiCommandError):
            WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
        assert requests == [] and kernel.controls == []


@pytest.mark.parametrize("after_lock", [False, True])
def test_serial_mismatch_never_sends_an_output_command(
    tmp_path: Path, after_lock: bool
) -> None:
    kernel = _Kernel()
    if after_lock:
        kernel.changed_serial_after_lock = True
    else:
        kernel.serial = "wrong-device"
    with pytest.raises(VolumeIdentityChangedError):
        WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    assert kernel.closed == [123]
    assert kernel.payloads == []
    assert {command[0] for command in kernel.commands} == {0x12}
    assert kernel.controls.count(0x90018) == int(after_lock)


def test_disk_mismatch_fails_before_inquiry_or_lock(tmp_path: Path) -> None:
    kernel = _Kernel()
    kernel.disk_number = 3
    with pytest.raises(VolumeIdentityChangedError):
        WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    assert kernel.closed == [123]
    assert kernel.commands == []
    assert 0x90018 not in kernel.controls


def test_lock_denial_closes_without_dismount_or_retry(tmp_path: Path) -> None:
    kernel = _Kernel()
    kernel.fail_control = 0x90018
    with pytest.raises(DeviceBusyError):
        WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    assert kernel.controls.count(0x90018) == 1
    assert 0x90020 not in kernel.controls  # FSCTL_DISMOUNT_VOLUME
    assert kernel.closed == [123]


@pytest.mark.parametrize("serial", ["", "\x01bad", "test-serial\0\0\0"])
def test_serial_is_validated_and_only_trailing_padding_is_stripped(
    tmp_path: Path, serial: str
) -> None:
    kernel = _Kernel()
    kernel.serial = serial
    if serial.startswith("test-serial"):
        WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY).close()
    else:
        with pytest.raises(ScsiSessionError):
            WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    assert kernel.closed == [123]


@pytest.mark.parametrize("mask", [2, 65536, 0xFFFFFFFF])
def test_invalid_adapter_alignment_fails_closed(tmp_path: Path, mask: int) -> None:
    kernel = _Kernel()
    kernel.mask = mask
    with pytest.raises(ScsiSessionError):
        WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    assert kernel.commands == []
    assert kernel.closed == [123]


def test_adapter_transfer_bound_is_checked_before_ioctl(tmp_path: Path) -> None:
    kernel = _Kernel()
    kernel.maximum = 4096
    channel = WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    command = ScsiCommand(b"\x28" + b"\0" * 9, data_in_length=8192)
    with pytest.raises(ScsiCommandError):
        channel.execute(command)
    assert len(kernel.commands) == 4
    channel.close()


@pytest.mark.parametrize("delta", [-1, 1])
def test_wrong_transfer_count_is_rejected(tmp_path: Path, delta: int) -> None:
    kernel = _Kernel()
    channel = WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    kernel.transfer_delta = delta
    command = ScsiCommand(b"\x28" + b"\0" * 9, data_in_length=4096)
    with pytest.raises(ScsiCommandError):
        checked_response(command, channel.execute(command))
    channel.close()


def test_failed_status_retains_sense_for_diagnosis(tmp_path: Path) -> None:
    kernel = _Kernel()
    channel = WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    kernel.status = 2
    kernel.sense = b"\x70\0\x03" + b"\0" * 9 + b"\x11\0"
    command = ScsiCommand(b"\x28" + b"\0" * 9, data_in_length=4096)
    with pytest.raises(ScsiCommandError) as caught:
        checked_response(command, channel.execute(command))
    assert caught.value.response is not None
    assert caught.value.response.sense.startswith(kernel.sense)
    assert len(kernel.commands) == 5
    channel.close()


def test_native_failure_is_not_retried(tmp_path: Path) -> None:
    kernel = _Kernel()
    channel = WindowsScsiChannel.open(kernel, _observation(tmp_path), IDENTITY)
    kernel.fail_control = 0x4D014
    with pytest.raises(ScsiCommandError):
        channel.execute(ScsiCommand(b"\0" * 6))
    assert kernel.controls.count(0x4D014) == 5
    channel.close()
