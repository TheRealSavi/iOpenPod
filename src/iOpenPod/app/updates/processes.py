"""Independent child lifetimes and identity-bound waits for updater handoff."""

from __future__ import annotations

import ctypes
import os
import select
import signal
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Protocol


def child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if sys.platform == "linux":
        original = environment.pop("LD_LIBRARY_PATH_ORIG", None)
        if original:
            environment["LD_LIBRARY_PATH"] = original
        else:
            environment.pop("LD_LIBRARY_PATH", None)
    return environment


def independent_process(arguments: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        arguments,
        env=child_environment(),
        cwd=str(Path(arguments[0]).parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        start_new_session=sys.platform != "win32",
    )


class CandidateProcess(Protocol):
    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def stop(self) -> None: ...
    def release(self) -> None: ...


class _PosixCandidate:
    def __init__(self, arguments: list[str]) -> None:
        self._process = independent_process(arguments)

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._process.wait(timeout)

    def stop(self) -> None:
        if self._process.poll() is None:
            if sys.platform != "win32":
                os.killpg(self._process.pid, signal.SIGTERM)
            self._process.wait(timeout=15)

    def release(self) -> None:
        pass


def candidate_process(arguments: list[str]) -> CandidateProcess:
    if sys.platform == "win32":
        from .processes_windows import WindowsCandidateProcess

        return WindowsCandidateProcess(arguments, child_environment())
    return _PosixCandidate(arguments)


class ParentProcess:
    def __init__(self, pid: int, executable: Path) -> None:
        self._handle: Any = None
        self._pidfd: int | None = None
        self._kernel: Any = None
        if sys.platform == "win32":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self._kernel = kernel
            self._handle = kernel.OpenProcess(0x101000, False, pid)
            if not self._handle:
                raise ctypes.WinError(ctypes.get_last_error())
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if not kernel.QueryFullProcessImageNameW(
                self._handle, 0, buffer, ctypes.byref(length)
            ):
                self.close()
                raise OSError("Could not identify the application process")
            actual = Path(buffer.value)
        else:
            self._pidfd = os.pidfd_open(pid)
            actual = Path(os.readlink(f"/proc/{pid}/exe"))
        if actual != executable:
            self.close()
            raise ValueError("Update parent is not the selected executable")

    def exited(self) -> bool:
        if self._pidfd is not None:
            return bool(select.select([self._pidfd], [], [], 0)[0])
        return bool(self._kernel.WaitForSingleObject(self._handle, 0) == 0)

    def close(self) -> None:
        if self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None
        if self._pidfd is not None:
            os.close(self._pidfd)
            self._pidfd = None
