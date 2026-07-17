"""Coordinate exclusive, generation-checked write sessions for one iPod."""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

_ACTIVE_WRITERS: set[str] = set()
_ACTIVE_WRITERS_LOCK = threading.Lock()
_HASH_CHUNK_SIZE = 1024 * 1024


def _writer_lock_identity(volume_key: str) -> str:
    """Collapse mount aliases to the same underlying-volume writer key.

    Scan-time identity keys include a fourth mount-instance field so a remount
    can be detected. Host writer serialization intentionally uses only the OS,
    underlying device, and volume identifiers so bind mounts and aliases cannot
    acquire independent locks for the same storage.
    """
    parts = volume_key.split("|")
    if len(parts) == 4 and all(parts[:3]):
        return "|".join(parts[:3])
    return volume_key


class DeviceWriteSafetyError(RuntimeError):
    """Base class for a condition that makes a device write unsafe."""


class DeviceBusyError(DeviceWriteSafetyError):
    """Raised when another iOpenPod writer already owns the device."""


class ExternalDatabaseChangeError(DeviceWriteSafetyError):
    """Raised when another program changes the database during a write session."""


@dataclass(frozen=True, slots=True)
class DatabaseGeneration:
    """Content-backed identity for the active iTunesDB/iTunesCDB."""

    filename: str
    exists: bool
    size: int = 0
    modified_ns: int = 0
    device: int = 0
    inode: int = 0
    digest: str = ""


class DeviceWriteGuard:
    """Hold one host-wide writer lock and track the starting DB generation.

    The lock lives on the host rather than the iPod so acquiring it never
    dirties the device.  The operating system releases the advisory lock if a
    process crashes.  A content digest catches external writers (for example,
    iTunes) that do not participate in iOpenPod's lock protocol.
    """

    def __init__(
        self,
        ipod_path: str | Path,
        *,
        volume_key: str = "",
        expected_database_generation: DatabaseGeneration | None = None,
        track_database_generation: bool = True,
        lock_dir: str | Path | None = None,
    ) -> None:
        self.ipod_path = Path(os.path.realpath(ipod_path))
        identity_key = _writer_lock_identity(
            str(volume_key or self.ipod_path).strip()
        )
        self._writer_key = hashlib.sha256(
            identity_key.encode("utf-8", errors="surrogatepass")
        ).hexdigest()
        if lock_dir is not None:
            base_dir = Path(lock_dir)
        else:
            directory_name = "iopenpod-device-locks"
            get_user_id = getattr(os, "getuid", None)
            if callable(get_user_id):
                directory_name = f"{directory_name}-{get_user_id()}"
            base_dir = Path(tempfile.gettempdir()) / directory_name
        self.lock_path = base_dir / f"{self._writer_key}.lock"
        self._expected_database_generation = expected_database_generation
        self._track_database_generation = bool(track_database_generation)
        self._file: BinaryIO | None = None
        self._entered = False
        self._database_generation: DatabaseGeneration | None = None

    def __enter__(self) -> DeviceWriteGuard:
        if self._entered:
            raise RuntimeError("DeviceWriteGuard instances cannot be entered twice")

        self._reserve_in_process()
        try:
            _ensure_safe_lock_directory(self.lock_path.parent)
            lock_file = _open_lock_file_safely(self.lock_path)
            self._file = lock_file
            _ensure_lock_byte(lock_file)
            try:
                _lock_file_nonblocking(lock_file)
            except OSError as exc:
                raise DeviceBusyError(
                    "Another iOpenPod process is already writing to this iPod. "
                    "Wait for that operation to finish, then try again."
                ) from exc

            self._write_owner_metadata()
            current_generation = (
                capture_database_generation(self.ipod_path)
                if self._track_database_generation
                else None
            )
            expected_generation = self._expected_database_generation
            if expected_generation is not None:
                if current_generation is None:
                    raise DeviceWriteSafetyError(
                        "The expected iPod database generation cannot be verified "
                        "while database tracking is disabled. iOpenPod stopped "
                        "before writing."
                    )
                if not _same_database_generation(
                    current_generation,
                    expected_generation,
                ):
                    raise ExternalDatabaseChangeError(
                        "The iPod database changed since the iPod library was "
                        "loaded. iOpenPod stopped before overwriting those newer "
                        "changes. Reload the iPod library and try again."
                    )
            self._database_generation = current_generation
            self._entered = True
            logger.info(
                "Acquired exclusive iPod writer guard: mount=%s lock=%s database=%s",
                self.ipod_path,
                self.lock_path,
                (
                    self._database_generation.filename or "absent"
                    if self._database_generation is not None
                    else "not-tracked"
                ),
            )
            return self
        except Exception:
            self._release_resources()
            raise

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self._release_resources()

    @property
    def starting_database_generation(self) -> DatabaseGeneration:
        """Return the generation captured when this session acquired its lock."""
        if self._database_generation is None:
            raise RuntimeError("Device write guard is not active")
        return self._database_generation

    def assert_database_unchanged(self) -> None:
        """Refuse a commit if another program replaced or edited the database."""
        starting = self.starting_database_generation
        current = capture_database_generation(self.ipod_path)
        if _same_database_generation(current, starting):
            return
        raise ExternalDatabaseChangeError(
            "The iPod database changed after this write session started. "
            "iOpenPod stopped before overwriting the newer database. Reload the "
            "iPod library and try again after closing other device-management apps."
        )

    def refresh_database_generation(self) -> None:
        """Record a database commit made by this guarded write session."""
        if not self._entered:
            raise RuntimeError("Device write guard is not active")
        self._database_generation = capture_database_generation(self.ipod_path)

    def _reserve_in_process(self) -> None:
        with _ACTIVE_WRITERS_LOCK:
            if self._writer_key in _ACTIVE_WRITERS:
                raise DeviceBusyError(
                    "iOpenPod is already writing to this iPod. Wait for that "
                    "operation to finish, then try again."
                )
            _ACTIVE_WRITERS.add(self._writer_key)

    def _write_owner_metadata(self) -> None:
        if self._file is None:
            return
        metadata = f"pid={os.getpid()} mount={self.ipod_path}\n".encode(
            "utf-8", errors="replace"
        )
        self._file.seek(1)
        self._file.truncate()
        self._file.write(metadata)
        self._file.flush()

    def _release_resources(self) -> None:
        lock_file = self._file
        self._file = None
        if lock_file is not None:
            try:
                _unlock_file(lock_file)
            except OSError as exc:
                logger.warning("Could not release iPod writer lock cleanly: %s", exc)
            finally:
                lock_file.close()
        with _ACTIVE_WRITERS_LOCK:
            _ACTIVE_WRITERS.discard(self._writer_key)
        if self._entered:
            logger.info("Released exclusive iPod writer guard: mount=%s", self.ipod_path)
        self._entered = False


