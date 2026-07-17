"""Durability helpers for flushing pending writes to an iPod filesystem."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO, Any


def open_unique_sibling_temp(
    target: str | Path,
    *,
    mode: str = "w+b",
    encoding: str | None = None,
) -> tuple[Path, IO[Any]]:
    """Exclusively create and open a short-lived sibling of *target*.

    Device files must not use predictable ``target + '.tmp'`` names: a stale
    or malicious symlink/reparse point at that path could redirect a
    truncating open away from the intended iPod file.  ``mkstemp`` asks the
    filesystem to create a unique name with ``O_EXCL`` semantics and returns
    the already-open descriptor, so there is no check-then-open window.

    The caller owns both the returned file object and path.  It must flush and
    close the file before ``durable_replace`` and durably remove the path on
    failure.  The compact prefix also leaves room on filesystems with short
    component-name limits.
    """
    target_path = Path(target)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".iop-",
        suffix=".tmp",
        dir=str(target_path.parent),
    )
    temp_path = Path(temp_name)
    try:
        if "b" in mode:
            file = os.fdopen(descriptor, mode)
        else:
            file = os.fdopen(descriptor, mode, encoding=encoding or "utf-8")
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
    return temp_path, file


def flush_written_file(file: IO[Any], *, full: bool = False) -> None:
    """Synchronize one file and check the strongest available OS barrier."""
    file.flush()
    os.fsync(file.fileno())
    if sys.platform == "win32":
        _windows_flush_file_buffers(file.fileno())
    elif sys.platform == "darwin" and full:
        _macos_full_fsync(file.fileno())


def flush_parent_directory(path: str | Path) -> None:
    """Persist the directory entry containing *path* on POSIX systems.

    Flushing a file does not necessarily make a create, replace, or unlink
    durable.  POSIX filesystems expose that metadata barrier through the
    containing directory.  Windows write sessions receive their final volume
    barrier through ``flush_filesystem`` and safe eject instead.
    """
    if sys.platform == "win32":
        return

    parent = Path(path).parent
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(str(parent), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_replace(source: str | Path, target: str | Path) -> None:
    """Atomically replace *target* and persist its parent directory entry."""
    os.replace(source, target)
    flush_parent_directory(target)


def durable_unlink(path: str | Path, *, missing_ok: bool = False) -> None:
    """Remove *path* and persist the parent directory entry."""
    target = Path(path)
    try:
        target.unlink()
    except FileNotFoundError:
        if missing_ok:
            return
        raise
    flush_parent_directory(target)


def flush_filesystem(
    mount_path: str | Path,
    *,
    allow_unavailable: bool = False,
) -> tuple[bool, str]:
    """Flush pending writes for *mount_path*, checking the command result.

    Linux supports a target-specific flush through GNU ``sync -f``. Windows
    checks ``FlushFileBuffers`` on the committed iTunesDB, while macOS first
    schedules all filesystem writes and then issues ``F_FULLFSYNC`` on it.
    """
    if sys.platform == "win32":
        return _flush_database_anchor(mount_path, full=False, allow_unavailable=allow_unavailable)
    if sys.platform == "darwin":
        try:
            os.sync()
        except (AttributeError, OSError) as exc:
            if allow_unavailable:
                return True, f"macOS sync unavailable ({exc}); relying on the unmount flush"
            return False, f"macOS sync failed: {exc}"
        return _flush_database_anchor(mount_path, full=True, allow_unavailable=allow_unavailable)
    if sys.platform != "linux":
        message = f"filesystem flush is unsupported on {sys.platform}"
        if allow_unavailable:
            return True, f"{message}; relying on the unmount flush"
        return False, message

    if not shutil.which("sync"):
        message = "sync utility unavailable"
        if allow_unavailable:
            return True, f"{message}; relying on the unmount flush"
        return False, message

    try:
        proc = subprocess.run(
            ["sync", "-f", str(mount_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        message = "sync utility unavailable"
        if allow_unavailable:
            return True, f"{message}; relying on the unmount flush"
        return False, message
    except subprocess.TimeoutExpired:
        return False, "filesystem flush timed out"

    output = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        return False, output or f"filesystem flush failed with code {proc.returncode}"
    return True, output or "pending writes flushed"


def _flush_database_anchor(
    mount_path: str | Path,
    *,
    full: bool,
    allow_unavailable: bool,
) -> tuple[bool, str]:
    anchor = _committed_database_path(Path(mount_path))
    if anchor is None:
        message = "committed iTunesDB/iTunesCDB not found for durability barrier"
        if allow_unavailable:
            return True, f"{message}; relying on the unmount flush"
        return False, message

    try:
        with open(anchor, "rb+") as file:
            flush_written_file(file, full=full)
    except OSError as exc:
        return False, f"filesystem flush failed for {anchor}: {exc}"

    if full:
        return True, f"macOS full filesystem flush completed via {anchor}"
    return True, f"Windows file buffers flushed for {anchor}"


def _committed_database_path(mount_path: Path) -> Path | None:
    # Use the same device-aware authority as the database reader, writer, and
    # generation guard. In particular, a known Classic must flush iTunesDB
    # even when a stale non-empty iTunesCDB is also present.
    from .info import resolve_itdb_path

    resolved = resolve_itdb_path(str(mount_path))
    if resolved is None:
        return None
    candidate = Path(resolved)
    try:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    except OSError:
        pass
    return None


def _windows_flush_file_buffers(file_descriptor: int) -> None:
    """Call and check Win32 ``FlushFileBuffers`` for an open file."""
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.FlushFileBuffers.argtypes = [ctypes.c_void_p]
    kernel32.FlushFileBuffers.restype = ctypes.c_int
    handle = msvcrt.get_osfhandle(file_descriptor)
    if kernel32.FlushFileBuffers(handle):
        return
    code = ctypes.get_last_error()
    raise OSError(code, ctypes.FormatError(code).strip() or "FlushFileBuffers failed")


def _macos_full_fsync(file_descriptor: int) -> None:
    """Ask macOS and the attached drive to commit their buffered writes."""
    import fcntl

    command = getattr(fcntl, "F_FULLFSYNC", 51)
    fcntl_call = vars(fcntl).get("fcntl")
    if not callable(fcntl_call):
        raise OSError("macOS fcntl() is unavailable")
    fcntl_call(file_descriptor, command)
