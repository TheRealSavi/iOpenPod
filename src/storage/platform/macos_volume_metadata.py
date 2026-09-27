"""Descriptor-bound Darwin Volume attributes; never rename a Host directory."""

from __future__ import annotations

import ctypes
import os
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_ATTR_VOL_NAME = 0x00002000
_ATTR_VOL_INFO = 0x80000000
_ATTR_CMN_FNDRINFO = 0x00004000


class _AttrList(ctypes.Structure):
    _fields_ = (
        ("bitmapcount", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16),
        ("commonattr", ctypes.c_uint32),
        ("volattr", ctypes.c_uint32),
        ("dirattr", ctypes.c_uint32),
        ("fileattr", ctypes.c_uint32),
        ("forkattr", ctypes.c_uint32),
    )


class _VolumeAttributes:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        for name in ("fgetattrlist", "fsetattrlist"):
            function = getattr(self._libc, name)
            function.argtypes = [
                ctypes.c_int,
                ctypes.POINTER(_AttrList),
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_ulong,
            ]
            function.restype = ctypes.c_int

    def read(self, fd: int, attributes: _AttrList) -> bytes:
        buffer = ctypes.create_string_buffer(4096)
        if self._libc.fgetattrlist(
            fd, ctypes.byref(attributes), buffer, len(buffer), 0
        ):
            raise OSError(ctypes.get_errno(), "Could not read Volume attributes")
        length = struct.unpack_from("=I", buffer.raw)[0]
        if not 4 <= length <= len(buffer):
            raise OSError("Invalid Volume attribute response")
        return buffer.raw[4:length]

    def write(self, fd: int, attributes: _AttrList, data: bytes) -> None:
        buffer = ctypes.create_string_buffer(data)
        if self._libc.fsetattrlist(fd, ctypes.byref(attributes), buffer, len(data), 0):
            raise OSError(ctypes.get_errno(), "Could not update Volume attributes")

    def set_label(self, label: str) -> str:
        attributes = _AttrList(5, 0, 0, _ATTR_VOL_INFO | _ATTR_VOL_NAME, 0, 0, 0)
        fd = os.open(
            self._root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0x100000)
            | getattr(os, "O_NOFOLLOW", 0x100),
        )
        try:
            if _decode_label(self.read(fd, attributes)) == label:
                return label
            encoded = label.encode("utf-8") + b"\0"
            self.write(fd, attributes, struct.pack("=iI", 8, len(encoded)) + encoded)
            return _decode_label(self.read(fd, attributes))
        finally:
            os.close(fd)

    def enable_icon(self) -> None:
        attributes = _AttrList(5, 0, _ATTR_CMN_FNDRINFO, 0, 0, 0, 0)
        fd = os.open(
            self._root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0x100000)
            | getattr(os, "O_NOFOLLOW", 0x100),
        )
        try:
            original = self.read(fd, attributes)
            if len(original) != 32:
                raise OSError("Invalid Finder information length")
            data = bytearray(original)
            # Finder's kHasCustomIcon is a big-endian UInt16 at byte eight.
            data[8] |= 0x04
            updated = bytes(data)
            if updated != original:
                self.write(fd, attributes, updated)
                if self.read(fd, attributes) != updated:
                    raise OSError("The custom Volume icon flag did not verify")
        finally:
            os.close(fd)


def set_label(root: Path, label: str) -> str:
    return _VolumeAttributes(root).set_label(label)


def _decode_label(data: bytes) -> str:
    if len(data) < 8:
        raise OSError("Invalid Volume label response")
    offset, length = struct.unpack_from("=iI", data)
    if offset < 8 or length < 1 or offset + length > len(data):
        raise OSError("Invalid Volume label response")
    return data[offset : offset + length].rstrip(b"\0").decode("utf-8")


def enable_icon(root: Path) -> None:
    _VolumeAttributes(root).enable_icon()
