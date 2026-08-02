"""
Content-Addressable Backup Manager for iPod devices.

Creates verified, git-like snapshots of the iPod's regular-file tree. Each
snapshot records every included file's path, bytes, size, modification time,
and SHA-256 hash. Files are stored once by hash in a **shared** blob store —
identical files across different devices are stored only once.

This is a functional file backup, not a raw-disk image: explicitly excluded
host metadata, empty directories, permissions/ACLs, extended attributes,
resource forks, sparse allocation, and partition/firmware state are outside
the manifest contract.

Storage layout on PC:
    <backup_dir>/
        blobs/<aa>/<aabbccddee...>      # Shared content-addressable files
        <device_id>/
            snapshots/<timestamp>.json  # Manifest per backup

Restore reconciles the included regular-file tree to the verified snapshot.
"""

import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Concatenate, ParamSpec, TypeVar

from iopenpod.device.durability import (
    durable_publish_new,
    durable_replace,
    durable_unlink,
    flush_filesystem,
    flush_parent_directory,
    flush_written_file,
    open_unique_sibling_temp,
)
from iopenpod.device.filesystem_profile import FilesystemProfile, inspect_filesystem_profile
from iopenpod.device.storage_safety import (
    allocated_size,
    existing_file_allocated_size,
    require_file_size_supported,
)
from iopenpod.device.virtual_identity import virtual_ipod_profile
from iopenpod.device.write_guard import (
    DeviceBusyError,
    DeviceWriteGuard,
    DeviceWriteSafetyError,
)
from iopenpod.device.write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)

logger = logging.getLogger(__name__)

# Default backup directory (XDG-aware on Linux)


def _resolve_default_backup_dir() -> str:
    try:
        from iopenpod.infrastructure.settings_paths import default_data_dir
        return os.path.join(default_data_dir(), "backups")
    except Exception:
        return os.path.join(os.path.expanduser("~"), "iOpenPod", "backups")


_DEFAULT_BACKUP_DIR = _resolve_default_backup_dir()

# Number of worker threads for parallel I/O.
# iPod is on USB (single bus) so diminishing returns above ~4,
# but we overlap iPod reads with PC blob writes + CPU hashing.
_NUM_WORKERS = 4

# OS-managed directories/files to skip during backup and never delete during restore.
# Stored in lower-case; comparisons use .lower() for case-insensitive matching on
# Windows (FAT32/exFAT are case-preserving but case-insensitive).
_OS_EXCLUDE_LOWER = frozenset({
    "system volume information",
    "$recycle.bin",
    ".trashes",
    ".fseventsd",
    ".spotlight-v100",
    ".ds_store",
    ".metadata_never_index",
    "thumbs.db",
    "desktop.ini",
})


def _is_excluded(name: str) -> bool:
    """Check if a filename/dirname should be excluded (case-insensitive)."""
    lower = name.lower()
    return lower in _OS_EXCLUDE_LOWER or lower.startswith("._")


# SHA-256 read buffer
_HASH_BUF_SIZE = 1024 * 1024  # 1 MB

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_SNAPSHOT_NOTE_LENGTH = 4_000
_SNAPSHOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CURRENT_MANIFEST_VERSION = 3
_SUPPORTED_MANIFEST_VERSIONS = frozenset({2, 3})
_MAX_MTIME_NS = (1 << 63) - 1
_AUTOMATIC_SAFETY_CHECKPOINT_LIMIT = 5
_PROVISIONAL_ARCHIVE_TOKENS: dict[str, str] = {}
_PROVISIONAL_DEVICE_TOKENS: dict[int, tuple[object, str]] = {}
_PROVISIONAL_ARCHIVE_TOKENS_LOCK = threading.Lock()
_FAT_FILESYSTEMS = frozenset(
    {"exfat", "fat", "fat16", "fat32", "msdos", "msdosfs", "vfat"}
)
_HFS_FILESYSTEMS = frozenset({"hfs", "hfs+", "hfsplus", "hfsx"})
_FAT_MIN_MTIME_NS = 315_532_800 * 1_000_000_000
_FAT_MAX_MTIME_NS = 4_354_819_198 * 1_000_000_000
_WINDOWS_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _mtime_matches(
    actual_ns: int,
    expected_ns: int,
    filesystem_type: str,
) -> bool:
    """Compare modification times at the target filesystem's resolution."""
    normalized = filesystem_type.casefold()
    if normalized in _FAT_FILESYSTEMS:
        tolerance_ns = 2_000_000_000
    elif normalized in _HFS_FILESYSTEMS:
        tolerance_ns = 1_000_000_000
    else:
        tolerance_ns = 1_000_000
    return abs(actual_ns - expected_ns) <= tolerance_ns


def _provisional_archive_identifier(
    identity_key: str,
    *,
    session_owner: object | None = None,
) -> str:
    """Return a process-session archive ID for non-hardware evidence.

    Filesystem UUIDs, FAT serials, device numbers, mount IDs, and drive letters
    can all be cloned or reused by a different iPod. A scanned device object
    therefore owns a unique in-process token. This keeps every caller in one
    selected-device session consistent without allowing another object—or a
    later app run—to merge into its unresolved archive.
    """
    with _PROVISIONAL_ARCHIVE_TOKENS_LOCK:
        if session_owner is not None:
            owner_key = id(session_owner)
            owner_entry = _PROVISIONAL_DEVICE_TOKENS.get(owner_key)
            if owner_entry is None or owner_entry[0] is not session_owner:
                token = os.urandom(24).hex()
                # Retaining the owner prevents Python object-ID reuse from
                # accidentally inheriting another connected iPod's token.
                _PROVISIONAL_DEVICE_TOKENS[owner_key] = (session_owner, token)
            else:
                token = owner_entry[1]
            digest_input = f"selected-device-session|{token}"
        else:
            token = _PROVISIONAL_ARCHIVE_TOKENS.get(identity_key)
            if token is None:
                token = os.urandom(24).hex()
                _PROVISIONAL_ARCHIVE_TOKENS[identity_key] = token
            digest_input = f"{identity_key}|{token}"
    digest = hashlib.sha256(
        digest_input.encode("utf-8", errors="surrogatepass")
    ).hexdigest()
    return f"unidentified_session_{digest[:24]}"


def _filesystem_component_length(component: str, filesystem_type: str) -> int:
    """Measure a filename in the units used by common iPod filesystems."""
    normalized = filesystem_type.casefold()
    if normalized in _FAT_FILESYSTEMS | _HFS_FILESYSTEMS:
        return len(component.encode("utf-16-le")) // 2
    return len(os.fsencode(component))


class RestoreIncompleteError(DeviceWriteSafetyError):
    """A restore failed after at least one durable device mutation."""

    device_dirty = True


class RestoreDurabilityPendingError(RestoreIncompleteError):
    """Restored bytes verified, but the final volume barrier is still pending."""

    content_verified = True
    requires_safe_eject = True


class _BackupOperationCancelled(RuntimeError):
    """Internal control flow for cancellation before device mutation."""


@contextmanager
def _locked_backup_repository(backup_root: Path):
    """Hold transition and object locks for one backup repository.

    The bootstrap lock coordinates first creation without touching the backup
    destination. Once the repository exists, its filesystem object identity is
    also locked so bind mounts, mapped drives, UNC paths, and other aliases
    cannot obtain independent writer sessions.
    """
    guards: list[DeviceWriteGuard] = []
    try:
        identities = [_repository_bootstrap_lock_identity(backup_root)]
        object_identity = _repository_lock_identity(backup_root)
        if object_identity not in identities:
            identities.append(object_identity)
        for identity in identities:
            guard = DeviceWriteGuard(
                backup_root,
                volume_key=identity,
                track_database_generation=False,
                # Repository maintenance is not an iPod mutation.  It must
                # fail fast so a second backup cannot silently block a GUI
                # operation behind a long-running archive writer.
                queue_in_process=False,
            )
            try:
                guard.__enter__()
            except DeviceBusyError as exc:
                raise DeviceWriteSafetyError(
                    "Another iOpenPod process is using this backup location. "
                    "Wait for it to finish, then try again."
                ) from exc
            guards.append(guard)
        yield
    finally:
        for guard in reversed(guards):
            guard.__exit__(None, None, None)


def _repository_bootstrap_lock_identity(backup_root: Path) -> str:
    """Identify a not-yet-created repository through its nearest parent."""
    resolved = Path(os.path.realpath(backup_root))
    probe = resolved.parent if resolved.parent != resolved else resolved
    suffix_parts = (() if probe == resolved else (resolved.name,))
    while not probe.exists() and probe.parent != probe:
        suffix_parts = (probe.name, *suffix_parts)
        probe = probe.parent
    try:
        parent_stat = probe.stat()
    except OSError:
        normalized = os.path.normcase(os.path.realpath(resolved))
        return f"iopenpod-backup-repository:bootstrap:path:{normalized}"

    device = int(getattr(parent_stat, "st_dev", 0) or 0)
    inode = int(getattr(parent_stat, "st_ino", 0) or 0)
    if not device and not inode:
        normalized = os.path.normcase(os.path.realpath(resolved))
        return f"iopenpod-backup-repository:bootstrap:path:{normalized}"
    suffix = os.path.normcase("/".join(suffix_parts))
    return (
        "iopenpod-backup-repository:bootstrap:"
        f"{os.name}:{device}:{inode}:{suffix}"
    )