def _database_path(ipod_path: Path) -> Path:
    # Use the exact same selection logic as the reader and writer. In
    # particular, a known Classic must track iTunesDB even if a stale,
    # non-empty iTunesCDB is also present.
    from .info import itdb_write_filename, resolve_itdb_path

    resolved = resolve_itdb_path(str(ipod_path))
    if resolved is not None:
        return Path(resolved)
    return (
        ipod_path
        / "iPod_Control"
        / "iTunes"
        / itdb_write_filename(str(ipod_path))
    )


def _same_database_generation(
    left: DatabaseGeneration,
    right: DatabaseGeneration,
) -> bool:
    # With no database on disk, a later exact device identification may change
    # the expected filename from iTunesDB to iTunesCDB. That is not an external
    # mutation. Any database created after the first snapshot still has
    # ``exists=True`` and is detected.
    if not left.exists and not right.exists:
        return True
    return left == right


def capture_database_generation(ipod_path: str | Path) -> DatabaseGeneration:
    """Return a content-backed generation for the active device database."""
    ipod_path = Path(ipod_path)
    database = _database_path(ipod_path)
    try:
        before = database.stat()
    except FileNotFoundError:
        return DatabaseGeneration(filename=database.name, exists=False)
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"Could not inspect the iPod database before writing: {exc}"
        ) from exc

    digest = hashlib.sha256()
    try:
        with open(database, "rb") as source:
            while chunk := source.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
        after = database.stat()
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"Could not read the iPod database generation safely: {exc}"
        ) from exc

    before_identity = (
        before.st_size,
        before.st_mtime_ns,
        before.st_dev,
        before.st_ino,
    )
    after_identity = (
        after.st_size,
        after.st_mtime_ns,
        after.st_dev,
        after.st_ino,
    )
    if before_identity != after_identity:
        raise ExternalDatabaseChangeError(
            "The iPod database changed while iOpenPod was inspecting it. Close "
            "other device-management apps, reload the library, and try again."
        )
    return DatabaseGeneration(
        filename=database.name,
        exists=True,
        size=after.st_size,
        modified_ns=after.st_mtime_ns,
        device=after.st_dev,
        inode=after.st_ino,
        digest=digest.hexdigest(),
    )


