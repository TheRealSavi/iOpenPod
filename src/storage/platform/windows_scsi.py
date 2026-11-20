"""Windows SCSI pass-through on one retained, exclusively locked volume handle."""

from __future__ import annotations

import ctypes
import mmap
import re
import struct
from typing import TYPE_CHECKING, Any

from storage.errors import DeviceBusyError, VolumeIdentityChangedError
from storage.scsi import (
    ScsiCommand,
    ScsiCommandError,
    ScsiIdentity,
    ScsiResponse,
    ScsiSessionError,
    checked_response,
)

if TYPE_CHECKING:
    from storage.models import VolumeObservation

_VOLUME_ID = re.compile(
    r"windows:(\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\):[0-9A-Fa-f]{8}"
)
_DISK_ID = re.compile(r"windows:disk-(\d+)")
_SCSI_PASS_THROUGH_DIRECT = 0x4D014
_STORAGE_GET_DEVICE_NUMBER = 0x2D1080
_STORAGE_QUERY_PROPERTY = 0x2D1400
_LOCK_VOLUME = 0x90018
_SENSE_BYTES = 64


class _PassThrough(ctypes.Structure):
    # Fixed Windows ABI widths, including when tests run on another Host OS.
    _fields_ = [
        ("length", ctypes.c_uint16),
        ("status", ctypes.c_uint8),
        ("path_id", ctypes.c_uint8),
        ("target_id", ctypes.c_uint8),
        ("lun", ctypes.c_uint8),
        ("cdb_length", ctypes.c_uint8),
        ("sense_length", ctypes.c_uint8),
        ("data_in", ctypes.c_uint8),
        ("transfer_length", ctypes.c_uint32),
        ("timeout", ctypes.c_uint32),
        ("data_buffer", ctypes.c_void_p),
        ("sense_offset", ctypes.c_uint32),
        ("cdb", ctypes.c_uint8 * 16),
    ]


class _Packet(ctypes.Structure):
    _fields_ = [("request", _PassThrough), ("sense", ctypes.c_uint8 * _SENSE_BYTES)]