def _windows_repository_file_identity(path: Path) -> tuple[int, int] | None:
    """Return the Win32 volume serial and file index for an existing directory."""
    if os.name != "nt":
        return None

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", ctypes.c_uint32),
            ("creation_time_low", ctypes.c_uint32),
            ("creation_time_high", ctypes.c_uint32),
            ("access_time_low", ctypes.c_uint32),
            ("access_time_high", ctypes.c_uint32),
            ("write_time_low", ctypes.c_uint32),
            ("write_time_high", ctypes.c_uint32),
            ("volume_serial_number", ctypes.c_uint32),
            ("file_size_high", ctypes.c_uint32),
            ("file_size_low", ctypes.c_uint32),
            ("number_of_links", ctypes.c_uint32),
            ("file_index_high", ctypes.c_uint32),
            ("file_index_low", ctypes.c_uint32),
        ]

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
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    get_information.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    share_all = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    backup_semantics = 0x02000000
    handle = create_file(
        str(path),
        0,
        share_all,
        None,
        open_existing,
        backup_semantics,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        return None
    try:
        information = _ByHandleFileInformation()
        if not get_information(handle, ctypes.byref(information)):
            return None
        file_index = (
            int(information.file_index_high) << 32
        ) | int(information.file_index_low)
        return int(information.volume_serial_number), file_index
    finally:
        close_handle(handle)


def _repository_lock_identity(backup_root: Path) -> str:
    """Identify an existing repository by its physical directory object."""
    resolved = Path(os.path.realpath(backup_root))
    if not resolved.is_dir():
        return _repository_bootstrap_lock_identity(resolved)

    windows_identity = _windows_repository_file_identity(resolved)
    if windows_identity is not None:
        volume_serial, file_index = windows_identity
        return (
            "iopenpod-backup-repository:object:windows:"
            f"{volume_serial}:{file_index}"
        )
    try:
        repository_stat = resolved.stat()
    except OSError:
        return _repository_bootstrap_lock_identity(resolved)

    device = int(getattr(repository_stat, "st_dev", 0) or 0)
    inode = int(getattr(repository_stat, "st_ino", 0) or 0)
    if not device and not inode:
        return _repository_bootstrap_lock_identity(resolved)
    return (
        "iopenpod-backup-repository:object:"
        f"{os.name}:{device}:{inode}"
    )


def _repository_locked(
    method: Callable[Concatenate["BackupManager", _P], _R],
) -> Callable[Concatenate["BackupManager", _P], _R]:
    """Serialize archive reads that race with creation, deletion, or GC."""

    @wraps(method)
    def wrapper(
        manager: "BackupManager",
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        if manager._repository_lock_depth:
            return method(manager, *args, **kwargs)
        with _locked_backup_repository(manager.backup_root):
            manager._repository_lock_depth += 1
            try:
                return method(manager, *args, **kwargs)
            finally:
                manager._repository_lock_depth -= 1

    return wrapper


def _repository_locked_create(
    method: Callable[Concatenate["BackupManager", _P], _R],
) -> Callable[Concatenate["BackupManager", _P], _R]:
    """Serialize creation and clean unpublished blobs on every early exit."""

    @wraps(method)
    def wrapper(
        manager: "BackupManager",
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        def run_with_device_guard() -> _R:
            if manager._active_device_guard is not None:
                return run_create()

            ipod_path = (
                kwargs.get("ipod_path")
                if "ipod_path" in kwargs
                else (args[0] if args else "")
            )
            source_profile = _inspect_backup_source(
                Path(str(ipod_path or "")),
                reported_volume_format=str(
                    kwargs.get("reported_volume_format", "") or ""
                ),
                expected_volume_identity_key=str(
                    kwargs.get("expected_volume_identity_key", "") or ""
                ),
                allow_uninitialized_source=bool(
                    kwargs.get("_allow_uninitialized_source", False)
                ),
            )
            with DeviceWriteGuard(
                str(ipod_path),
                volume_key=volume_lock_key(source_profile),
                track_database_generation=True,
            ) as device_guard:
                manager._active_device_guard = device_guard
                try:
                    return run_create()
                finally:
                    manager._active_device_guard = None

        def run_create() -> _R:
            try:
                result = method(manager, *args, **kwargs)
            except Exception:
                try:
                    manager._gc_blobs()
                except Exception as cleanup_exc:
                    logger.warning(
                        "Could not clean unpublished backup blobs after failure: %s",
                        cleanup_exc,
                    )
                raise
            if result is None and manager._last_create_cancelled:
                try:
                    manager._gc_blobs()
                except Exception as cleanup_exc:
                    logger.warning(
                        "Could not clean unpublished backup blobs after cancellation: %s",
                        cleanup_exc,
                    )
            return result

        if manager._repository_lock_depth:
            return run_with_device_guard()

        # The repository lock transition must never create a directory before
        # proving that the configured destination is not on the iPod itself.
        # Repeat the lightweight source/destination check here; create_backup
        # performs it again under the device writer guard before reading files.
        raw_ipod_path = (
            kwargs.get("ipod_path")
            if "ipod_path" in kwargs
            else (args[0] if args else "")
        )
        ipod_path = Path(str(raw_ipod_path or ""))
        source_profile = _inspect_backup_source(
            ipod_path,
            reported_volume_format=str(
                kwargs.get("reported_volume_format", "") or ""
            ),
            expected_volume_identity_key=str(
                kwargs.get("expected_volume_identity_key", "") or ""
            ),
            allow_uninitialized_source=bool(
                kwargs.get("_allow_uninitialized_source", False)
            ),
        )
        _ensure_backup_destination_is_separate(
            ipod_path,
            manager.backup_root,
            source_profile,
        )
        try:
            manager.backup_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"The backup location could not be prepared safely: {exc}"
            ) from exc

        with _locked_backup_repository(manager.backup_root):
            manager._repository_lock_depth += 1
            try:
                return run_with_device_guard()
            finally:
                manager._repository_lock_depth -= 1

    return wrapper


def _is_link_or_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"Could not inspect backup repository path {path}: {exc}"
        ) from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = int(getattr(info, "st_file_attributes", 0) or 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _ensure_repository_path_safe(backup_root: Path, path: Path) -> None:
    """Reject symlink/reparse traversal below the canonical repository root."""
    try:
        relative = path.relative_to(backup_root)
    except ValueError as exc:
        raise DeviceWriteSafetyError(
            "A backup repository path escaped the configured backup location."
        ) from exc
    current = backup_root
    for component in relative.parts:
        current /= component
        if os.path.lexists(current) and _is_link_or_reparse_point(current):
            raise DeviceWriteSafetyError(
                f"The backup repository contains an unsafe link at {current}. "
                "iOpenPod stopped without reading, replacing, or deleting through it."
            )


@dataclass(frozen=True, slots=True)
class _RestoreFile:
    relative_path: str
    file_hash: str
    size: int
    mtime_ns: int | None
    blob_path: Path


_SnapshotState = dict[str, tuple[str, int, int | None]]


@dataclass(slots=True)
class _RestoreWriteSession:
    """Identity-retained, durable mutation session for one backup restore."""

    mount_path: Path
    filesystem_profile: FilesystemProfile
    write_guard: DeviceWriteGuard | None = None
    device_dirty: bool = False
    finalized: bool = False
    finalize_attempted: bool = False

    def revalidate(self, *, probe_case_sensitivity: bool | None = None) -> None:
        self.filesystem_profile = revalidate_device_write_readiness(
            self.filesystem_profile,
            probe_case_sensitivity=probe_case_sensitivity,
        )

    def validate_target(self, relative_path: str, size: int) -> None:
        target = _resolve_restore_path(self.mount_path, relative_path)
        limit = int(self.filesystem_profile.max_component_length or 0)
        if limit > 0:
            relative_parts = target.relative_to(self.mount_path).parts
            too_long = next(
                (
                    part
                    for part in relative_parts
                    if _filesystem_component_length(
                        part,
                        self.filesystem_profile.filesystem_type,
                    )
                    > limit
                ),
                None,
            )
            if too_long is not None:
                raise DeviceWriteSafetyError(
                    f"The backup path component {too_long!r} exceeds this iPod "
                    f"filesystem's {limit}-character filename limit."
                )
        require_file_size_supported(
            size,
            max_file_size_bytes=self.filesystem_profile.max_file_size_bytes,
            display_name=relative_path,
        )

    def ensure_parent(self, relative_path: str) -> None:
        target = _resolve_restore_path(self.mount_path, relative_path)
        relative_parent_parts = target.parent.relative_to(self.mount_path).parts
        for depth in range(1, len(relative_parent_parts) + 1):
            self.revalidate()
            target = _resolve_restore_path(self.mount_path, relative_path)
            directory = self.mount_path.joinpath(*relative_parent_parts[:depth])
            if directory.exists():
                if not directory.is_dir():
                    raise DeviceWriteSafetyError(
                        f"Cannot restore {relative_path}: {directory} is not a directory."
                    )
                continue
            directory.mkdir()
            self.device_dirty = True
            flush_parent_directory(directory)

    def delete(self, relative_path: str) -> None:
        self.revalidate()
        target = _resolve_restore_path(self.mount_path, relative_path)
        # Durability helpers can fail after the namespace mutation succeeds
        # (for example while flushing the parent directory). Mark the session
        # conservatively before calling one so recovery guidance is never lost.
        self.device_dirty = True
        durable_unlink(target)

    def remove_empty_parents(self, relative_path: str) -> None:
        target = _resolve_restore_path(self.mount_path, relative_path)
        relative_parent_parts = target.parent.relative_to(self.mount_path).parts
        for depth in range(len(relative_parent_parts), 0, -1):
            parent = self.mount_path.joinpath(*relative_parent_parts[:depth])
            try:
                has_entries = next(parent.iterdir(), None) is not None
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not inspect restore directory {parent}: {exc}"
                ) from exc
            if has_entries:
                break
            self.revalidate()
            _resolve_restore_path(self.mount_path, relative_path)
            if not parent.exists():
                continue
            try:
                parent.rmdir()
                self.device_dirty = True
                flush_parent_directory(parent)
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not remove empty restore directory {parent}: {exc}"
                ) from exc

    def install(self, restore_file: _RestoreFile) -> None:
        self.validate_target(restore_file.relative_path, restore_file.size)
        self.ensure_parent(restore_file.relative_path)
        self.revalidate()
        self._ensure_free_space(restore_file.size, restore_file.relative_path)
        target = _resolve_restore_path(self.mount_path, restore_file.relative_path)
        fd, raw_temp = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=".iop-restore-",
            suffix=".tmp",
        )
        temp_path = Path(raw_temp)
        try:
            with open(restore_file.blob_path, "rb") as source, os.fdopen(
                fd,
                "wb",
            ) as destination:
                fd = -1
                shutil.copyfileobj(source, destination, _HASH_BUF_SIZE)
                flush_written_file(destination)

            if _hash_file(temp_path) != restore_file.file_hash:
                raise DeviceWriteSafetyError(
                    f"The temporary restore copy for {restore_file.relative_path} "
                    "failed its SHA-256 verification."
                )

            self.revalidate()
            target = _resolve_restore_path(self.mount_path, restore_file.relative_path)
            if temp_path.parent != target.parent:
                raise DeviceWriteSafetyError(
                    "The restore destination changed before atomic replacement."
                )
            # ``durable_replace`` includes a post-replace directory flush. If
            # that flush fails, the target may already contain the new bytes.
            self.device_dirty = True
            durable_replace(temp_path, target)

            if _hash_file(target) != restore_file.file_hash:
                raise DeviceWriteSafetyError(
                    f"The restored file {restore_file.relative_path} failed its "
                    "SHA-256 verification."
                )
            self.apply_metadata(restore_file)
        except Exception:
            if fd >= 0:
                os.close(fd)
            if not self._cleanup_temp_if_safe(temp_path):
                self.device_dirty = True
            raise

    def apply_metadata(self, restore_file: _RestoreFile) -> None:
        """Restore captured file metadata that the target filesystem supports."""
        if restore_file.mtime_ns is None:
            return
        self.revalidate()
        target = _resolve_restore_path(
            self.mount_path,
            restore_file.relative_path,
        )
        try:
            current_stat = target.stat()
            if _mtime_matches(
                current_stat.st_mtime_ns,
                restore_file.mtime_ns,
                self.filesystem_profile.filesystem_type,
            ):
                return
            current_atime_ns = current_stat.st_atime_ns
            try:
                self.device_dirty = True
                os.utime(
                    target,
                    ns=(current_atime_ns, restore_file.mtime_ns),
                    follow_symlinks=False,
                )
            except (NotImplementedError, TypeError):
                if target.is_symlink():
                    raise DeviceWriteSafetyError(
                        f"Refusing to apply metadata through symbolic link {target}."
                    ) from None
                self.device_dirty = True
                os.utime(
                    target,
                    ns=(current_atime_ns, restore_file.mtime_ns),
                )
            restored_mtime_ns = target.stat().st_mtime_ns
            if not _mtime_matches(
                restored_mtime_ns,
                restore_file.mtime_ns,
                self.filesystem_profile.filesystem_type,
            ):
                raise DeviceWriteSafetyError(
                    f"The modification time for {restore_file.relative_path} "
                    "could not be restored at this filesystem's supported resolution."
                )
        except (OSError, OverflowError, ValueError) as exc:
            raise DeviceWriteSafetyError(
                f"Could not restore the modification time for "
                f"{restore_file.relative_path}: {exc}"
            ) from exc

    def finalize(self) -> None:
        self.finalize_attempted = True
        self.revalidate()
        flush_ok, flush_message = flush_filesystem(
            self.mount_path,
            allow_unavailable=False,
            require_volume_barrier=True,
        )
        if not flush_ok:
            raise RestoreDurabilityPendingError(
                "Every restored file passed final SHA-256 verification, but "
                "the operating system did not confirm the final iPod volume "
                f"flush: {flush_message}. Keep the iPod connected and use "
                "iOpenPod's Eject command before unplugging or syncing it."
            )
        self.revalidate()
        self.finalized = True
        logger.info("Backup restore durability barrier completed: %s", flush_message)

    def _ensure_free_space(self, size: int, relative_path: str) -> None:
        try:
            free = shutil.disk_usage(self.mount_path).free
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"Could not verify iPod free space before restoring "
                f"{relative_path}: {exc}"
            ) from exc
        required = allocated_size(
            size,
            self.filesystem_profile.allocation_unit_size,
        )
        if free < required:
            raise DeviceWriteSafetyError(
                f"The iPod does not have enough free space to atomically restore "
                f"{relative_path}. iOpenPod stopped before creating its temporary copy."
            )

    def _cleanup_temp_if_safe(self, temp_path: Path) -> bool:
        try:
            self.revalidate()
            durable_unlink(temp_path, missing_ok=True)
            return True
        except Exception as exc:
            logger.warning(
                "Could not safely remove temporary restore file %s: %s",
                temp_path,
                exc,
            )
            return False


def _manifest_order_key(manifest_path: Path) -> tuple[int, int, str]:
    """Return an archive-monotonic ordering key with legacy fallbacks."""
    try:
        with open(manifest_path, encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        try:
            modified_ns = manifest_path.stat().st_mtime_ns
        except OSError:
            modified_ns = 0
        return (-1, modified_ns, manifest_path.stem)

    sequence = manifest.get("sequence")
    if (
        not isinstance(sequence, bool)
        and isinstance(sequence, int)
        and sequence > 0
    ):
        return (1, sequence, manifest_path.stem)
    raw_timestamp = manifest.get("timestamp")
    if isinstance(raw_timestamp, str):
        try:
            parsed = datetime.fromisoformat(raw_timestamp)
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            return (0, int(parsed.timestamp() * 1_000_000_000), manifest_path.stem)
        except (OverflowError, ValueError):
            pass
    try:
        modified_ns = manifest_path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    return (0, modified_ns, manifest_path.stem)


def _restore_component_key(
    component: str,
    filesystem_profile: FilesystemProfile,
) -> str:
    filesystem_type = filesystem_profile.filesystem_type.casefold()
    normalized = (
        unicodedata.normalize("NFD", component)
        if filesystem_type in _HFS_FILESYSTEMS
        else unicodedata.normalize("NFC", component)
    )
    if filesystem_profile.case_sensitive is True:
        return normalized
    return normalized.casefold()


def _validate_restore_target_names(
    target_files: dict[str, _RestoreFile],
    filesystem_profile: FilesystemProfile,
) -> None:
    """Reject aliases and names the target filesystem cannot represent."""
    filesystem_type = filesystem_profile.filesystem_type.casefold()
    normalized_paths: dict[tuple[str, ...], str] = {}
    normalized_directories: dict[tuple[str, ...], tuple[str, ...]] = {}
    for relative_path, restore_file in target_files.items():
        components = tuple(relative_path.split("/"))
        if filesystem_type in _FAT_FILESYSTEMS:
            if (
                restore_file.mtime_ns is not None
                and not (
                    _FAT_MIN_MTIME_NS
                    <= restore_file.mtime_ns
                    <= _FAT_MAX_MTIME_NS
                )
            ):
                raise DeviceWriteSafetyError(
                    f"The backup modification time for {relative_path!r} cannot "
                    "be represented on this iPod filesystem."
                )
            for component in components:
                if (
                    any(ord(character) < 32 for character in component)
                    or any(character in '<>:"/\\|?*' for character in component)
                    or component.endswith((" ", "."))
                    or component.split(".", 1)[0].rstrip(" .").casefold()
                    in _WINDOWS_RESERVED_STEMS
                ):
                    raise DeviceWriteSafetyError(
                        f"The backup path {relative_path!r} cannot be represented "
                        "safely on this iPod filesystem."
                    )

        normalized = tuple(
            _restore_component_key(component, filesystem_profile)
            for component in components
        )
        previous = normalized_paths.get(normalized)
        if previous is not None and previous != relative_path:
            raise DeviceWriteSafetyError(
                f"The backup contains file paths that collide on this iPod: "
                f"{previous!r} and {relative_path!r}."
            )
        normalized_paths[normalized] = relative_path
        for depth in range(1, len(components)):
            normalized_directory = normalized[:depth]
            actual_directory = components[:depth]
            previous_directory = normalized_directories.get(normalized_directory)
            if (
                previous_directory is not None
                and previous_directory != actual_directory
            ):
                raise DeviceWriteSafetyError(
                    "The backup contains directory names that alias each other "
                    f"on this iPod: {'/'.join(previous_directory)!r} and "
                    f"{'/'.join(actual_directory)!r}."
                )
            normalized_directories[normalized_directory] = actual_directory

    normalized_file_paths = set(normalized_paths)
    for normalized, relative_path in normalized_paths.items():
        if any(
            normalized[:depth] in normalized_file_paths
            for depth in range(1, len(normalized))
        ):
            raise DeviceWriteSafetyError(
                f"The backup path {relative_path!r} is nested beneath another file."
            )


def _resolve_restore_path(ipod_root: Path, relative_path: str) -> Path:
    """Resolve one manifest path within the selected iPod root."""
    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise DeviceWriteSafetyError("The backup contains an invalid file path.")
    unified = relative_path
    if (
        unified.startswith(("/", "\\\\"))
        or re.match(r"^[A-Za-z]:[/\\]", unified)
    ):
        raise DeviceWriteSafetyError(
            f"The backup contains an absolute file path: {relative_path!r}."
        )
    parts = tuple(unified.split("/"))
    if any(not part or part in {".", ".."} for part in parts):
        raise DeviceWriteSafetyError(
            f"The backup contains an unsafe file path: {relative_path!r}."
        )
    if any(_is_excluded(part) for part in parts):
        raise DeviceWriteSafetyError(
            f"The backup path {relative_path!r} targets an OS-managed location."
        )

    try:
        root = ipod_root.resolve(strict=True)
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"The selected iPod root is unavailable: {exc}"
        ) from exc
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current /= part
        try:
            if current.is_symlink():
                raise DeviceWriteSafetyError(
                    f"The backup path {relative_path!r} crosses a symbolic link."
                )
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"Could not safely inspect backup path {relative_path!r}: {exc}"
            ) from exc
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise DeviceWriteSafetyError(
            f"The backup path escapes the selected iPod: {relative_path!r}."
        ) from exc
    return candidate


