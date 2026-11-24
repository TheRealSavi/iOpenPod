# pyright: strict, reportPrivateUsage=false
"""Exercise native update-session ownership and command completion without hardware."""

import ctypes
import errno
import os
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from storage.errors import DeviceBusyError, VolumeIdentityChangedError
from storage.platform import linux_scsi, linux_usb_access, macos_vpd
from storage.platform.linux import LinuxPlatformAdapter
from storage.platform.linux_usb_access import LinuxScsiTarget
from storage.platform.macos import MacOSPlatformAdapter
from storage.platform.macos_iokit import MacFrameworks
from storage.portal import Storage
from storage.scsi import (
    ScsiCommand,
    ScsiCommandError,
    ScsiIdentity,
    ScsiSessionError,
    checked_response,
)

IDENTITY = ScsiIdentity("Apple", "iPod", "selected-unit")


@pytest.mark.parametrize("adapter", [LinuxPlatformAdapter, MacOSPlatformAdapter])
def test_standalone_native_adapters_offer_update_sessions(
    adapter: type[LinuxPlatformAdapter] | type[MacOSPlatformAdapter],
) -> None:
    assert Storage(adapter()).supports_scsi_sessions


@pytest.mark.parametrize("residual", [-1, 0, 1, 5])
def test_linux_uses_completed_byte_count_for_writes(
    monkeypatch: pytest.MonkeyPatch, residual: int
) -> None:
    command = ScsiCommand(bytes(10), data_out=b"test", timeout_seconds=30)

    def submit(fd: int, header: linux_scsi._SgIoHeader) -> None:
        assert fd == 8 and header.dxfer_direction == -2
        assert header.timeout == 30_000 and header.interface_id == ord("S")
        assert ctypes.string_at(header.cmdp, header.cmd_len) == command.cdb
        assert ctypes.string_at(header.dxferp, header.dxfer_len) == command.data_out
        header.resid = residual

    monkeypatch.setattr(linux_scsi, "_sg_io", submit)
    response = linux_scsi.execute_linux_scsi(8, command)
    if residual:
        with pytest.raises(ScsiCommandError):
            checked_response(command, response)
    else:
        assert checked_response(command, response).transferred == 4


