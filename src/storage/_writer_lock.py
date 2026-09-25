"""Host-side writer leases keyed by stable storage-resource identities."""

from __future__ import annotations

import hashlib
import importlib
import os
import stat
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Self, cast

from storage.errors import DeviceBusyError, StorageOperationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_OWNERS: dict[str, int] = {}


class _WriterLease:
    def __init__(
        self,
        identity: str,
        lock_directory: Path | None,
        resource_name: str,
    ) -> None:
        self._resource_name = resource_name
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self._key = digest
        self._process_lock = _process_lock(digest)
        directory_name = "iopenpod-storage-locks"
        get_user_id = getattr(os, "getuid", None)
        if callable(get_user_id):
            directory_name = f"{directory_name}-{get_user_id()}"
        directory = lock_directory or Path(tempfile.gettempdir()) / directory_name
        self._path = directory / f"{digest}.lock"
        self._file: BinaryIO | None = None

    def __enter__(self) -> Self:
        owner = threading.get_ident()
        with _LOCKS_GUARD:
            if _PROCESS_OWNERS.get(self._key) == owner:
                raise DeviceBusyError(
                    f"This thread already holds the {self._resource_name} writer lease"
                )
        self._process_lock.acquire()
        with _LOCKS_GUARD:
            _PROCESS_OWNERS[self._key] = owner
        try:
            self._file = _open_lock_file(self._path)
            _lock_file(self._file, self._resource_name)
            return self
        except Exception:
            if self._file is not None:
                self._file.close()
                self._file = None
            self._release_process_lock()
            raise

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        lock_file = self._file
        self._file = None
        try:
            if lock_file is not None:
                _unlock_file(lock_file)
                lock_file.close()
        finally:
            self._release_process_lock()

    def _release_process_lock(self) -> None:
        with _LOCKS_GUARD:
            del _PROCESS_OWNERS[self._key]
        self._process_lock.release()


class VolumeWriterLease(_WriterLease):
    """Serialize participating writers without creating files on the device."""

    def __init__(self, identity: str, lock_directory: Path | None = None) -> None:
        super().__init__(identity, lock_directory, "Volume")


class HostResourceLease(_WriterLease):
    """Serialize participating processes that access one Host-side resource."""

    def __init__(self, identity: str, lock_directory: Path | None = None) -> None:
        super().__init__(identity, lock_directory, "Host resource")


def _process_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.Lock())


def _open_lock_file(path: Path) -> BinaryIO:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent_stat = os.lstat(path.parent)
    except OSError as error:
        raise StorageOperationError(
            f"Could not prepare the Host-side writer lease: {error}"
        ) from error
    if _is_link_or_reparse(parent_stat) or not stat.S_ISDIR(parent_stat.st_mode):
        raise StorageOperationError(
            "The Host-side writer lease directory is not a safe directory"
        )
    if os.name != "nt":
        try:
            os.chmod(path.parent, 0o700)
        except OSError as error:
            raise StorageOperationError(
                f"Could not secure the Host-side writer lease directory: {error}"
            ) from error

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise StorageOperationError(
            f"Could not open the Host-side writer lease: {error}"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or _is_link_or_reparse(metadata):
            raise StorageOperationError(
                "The Host-side writer lease path is not a regular file"
            )
        lock_file = os.fdopen(descriptor, "r+b", buffering=0)
        descriptor = -1
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
        lock_file.seek(0)
        return lock_file
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _lock_file(lock_file: BinaryIO, resource_name: str) -> None:
    try:
        if os.name == "nt":
            _windows_locking(lock_file, "LK_NBLCK")
        else:
            _posix_flock(lock_file, "LOCK_EX", "LOCK_NB")
    except OSError as error:
        raise DeviceBusyError(
            f"Another iOpenPod process is already using this {resource_name}"
        ) from error


def _unlock_file(lock_file: BinaryIO) -> None:
    if os.name == "nt":
        _windows_locking(lock_file, "LK_UNLCK")
    else:
        _posix_flock(lock_file, "LOCK_UN")


def _windows_locking(lock_file: BinaryIO, operation_name: str) -> None:
    attributes = vars(importlib.import_module("msvcrt"))
    locking = cast("Callable[[int, int, int], None]", attributes["locking"])
    operation = cast("int", attributes[operation_name])
    lock_file.seek(0)
    locking(lock_file.fileno(), operation, 1)


def _posix_flock(lock_file: BinaryIO, *operation_names: str) -> None:
    attributes = vars(importlib.import_module("fcntl"))
    flock = cast("Callable[[int, int], None]", attributes["flock"])
    operation = 0
    for name in operation_names:
        operation |= cast("int", attributes[name])
    flock(lock_file.fileno(), operation)


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)