def _resolve_export_relative_path(relative_path: str) -> tuple[str, ...]:
    """Validate a manifest path before materializing it on the host."""
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or "\x00" in relative_path
    ):
        raise DeviceWriteSafetyError("The backup contains an invalid file path.")
    if (
        relative_path.startswith(("/", "\\\\"))
        or re.match(r"^[A-Za-z]:[/\\]", relative_path)
    ):
        raise DeviceWriteSafetyError(
            f"The backup contains an absolute file path: {relative_path!r}."
        )
    parts = tuple(relative_path.split("/"))
    if any(not part or part in {".", ".."} for part in parts):
        raise DeviceWriteSafetyError(
            f"The backup contains an unsafe file path: {relative_path!r}."
        )
    if any(_is_excluded(part) for part in parts):
        raise DeviceWriteSafetyError(
            f"The backup path {relative_path!r} targets an OS-managed location."
        )
    if os.name == "nt":
        for component in parts:
            if (
                any(ord(character) < 32 for character in component)
                or any(character in '<>:"\\|?*' for character in component)
                or component.endswith((" ", "."))
                or component.split(".", 1)[0].rstrip(" .").casefold()
                in _WINDOWS_RESERVED_STEMS
            ):
                raise DeviceWriteSafetyError(
                    f"The backup path {relative_path!r} cannot be represented "
                    "safely on this computer."
                )
    return parts


def _resolve_export_path(export_root: Path, relative_path: str) -> Path:
    """Resolve one validated manifest path beneath a newly-created export."""
    parts = _resolve_export_relative_path(relative_path)
    root = export_root.resolve(strict=True)
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise DeviceWriteSafetyError(
                f"The export path {relative_path!r} crosses a symbolic link."
            )
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise DeviceWriteSafetyError(
            f"The export path escapes its destination: {relative_path!r}."
        ) from exc
    return candidate


def _hash_file(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as file:
        while chunk := file.read(_HASH_BUF_SIZE):
            sha.update(chunk)
    return sha.hexdigest()


def _manifest_digest(manifest: dict) -> str:
    """Digest the canonical manifest payload, excluding the digest itself."""
    payload = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_manifest_entries(
    manifest: object,
    *,
    expected_snapshot_id: str,
    expected_device_id: str,
) -> dict[str, dict]:
    """Validate the complete manifest catalog before it can authorize deletion."""
    if not isinstance(manifest, dict):
        raise DeviceWriteSafetyError("The backup manifest is not a JSON object.")

    version = manifest.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in _SUPPORTED_MANIFEST_VERSIONS
    ):
        raise DeviceWriteSafetyError(
            f"The backup manifest version {version!r} is unsupported."
        )
    if manifest.get("id") != expected_snapshot_id:
        raise DeviceWriteSafetyError(
            "The backup manifest identity does not match its snapshot filename."
        )
    if manifest.get("device_id") != expected_device_id:
        raise DeviceWriteSafetyError(
            "The selected snapshot belongs to a different iPod backup set."
        )
    identity_marker = manifest.get("identity_is_stable")
    if identity_marker is not None and not isinstance(identity_marker, bool):
        raise DeviceWriteSafetyError(
            "The backup manifest has an invalid hardware-identity marker."
        )
    source_volume_key = manifest.get("source_volume_identity_key")
    if source_volume_key is not None and not isinstance(source_volume_key, str):
        raise DeviceWriteSafetyError(
            "The backup manifest has an invalid source-volume identity."
        )

    raw_files = manifest.get("files")
    file_count = manifest.get("file_count")
    total_size = manifest.get("total_size")
    if not isinstance(raw_files, dict):
        raise DeviceWriteSafetyError(
            "The backup manifest has an invalid files section."
        )
    if (
        isinstance(file_count, bool)
        or not isinstance(file_count, int)
        or file_count < 0
    ):
        raise DeviceWriteSafetyError(
            "The backup manifest has an invalid file count."
        )
    if (
        isinstance(total_size, bool)
        or not isinstance(total_size, int)
        or total_size < 0
    ):
        raise DeviceWriteSafetyError(
            "The backup manifest has an invalid total size."
        )

    validated: dict[str, dict] = {}
    computed_size = 0
    for relative_path, file_info in raw_files.items():
        if not isinstance(relative_path, str) or not isinstance(file_info, dict):
            raise DeviceWriteSafetyError(
                "The backup manifest contains an invalid file entry."
            )
        file_hash = file_info.get("hash")
        size = file_info.get("size")
        mtime_ns = file_info.get("mtime_ns")
        if not isinstance(file_hash, str) or not _SHA256_RE.fullmatch(file_hash):
            raise DeviceWriteSafetyError(
                f"The backup entry for {relative_path!r} has an invalid SHA-256 hash."
            )
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise DeviceWriteSafetyError(
                f"The backup entry for {relative_path!r} has an invalid file size."
            )
        if (
            mtime_ns is not None
            and (
                isinstance(mtime_ns, bool)
                or not isinstance(mtime_ns, int)
                or not 0 <= mtime_ns <= _MAX_MTIME_NS
            )
        ):
            raise DeviceWriteSafetyError(
                f"The backup entry for {relative_path!r} has an invalid "
                "modification time."
            )
        computed_size += size
        validated[relative_path] = file_info

    if file_count != len(validated) or total_size != computed_size:
        raise DeviceWriteSafetyError(
            "The backup manifest catalog does not match its recorded file "
            "count and size. iOpenPod stopped before changing the iPod."
        )

    if version >= 3:
        recorded_digest = manifest.get("manifest_sha256")
        if (
            not isinstance(recorded_digest, str)
            or not _SHA256_RE.fullmatch(recorded_digest)
            or recorded_digest.casefold() != _manifest_digest(manifest)
        ):
            raise DeviceWriteSafetyError(
                "The backup manifest failed its integrity checksum."
            )
    return validated


def _file_state_key(relative_path: str, file_stat: os.stat_result) -> str:
    """Build a conservative key for detecting a file changed during an operation."""
    return "|".join(
        (
            relative_path,
            str(file_stat.st_size),
            str(file_stat.st_mtime_ns),
            str(file_stat.st_ctime_ns),
            str(file_stat.st_dev),
            str(file_stat.st_ino),
        )
    )


def _inspect_backup_source(
    mount_path: Path,
    *,
    reported_volume_format: str,
    expected_volume_identity_key: str = "",
    allow_uninitialized_source: bool = False,
) -> FilesystemProfile:
    """Capture and validate the scan-time identity for a read-only backup pass."""
    profile = virtual_ipod_profile(
        inspect_filesystem_profile(
            mount_path,
            reported_volume_format=reported_volume_format,
        ),
        mount_path,
    )
    requested = os.path.normcase(os.path.realpath(mount_path))
    observed_mount = os.path.normcase(os.path.realpath(profile.mount_path))
    is_virtual_ipod = (Path(requested) / "iPodInfo.json").is_file()
    if requested != observed_mount and not is_virtual_ipod:
        raise DeviceWriteSafetyError(
            "The selected iPod path is not mounted as its own volume. "
            "iOpenPod stopped before reading an empty host directory as an iPod."
        )
    has_ipod_layout = (Path(requested) / "iPod_Control").is_dir()
    if (
        not is_virtual_ipod
        and not has_ipod_layout
        and not (
            allow_uninitialized_source
            and bool(expected_volume_identity_key)
        )
    ):
        raise DeviceWriteSafetyError(
            "The selected volume no longer contains iPod_Control. "
            "Reconnect and reselect the iPod before creating its backup."
        )
    if not profile.identity.is_complete:
        raise DeviceWriteSafetyError(
            "The connected iPod volume identity could not be verified before backup."
        )
    if (
        expected_volume_identity_key
        and volume_lock_key(profile) != expected_volume_identity_key
    ):
        raise DeviceWriteSafetyError(
            "A different volume is mounted at the selected iPod path. "
            "iOpenPod stopped before creating a mixed-device backup."
        )
    logger.debug(
        "Backup source filesystem: mount=%s actual=%s reported=%s identity=%s",
        profile.mount_path,
        profile.filesystem_type or "unknown",
        profile.reported_volume_format or "unknown",
        expected_volume_identity_key,
    )
    return profile


def _revalidate_backup_source(
    retained: FilesystemProfile,
    *,
    allow_uninitialized_source: bool = False,
) -> None:
    current = virtual_ipod_profile(
        inspect_filesystem_profile(
            retained.inspection_path or retained.mount_path,
            reported_volume_format=retained.reported_volume_format,
        ),
        retained.inspection_path or retained.mount_path,
    )
    if (
        not current.identity.is_complete
        or current.identity != retained.identity
        or current.filesystem_type != retained.filesystem_type
        or os.path.realpath(current.mount_path) != os.path.realpath(retained.mount_path)
    ):
        raise DeviceWriteSafetyError(
            "The selected iPod volume changed while its backup was being created. "
            "iOpenPod discarded the incomplete snapshot."
        )
    requested = Path(retained.inspection_path or retained.mount_path)
    if (
        not allow_uninitialized_source
        and not (requested / "iPodInfo.json").is_file()
        and not (requested / "iPod_Control").is_dir()
    ):
        raise DeviceWriteSafetyError(
            "The selected iPod disappeared while its backup was being created. "
            "iOpenPod discarded the incomplete snapshot."
        )


def _ensure_backup_destination_is_separate(
    ipod_root: Path,
    backup_root: Path,
    source_profile: FilesystemProfile,
) -> None:
    """Refuse a backup repository stored on the physical iPod being protected."""
    selected = Path(os.path.realpath(ipod_root))
    destination = Path(os.path.realpath(backup_root))
    try:
        destination.relative_to(selected)
    except ValueError:
        pass
    else:
        raise DeviceWriteSafetyError(
            "The backup location is inside the selected iPod. Choose a folder "
            "on the computer or another drive before backing up or restoring."
        )

    if (selected / "iPodInfo.json").is_file():
        return

    probe = destination
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        destination_profile = inspect_filesystem_profile(probe)
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"The backup destination filesystem could not be verified: {exc}"
        ) from exc
    source_identity = source_profile.identity
    destination_identity = destination_profile.identity
    if (
        source_identity.is_complete
        and destination_identity.is_complete
        and source_identity.operating_system == destination_identity.operating_system
        and source_identity.device_id == destination_identity.device_id
        and source_identity.volume_id == destination_identity.volume_id
    ):
        raise DeviceWriteSafetyError(
            "The backup location is on the same physical iPod being protected. "
            "Choose storage on the computer or another drive."
        )


@dataclass
class SnapshotInfo:
    """Summary information about a backup snapshot."""

    id: str  # timestamp string, e.g. "20260228_151400"
    timestamp: str  # ISO format datetime
    device_id: str
    device_name: str
    file_count: int = 0
    total_size: int = 0  # bytes
    reason: str = "manual"
    note: str = ""
    # Delta vs previous snapshot (computed on list)
    files_added: int = 0
    files_removed: int = 0
    files_changed: int = 0
    # Device metadata (family, generation, color) for UI display
    device_meta: dict = field(default_factory=dict)
    is_valid: bool = True
    validation_error: str = ""

    @property
    def display_date(self) -> str:
        """Human-readable date string."""
        try:
            dt = datetime.fromisoformat(self.timestamp)
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            return dt.strftime("%b %d, %Y · %I:%M %p")
        except Exception:
            return self.timestamp


@dataclass(frozen=True, slots=True)
class ExportResult:
    """The materialized filesystem folder created from one snapshot."""

    destination: Path
    file_count: int
    total_size: int


@dataclass
class BackupProgress:
    """Progress info for backup/restore callbacks."""

    stage: str  # "hashing", "copying", "restoring", "cleaning"
    current: int
    total: int
    current_file: str = ""
    message: str = ""


