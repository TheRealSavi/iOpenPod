"""Windows handle-bound file renames for Host executable installation."""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import sys
import uuid
from contextlib import contextmanager
from ctypes import wintypes
from typing import TYPE_CHECKING, Any

from storage._filesystem import is_link_or_reparse
from storage.host_directory import pin_host_directory
from storage.host_installation import HostFileIdentity, require_plain_path

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


def installation_kernel() -> Any:
    """Return the shared Kernel32 bindings for installation files and use leases."""
    if sys.platform != "win32":
        raise OSError("Windows installation operations require Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    return kernel


def require_fixed_ntfs(path: Path) -> None:
    kernel = installation_kernel()
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel.GetDriveTypeW.restype = wintypes.UINT
    if kernel.GetDriveTypeW(path.anchor) != 3:
        raise ValueError("Automatic installation requires a fixed local drive")
    kernel.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel.GetVolumeInformationW.restype = wintypes.BOOL
    filesystem = ctypes.create_unicode_buffer(32)
    if not kernel.GetVolumeInformationW(
        path.anchor, None, 0, None, None, None, filesystem, 32
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if filesystem.value != "NTFS":
        raise ValueError("Automatic installation currently requires NTFS")


def create_private_directory(parent: Path, prefix: str) -> Path:
    """Create with an owner-only DACL atomically, before any data can be written."""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = installation_kernel()
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    ]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    kernel.CreateDirectoryW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_void_p,
    ]
    kernel.CreateDirectoryW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    # OW is OWNER RIGHTS; inherited children grant access only to their owner.
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        "D:P(A;OICI;FA;;;OW)", 1, ctypes.byref(descriptor), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [
                ("length", wintypes.DWORD),
                ("descriptor", ctypes.c_void_p),
                ("inherit", wintypes.BOOL),
            ]

        attributes = SecurityAttributes(
            ctypes.sizeof(SecurityAttributes), descriptor, False
        )
        for _attempt in range(10):
            directory = parent / (prefix + uuid.uuid4().hex)
            if kernel.CreateDirectoryW(os.fspath(directory), ctypes.byref(attributes)):
                return directory
            code = ctypes.get_last_error()
            if code != 183:
                raise ctypes.WinError(code)
        raise FileExistsError("Could not allocate a new private update directory")
    finally:
        kernel.LocalFree(descriptor)


@contextmanager
def _owned_handle(path: Path, expected: HostFileIdentity) -> Generator[int]:
    import msvcrt

    kernel = installation_kernel()
    require_plain_path(path)
    with pin_host_directory(path.parent):
        handle = kernel.CreateFileW(
            os.fspath(path), 0x80010000, 0, None, 3, 0x00200000, None
        )
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                is_link_or_reparse(info)
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
            ):
                raise ValueError("Installation file is linked or not regular")
            identity = HostFileIdentity(
                info.st_dev,
                info.st_ino,
                info.st_size,
                hashlib.file_digest(stream, "sha256").hexdigest(),
            )
            if identity != expected:
                raise ValueError(
                    "Installation file no longer matches the approved identity"
                )
            yield int(handle)


def rename_file(source: Path, destination: Path, expected: HostFileIdentity) -> None:
    require_plain_path(destination)
    require_fixed_ntfs(source)
    kernel = installation_kernel()
    with (
        pin_host_directory(destination.parent),
        _owned_handle(source, expected) as handle,
    ):
        # The native rename acts on the verified open file and refuses any existing
        # destination, including files appearing after validation.
        encoded = os.fspath(destination).encode("utf-16-le")

        class RenameInfo(ctypes.Structure):
            _fields_ = [
                ("flags", wintypes.DWORD),
                ("root", wintypes.HANDLE),
                ("length", wintypes.DWORD),
                ("name", ctypes.c_byte * (len(encoded) + 2)),
            ]

        request = RenameInfo()
        request.length = len(encoded)
        ctypes.memmove(
            ctypes.addressof(request) + RenameInfo.name.offset, encoded, len(encoded)
        )
        if not kernel.SetFileInformationByHandle(
            handle, 3, ctypes.byref(request), ctypes.sizeof(request)
        ):
            raise ctypes.WinError(ctypes.get_last_error())


def remove_file(path: Path, expected: HostFileIdentity) -> None:
    kernel = installation_kernel()
    with _owned_handle(path, expected) as handle:
        delete = wintypes.BOOL(True)
        if not kernel.SetFileInformationByHandle(
            handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
