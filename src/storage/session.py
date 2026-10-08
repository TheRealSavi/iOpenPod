"""Connection-bound, root-contained filesystem access."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import uuid
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, cast

from storage._filesystem import (
    COPY_CHUNK_SIZE,
    allocated_size,
    fingerprint_from_stat,
    flush_parent_directory,
    flush_written_file,
    is_link_or_reparse,
    open_read_no_follow,
    read_and_fingerprint,
    resolve_device_path,
)
from storage._filesystem import modified_time_matches as _modified_time_matches
from storage._writer_lock import VolumeWriterLease
from storage.errors import (
    ConcurrentModificationError,
    FilePreconditionError,
    FileSizeLimitError,
    MountInspectionError,
    ReadOnlyFilesystemError,
    RecoverableWriteError,
    SessionClosedError,
    SessionInvalidatedError,
    StorageCapacityError,
    StorageError,
    StorageOperationError,
    UnsafeFilesystemPathError,
    VolumeDisconnectedError,
    VolumeIdentityChangedError,
)
from storage.models import (
    AccessMode,
    ConnectionGeneration,
    CopyResult,
    DeviceEntry,
    DeviceEntryKind,
    FileFingerprint,
    FileIdentity,
    FileRangeSnapshot,
    FileSnapshot,
    FlushResult,
    MountedVolume,
    RecoveryWriteResult,
    TrashEntry,
    VolumeObservation,
    WriteResult,
)
from storage.paths import DevicePath, HostPath

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from types import TracebackType

    from storage.platform.base import PlatformAdapter
    from storage.transactions import (
        FileContent,
        StorageTransaction,
        TransactionActivity,
        TransactionJournalStatus,
        TransactionProgress,
        TransactionRecovery,
        TransactionRecoveryMaterial,
        TransactionResult,
        TransactionState,
        TransactionValidation,
    )

_DEFAULT_TRASH_ROOT = DevicePath(".iopenpod-trash")


class _SessionState(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    INVALIDATED = "invalidated"


class FilesystemSession:
    """The sole portal for one mounted Volume and Connection Generation."""

    def __init__(
        self,
        *,
        mounted_volume: MountedVolume,
        access: AccessMode,
        platform: PlatformAdapter,
        on_invalidate: Callable[[str, ConnectionGeneration], None],
        writer_lock_directory: Path | None,
    ) -> None:
        self._mounted_volume = mounted_volume
        self._current_observation = mounted_volume.observation
        self._access = access
        self._platform = platform
        self._on_invalidate = on_invalidate
        self._writer_lock_directory = writer_lock_directory
        self._root = mounted_volume.mount_point.path.resolve(strict=True)
        self._state = _SessionState.ACTIVE
        self._invalid_reason = ""
        self._state_lock = threading.Lock()

    @property
    def mounted_volume(self) -> MountedVolume:
        return MountedVolume(
            observation=self._current_observation,
            connection_generation=self._mounted_volume.connection_generation,
        )

    @property
    def access(self) -> AccessMode:
        return self._access

    @property
    def connection_key(self) -> str:
        return self._mounted_volume.observation.connection_key

    @property
    def is_active(self) -> bool:
        with self._state_lock:
            return self._state is _SessionState.ACTIVE

    def __enter__(self) -> FilesystemSession:
        self._assert_active()
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        with self._state_lock:
            if self._state is _SessionState.ACTIVE:
                self._state = _SessionState.CLOSED

    def invalidate(self, reason: str) -> None:
        self._invalidate(reason, notify=True)

    def invalidate_from_storage(self, reason: str) -> None:
        """Invalidate without notifying the Storage portal a second time.

        This lifecycle hook is public because ``Storage`` and
        ``FilesystemSession`` are separate classes at the same package boundary.
        Application callers should use :meth:`invalidate` or :meth:`close`.
        """

        self._invalidate(reason, notify=False)

    def _invalidate(self, reason: str, *, notify: bool) -> None:
        should_notify = False
        with self._state_lock:
            if self._state is _SessionState.ACTIVE:
                self._state = _SessionState.INVALIDATED
                self._invalid_reason = (
                    reason.strip() or "The connection was invalidated"
                )
                should_notify = notify
        if should_notify:
            self._on_invalidate(
                self.connection_key,
                self._mounted_volume.connection_generation,
            )

    def exists(self, path: DevicePath) -> bool:
        observation = self._revalidate()
        target = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
        )
        return os.path.lexists(target)

    def stat(self, path: DevicePath) -> DeviceEntry:
        observation = self._revalidate()
        target = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
            require_leaf=True,
        )
        try:
            metadata = os.lstat(target)
        except OSError as error:
            raise StorageOperationError(f"Could not inspect {path}: {error}") from error
        kind = _entry_kind(metadata)
        if kind is DeviceEntryKind.LINK_OR_REPARSE_POINT:
            raise UnsafeFilesystemPathError(
                f"Device Path is a symbolic link or reparse point: {path}"
            )
        return DeviceEntry(
            path=path,
            kind=kind,
            size=int(metadata.st_size),
            modified_ns=int(metadata.st_mtime_ns),
        )

    def list_directory(self, path: DevicePath) -> tuple[DeviceEntry, ...]:
        observation = self._revalidate()
        directory = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
            require_leaf=True,
        )
        entries = self._list_directory(directory, path)
        self._revalidate()
        return entries

    def list_root(self) -> tuple[DeviceEntry, ...]:
        """List the root of this Volume without exposing its Host Mount Point."""

        self._revalidate()
        entries = self._list_directory(self._root, None)
        self._revalidate()
        return entries

    def _list_directory(
        self,
        directory: Path,
        parent: DevicePath | None,
    ) -> tuple[DeviceEntry, ...]:
        try:
            entries: list[DeviceEntry] = []
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    metadata = entry.stat(follow_symlinks=False)
                    path = (
                        DevicePath(entry.name)
                        if parent is None
                        else parent.joinpath(entry.name)
                    )
                    entries.append(
                        DeviceEntry(
                            path=path,
                            kind=_entry_kind(metadata),
                            size=int(metadata.st_size),
                            modified_ns=int(metadata.st_mtime_ns),
                        )
                    )
        except OSError as error:
            raise StorageOperationError(
                f"Could not list Device directory {parent or 'root'}: {error}"
            ) from error
        return tuple(sorted(entries, key=lambda item: item.path.name.casefold()))

    def read(self, path: DevicePath, *, max_bytes: int | None = None) -> bytes:
        return self.read_snapshot(path, max_bytes=max_bytes).data

    def read_range(
        self,
        path: DevicePath,
        *,
        offset: int,
        length: int,
    ) -> bytes:
        """Read one exact byte range without materializing the complete file."""

        return self.read_range_snapshot(path, offset=offset, length=length).data

    def read_range_snapshot(
        self,
        path: DevicePath,
        *,
        offset: int,
        length: int,
    ) -> FileRangeSnapshot:
        """Read one exact byte range and return its stable source identity."""

        if offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative")
        observation = self._revalidate()
        target = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
            require_leaf=True,
        )
        try:
            with open_read_no_follow(target) as source:
                before = os.fstat(source.fileno())
                end = offset + length
                if offset > before.st_size or end > before.st_size:
                    raise StorageOperationError(
                        f"Requested byte range is outside Device file {path}"
                    )
                source.seek(offset)
                data = source.read(length)
                self._assert_active()
                after = os.fstat(source.fileno())
        except StorageOperationError:
            raise
        except OSError as error:
            raise StorageOperationError(
                f"Could not read byte range from {path}: {error}"
            ) from error
        if len(data) != length:
            raise ConcurrentModificationError(
                f"Device file changed while its byte range was read: {path}"
            )
        if _stat_identity(before) != _stat_identity(after):
            raise ConcurrentModificationError(
                f"Device file changed while its byte range was read: {path}"
            )
        self._revalidate()
        return FileRangeSnapshot(data=data, identity=_file_identity(after))

    def file_identity(self, path: DevicePath) -> FileIdentity:
        """Return a cheap identity suitable for validating a read-only cache."""

        observation = self._revalidate()
        target = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
            require_leaf=True,
        )
        try:
            with open_read_no_follow(target) as source:
                identity = _file_identity(os.fstat(source.fileno()))
                self._assert_active()
        except OSError as error:
            raise StorageOperationError(
                f"Could not inspect device file {path}: {error}"
            ) from error
        self._revalidate()
        return identity

    def delete_unrecoverably(self, path: DevicePath, *, expected: FileIdentity) -> None:
        """Delete one unchanged regular file without retaining a recovery copy."""

        with self._writer_lease():
            observation = self._revalidate(write=True)
            target = resolve_device_path(
                self._root,
                path,
                observation.volume.capabilities,
                require_leaf=True,
            )
            try:
                with open_read_no_follow(target) as source:
                    if _file_identity(os.fstat(source.fileno())) != expected:
                        raise FilePreconditionError(
                            f"Device file changed before deletion: {path}"
                        )
                # Check the named entry again after closing its handle (required
                # for deletion on Windows).
                metadata = os.lstat(target)
                if is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
                    raise UnsafeFilesystemPathError(
                        f"Device Path is not a regular file: {path}"
                    )
                if _file_identity(metadata) != expected:
                    raise FilePreconditionError(
                        f"Device file changed before deletion: {path}"
                    )
                self._revalidate(write=True)
                target.unlink()
                if os.path.lexists(target):
                    raise StorageOperationError(
                        f"Deleted device file is still present: {path}"
                    )
                flush_parent_directory(target)
                self._revalidate(write=True)
            except StorageError:
                raise
            except OSError as error:
                raise StorageOperationError(
                    f"Could not delete device file {path}: {error}"
                ) from error

    def read_snapshot(
        self,
        path: DevicePath,
        *,
        max_bytes: int | None = None,
    ) -> FileSnapshot:
        if max_bytes is not None and max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        observation = self._revalidate()
        target = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
            require_leaf=True,
        )
        data, fingerprint = read_and_fingerprint(
            target,
            collect_data=True,
            max_bytes=max_bytes,
            assert_active=self._assert_active,
        )
        self._revalidate()
        return FileSnapshot(data=data, fingerprint=fingerprint)

    def fingerprint(self, path: DevicePath) -> FileFingerprint:
        observation = self._revalidate()
        target = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
            require_leaf=True,
        )
        _, fingerprint = read_and_fingerprint(
            target,
            collect_data=False,
            max_bytes=None,
            assert_active=self._assert_active,
        )
        self._revalidate()
        return fingerprint

    def modified_time_matches(self, actual_ns: int, expected_ns: int) -> bool:
        """Compare observed times using the bound Volume's timestamp precision.

        Filesystem type cannot change within a valid Connection Generation.
        File operations revalidate that identity; comparing their returned facts
        needs no additional device I/O and is not a connection health check.
        """

        self._assert_active()
        return _modified_time_matches(
            actual_ns,
            expected_ns,
            self._mounted_volume.volume.filesystem_type,
        )

    def free_space(self) -> int:
        observation = self._revalidate()
        return observation.volume.available_bytes

    def set_modified_time(
        self,
        path: DevicePath,
        modified_ns: int,
        *,
        expected: FileFingerprint,
    ) -> DeviceEntry:
        """Set file modification time only when its complete content is unchanged."""

        if modified_ns < 0:
            raise ValueError("A modification time must be non-negative")
        with self._writer_lease():
            return self._set_modified_time(path, modified_ns, expected=expected)

    def _set_modified_time(
        self,
        path: DevicePath,
        modified_ns: int,
        *,
        expected: FileFingerprint,
    ) -> DeviceEntry:
        observation = self._revalidate(write=True)
        target = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
            require_leaf=True,
        )
        self._check_precondition(target, expected)
        try:
            metadata = os.lstat(target)
            os.utime(
                target,
                ns=(int(metadata.st_atime_ns), modified_ns),
            )
        except OSError as error:
            raise StorageOperationError(
                f"Could not set the modification time for {path}: {error}"
            ) from error
        self._revalidate(write=True)
        return self.stat(path)

    def create_directory(self, path: DevicePath) -> None:
        with self._writer_lease():
            observation = self._revalidate(write=True)
            self._ensure_directories(path, observation)
            self._revalidate(write=True)

    def atomic_write(
        self,
        path: DevicePath,
        data: bytes | bytearray | memoryview,
        *,
        expected: FileFingerprint | None = None,
        create_parents: bool = False,
        reserve_bytes: int = 0,
    ) -> WriteResult:
        """Create or generation-check and atomically replace one device file.

        ``expected=None`` means the target must not exist. Replacing an existing
        file requires the fingerprint returned by ``read_snapshot`` or
        ``fingerprint``; unconditional overwrites are deliberately unavailable.
        """

        if reserve_bytes < 0:
            raise ValueError("reserve_bytes must be non-negative")
        payload = bytes(data)
        with self._writer_lease():
            return self._atomic_publish(
                path,
                source_size=len(payload),
                chunks=(payload,),
                expected=expected,
                create_parents=create_parents,
                reserve_bytes=reserve_bytes,
            )

    def replace_with_recovery(
        self,
        path: DevicePath,
        data: bytes,
        *,
        expected: FileFingerprint,
        before_publish: Callable[[], None] | None = None,
    ) -> RecoveryWriteResult:
        """Replace one file under one writer lease, retaining its verified original.

        A durable intent journal precedes publication. Recovery data is never
        automatically deleted, including on disconnect or a failed verification.
        ``before_publish`` can cancel or verify application dependencies before
        entering the non-cancellable atomic publication stage.
        """
        recovery = DevicePath(f".iopenpod-recovery/{uuid.uuid4().hex}")
        original_path = recovery.joinpath("original.bin")
        journal_path = recovery.joinpath("replacement.json")
        started = False
        with self._writer_lease():
            self._revalidate(write=True)
            source = self.read_snapshot(path, max_bytes=expected.size)
            if source.fingerprint != expected:
                raise FilePreconditionError(
                    "The replacement source changed before saving"
                )
            journal: dict[str, str | int] = {
                "version": 1,
                "state": "prepared",
                "target": str(path),
                "original_sha256": expected.sha256,
                "original_size": expected.size,
                "replacement_sha256": hashlib.sha256(data).hexdigest(),
                "replacement_size": len(data),
            }
            try:
                self._atomic_publish(
                    original_path,
                    source_size=len(source.data),
                    chunks=(source.data,),
                    expected=None,
                    create_parents=True,
                    reserve_bytes=len(data) + 4096,
                )
                payload = json.dumps(journal, sort_keys=True).encode("utf-8")
                intent = self._atomic_publish(
                    journal_path,
                    source_size=len(payload),
                    chunks=(payload,),
                    expected=None,
                    create_parents=False,
                    reserve_bytes=len(data),
                )
                self.flush()
                if before_publish is not None:
                    before_publish()
                started = True
                written = self._atomic_publish(
                    path,
                    source_size=len(data),
                    chunks=(data,),
                    expected=expected,
                    create_parents=False,
                    reserve_bytes=0,
                )
                journal["state"] = "committed"
                payload = json.dumps(journal, sort_keys=True).encode("utf-8")
                self._atomic_publish(
                    journal_path,
                    source_size=len(payload),
                    chunks=(payload,),
                    expected=intent.fingerprint,
                    create_parents=False,
                    reserve_bytes=0,
                )
                return RecoveryWriteResult(written, journal_path, self.flush())
            except StorageError as error:
                raise RecoverableWriteError(
                    str(error), str(journal_path), started
                ) from error

    def restore_replacement(
        self, journal_path: DevicePath, *, expected: FileFingerprint
    ) -> WriteResult:
        """Restore retained bytes only over the exact recorded replacement.

        Recovery never overwrites an unrelated later edit. The journal and backup
        remain available after restoration; calling again on the original is safe.
        """
        if (
            journal_path.name != "replacement.json"
            or len(journal_path.parts) != 3
            or journal_path.parts[0] != ".iopenpod-recovery"
        ):
            raise ValueError("Choose a Storage replacement journal")
        with self._writer_lease():
            self._revalidate(write=True)
            try:
                decoded: object = json.loads(self.read(journal_path, max_bytes=16_384))
                if not isinstance(decoded, dict):
                    raise ValueError("Invalid replacement journal")
                journal = cast("dict[str, object]", decoded)
                if type(journal.get("version")) is not int or journal["version"] != 1:
                    raise ValueError("Unsupported replacement journal")
                target = journal["target"]
                if not isinstance(target, str):
                    raise ValueError("Invalid replacement target")
                path = DevicePath(target)
                assert journal_path.parent is not None
                size = journal["original_size"]
                if type(size) is not int or size < 0:
                    raise ValueError("Invalid original size")
                source = self.read_snapshot(
                    journal_path.parent.joinpath("original.bin"), max_bytes=size
                )
                if (
                    source.fingerprint.sha256 != journal["original_sha256"]
                    or source.fingerprint.size != size
                ):
                    raise ValueError("The recovery copy did not verify")
                current = self.fingerprint(path)
                if current != expected:
                    raise FilePreconditionError("The file changed before recovery")
                if current.sha256 == source.fingerprint.sha256 and current.size == size:
                    return WriteResult(path, current, False)
                if (
                    current.sha256 != journal["replacement_sha256"]
                    or current.size != journal["replacement_size"]
                ):
                    raise FilePreconditionError(
                        "Recovery would overwrite an unrelated edit"
                    )
            except (KeyError, TypeError, ValueError) as error:
                raise StorageOperationError(
                    f"Invalid recovery journal: {error}"
                ) from error
            return self._atomic_publish(
                path,
                source_size=size,
                chunks=(source.data,),
                expected=expected,
                create_parents=False,
                reserve_bytes=0,
            )

    def copy_from_host(
        self,
        source: HostPath,
        destination: DevicePath,
        *,
        expected: FileFingerprint | None = None,
        create_parents: bool = False,
        reserve_bytes: int = 0,
    ) -> WriteResult:
        if reserve_bytes < 0:
            raise ValueError("reserve_bytes must be non-negative")
        source_path = Path(os.fspath(source))
        source_file = _open_host_source(source_path)
        with source_file:
            before = os.fstat(source_file.fileno())

            def source_chunks() -> Iterable[bytes]:
                while True:
                    self._assert_active()
                    chunk = source_file.read(COPY_CHUNK_SIZE)
                    if not chunk:
                        return
                    yield chunk

            def validate_source() -> None:
                after = os.fstat(source_file.fileno())
                if _stat_identity(before) != _stat_identity(after):
                    raise ConcurrentModificationError(
                        f"Host source changed while it was copied: {source_path.name}"
                    )

            with self._writer_lease():
                return self._atomic_publish(
                    destination,
                    source_size=int(before.st_size),
                    chunks=source_chunks(),
                    expected=expected,
                    create_parents=create_parents,
                    reserve_bytes=reserve_bytes,
                    validate_staged=validate_source,
                )

    def validate_transaction(self, plan: StorageTransaction) -> TransactionValidation:
        """Inspect target preconditions and capacity without writing any files."""
        from storage._transactions import validate

        return validate(self, plan)

    def execute_transaction(
        self,
        plan: StorageTransaction,
        *,
        checkpoint: Callable[[], None] | None = None,
        progress: Callable[[TransactionProgress], None] | None = None,
        activity: Callable[[TransactionActivity], None] | None = None,
    ) -> TransactionResult:
        """Stage, verify and publish one recoverable ordered transaction."""
        from storage._transactions import execute

        with self._writer_lease():
            self._revalidate(write=True)
            return execute(
                self, plan, checkpoint=checkpoint, progress=progress, activity=activity
            )

    def inspect_transaction(
        self,
        journal_path: DevicePath,
        *,
        activity: Callable[[TransactionActivity], None] | None = None,
    ) -> TransactionRecovery:
        """Capture a read-only observation for explicit, revalidated recovery."""
        from storage._transactions import inspect

        return inspect(self, journal_path, activity=activity)

    def read_transaction_status(
        self, journal_path: DevicePath
    ) -> TransactionJournalStatus:
        """Read validated journal status; an identity mismatch grants no write authority."""
        from storage._transactions import read_status

        return read_status(self, journal_path)

    def read_transaction_state(self, journal_path: DevicePath) -> TransactionState:
        """Read validated journal state without streaming the transaction's files."""
        from storage._transactions import read_state

        return read_state(self, journal_path)

    def finalize_committed_transaction(self, journal_path: DevicePath) -> FlushResult:
        """Clean a durable verified commit without repeating media verification."""
        from storage._transactions import finalize_committed

        with self._writer_lease():
            self._revalidate(write=True)
            return finalize_committed(self, journal_path)

    def finalize_restored_transaction(self, journal_path: DevicePath) -> FlushResult:
        """Clean a durable verified restoration without repeating media reads."""
        from storage._transactions import finalize_restored

        with self._writer_lease():
            self._revalidate(write=True)
            return finalize_restored(self, journal_path)

    def restore_transaction(
        self,
        recovery: TransactionRecovery,
        *,
        recovery_material: TransactionRecoveryMaterial | None = None,
        checkpoint: Callable[[], None] | None = None,
        progress: Callable[[TransactionProgress], None] | None = None,
        activity: Callable[[TransactionActivity], None] | None = None,
    ) -> TransactionResult:
        """Restore original state only over the exact inspected transaction."""
        from storage._transactions import restore

        with self._writer_lease():
            self._revalidate(write=True)
            return restore(
                self,
                recovery,
                recovery_material=recovery_material,
                checkpoint=checkpoint,
                progress=progress,
                activity=activity,
            )

    def finalize_transaction(self, recovery: TransactionRecovery) -> FlushResult:
        """Remove one verified terminal transaction's recovery namespace.

        Finalization is retryable only after this exact namespace is wholly absent;
        a present namespace without its verified journal fails closed.
        """
        from storage._transactions import finalize

        with self._writer_lease():
            self._revalidate(write=True)
            return finalize(self, recovery)

    def finalize_missing_transaction(self, journal_path: DevicePath) -> FlushResult:
        """Remove an exact empty namespace left after its journal was deleted.

        This closes the narrow crash window between deleting a terminal journal
        and deleting its now-empty transaction directory. A present journal or
        any other namespace entry fails closed.
        """
        from storage._transactions import finalize_missing

        with self._writer_lease():
            self._revalidate(write=True)
            return finalize_missing(self, journal_path)

    def _remove_transaction_namespace(
        self,
        root: DevicePath,
        journal: DevicePath,
        *,
        expected_journal: FileFingerprint,
    ) -> None:
        observation = self._revalidate(write=True)
        root_path = resolve_device_path(
            self._root,
            root,
            observation.volume.capabilities,
            require_leaf=True,
        )
        journal_path = resolve_device_path(
            self._root,
            journal,
            observation.volume.capabilities,
            require_leaf=True,
        )
        children = self._transaction_namespace_entries(
            root_path,
            preserved=journal_path,
        )
        self._revalidate(write=True)
        self._check_precondition(journal_path, expected_journal)
        for child, is_directory in children:
            try:
                child_metadata = os.lstat(child)
                if is_link_or_reparse(child_metadata) or (
                    is_directory != stat.S_ISDIR(child_metadata.st_mode)
                ):
                    raise UnsafeFilesystemPathError(
                        "A transaction recovery entry changed during finalization"
                    )
                if is_directory:
                    child.rmdir()
                elif stat.S_ISREG(child_metadata.st_mode):
                    child.unlink()
                else:
                    raise UnsafeFilesystemPathError(
                        "A transaction recovery namespace contains an unsafe entry"
                    )
                flush_parent_directory(child)
            except FileNotFoundError:
                # macOS may remove an AppleDouble companion as its data file is
                # removed. An already absent cleanup entry needs no deletion.
                # Revalidate the session just as after a successful deletion.
                self._revalidate(write=True)
                continue
            except StorageError:
                raise
            except OSError as error:
                raise StorageOperationError(
                    f"Could not remove transaction recovery entry {child.name}: {error}"
                ) from error
            self._revalidate(write=True)
        try:
            journal_path.unlink()
            flush_parent_directory(journal_path)
            self._revalidate(write=True)
            root_path.rmdir()
            flush_parent_directory(root_path)
        except OSError as error:
            raise StorageOperationError(
                f"Could not finalize transaction recovery {root}: {error}"
            ) from error
        self._revalidate(write=True)

    def _transaction_namespace_entries(
        self,
        directory: Path,
        *,
        preserved: Path,
    ) -> tuple[tuple[Path, bool], ...]:
        try:
            metadata = os.lstat(directory)
            if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise UnsafeFilesystemPathError(
                    "A transaction recovery namespace became unsafe"
                )
            children = tuple(Path(entry.path) for entry in os.scandir(directory))
        except StorageError:
            raise
        except OSError as error:
            raise StorageOperationError(
                f"Could not inspect transaction recovery {directory.name}: {error}"
            ) from error
        result: list[tuple[Path, bool]] = []
        for child in children:
            if child == preserved:
                continue
            try:
                child_metadata = os.lstat(child)
                if is_link_or_reparse(child_metadata):
                    raise UnsafeFilesystemPathError(
                        "A transaction recovery namespace contains a link"
                    )
                if stat.S_ISDIR(child_metadata.st_mode):
                    result.extend(
                        self._transaction_namespace_entries(
                            child,
                            preserved=preserved,
                        )
                    )
                    result.append((child, True))
                elif stat.S_ISREG(child_metadata.st_mode):
                    result.append((child, False))
                else:
                    raise UnsafeFilesystemPathError(
                        "A transaction recovery namespace contains an unsafe entry"
                    )
            except FileNotFoundError:
                # Enumeration and deletion can race host metadata maintenance.
                continue
            except StorageError:
                raise
            except OSError as error:
                raise StorageOperationError(
                    f"Could not inspect transaction recovery entry {child.name}: {error}"
                ) from error
        return tuple(result)

    def _remove_empty_transaction_namespace(self, root: DevicePath) -> None:
        observation = self._revalidate(write=True)
        root_path = resolve_device_path(
            self._root,
            root,
            observation.volume.capabilities,
            require_leaf=True,
        )
        try:
            metadata = os.lstat(root_path)
            if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise UnsafeFilesystemPathError(
                    "A transaction recovery namespace became unsafe"
                )
            root_path.rmdir()
            flush_parent_directory(root_path)
        except StorageError:
            raise
        except OSError as error:
            if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise FilePreconditionError(
                    "A transaction namespace without its journal is not empty"
                ) from error
            raise StorageOperationError(
                f"Could not finalize empty transaction recovery {root}: {error}"
            ) from error
        self._revalidate(write=True)

    def _copy_transaction_file(
        self,
        source: bytes | HostPath | DevicePath,
        destination: DevicePath,
        content: FileContent,
        *,
        expected: FileFingerprint | None = None,
        reserve_bytes: int = 0,
        checkpoint: Callable[[], None] | None = None,
    ) -> WriteResult:
        if isinstance(source, bytes):
            return self._atomic_publish(
                destination,
                source_size=content.size,
                chunks=(source,),
                expected=expected,
                create_parents=True,
                reserve_bytes=reserve_bytes,
                expected_sha256=content.sha256,
            )
        if isinstance(source, HostPath):
            stream = _open_host_source(Path(os.fspath(source)))
        else:
            observation = self._revalidate()
            stream = open_read_no_follow(
                resolve_device_path(
                    self._root,
                    source,
                    observation.volume.capabilities,
                    require_leaf=True,
                )
            )
        with stream:
            before = os.fstat(stream.fileno())

            def chunks() -> Iterable[bytes]:
                while True:
                    if checkpoint is not None:
                        checkpoint()
                    self._assert_active()
                    data = stream.read(COPY_CHUNK_SIZE)
                    if not data:
                        return
                    yield data

            def verify_source() -> None:
                if _stat_identity(before) != _stat_identity(os.fstat(stream.fileno())):
                    raise ConcurrentModificationError(
                        "Transaction source changed during staging"
                    )

            return self._atomic_publish(
                destination,
                source_size=content.size,
                chunks=chunks(),
                expected=expected,
                create_parents=True,
                reserve_bytes=reserve_bytes,
                validate_staged=verify_source,
                expected_sha256=content.sha256,
            )

    def copy_to_host(
        self,
        source: DevicePath,
        destination: HostPath,
        *,
        prepare_staged: Callable[[HostPath], None] | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> CopyResult:
        """Stream to the Host and retain the original Device content fingerprint."""

        observation = self._revalidate()
        source_path = resolve_device_path(
            self._root,
            source,
            observation.volume.capabilities,
            require_leaf=True,
        )
        destination_path = Path(os.fspath(destination))
        if not destination_path.parent.is_dir():
            raise StorageOperationError("The Host destination directory does not exist")
        if os.path.lexists(destination_path):
            raise FilePreconditionError(
                f"Host destination already exists: {destination_path}"
            )

        descriptor = -1
        temp_path: Path | None = None
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".iop-",
                suffix=destination_path.suffix or ".tmp",
                dir=destination_path.parent,
            )
            temp_path = Path(temp_name)
            digest = hashlib.sha256()
            copied = 0
            with (
                open_read_no_follow(source_path) as device_file,
                os.fdopen(descriptor, "wb") as host_file,
            ):
                descriptor = -1
                before = os.fstat(device_file.fileno())
                while True:
                    self._assert_active()
                    chunk = device_file.read(COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    host_file.write(chunk)
                    digest.update(chunk)
                    copied += len(chunk)
                    if progress is not None:
                        progress(copied)
                after = os.fstat(device_file.fileno())
                if (
                    _stat_identity(before) != _stat_identity(after)
                    or copied != after.st_size
                ):
                    raise ConcurrentModificationError(
                        f"Device file changed while it was exported: {source}"
                    )
                flush_written_file(host_file)
            source_fingerprint = fingerprint_from_stat(after, digest.hexdigest())
            self._revalidate()
            if prepare_staged is not None:
                prepare_staged(HostPath(temp_path))
                with _open_host_source(temp_path, writable=True) as prepared:
                    flush_written_file(prepared)
                    prepared.seek(0)
                    digest = hashlib.sha256()
                    copied = 0
                    while chunk := prepared.read(COPY_CHUNK_SIZE):
                        digest.update(chunk)
                        copied += len(chunk)
                self._revalidate()
            # The opened file's identity may stay valid after its Device Path is
            # replaced. Bind the captured fingerprint to the named regular file
            # before it can become a later write precondition.
            current_source = resolve_device_path(
                self._root,
                source,
                self._current_observation.volume.capabilities,
                require_leaf=True,
            )
            if _stat_identity(os.lstat(current_source)) != _stat_identity(after):
                raise ConcurrentModificationError(
                    f"Device file changed while it was exported: {source}"
                )
            _publish_new_host_file(temp_path, destination_path)
            temp_path = None
            return CopyResult(
                bytes_copied=copied,
                sha256=digest.hexdigest(),
                source_fingerprint=source_fingerprint,
            )
        except OSError as error:
            raise StorageOperationError(
                f"Could not export {source} to the Host: {error}"
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temp_path is not None:
                with suppress(OSError):
                    temp_path.unlink(missing_ok=True)

    def move(
        self,
        source: DevicePath,
        destination: DevicePath,
        *,
        expected_source: FileFingerprint,
        expected_destination: FileFingerprint | None = None,
        create_parents: bool = False,
    ) -> WriteResult:
        with self._writer_lease():
            return self._move_file(
                source,
                destination,
                expected_source=expected_source,
                expected_destination=expected_destination,
                create_parents=create_parents,
            )

    def trash(
        self,
        path: DevicePath,
        *,
        trash_root: DevicePath = _DEFAULT_TRASH_ROOT,
        expected: FileFingerprint | None = None,
        remove_empty_parents: bool = False,
    ) -> TrashEntry:
        with self._writer_lease():
            observation = self._revalidate(write=True)
            source_path = resolve_device_path(
                self._root,
                path,
                observation.volume.capabilities,
                require_leaf=True,
            )
            fingerprint = self._fingerprint_path(source_path)
            if expected is not None and fingerprint != expected:
                raise FilePreconditionError(
                    f"Device file changed since it was read: {path.name}"
                )
            trash_path = trash_root.joinpath(uuid.uuid4().hex, *path.parts)
            self._move_file(
                path,
                trash_path,
                expected_source=fingerprint,
                expected_destination=None,
                create_parents=True,
            )
            if remove_empty_parents and path.parent is not None:
                self._remove_empty_parents(path.parent, observation)
            return TrashEntry(
                original_path=path,
                trash_path=trash_path,
                fingerprint=fingerprint,
            )

    def _remove_empty_parents(
        self,
        path: DevicePath,
        observation: VolumeObservation,
    ) -> None:
        current = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
            require_leaf=True,
        )
        while current != self._root:
            metadata = os.lstat(current)
            if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise UnsafeFilesystemPathError(
                    "An empty Device directory cleanup path became unsafe"
                )
            try:
                current.rmdir()
            except OSError as error:
                if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                    return
                raise StorageOperationError(
                    f"Could not remove empty Device directory {current.name}: {error}"
                ) from error
            flush_parent_directory(current)
            self._revalidate(write=True)
            current = current.parent

    def restore_trash(self, entry: TrashEntry) -> WriteResult:
        with self._writer_lease():
            return self._move_file(
                entry.trash_path,
                entry.original_path,
                expected_source=entry.fingerprint,
                expected_destination=None,
                create_parents=True,
            )

    def flush(self) -> FlushResult:
        observation = self._revalidate()
        result = self._platform.flush(observation)
        self._revalidate()
        return result

    def set_volume_label(self, name: str) -> str:
        """Apply and verify a native label under the same writer/identity safeguards."""
        from storage.volume_metadata import volume_label

        with self._writer_lease():
            observation = self._revalidate(write=True)
            label = volume_label(name, observation.volume.filesystem_type)
            try:
                actual = self._platform.set_volume_label(observation, label)
            except OSError as error:
                raise StorageOperationError(
                    f"Could not update the Volume label: {error}"
                ) from error
            self._revalidate(write=True)
            if actual != label:
                raise StorageOperationError(
                    f"Volume label did not verify: expected {label!r}, observed {actual!r}"
                )
            return label

    def enable_volume_icon(self) -> None:
        """Enable the Host's custom-volume-icon flag without changing other flags."""
        with self._writer_lease():
            observation = self._revalidate(write=True)
            try:
                self._platform.enable_volume_icon(observation)
            except OSError as error:
                raise StorageOperationError(
                    f"Could not enable the Volume icon: {error}"
                ) from error
            self._revalidate(write=True)

    def _atomic_publish(
        self,
        path: DevicePath,
        *,
        source_size: int,
        chunks: Iterable[bytes],
        expected: FileFingerprint | None,
        create_parents: bool,
        reserve_bytes: int,
        validate_staged: Callable[[], None] | None = None,
        expected_sha256: str | None = None,
    ) -> WriteResult:
        observation = self._revalidate(write=True)
        if create_parents and path.parent is not None:
            self._ensure_directories(path.parent, observation)
        target = resolve_device_path(
            self._root,
            path,
            observation.volume.capabilities,
        )
        if not target.parent.is_dir():
            raise StorageOperationError(
                f"The parent directory does not exist for Device Path {path}"
            )
        existing = self._check_precondition(target, expected)
        self._check_write_capacity(
            source_size,
            observation,
            reserve_bytes=reserve_bytes,
            display_name=path.name,
        )

        descriptor = -1
        temp_path: Path | None = None
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".iop-",
                suffix=".tmp",
                dir=target.parent,
            )
            temp_path = Path(temp_name)
            digest = hashlib.sha256()
            written = 0
            with os.fdopen(descriptor, "wb") as staged_file:
                descriptor = -1
                for chunk in chunks:
                    self._assert_active()
                    staged_file.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if written > source_size:
                        raise ConcurrentModificationError(
                            "The write source grew while it was being staged"
                        )
                if written != source_size:
                    raise ConcurrentModificationError(
                        "The write source changed size while it was being staged"
                    )
                flush_written_file(staged_file)
            if validate_staged is not None:
                validate_staged()
            if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
                raise ConcurrentModificationError(
                    "Staged content does not match its captured SHA-256"
                )

            observation = self._revalidate(write=True)
            target = resolve_device_path(
                self._root,
                path,
                observation.volume.capabilities,
            )
            self._check_precondition(target, expected)
            os.replace(temp_path, target)
            temp_path = None
            flush_parent_directory(target)
            self._revalidate(write=True)
            committed = self._fingerprint_path(target)
            if committed.size != written or committed.sha256 != digest.hexdigest():
                raise ConcurrentModificationError(
                    f"Committed device file did not verify: {path}"
                )
            return WriteResult(
                path=path,
                fingerprint=committed,
                replaced_existing=existing is not None,
            )
        except OSError as error:
            raise StorageOperationError(
                f"Could not atomically write Device Path {path}: {error}"
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temp_path is not None:
                with suppress(OSError):
                    temp_path.unlink(missing_ok=True)

    def _move_file(
        self,
        source: DevicePath,
        destination: DevicePath,
        *,
        expected_source: FileFingerprint,
        expected_destination: FileFingerprint | None,
        create_parents: bool,
    ) -> WriteResult:
        if source == destination:
            raise FilePreconditionError("Move source and destination are identical")
        observation = self._revalidate(write=True)
        if create_parents and destination.parent is not None:
            self._ensure_directories(destination.parent, observation)
        source_path = resolve_device_path(
            self._root,
            source,
            observation.volume.capabilities,
            require_leaf=True,
        )
        destination_path = resolve_device_path(
            self._root,
            destination,
            observation.volume.capabilities,
        )
        if not destination_path.parent.is_dir():
            raise StorageOperationError(
                f"The destination parent does not exist for {destination}"
            )
        self._revalidate(write=True)
        self._check_precondition(source_path, expected_source)
        replaced = (
            self._check_precondition(destination_path, expected_destination) is not None
        )
        try:
            os.replace(source_path, destination_path)
            flush_parent_directory(source_path)
            if source_path.parent != destination_path.parent:
                flush_parent_directory(destination_path)
        except OSError as error:
            raise StorageOperationError(
                f"Could not move {source} to {destination}: {error}"
            ) from error
        self._revalidate(write=True)
        committed = self._fingerprint_path(destination_path)
        if committed.sha256 != expected_source.sha256:
            raise ConcurrentModificationError(
                f"Moved device file did not verify: {destination}"
            )
        return WriteResult(
            path=destination,
            fingerprint=committed,
            replaced_existing=replaced,
        )

    def _ensure_directories(
        self,
        path: DevicePath,
        observation: VolumeObservation,
    ) -> None:
        current = self._root
        traversed: list[str] = []
        for component in path.parts:
            traversed.append(component)
            current_path = DevicePath("/".join(traversed))
            current = resolve_device_path(
                self._root,
                current_path,
                observation.volume.capabilities,
            )
            if os.path.lexists(current):
                metadata = os.lstat(current)
                if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                    raise UnsafeFilesystemPathError(
                        f"Device directory path is unsafe: {current_path}"
                    )
                continue
            try:
                current.mkdir()
                flush_parent_directory(current)
            except OSError as error:
                raise StorageOperationError(
                    f"Could not create Device directory {current_path}: {error}"
                ) from error

    def _check_precondition(
        self,
        path: Path,
        expected: FileFingerprint | None,
    ) -> FileFingerprint | None:
        if not os.path.lexists(path):
            if expected is not None:
                raise FilePreconditionError(
                    f"Expected device file is missing: {path.name}"
                )
            return None
        current = self._fingerprint_path(path)
        if expected is None:
            raise FilePreconditionError(
                f"Device destination already exists: {path.name}"
            )
        if current != expected:
            raise FilePreconditionError(
                f"Device file changed since it was read: {path.name}"
            )
        return current

    def _fingerprint_path(self, path: Path) -> FileFingerprint:
        _, fingerprint = read_and_fingerprint(
            path,
            collect_data=False,
            max_bytes=None,
            assert_active=self._assert_active,
        )
        return fingerprint

    def _check_write_capacity(
        self,
        logical_size: int,
        observation: VolumeObservation,
        *,
        reserve_bytes: int,
        display_name: str,
    ) -> None:
        capabilities = observation.volume.capabilities
        max_size = capabilities.max_file_size_bytes
        if max_size is not None and logical_size > max_size:
            raise FileSizeLimitError(
                f"{display_name} is {logical_size} bytes, exceeding the "
                f"filesystem limit of {max_size} bytes"
            )
        required = allocated_size(logical_size, capabilities.allocation_unit_size)
        required += max(0, reserve_bytes)
        try:
            available = shutil.disk_usage(self._root).free
        except OSError as error:
            raise StorageCapacityError(
                f"Could not verify free space before writing {display_name}: {error}"
            ) from error
        if available < required:
            raise StorageCapacityError(
                f"Writing {display_name} requires {required} bytes but only "
                f"{available} bytes are available"
            )

    def _writer_lease(self) -> VolumeWriterLease:
        self._assert_active()
        identity = "|".join(
            (
                self._mounted_volume.physical_device.id.value,
                self._mounted_volume.volume.id.value,
            )
        )
        return VolumeWriterLease(identity, self._writer_lock_directory)

    def _revalidate(self, *, write: bool = False) -> VolumeObservation:
        self._assert_active()
        if write and self._access is not AccessMode.READ_WRITE:
            raise ReadOnlyFilesystemError(
                "This Filesystem Session was opened for read-only access"
            )
        try:
            current = self._platform.reinspect(self._mounted_volume.observation)
        except (MountInspectionError, OSError) as error:
            self.invalidate(f"The Volume disconnected: {error}")
            raise VolumeDisconnectedError(
                "The Volume disconnected and this Filesystem Session is invalid"
            ) from error
        if not _same_connection(self._mounted_volume.observation, current):
            self.invalidate("The Mount Point now refers to a different Volume")
            raise VolumeIdentityChangedError(
                "The Mount Point changed and this Filesystem Session is invalid"
            )
        if (
            current.volume.filesystem_type
            != self._mounted_volume.volume.filesystem_type
        ):
            self.invalidate("The mounted filesystem type changed")
            raise VolumeIdentityChangedError(
                "The filesystem changed and this Filesystem Session is invalid"
            )
        if not current.volume.capabilities.readable:
            self.invalidate("The mounted Volume is no longer readable")
            raise MountInspectionError(
                "The mounted Volume is no longer readable and the session is invalid"
            )
        if write and not current.volume.capabilities.safe_for_writes:
            self.invalidate("The mounted Volume is no longer safely writable")
            raise ReadOnlyFilesystemError(
                "The mounted Volume is no longer safely writable"
            )
        self._current_observation = current
        self._assert_active()
        return current

    def _assert_active(self) -> None:
        with self._state_lock:
            state = self._state
            reason = self._invalid_reason
        if state is _SessionState.CLOSED:
            raise SessionClosedError("The Filesystem Session is closed")
        if state is _SessionState.INVALIDATED:
            raise SessionInvalidatedError(
                reason or "The Filesystem Session was invalidated"
            )


def _same_connection(
    retained: VolumeObservation,
    current: VolumeObservation,
) -> bool:
    return (
        retained.physical_device.id == current.physical_device.id
        and retained.volume.id == current.volume.id
        and retained.mount_instance == current.mount_instance
        and os.path.normcase(os.path.realpath(retained.mount_point.path))
        == os.path.normcase(os.path.realpath(current.mount_point.path))
    )


def _entry_kind(metadata: os.stat_result) -> DeviceEntryKind:
    if is_link_or_reparse(metadata):
        return DeviceEntryKind.LINK_OR_REPARSE_POINT
    if stat.S_ISREG(metadata.st_mode):
        return DeviceEntryKind.FILE
    if stat.S_ISDIR(metadata.st_mode):
        return DeviceEntryKind.DIRECTORY
    return DeviceEntryKind.OTHER


def _open_host_source(path: Path, *, writable: bool = False) -> BinaryIO:
    try:
        path_metadata = os.lstat(path)
    except OSError as error:
        raise StorageOperationError(
            f"Could not inspect Host source {path}: {error}"
        ) from error
    if is_link_or_reparse(path_metadata) or not stat.S_ISREG(path_metadata.st_mode):
        raise UnsafeFilesystemPathError(
            f"Host source is not a safe regular file: {path}"
        )
    access = os.O_RDWR if writable else os.O_RDONLY
    flags = access | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise StorageOperationError(
            f"Could not open Host source {path}: {error}"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        if is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise UnsafeFilesystemPathError(
                f"Host source is not a regular file: {path}"
            )
        file = os.fdopen(descriptor, "rb+" if writable else "rb")
        descriptor = -1
        return file
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _publish_new_host_file(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
        flush_parent_directory(destination)
        source.unlink()
        return
    except FileExistsError as error:
        raise FilePreconditionError(
            f"Host destination already exists: {destination}"
        ) from error
    except OSError:
        pass

    descriptor = -1
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        with open(source, "rb") as staged, os.fdopen(descriptor, "wb") as published:
            descriptor = -1
            shutil.copyfileobj(staged, published, COPY_CHUNK_SIZE)
            flush_written_file(published)
        flush_parent_directory(destination)
        source.unlink()
    except FileExistsError as error:
        raise FilePreconditionError(
            f"Host destination already exists: {destination}"
        ) from error
    except OSError:
        with suppress(OSError):
            destination.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _file_identity(metadata: os.stat_result) -> FileIdentity:
    device, inode, size, modified_ns = _stat_identity(metadata)
    return FileIdentity(
        size=size,
        modified_ns=modified_ns,
        device=device,
        inode=inode,
    )


__all__ = ["FilesystemSession"]
