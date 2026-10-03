"""Own an entire candidate bootloader tree before its first instruction runs."""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes as w
from pathlib import Path


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        ("reserved", w.LPWSTR),
        ("desktop", w.LPWSTR),
        ("title", w.LPWSTR),
        ("x", w.DWORD),
        ("y", w.DWORD),
        ("width", w.DWORD),
        ("height", w.DWORD),
        ("chars_x", w.DWORD),
        ("chars_y", w.DWORD),
        ("fill", w.DWORD),
        ("flags", w.DWORD),
        ("show", w.WORD),
        ("reserved_size", w.WORD),
        ("reserved_bytes", ctypes.c_void_p),
        ("stdin", w.HANDLE),
        ("stdout", w.HANDLE),
        ("stderr", w.HANDLE),
    ]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("process", w.HANDLE),
        ("thread", w.HANDLE),
        ("pid", w.DWORD),
        ("tid", w.DWORD),
    ]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", w.DWORD),
        ("minimum_working", ctypes.c_size_t),
        ("maximum_working", ctypes.c_size_t),
        ("processes", w.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("io", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("times", ctypes.c_int64 * 4),
        ("faults", w.DWORD),
        ("total", w.DWORD),
        ("active", w.DWORD),
        ("terminated", w.DWORD),
    ]


class WindowsCandidateProcess:
    """A candidate may be stopped only while device work is bootstrap-blocked."""

    def __init__(self, arguments: list[str], environment: dict[str, str]) -> None:
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel = self._kernel
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            w.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            w.DWORD,
        ]
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.CreateProcessW.argtypes = [
            w.LPCWSTR,
            w.LPWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            w.BOOL,
            w.DWORD,
            ctypes.c_void_p,
            w.LPCWSTR,
            ctypes.POINTER(_StartupInfo),
            ctypes.POINTER(_ProcessInfo),
        ]
        kernel.ResumeThread.argtypes = [w.HANDLE]
        kernel.ResumeThread.restype = w.DWORD
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        kernel.WaitForSingleObject.restype = w.DWORD
        kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        kernel.QueryInformationJobObject.argtypes = [
            w.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.c_void_p,
        ]
        self._job = kernel.CreateJobObjectW(None, None)
        if not self._job:
            raise ctypes.WinError(ctypes.get_last_error())
        self._process = _ProcessInfo()
        self._arguments = arguments
        try:
            self._limits(kill_on_close=True)
            startup = _StartupInfo()
            startup.cb = ctypes.sizeof(startup)
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(arguments))
            block = ctypes.create_unicode_buffer(
                "\0".join(
                    f"{name}={value}"
                    for name, value in sorted(
                        environment.items(), key=lambda pair: pair[0].upper()
                    )
                )
                + "\0"
            )
            if not kernel.CreateProcessW(
                arguments[0],
                command,
                None,
                None,
                False,
                0x08000404,
                block,
                str(Path(arguments[0]).parent),
                ctypes.byref(startup),
                ctypes.byref(self._process),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            # The initial thread is suspended: even the onefile bootloader cannot
            # create an unowned child between process creation and job assignment.
            if not kernel.AssignProcessToJobObject(self._job, self._process.process):
                raise ctypes.WinError(ctypes.get_last_error())
            if kernel.ResumeThread(self._process.thread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            kernel.CloseHandle(self._process.thread)
            self._process.thread = None
        except BaseException:
            if self._process.process:
                kernel.TerminateProcess(self._process.process, 1)
            kernel.CloseHandle(self._job)
            if self._process.thread:
                kernel.CloseHandle(self._process.thread)
            if self._process.process:
                kernel.CloseHandle(self._process.process)
            raise

    def _limits(self, *, kill_on_close: bool) -> None:
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000 if kill_on_close else 0
        if not self._kernel.SetInformationJobObject(
            self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def poll(self) -> int | None:
        result = self._kernel.WaitForSingleObject(self._process.process, 0)
        if result == 258:
            return None
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = w.DWORD()
        if not self._kernel.GetExitCodeProcess(
            self._process.process, ctypes.byref(code)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def wait(self, timeout: float | None = None) -> int:
        result = self._kernel.WaitForSingleObject(
            self._process.process,
            int(timeout * 1000) if timeout is not None else 0xFFFFFFFF,
        )
        if result == 258:
            assert timeout is not None
            raise subprocess.TimeoutExpired(self._arguments, timeout)
        code = self.poll()
        if code is None:
            raise OSError("Candidate wait returned without process exit")
        return code

    def stop(self) -> None:
        if not self._kernel.TerminateJobObject(self._job, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + 15
        while True:
            accounting = _Accounting()
            if not self._kernel.QueryInformationJobObject(
                self._job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if accounting.active == 0:
                self.wait(timeout=15)
                return
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "The candidate process tree has not stopped; recovery files were retained"
                )
            time.sleep(0.05)

    def release(self) -> None:
        # Called only after probe exit or after the durable health commit. A new
        # application then owns its lifetime, even when this helper exits.
        self._limits(kill_on_close=False)
        self._kernel.CloseHandle(self._job)
        self._kernel.CloseHandle(self._process.process)
