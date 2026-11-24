"""Connection-bound normal-mode SCSI access using the Linux kernel sg driver."""

from __future__ import annotations

import ctypes
import errno
import os
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from storage.errors import VolumeIdentityChangedError
from storage.platform.linux_eject import lock_linux_disk
from storage.platform.linux_usb_access import (
    check_device_number,
    open_scsi_device,
    scsi_target,
)
from storage.platform.linux_usb_authorization import authorized_open
from storage.scsi import (
    ScsiCommand,
    ScsiCommandError,
    ScsiIdentity,
    ScsiResponse,
    ScsiSessionError,
    require_scsi_identity,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class _SgIoHeader(ctypes.Structure):
    _fields_ = [
        ("interface_id", ctypes.c_int),
        ("dxfer_direction", ctypes.c_int),
        ("cmd_len", ctypes.c_ubyte),
        ("mx_sb_len", ctypes.c_ubyte),
        ("iovec_count", ctypes.c_ushort),
        ("dxfer_len", ctypes.c_uint),
        ("dxferp", ctypes.c_void_p),
        ("cmdp", ctypes.c_void_p),
        ("sbp", ctypes.c_void_p),
        ("timeout", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("pack_id", ctypes.c_int),
        ("usr_ptr", ctypes.c_void_p),
        ("status", ctypes.c_ubyte),
        ("masked_status", ctypes.c_ubyte),
        ("msg_status", ctypes.c_ubyte),
        ("sb_len_wr", ctypes.c_ubyte),
        ("host_status", ctypes.c_ushort),
        ("driver_status", ctypes.c_ushort),
        ("resid", ctypes.c_int),
        ("duration", ctypes.c_uint),
        ("info", ctypes.c_uint),
    ]


class _Ioctl(Protocol):
    def __call__(
        self,
        descriptor: int,
        operation: int,
        argument: _SgIoHeader,
        /,
    ) -> int: ...


def _sg_io(descriptor: int, header: _SgIoHeader) -> None:
    ioctl = cast("_Ioctl", vars(__import__("fcntl"))["ioctl"])
    ioctl(descriptor, 0x2285, header)


def execute_linux_scsi(descriptor: int, command: ScsiCommand) -> ScsiResponse:
    length = command.transfer_length
    data = ctypes.create_string_buffer(command.data_out, max(1, length))
    sense = ctypes.create_string_buffer(64)
    cdb = ctypes.create_string_buffer(command.cdb)
    header = _SgIoHeader()
    header.interface_id = ord("S")
    header.dxfer_direction = (
        -2 if command.data_out else -3 if command.data_in_length else -1
    )
    header.cmd_len = len(command.cdb)
    header.mx_sb_len = len(sense)
    header.dxfer_len = length
    header.dxferp = ctypes.addressof(data) if length else None
    header.cmdp = ctypes.addressof(cdb)
    header.sbp = ctypes.addressof(sense)
    header.timeout = command.timeout_seconds * 1000
    try:
        _sg_io(descriptor, header)
    except OSError as error:
        if error.errno == errno.ENODEV:
            raise ScsiCommandError(
                "Linux lost the device during the SCSI command"
            ) from error
        raise ScsiSessionError(
            f"Linux could not execute the SCSI command: {error}"
        ) from error
    transferred = length - header.resid
    response = ScsiResponse(
        data.raw[:transferred]
        if command.data_in_length and 0 <= transferred <= length
        else b"",
        transferred,
        header.status,
        sense.raw[: header.sb_len_wr],
    )
    if (
        header.host_status or header.driver_status or header.info & 1
    ) and not header.status:
        raise ScsiCommandError(
            f"Linux SCSI transport failed (host {header.host_status}, driver {header.driver_status})",
            response,
        )
    return response


class LinuxScsiChannel:
    def __init__(self, descriptor: int, handles: ExitStack) -> None:
        self._descriptor: int | None = descriptor
        self._handles = handles

    def execute(self, command: ScsiCommand) -> ScsiResponse:
        if self._descriptor is None:
            raise ScsiSessionError("The Linux SCSI channel is closed")
        return execute_linux_scsi(self._descriptor, command)

    def close(self) -> None:
        self._descriptor = None
        self._handles.close()


def open_linux_scsi(
    source: str,
    device_number: str,
    check_mount: Callable[[], None],
    expected: ScsiIdentity,
) -> LinuxScsiChannel:
    target = scsi_target(Path(source).name)
    if source != "/dev/" + target.partition or device_number != target.partition_number:
        raise VolumeIdentityChangedError(
            "The mounted partition does not match the selected Linux device"
        )

    handles = ExitStack()
    try:
        try:
            descriptor = open_scsi_device(target.partition, target.diskseq)
        except PermissionError:
            descriptor = authorized_open(target.partition, target.diskseq, scsi=True)
        handles.callback(os.close, descriptor)
        check_device_number(descriptor, target.sg_number, block=False)
        channel = LinuxScsiChannel(descriptor, handles)
        require_scsi_identity(channel, expected)

        def check_selected_mount() -> None:
            check_mount()
            if scsi_target(target.partition) != target:
                raise VolumeIdentityChangedError(
                    "The selected USB disk was reconnected"
                )

        block = lock_linux_disk(target.partition, target.disk, check_selected_mount)
        handles.callback(os.close, block)
        check_device_number(block, target.disk_number, block=True)
        if scsi_target(target.partition) != target:
            raise VolumeIdentityChangedError(
                "The disk changed while obtaining exclusive access"
            )
        require_scsi_identity(channel, expected)
        return channel
    except BaseException:
        handles.close()
        raise
