"""Crash-safe Backup Archive v4 repository.

The repository owns Host-side persistence only.  It verifies every object before
exposing it and never treats an Archive Key as proof of a connected iPod's identity.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from iOpenPod.app.backups.archive import (
    BACKUP_REPOSITORY_DIRECTORY,
    INCREMENTAL_SOURCE_VERIFICATION,
    LegacySource,
    NativeArchiveFormatError,
    NativeManifest,
    NativeManifestFile,
    decode_manifest,
    encode_manifest,
    replace_note,
    repository_marker_bytes,
    validate_repository_marker,
)
from iOpenPod.app.backups.models import (
    ArchiveKey,
    BackupCatalog,
    BackupDeviceIdentity,
    BackupDeviceInfo,
    BackupDeviceMetadata,
    BackupExportResult,
    BackupIdentityClaim,
    BackupIdentityClaimKind,
    BackupProgress,
    BackupReason,
    BackupStage,
    ContentIdentity,
    LegacyIdentityClaim,
    LegacyImportFailure,
    LegacyImportIdentityAssignment,
    LegacyImportResult,
    RestoreRecoveryOutcome,
    RestoreRecoveryPhase,
    RestoreRecoveryRecord,
    SnapshotIdentityState,
    SnapshotInfo,
    VerifiedSnapshot,
    VerifiedSnapshotFile,
    sanitize_backup_device_id,
)
from iOpenPod.app.backups.original_archive import (
    OriginalArchiveFormatError,
    OriginalManifest,
    decode_original_manifest,
)
from iOpenPod.app.backups.recovery import (
    RestoreRecoveryFormatError,
    decode_recovery,
    encode_recovery,
    update_recovery_phase,
)
from iOpenPod.app.backups.scope import (
    UnsupportedBackupEntryError,
    enumerate_backup_files,
)
from iOpenPod.app.display_text import source_text
from storage import (
    AtomicHostFile,
    DeviceEntry,
    DevicePath,
    FilesystemSession,
    HostPath,
    HostResourceLease,
)

if TYPE_CHECKING:
    from typing import BinaryIO

_COPY_CHUNK_SIZE = 1024 * 1024
_MAX_CATALOG_BYTES = 64 * 1024 * 1024
_MAX_RECOVERY_RECORD_BYTES = 1024 * 1024
_MAX_REPOSITORY_MARKER_BYTES = 4 * 1024
_MAX_NOTE_LENGTH = 4_000
_AUTOMATIC_SAFETY_CHECKPOINT_LIMIT = 5
_WINDOWS_INVALID_EXPORT_CHARACTERS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_EXPORT_NAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}

type ProgressCallback = Callable[[BackupProgress], None]
type CancellationCheck = Callable[[], bool]


class BackupError(RuntimeError):
    """A Backup Archive operation could not complete or be trusted."""


class BackupCancelledError(BackupError):
    """A cancellable capture stopped before publication."""


class BackupPathOverlapError(BackupError):
    """A Host source or destination overlaps Backup Archive v4."""


class BackupRecoveryRequiredError(BackupError):
    """An unresolved restore pins archive state until recovery completes."""


class BackupRestoreIncompleteError(BackupError):
    """Compatibility error for callers migrating to bounded restore recovery."""

    def __init__(self, message: str, safety_snapshot_id: str) -> None:
        super().__init__(message)
        self.safety_snapshot_id = safety_snapshot_id


def _repository_lock(root: Path) -> threading.RLock:
    key = os.path.normcase(os.path.realpath(root))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _is_link_or_reparse(path: Path) -> bool:
    metadata = os.lstat(path)
    return _metadata_is_link_or_reparse(metadata)


def _metadata_is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse = int(getattr(metadata, "st_file_attributes", 0) or 0) & int(
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    return stat.S_ISLNK(metadata.st_mode) or bool(reparse)


def _stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        int(metadata.st_ctime_ns),
    )


def _path_open_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    """Identity stable across a Windows path-to-handle transition."""

    creation_ns = int(getattr(metadata, "st_birthtime_ns", metadata.st_ctime_ns))
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        creation_ns,
    )


@contextmanager
def _open_regular_file(path: Path) -> Generator[BinaryIO]:
    """Open one unchanged regular file without following a link when supported."""

    before = os.lstat(path)
    if _metadata_is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise BackupError(f"Backup path is not a safe regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _path_open_identity(
            before
        ) != _path_open_identity(opened):
            raise BackupError(f"Backup file changed while it was opened: {path}")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            yield stream
            after = os.fstat(stream.fileno())
        if _stat_identity(opened) != _stat_identity(after):
            raise BackupError(f"Backup file changed while it was read: {path}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_bounded_regular_file(path: Path, *, max_bytes: int, label: str) -> bytes:
    with _open_regular_file(path) as stream:
        if os.fstat(stream.fileno()).st_size > max_bytes:
            raise BackupError(f"{label} exceeds its supported size: {path}")
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise BackupError(f"{label} exceeds its supported size: {path}")
    return data


def _require_payload_size(data: bytes, *, max_bytes: int, label: str) -> None:
    if len(data) > max_bytes:
        raise BackupError(f"{label} exceeds its supported size")


def _encode_bounded_recovery(record: RestoreRecoveryRecord) -> bytes:
    data = encode_recovery(record)
    _require_payload_size(
        data,
        max_bytes=_MAX_RECOVERY_RECORD_BYTES,
        label="Restore Recovery record",
    )
    return data


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _open_regular_file(path) as stream:
        while chunk := stream.read(_COPY_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _flush_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class BackupRepository:
    """Persist independently identified, content-addressed v4 snapshots."""

    def __init__(self, root: Path) -> None:
        self._configured_root = Path(os.path.abspath(root))
        self.root = Path(os.path.realpath(self._configured_root))
        self.native_root = self.root / BACKUP_REPOSITORY_DIRECTORY
        self._archives_root = self.native_root / "archives"
        self._objects_root = self.native_root / "objects" / "sha256"
        self._staging_root = self.native_root / "staging"
        self._recoveries_root = self.native_root / "recoveries"
        self._marker_path = self.native_root / "repository.json"
        self._lock = _repository_lock(self.root)
        normalized = os.path.normcase(os.path.realpath(self._configured_root))
        self._lease_identity = f"native-backup-repository:{normalized}"
        self._operation_depth = threading.local()

    @contextmanager
    def _locked(self) -> Generator[None]:
        with self._lock:
            depth = int(getattr(self._operation_depth, "value", 0))
            self._operation_depth.value = depth + 1
            try:
                if depth:
                    yield
                else:
                    with HostResourceLease(self._lease_identity):
                        yield
            finally:
                self._operation_depth.value = depth

    @staticmethod
    def sanitize_device_id(device_id: str) -> str:
        """Compatibility helper; native Archive Keys use stronger namespacing."""

        return sanitize_backup_device_id(device_id)

    def resolve_archive_key(self, identity: BackupDeviceIdentity) -> ArchiveKey:
        """Find a matching archive, or allocate a collision-safe key."""

        if not identity.is_stable:
            raise BackupError("A Backup Archive requires a Backup Identifier")
        with self._locked():
            if os.path.lexists(self.native_root):
                self._assert_repository_readable()
                for key in self._archive_keys():
                    existing = self._archive_identity(key)
                    if existing is not None and existing.matches(identity):
                        return key

            for length in (16, 24, 32, 64):
                key = ArchiveKey(f"ipod--{identity.digest[:length]}")
                if not self._archive_dir(key).exists():
                    return key
                existing = self._archive_identity(key)
                if existing is not None and existing.matches(identity):
                    return key
                if not self._manifest_paths(key):
                    return key
            raise BackupError("Could not allocate a collision-free Backup Archive Key")

    def list_devices(self) -> tuple[BackupDeviceInfo, ...]:
        with self._locked():
            if not os.path.lexists(self.native_root):
                return ()
            self._assert_repository_readable()
            result: list[BackupDeviceInfo] = []
            for key in self._archive_keys():
                paths = self._manifest_paths(key)
                if not paths:
                    continue
                latest: NativeManifest | None = None
                for path in paths:
                    try:
                        latest = self._read_manifest(key, path.stem)
                    except BackupError:
                        continue
                    break
                result.append(
                    BackupDeviceInfo(
                        device_id=key.value,
                        device_name=latest.device_name if latest else key.value,
                        snapshot_count=len(paths),
                        metadata=latest.metadata if latest else BackupDeviceMetadata(),
                        has_backup_identifier=(
                            latest.identity_state is SnapshotIdentityState.NATIVE
                            if latest
                            else False
                        ),
                        identity_state=(
                            latest.identity_state
                            if latest
                            else SnapshotIdentityState.UNSTABLE
                        ),
                    )
                )
            return tuple(result)

    def list_snapshots(self, archive_key: ArchiveKey | str) -> tuple[SnapshotInfo, ...]:
        with self._locked():
            if not os.path.lexists(self.native_root):
                return ()
            self._assert_repository_readable()
            key = self._coerce_existing_key(archive_key)
            snapshots: list[SnapshotInfo] = []
            newer_files: tuple[NativeManifestFile, ...] | None = None
            for path in self._manifest_paths(key):
                try:
                    manifest = self._read_manifest(key, path.stem)
                except BackupError as error:
                    snapshots.append(
                        SnapshotInfo(
                            id=path.stem,
                            timestamp=path.stem,
                            device_id=key.value,
                            device_name=key.value,
                            is_valid=False,
                            validation_error=str(error),
                        )
                    )
                    newer_files = None
                    continue
                if newer_files is not None and snapshots:
                    added, removed, changed = self._delta(manifest.files, newer_files)
                    snapshots[-1] = replace(
                        snapshots[-1],
                        files_added=added,
                        files_removed=removed,
                        files_changed=changed,
                    )
                snapshots.append(self._snapshot_info(manifest))
                newer_files = manifest.files
            return tuple(snapshots)

    def stored_size(self, archive_key: ArchiveKey | str) -> int:
        with self._locked():
            if not os.path.lexists(self.native_root):
                return 0
            self._assert_repository_readable()
            key = self._coerce_existing_key(archive_key)
            referenced: dict[str, int] = {}
            total = 0
            for path in self._manifest_paths(key):
                try:
                    manifest = self._read_manifest(key, path.stem)
                    total += path.stat().st_size
                except (BackupError, OSError):
                    continue
                for entry in manifest.files:
                    referenced[entry.content.sha256] = entry.content.size
            for digest, size in referenced.items():
                object_path = self._object_path(digest)
                try:
                    self._require_native_directory(object_path.parent)
                    if object_path.is_file() and object_path.stat().st_size == size:
                        total += size
                except OSError:
                    continue
            return total

    def catalog(self, archive_key: ArchiveKey | str) -> BackupCatalog:
        with self._locked():
            key = self._coerce_existing_key(archive_key)
            snapshots = self.list_snapshots(key)
            latest = next((item for item in snapshots if item.is_valid), None)
            device = BackupDeviceInfo(
                device_id=key.value,
                device_name=latest.device_name if latest else key.value,
                snapshot_count=len(snapshots),
                metadata=latest.metadata if latest else BackupDeviceMetadata(),
                has_backup_identifier=(
                    latest.has_backup_identifier if latest else False
                ),
                identity_state=(
                    latest.identity_state if latest else SnapshotIdentityState.UNSTABLE
                ),
            )
            return BackupCatalog(device, snapshots, self.stored_size(key))

    def create_snapshot(
        self,
        session: FilesystemSession,
        *,
        identity: BackupDeviceIdentity | None = None,
        archive_key: ArchiveKey | None = None,
        device_name: str,
        metadata: BackupDeviceMetadata,
        reason: BackupReason = BackupReason.MANUAL,
        max_backups: int = 0,
        force: bool = False,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCheck | None = None,
        # Transitional arguments used only by callers migrating to native claims.
        device_id: str | None = None,
        identity_is_stable: bool | None = None,
    ) -> SnapshotInfo | None:
        identity = self._coerce_capture_identity(
            identity, device_id=device_id, identity_is_stable=identity_is_stable
        )
        if not identity.is_stable and (
            archive_key is None or not archive_key.value.startswith("unidentified--")
        ):
            raise BackupError(
                "An unstable capture requires an explicit unidentified Archive Key"
            )
        if not identity.is_stable and reason is BackupReason.PRE_RESTORE_SAFETY:
            raise BackupError(
                "An unstable iPod cannot create a restore safety snapshot"
            )
        with self._locked():
            self._prepare_repository()
            key = archive_key or self.resolve_archive_key(identity)
            self._validate_capture_archive(key, identity)
            self._reconcile_staging()
            self._emit(progress, BackupStage.SCANNING, 0, 0, "Scanning the iPod…")
            before = self._enumerate(session)
            latest = self._latest_valid_manifest(key)
            previous_by_path = (
                {entry.path_parts: entry for entry in latest.files}
                if latest is not None and not force
                else {}
            )
            stage = Path(tempfile.mkdtemp(prefix="capture-", dir=self._staging_root))
            captured: list[NativeManifestFile] = []
            manifest_published = False
            try:
                total = len(before)
                total_bytes = sum(entry.size for entry in before)
                completed_bytes = 0
                for index, entry in enumerate(before, start=1):
                    self._check_cancelled(cancelled)
                    label = str(entry.path)
                    previous = previous_by_path.get(entry.path.parts)
                    if (
                        previous is not None
                        and previous.content.size == entry.size
                        and previous.modified_ns == entry.modified_ns
                        and self._object_is_reusable(previous.content)
                    ):
                        captured.append(previous)
                        completed_bytes += entry.size
                        self._emit(
                            progress,
                            BackupStage.CAPTURING,
                            index,
                            total,
                            source_text(
                                "Reusing unchanged file {index} of {total}…",
                                index=f"{index:,}",
                                total=f"{total:,}",
                            ),
                            label,
                            completed_bytes=completed_bytes,
                            total_bytes=total_bytes,
                        )
                        continue
                    self._emit(
                        progress,
                        BackupStage.CAPTURING,
                        index - 1,
                        total,
                        source_text(
                            "Capturing {index} of {total} files…",
                            index=f"{index:,}",
                            total=f"{total:,}",
                        ),
                        label,
                        completed_bytes=completed_bytes,
                        total_bytes=total_bytes,
                    )
                    staged = stage / f"{index:08d}.object"
                    last_progress_at = time.monotonic()

                    def observe_copy(
                        file_bytes: int,
                        entry_size: int = entry.size,
                        file_index: int = index,
                        file_label: str = label,
                        bytes_before: int = completed_bytes,
                    ) -> None:
                        nonlocal last_progress_at
                        self._check_cancelled(cancelled)
                        now = time.monotonic()
                        if file_bytes < entry_size and now - last_progress_at < 0.1:
                            return
                        last_progress_at = now
                        self._emit(
                            progress,
                            BackupStage.CAPTURING,
                            file_index - 1,
                            total,
                            source_text(
                                "Capturing {index} of {total} files…",
                                index=f"{file_index:,}",
                                total=f"{total:,}",
                            ),
                            file_label,
                            completed_bytes=bytes_before + file_bytes,
                            total_bytes=total_bytes,
                        )

                    copied = session.copy_to_host(
                        entry.path,
                        HostPath(staged),
                        progress=observe_copy,
                    )
                    if copied.bytes_copied != entry.size:
                        raise BackupError(f"{label} changed during capture")
                    content = ContentIdentity(copied.sha256, copied.bytes_copied)
                    self._publish_object(staged, content)
                    captured.append(
                        NativeManifestFile(
                            path_parts=entry.path.parts,
                            content=content,
                            modified_ns=entry.modified_ns,
                        )
                    )
                    completed_bytes += copied.bytes_copied

                self._check_cancelled(cancelled)
                self._emit(
                    progress,
                    BackupStage.FINALIZING,
                    total,
                    total,
                    "Finalizing the Backup Snapshot…",
                    can_cancel=False,
                    completed_bytes=completed_bytes,
                    total_bytes=total_bytes,
                )
                final = self._enumerate(session)
                if self._entry_state(final) != self._entry_state(before):
                    raise BackupError(
                        "The iPod changed while its Backup Snapshot was captured"
                    )

                files = tuple(sorted(captured, key=lambda item: item.path_parts))
                if latest is not None and not force and latest.files == files:
                    self._emit(
                        progress,
                        BackupStage.NO_CHANGES,
                        total,
                        total,
                        "No changes since the latest Backup Snapshot.",
                        can_cancel=False,
                        completed_bytes=completed_bytes,
                        total_bytes=total_bytes,
                    )
                    return None

                snapshot_id, sequence, timestamp = self._next_snapshot_identity(key)
                encoded = encode_manifest(
                    snapshot_id=snapshot_id,
                    timestamp=timestamp,
                    sequence=sequence,
                    archive_key=key,
                    device_name=device_name,
                    metadata=metadata,
                    identity_state=(
                        SnapshotIdentityState.NATIVE
                        if identity.is_stable
                        else SnapshotIdentityState.UNSTABLE
                    ),
                    identity=identity,
                    legacy_identity_claim=None,
                    reason=reason,
                    note="",
                    files=files,
                    source_verification=INCREMENTAL_SOURCE_VERIFICATION,
                )
                _require_payload_size(
                    encoded,
                    max_bytes=_MAX_CATALOG_BYTES,
                    label="Native Backup catalog",
                )
                manifest_path = self._manifest_path(key, snapshot_id)
                self._ensure_native_directory(manifest_path.parent)
                AtomicHostFile(manifest_path).create_bytes(encoded)
                try:
                    manifest = self._read_manifest(key, snapshot_id)
                except Exception:
                    manifest_path.unlink(missing_ok=True)
                    _flush_directory(manifest_path.parent)
                    raise
                manifest_published = True
                if reason is BackupReason.PRE_RESTORE_SAFETY:
                    self._prune(
                        key,
                        _AUTOMATIC_SAFETY_CHECKPOINT_LIMIT,
                        snapshot_id,
                        safety_only=True,
                    )
                elif max_backups > 0 and identity.is_stable:
                    self._prune(key, max_backups, snapshot_id, safety_only=False)
                self._emit(
                    progress,
                    BackupStage.COMPLETE,
                    total,
                    total,
                    source_text(
                        "Backup complete — {total} files protected.", total=f"{total:,}"
                    ),
                    can_cancel=False,
                    completed_bytes=completed_bytes,
                    total_bytes=total_bytes,
                )
                return self._snapshot_info(manifest)
            finally:
                self._remove_owned_tree(stage, self._staging_root)
                if not manifest_published:
                    with suppress(BackupError, OSError):
                        self._garbage_collect()

    @contextmanager
    def open_verified_snapshot(
        self, archive_key: ArchiveKey | str, snapshot_id: str
    ) -> Generator[VerifiedSnapshot]:
        """Verify and pin every Host object for a restore/export consumer."""

        with self._locked():
            self._assert_repository_readable()
            key = self._coerce_existing_key(archive_key)
            manifest = self._read_manifest(key, snapshot_id)
            verified: list[VerifiedSnapshotFile] = []
            checked: set[str] = set()
            for entry in manifest.files:
                object_path = self._object_path(entry.content.sha256)
                self._verify_object(object_path, entry.content, checked=checked)
                verified.append(
                    VerifiedSnapshotFile(
                        path_parts=entry.path_parts,
                        source=HostPath(object_path),
                        content=entry.content,
                        modified_ns=entry.modified_ns,
                    )
                )
            material_identity = hashlib.sha256(
                (
                    "iopenpod.backup.recovery-material.v1\0"
                    + key.value
                    + "\0"
                    + manifest.catalog_sha256
                ).encode("utf-8")
            ).hexdigest()
            yield VerifiedSnapshot(
                archive_key=key,
                snapshot_id=snapshot_id,
                identity_state=manifest.identity_state,
                identity=manifest.identity,
                legacy_identity_claim=manifest.legacy_identity_claim,
                files=tuple(verified),
                recovery_material_identity=material_identity,
            )

    def import_original(
        self,
        source_root: Path,
        *,
        identity_assignments: tuple[LegacyImportIdentityAssignment, ...] = (),
    ) -> LegacyImportResult:
        """Copy verified Original v2/v3 snapshots without modifying their source."""

        source = Path(os.path.abspath(source_root))
        if self._paths_overlap(source, self.root):
            raise BackupPathOverlapError(
                "Original import source and native destination must not overlap"
            )
        self._require_source_directory(source, source)
        imported: list[SnapshotInfo] = []
        already_imported: list[SnapshotInfo] = []
        failures: list[LegacyImportFailure] = []
        assignments = self._legacy_import_assignments(identity_assignments)
        with self._locked():
            self._prepare_repository()
            self._reconcile_staging()
            for device_directory in sorted(
                source.iterdir(), key=lambda path: path.name
            ):
                if device_directory.name in {"blobs", BACKUP_REPOSITORY_DIRECTORY}:
                    continue
                if not device_directory.is_dir():
                    continue
                legacy_device_id = device_directory.name
                snapshots_directory = device_directory / "snapshots"
                if not snapshots_directory.exists():
                    continue
                try:
                    self._require_source_directory(source, device_directory)
                    self._require_source_directory(source, snapshots_directory)
                except BackupError as error:
                    failures.append(
                        LegacyImportFailure(legacy_device_id, "", str(error))
                    )
                    continue
                for manifest_path in sorted(snapshots_directory.iterdir()):
                    if manifest_path.suffix != ".json":
                        continue
                    snapshot_id = manifest_path.stem
                    try:
                        info, existed = self._import_original_manifest(
                            source,
                            legacy_device_id,
                            snapshot_id,
                            manifest_path,
                            assignments=assignments,
                        )
                    except (BackupError, OriginalArchiveFormatError, OSError) as error:
                        failures.append(
                            LegacyImportFailure(
                                legacy_device_id,
                                snapshot_id,
                                str(error),
                            )
                        )
                    else:
                        (already_imported if existed else imported).append(info)
            with suppress(BackupError, OSError):
                self._garbage_collect()
        return LegacyImportResult(
            imported=tuple(imported),
            already_imported=tuple(already_imported),
            failures=tuple(failures),
        )

    def _import_original_manifest(
        self,
        source_root: Path,
        legacy_device_id: str,
        legacy_snapshot_id: str,
        manifest_path: Path,
        *,
        assignments: dict[LegacyIdentityClaim, LegacyImportIdentityAssignment],
    ) -> tuple[SnapshotInfo, bool]:
        manifest_bytes = self._read_source_file(
            source_root,
            manifest_path,
            max_bytes=_MAX_CATALOG_BYTES,
        )
        manifest = decode_original_manifest(
            manifest_bytes,
            expected_snapshot_id=legacy_snapshot_id,
            expected_device_id=legacy_device_id,
        )
        existing = self._find_legacy_imports(manifest)
        legacy_identity = LegacyIdentityClaim.from_original_key(legacy_device_id)
        assignment = (
            assignments.get(legacy_identity)
            if manifest.identity_state is not SnapshotIdentityState.UNSTABLE
            else None
        )
        key = (
            assignment.archive_key
            if assignment is not None
            else ArchiveKey.for_legacy(legacy_device_id)
        )
        identity_state = (
            SnapshotIdentityState.NATIVE
            if assignment is not None
            else manifest.identity_state
        )
        identity = (
            assignment.identity if assignment is not None else BackupDeviceIdentity()
        )
        stage = Path(tempfile.mkdtemp(prefix="import-", dir=self._staging_root))
        native_files: list[NativeManifestFile] = []
        try:
            for index, entry in enumerate(manifest.files, start=1):
                staged = stage / f"{index:08d}.object"
                self._copy_original_object(
                    source_root,
                    legacy_device_id,
                    entry.content,
                    staged,
                )
                self._publish_object(staged, entry.content)
                native_files.append(
                    NativeManifestFile(
                        path_parts=entry.path_parts,
                        content=entry.content,
                        modified_ns=entry.modified_ns,
                    )
                )
            if (
                self._read_source_file(
                    source_root,
                    manifest_path,
                    max_bytes=_MAX_CATALOG_BYTES,
                )
                != manifest_bytes
            ):
                raise BackupError(
                    "The Original catalog changed while it was being imported"
                )
            if existing:
                if assignment is not None:
                    assigned = self._assign_legacy_import_identity(existing, assignment)
                    return self._snapshot_info(assigned), True
                return self._snapshot_info(existing[0]), True

            if assignment is not None:
                self._validate_capture_archive(key, identity)
            snapshot_id = self._available_import_id(key, legacy_snapshot_id)
            sequence = self._next_sequence(key)
            encoded = encode_manifest(
                snapshot_id=snapshot_id,
                timestamp=manifest.timestamp,
                sequence=sequence,
                archive_key=key,
                device_name=manifest.device_name,
                metadata=manifest.metadata,
                identity_state=identity_state,
                identity=identity,
                legacy_identity_claim=legacy_identity,
                reason=BackupReason.IMPORT,
                note=manifest.note,
                files=tuple(native_files),
                legacy_source=LegacySource(
                    version=manifest.version,
                    device_identity=legacy_identity,
                    snapshot_id=legacy_snapshot_id,
                    catalog_sha256=manifest.catalog_sha256,
                ),
            )
            _require_payload_size(
                encoded,
                max_bytes=_MAX_CATALOG_BYTES,
                label="Native Backup catalog",
            )
            path = self._manifest_path(key, snapshot_id)
            self._ensure_native_directory(path.parent)
            AtomicHostFile(path).create_bytes(encoded)
            try:
                published = self._read_manifest(key, snapshot_id)
            except Exception:
                path.unlink(missing_ok=True)
                _flush_directory(path.parent)
                raise
            return self._snapshot_info(published), False
        finally:
            self._remove_owned_tree(stage, self._staging_root)

    @staticmethod
    def _legacy_import_assignments(
        assignments: tuple[LegacyImportIdentityAssignment, ...],
    ) -> dict[LegacyIdentityClaim, LegacyImportIdentityAssignment]:
        result: dict[LegacyIdentityClaim, LegacyImportIdentityAssignment] = {}
        for assignment in assignments:
            existing = result.get(assignment.legacy_identity_claim)
            if existing is not None and existing != assignment:
                raise BackupError(
                    "A Legacy Backup Import identity has conflicting assignments"
                )
            result[assignment.legacy_identity_claim] = assignment
        return result

    def _assign_legacy_import_identity(
        self,
        manifests: tuple[NativeManifest, ...],
        assignment: LegacyImportIdentityAssignment,
    ) -> NativeManifest:
        native = tuple(
            manifest
            for manifest in manifests
            if manifest.identity_state is SnapshotIdentityState.NATIVE
        )
        if any(not item.identity.matches(assignment.identity) for item in native):
            raise BackupError(
                "An imported Original snapshot is assigned to another Backup Identifier"
            )
        assigned = next(
            (item for item in native if item.archive_key == assignment.archive_key),
            None,
        )
        if assigned is None:
            assigned = self._publish_assigned_legacy_import(manifests[0], assignment)
        removed_directories: set[Path] = set()
        assigned_path = self._manifest_path(
            assigned.archive_key,
            assigned.snapshot_id,
        )
        for manifest in manifests:
            path = self._manifest_path(manifest.archive_key, manifest.snapshot_id)
            if path == assigned_path:
                continue
            path.unlink()
            removed_directories.add(path.parent)
        for directory in removed_directories:
            _flush_directory(directory)
        return assigned

    def _publish_assigned_legacy_import(
        self,
        manifest: NativeManifest,
        assignment: LegacyImportIdentityAssignment,
    ) -> NativeManifest:
        self._validate_capture_archive(assignment.archive_key, assignment.identity)
        snapshot_id = self._available_import_id(
            assignment.archive_key,
            manifest.snapshot_id,
        )
        sequence = self._next_sequence(assignment.archive_key)
        encoded = encode_manifest(
            snapshot_id=snapshot_id,
            timestamp=manifest.timestamp,
            sequence=sequence,
            archive_key=assignment.archive_key,
            device_name=manifest.device_name,
            metadata=manifest.metadata,
            identity_state=SnapshotIdentityState.NATIVE,
            identity=assignment.identity,
            legacy_identity_claim=manifest.legacy_identity_claim,
            reason=manifest.reason,
            note=manifest.note,
            files=manifest.files,
            legacy_source=manifest.legacy_source,
        )
        path = self._manifest_path(assignment.archive_key, snapshot_id)
        self._ensure_native_directory(path.parent)
        AtomicHostFile(path).create_bytes(encoded)
        try:
            published = self._read_manifest(assignment.archive_key, snapshot_id)
        except Exception:
            path.unlink(missing_ok=True)
            _flush_directory(path.parent)
            raise
        return published

    def _find_legacy_imports(
        self,
        source: OriginalManifest,
    ) -> tuple[NativeManifest, ...]:
        source_identity = LegacyIdentityClaim.from_original_key(source.device_id)
        matches: list[NativeManifest] = []
        for manifest in self._all_manifests(require_all_valid=False):
            legacy = manifest.legacy_source
            if (
                legacy is not None
                and legacy.version == source.version
                and legacy.device_identity == source_identity
                and legacy.snapshot_id == source.snapshot_id
                and legacy.catalog_sha256 == source.catalog_sha256
            ):
                matches.append(manifest)
        return tuple(matches)

    def _copy_original_object(
        self,
        source_root: Path,
        legacy_device_id: str,
        content: ContentIdentity,
        staged: Path,
    ) -> None:
        candidates = (
            source_root / "blobs" / content.sha256[:2] / content.sha256,
            source_root
            / legacy_device_id
            / "blobs"
            / content.sha256[:2]
            / content.sha256,
        )
        errors: list[str] = []
        for candidate in candidates:
            if not os.path.lexists(candidate):
                continue
            try:
                self._copy_verified_source_file(source_root, candidate, staged, content)
                return
            except (BackupError, OSError) as error:
                staged.unlink(missing_ok=True)
                errors.append(str(error))
        detail = f": {'; '.join(errors)}" if errors else ""
        raise BackupError(
            f"Original object is missing or corrupt: {content.sha256}{detail}"
        )

    @classmethod
    def _copy_verified_source_file(
        cls,
        source_root: Path,
        source: Path,
        destination: Path,
        content: ContentIdentity,
    ) -> None:
        cls._require_source_file(source_root, source)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        source_descriptor = os.open(source, flags)
        destination_descriptor = -1
        try:
            before = os.fstat(source_descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise BackupError(f"Original object is not a regular file: {source}")
            destination_descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            digest = hashlib.sha256()
            copied = 0
            with (
                os.fdopen(source_descriptor, "rb") as source_stream,
                os.fdopen(destination_descriptor, "wb") as target_stream,
            ):
                source_descriptor = -1
                destination_descriptor = -1
                while chunk := source_stream.read(_COPY_CHUNK_SIZE):
                    target_stream.write(chunk)
                    digest.update(chunk)
                    copied += len(chunk)
                after = os.fstat(source_stream.fileno())
                target_stream.flush()
                os.fsync(target_stream.fileno())
            if _stat_identity(before) != _stat_identity(after):
                raise BackupError(f"Original object changed while imported: {source}")
            if copied != content.size or digest.hexdigest() != content.sha256:
                raise BackupError(f"Original object failed verification: {source}")
        finally:
            if source_descriptor >= 0:
                os.close(source_descriptor)
            if destination_descriptor >= 0:
                os.close(destination_descriptor)

    @classmethod
    def _read_source_file(
        cls,
        source_root: Path,
        path: Path,
        *,
        max_bytes: int,
    ) -> bytes:
        cls._require_source_file(source_root, path)
        return _read_bounded_regular_file(
            path,
            max_bytes=max_bytes,
            label="Original Backup catalog",
        )

    @classmethod
    def _require_source_file(cls, source_root: Path, path: Path) -> None:
        cls._require_source_path(source_root, path, require_directory=False)

    @classmethod
    def _require_source_directory(cls, source_root: Path, path: Path) -> None:
        cls._require_source_path(source_root, path, require_directory=True)

    @staticmethod
    def _require_source_path(
        source_root: Path, path: Path, *, require_directory: bool
    ) -> None:
        try:
            relative = path.relative_to(source_root)
        except ValueError as error:
            raise BackupError(
                "Original source path escapes its selected root"
            ) from error
        current = source_root
        for component in relative.parts:
            current /= component
            if _is_link_or_reparse(current):
                raise BackupError(f"Original source crosses an unsafe link: {current}")
        metadata = os.lstat(path)
        expected = stat.S_ISDIR if require_directory else stat.S_ISREG
        if not expected(metadata.st_mode):
            kind = "directory" if require_directory else "regular file"
            raise BackupError(f"Original source is not a {kind}: {path}")

    def _available_import_id(self, key: ArchiveKey, preferred: str) -> str:
        try:
            path = self._manifest_path(key, preferred)
        except BackupError:
            preferred = "legacy-snapshot"
            path = self._manifest_path(key, preferred)
        if not path.exists():
            return preferred
        for suffix in range(2, 100_000):
            candidate = f"{preferred}-import-{suffix}"
            if not self._manifest_path(key, candidate).exists():
                return candidate
        raise BackupError("Could not allocate a native ID for the imported snapshot")

    def _next_sequence(self, key: ArchiveKey) -> int:
        highest = 0
        for path in self._manifest_paths(key):
            with suppress(BackupError):
                highest = max(highest, self._read_manifest(key, path.stem).sequence)
        return highest + 1

    def begin_restore_recovery(
        self,
        *,
        target_archive_key: ArchiveKey | str,
        safety_archive_key: ArchiveKey | str,
        current_identity: BackupDeviceIdentity,
        target_snapshot_id: str,
        safety_snapshot_id: str,
        operation_journal: DevicePath,
        recovery_material_identity: str,
    ) -> RestoreRecoveryRecord:
        """Publish the Host recovery anchor before Storage publication begins."""

        if not current_identity.is_stable:
            raise BackupError("Restore recovery requires a current Backup Identifier")
        with self._locked():
            self._prepare_repository()
            if any(
                record.outcome is RestoreRecoveryOutcome.UNRESOLVED
                for record in self.list_restore_recoveries()
            ):
                raise BackupRecoveryRequiredError(
                    "Another restore has unresolved recovery state"
                )
            target_key = self._coerce_existing_key(target_archive_key)
            safety_key = self._coerce_existing_key(safety_archive_key)
            target = self._read_manifest(target_key, target_snapshot_id)
            if target.identity_state is SnapshotIdentityState.UNSTABLE:
                raise BackupError(
                    "An explicitly unstable imported snapshot cannot restore"
                )
            if (
                target.identity_state is SnapshotIdentityState.NATIVE
                and not target.identity.matches(current_identity)
            ):
                raise BackupError(
                    "The target snapshot belongs to another Backup Identifier"
                )
            safety = self._read_manifest(safety_key, safety_snapshot_id)
            if (
                safety.identity_state is not SnapshotIdentityState.NATIVE
                or not safety.identity.matches(current_identity)
                or safety.reason is not BackupReason.PRE_RESTORE_SAFETY
            ):
                raise BackupError(
                    "Restore safety snapshot does not match this Backup Identifier"
                )
            with self.open_verified_snapshot(target_key, target_snapshot_id):
                pass
            with self.open_verified_snapshot(
                safety_key, safety_snapshot_id
            ) as verified:
                if verified.recovery_material_identity != recovery_material_identity:
                    raise BackupError(
                        "Restore recovery material identity does not match"
                    )

            now = datetime.now(UTC).isoformat()
            record = RestoreRecoveryRecord(
                id=uuid.uuid4().hex,
                target_archive_key=target_key,
                safety_archive_key=safety_key,
                current_identity=current_identity,
                target_snapshot_id=target_snapshot_id,
                safety_snapshot_id=safety_snapshot_id,
                operation_journal=operation_journal,
                recovery_material_identity=recovery_material_identity,
                phase=RestoreRecoveryPhase.SAFETY_PINNED,
                outcome=RestoreRecoveryOutcome.UNRESOLVED,
                created_at=now,
                updated_at=now,
            )
            path = self._recovery_path(record.id)
            AtomicHostFile(path).create_bytes(_encode_bounded_recovery(record))
            return self._read_recovery(record.id)

    def list_restore_recoveries(self) -> tuple[RestoreRecoveryRecord, ...]:
        with self._locked():
            if not os.path.lexists(self.native_root):
                return ()
            self._assert_repository_readable()
            if not os.path.lexists(self._recoveries_root):
                return ()
            self._require_native_directory(self._recoveries_root)
            records: list[RestoreRecoveryRecord] = []
            reconciled = False
            for path in sorted(self._recoveries_root.iterdir()):
                if path.suffix != ".json":
                    continue
                record = self._read_recovery(path.stem)
                if record.outcome is not RestoreRecoveryOutcome.UNRESOLVED:
                    path.unlink()
                    reconciled = True
                    continue
                records.append(record)
            if reconciled:
                _flush_directory(self._recoveries_root)
            return tuple(records)

    def advance_restore_recovery(
        self,
        recovery_id: str,
        phase: RestoreRecoveryPhase,
    ) -> RestoreRecoveryRecord:
        with self._locked():
            record = self._read_recovery(recovery_id)
            if record.outcome is not RestoreRecoveryOutcome.UNRESOLVED:
                raise BackupError("A resolved restore recovery cannot advance")
            if not self._valid_recovery_transition(record.phase, phase):
                raise BackupError(
                    f"Invalid restore recovery transition: {record.phase} to {phase}"
                )
            updated = update_recovery_phase(
                record,
                phase,
                updated_at=datetime.now(UTC).isoformat(),
            )
            AtomicHostFile(self._recovery_path(recovery_id)).replace_bytes(
                _encode_bounded_recovery(updated)
            )
            return self._read_recovery(recovery_id)

    def clear_restore_recovery(
        self,
        recovery_id: str,
        outcome: RestoreRecoveryOutcome,
    ) -> None:
        """Clear only after the caller verifies completion or recovery."""

        if outcome is RestoreRecoveryOutcome.UNRESOLVED:
            raise BackupError("Unresolved restore recovery cannot be cleared")
        with self._locked():
            record = self._read_recovery(recovery_id)
            if record.outcome not in {RestoreRecoveryOutcome.UNRESOLVED, outcome}:
                raise BackupError("Restore recovery has a conflicting terminal outcome")
            path = self._recovery_path(recovery_id)
            if record.outcome is RestoreRecoveryOutcome.UNRESOLVED:
                terminal = replace(
                    record,
                    outcome=outcome,
                    updated_at=datetime.now(UTC).isoformat(),
                )
                AtomicHostFile(path).replace_bytes(_encode_bounded_recovery(terminal))
                self._read_recovery(recovery_id)
            path.unlink()
            _flush_directory(path.parent)

    @staticmethod
    def _valid_recovery_transition(
        current: RestoreRecoveryPhase,
        requested: RestoreRecoveryPhase,
    ) -> bool:
        if current is requested:
            return True
        if requested is RestoreRecoveryPhase.RECOVERY_REQUIRED:
            return True
        allowed = {
            RestoreRecoveryPhase.SAFETY_PINNED: {
                RestoreRecoveryPhase.DEVICE_TRANSACTION_PUBLISHED
            },
            RestoreRecoveryPhase.DEVICE_TRANSACTION_PUBLISHED: {
                RestoreRecoveryPhase.APPLYING
            },
            RestoreRecoveryPhase.APPLYING: {RestoreRecoveryPhase.VERIFYING},
        }
        return requested in allowed.get(current, set())

    def update_note(
        self, archive_key: ArchiveKey | str, snapshot_id: str, note: str
    ) -> None:
        normalized = note.strip()
        if len(normalized) > _MAX_NOTE_LENGTH:
            raise BackupError(
                f"A backup note cannot exceed {_MAX_NOTE_LENGTH:,} characters"
            )
        with self._locked():
            key = self._coerce_existing_key(archive_key)
            manifest = self._read_manifest(key, snapshot_id)
            if snapshot_id in self._pinned_snapshot_ids(key):
                raise BackupRecoveryRequiredError(
                    "An unresolved restore pins this snapshot and its note"
                )
            updated = replace_note(manifest, normalized)
            _require_payload_size(
                updated,
                max_bytes=_MAX_CATALOG_BYTES,
                label="Native Backup catalog",
            )
            AtomicHostFile(self._manifest_path(key, snapshot_id)).replace_bytes(updated)
            self._read_manifest(key, snapshot_id)

    def delete_snapshot(self, archive_key: ArchiveKey | str, snapshot_id: str) -> None:
        with self._locked():
            key = self._coerce_existing_key(archive_key)
            self._read_manifest(key, snapshot_id)
            if snapshot_id in self._pinned_snapshot_ids(key):
                raise BackupRecoveryRequiredError(
                    "An unresolved restore pins this Backup Snapshot"
                )
            # Every catalog must be valid before any catalog may stop authorizing GC.
            self._all_manifests(require_all_valid=True)
            path = self._manifest_path(key, snapshot_id)
            path.unlink()
            _flush_directory(path.parent)
            self._garbage_collect()

    def export_snapshot(
        self,
        archive_key: ArchiveKey | str,
        snapshot_id: str,
        destination_parent: Path,
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCheck | None = None,
    ) -> BackupExportResult:
        parent = Path(os.path.abspath(destination_parent))
        if self._paths_overlap(parent, self.root):
            raise BackupPathOverlapError(
                "Export destination must be outside the backup repository"
            )
        with self.open_verified_snapshot(archive_key, snapshot_id) as snapshot:
            self._validate_export_paths(snapshot.files)
            parent.mkdir(parents=True, exist_ok=True)
            self._require_regular_directory(parent)
            export_root = self._new_export_directory(parent, snapshot_id)
            try:
                total = len(snapshot.files)
                total_size = 0
                for index, entry in enumerate(snapshot.files, start=1):
                    self._check_cancelled(cancelled)
                    target = export_root.joinpath(*entry.path_parts)
                    self._ensure_export_directory(export_root, target.parent)
                    self._copy_export_file(
                        Path(os.fspath(entry.source)),
                        target,
                        entry.content,
                        entry.modified_ns,
                    )
                    total_size += entry.content.size
                    self._emit(
                        progress,
                        BackupStage.EXPORTING,
                        index,
                        total,
                        source_text(
                            "Exporting {index} of {total} files…",
                            index=f"{index:,}",
                            total=f"{total:,}",
                        ),
                        "/".join(entry.path_parts),
                    )
                return BackupExportResult(export_root, total, total_size)
            except Exception:
                self._remove_owned_tree(export_root, parent)
                raise

    def restore_snapshot(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise BackupError(
            "Restore requires the application restore coordinator and a bounded "
            "Storage transaction; use open_verified_snapshot()"
        )

    def archive_path(self, archive_key: ArchiveKey | str = "") -> Path:
        if not archive_key:
            return self.native_root
        return self._archive_dir(
            archive_key
            if isinstance(archive_key, ArchiveKey)
            else ArchiveKey(archive_key)
        )

    def _prepare_repository(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._require_regular_directory(self.root)
        if os.path.lexists(self.native_root):
            self._require_regular_directory(self.native_root)
            if not os.path.lexists(self._marker_path):
                if any(self.native_root.iterdir()):
                    raise BackupError("Backup Archive v4 has no identity marker")
                AtomicHostFile(self._marker_path).create_bytes(
                    repository_marker_bytes()
                )
            self._assert_repository_readable()
        else:
            self.native_root.mkdir()
            self._require_regular_directory(self.native_root)
            AtomicHostFile(self._marker_path).create_bytes(repository_marker_bytes())
        for directory in (
            self._archives_root,
            self._objects_root,
            self._staging_root,
            self._recoveries_root,
        ):
            self._ensure_native_directory(directory)

    def _assert_repository_readable(self) -> None:
        self._require_regular_directory(self.native_root)
        if os.path.lexists(self._marker_path) and (
            _is_link_or_reparse(self._marker_path) or not self._marker_path.is_file()
        ):
            raise BackupError("The Backup Archive v4 marker is unsafe")
        if not os.path.lexists(self._marker_path):
            raise BackupError("Backup Archive v4 has no identity marker")
        marker = _read_bounded_regular_file(
            self._marker_path,
            max_bytes=_MAX_REPOSITORY_MARKER_BYTES,
            label="Native Backup repository marker",
        )
        try:
            validate_repository_marker(marker)
        except NativeArchiveFormatError as error:
            raise BackupError(str(error)) from error

    @staticmethod
    def _require_regular_directory(path: Path) -> None:
        try:
            if _is_link_or_reparse(path) or not path.is_dir():
                raise BackupError(f"Unsafe Backup Archive directory: {path}")
        except OSError as error:
            raise BackupError(
                f"Could not inspect Backup Archive path {path}: {error}"
            ) from error

    def _require_native_directory(self, path: Path) -> None:
        """Reject a native path if any repository-relative ancestor is unsafe."""

        try:
            relative = path.relative_to(self.native_root)
        except ValueError as error:
            raise BackupError(
                f"Backup Archive path escapes the v4 repository: {path}"
            ) from error
        current = self.native_root
        self._require_regular_directory(current)
        for component in relative.parts:
            current /= component
            self._require_regular_directory(current)

    def _ensure_native_directory(self, path: Path) -> None:
        """Create native directories one level at a time after checking ancestors."""

        try:
            relative = path.relative_to(self.native_root)
        except ValueError as error:
            raise BackupError(
                f"Backup Archive path escapes the v4 repository: {path}"
            ) from error
        current = self.native_root
        self._require_regular_directory(current)
        for component in relative.parts:
            current /= component
            if not os.path.lexists(current):
                current.mkdir()
                _flush_directory(current.parent)
            self._require_regular_directory(current)

    def _archive_keys(self) -> tuple[ArchiveKey, ...]:
        if not os.path.lexists(self._archives_root):
            return ()
        self._require_native_directory(self._archives_root)
        result: list[ArchiveKey] = []
        for path in sorted(self._archives_root.iterdir(), key=lambda item: item.name):
            if _is_link_or_reparse(path):
                raise BackupError(f"Unsafe Backup Archive path: {path}")
            if not path.is_dir():
                continue
            try:
                result.append(ArchiveKey(path.name))
            except ValueError as error:
                raise BackupError(
                    f"Invalid Backup Archive directory: {path.name}"
                ) from error
        return tuple(result)

    def _archive_dir(self, key: ArchiveKey) -> Path:
        return self._archives_root / key.value

    def _manifest_path(self, key: ArchiveKey, snapshot_id: str) -> Path:
        if (
            not snapshot_id
            or Path(snapshot_id).name != snapshot_id
            or snapshot_id in {".", ".."}
        ):
            raise BackupError(f"Invalid Backup Snapshot ID: {snapshot_id!r}")
        return self._archive_dir(key) / "snapshots" / f"{snapshot_id}.json"

    def _manifest_paths(self, key: ArchiveKey) -> tuple[Path, ...]:
        archive_directory = self._archive_dir(key)
        if not os.path.lexists(archive_directory):
            return ()
        self._require_native_directory(archive_directory)
        directory = archive_directory / "snapshots"
        if not os.path.lexists(directory):
            return ()
        self._require_native_directory(directory)
        result: list[tuple[int, str, Path]] = []
        for path in directory.iterdir():
            if _is_link_or_reparse(path):
                raise BackupError(f"Unsafe Backup Snapshot path: {path}")
            if not path.is_file() or path.suffix != ".json":
                continue
            try:
                manifest = self._read_manifest(key, path.stem)
                result.append((manifest.sequence, manifest.timestamp, path))
            except BackupError:
                result.append((-1, path.stem, path))
        return tuple(
            path
            for _, _, path in sorted(result, key=lambda item: item[:2], reverse=True)
        )

    def _read_manifest(self, key: ArchiveKey, snapshot_id: str) -> NativeManifest:
        path = self._manifest_path(key, snapshot_id)
        try:
            self._require_native_directory(path.parent)
            if _is_link_or_reparse(path) or not path.is_file():
                raise BackupError(f"Unsafe or missing Backup Snapshot: {snapshot_id}")
            data = _read_bounded_regular_file(
                path,
                max_bytes=_MAX_CATALOG_BYTES,
                label="Native Backup catalog",
            )
            return decode_manifest(
                data,
                expected_snapshot_id=snapshot_id,
                expected_archive_key=key,
            )
        except BackupError:
            raise
        except (NativeArchiveFormatError, OSError) as error:
            raise BackupError(
                f"Invalid Backup Snapshot {snapshot_id}: {error}"
            ) from error

    def _latest_valid_manifest(self, key: ArchiveKey) -> NativeManifest | None:
        for path in self._manifest_paths(key):
            try:
                return self._read_manifest(key, path.stem)
            except BackupError:
                continue
        return None

    def _archive_identity(self, key: ArchiveKey) -> BackupDeviceIdentity | None:
        paths = self._manifest_paths(key)
        if not paths:
            return None
        found: BackupDeviceIdentity | None = None
        for path in paths:
            manifest = self._read_manifest(key, path.stem)
            if manifest.identity_state is not SnapshotIdentityState.NATIVE:
                continue
            if found is not None and not found.matches(manifest.identity):
                raise BackupError("A Backup Archive contains conflicting identities")
            found = BackupDeviceIdentity(
                (
                    *(found.claims if found is not None else ()),
                    *manifest.identity.claims,
                )
            )
        return found

    def _validate_capture_archive(
        self,
        key: ArchiveKey,
        identity: BackupDeviceIdentity,
    ) -> None:
        for path in self._manifest_paths(key):
            manifest = self._read_manifest(key, path.stem)
            if identity.is_stable:
                if (
                    manifest.identity_state is not SnapshotIdentityState.NATIVE
                    or not manifest.identity.matches(identity)
                ):
                    raise BackupError(
                        "The selected Backup Archive belongs to another identity class"
                    )
            elif manifest.identity_state is not SnapshotIdentityState.UNSTABLE:
                raise BackupError(
                    "An unstable capture cannot share an identified Backup Archive"
                )

    def _coerce_existing_key(self, value: ArchiveKey | str) -> ArchiveKey:
        if isinstance(value, ArchiveKey):
            return value
        try:
            direct = ArchiveKey(value)
        except ValueError as error:
            raise BackupError(str(error)) from error
        if self._archive_dir(direct).exists():
            return direct
        # Transitional lookup for callers that still pass a raw product serial.
        with suppress(ValueError):
            identity = BackupDeviceIdentity(
                (
                    BackupIdentityClaim.from_hardware(
                        BackupIdentityClaimKind.PRODUCT_SERIAL, value
                    ),
                )
            )
            for key in self._archive_keys():
                existing = self._archive_identity(key)
                if existing is not None and existing.matches(identity):
                    return key
        return direct

    @staticmethod
    def _coerce_capture_identity(
        identity: BackupDeviceIdentity | None,
        *,
        device_id: str | None,
        identity_is_stable: bool | None,
    ) -> BackupDeviceIdentity:
        if identity is not None:
            return identity
        if identity_is_stable and device_id:
            return BackupDeviceIdentity(
                (
                    BackupIdentityClaim.from_hardware(
                        BackupIdentityClaimKind.PRODUCT_SERIAL, device_id
                    ),
                )
            )
        return BackupDeviceIdentity()

    def _object_path(self, digest: str) -> Path:
        return self._objects_root / digest[:2] / digest

    def _recovery_path(self, recovery_id: str) -> Path:
        if len(recovery_id) != 32 or any(
            character not in "0123456789abcdef" for character in recovery_id
        ):
            raise BackupError(f"Invalid restore recovery ID: {recovery_id!r}")
        return self._recoveries_root / f"{recovery_id}.json"

    def _read_recovery(self, recovery_id: str) -> RestoreRecoveryRecord:
        path = self._recovery_path(recovery_id)
        try:
            self._require_native_directory(path.parent)
            if _is_link_or_reparse(path) or not path.is_file():
                raise BackupError(f"Unsafe or missing restore recovery: {recovery_id}")
            return decode_recovery(
                _read_bounded_regular_file(
                    path,
                    max_bytes=_MAX_RECOVERY_RECORD_BYTES,
                    label="Restore Recovery record",
                ),
                expected_id=recovery_id,
            )
        except BackupError:
            raise
        except (OSError, RestoreRecoveryFormatError) as error:
            raise BackupError(
                f"Invalid restore recovery record {recovery_id}: {error}"
            ) from error

    def _pinned_snapshot_ids(self, key: ArchiveKey) -> set[str]:
        pinned: set[str] = set()
        for record in self.list_restore_recoveries():
            if record.outcome is not RestoreRecoveryOutcome.UNRESOLVED:
                continue
            if record.target_archive_key == key:
                pinned.add(record.target_snapshot_id)
            if record.safety_archive_key == key:
                pinned.add(record.safety_snapshot_id)
        return pinned

    def _publish_object(self, staged: Path, content: ContentIdentity) -> None:
        if (
            staged.stat().st_size != content.size
            or _hash_file(staged) != content.sha256
        ):
            raise BackupError("A staged Backup object failed verification")
        destination = self._object_path(content.sha256)
        self._ensure_native_directory(destination.parent)
        if os.path.lexists(destination):
            if _is_link_or_reparse(destination) or not destination.is_file():
                raise BackupError(f"Unsafe Backup object path: {destination}")
            if (
                destination.stat().st_size == content.size
                and _hash_file(destination) == content.sha256
            ):
                staged.unlink()
                return
            os.replace(staged, destination)
            _flush_directory(destination.parent)
            if _hash_file(destination) != content.sha256:
                raise BackupError("A corrupt Backup object could not be repaired")
            return
        try:
            os.link(staged, destination)
            _flush_directory(destination.parent)
            staged.unlink()
        except FileExistsError:
            self._publish_object(staged, content)
        except OSError:
            descriptor = -1
            try:
                descriptor = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                with staged.open("rb") as source, os.fdopen(descriptor, "wb") as target:
                    descriptor = -1
                    shutil.copyfileobj(source, target, _COPY_CHUNK_SIZE)
                    target.flush()
                    os.fsync(target.fileno())
                _flush_directory(destination.parent)
                staged.unlink()
            except FileExistsError:
                if descriptor >= 0:
                    os.close(descriptor)
                self._publish_object(staged, content)
            except Exception:
                if descriptor >= 0:
                    os.close(descriptor)
                with suppress(OSError):
                    destination.unlink(missing_ok=True)
                raise

    def _verify_object(
        self, path: Path, content: ContentIdentity, *, checked: set[str]
    ) -> None:
        if content.sha256 in checked:
            return
        try:
            self._require_native_directory(path.parent)
            if _is_link_or_reparse(path) or not path.is_file():
                raise BackupError(
                    f"Backup object is missing or unsafe: {content.sha256}"
                )
            if (
                path.stat().st_size != content.size
                or _hash_file(path) != content.sha256
            ):
                raise BackupError(
                    f"Backup object is missing or corrupt: {content.sha256}"
                )
        except BackupError:
            raise
        except OSError as error:
            raise BackupError(
                f"Could not verify Backup object {content.sha256}: {error}"
            ) from error
        checked.add(content.sha256)

    def _object_is_reusable(self, content: ContentIdentity) -> bool:
        """Trust a previously verified object when its safe shape is unchanged."""

        path = self._object_path(content.sha256)
        if not os.path.lexists(path):
            return False
        try:
            self._require_native_directory(path.parent)
            if _is_link_or_reparse(path) or not path.is_file():
                raise BackupError(f"Unsafe Backup object path: {path}")
            return path.stat().st_size == content.size
        except BackupError:
            raise
        except OSError as error:
            raise BackupError(
                f"Could not inspect Backup object {content.sha256}: {error}"
            ) from error

    @staticmethod
    def _enumerate(session: FilesystemSession) -> tuple[DeviceEntry, ...]:
        try:
            return enumerate_backup_files(session)
        except UnsupportedBackupEntryError as error:
            raise BackupError(str(error)) from error

    @staticmethod
    def _entry_state(
        entries: tuple[DeviceEntry, ...],
    ) -> tuple[tuple[tuple[str, ...], int, int], ...]:
        return tuple(
            (entry.path.parts, entry.size, entry.modified_ns) for entry in entries
        )

    def _next_snapshot_identity(self, key: ArchiveKey) -> tuple[str, int, str]:
        sequence = 1
        for path in self._manifest_paths(key):
            with suppress(BackupError):
                sequence = max(
                    sequence, self._read_manifest(key, path.stem).sequence + 1
                )
        now = datetime.now(UTC)
        timestamp = now.isoformat()
        base = now.strftime("%Y%m%dT%H%M%S.%fZ")
        snapshot_id = f"{base}-{sequence:08d}"
        while self._manifest_path(key, snapshot_id).exists():
            sequence += 1
            snapshot_id = f"{base}-{sequence:08d}"
        return snapshot_id, sequence, timestamp

    @staticmethod
    def _snapshot_info(manifest: NativeManifest) -> SnapshotInfo:
        return SnapshotInfo(
            id=manifest.snapshot_id,
            timestamp=manifest.timestamp,
            device_id=manifest.archive_key.value,
            device_name=manifest.device_name,
            file_count=len(manifest.files),
            total_size=manifest.total_size,
            reason=manifest.reason,
            note=manifest.note,
            metadata=manifest.metadata,
            has_backup_identifier=(
                manifest.identity_state is SnapshotIdentityState.NATIVE
            ),
            identity_state=manifest.identity_state,
            legacy_identity_claim=manifest.legacy_identity_claim,
        )

    @staticmethod
    def _delta(
        older: tuple[NativeManifestFile, ...], newer: tuple[NativeManifestFile, ...]
    ) -> tuple[int, int, int]:
        old = {entry.path_parts: entry.content for entry in older}
        new = {entry.path_parts: entry.content for entry in newer}
        added = len(new.keys() - old.keys())
        removed = len(old.keys() - new.keys())
        changed = sum(old[path] != new[path] for path in old.keys() & new.keys())
        return added, removed, changed

    def _prune(
        self,
        key: ArchiveKey,
        maximum: int,
        preserve: str,
        *,
        safety_only: bool,
    ) -> None:
        if maximum <= 0:
            return
        valid: list[NativeManifest] = []
        for path in self._manifest_paths(key):
            manifest = self._read_manifest(key, path.stem)
            if (manifest.reason is BackupReason.PRE_RESTORE_SAFETY) is safety_only:
                valid.append(manifest)
        pinned = self._pinned_snapshot_ids(key)
        removed = False
        for manifest in valid[maximum:]:
            if manifest.snapshot_id != preserve and manifest.snapshot_id not in pinned:
                self._manifest_path(key, manifest.snapshot_id).unlink()
                removed = True
        if removed:
            _flush_directory(self._archive_dir(key) / "snapshots")
        self._garbage_collect()

    def _all_manifests(self, *, require_all_valid: bool) -> tuple[NativeManifest, ...]:
        manifests: list[NativeManifest] = []
        for key in self._archive_keys():
            for path in self._manifest_paths(key):
                try:
                    manifests.append(self._read_manifest(key, path.stem))
                except BackupError as error:
                    if require_all_valid:
                        raise BackupError(
                            "Garbage collection is blocked by an invalid Backup catalog"
                        ) from error
        return tuple(manifests)

    def _garbage_collect(self) -> None:
        referenced = {
            entry.content.sha256
            for manifest in self._all_manifests(require_all_valid=True)
            for entry in manifest.files
        }
        if not os.path.lexists(self._objects_root):
            return
        self._require_native_directory(self._objects_root)
        for bucket in self._objects_root.iterdir():
            if _is_link_or_reparse(bucket) or not bucket.is_dir():
                raise BackupError(f"Unsafe Backup object bucket: {bucket}")
            for path in bucket.iterdir():
                if _is_link_or_reparse(path) or not path.is_file():
                    raise BackupError(f"Unsafe Backup object path: {path}")
                if path.name not in referenced:
                    path.unlink()
            with suppress(OSError):
                bucket.rmdir()

    def _reconcile_staging(self) -> None:
        if not os.path.lexists(self._staging_root):
            return
        self._require_native_directory(self._staging_root)
        for path in self._staging_root.iterdir():
            self._remove_owned_tree(path, self._staging_root)
        self._garbage_collect()

    @staticmethod
    def _remove_owned_tree(path: Path, parent: Path) -> None:
        if not os.path.lexists(path):
            return
        try:
            resolved_parent = parent.resolve(strict=True)
            if path.parent.resolve(strict=True) != resolved_parent:
                raise BackupError(f"Refusing to remove path outside {parent}")
            if _is_link_or_reparse(path):
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as error:
            raise BackupError(f"Could not clean owned path {path}: {error}") from error

    @staticmethod
    def _paths_overlap(first: Path, second: Path) -> bool:
        first = first.resolve(strict=False)
        second = second.resolve(strict=False)
        try:
            first.relative_to(second)
            return True
        except ValueError:
            pass
        try:
            second.relative_to(first)
            return True
        except ValueError:
            return False

    @staticmethod
    def _validate_export_paths(files: tuple[VerifiedSnapshotFile, ...]) -> None:
        paths = {entry.path_parts for entry in files}
        for parts in paths:
            if any(parts[:depth] in paths for depth in range(1, len(parts))):
                raise BackupError("A Backup catalog nests a file beneath another file")
            if os.name == "nt":
                for part in parts:
                    stem = part.split(".", maxsplit=1)[0].casefold()
                    if (
                        part.endswith((" ", "."))
                        or stem in _WINDOWS_RESERVED_EXPORT_NAMES
                        or any(
                            ord(character) < 32
                            or character in _WINDOWS_INVALID_EXPORT_CHARACTERS
                            for character in part
                        )
                    ):
                        raise BackupError(
                            "A Backup path cannot be exported safely on Windows: "
                            + "/".join(parts)
                        )
        canonical_paths = {
            tuple(
                unicodedata.normalize("NFC", component.casefold())
                for component in parts
            )
            for parts in paths
        }
        if len(canonical_paths) != len(paths):
            raise BackupError(
                "The Backup catalog contains case-equivalent export paths"
            )
        if any(
            parts[:depth] in canonical_paths
            for parts in canonical_paths
            for depth in range(1, len(parts))
        ):
            raise BackupError(
                "The Backup catalog contains a file beneath a case-equivalent path"
            )

    @staticmethod
    def _ensure_export_directory(root: Path, directory: Path) -> None:
        try:
            relative = directory.relative_to(root)
        except ValueError as error:
            raise BackupError("An export path escapes its new directory") from error
        current = root
        for component in ("", *relative.parts):
            if component:
                current /= component
                try:
                    current.mkdir()
                    _flush_directory(current.parent)
                except FileExistsError:
                    pass
            try:
                metadata = os.lstat(current)
            except OSError as error:
                raise BackupError(
                    f"Could not inspect export directory {current}: {error}"
                ) from error
            if _metadata_is_link_or_reparse(metadata) or not stat.S_ISDIR(
                metadata.st_mode
            ):
                raise BackupError(f"Unsafe export directory: {current}")

    @staticmethod
    def _copy_export_file(
        source: Path,
        target: Path,
        content: ContentIdentity,
        modified_ns: int | None,
    ) -> None:
        descriptor = -1
        try:
            with _open_regular_file(source) as source_stream:
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                digest = hashlib.sha256()
                copied = 0
                with os.fdopen(descriptor, "wb") as target_stream:
                    descriptor = -1
                    while chunk := source_stream.read(_COPY_CHUNK_SIZE):
                        target_stream.write(chunk)
                        digest.update(chunk)
                        copied += len(chunk)
                    if copied != content.size or digest.hexdigest() != content.sha256:
                        raise BackupError("An exported file failed verification")
                    target_stream.flush()
                    os.fsync(target_stream.fileno())
                    if modified_ns is not None:
                        if os.utime in os.supports_fd:
                            os.utime(
                                target_stream.fileno(),
                                ns=(modified_ns, modified_ns),
                            )
                        else:
                            os.utime(target, ns=(modified_ns, modified_ns))
                        os.fsync(target_stream.fileno())
            if (
                target.stat().st_size != content.size
                or _hash_file(target) != content.sha256
            ):
                raise BackupError("An exported file failed final verification")
            _flush_directory(target.parent)
        except FileExistsError as error:
            raise BackupError(
                f"An export destination appeared during the operation: {target}"
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _new_export_directory(parent: Path, snapshot_id: str) -> Path:
        normalized = unicodedata.normalize("NFKC", snapshot_id)
        readable = "".join(
            character if character.isalnum() or character in {"-", ".", "_"} else "_"
            for character in normalized
        )
        readable = readable.strip(" ._")[:80].rstrip(" .") or "snapshot"
        identity = hashlib.sha256(
            snapshot_id.encode("utf-8", errors="surrogatepass")
        ).hexdigest()[:10]
        base = f"iOpenPod Export - {readable} - {identity}"
        for suffix in range(10_000):
            candidate = parent / (base if suffix == 0 else f"{base} ({suffix})")
            try:
                candidate.mkdir()
                _flush_directory(parent)
                return candidate
            except FileExistsError:
                continue
        raise BackupError("Could not allocate a unique export directory")

    @staticmethod
    def _check_cancelled(cancelled: CancellationCheck | None) -> None:
        if cancelled is not None and cancelled():
            raise BackupCancelledError("Backup cancelled before publication")

    @staticmethod
    def _emit(
        callback: ProgressCallback | None,
        stage: BackupStage,
        current: int,
        total: int,
        message: str,
        current_file: str = "",
        *,
        can_cancel: bool = True,
        completed_bytes: int = 0,
        total_bytes: int = 0,
    ) -> None:
        if callback is not None:
            callback(
                BackupProgress(
                    stage,
                    current,
                    total,
                    message,
                    current_file,
                    can_cancel,
                    completed_bytes,
                    total_bytes,
                )
            )


__all__ = [
    "BackupCancelledError",
    "BackupError",
    "BackupPathOverlapError",
    "BackupRecoveryRequiredError",
    "BackupRepository",
    "BackupRestoreIncompleteError",
]