def test_linux_exposes_short_read_and_explicit_check_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def submit(_fd: int, header: linux_scsi._SgIoHeader) -> None:
        assert header.dxfer_direction == -3
        ctypes.memmove(header.dxferp, b"ab", 2)
        ctypes.memmove(header.sbp, b"sense", 5)
        header.sb_len_wr = 5
        header.resid = 2
        header.status = 2
        header.driver_status = 8

    monkeypatch.setattr(linux_scsi, "_sg_io", submit)
    command = ScsiCommand(bytes(6), data_in_length=4, allow_short_read=True)
    response = linux_scsi.execute_linux_scsi(7, command)
    assert response.data == b"ab" and response.sense == b"sense"
    with pytest.raises(ScsiCommandError) as failure:
        checked_response(command, response)
    assert failure.value.response == response


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EINTR, errno.ENODEV])
def test_linux_no_data_command_is_submitted_once(
    monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    calls: list[int] = []

    def submit(_fd: int, header: linux_scsi._SgIoHeader) -> None:
        calls.append(header.dxfer_direction)
        assert header.dxfer_len == 0 and not header.dxferp
        raise OSError(error_number, "test transport")

    monkeypatch.setattr(linux_scsi, "_sg_io", submit)
    with pytest.raises(ScsiSessionError) as failure:
        linux_scsi.execute_linux_scsi(7, ScsiCommand(bytes(6)))
    assert isinstance(failure.value, ScsiCommandError) == (error_number == errno.ENODEV)
    assert calls == [-1]


@pytest.mark.parametrize("event", ["success", "busy", "reconnect", "wrong-serial"])
def test_linux_owns_sg_and_whole_disk_for_one_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, event: str
) -> None:
    target = LinuxScsiTarget("sdb1", "8:17", "sdb", "8:16", "sg3", "21:3", "333")
    current = target
    handles: list[int] = []
    checks: list[bool] = []
    locked = False
    with (tmp_path / "handle").open("wb") as host_file:

        def new_fd(*_args: str) -> int:
            handles.append(os.dup(host_file.fileno()))
            return handles[-1]

        def lock(partition: str, disk: str, check_mount: Callable[[], None]) -> int:
            nonlocal current, locked
            assert (partition, disk) == ("sdb1", "sdb")
            check_mount()
            if event == "busy":
                raise DeviceBusyError("busy")
            locked = True
            if event == "reconnect":
                current = replace(target, diskseq="334")
            return new_fd()

        def identity(_channel: object, expected: ScsiIdentity) -> None:
            assert expected == IDENTITY
            checks.append(locked)
            if event == "wrong-serial":
                raise VolumeIdentityChangedError("serial mismatch")

        def resolve(partition: str) -> LinuxScsiTarget:
            assert partition == target.partition
            return current

        def check_fd(descriptor: int, number: str, *, block: bool) -> None:
            assert descriptor in handles
            assert number == (target.disk_number if block else target.sg_number)

        monkeypatch.setattr(linux_scsi, "scsi_target", resolve)
        monkeypatch.setattr(linux_scsi, "open_scsi_device", new_fd)
        monkeypatch.setattr(linux_scsi, "check_device_number", check_fd)
        monkeypatch.setattr(linux_scsi, "require_scsi_identity", identity)
        monkeypatch.setattr(linux_scsi, "lock_linux_disk", lock)
        if event == "success":
            channel = linux_scsi.open_linux_scsi(
                "/dev/sdb1", "8:17", lambda: None, IDENTITY
            )
            assert checks == [False, True] and len(handles) == 2
            for fd in handles:
                os.fstat(fd)
            channel.close()
            channel.close()
        else:
            with pytest.raises((VolumeIdentityChangedError, DeviceBusyError)):
                linux_scsi.open_linux_scsi("/dev/sdb1", "8:17", lambda: None, IDENTITY)
            assert checks == [False]
            assert len(handles) == (2 if event == "reconnect" else 1)
        for fd in handles:
            with pytest.raises(OSError):
                os.fstat(fd)


@pytest.mark.parametrize("event", ["success", "ambiguous", "busy", "wrong-serial"])
def test_mac_binds_interface_before_unmount_and_verifies_under_lock(
    monkeypatch: pytest.MonkeyPatch, event: str
) -> None:
    calls: list[str] = []
    matches = [(42, "usb")] * (2 if event == "ambiguous" else 1)

    def matching(
        _frameworks: object, product: int, serial: str, partition: str
    ) -> nullcontext[list[tuple[int, str]]]:
        assert (product, serial, partition) == (1, "usb", "disk4s1")
        return nullcontext(matches)

    monkeypatch.setattr(macos_vpd, "_MacFrameworks", object)
    monkeypatch.setattr(macos_vpd, "_matching_services", matching)

    class Session:
        def __init__(self, _frameworks: object, service: int) -> None:
            assert service == 42

        def connect(self) -> bool:
            calls.append("connect")
            return True

        def obtain_exclusive(self) -> bool:
            calls.append("lock")
            return event != "busy"

        def close(self) -> None:
            calls.append("close")

    def verify(_session: object, expected: ScsiIdentity) -> None:
        calls.append("verify")
        assert expected == IDENTITY
        if event == "wrong-serial":
            raise VolumeIdentityChangedError("serial mismatch")

    monkeypatch.setattr(macos_vpd, "_ScsiSession", Session)
    monkeypatch.setattr(macos_vpd, "require_scsi_identity", verify)

    def open_channel() -> macos_vpd._ScsiSession:
        return macos_vpd.open_macos_scsi(
            product=1,
            serial="usb",
            bsd_partition="disk4s1",
            expected=IDENTITY,
            unmount=lambda: calls.append("unmount"),
        )

    if event == "success":
        channel = open_channel()
        assert calls == ["connect", "unmount", "lock", "verify"]
        channel.close()
    else:
        with pytest.raises((DeviceBusyError, VolumeIdentityChangedError)):
            open_channel()
        if event == "ambiguous":
            assert calls == []
        elif event == "busy":
            assert calls == ["connect", "unmount", "lock", "close"]
        else:
            assert calls == ["connect", "unmount", "lock", "verify", "close"]