class WindowsScsiChannel:
    """Native channel; use Storage.open_scsi_session instead of constructing it."""

    def __init__(self, kernel32: Any, handle: int) -> None:
        self._kernel32 = kernel32
        self._handle: int | None = handle
        self._alignment = mmap.PAGESIZE
        self._max_transfer = 0

    @classmethod
    def open(
        cls,
        kernel32: Any,
        observation: VolumeObservation,
        expected_identity: ScsiIdentity,
    ) -> WindowsScsiChannel:
        volume = _VOLUME_ID.fullmatch(observation.volume.id.value)
        disk = _DISK_ID.fullmatch(observation.physical_device.id.value)
        if volume is None or disk is None:
            raise ScsiSessionError(
                "SCSI access requires a retained Windows Volume GUID"
            )
        handle = kernel32.CreateFileW(
            volume.group(1).rstrip("\\"),
            0xC0000000,  # GENERIC_READ | GENERIC_WRITE, required by SPTD.
            3,  # FILE_SHARE_READ | FILE_SHARE_WRITE, required by volume locking.
            None,
            3,  # OPEN_EXISTING
            0,
            None,
        )
        if handle in (None, 0, ctypes.c_void_p(-1).value):
            raise _native_error("Opening the selected Volume for SCSI access failed")
        channel = cls(kernel32, int(handle))
        try:
            channel._verify_disk(int(disk.group(1)))
            channel._query_adapter()
            channel._verify_identity(expected_identity)
            try:
                channel._ioctl(_LOCK_VOLUME, None, 0, None, 0)
            except ScsiCommandError as error:
                raise DeviceBusyError(
                    "Windows could not lock the Volume; close applications using it"
                ) from error
            # No forced dismount and no fallback to a drive letter or disk number.
            channel._verify_disk(int(disk.group(1)))
            channel._verify_identity(expected_identity)
            return channel
        except BaseException as error:
            try:
                channel.close()
            except Exception as cleanup_error:
                error.add_note(f"Closing the SCSI handle also failed: {cleanup_error}")
            raise

    def _ioctl(
        self,
        control: int,
        input_buffer: object,
        input_length: int,
        output_buffer: object,
        output_length: int,
    ) -> int:
        if self._handle is None:
            raise ScsiSessionError("The native SCSI handle is closed")
        returned = ctypes.c_uint32()
        succeeded = self._kernel32.DeviceIoControl(
            self._handle,
            control,
            input_buffer,
            input_length,
            output_buffer,
            output_length,
            ctypes.byref(returned),
            None,
        )
        if not succeeded:
            raise _native_error(f"DeviceIoControl 0x{control:x} failed")
        return returned.value

    def _verify_disk(self, expected_number: int) -> None:
        result = ctypes.create_string_buffer(12)
        size = self._ioctl(_STORAGE_GET_DEVICE_NUMBER, None, 0, result, 12)
        if size != 12:
            raise ScsiSessionError("Windows returned an incomplete device identity")
        device_type, number, _partition = struct.unpack("<III", result.raw)
        if device_type != 7 or number != expected_number:
            raise VolumeIdentityChangedError(
                "The retained Volume belongs to another disk"
            )

    def _query_adapter(self) -> None:
        query = ctypes.create_string_buffer(struct.pack("<III", 1, 0, 0))
        result = ctypes.create_string_buffer(128)
        received = self._ioctl(_STORAGE_QUERY_PROPERTY, query, 12, result, 128)
        if received < 20:
            raise ScsiSessionError("Windows returned an incomplete adapter descriptor")
        version, size, maximum, pages, mask = struct.unpack_from("<IIIII", result.raw)
        if version < 20 or size < 20 or not maximum or not pages:
            raise ScsiSessionError("Windows returned invalid adapter transfer limits")
        if mask > 65535 or mask & (mask + 1):
            raise ScsiSessionError("Windows returned an unsupported alignment mask")
        self._alignment = max(mask + 1, mmap.PAGESIZE)
        self._max_transfer = min(maximum, pages * mmap.PAGESIZE)

    def _verify_identity(self, expected: ScsiIdentity) -> None:
        inquiry = ScsiCommand(bytes((0x12, 0, 0, 0, 36, 0)), data_in_length=36)
        header = checked_response(inquiry, self.execute(inquiry)).data
        serial_command = ScsiCommand(
            bytes((0x12, 1, 0x80, 0, 255, 0)),
            data_in_length=255,
            allow_short_read=True,
        )
        page = checked_response(serial_command, self.execute(serial_command)).data
        if header[0] != 0 or len(page) < 5 or page[:2] != b"\x00\x80":
            raise ScsiSessionError(
                "The device did not return direct-access SCSI identity"
            )
        # Some devices advertise 32 serial bytes but return only their actual
        # serial. Bound by both the declared length and the completed transfer.
        declared = int.from_bytes(page[2:4], "big")
        try:
            identity = ScsiIdentity(
                header[8:16].decode("ascii").rstrip(" \0"),
                header[16:32].decode("ascii").rstrip(" \0"),
                page[4 : 4 + declared].decode("ascii").rstrip(" \0"),
            )
        except ValueError as error:
            raise ScsiSessionError(
                "The device returned malformed SCSI identity"
            ) from error
        if identity != expected:
            raise VolumeIdentityChangedError(
                "The connected SCSI device identity changed"
            )

    def execute(self, command: ScsiCommand) -> ScsiResponse:
        size = command.transfer_length
        if size > self._max_transfer:
            raise ScsiCommandError("SCSI command exceeds the native adapter limits")
        # Retain the owner for the entire synchronous call; align to the adapter
        # mask and page size so MaximumPhysicalPages is also respected.
        owner = ctypes.create_string_buffer(max(1, size) + self._alignment - 1)
        address = (ctypes.addressof(owner) + self._alignment - 1) & -self._alignment
        if command.data_out:
            ctypes.memmove(address, command.data_out, size)
        packet = _Packet()
        request = packet.request
        request.length = ctypes.sizeof(_PassThrough)
        request.cdb_length = len(command.cdb)
        request.cdb[: len(command.cdb)] = command.cdb
        request.sense_length = _SENSE_BYTES
        request.sense_offset = _Packet.sense.offset
        request.data_in = 0 if command.data_out else 1 if command.data_in_length else 2
        request.transfer_length = size
        request.timeout = command.timeout_seconds
        request.data_buffer = address if size else None
        returned = self._ioctl(
            _SCSI_PASS_THROUGH_DIRECT,
            ctypes.byref(packet),
            ctypes.sizeof(packet),
            ctypes.byref(packet),
            ctypes.sizeof(packet),
        )
        if returned < ctypes.sizeof(_PassThrough):
            raise ScsiCommandError(
                "Windows returned an incomplete SCSI response header"
            )
        if request.transfer_length > size or request.sense_length > _SENSE_BYTES:
            raise ScsiCommandError("Windows returned an invalid SCSI response length")
        sense = bytes(packet.sense[: request.sense_length])
        return ScsiResponse(
            data=(
                ctypes.string_at(address, request.transfer_length)
                if command.data_in_length
                else b""
            ),
            transferred=request.transfer_length,
            status=request.status,
            sense=sense if any(sense) else b"",
        )

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None and not self._kernel32.CloseHandle(handle):
            raise _native_error("Closing the SCSI Volume handle failed")


def _native_error(message: str) -> ScsiCommandError:
    get_last_error: Any = getattr(ctypes, "get_last_error", lambda: 0)
    return ScsiCommandError(f"{message} (Windows error {get_last_error()})")