def _ensure_lock_byte(lock_file: BinaryIO) -> None:
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
    lock_file.seek(0)


def _is_link_or_reparse(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(st, "st_file_attributes", 0) & reparse_flag)


def _ensure_safe_lock_directory(path: Path) -> None:
    """Create and verify the host-side lock directory without following links."""
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = path.lstat()
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"Could not create the host-side iPod lock directory safely: {exc}"
        ) from exc

    if _is_link_or_reparse(directory_stat) or not stat.S_ISDIR(directory_stat.st_mode):
        raise DeviceWriteSafetyError(
            "The host-side iPod lock directory is a link, reparse point, or "
            "non-directory. iOpenPod stopped before writing."
        )

    get_effective_user_id = getattr(os, "geteuid", None)
    if callable(get_effective_user_id):
        if directory_stat.st_uid != get_effective_user_id():
            raise DeviceWriteSafetyError(
                "The host-side iPod lock directory is owned by another user. "
                "iOpenPod stopped before writing."
            )
        try:
            os.chmod(path, 0o700)
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"Could not secure the host-side iPod lock directory: {exc}"
            ) from exc


def _open_lock_file_safely(path: Path) -> BinaryIO:
    """Open a reusable regular lock file without following its final leaf."""
    if sys.platform == "win32":
        return _open_windows_lock_file_safely(path)

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"Could not open the host-side iPod lock file safely: {exc}"
        ) from exc

    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise DeviceWriteSafetyError(
                "The host-side iPod lock path is not a regular file. "
                "iOpenPod stopped before writing."
            )
        get_effective_user_id = getattr(os, "geteuid", None)
        if (
            callable(get_effective_user_id)
            and opened_stat.st_uid != get_effective_user_id()
        ):
            raise DeviceWriteSafetyError(
                "The host-side iPod lock file is owned by another user. "
                "iOpenPod stopped before writing."
            )
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "r+b")
    except Exception:
        os.close(descriptor)
        raise


def _open_windows_lock_file_safely(path: Path) -> BinaryIO:
    """Open a Windows lock while refusing a final reparse point."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    generic_read = 0x80000000
    generic_write = 0x40000000
    share_read = 0x00000001
    share_write = 0x00000002
    open_always = 4
    file_attribute_normal = 0x00000080
    file_flag_open_reparse_point = 0x00200000
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    get_file_information = kernel32.GetFileInformationByHandle
    get_file_information.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    get_file_information.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        str(path),
        generic_read | generic_write,
        share_read | share_write,
        None,
        open_always,
        file_attribute_normal | file_flag_open_reparse_point,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise DeviceWriteSafetyError(
            "Could not open the host-side iPod lock file safely: "
            f"{ctypes.WinError(ctypes.get_last_error())}"
        )

    try:
        information = _ByHandleFileInformation()
        if not get_file_information(handle, ctypes.byref(information)):
            raise ctypes.WinError(ctypes.get_last_error())
        unsafe_attributes = file_attribute_directory | file_attribute_reparse_point
        if information.dwFileAttributes & unsafe_attributes:
            raise DeviceWriteSafetyError(
                "The host-side iPod lock path is a link, reparse point, or "
                "non-file. iOpenPod stopped before writing."
            )
        descriptor = msvcrt.open_osfhandle(
            int(handle),
            os.O_RDWR | getattr(os, "O_BINARY", 0),
        )
        handle = None
        return os.fdopen(descriptor, "r+b")
    except DeviceWriteSafetyError:
        raise
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"Could not verify the host-side iPod lock file safely: {exc}"
        ) from exc
    finally:
        if handle is not None:
            close_handle(handle)


def _lock_file_nonblocking(lock_file: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(lock_file: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