class BackupManager:
    """
    Manages content-addressable backups of a full iPod device.

    Args:
        device_id: Unique identifier for the device (serial number or folder name).
        backup_dir: Root directory for all backups. Empty string uses default.
        device_name: Human-readable device name (for display in manifests).
    """

    def __init__(self, device_id: str, backup_dir: str = "",
                 device_name: str = "iPod",
                 device_meta: dict | None = None,
                 identity_is_stable: bool = False):
        self.device_id = self._sanitize_id(device_id)
        self.device_name = device_name
        self.device_meta = device_meta or {}
        self.identity_is_stable = bool(identity_is_stable)
        # Re-entrancy belongs to one operation thread, not to the manager
        # instance. A BackupManager can be shared by GUI/application callers;
        # instance-global depth would let a second thread bypass both locks.
        self._operation_state = threading.local()
        self._last_create_cancelled = False
        self.backup_root = Path(
            os.path.realpath(backup_dir or _DEFAULT_BACKUP_DIR)
        )
        self.device_dir = self.backup_root / self.device_id
        self.blobs_dir = self.backup_root / "blobs"  # Shared across devices
        self.snapshots_dir = self.device_dir / "snapshots"

    @property
    def _repository_lock_depth(self) -> int:
        return int(getattr(self._operation_state, "repository_lock_depth", 0))

    @_repository_lock_depth.setter
    def _repository_lock_depth(self, value: int) -> None:
        self._operation_state.repository_lock_depth = int(value)

    @property
    def _active_device_guard(self) -> DeviceWriteGuard | None:
        return getattr(self._operation_state, "active_device_guard", None)

    @_active_device_guard.setter
    def _active_device_guard(self, value: DeviceWriteGuard | None) -> None:
        self._operation_state.active_device_guard = value

    @staticmethod
    def _sanitize_id(device_id: str) -> str:
        """Sanitize device_id for use as a directory name."""
        # Replace problematic characters
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in device_id)
        return safe or "unknown_device"

    # ── Public API ──────────────────────────────────────────────────────────

    @_repository_locked_create
    def create_backup(
        self,
        ipod_path: str | Path,
        progress_callback: Callable[[BackupProgress], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        max_backups: int = 10,
        *,
        reported_volume_format: str = "",
        expected_volume_identity_key: str = "",
        reason: str = "manual",
        _force_snapshot: bool = False,
        _allow_uninitialized_source: bool = False,
    ) -> SnapshotInfo | None:
        """
        Create a full backup of the iPod device.

        Walks the entire iPod root, hashes every file, stores new blobs,
        and writes a snapshot manifest. Prunes old snapshots if over limit.

        Args:
            ipod_path: Root path of the iPod (e.g. "D:\\").
            progress_callback: Called with BackupProgress updates.
            is_cancelled: If provided, called to check for cancellation.
            max_backups: Max snapshots to retain (0 = unlimited).
            reason: Why the snapshot was created (manual, pre-sync, or
                pre-restore safety checkpoint).

        Returns:
            SnapshotInfo for the new snapshot, or None if cancelled/unchanged.

        Raises:
            DeviceWriteSafetyError: If a complete, identity-stable snapshot
                cannot be committed safely.
        """
        ipod_root = Path(ipod_path)
        self._last_create_cancelled = False
        source_profile = _inspect_backup_source(
            ipod_root,
            reported_volume_format=reported_volume_format,
            expected_volume_identity_key=expected_volume_identity_key,
            allow_uninitialized_source=_allow_uninitialized_source,
        )
        _ensure_backup_destination_is_separate(
            ipod_root,
            self.backup_root,
            source_profile,
        )
        self._migrate_device_blobs()

        # Ensure directories exist
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        archive_is_provisional = self.device_id.startswith("unidentified_")
        if not archive_is_provisional:
            self._update_device_metadata_unlocked()

        # Phase 1: Discover all files
        if progress_callback:
            progress_callback(BackupProgress(
                "scanning", 0, 0, message="Enumerating iPod files…"
            ))

        try:
            all_files = self._walk_device(ipod_root, fail_on_error=True)
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"The iPod filesystem could not be read completely: {exc}. "
                "iOpenPod did not create a partial backup."
            ) from exc
        _revalidate_backup_source(
            source_profile,
            allow_uninitialized_source=_allow_uninitialized_source,
        )
        total_files = len(all_files)

        logger.info(f"Backup: found {total_files} files to process")

        if progress_callback:
            progress_callback(BackupProgress(
                "scanning", 0, total_files,
                message=f"Found {total_files:,} files, verifying every file…"
            ))

        # Phase 2: Fully hash every source file and store verified blobs. A
        # metadata cache is never trusted for preservation snapshots: removable
        # filesystems can retain coarse timestamps across content changes.

        manifest_files: dict[str, dict] = {}
        total_size = 0
        new_blobs = 0
        skipped_files = 0
        skipped_samples: list[str] = []
        processed = 0
        captured_file_keys: set[str] = set()

        files_to_hash: list[tuple[str, Path, int, int, str]] = []

        for rel_path, full_path in all_files:
            try:
                st = full_path.stat()
                if not 0 <= st.st_mtime_ns <= _MAX_MTIME_NS:
                    raise DeviceWriteSafetyError(
                        f"The iPod file {rel_path} has a modification time "
                        "that cannot be preserved safely."
                    )
                cache_key = _file_state_key(rel_path, st)
                files_to_hash.append(
                    (
                        rel_path,
                        full_path,
                        st.st_size,
                        st.st_mtime_ns,
                        cache_key,
                    )
                )
            except (OSError, PermissionError) as e:
                skipped_files += 1
                if len(skipped_samples) < 5:
                    skipped_samples.append(f"{rel_path} ({e})")

        logger.info("Backup: fully hashing %s files", len(files_to_hash))
        if progress_callback and files_to_hash:
            progress_callback(BackupProgress(
                "hashing", processed, total_files,
                message=f"Hashing and verifying {len(files_to_hash):,} files…"
            ))

        if files_to_hash:
            lock = threading.Lock()

            def _process_file(
                rel_path: str,
                full_path: Path,
                fsize: int,
                fmtime: int,
                cache_key: str,
            ):
                """Hash a file and store its blob. Returns result tuple."""
                file_hash = self._hash_file(full_path)
                is_new = self._store_blob(
                    full_path,
                    file_hash,
                )
                if _file_state_key(rel_path, full_path.stat()) != cache_key:
                    raise DeviceWriteSafetyError(
                        f"The iPod file {rel_path} changed while its backup "
                        "was being created. iOpenPod discarded the incomplete snapshot."
                    )
                return rel_path, fsize, fmtime, cache_key, file_hash, is_new

            with ThreadPoolExecutor(max_workers=_NUM_WORKERS) as pool:
                futures = {
                    pool.submit(_process_file, rp, fp, sz, mt, cache_key): rp
                    for rp, fp, sz, mt, cache_key in files_to_hash
                }

                for future in as_completed(futures):
                    if is_cancelled and is_cancelled():
                        pool.shutdown(wait=False, cancel_futures=True)
                        logger.info("Backup cancelled by user")
                        self._last_create_cancelled = True
                        return None

                    processed += 1
                    try:
                        (
                            rel_path,
                            fsize,
                            fmtime,
                            cache_key,
                            file_hash,
                            is_new,
                        ) = future.result()

                        with lock:
                            manifest_files[rel_path] = {
                                "hash": file_hash, "size": fsize, "mtime_ns": fmtime,
                            }
                            captured_file_keys.add(cache_key)
                            total_size += fsize
                            if is_new:
                                new_blobs += 1

                        if progress_callback:
                            progress_callback(BackupProgress(
                                "hashing", processed, total_files,
                                current_file=rel_path,
                                message=f"Hashing {processed}/{total_files}: {rel_path}"
                            ))

                    except (OSError, PermissionError) as e:
                        rp = futures[future]
                        with lock:
                            skipped_files += 1
                            if len(skipped_samples) < 5:
                                skipped_samples.append(f"{rp} ({e})")

        _revalidate_backup_source(
            source_profile,
            allow_uninitialized_source=_allow_uninitialized_source,
        )
        if skipped_files:
            examples = "; ".join(skipped_samples)
            raise DeviceWriteSafetyError(
                f"The iPod backup could not read {skipped_files} file(s). "
                f"iOpenPod discarded the incomplete snapshot. {examples}"
            )
        try:
            final_files = self._walk_device(ipod_root, fail_on_error=True)
            final_file_keys = {
                relative_path: _file_state_key(relative_path, full_path.stat())
                for relative_path, full_path in final_files
            }
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"The iPod changed or became unreadable during its backup: {exc}. "
                "iOpenPod discarded the incomplete snapshot."
            ) from exc
        if set(final_file_keys.values()) != captured_file_keys:
            raise DeviceWriteSafetyError(
                "The iPod filesystem changed while its backup was being created. "
                "iOpenPod discarded the mixed-time snapshot; close other device "
                "management apps and try again."
            )

        # Do not re-read the complete device here. Every source file was
        # SHA-256 hashed during capture, every newly written blob was verified,
        # and the state-key comparison above catches structural or metadata
        # changes before publication. A second full-device content pass makes
        # large preservation libraries needlessly read hundreds of gigabytes
        # again without improving the integrity of the stored blobs.

        # Phase 2c: Check for duplicate — content and preserved metadata both
        # define the state. A safety checkpoint must not disappear merely
        # because only a timestamp changed.
        latest_snap = self._get_latest_snapshot_files()
        if latest_snap is not None and not _force_snapshot:
            preserved_fields = ("hash", "size", "mtime_ns")
            previous_state = {
                relative_path: tuple(file_info.get(field) for field in preserved_fields)
                for relative_path, file_info in latest_snap.items()
            }
            current_state = {
                relative_path: tuple(file_info.get(field) for field in preserved_fields)
                for relative_path, file_info in manifest_files.items()
            }
            if previous_state == current_state:
                logger.info("Backup: no changes since last snapshot — skipping")
                if progress_callback:
                    progress_callback(BackupProgress(
                        "no_changes", total_files, total_files,
                        message="No changes since last backup"
                    ))
                return None

        # Phase 3: Write manifest
        _revalidate_backup_source(
            source_profile,
            allow_uninitialized_source=_allow_uninitialized_source,
        )
        if self._active_device_guard is not None:
            self._active_device_guard.assert_database_unchanged()
        now = datetime.now(UTC)
        timestamp = now.strftime("%Y%m%dT%H%M%S_%fZ")
        manifest_path = self._snapshot_manifest_path(timestamp)
        if manifest_path.exists():
            raise DeviceWriteSafetyError(
                "A backup snapshot ID collision occurred. iOpenPod stopped "
                "instead of replacing an existing snapshot."
            )
        sequence = self._next_snapshot_sequence()

        manifest = {
            "version": _CURRENT_MANIFEST_VERSION,
            "id": timestamp,
            "timestamp": now.isoformat(),
            "sequence": sequence,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_meta": self.device_meta,
            "identity_is_stable": self.identity_is_stable,
            "source_volume_identity_key": str(
                expected_volume_identity_key or ""
            ),
            "reason": str(reason or "manual"),
            "note": "",
            "file_count": len(manifest_files),
            "total_size": total_size,
            "source_verification": "full_sha256",
            "files": manifest_files,
        }
        manifest["manifest_sha256"] = _manifest_digest(manifest)

        tmp_path: Path | None = None
        manifest_published = False
        try:
            tmp_path, manifest_file = open_unique_sibling_temp(
                manifest_path,
                mode="w",
                encoding="utf-8",
            )
            with manifest_file as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
                flush_written_file(f)
            temp_cleanup_complete = durable_publish_new(tmp_path, manifest_path)
            manifest_published = True
            with open(manifest_path, encoding="utf-8") as published_file:
                published_manifest = json.load(published_file)
            if published_manifest != manifest:
                raise DeviceWriteSafetyError(
                    "The published backup manifest did not match the verified "
                    "snapshot prepared by iOpenPod."
                )
            _validated_manifest_entries(
                published_manifest,
                expected_snapshot_id=timestamp,
                expected_device_id=self.device_id,
            )
            if not temp_cleanup_complete:
                logger.warning(
                    "Snapshot %s was committed and verified, but temporary "
                    "manifest cleanup remains pending at %s",
                    timestamp,
                    tmp_path,
                )
        except Exception as e:
            logger.error(f"Failed to write snapshot manifest: {e}")
            if manifest_published:
                try:
                    durable_unlink(manifest_path, missing_ok=True)
                except OSError:
                    logger.exception(
                        "Could not remove a published manifest that failed "
                        "post-publication validation: %s",
                        manifest_path,
                    )
            try:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise DeviceWriteSafetyError(
                "The backup manifest could not be committed safely. "
                "No snapshot was reported as complete."
            ) from e

        # Prune old snapshots
        if max_backups > 0 and not archive_is_provisional:
            self._prune_snapshots(
                max_backups,
                preserve_snapshot_id=timestamp,
            )
        elif max_backups > 0 and archive_is_provisional:
            logger.info(
                "Automatic retention is disabled for unresolved iPod identity %s; "
                "snapshots are preserved until the device can be reassociated safely.",
                self.device_id,
            )

        info = SnapshotInfo(
            id=timestamp,
            timestamp=manifest["timestamp"],
            device_id=self.device_id,
            device_name=self.device_name,
            file_count=len(manifest_files),
            total_size=total_size,
            reason=str(reason or "manual"),
            device_meta=self.device_meta,
        )

        if skipped_files:
            examples = "; examples: " + ", ".join(skipped_samples) if skipped_samples else ""
            logger.warning(
                f"Backup complete with {skipped_files} skipped files: "
                f"{len(manifest_files)} files stored, "
                f"{total_size / (1024**3):.2f} GB, {new_blobs} new blobs"
                f"{examples}"
            )
        else:
            logger.info(
                f"Backup complete: {len(manifest_files)} files, "
                f"{total_size / (1024**3):.2f} GB, {new_blobs} new blobs"
            )

        if progress_callback:
            msg = f"Backup complete — {len(manifest_files)} files, {new_blobs} new"
            if skipped_files:
                msg += f" ({skipped_files} files could not be read)"
            progress_callback(BackupProgress(
                "complete", total_files, total_files, message=msg
            ))

        return info

    @_repository_locked
    def update_snapshot_note(self, snapshot_id: str, note: str) -> bool:
        """Persist a user note without changing the snapshot's file content."""
        if not isinstance(note, str):
            raise DeviceWriteSafetyError("A backup note must be text.")
        normalized_note = note.strip()
        if len(normalized_note) > _MAX_SNAPSHOT_NOTE_LENGTH:
            raise DeviceWriteSafetyError(
                f"A backup note cannot exceed {_MAX_SNAPSHOT_NOTE_LENGTH:,} characters."
            )
        manifest_path = self._snapshot_manifest_path(snapshot_id)
        manifest = self._load_manifest(snapshot_id)
        if manifest is None:
            raise DeviceWriteSafetyError(
                f"The backup snapshot {snapshot_id!r} could not be found."
            )
        _validated_manifest_entries(
            manifest,
            expected_snapshot_id=snapshot_id,
            expected_device_id=self.device_id,
        )
        if str(manifest.get("note", "") or "") == normalized_note:
            return True
        manifest["note"] = normalized_note
        manifest["manifest_sha256"] = _manifest_digest(manifest)
        tmp_path: Path | None = None
        try:
            tmp_path, manifest_file = open_unique_sibling_temp(
                manifest_path,
                mode="w",
                encoding="utf-8",
            )
            with manifest_file as file:
                json.dump(manifest, file, indent=2, ensure_ascii=False)
                flush_written_file(file)
            durable_replace(tmp_path, manifest_path)
            tmp_path = None
            with open(manifest_path, encoding="utf-8") as file:
                published = json.load(file)
            _validated_manifest_entries(
                published,
                expected_snapshot_id=snapshot_id,
                expected_device_id=self.device_id,
            )
            return True
        finally:
            if tmp_path is not None:
                durable_unlink(tmp_path, missing_ok=True)

    def restore_backup(
        self,
        snapshot_id: str,
        ipod_path: str | Path,
        progress_callback: Callable[[BackupProgress], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        *,
        reported_volume_format: str = "",
        expected_volume_identity_key: str = "",
        allow_unverified_device: bool = False,
    ) -> bool:
        """Safely restore after preserving the device's current file state."""
        return self.restore_with_safety_checkpoint(
            snapshot_id,
            ipod_path,
            progress_callback=progress_callback,
            safety_progress_callback=progress_callback,
            is_cancelled=is_cancelled,
            reported_volume_format=reported_volume_format,
            expected_volume_identity_key=expected_volume_identity_key,
            allow_unverified_device=allow_unverified_device,
        )

    @_repository_locked
    def restore_with_safety_checkpoint(
        self,
        snapshot_id: str,
        ipod_path: str | Path,
        progress_callback: Callable[[BackupProgress], None] | None = None,
        safety_progress_callback: Callable[[BackupProgress], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        *,
        reported_volume_format: str = "",
        expected_volume_identity_key: str = "",
        allow_unverified_device: bool = False,
    ) -> bool:
        """Capture current state and restore under one exclusive transaction."""
        if not self.identity_is_stable and not allow_unverified_device:
            raise DeviceWriteSafetyError(
                "Restore requires a stable hardware serial number or FireWire "
                "GUID for the connected iPod."
            )

        source_profile = _inspect_backup_source(
            Path(ipod_path),
            reported_volume_format=reported_volume_format,
            expected_volume_identity_key=expected_volume_identity_key,
            allow_uninitialized_source=True,
        )
        with DeviceWriteGuard(
            ipod_path,
            volume_key=volume_lock_key(source_profile),
            track_database_generation=True,
        ) as device_guard:
            self._active_device_guard = device_guard
            checkpoint: SnapshotInfo | None = None
            try:
                checkpoint = self.create_backup(
                    ipod_path,
                    progress_callback=safety_progress_callback,
                    is_cancelled=is_cancelled,
                    max_backups=0,
                    reported_volume_format=reported_volume_format,
                    expected_volume_identity_key=expected_volume_identity_key,
                    reason="pre_restore_safety",
                    _force_snapshot=True,
                    _allow_uninitialized_source=True,
                )
                if checkpoint is None:
                    return False
                if is_cancelled and is_cancelled():
                    return False

                checkpoint_manifest = self._load_manifest(checkpoint.id)
                if checkpoint_manifest is None:
                    raise DeviceWriteSafetyError(
                        "The safety checkpoint could not be reopened. "
                        "iOpenPod stopped before changing the iPod."
                    )
                raw_checkpoint_files = _validated_manifest_entries(
                    checkpoint_manifest,
                    expected_snapshot_id=checkpoint.id,
                    expected_device_id=self.device_id,
                )
                checkpoint_state: _SnapshotState = {
                    relative_path: (
                        str(file_info["hash"]).casefold(),
                        int(file_info["size"]),
                        (
                            int(file_info["mtime_ns"])
                            if file_info.get("mtime_ns") is not None
                            else None
                        ),
                    )
                    for relative_path, file_info in raw_checkpoint_files.items()
                }
                self._prune_safety_checkpoints(
                    preserve_snapshot_id=checkpoint.id,
                )

                return self._restore_backup_from_snapshot(
                    snapshot_id,
                    ipod_path,
                    progress_callback=progress_callback,
                    is_cancelled=is_cancelled,
                    reported_volume_format=reported_volume_format,
                    expected_volume_identity_key=expected_volume_identity_key,
                    allow_unverified_device=allow_unverified_device,
                    _expected_current_state=checkpoint_state,
                )
            except Exception as exc:
                if checkpoint is not None:
                    vars(exc)["safety_snapshot_id"] = checkpoint.id
                raise
            finally:
                self._active_device_guard = None

    @_repository_locked
    def export_snapshot(
        self,
        snapshot_id: str,
        destination_dir: str | Path,
        progress_callback: Callable[[BackupProgress], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> ExportResult | None:
        """Materialize a validated snapshot as ordinary files on the computer.

        ``destination_dir`` is treated as a parent folder. A new uniquely
        named child is created so an export can never overwrite user files.
        The archive itself is read-only and remains content-addressed.
        """
        self._migrate_device_blobs()
        manifest = self._load_manifest(snapshot_id)
        if not manifest:
            raise DeviceWriteSafetyError(
                f"The backup snapshot {snapshot_id!r} could not be found."
            )
        raw_files = _validated_manifest_entries(
            manifest,
            expected_snapshot_id=snapshot_id,
            expected_device_id=self.device_id,
        )
        export_files = self._validated_export_files(raw_files)
        parent = Path(destination_dir).expanduser().resolve()
        try:
            parent.relative_to(self.backup_root.resolve())
        except ValueError:
            pass
        else:
            raise DeviceWriteSafetyError(
                "Choose an export location outside the iOpenPod backup "
                "repository so exported files cannot be mistaken for archive data."
            )
        parent.mkdir(parents=True, exist_ok=True)
        export_root = self._create_export_directory(parent, snapshot_id)

        if progress_callback:
            progress_callback(BackupProgress(
                "exporting",
                0,
                len(export_files),
                message=f"Preparing export folder: {export_root.name}",
            ))

        try:
            for index, (relative_path, file_info) in enumerate(
                export_files.items(),
                start=1,
            ):
                if is_cancelled and is_cancelled():
                    raise _BackupOperationCancelled
                target = _resolve_export_path(export_root, relative_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                blob_path = self._blob_path(file_info["hash"])
                fd, raw_temp = tempfile.mkstemp(
                    dir=str(target.parent),
                    prefix=".iopenpod-export-",
                    suffix=".tmp",
                )
                temp_path = Path(raw_temp)
                try:
                    if target.exists() or os.path.lexists(target):
                        raise DeviceWriteSafetyError(
                            f"The export destination already contains "
                            f"{relative_path!r}; no files were overwritten."
                        )
                    digest = hashlib.sha256()
                    copied = 0
                    with open(blob_path, "rb") as source, os.fdopen(
                        fd,
                        "wb",
                    ) as destination:
                        fd = -1
                        while chunk := source.read(_HASH_BUF_SIZE):
                            destination.write(chunk)
                            digest.update(chunk)
                            copied += len(chunk)
                        flush_written_file(destination)
                    if digest.hexdigest() != file_info["hash"] or copied != file_info["size"]:
                        raise DeviceWriteSafetyError(
                            f"The backup blob for {relative_path!r} failed "
                            "verification while exporting."
                        )
                    durable_replace(temp_path, target)
                    mtime_ns = file_info.get("mtime_ns")
                    if isinstance(mtime_ns, int):
                        os.utime(target, ns=(mtime_ns, mtime_ns))
                except Exception:
                    if fd >= 0:
                        os.close(fd)
                    durable_unlink(temp_path, missing_ok=True)
                    raise
                if progress_callback:
                    progress_callback(BackupProgress(
                        "exporting",
                        index,
                        len(export_files),
                        current_file=relative_path,
                        message=(
                            f"Exporting {index:,}/{len(export_files):,}: "
                            f"{relative_path}"
                        ),
                    ))
        except _BackupOperationCancelled:
            shutil.rmtree(export_root, ignore_errors=True)
            return None
        except Exception:
            shutil.rmtree(export_root, ignore_errors=True)
            raise

        return ExportResult(
            destination=export_root,
            file_count=len(export_files),
            total_size=sum(int(info["size"]) for info in export_files.values()),
        )

    def _validated_export_files(
        self,
        raw_files: dict[str, dict],
    ) -> dict[str, dict]:
        """Validate export paths before creating any output files."""
        normalized_paths: dict[tuple[str, ...], str] = {}
        normalized_directories: dict[tuple[str, ...], tuple[str, ...]] = {}
        for relative_path, _file_info in raw_files.items():
            _resolve_export_relative_path(relative_path)
            components = tuple(relative_path.split("/"))
            normalized = tuple(
                unicodedata.normalize("NFC", component).casefold()
                if os.name == "nt"
                else unicodedata.normalize("NFC", component)
                for component in components
            )
            previous = normalized_paths.get(normalized)
            if previous is not None and previous != relative_path:
                raise DeviceWriteSafetyError(
                    f"The backup contains export paths that collide on this "
                    f"computer: {previous!r} and {relative_path!r}."
                )
            normalized_paths[normalized] = relative_path
            for depth in range(1, len(components)):
                normalized_directory = normalized[:depth]
                actual_directory = components[:depth]
                previous_directory = normalized_directories.get(normalized_directory)
                if (
                    previous_directory is not None
                    and previous_directory != actual_directory
                ):
                    raise DeviceWriteSafetyError(
                        "The backup contains directory names that alias each "
                        f"other during export: {'/'.join(previous_directory)!r} "
                        f"and {'/'.join(actual_directory)!r}."
                    )
                normalized_directories[normalized_directory] = actual_directory
        normalized_file_paths = set(normalized_paths)
        for normalized, relative_path in normalized_paths.items():
            if any(
                normalized[:depth] in normalized_file_paths
                for depth in range(1, len(normalized))
            ):
                raise DeviceWriteSafetyError(
                    f"The backup path {relative_path!r} is nested beneath another file."
                )
        return raw_files

    @staticmethod
    def _create_export_directory(parent: Path, snapshot_id: str) -> Path:
        base_name = f"iOpenPod Export - {snapshot_id}"
        for suffix in range(1, 10_000):
            name = base_name if suffix == 1 else f"{base_name} ({suffix})"
            candidate = parent / name
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            return candidate
        raise DeviceWriteSafetyError(
            "Could not create a unique export folder in the selected location."
        )

    @_repository_locked
    def _restore_backup_from_snapshot(
        self,
        snapshot_id: str,
        ipod_path: str | Path,
        progress_callback: Callable[[BackupProgress], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        *,
        reported_volume_format: str = "",
        expected_volume_identity_key: str = "",
        allow_unverified_device: bool = False,
        _expected_current_state: _SnapshotState | None = None,
    ) -> bool:
        """Restore a snapshot with the existing delete-then-delta-copy phases."""
        if not self.identity_is_stable and not allow_unverified_device:
            raise DeviceWriteSafetyError(
                "Restore requires a stable hardware serial number or FireWire "
                "GUID for the connected iPod. iOpenPod refused to use a mount "
                "name or drive letter as destructive-write authorization."
            )
        ipod_root = Path(os.path.realpath(ipod_path))
        filesystem_profile = inspect_device_write_readiness(
            ipod_root,
            reported_volume_format=reported_volume_format,
        )
        _ensure_backup_destination_is_separate(
            ipod_root,
            self.backup_root,
            filesystem_profile,
        )
        current_volume_key = volume_lock_key(filesystem_profile)
        if (
            expected_volume_identity_key
            and current_volume_key != expected_volume_identity_key
        ):
            raise DeviceWriteSafetyError(
                "A different volume is mounted at the selected iPod path. "
                "iOpenPod stopped before restoring the backup."
            )

        self._migrate_device_blobs()
        manifest = self._load_manifest(snapshot_id)
        if not manifest:
            logger.error("Snapshot %s not found", snapshot_id)
            return False
        raw_files = _validated_manifest_entries(
            manifest,
            expected_snapshot_id=snapshot_id,
            expected_device_id=self.device_id,
        )
        if (
            manifest.get("identity_is_stable") is False
            and not allow_unverified_device
        ):
            raise DeviceWriteSafetyError(
                "This snapshot was created without a stable hardware identity. "
                "Automatic destructive restore is disabled to protect other iPods."
            )

        if progress_callback:
            progress_callback(BackupProgress(
                "verifying",
                0,
                0,
                message="Verifying backup integrity…",
            ))
        try:
            target_files = self._validated_restore_files(
                ipod_root,
                raw_files,
                filesystem_profile=filesystem_profile,
                progress_callback=progress_callback,
                is_cancelled=is_cancelled,
            )
        except _BackupOperationCancelled:
            logger.info("Restore cancelled while verifying backup blobs")
            return False

        logger.info(
            "Restore: %s files from snapshot %s",
            len(target_files),
            snapshot_id,
        )
        guard_context = (
            nullcontext(self._active_device_guard)
            if self._active_device_guard is not None
            else DeviceWriteGuard(
                ipod_root,
                volume_key=current_volume_key,
            )
        )
        with guard_context as write_guard:
            session = _RestoreWriteSession(
                ipod_root,
                filesystem_profile,
                write_guard=write_guard,
            )
            session.revalidate(probe_case_sensitivity=True)
            _validate_restore_target_names(
                target_files,
                session.filesystem_profile,
            )
            try:
                result = self._restore_backup_guarded(
                    target_files,
                    session,
                    progress_callback=progress_callback,
                    is_cancelled=is_cancelled,
                    expected_current_state=_expected_current_state,
                )
            except Exception as exc:
                if isinstance(exc, RestoreDurabilityPendingError):
                    raise
                finalize_error: Exception | None = None
                if session.device_dirty and not session.finalize_attempted:
                    try:
                        session.finalize()
                    except Exception as flush_exc:
                        finalize_error = flush_exc
                        logger.exception(
                            "Restore failed and its emergency flush also failed"
                        )
                if session.device_dirty:
                    detail = (
                        f" The final filesystem flush also failed: {finalize_error}."
                        if finalize_error is not None
                        else ""
                    )
                    raise RestoreIncompleteError(
                        "The restore stopped after changing files on the iPod."
                        f"{detail} The selected backup is still safe on the "
                        "computer. Reconnect the same iPod if needed, then run "
                        "this restore again before syncing or using it."
                    ) from exc
                raise
            else:
                if session.device_dirty and not session.finalize_attempted:
                    session.finalize()
                return result

    def _validated_restore_files(
        self,
        ipod_root: Path,
        raw_files: dict[str, dict],
        *,
        filesystem_profile: FilesystemProfile,
        progress_callback: Callable[[BackupProgress], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> dict[str, _RestoreFile]:
        result: dict[str, _RestoreFile] = {}
        verified_blobs: set[str] = set()
        total_files = len(raw_files)
        for index, (raw_relative_path, raw_info) in enumerate(
            raw_files.items(),
            start=1,
        ):
            if is_cancelled and is_cancelled():
                raise _BackupOperationCancelled
            if not isinstance(raw_relative_path, str):
                raise DeviceWriteSafetyError(
                    "The backup manifest contains a non-text file path."
                )
            raw_components = tuple(raw_relative_path.split("/"))
            if (
                os.name == "nt"
                and any("\\" in component for component in raw_components)
            ):
                raise DeviceWriteSafetyError(
                    f"The backup path {raw_relative_path!r} cannot be represented "
                    "losslessly on Windows. iOpenPod stopped before changing the iPod."
                )
            if (
                filesystem_profile.filesystem_type.casefold() in _FAT_FILESYSTEMS
                and any(
                    any(ord(character) < 32 for character in component)
                    or any(character in '<>:"/\\|?*' for character in component)
                    or component.endswith((" ", "."))
                    or component.split(".", 1)[0].rstrip(" .").casefold()
                    in _WINDOWS_RESERVED_STEMS
                    for component in raw_components
                )
            ):
                raise DeviceWriteSafetyError(
                    f"The backup path {raw_relative_path!r} cannot be represented "
                    "safely on this iPod filesystem."
                )
            target = _resolve_restore_path(ipod_root, raw_relative_path)
            relative_path = target.relative_to(ipod_root).as_posix()
            if relative_path in result:
                raise DeviceWriteSafetyError(
                    f"The backup contains colliding file paths: {relative_path!r}."
                )
            if not isinstance(raw_info, dict):
                raise DeviceWriteSafetyError(
                    f"The backup entry for {relative_path!r} is invalid."
                )
            file_hash = raw_info.get("hash")
            size = raw_info.get("size")
            mtime_ns = raw_info.get("mtime_ns")
            if not isinstance(file_hash, str) or not _SHA256_RE.fullmatch(file_hash):
                raise DeviceWriteSafetyError(
                    f"The backup entry for {relative_path!r} has an invalid SHA-256 hash."
                )
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise DeviceWriteSafetyError(
                    f"The backup entry for {relative_path!r} has an invalid file size."
                )
            if (
                mtime_ns is not None
                and (
                    isinstance(mtime_ns, bool)
                    or not isinstance(mtime_ns, int)
                    or mtime_ns < 0
                )
            ):
                raise DeviceWriteSafetyError(
                    f"The backup entry for {relative_path!r} has an invalid "
                    "modification time."
                )
            normalized_hash = file_hash.casefold()
            blob_path = self._blob_path(normalized_hash)
            try:
                blob_size = blob_path.stat().st_size
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"The backup blob for {relative_path!r} is unavailable: {exc}"
                ) from exc
            if blob_size != size:
                raise DeviceWriteSafetyError(
                    f"The backup blob for {relative_path!r} has the wrong size."
                )
            if normalized_hash not in verified_blobs:
                try:
                    actual_hash = _hash_file(blob_path)
                except OSError as exc:
                    raise DeviceWriteSafetyError(
                        f"The backup blob for {relative_path!r} could not be verified: {exc}"
                    ) from exc
                if actual_hash != normalized_hash:
                    raise DeviceWriteSafetyError(
                        f"The backup blob for {relative_path!r} failed SHA-256 verification."
                    )
                verified_blobs.add(normalized_hash)

            result[relative_path] = _RestoreFile(
                relative_path=relative_path,
                file_hash=normalized_hash,
                size=size,
                mtime_ns=mtime_ns,
                blob_path=blob_path,
            )
            if progress_callback:
                progress_callback(BackupProgress(
                    "verifying",
                    index,
                    total_files,
                    current_file=relative_path,
                    message=(
                        f"Verifying backup file {index:,}/{total_files:,}: "
                        f"{relative_path}"
                    ),
                ))

        file_paths = set(result)
        for relative_path in result:
            parts = relative_path.split("/")
            if any(
                "/".join(parts[:depth]) in file_paths
                for depth in range(1, len(parts))
            ):
                raise DeviceWriteSafetyError(
                    f"The backup path {relative_path!r} is nested beneath another file."
                )
        return result

    def _restore_backup_guarded(
        self,
        target_files: dict[str, _RestoreFile],
        session: _RestoreWriteSession,
        *,
        progress_callback: Callable[[BackupProgress], None] | None,
        is_cancelled: Callable[[], bool] | None,
        expected_current_state: _SnapshotState | None,
    ) -> bool:
        if progress_callback:
            progress_callback(BackupProgress(
                "scanning",
                0,
                0,
                message="Enumerating and verifying iPod files…",
            ))
        ipod_files = self._walk_device(session.mount_path, fail_on_error=True)
        current_hashes: dict[str, str] = {}
        current_state: _SnapshotState = {}
        scanned_cache_keys: set[str] = set()
        total_current = len(ipod_files)
        for index, (relative_path, full_path) in enumerate(ipod_files, start=1):
            if is_cancelled and is_cancelled():
                logger.info("Restore cancelled during scan")
                return False
            session.revalidate()
            try:
                before = full_path.stat()
                cache_key = _file_state_key(relative_path, before)
                file_hash = _hash_file(full_path)
                after = full_path.stat()
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not verify existing iPod file {relative_path}: {exc}"
                ) from exc
            if _file_state_key(relative_path, after) != cache_key:
                raise DeviceWriteSafetyError(
                    f"The iPod file {relative_path} changed while restore was "
                    "verifying it. iOpenPod stopped before changing the device."
                )
            current_hashes[relative_path] = file_hash
            current_state[relative_path] = (
                file_hash,
                after.st_size,
                after.st_mtime_ns,
            )
            scanned_cache_keys.add(cache_key)
            if progress_callback and (index == total_current or index % 10 == 0):
                progress_callback(BackupProgress(
                    "scanning",
                    index,
                    total_current,
                    current_file=relative_path,
                    message=f"Verifying {index:,}/{total_current:,} iPod files…",
                ))
        session.revalidate()

        target_keys = set(target_files)
        current_keys = set(current_hashes)
        to_add = target_keys - current_keys
        to_remove = current_keys - target_keys
        to_replace = {
            path
            for path in target_keys & current_keys
            if target_files[path].file_hash != current_hashes[path]
        }
        to_copy = to_add | to_replace
        skipped = len(target_keys & current_keys) - len(to_replace)
        logger.info(
            "Restore delta: %s add, %s replace, %s remove, %s unchanged",
            len(to_add),
            len(to_replace),
            len(to_remove),
            skipped,
        )

        self._preflight_restore_capacity(
            target_files,
            to_copy,
            to_remove,
            to_replace,
            session,
        )
        if session.write_guard is not None:
            session.write_guard.assert_database_unchanged()
        session.revalidate()
        if (
            expected_current_state is not None
            and current_state != expected_current_state
        ):
            raise DeviceWriteSafetyError(
                "The iPod changed after its safety checkpoint was captured. "
                "iOpenPod stopped before erasing anything; try the restore again "
                "after closing other device-management apps."
            )
        try:
            final_files = self._walk_device(
                session.mount_path,
                fail_on_error=True,
            )
            final_cache_keys = {
                _file_state_key(relative_path, full_path.stat())
                for relative_path, full_path in final_files
            }
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"The iPod became unreadable before restore commit: {exc}"
            ) from exc
        if final_cache_keys != scanned_cache_keys:
            raise DeviceWriteSafetyError(
                "The iPod filesystem changed during restore verification. "
                "iOpenPod stopped before erasing anything."
            )

        # Cancellation is safe through verification and preflight because the
        # iPod has not changed yet. Once commit begins, finish the verified
        # plan so a user click cannot deliberately leave a half-restored iPod.
        if is_cancelled and is_cancelled():
            logger.info("Restore cancelled before device changes began")
            return False
        mutation_count = len(to_remove) + len(to_copy)
        if progress_callback:
            progress_callback(BackupProgress(
                "committing",
                0,
                max(mutation_count, 1),
                message=(
                    "Applying the verified restore safely. "
                    "This phase cannot be cancelled."
                ),
            ))

        if to_remove and progress_callback:
            progress_callback(BackupProgress(
                "cleaning",
                0,
                len(to_remove),
                message=f"Removing {len(to_remove)} files…",
            ))
        for index, relative_path in enumerate(sorted(to_remove), start=1):
            session.delete(relative_path)
            session.remove_empty_parents(relative_path)
            if progress_callback:
                progress_callback(BackupProgress(
                    "cleaning",
                    index,
                    len(to_remove),
                    current_file=relative_path,
                    message=f"Removing {index}/{len(to_remove)}: {relative_path}",
                ))

        for index, relative_path in enumerate(sorted(to_copy), start=1):
            session.install(target_files[relative_path])
            if progress_callback:
                progress_callback(BackupProgress(
                    "restoring",
                    index,
                    len(to_copy),
                    current_file=relative_path,
                    message=f"Copying {index}/{len(to_copy)}: {relative_path}",
                ))

        self._finalize_restored_tree(
            target_files,
            session,
            progress_callback=progress_callback,
        )
        session.finalize()
        logger.info(
            "Restore complete: +%s add, ~%s replace, −%s remove, %s skipped",
            len(to_add),
            len(to_replace),
            len(to_remove),
            skipped,
        )
        if progress_callback:
            parts = []
            if to_add:
                parts.append(f"+{len(to_add)} added")
            if to_replace:
                parts.append(f"~{len(to_replace)} replaced")
            if to_remove:
                parts.append(f"−{len(to_remove)} removed")
            parts.append(f"{skipped} unchanged")
            progress_callback(BackupProgress(
                "complete",
                len(target_files),
                len(target_files),
                message=f"Restore complete — {', '.join(parts)}",
            ))
        return True

    def _preflight_restore_capacity(
        self,
        target_files: dict[str, _RestoreFile],
        to_copy: set[str],
        to_remove: set[str],
        to_replace: set[str],
        session: _RestoreWriteSession,
    ) -> None:
        for relative_path in sorted(to_copy):
            restore_file = target_files[relative_path]
            session.validate_target(relative_path, restore_file.size)

        session.revalidate()
        try:
            free_now = shutil.disk_usage(session.mount_path).free
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"Could not verify iPod free space before restore: {exc}"
            ) from exc
        allocation_unit = session.filesystem_profile.allocation_unit_size
        freed_by_removals = 0
        for relative_path in to_remove:
            target = _resolve_restore_path(session.mount_path, relative_path)
            try:
                freed_by_removals += existing_file_allocated_size(
                    target,
                    allocation_unit,
                )
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not inspect {relative_path} before restore: {exc}"
                ) from exc

        consumed = 0
        peak_required = 0
        for relative_path in sorted(to_copy):
            new_size = allocated_size(target_files[relative_path].size, allocation_unit)
            old_size = 0
            if relative_path in to_replace:
                target = _resolve_restore_path(session.mount_path, relative_path)
                try:
                    old_size = existing_file_allocated_size(
                        target,
                        allocation_unit,
                    )
                except OSError as exc:
                    raise DeviceWriteSafetyError(
                        f"Could not inspect {relative_path} before replacement: {exc}"
                    ) from exc
            peak_required = max(peak_required, consumed + new_size)
            consumed += new_size - old_size

        if free_now + freed_by_removals < peak_required:
            raise DeviceWriteSafetyError(
                "The iPod does not have enough free space for the restore's "
                "atomic temporary files. iOpenPod stopped before deleting anything."
            )

    def _finalize_restored_tree(
        self,
        target_files: dict[str, _RestoreFile],
        session: _RestoreWriteSession,
        *,
        progress_callback: Callable[[BackupProgress], None] | None,
    ) -> None:
        session.revalidate()
        restored_files = self._walk_device(session.mount_path, fail_on_error=True)
        total_files = len(restored_files)
        if progress_callback:
            progress_callback(BackupProgress(
                "finalizing",
                0,
                total_files,
                message=(
                    "Checking the restored file list and metadata. "
                    "This phase cannot be cancelled."
                ),
            ))
        restored_paths = {relative_path for relative_path, _path in restored_files}
        if restored_paths != set(target_files):
            missing = sorted(set(target_files) - restored_paths)
            extra = sorted(restored_paths - set(target_files))
            detail = missing[0] if missing else extra[0]
            raise DeviceWriteSafetyError(
                f"The restored iPod does not match the backup manifest: {detail}."
            )
        for index, (relative_path, full_path) in enumerate(
            restored_files,
            start=1,
        ):
            session.revalidate()
            try:
                actual_size = full_path.stat().st_size
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not inspect restored file {relative_path}: {exc}"
                ) from exc
            if actual_size != target_files[relative_path].size:
                raise DeviceWriteSafetyError(
                    f"The restored file {relative_path} has the wrong size."
                )
            session.apply_metadata(target_files[relative_path])
            if progress_callback:
                progress_callback(BackupProgress(
                    "finalizing",
                    index,
                    total_files,
                    current_file=relative_path,
                    message=(
                        f"Finalizing {index:,}/{total_files:,}: "
                        f"{relative_path}"
                    ),
                ))
        session.revalidate()

    def list_snapshots(self) -> list[SnapshotInfo]:
        """
        List all available snapshots for this device, newest first.

        Computes delta stats (files added/removed/changed) vs the
        previous snapshot for each entry.

        Optimised: only loads the full ``files`` dict for adjacent pairs
        that need delta computation, and discards them immediately to
        keep memory pressure low on large libraries.
        """
        _ensure_repository_path_safe(self.backup_root, self.snapshots_dir)
        if not self.snapshots_dir.exists():
            return []

        manifest_paths = sorted(
            self.snapshots_dir.glob("*.json"),
            key=_manifest_order_key,
            reverse=True,
        )

        if not manifest_paths:
            return []

        # ── Build SnapshotInfo list ─────────────────────────────────
        #
        # Load manifests lazily one at a time for delta computation.
        # Each iteration loads the current manifest, extracts its file
        # dict for delta computation with the *previous* iteration,
        # then discards the file dict.  At most TWO file dicts are
        # in memory at once.
        snapshots: list[SnapshotInfo] = []
        prev_files: dict | None = None   # files dict of the "newer" snapshot

        for mf in manifest_paths:
            try:
                with open(mf, encoding="utf-8") as f:
                    data = json.load(f)
                cur_files = _validated_manifest_entries(
                    data,
                    expected_snapshot_id=mf.stem,
                    expected_device_id=self.device_id,
                )
            except (
                DeviceWriteSafetyError,
                json.JSONDecodeError,
                UnicodeDecodeError,
                OSError,
            ) as exc:
                logger.warning("Could not validate snapshot %s: %s", mf.name, exc)
                snapshots.append(
                    SnapshotInfo(
                        id=mf.stem,
                        timestamp=mf.stem,
                        device_id=self.device_id,
                        device_name=self.device_name or "iPod",
                        is_valid=False,
                        validation_error=str(exc),
                    )
                )
                prev_files = None
                continue

            info = SnapshotInfo(
                id=mf.stem,
                timestamp=str(data.get("timestamp", "") or mf.stem),
                device_id=self.device_id,
                device_name=str(data.get("device_name", "iPod") or "iPod"),
                file_count=int(data["file_count"]),
                total_size=int(data["total_size"]),
                reason=str(data.get("reason", "manual") or "manual"),
                note=str(data.get("note", "") or "")[:_MAX_SNAPSHOT_NOTE_LENGTH],
                device_meta=(
                    data.get("device_meta", {})
                    if isinstance(data.get("device_meta", {}), dict)
                    else {}
                ),
            )

            # Delta: compare *previous* SnapshotInfo (newer) against this one
            if prev_files is not None:
                # prev_files is the *newer* snapshot, cur_files the *older*
                snapshots[-1].files_added, snapshots[-1].files_removed, snapshots[-1].files_changed = (
                    self._compute_delta(cur_files, prev_files)
                )

            # Keep only the files dict, drop the full manifest to free memory
            prev_files = cur_files
            del data

            snapshots.append(info)

        return snapshots

    @_repository_locked
    def garbage_collect(self):
        """Remove blob files not referenced by any snapshot."""
        self._migrate_device_blobs()
        self._gc_blobs()

    @_repository_locked
    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot and garbage-collect unreferenced blobs."""
        self._migrate_device_blobs()
        if not _SNAPSHOT_ID_RE.fullmatch(snapshot_id):
            logger.warning("Rejected invalid snapshot ID for deletion: %r", snapshot_id)
            return False
        manifest_path = self._snapshot_manifest_path(snapshot_id)
        if not manifest_path.exists():
            logger.warning(f"Snapshot {snapshot_id} not found for deletion")
            return False

        try:
            with open(manifest_path, encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
            _validated_manifest_entries(
                manifest,
                expected_snapshot_id=snapshot_id,
                expected_device_id=self.device_id,
            )
        except (
            DeviceWriteSafetyError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            OSError,
        ) as exc:
            logger.error(
                "Refusing to delete invalid snapshot catalog %s: %s",
                snapshot_id,
                exc,
            )
            return False

        try:
            durable_unlink(manifest_path)
            logger.info(f"Deleted snapshot {snapshot_id}")
        except OSError as e:
            logger.error(f"Could not delete snapshot {snapshot_id}: {e}")
            return False

        # Garbage collect unreferenced blobs
        self._gc_blobs()
        return True

    @_repository_locked
    def update_device_metadata(
        self,
        *,
        device_name: str | None = None,
        device_meta: dict | None = None,
    ) -> int:
        """Refresh display metadata while holding the archive writer lock."""
        return self._update_device_metadata_unlocked(
            device_name=device_name,
            device_meta=device_meta,
        )

    def _update_device_metadata_unlocked(
        self,
        *,
        device_name: str | None = None,
        device_meta: dict | None = None,
    ) -> int:
        """Refresh device display metadata in existing snapshot manifests.

        Snapshot manifests store the display name so they can be shown without
        the device connected. When the iPod's name changes, update those
        manifests in place instead of waiting for the next content-changing
        snapshot.

        Returns the number of manifest files updated.
        """
        _ensure_repository_path_safe(self.backup_root, self.snapshots_dir)
        name = str(device_name if device_name is not None else self.device_name).strip()
        meta = self.device_meta if device_meta is None else (device_meta or {})
        should_update_meta = bool(meta)

        if not name and not should_update_meta:
            return 0
        if not self.snapshots_dir.exists():
            return 0

        updated = 0
        for manifest_path in sorted(self.snapshots_dir.glob("*.json")):
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
                _validated_manifest_entries(
                    manifest,
                    expected_snapshot_id=manifest_path.stem,
                    expected_device_id=self.device_id,
                )
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
                logger.warning("Could not read snapshot %s for metadata refresh: %s", manifest_path.name, exc)
                continue
            except DeviceWriteSafetyError as exc:
                logger.warning(
                    "Could not validate snapshot %s for metadata refresh: %s",
                    manifest_path.name,
                    exc,
                )
                continue

            changed = False
            if name and manifest.get("device_name") != name:
                manifest["device_name"] = name
                changed = True
            if should_update_meta and manifest.get("device_meta", {}) != meta:
                manifest["device_meta"] = meta
                changed = True
            if not changed:
                continue
            if int(manifest.get("version", 0) or 0) >= 3:
                manifest["manifest_sha256"] = _manifest_digest(manifest)

            tmp_path: Path | None = None
            try:
                tmp_path, manifest_file = open_unique_sibling_temp(
                    manifest_path,
                    mode="w",
                    encoding="utf-8",
                )
                with manifest_file as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)
                    flush_written_file(f)
                durable_replace(tmp_path, manifest_path)
                updated += 1
            except OSError as exc:
                logger.warning("Could not refresh metadata for snapshot %s: %s", manifest_path.name, exc)
                try:
                    if tmp_path is not None:
                        tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        if updated:
            logger.info("Updated device metadata in %s backup manifest(s) for %s", updated, self.device_id)
        return updated

    def get_backup_size(self) -> int:
        """Get total size of this device's backup data.

        Counts manifest/cache files directly, plus the size of all blobs
        referenced by this device's snapshots (shared blobs counted in full
        since they are required for restore).
        """
        _ensure_repository_path_safe(self.backup_root, self.device_dir)
        _ensure_repository_path_safe(self.backup_root, self.snapshots_dir)
        if not self.device_dir.exists():
            return 0

        total = 0
        # Per-device manifests and metadata
        for root, _dirs, files in os.walk(self.device_dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass

        # Referenced blobs
        referenced: set[str] = set()
        if self.snapshots_dir.exists():
            for mf in self.snapshots_dir.glob("*.json"):
                try:
                    with open(mf, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                    continue
                for file_info in data.get("files", {}).values():
                    h = file_info.get("hash")
                    if h:
                        referenced.add(h)

        for h in referenced:
            bp = self._blob_path(h)
            try:
                total += bp.stat().st_size
            except OSError:
                pass

        return total

    def has_snapshots(self) -> bool:
        """Quick check if any snapshots exist for this device."""
        _ensure_repository_path_safe(self.backup_root, self.snapshots_dir)
        if not self.snapshots_dir.exists():
            return False
        return any(self.snapshots_dir.glob("*.json"))

    @classmethod
    def list_all_devices(cls, backup_dir: str = "") -> list[dict]:
        """List all devices that have backups, without requiring a connected device.

        Returns a list of dicts:
            [{"device_id": str, "device_name": str, "snapshot_count": int,
              "device_meta": dict}]
        """
        root = Path(os.path.realpath(backup_dir or _DEFAULT_BACKUP_DIR))
        if not root.exists():
            return []

        devices: list[dict] = []
        for child in sorted(root.iterdir()):
            _ensure_repository_path_safe(root, child)
            if not child.is_dir():
                continue
            # Skip the shared blobs directory
            if child.name == "blobs":
                continue
            snap_dir = child / "snapshots"
            _ensure_repository_path_safe(root, snap_dir)
            if not snap_dir.is_dir():
                continue
            manifests = sorted(
                snap_dir.glob("*.json"),
                key=_manifest_order_key,
                reverse=True,
            )
            if not manifests:
                continue

            # Read device_name and device_meta from the latest manifest
            device_name = child.name
            device_meta: dict = {}
            identity_is_stable = False
            for manifest_path in manifests:
                _ensure_repository_path_safe(root, manifest_path)
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        data = json.load(f)
                    _validated_manifest_entries(
                        data,
                        expected_snapshot_id=manifest_path.stem,
                        expected_device_id=child.name,
                    )
                except (
                    DeviceWriteSafetyError,
                    json.JSONDecodeError,
                    UnicodeDecodeError,
                    OSError,
                ):
                    continue
                device_name = str(data.get("device_name", child.name) or child.name)
                device_meta = (
                    data.get("device_meta", {})
                    if isinstance(data.get("device_meta", {}), dict)
                    else {}
                )
                identity_is_stable = bool(data.get("identity_is_stable", False))
                break

            devices.append({
                "device_id": child.name,
                "device_name": device_name,
                "snapshot_count": len(manifests),
                "device_meta": device_meta,
                "identity_is_stable": identity_is_stable,
            })

        return devices

    # ── Internal helpers ────────────────────────────────────────────────────

    def _next_snapshot_sequence(self) -> int:
        """Return a monotonic per-device sequence while the archive lock is held."""
        _ensure_repository_path_safe(self.backup_root, self.snapshots_dir)
        highest = 0
        if not self.snapshots_dir.exists():
            return 1
        for manifest_path in self.snapshots_dir.glob("*.json"):
            _ensure_repository_path_safe(self.backup_root, manifest_path)
            try:
                with open(manifest_path, encoding="utf-8") as manifest_file:
                    manifest = json.load(manifest_file)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                continue
            sequence = manifest.get("sequence")
            if (
                not isinstance(sequence, bool)
                and isinstance(sequence, int)
                and sequence > highest
            ):
                highest = sequence
        return highest + 1

    def _get_latest_snapshot_files(self) -> dict | None:
        """Load the files dict from the most recent snapshot, or None."""
        _ensure_repository_path_safe(self.backup_root, self.snapshots_dir)
        if not self.snapshots_dir.exists():
            return None
        manifests = sorted(
            self.snapshots_dir.glob("*.json"),
            key=_manifest_order_key,
            reverse=True,
        )
        if not manifests:
            return None
        try:
            with open(manifests[0], encoding="utf-8") as f:
                data = json.load(f)
            return _validated_manifest_entries(
                data,
                expected_snapshot_id=manifests[0].stem,
                expected_device_id=self.device_id,
            )
        except (
            DeviceWriteSafetyError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            OSError,
        ):
            return None

    def _walk_device(
        self,
        ipod_root: Path,
        *,
        fail_on_error: bool = False,
    ) -> list[tuple[str, Path]]:
        """
        Walk the entire iPod root and return (relative_path, full_path) pairs.

        Skips OS-managed directories (case-insensitive). Dot-directories like
        .iOpenPod are kept — only the explicit exclusion set is filtered.
        """
        results: list[tuple[str, Path]] = []
        virtual_marker = ipod_root / "iPodInfo.json"
        is_virtual_ipod = virtual_marker.is_file()

        def _raise_walk_error(exc: OSError) -> None:
            raise exc

        for root, dirs, files in os.walk(
            ipod_root,
            followlinks=False,
            onerror=_raise_walk_error if fail_on_error else None,
        ):
            # Filter out OS-managed directories in-place (single pass)
            dirs[:] = [d for d in dirs if not _is_excluded(d)]

            if fail_on_error:
                for dirname in dirs:
                    directory = Path(root) / dirname
                    if directory.is_symlink():
                        raise DeviceWriteSafetyError(
                            f"Restore stopped because {directory} is a symbolic link."
                        )

            for filename in files:
                if _is_excluded(filename):
                    continue

                full_path = Path(root) / filename
                if is_virtual_ipod and full_path == virtual_marker:
                    continue

                # Skip symlinks — avoid following links outside the device,
                # and iPod filesystems (FAT32/exFAT) don't support them anyway.
                if full_path.is_symlink():
                    if fail_on_error:
                        raise DeviceWriteSafetyError(
                            f"Restore stopped because {full_path} is a symbolic link."
                        )
                    continue

                try:
                    rel_path = full_path.relative_to(ipod_root).as_posix()
                except ValueError:
                    continue

                results.append((rel_path, full_path))

        return results

    def _hash_file(self, path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_HASH_BUF_SIZE)
                if not chunk:
                    break
                sha.update(chunk)
        return sha.hexdigest()

    def _blob_path(self, file_hash: str) -> Path:
        """Get the storage path for a blob by its hash."""
        if not isinstance(file_hash, str) or not _SHA256_RE.fullmatch(file_hash):
            raise DeviceWriteSafetyError("The backup contains an invalid blob hash.")
        normalized_hash = file_hash.casefold()
        blob_path = self.blobs_dir / normalized_hash[:2] / normalized_hash
        _ensure_repository_path_safe(self.backup_root, blob_path)
        return blob_path

    def _snapshot_manifest_path(self, snapshot_id: str) -> Path:
        if not _SNAPSHOT_ID_RE.fullmatch(snapshot_id):
            raise DeviceWriteSafetyError("The selected backup snapshot ID is invalid.")
        manifest_path = self.snapshots_dir / f"{snapshot_id}.json"
        _ensure_repository_path_safe(self.backup_root, manifest_path)
        return manifest_path

    def _store_blob(
        self,
        source_path: Path,
        file_hash: str,
        *,
        verify_existing: bool = True,
    ) -> bool:
        """
        Store a file as a blob if it doesn't already exist.

        Thread-safe: uses copy-to-temp + atomic rename so concurrent
        threads writing the same hash don't corrupt each other.

        Returns True if a new blob was created, False if it already existed.
        """
        blob_path = self._blob_path(file_hash)
        if blob_path.exists():
            try:
                blob_size = blob_path.stat().st_size
                source_size = source_path.stat().st_size
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not verify the existing backup blob for {source_path}: {exc}"
                ) from exc
            if blob_size == source_size and (
                not verify_existing or _hash_file(blob_path) == file_hash
            ):
                return False
            logger.warning(
                "Repairing corrupt content-addressed blob %s from verified source %s",
                file_hash,
                source_path,
            )

        blob_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a per-thread temp file, then atomically move into place.
        # If two threads race on the same hash the second os.replace is a
        # harmless overwrite (same content, same hash).
        fd, tmp_path = tempfile.mkstemp(
            dir=str(blob_path.parent), prefix=".blob_",
        )
        temp_path = Path(tmp_path)
        try:
            with open(source_path, "rb") as source, os.fdopen(fd, "wb") as destination:
                fd = -1
                shutil.copyfileobj(source, destination, _HASH_BUF_SIZE)
                flush_written_file(destination)
            if _hash_file(temp_path) != file_hash:
                raise DeviceWriteSafetyError(
                    f"The iPod file {source_path} changed while it was being "
                    "captured. iOpenPod discarded the incomplete snapshot."
                )
            durable_replace(temp_path, blob_path)
            return True
        except Exception as e:
            logger.error(f"Failed to store blob {file_hash[:16]}…: {e}")
            if fd >= 0:
                os.close(fd)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _load_manifest(self, snapshot_id: str) -> dict | None:
        """Load a snapshot manifest by its ID."""
        manifest_path = self._snapshot_manifest_path(snapshot_id)
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            logger.error(f"Could not read snapshot {snapshot_id}: {e}")
            return None

    def _migrate_device_blobs(self):
        """One-time migration: move per-device blobs to the shared store.

        Old layout had blobs at <device_dir>/blobs/. If that directory exists,
        move all blobs to <backup_root>/blobs/ and remove the old directory.
        """
        old_blobs = self.device_dir / "blobs"
        _ensure_repository_path_safe(self.backup_root, old_blobs)
        _ensure_repository_path_safe(self.backup_root, self.blobs_dir)
        if not old_blobs.exists() or not old_blobs.is_dir():
            return

        # Ensure shared blobs dir exists
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        migrated = 0

        for prefix_dir in old_blobs.iterdir():
            _ensure_repository_path_safe(self.backup_root, prefix_dir)
            if not prefix_dir.is_dir():
                continue
            for blob_file in prefix_dir.iterdir():
                _ensure_repository_path_safe(self.backup_root, blob_file)
                file_hash = blob_file.name.casefold()
                if (
                    not blob_file.is_file()
                    or not _SHA256_RE.fullmatch(file_hash)
                    or file_hash[:2] != prefix_dir.name.casefold()
                ):
                    logger.warning(
                        "Leaving unrecognized legacy backup entry in place: %s",
                        blob_file,
                    )
                    continue
                try:
                    if _hash_file(blob_file) != file_hash:
                        logger.error(
                            "Leaving corrupt legacy blob in place for recovery: %s",
                            blob_file,
                        )
                        continue
                    self._store_blob(
                        blob_file,
                        file_hash,
                        verify_existing=True,
                    )
                    if _hash_file(self._blob_path(file_hash)) != file_hash:
                        raise DeviceWriteSafetyError(
                            f"Migrated backup blob {file_hash} failed verification."
                        )
                    durable_unlink(blob_file)
                    migrated += 1
                except (OSError, DeviceWriteSafetyError) as exc:
                    logger.warning(
                        "Blob migration left %s untouched: %s",
                        blob_file,
                        exc,
                    )
            # Remove empty prefix dir
            try:
                prefix_dir.rmdir()
                flush_parent_directory(prefix_dir)
            except OSError:
                pass

        # Remove old blobs directory
        try:
            old_blobs.rmdir()
            flush_parent_directory(old_blobs)
        except OSError:
            pass

        if migrated:
            logger.info(f"Migrated {migrated} blobs from {self.device_id}/blobs/ to shared store")

    def _gc_blobs(self):
        """Garbage-collect blobs not referenced by any device's snapshots.

        Since the blob store is shared across all devices, we must scan
        every device's manifests before deciding a blob is unreferenced. If
        even one manifest cannot be read completely, garbage collection stops
        without deleting anything: an unreadable catalog must never cause
        otherwise recoverable backup data to be destroyed.
        """
        _ensure_repository_path_safe(self.backup_root, self.blobs_dir)
        if not self.blobs_dir.exists():
            return

        # Build set of all referenced hashes across ALL devices
        referenced: set[str] = set()
        for device_dir in self.backup_root.iterdir():
            _ensure_repository_path_safe(self.backup_root, device_dir)
            if not device_dir.is_dir() or device_dir.name == "blobs":
                continue
            snap_dir = device_dir / "snapshots"
            _ensure_repository_path_safe(self.backup_root, snap_dir)
            if not snap_dir.is_dir():
                continue
            for mf in snap_dir.glob("*.json"):
                _ensure_repository_path_safe(self.backup_root, mf)
                try:
                    with open(mf, encoding="utf-8") as f:
                        data = json.load(f)
                    files = _validated_manifest_entries(
                        data,
                        expected_snapshot_id=mf.stem,
                        expected_device_id=device_dir.name,
                    )
                except (
                    DeviceWriteSafetyError,
                    json.JSONDecodeError,
                    UnicodeDecodeError,
                    OSError,
                ) as exc:
                    logger.error(
                        "GC skipped because snapshot %s is not trustworthy: %s",
                        mf,
                        exc,
                    )
                    return
                for file_info in files.values():
                    file_hash = file_info["hash"]
                    referenced.add(file_hash.casefold())

        # Walk blobs and delete unreferenced ones
        removed = 0
        for prefix_dir in self.blobs_dir.iterdir():
            _ensure_repository_path_safe(self.backup_root, prefix_dir)
            if not prefix_dir.is_dir():
                continue
            for blob_file in prefix_dir.iterdir():
                _ensure_repository_path_safe(self.backup_root, blob_file)
                if blob_file.name not in referenced:
                    try:
                        blob_file.unlink()
                        removed += 1
                    except OSError:
                        pass
            # Remove empty prefix directories
            try:
                prefix_dir.rmdir()  # Only succeeds if empty
            except OSError:
                pass

        if removed:
            logger.info(f"GC: removed {removed} unreferenced blobs")

    def _prune_safety_checkpoints(
        self,
        *,
        preserve_snapshot_id: str,
        limit: int = _AUTOMATIC_SAFETY_CHECKPOINT_LIMIT,
    ) -> None:
        """Keep a bounded rolling set of automatic pre-restore checkpoints."""
        if limit <= 0:
            return
        _ensure_repository_path_safe(self.backup_root, self.snapshots_dir)
        if not self.snapshots_dir.exists():
            return

        safety_snapshots: list[Path] = []
        for manifest_path in self.snapshots_dir.glob("*.json"):
            _ensure_repository_path_safe(self.backup_root, manifest_path)
            try:
                with open(manifest_path, encoding="utf-8") as manifest_file:
                    manifest = json.load(manifest_file)
                _validated_manifest_entries(
                    manifest,
                    expected_snapshot_id=manifest_path.stem,
                    expected_device_id=self.device_id,
                )
            except (
                DeviceWriteSafetyError,
                json.JSONDecodeError,
                UnicodeDecodeError,
                OSError,
            ) as exc:
                logger.error(
                    "Safety-checkpoint retention skipped because %s is "
                    "unreadable: %s",
                    manifest_path,
                    exc,
                )
                return
            if manifest.get("reason") == "pre_restore_safety":
                safety_snapshots.append(manifest_path)

        safety_snapshots.sort(key=_manifest_order_key, reverse=True)
        preserved = next(
            (
                snapshot
                for snapshot in safety_snapshots
                if snapshot.stem == preserve_snapshot_id
            ),
            None,
        )
        keep: list[Path] = []
        if preserved is not None:
            keep.append(preserved)
        for snapshot in safety_snapshots:
            if snapshot in keep:
                continue
            if len(keep) >= limit:
                break
            keep.append(snapshot)
        keep_set = set(keep)

        pruned = 0
        for checkpoint in safety_snapshots:
            if checkpoint in keep_set:
                continue
            try:
                durable_unlink(checkpoint)
                pruned += 1
            except OSError as exc:
                logger.warning(
                    "Could not prune automatic safety checkpoint %s: %s",
                    checkpoint,
                    exc,
                )
        if pruned:
            logger.info(
                "Pruned %s old automatic safety checkpoints; retained %s",
                pruned,
                len(keep_set),
            )
            self._gc_blobs()

    def _prune_snapshots(
        self,
        max_count: int,
        *,
        preserve_snapshot_id: str = "",
    ):
        """Delete oldest snapshots beyond the configured max, then GC."""
        _ensure_repository_path_safe(self.backup_root, self.snapshots_dir)
        if not self.snapshots_dir.exists():
            return

        snapshot_paths = list(self.snapshots_dir.glob("*.json"))
        safety_snapshot_paths: set[Path] = set()
        for manifest_path in snapshot_paths:
            _ensure_repository_path_safe(self.backup_root, manifest_path)
            try:
                with open(manifest_path, encoding="utf-8") as manifest_file:
                    manifest = json.load(manifest_file)
                _validated_manifest_entries(
                    manifest,
                    expected_snapshot_id=manifest_path.stem,
                    expected_device_id=self.device_id,
                )
                if manifest.get("reason") == "pre_restore_safety":
                    safety_snapshot_paths.add(manifest_path)
            except (
                DeviceWriteSafetyError,
                json.JSONDecodeError,
                UnicodeDecodeError,
                OSError,
            ) as exc:
                logger.error(
                    "Snapshot retention skipped because %s is unreadable: %s",
                    manifest_path,
                    exc,
                )
                return

        snapshots = sorted(
            snapshot_paths,
            key=_manifest_order_key,
            reverse=True,
        )

        ordered_safety = [
            snapshot
            for snapshot in snapshots
            if snapshot in safety_snapshot_paths
        ]
        keep_set = set(
            ordered_safety[:_AUTOMATIC_SAFETY_CHECKPOINT_LIMIT]
        )
        preserved = next(
            (
                snapshot
                for snapshot in snapshots
                if snapshot.stem == preserve_snapshot_id
            ),
            None,
        )
        if preserved is not None:
            keep_set.add(preserved)

        regular_kept = int(
            preserved is not None
            and preserved not in safety_snapshot_paths
        )
        for snapshot in snapshots:
            if snapshot in keep_set or snapshot in safety_snapshot_paths:
                continue
            if regular_kept >= max_count:
                break
            keep_set.add(snapshot)
            regular_kept += 1

        pruned = 0
        for old_snapshot in snapshots:
            if old_snapshot in keep_set:
                continue
            try:
                durable_unlink(old_snapshot)
                pruned += 1
                logger.debug(f"Pruned old snapshot: {old_snapshot.stem}")
            except OSError as e:
                logger.warning(f"Could not prune snapshot {old_snapshot}: {e}")

        if pruned:
            logger.info(
                "Pruned %s old snapshots (keeping up to %s regular plus %s "
                "pre-restore safety checkpoints)",
                pruned,
                max_count,
                len(keep_set & safety_snapshot_paths),
            )
            self._gc_blobs()

    @staticmethod
    def _compute_delta(
        older_files: dict[str, dict],
        newer_files: dict[str, dict],
    ) -> tuple[int, int, int]:
        """
        Compute file delta between two *files* dicts (path → {hash, …}).

        Args:
            older_files: The files dict from the older snapshot.
            newer_files: The files dict from the newer snapshot.

        Returns:
            (files_added, files_removed, files_changed)
        """
        old_keys = set(older_files.keys())
        new_keys = set(newer_files.keys())

        added = len(new_keys - old_keys)
        removed = len(old_keys - new_keys)

        # Changed = same path but different hash
        changed = 0
        for key in old_keys & new_keys:
            if older_files[key].get("hash") != newer_files[key].get("hash"):
                changed += 1

        return added, removed, changed


# ── Module-level helpers ────────────────────────────────────────────────────

def get_device_identifier(
    ipod_path: str | Path,
    discovered_ipod=None,
    *,
    volume_identity_key: str = "",
) -> str:
    """
    Get a stable identifier for a device, suitable for backup directory naming.

    Only a hardware serial number or FireWire GUID is allowed to identify an
    archive across app sessions. All filesystem and mount evidence is scoped to
    the current selected-device session because it can be cloned or reused.
    """
    observed_volume_key = str(volume_identity_key or "").strip()
    if discovered_ipod:
        if getattr(discovered_ipod, "serial", ""):
            return discovered_ipod.serial
        if getattr(discovered_ipod, "firewire_guid", ""):
            return discovered_ipod.firewire_guid
        observed_volume_key = str(
            observed_volume_key
            or getattr(discovered_ipod, "volume_identity_key", "")
            or ""
        ).strip()

    if observed_volume_key:
        return _provisional_archive_identifier(
            observed_volume_key,
            session_owner=discovered_ipod,
        )

    # Last-resort namespace for source/dev fixtures where no scan-time volume
    # identity exists. The per-process token prevents a later app run from
    # reusing a drive letter or mount directory as if it were hardware identity.
    normalized_mount = os.path.normcase(os.path.realpath(ipod_path))
    if normalized_mount:
        return _provisional_archive_identifier(
            f"mount:{normalized_mount}",
            session_owner=discovered_ipod,
        )

    # ``realpath`` should never be empty, but preserve a safe non-empty ID if
    # an unusual host path implementation returns one.
    digest = hashlib.sha256(os.urandom(32)).hexdigest()
    return f"unidentified_session_{digest[:24]}"


def get_device_display_name(discovered_ipod=None, fallback: str = "iPod") -> str:
    """Get a human-readable device name for display in manifests.

    Prefers the user-assigned iPod name (from the master playlist title)
    when available, falling back to the model display name.
    """
    if discovered_ipod:
        ipod_name = getattr(discovered_ipod, "ipod_name", "")
        if ipod_name:
            return ipod_name
        return getattr(discovered_ipod, "display_name", fallback) or fallback
    return fallback
