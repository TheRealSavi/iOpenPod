"""Cross-process shared use / exclusive maintenance of a Host installation."""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import sys
from ctypes import wintypes
from typing import TYPE_CHECKING, Any

from storage.host_files import application_cache_file
from storage.host_installation import require_plain_path

if TYPE_CHECKING:
    from pathlib import Path


class HostInstallationLease:
    """A nonblocking OS lock. Every participating launch holds a shared lease.

    Lock files are stable rendezvous points and are never unlinked. An exclusive
    lease fails while any application instance is using the installation.
    """

    def __init__(self, installation: Path, *, exclusive: bool = False) -> None:
        name = hashlib.sha256(os.path.normcase(str(installation)).encode()).hexdigest()
        platform_name = {"win32": "windows", "darwin": "macos", "linux": "linux"}[
            sys.platform
        ]
        path = application_cache_file(
            "iOpenPod", f"installation-{name}.lock", platform_name=platform_name
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        require_plain_path(path)
        self._handle: Any = None
        self._descriptor: int | None = None
        self._overlapped: Any = None
        if sys.platform == "win32":
            from storage.platform.host_install_windows import installation_kernel

            kernel = installation_kernel()
            handle = kernel.CreateFileW(
                str(path), 0xC0000000, 3, None, 4, 0x00200000, None
            )
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            self._handle = handle

            class Overlapped(ctypes.Structure):
                _fields_ = [
                    ("internal", ctypes.c_size_t),
                    ("internal_high", ctypes.c_size_t),
                    ("offset", wintypes.DWORD),
                    ("offset_high", wintypes.DWORD),
                    ("event", wintypes.HANDLE),
                ]

            self._overlapped = Overlapped()
            kernel.LockFileEx.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
            ]
            kernel.LockFileEx.restype = wintypes.BOOL
            if not kernel.LockFileEx(
                handle,
                1 | (2 if exclusive else 0),
                0,
                1,
                0,
                ctypes.byref(self._overlapped),
            ):
                code = ctypes.get_last_error()
                self.close()
                raise OSError(
                    code,
                    "Another iOpenPod instance is using or updating this installation",
                )
        else:
            import fcntl

            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            self._descriptor = descriptor
            info = os.fstat(descriptor)
            try:
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid != os.getuid()
                ):
                    raise ValueError("Unsafe installation lock file")
                fcntl.flock(
                    descriptor,
                    (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB,
                )
            except BaseException:
                self.close()
                raise

    def close(self) -> None:
        if self._handle is not None:
            from storage.platform.host_install_windows import installation_kernel

            installation_kernel().CloseHandle(self._handle)
            self._handle = None
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None

    def __enter__(self) -> HostInstallationLease:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
