"""Win32 bindings for a bounded, mutually identified Storage handle handoff."""

from __future__ import annotations

import ctypes
import os
import subprocess
from contextlib import contextmanager
from ctypes import wintypes as w
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

INVALID = ctypes.c_void_p(-1).value


def last_error() -> int:
    return cast("int", getattr(ctypes, "get_last_error", lambda: 0)())


class _Security(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", w.BOOL)]


class _Overlapped(ctypes.Structure):
    _fields_ = [
        ("internal", ctypes.c_size_t),
        ("internal_high", ctypes.c_size_t),
        ("offset", w.DWORD),
        ("offset_high", w.DWORD),
        ("event", w.HANDLE),
    ]


class _ShellExecute(ctypes.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("mask", w.ULONG),
        ("window", w.HWND),
        ("verb", w.LPCWSTR),
        ("file", w.LPCWSTR),
        ("parameters", w.LPCWSTR),
        ("directory", w.LPCWSTR),
        ("show", ctypes.c_int),
        ("instance", w.HINSTANCE),
        ("id_list", ctypes.c_void_p),
        ("class_name", w.LPCWSTR),
        ("class_key", w.HKEY),
        ("hot_key", w.DWORD),
        ("icon", w.HANDLE),
        ("process", w.HANDLE),
    ]


class WindowsAccessNative:
    def __init__(self) -> None:
        loader = cast("type[ctypes.CDLL]", vars(ctypes)["WinDLL"])
        self.kernel = loader("kernel32", use_last_error=True)
        self.security = loader("advapi32", use_last_error=True)
        self.shell = loader("shell32", use_last_error=True)
        self.com = loader("ole32", use_last_error=True)
        self.com.CoInitializeEx.argtypes = [ctypes.c_void_p, w.DWORD]
        self.com.CoInitializeEx.restype = ctypes.c_int32
        self.com.CoUninitialize.argtypes = []
        self.com.CoUninitialize.restype = None
        pointer = ctypes.c_void_p
        bindings: dict[str, tuple[object, list[object]]] = {
            "CloseHandle": (w.BOOL, [w.HANDLE]),
            "CreateFileW": (
                w.HANDLE,
                [w.LPCWSTR, w.DWORD, w.DWORD, pointer, w.DWORD, w.DWORD, w.HANDLE],
            ),
            "CreateDirectoryW": (w.BOOL, [w.LPCWSTR, pointer]),
            "CreateNamedPipeW": (
                w.HANDLE,
                [
                    w.LPCWSTR,
                    w.DWORD,
                    w.DWORD,
                    w.DWORD,
                    w.DWORD,
                    w.DWORD,
                    w.DWORD,
                    pointer,
                ],
            ),
            "CreateEventW": (w.HANDLE, [pointer, w.BOOL, w.BOOL, w.LPCWSTR]),
            "ConnectNamedPipe": (w.BOOL, [w.HANDLE, pointer]),
            "ReadFile": (w.BOOL, [w.HANDLE, pointer, w.DWORD, pointer, pointer]),
            "WriteFile": (w.BOOL, [w.HANDLE, pointer, w.DWORD, pointer, pointer]),
            "CancelIoEx": (w.BOOL, [w.HANDLE, pointer]),
            "GetOverlappedResult": (w.BOOL, [w.HANDLE, pointer, pointer, w.BOOL]),
            "WaitForSingleObject": (w.DWORD, [w.HANDLE, w.DWORD]),
            "GetProcessId": (w.DWORD, [w.HANDLE]),
            "OpenProcess": (w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),
            "GetCurrentProcess": (w.HANDLE, []),
            "GetProcessTimes": (w.BOOL, [w.HANDLE, pointer, pointer, pointer, pointer]),
            "GetNamedPipeClientProcessId": (w.BOOL, [w.HANDLE, pointer]),
            "GetExitCodeProcess": (w.BOOL, [w.HANDLE, pointer]),
            "LocalFree": (pointer, [pointer]),
        }
        for name, (result, arguments) in bindings.items():
            function = getattr(self.kernel, name)
            function.restype = result
            function.argtypes = arguments
        self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            w.LPCWSTR,
            w.DWORD,
            pointer,
            pointer,
        ]
        self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
            w.BOOL
        )
        self.shell.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecute)]
        self.shell.ShellExecuteExW.restype = w.BOOL

    def error(self, operation: str) -> OSError:
        return OSError(last_error(), f"{operation} (Windows error {last_error()})")

    def close(self, handle: int) -> None:
        self.kernel.CloseHandle(handle)

    @contextmanager
    def security_attributes(self, sddl: str) -> Generator[_Security]:
        descriptor = ctypes.c_void_p()
        if not self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise self.error("Preparing private Storage access")
        try:
            yield _Security(ctypes.sizeof(_Security), descriptor, False)
        finally:
            self.kernel.LocalFree(descriptor)

    def create_directory(self, path: Path) -> None:
        # Allow credential-elevated administrators to read/execute this one file.
        # PyInstaller's extraction directory itself need not permit that access.
        with self.security_attributes(
            "D:P(A;OICI;FA;;;OW)(A;OICI;GRGX;;;BA)(A;OICI;GRGX;;;SY)"
        ) as attributes:
            if not self.kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
                raise self.error("Preparing the Storage helper directory")

    @contextmanager
    def pin(self, path: Path, *, directory: bool = False) -> Generator[None]:
        handle = self.kernel.CreateFileW(
            str(path),
            0x80000000,
            1 if not directory else 3,
            None,
            3,
            0x02000000 if directory else 0,
            None,
        )
        if handle in (None, 0, INVALID):
            raise self.error("Retaining the Storage helper")
        try:
            yield
        finally:
            self.close(handle)

    @contextmanager
    def pipe(self, name: str, *, diagnostic: bool = False) -> Generator[int]:
        # Administrators/System only; no default Everyone/Anonymous access.
        acl = "D:P(A;;GA;;;BA)(A;;GA;;;SY)" + ("(A;;GA;;;OW)" if diagnostic else "")
        with self.security_attributes(acl) as attributes:
            handle = self.kernel.CreateNamedPipeW(
                name,
                3 | 0x40000000 | 0x00080000,
                4 | 2 | 8,
                1,
                4096,
                4096,
                0,
                ctypes.byref(attributes),
            )
        if handle in (None, 0, INVALID):
            raise self.error("Creating the Storage authorization pipe")
        try:
            yield int(handle)
        finally:
            self.close(handle)

    @contextmanager
    def connection(self, pipe: int) -> Generator[_Overlapped | None]:
        with self.operation() as operation:
            result = self.kernel.ConnectNamedPipe(pipe, ctypes.byref(operation))
            error = 0 if result else last_error()
            if error not in (0, 535, 997):  # connected / pending
                raise self.error("Connecting the Storage helper")
            pending = error == 997
            try:
                yield operation if pending else None
            finally:
                if pending:
                    self.cancel(pipe, operation)

    @contextmanager
    def operation(self) -> Generator[_Overlapped]:
        event = self.kernel.CreateEventW(None, True, False, None)
        if not event:
            raise self.error("Creating the Storage authorization event")
        try:
            yield _Overlapped(event=event)
        finally:
            self.close(event)

    def cancel(self, pipe: int, operation: _Overlapped) -> None:
        self.kernel.CancelIoEx(pipe, ctypes.byref(operation))
        count = w.DWORD()
        self.kernel.GetOverlappedResult(
            pipe, ctypes.byref(operation), ctypes.byref(count), True
        )

    def complete(
        self, pipe: int, operation: _Overlapped | None, timeout_ms: int
    ) -> int:
        if operation is None:
            return 0
        count = w.DWORD()
        if self.kernel.WaitForSingleObject(operation.event, timeout_ms) != 0:
            raise TimeoutError("Windows device authorization timed out")
        if not self.kernel.GetOverlappedResult(
            pipe, ctypes.byref(operation), ctypes.byref(count), False
        ):
            raise self.error("Completing Storage authorization")
        return count.value

    def exchange(self, pipe: int, data: bytes | int, timeout_ms: int) -> bytes:
        buffer = (
            ctypes.create_string_buffer(data)
            if isinstance(data, int)
            else ctypes.create_string_buffer(data, len(data))
        )
        count = w.DWORD()
        with self.operation() as operation:
            function = (
                self.kernel.ReadFile if isinstance(data, int) else self.kernel.WriteFile
            )
            result = function(
                pipe, buffer, len(buffer), ctypes.byref(count), ctypes.byref(operation)
            )
            if not result and last_error() != 997:
                raise self.error("Exchanging the Storage authorization result")
            try:
                size = (
                    count.value
                    if result
                    else self.complete(pipe, operation, timeout_ms)
                )
                if size != len(buffer):
                    raise OSError("Incomplete Storage authorization result")
                return buffer.raw
            finally:
                if not result:
                    self.cancel(pipe, operation)

    def birth(self) -> int:
        stamps = [w.FILETIME() for _ in range(4)]
        if not self.kernel.GetProcessTimes(
            self.kernel.GetCurrentProcess(), *(ctypes.byref(stamp) for stamp in stamps)
        ):
            raise self.error("Identifying the application process")
        return (stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime

    @contextmanager
    def launch(self, executable: Path, arguments: list[str]) -> Generator[int]:
        request = _ShellExecute(
            size=ctypes.sizeof(_ShellExecute),
            mask=0x40 | 0x100 | 0x400,
            verb="runas",
            file=str(executable),
            parameters=subprocess.list2cmdline(arguments),
            directory=os.environ["SYSTEMROOT"],
            show=0,
        )
        initialized = self.com.CoInitializeEx(None, 2)
        if initialized < 0 and initialized != -2147417850:  # RPC_E_CHANGED_MODE
            raise OSError("Windows could not initialize device authorization")
        try:
            if (
                not self.shell.ShellExecuteExW(ctypes.byref(request))
                or not request.process
            ):
                if last_error() == 1223:
                    raise PermissionError("Windows device authorization was cancelled")
                raise self.error("Starting Windows device authorization")
            try:
                yield int(request.process)
            finally:
                self.close(request.process)
        finally:
            if initialized >= 0:
                self.com.CoUninitialize()

    def require_peer(self, pipe: int, process: int) -> None:
        peer = w.DWORD()
        if not self.kernel.GetNamedPipeClientProcessId(
            pipe, ctypes.byref(peer)
        ) or peer.value != self.kernel.GetProcessId(process):
            raise PermissionError("The Storage authorization process did not match")

    def require_exit(self, process: int, timeout_ms: int) -> None:
        if self.kernel.WaitForSingleObject(process, timeout_ms) != 0:
            raise TimeoutError("Windows device authorization did not finish")
        code = w.DWORD()
        if (
            not self.kernel.GetExitCodeProcess(process, ctypes.byref(code))
            or code.value
        ):
            raise OSError("The Storage authorization helper failed")

    @contextmanager
    def diagnostic_process(
        self, executable: Path, arguments: list[str]
    ) -> Generator[int]:
        with subprocess.Popen(
            [str(executable), "--check-ipc", *arguments], creationflags=0x08000000
        ) as child:
            handle = self.kernel.OpenProcess(0x1000 | 0x100000, False, child.pid)
            try:
                if not handle:
                    raise self.error("Identifying the diagnostic helper")
                yield int(handle)
            finally:
                if handle:
                    self.close(handle)
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