@pytest.mark.parametrize("direction", ["read", "write", "none"])
def test_mac_scsi_passes_native_transfer_direction_and_count(
    monkeypatch: pytest.MonkeyPatch, direction: str
) -> None:
    command = ScsiCommand(
        bytes(10),
        data_out=b"test" if direction == "write" else b"",
        data_in_length=4 if direction == "read" else 0,
    )
    calls: list[int] = []

    def native(
        _task: object, slot: int, _result: object, _types: object, *args: Any
    ) -> int:
        calls.append(slot)
        if slot == 8:
            assert bytes(args[0])[: args[1].value] == command.cdb
        if slot == 11:
            address = ctypes.cast(
                args[0], ctypes.POINTER(macos_vpd._IoVirtualRange)
            ).contents.address
            assert args[3].value == (1 if direction == "write" else 2)
            if direction == "read":
                ctypes.memmove(address, b"test", 4)
            else:
                assert ctypes.string_at(address, 4) == b"test"
        if slot == 16:
            ctypes.cast(args[2], ctypes.POINTER(ctypes.c_uint64))[0] = (
                command.transfer_length
            )
        return 0

    monkeypatch.setattr(macos_vpd, "_vtable_call", native)
    session = macos_vpd._ScsiSession(MacFrameworks.__new__(MacFrameworks), 42)
    session._task = ctypes.c_void_p(1)
    response = checked_response(command, session.execute(command))
    assert response.data == (b"test" if direction == "read" else b"")
    assert calls == ([24, 8, 11, 12, 16] if direction != "none" else [24, 8, 12, 16])


@pytest.mark.parametrize("slot,result", [(12, 1), (16, 1), (16, 0xE00002C0)])
def test_mac_distinguishes_prepare_failure_from_missing_device_reply(
    monkeypatch: pytest.MonkeyPatch, slot: int, result: int
) -> None:
    calls: list[int] = []

    def native(_task: object, method: int, *_args: object) -> int:
        calls.append(method)
        return result if slot == method else 0

    monkeypatch.setattr(macos_vpd, "_vtable_call", native)
    frameworks = MacFrameworks.__new__(MacFrameworks)
    session = macos_vpd._ScsiSession(frameworks, 42)
    session._task = ctypes.c_void_p(1)
    with pytest.raises(ScsiSessionError) as failure:
        session.execute(ScsiCommand(bytes(6)))
    assert calls[-1] == slot and calls.count(16) == int(slot == 16)
    if slot == 16:
        assert isinstance(failure.value, ScsiCommandError)
        assert (failure.value.response is None) == (result == 0xE00002C0)
    else:
        assert not isinstance(failure.value, ScsiCommandError)


@pytest.mark.parametrize(
    "partition", ["/dev/sda1", "../sda1", "sda", "sg0", "nvme0n1p1"]
)
def test_authorization_only_accepts_scsi_partition_names(partition: str) -> None:
    with pytest.raises(OSError, match="partition"):
        linux_usb_access.open_scsi_device(partition, "42")


def test_authorization_rejects_reused_disk_name_before_opening_a_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def replacement(partition: str) -> LinuxScsiTarget:
        return LinuxScsiTarget(partition, "8:17", "sdb", "8:16", "sg1", "21:1", "43")

    monkeypatch.setattr(linux_usb_access, "scsi_target", replacement)
    with pytest.raises(OSError, match="connection changed"):
        linux_usb_access.open_scsi_device("sdb1", "42")
