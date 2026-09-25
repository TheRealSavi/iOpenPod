"""Durability helpers for flushing pending writes to an iPod filesystem."""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)


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


def durable_publish_new(source: str | Path, target: str | Path) -> bool:
    """Publish a flushed file without replacing an existing target.

    Returns whether the now-unneeded source temp was also removed. Once the
    target's parent-directory barrier succeeds, temp cleanup is not allowed to
    turn a committed publication into a reported failure.
    """
    source_path = Path(source)
    target_path = Path(target)
    try:
        os.link(source_path, target_path)
    except FileExistsError:
        raise
    except OSError:
        # Some valid backup destinations (notably FAT/exFAT and network
        # filesystems) do not support hard links. O_EXCL still preserves the
        # no-clobber contract; a crash-truncated file is detected by the
        # manifest checksum and never authorizes blob deletion or restore.
        descriptor = os.open(
            target_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with open(source_path, "rb") as source_file, os.fdopen(
                descriptor,
                "wb",
            ) as target_file:
                descriptor = -1
                shutil.copyfileobj(source_file, target_file)
                flush_written_file(target_file)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                durable_unlink(target_path, missing_ok=True)
            except OSError:
                pass
            raise

    try:
        flush_parent_directory(target_path)
    except OSError:
        # The target was not durably published. Remove the visible entry when
        # possible so callers do not discover an unconfirmed manifest.
        try:
            durable_unlink(target_path, missing_ok=True)
        except OSError:
            logger.exception(
                "Could not remove unconfirmed publication target %s",
                target_path,
            )
        raise

    try:
        durable_unlink(source_path)
    except OSError as exc:
        logger.warning(
            "Published %s, but its temporary source %s could not be removed: %s",
            target_path,
            source_path,
            exc,
        )
        return False
    return True


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
    require_volume_barrier: bool = False,
) -> tuple[bool, str]:
    """Flush pending writes for *mount_path*, checking the command result.

    Linux supports a target-specific flush through GNU ``sync -f``. Windows
    checks ``FlushFileBuffers`` on the committed iTunesDB when present and on
    a documented volume handle. macOS first schedules all filesystem writes
    and then issues ``F_FULLFSYNC`` when a committed database file is available.
    """
    if sys.platform == "win32":
        return _flush_database_anchor(
            mount_path,
            full=False,
            allow_unavailable=allow_unavailable,
            require_volume_barrier=require_volume_barrier,
        )
    if sys.platform == "darwin":
        try:
            os.sync()
        except (AttributeError, OSError) as exc:
            if allow_unavailable:
                return True, f"macOS sync unavailable ({exc}); relying on the unmount flush"
            return False, f"macOS sync failed: {exc}"
        return _flush_database_anchor(
            mount_path,
            full=True,
            allow_unavailable=allow_unavailable,
            require_volume_barrier=require_volume_barrier,
        )
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
    require_volume_barrier: bool,
) -> tuple[bool, str]:
    anchor = _committed_database_path(Path(mount_path))
    if anchor is None:
        if sys.platform == "win32":
            return _windows_flush_volume_anchor(
                Path(mount_path),
                allow_unavailable=allow_unavailable,
            )
        if sys.platform == "darwin" and full:
            # ``flush_filesystem`` has already completed os.sync(). macOS does
            # not document F_FULLFSYNC as a directory-handle operation, so do
            # not invent one for a deliberately database-free snapshot.
            return (
                True,
                "macOS filesystem sync completed; no regular full-fsync "
                "anchor remains on the restored device",
            )
        message = "no committed file or volume durability anchor is available"
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
    if sys.platform == "win32" and require_volume_barrier:
        volume_ok, volume_message = _windows_flush_volume_anchor(
            Path(mount_path),
            allow_unavailable=allow_unavailable,
        )
        if not volume_ok:
            return False, (
                f"Windows file buffers flushed for {anchor}, but the full "
                f"volume barrier failed: {volume_message}"
            )
        return True, (
            f"Windows file buffers flushed for {anchor}; {volume_message}"
        )
    if sys.platform == "win32":
        return True, f"Windows file buffers flushed for {anchor}"
    return True, f"file buffers flushed for {anchor}"


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


def _windows_flush_volume_anchor(
    mount_path: Path,
    *,
    allow_unavailable: bool,
) -> tuple[bool, str]:
    """Flush a database-free Windows device through a documented volume handle."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    flush_buffers = kernel32.FlushFileBuffers
    flush_buffers.argtypes = [ctypes.c_void_p]
    flush_buffers.restype = ctypes.c_int

    get_volume_path = kernel32.GetVolumePathNameW
    get_volume_path.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    get_volume_path.restype = ctypes.c_int
    get_volume_name = kernel32.GetVolumeNameForVolumeMountPointW
    get_volume_name.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    get_volume_name.restype = ctypes.c_int

    volume_root = ctypes.create_unicode_buffer(1024)
    volume_name = ctypes.create_unicode_buffer(1024)
    volume_path = ""
    if get_volume_path(str(mount_path), volume_root, len(volume_root)):
        root = volume_root.value
        if get_volume_name(root, volume_name, len(volume_name)):
            volume_path = volume_name.value.rstrip("\\")
        else:
            drive, _tail = os.path.splitdrive(root)
            if drive:
                volume_path = rf"\\.\{drive}"
    if not volume_path:
        message = "could not resolve the iPod volume handle for a durability barrier"
        if allow_unavailable:
            return True, f"{message}; relying on the required safe-eject flush"
        return False, message

    generic_read_write = 0x80000000 | 0x40000000
    share_read_write = 0x00000001 | 0x00000002
    open_existing = 3
    handle = create_file(
        volume_path,
        generic_read_write,
        share_read_write,
        None,
        open_existing,
        0,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        code = ctypes.get_last_error()
        message = (
            "could not open the iPod volume for a durability barrier: "
            f"{ctypes.FormatError(code).strip() or code}"
        )
        if allow_unavailable:
            return True, f"{message}; relying on the required safe-eject flush"
        return False, message
    try:
        if flush_buffers(handle):
            return True, f"Windows volume buffers flushed for {volume_path}"
        code = ctypes.get_last_error()
        message = (
            "Windows directory durability barrier failed: "
            f"{ctypes.FormatError(code).strip() or code}"
        )
        if allow_unavailable:
            return True, f"{message}; relying on the required safe-eject flush"
        return False, message
    finally:
        close_handle(handle)


def _macos_full_fsync(file_descriptor: int) -> None:
    """Ask macOS and the attached drive to commit their buffered writes."""
    import fcntl

    command = getattr(fcntl, "F_FULLFSYNC", 51)
    fcntl_call = vars(fcntl).get("fcntl")
    if not callable(fcntl_call):
        raise OSError("macOS fcntl() is unavailable")
    fcntl_call(file_descriptor, command)
