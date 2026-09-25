"""Application orchestration for Backup capture, import, export, and restore."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

from iOpenPod.app.backups.models import (
    ArchiveKey,
    BackupCatalog,
    BackupDeviceContext,
    BackupDeviceInfo,
    BackupInventory,
    BackupProgress,
    BackupReason,
    BackupStage,
    ContentIdentity,
    LegacyImportIdentityAssignment,
    LegacyImportResult,
    RestoreRecoveryOutcome,
    RestoreRecoveryPhase,
    RestoreRecoveryRecord,
    SnapshotIdentityState,
    SnapshotInfo,
    VerifiedSnapshot,
)
from iOpenPod.app.backups.outcomes import (
    BackupDiagnostic,
    BackupFailure,
    BackupFailureCode,
    BackupImportCounts,
    CaptureCancelled,
    CaptureCreated,
    CaptureFailed,
    CaptureOutcome,
    CaptureUnchanged,
    ExportCancelled,
    ExportCompleted,
    ExportFailed,
    ExportOutcome,
    ImportCancelled,
    ImportCompleted,
    ImportFailed,
    ImportOutcome,
    RestoreCancelled,
    RestoreCompleted,
    RestoreDurabilityPending,
    RestoreIncomplete,
    RestoreOutcome,
    RestorePreMutationFailure,
    RestoreRecovered,
    RestoreUnchanged,
)
from iOpenPod.app.backups.repository import (
    BackupCancelledError,
    BackupError,
    BackupPathOverlapError,
    BackupRecoveryRequiredError,
    BackupRepository,
)
from iOpenPod.app.backups.scope import enumerate_backup_files
from iOpenPod.app.services.device_coordinator import (
    DeviceAccessError,
    DeviceChangedError,
)
from storage import (
    AccessMode,
    ConcurrentModificationError,
    DeviceBusyError,
    DevicePath,
    DevicePathNotFoundError,
    FileContent,
    FilePrecondition,
    FilePreconditionError,
    FilesystemSession,
    FilesystemSessionError,
    FlushResult,
    HostPathOnPhysicalDeviceError,
    MountInspectionError,
    ReadOnlyFilesystemError,
    StorageCapacityError,
    StorageTransaction,
    TransactionDurabilityPendingError,
    TransactionInterruptedError,
    TransactionPreparedError,
    TransactionProgress,
    TransactionRecovery,
    TransactionRecoveryFile,
    TransactionRecoveryMaterial,
    TransactionRemoval,
    TransactionState,
    TransactionWrite,
    VolumeDisconnectedError,
    VolumeIdentityChangedError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from storage import FileFingerprint

logger = logging.getLogger(__name__)

type ProgressCallback = Callable[[BackupProgress], None]
type CancellationCheck = Callable[[], bool]


class BackupService:
    """Coordinate Host archives with one identity-bound Filesystem Session."""

    def __init__(self, devices: DeviceCoordinator) -> None:
        self._devices = devices

    def inventory(self, backup_root: Path) -> BackupInventory:
        self._devices.require_backup_host_paths(backup_root)
        repository = BackupRepository(backup_root)
        connected = self._devices.backup_device_context()
        archived = {
            device.device_id: replace(
                device,
                connected=(
                    connected is not None
                    and self._archive_matches_context(repository, device, connected)
                ),
            )
            for device in repository.list_devices()
        }
        connected_id = ""
        if connected is not None:
            matching = tuple(
                device_id for device_id, device in archived.items() if device.connected
            )
            if matching:
                connected_id = matching[0]
            else:
                preferred = self._preferred_archive_key(repository, connected)
                connected_id = preferred.value
                archived[preferred.value] = BackupDeviceInfo(
                    preferred.value,
                    connected.display_name,
                    0,
                    connected.metadata,
                    connected.has_backup_identifier,
                    connected=True,
                    identity_state=(
                        SnapshotIdentityState.NATIVE
                        if connected.identity.is_stable
                        else SnapshotIdentityState.UNSTABLE
                    ),
                )
        devices = tuple(
            sorted(
                archived.values(),
                key=lambda item: (
                    not item.connected,
                    item.device_name.casefold(),
                    item.device_id,
                ),
            )
        )
        return BackupInventory(
            devices,
            connected_id,
            repository.list_restore_recoveries(),
        )

    def catalog(self, backup_root: Path, device_id: str) -> BackupCatalog:
        self._devices.require_backup_host_paths(backup_root)
        repository = BackupRepository(backup_root)
        catalog = repository.catalog(device_id)
        connected = self._devices.backup_device_context()
        if connected is None or not self._archive_matches_context(
            repository, catalog.device, connected
        ):
            return catalog
        return replace(
            catalog,
            device=replace(
                catalog.device,
                device_name=connected.display_name,
                metadata=connected.metadata,
                has_backup_identifier=connected.has_backup_identifier,
                connected=True,
                identity_state=(
                    SnapshotIdentityState.NATIVE
                    if not catalog.snapshots and connected.identity.is_stable
                    else catalog.device.identity_state
                ),
            ),
        )

    def create_snapshot(
        self,
        backup_root: Path,
        expected: ActiveIPod,
        *,
        max_backups: int,
        reason: BackupReason = BackupReason.MANUAL,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCheck | None = None,
        force: bool = False,
    ) -> CaptureOutcome:
        repository = BackupRepository(backup_root)
        try:
            with self._devices.backup_session(
                expected,
                repository.root,
                access=AccessMode.READ_ONLY,
            ) as (context, session):
                snapshot = repository.create_snapshot(
                    session,
                    identity=context.identity,
                    archive_key=context.archive_key,
                    device_name=context.display_name,
                    metadata=context.metadata,
                    reason=reason,
                    max_backups=max(0, max_backups),
                    force=force,
                    progress=progress,
                    cancelled=cancelled,
                )
                if snapshot is not None:
                    return CaptureCreated(snapshot)
                key = context.archive_key or repository.resolve_archive_key(
                    context.identity
                )
                latest = next(
                    (item for item in repository.list_snapshots(key) if item.is_valid),
                    None,
                )
                if latest is None:
                    raise BackupError(
                        "An unchanged capture has no verified prior snapshot"
                    )
                return CaptureUnchanged(latest.id)
        except BackupCancelledError:
            return CaptureCancelled()
        except Exception as error:
            return CaptureFailed(backup_failure_for(error, operation="capture"))

    def import_original(
        self,
        backup_root: Path,
        source_root: Path,
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCheck | None = None,
    ) -> ImportOutcome:
        """Import Original v2/v3 input; cancellation is accepted only preflight."""

        try:
            if cancelled is not None and cancelled():
                return ImportCancelled()
            self._devices.require_backup_host_paths(backup_root, source_root)
            _emit(
                progress,
                BackupStage.SCANNING,
                0,
                0,
                "Validating the Original Backup Archive…",
                can_cancel=False,
            )
            repository = BackupRepository(backup_root)
            connected = self._devices.backup_device_context()
            assignments: tuple[LegacyImportIdentityAssignment, ...] = ()
            if connected is not None and connected.identity.is_stable:
                archive_key = self._preferred_archive_key(repository, connected)
                assignments = tuple(
                    LegacyImportIdentityAssignment(
                        legacy_identity_claim=claim,
                        archive_key=archive_key,
                        identity=connected.identity,
                    )
                    for claim in connected.legacy_identity_claims
                )
            result = repository.import_original(
                source_root,
                identity_assignments=assignments,
            )
            if result.failures and not (result.imported or result.already_imported):
                detail = "\n".join(
                    f"{item.legacy_device_id}/{item.snapshot_id}: {item.detail}"
                    for item in result.failures
                )
                return ImportFailed(
                    BackupFailure(
                        BackupFailureCode.ARCHIVE_INVALID,
                        "No trusted Original Backup Snapshots could be imported.",
                        "Keep the Original archive unchanged, review the diagnostics, "
                        "and retry after repairing or recopying it.",
                        detail,
                    )
                )
            outcome = _import_outcome(result)
            completed = outcome.imported.snapshots + outcome.already_present.snapshots
            _emit(
                progress,
                BackupStage.COMPLETE,
                completed,
                completed,
                "Original Backup import complete.",
                can_cancel=False,
            )
            return outcome
        except BackupCancelledError:
            return ImportCancelled()
        except Exception as error:
            return ImportFailed(backup_failure_for(error, operation="import"))

    def restore_snapshot(
        self,
        backup_root: Path,
        expected: ActiveIPod,
        *,
        device_id: str,
        snapshot_id: str,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCheck | None = None,
        legacy_confirmed: bool = False,
    ) -> RestoreOutcome:
        repository = BackupRepository(backup_root)
        safety: SnapshotInfo | None = None
        recovery_id = ""
        journal_path: DevicePath | None = None
        transaction_complete = False
        try:
            with self._devices.backup_session(
                expected,
                repository.root,
                access=AccessMode.READ_WRITE,
            ) as (context, session):
                if repository.list_restore_recoveries():
                    return RestorePreMutationFailure(
                        snapshot_id,
                        BackupFailure(
                            BackupFailureCode.ARCHIVE_BUSY,
                            "A previous restore still requires recovery.",
                            "Recover the interrupted restore before starting another one.",
                        ),
                    )
                with repository.open_verified_snapshot(
                    device_id, snapshot_id
                ) as target:
                    authorization = _restore_authorization(
                        context,
                        target,
                        legacy_confirmed=legacy_confirmed,
                    )
                    if authorization is not None:
                        return RestorePreMutationFailure(snapshot_id, authorization)
                    _check_cancelled(cancelled)
                    safety = repository.create_snapshot(
                        session,
                        identity=context.identity,
                        archive_key=context.archive_key,
                        device_name=context.display_name,
                        metadata=context.metadata,
                        reason=BackupReason.PRE_RESTORE_SAFETY,
                        force=True,
                        progress=progress,
                        cancelled=cancelled,
                    )
                    if safety is None:
                        raise BackupError(
                            "The forced restore safety snapshot was not created"
                        )
                    with repository.open_verified_snapshot(
                        safety.device_id, safety.id
                    ) as verified_safety:
                        journal_identity = uuid.uuid4().hex
                        plan = _restore_plan(
                            session,
                            target,
                            verified_safety,
                            journal_identity=journal_identity,
                        )
                        if not plan.writes and not plan.removals:
                            return RestoreUnchanged(snapshot_id, safety.id)

                        journal_path = DevicePath(
                            f".iopenpod-recovery/{journal_identity}/transaction.json"
                        )
                        recovery = repository.begin_restore_recovery(
                            target_archive_key=target.archive_key,
                            safety_archive_key=verified_safety.archive_key,
                            current_identity=context.identity,
                            target_snapshot_id=target.snapshot_id,
                            safety_snapshot_id=verified_safety.snapshot_id,
                            operation_journal=journal_path,
                            recovery_material_identity=(
                                verified_safety.recovery_material_identity
                            ),
                        )
                        recovery_id = recovery.id
                        result = session.execute_transaction(
                            plan,
                            checkpoint=lambda: _check_cancelled(cancelled),
                            progress=lambda value: _restore_progress(
                                repository,
                                recovery.id,
                                value,
                                progress,
                            ),
                        )
                        transaction_complete = True
                        repository.advance_restore_recovery(
                            recovery.id, RestoreRecoveryPhase.VERIFYING
                        )
                        _require_snapshot_matches(session, target)
                        final_flush = session.finalize_transaction(result.recovery)
                        repository.clear_restore_recovery(
                            recovery.id,
                            RestoreRecoveryOutcome.VERIFIED_COMPLETION,
                        )
                        return RestoreCompleted(snapshot_id, safety.id, final_flush)
        except BackupCancelledError:
            if recovery_id:
                _clear_unpublished_recovery(repository, recovery_id)
            return RestoreCancelled(
                snapshot_id,
                safety_snapshot_id=safety.id if safety is not None else None,
            )
        except TransactionPreparedError as error:
            if recovery_id:
                _mark_recovery_required(repository, recovery_id)
            return _incomplete_restore(
                snapshot_id, safety, error.facts.journal_path, error
            )
        except TransactionDurabilityPendingError as error:
            if recovery_id:
                _mark_recovery_required(repository, recovery_id)
            if error.facts.content_verified and safety is not None:
                return RestoreDurabilityPending(
                    snapshot_id,
                    safety.id,
                    FlushResult(False, str(error)),
                )
            return _incomplete_restore(
                snapshot_id, safety, error.facts.journal_path, error
            )
        except TransactionInterruptedError as error:
            if recovery_id:
                _mark_recovery_required(repository, recovery_id)
            return _incomplete_restore(
                snapshot_id, safety, error.facts.journal_path, error
            )
        except Exception as error:
            if recovery_id and transaction_complete:
                _mark_recovery_required(repository, recovery_id)
                if safety is not None and journal_path is not None:
                    return RestoreIncomplete(
                        snapshot_id,
                        safety.id,
                        journal_path,
                        backup_failure_for(error, operation="restore"),
                    )
            elif recovery_id:
                _clear_unpublished_recovery(repository, recovery_id)
            return RestorePreMutationFailure(
                snapshot_id,
                backup_failure_for(error, operation="restore"),
                safety_snapshot_id=safety.id if safety is not None else None,
            )

    def recover_restore(
        self,
        backup_root: Path,
        expected: ActiveIPod,
        *,
        recovery_id: str,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCheck | None = None,
    ) -> RestoreOutcome:
        """Resolve one durable restore record by completion or verified rollback."""

        repository = BackupRepository(backup_root)
        try:
            record = next(
                (
                    item
                    for item in repository.list_restore_recoveries()
                    if item.id == recovery_id
                ),
                None,
            )
            if record is None:
                return RestorePreMutationFailure(
                    recovery_id,
                    BackupFailure(
                        BackupFailureCode.ARCHIVE_INVALID,
                        "The selected Restore Recovery record no longer exists.",
                        "Refresh Backups before choosing a recovery action.",
                    ),
                )
            if cancelled is not None and cancelled():
                return _pending_recovery_outcome(
                    record.target_snapshot_id,
                    record.safety_snapshot_id,
                    record.operation_journal,
                    "Restore Recovery was cancelled before it started.",
                )
            with self._devices.backup_session(
                expected,
                repository.root,
                access=AccessMode.READ_WRITE,
            ) as (context, session):
                if not context.identity.matches(record.current_identity):
                    return RestorePreMutationFailure(
                        record.target_snapshot_id,
                        BackupFailure(
                            BackupFailureCode.DEVICE_IDENTITY_MISMATCH,
                            "The connected iPod is not the device in this Restore Recovery.",
                            "Connect the interrupted iPod, refresh Devices, and recover it before any other write.",
                        ),
                        safety_snapshot_id=record.safety_snapshot_id,
                    )
                with (
                    repository.open_verified_snapshot(
                        record.target_archive_key,
                        record.target_snapshot_id,
                    ) as target,
                    repository.open_verified_snapshot(
                        record.safety_archive_key,
                        record.safety_snapshot_id,
                    ) as safety,
                ):
                    try:
                        observed = session.inspect_transaction(record.operation_journal)
                    except DevicePathNotFoundError:
                        return _resolve_missing_recovery_journal(
                            repository,
                            record.id,
                            session,
                            record.operation_journal,
                            target,
                            safety,
                        )
                    if (
                        observed.recovery_material_identity
                        != record.recovery_material_identity
                    ):
                        raise FilePreconditionError(
                            "The device journal does not match the Host recovery record"
                        )
                    if observed.state is TransactionState.COMMITTED:
                        _require_snapshot_matches(session, target)
                        flush = session.finalize_transaction(observed)
                        repository.clear_restore_recovery(
                            record.id,
                            RestoreRecoveryOutcome.VERIFIED_COMPLETION,
                        )
                        return RestoreCompleted(
                            target.snapshot_id,
                            safety.snapshot_id,
                            flush,
                        )
                    if observed.state is TransactionState.RESTORED:
                        _require_snapshot_matches(session, safety)
                        flush = session.finalize_transaction(observed)
                        repository.clear_restore_recovery(
                            record.id,
                            RestoreRecoveryOutcome.VERIFIED_RECOVERY,
                        )
                        return RestoreRecovered(
                            target.snapshot_id,
                            safety.snapshot_id,
                            flush,
                        )
                    material = _recovery_material(safety, observed)
                    _emit(
                        progress,
                        BackupStage.APPLYING,
                        0,
                        len(observed.files),
                        "Recovering the interrupted restore…",
                        can_cancel=False,
                    )
                    restored = session.restore_transaction(
                        observed,
                        recovery_material=material,
                        progress=lambda value: _emit(
                            progress,
                            BackupStage.APPLYING,
                            value.completed,
                            value.total,
                            "Recovering the interrupted restore…",
                            str(value.path) if value.path is not None else "",
                            can_cancel=False,
                        ),
                    )
                    _require_snapshot_matches(session, safety)
                    flush = session.finalize_transaction(restored.recovery)
                    repository.clear_restore_recovery(
                        record.id,
                        RestoreRecoveryOutcome.VERIFIED_RECOVERY,
                    )
                    return RestoreRecovered(
                        target.snapshot_id,
                        safety.snapshot_id,
                        flush,
                    )
        except TransactionDurabilityPendingError as error:
            _mark_recovery_required(repository, recovery_id)
            retained = _retained_recovery(repository, recovery_id)
            if retained is not None and error.facts.content_verified:
                return RestoreDurabilityPending(
                    retained.target_snapshot_id,
                    retained.safety_snapshot_id,
                    FlushResult(False, str(error)),
                )
            if retained is not None:
                return _pending_recovery_outcome(
                    retained.target_snapshot_id,
                    retained.safety_snapshot_id,
                    retained.operation_journal,
                    str(error),
                )
            return RestorePreMutationFailure(
                recovery_id,
                backup_failure_for(error, operation="recovery"),
            )
        except Exception as error:
            _mark_recovery_required(repository, recovery_id)
            retained = _retained_recovery(repository, recovery_id)
            if retained is not None:
                return RestoreIncomplete(
                    retained.target_snapshot_id,
                    retained.safety_snapshot_id,
                    retained.operation_journal,
                    backup_failure_for(error, operation="recovery"),
                )
            return RestorePreMutationFailure(
                recovery_id,
                backup_failure_for(error, operation="recovery"),
            )

    def update_note(
        self,
        backup_root: Path,
        device_id: str,
        snapshot_id: str,
        note: str,
    ) -> None:
        self._devices.require_backup_host_paths(backup_root)
        BackupRepository(backup_root).update_note(device_id, snapshot_id, note)

    def delete_snapshot(
        self,
        backup_root: Path,
        device_id: str,
        snapshot_id: str,
    ) -> None:
        self._devices.require_backup_host_paths(backup_root)
        BackupRepository(backup_root).delete_snapshot(device_id, snapshot_id)

    def export_snapshot(
        self,
        backup_root: Path,
        device_id: str,
        snapshot_id: str,
        destination: Path,
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCheck | None = None,
    ) -> ExportOutcome:
        try:
            self._devices.require_backup_host_paths(backup_root, destination)
            result = BackupRepository(backup_root).export_snapshot(
                device_id,
                snapshot_id,
                destination,
                progress=progress,
                cancelled=cancelled,
            )
            return ExportCompleted(result)
        except BackupCancelledError:
            return ExportCancelled()
        except Exception as error:
            return ExportFailed(backup_failure_for(error, operation="export"))

    @staticmethod
    def archive_path(backup_root: Path, device_id: str = "") -> Path:
        return BackupRepository(backup_root).archive_path(device_id)

    @staticmethod
    def _preferred_archive_key(
        repository: BackupRepository,
        context: BackupDeviceContext,
    ) -> ArchiveKey:
        if context.archive_key is not None:
            return context.archive_key
        return repository.resolve_archive_key(context.identity)

    @classmethod
    def _archive_matches_context(
        cls,
        repository: BackupRepository,
        device: BackupDeviceInfo,
        context: BackupDeviceContext,
    ) -> bool:
        if device.snapshot_count == 0:
            return (
                cls._preferred_archive_key(repository, context).value
                == device.device_id
            )
        if device.identity_state is SnapshotIdentityState.NATIVE:
            return (
                context.identity.is_stable
                and cls._preferred_archive_key(repository, context).value
                == device.device_id
            )
        if device.identity_state in {
            SnapshotIdentityState.LEGACY_ASSERTED,
            SnapshotIdentityState.LEGACY_UNKNOWN,
        }:
            return any(
                snapshot.legacy_identity_claim in context.legacy_identity_claims
                for snapshot in repository.list_snapshots(device.device_id)
                if snapshot.is_valid
            )
        return (
            context.archive_key is not None
            and context.archive_key.value == device.device_id
        )


def _restore_authorization(
    context: BackupDeviceContext,
    target: VerifiedSnapshot,
    *,
    legacy_confirmed: bool,
) -> BackupFailure | None:
    if not context.identity.is_stable:
        return BackupFailure(
            BackupFailureCode.DEVICE_IDENTITY_UNSTABLE,
            "This iPod does not currently have a Backup Identifier.",
            "Reconnect it and refresh Devices before attempting a restore.",
        )
    if target.identity_state is SnapshotIdentityState.NATIVE:
        if target.identity.matches(context.identity):
            return None
        return BackupFailure(
            BackupFailureCode.DEVICE_IDENTITY_MISMATCH,
            "This Backup Snapshot belongs to a different iPod.",
            "Connect the iPod identified by this archive and try again.",
        )
    if target.identity_state in {
        SnapshotIdentityState.LEGACY_ASSERTED,
        SnapshotIdentityState.LEGACY_UNKNOWN,
    }:
        if (
            target.legacy_identity_claim is None
            or target.legacy_identity_claim not in context.legacy_identity_claims
        ):
            return BackupFailure(
                BackupFailureCode.DEVICE_IDENTITY_MISMATCH,
                "The connected iPod does not match this imported Original backup.",
                "Connect the iPod whose Original archive used this legacy identity.",
            )
        if legacy_confirmed:
            return None
        return BackupFailure(
            BackupFailureCode.DEVICE_IDENTITY_MISMATCH,
            "This imported Original backup cannot prove an exact hardware identity.",
            "Review the warning and explicitly confirm this restore for the connected iPod.",
        )
    return BackupFailure(
        BackupFailureCode.DEVICE_IDENTITY_UNSTABLE,
        "This snapshot has no usable Backup Identifier.",
        "Export its files for manual recovery; it cannot be restored destructively.",
    )


def _restore_plan(
    session: FilesystemSession,
    target: VerifiedSnapshot,
    safety: VerifiedSnapshot,
    *,
    journal_identity: str,
) -> StorageTransaction:
    entries = enumerate_backup_files(session)
    current_paths = {entry.path.parts: entry.path for entry in entries}
    safety_files = {file.path_parts: file for file in safety.files}
    target_files = {file.path_parts: file for file in target.files}
    if len(safety_files) != len(safety.files) or len(target_files) != len(target.files):
        raise BackupError("A Backup Snapshot contains duplicate paths")
    if set(current_paths) != set(safety_files):
        raise ConcurrentModificationError(
            "The iPod changed after its restore safety snapshot was captured"
        )

    current: dict[tuple[str, ...], FileFingerprint] = {}
    for parts, path in current_paths.items():
        fingerprint = session.fingerprint(path)
        saved = safety_files[parts]
        if not _content_matches(fingerprint, saved.content) or (
            saved.modified_ns is not None
            and not session.modified_time_matches(
                fingerprint.modified_ns, saved.modified_ns
            )
        ):
            raise ConcurrentModificationError(
                "The iPod changed after its restore safety snapshot was captured"
            )
        current[parts] = fingerprint

    writes: list[TransactionWrite] = []
    removals: list[TransactionRemoval] = []
    dependencies: list[FilePrecondition] = []
    recovery_files: list[TransactionRecoveryFile] = []
    for parts, saved in sorted(target_files.items()):
        path = DevicePath.from_parts(parts)
        before = current.get(parts)
        same = (
            before is not None
            and _content_matches(before, saved.content)
            and (
                saved.modified_ns is None
                or session.modified_time_matches(before.modified_ns, saved.modified_ns)
            )
        )
        if same:
            dependencies.append(FilePrecondition(path, before))
            continue
        writes.append(
            TransactionWrite(
                path,
                saved.source,
                _file_content(saved.content),
                expected=before,
                modified_ns=saved.modified_ns,
            )
        )
        if before is not None:
            recovery = safety_files[parts]
            recovery_files.append(
                TransactionRecoveryFile(
                    path,
                    recovery.source,
                    _file_content(recovery.content),
                    recovery.modified_ns,
                )
            )
    for parts in sorted(set(current) - set(target_files)):
        path = DevicePath.from_parts(parts)
        fingerprint = current[parts]
        removals.append(TransactionRemoval(path, fingerprint))
        recovery = safety_files[parts]
        recovery_files.append(
            TransactionRecoveryFile(
                path,
                recovery.source,
                _file_content(recovery.content),
                recovery.modified_ns,
            )
        )
    return StorageTransaction(
        tuple(writes),
        tuple(removals),
        tuple(dependencies),
        recovery_material=TransactionRecoveryMaterial(
            safety.recovery_material_identity,
            tuple(recovery_files),
        ),
        journal_identity=journal_identity,
    )


def _require_snapshot_matches(
    session: FilesystemSession,
    snapshot: VerifiedSnapshot,
) -> None:
    entries = enumerate_backup_files(session)
    expected = {file.path_parts: file for file in snapshot.files}
    if {entry.path.parts for entry in entries} != set(expected):
        raise FilePreconditionError(
            "The restored iPod file tree does not match the selected snapshot"
        )
    for entry in entries:
        fingerprint = session.fingerprint(entry.path)
        saved = expected[entry.path.parts]
        if not _content_matches(fingerprint, saved.content) or (
            saved.modified_ns is not None
            and not session.modified_time_matches(
                fingerprint.modified_ns, saved.modified_ns
            )
        ):
            raise FilePreconditionError(f"A restored file did not verify: {entry.path}")


def _snapshot_matches(
    session: FilesystemSession,
    snapshot: VerifiedSnapshot,
) -> bool:
    try:
        _require_snapshot_matches(session, snapshot)
    except FilePreconditionError:
        return False
    return True


def _resolve_missing_recovery_journal(
    repository: BackupRepository,
    recovery_id: str,
    session: FilesystemSession,
    journal_path: DevicePath,
    target: VerifiedSnapshot,
    safety: VerifiedSnapshot,
) -> RestoreOutcome:
    """Close the crash gap after cleanup or before journal publication."""

    if _snapshot_matches(session, target):
        flush = session.finalize_missing_transaction(journal_path)
        if not flush.complete:
            return RestoreDurabilityPending(
                target.snapshot_id,
                safety.snapshot_id,
                flush,
            )
        repository.clear_restore_recovery(
            recovery_id,
            RestoreRecoveryOutcome.VERIFIED_COMPLETION,
        )
        return RestoreCompleted(target.snapshot_id, safety.snapshot_id, flush)
    if _snapshot_matches(session, safety):
        flush = session.finalize_missing_transaction(journal_path)
        if not flush.complete:
            return RestoreDurabilityPending(
                target.snapshot_id,
                safety.snapshot_id,
                flush,
            )
        repository.clear_restore_recovery(
            recovery_id,
            RestoreRecoveryOutcome.VERIFIED_RECOVERY,
        )
        return RestoreRecovered(target.snapshot_id, safety.snapshot_id, flush)
    raise FilePreconditionError(
        "The recovery journal is missing and the iPod matches neither the "
        "target nor its safety snapshot"
    )


def _recovery_material(
    safety: VerifiedSnapshot,
    recovery: TransactionRecovery,
) -> TransactionRecoveryMaterial:
    by_path = {DevicePath.from_parts(file.path_parts): file for file in safety.files}
    required = recovery.recovery_material_paths
    if not required and recovery.recovery_material_identity:
        raise FilePreconditionError(
            "The transaction observation does not identify its required recovery files"
        )
    try:
        files = tuple(
            TransactionRecoveryFile(
                path,
                by_path[path].source,
                _file_content(by_path[path].content),
                by_path[path].modified_ns,
            )
            for path in required
        )
    except KeyError as error:
        raise FilePreconditionError(
            "The safety snapshot does not contain every required recovery file"
        ) from error
    return TransactionRecoveryMaterial(
        safety.recovery_material_identity,
        files,
    )


def _content_matches(
    fingerprint: FileFingerprint,
    content: ContentIdentity,
) -> bool:
    return fingerprint.size == content.size and fingerprint.sha256 == content.sha256


def _file_content(content: ContentIdentity) -> FileContent:
    return FileContent(content.size, content.sha256)


def _restore_progress(
    repository: BackupRepository,
    recovery_id: str,
    value: TransactionProgress,
    callback: ProgressCallback | None,
) -> None:
    if value.state is TransactionState.PREPARED:
        repository.advance_restore_recovery(
            recovery_id, RestoreRecoveryPhase.DEVICE_TRANSACTION_PUBLISHED
        )
    elif value.state is TransactionState.PUBLISHING:
        repository.advance_restore_recovery(recovery_id, RestoreRecoveryPhase.APPLYING)
    elif value.state is TransactionState.COMMITTED:
        repository.advance_restore_recovery(recovery_id, RestoreRecoveryPhase.VERIFYING)
    _emit(
        callback,
        BackupStage.APPLYING,
        value.completed,
        value.total,
        "Restoring the selected Backup Snapshot…",
        str(value.path) if value.path is not None else "",
        # Once a durable Operation Journal exists, shutdown/cancellation must
        # retain explicit recovery rather than promise a mutation-free stop.
        can_cancel=False,
    )


def _clear_unpublished_recovery(
    repository: BackupRepository,
    recovery_id: str,
) -> None:
    try:
        repository.clear_restore_recovery(
            recovery_id, RestoreRecoveryOutcome.VERIFIED_RECOVERY
        )
    except Exception:
        logger.exception("Could not clear an unpublished Backup restore recovery")


def _mark_recovery_required(
    repository: BackupRepository,
    recovery_id: str,
) -> None:
    try:
        repository.advance_restore_recovery(
            recovery_id, RestoreRecoveryPhase.RECOVERY_REQUIRED
        )
    except Exception:
        logger.exception("Could not mark Backup restore recovery as required")


def _retained_recovery(
    repository: BackupRepository,
    recovery_id: str,
) -> RestoreRecoveryRecord | None:
    try:
        return next(
            (
                item
                for item in repository.list_restore_recoveries()
                if item.id == recovery_id
            ),
            None,
        )
    except Exception:
        logger.exception("Could not inspect the retained Backup restore recovery")
        return None


def _incomplete_restore(
    snapshot_id: str,
    safety: SnapshotInfo | None,
    journal_path: DevicePath,
    error: Exception,
) -> RestoreOutcome:
    if safety is None:
        return RestorePreMutationFailure(
            snapshot_id,
            backup_failure_for(error, operation="restore"),
        )
    return RestoreIncomplete(
        snapshot_id,
        safety.id,
        journal_path,
        backup_failure_for(error, operation="restore"),
    )


def _pending_recovery_outcome(
    snapshot_id: str,
    safety_snapshot_id: str,
    journal_path: DevicePath,
    detail: str,
) -> RestoreIncomplete:
    return RestoreIncomplete(
        snapshot_id,
        safety_snapshot_id,
        journal_path,
        BackupFailure(
            BackupFailureCode.VERIFICATION_FAILED,
            "Restore Recovery is still required.",
            "Keep the iPod and Backup Archive connected, then run Restore Recovery again.",
            detail,
        ),
    )


def _check_cancelled(cancelled: CancellationCheck | None) -> None:
    if cancelled is not None and cancelled():
        raise BackupCancelledError("Backup operation cancelled before publication")


def _import_outcome(result: LegacyImportResult) -> ImportCompleted:
    diagnostics = tuple(
        BackupDiagnostic(
            "legacy.import_failed",
            f"Could not import {item.legacy_device_id}/{item.snapshot_id}.",
            item.detail,
        )
        for item in result.failures
    ) + tuple(
        BackupDiagnostic(
            "legacy.identity_unproven",
            f"{item.device_name or item.device_id} requires confirmation before restore.",
        )
        for item in (*result.imported, *result.already_imported)
        if item.requires_restore_confirmation
    )
    return ImportCompleted(
        _import_counts(result.imported),
        _import_counts(result.already_imported),
        diagnostics,
    )


def _import_counts(items: tuple[SnapshotInfo, ...]) -> BackupImportCounts:
    return BackupImportCounts(
        devices=len({item.device_id for item in items}),
        snapshots=len(items),
        content_items=sum(item.file_count for item in items),
    )


def _emit(
    callback: ProgressCallback | None,
    stage: BackupStage,
    current: int,
    total: int,
    message: str,
    current_file: str = "",
    *,
    can_cancel: bool,
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
            )
        )


def backup_failure_for(error: Exception, *, operation: str) -> BackupFailure:
    detail = str(error).strip() or type(error).__name__
    if isinstance(error, DeviceBusyError):
        return BackupFailure(
            BackupFailureCode.ARCHIVE_BUSY,
            "Another operation is using this backup or iPod.",
            "Let that operation finish, then retry.",
            detail,
        )
    if isinstance(error, StorageCapacityError):
        return BackupFailure(
            BackupFailureCode.INSUFFICIENT_SPACE,
            "There is not enough free space to complete this operation safely.",
            "Free space at the reported location and retry.",
            detail,
        )
    if isinstance(error, (DeviceChangedError, VolumeIdentityChangedError)):
        return BackupFailure(
            BackupFailureCode.DEVICE_CHANGED,
            "The Active iPod or its connection changed during the operation.",
            "Keep the iPod connected, refresh Devices, and retry. If restore had begun, recover it first.",
            detail,
        )
    if isinstance(
        error,
        (
            DeviceAccessError,
            FilesystemSessionError,
            VolumeDisconnectedError,
            ReadOnlyFilesystemError,
        ),
    ):
        cause = error.__cause__
        if isinstance(cause, (HostPathOnPhysicalDeviceError, MountInspectionError)):
            return BackupFailure(
                BackupFailureCode.UNSAFE_DESTINATION,
                "The backup location could not be proven safe for this iPod.",
                "Choose a folder on a different physical disk, then retry.",
                detail,
            )
        return BackupFailure(
            BackupFailureCode.DEVICE_UNAVAILABLE,
            "The iPod is not safely available for this operation.",
            "Reconnect it, refresh Devices, and retry.",
            detail,
        )
    if isinstance(error, TransactionPreparedError):
        return BackupFailure(
            BackupFailureCode.VERIFICATION_FAILED,
            "Restore preparation could not be completed safely.",
            "Keep the archive and iPod connected, then run Restore Recovery before any other write.",
            detail,
        )
    if isinstance(error, TransactionInterruptedError):
        return BackupFailure(
            BackupFailureCode.VERIFICATION_FAILED,
            "Restore stopped after it may have changed the iPod.",
            "Keep the archive and iPod connected, then run Restore Recovery before any other write.",
            detail,
        )
    if isinstance(error, (ConcurrentModificationError, FilePreconditionError)):
        return BackupFailure(
            BackupFailureCode.SOURCE_CHANGED,
            "A required file changed while the operation was running.",
            "Stop other software from using the iPod or archive, refresh, and retry.",
            detail,
        )
    if isinstance(error, HostPathOnPhysicalDeviceError):
        return BackupFailure(
            BackupFailureCode.UNSAFE_DESTINATION,
            "The selected location is on the same physical device as the iPod.",
            "Choose a folder on a different physical disk.",
            detail,
        )
    if isinstance(error, BackupPathOverlapError):
        return BackupFailure(
            BackupFailureCode.UNSAFE_DESTINATION,
            "The selected folder overlaps the active Backup Archive.",
            "Choose separate folders for the native archive, legacy source, and exported files.",
            detail,
        )
    if isinstance(error, BackupRecoveryRequiredError):
        return BackupFailure(
            BackupFailureCode.ARCHIVE_BUSY,
            "Restore Recovery must finish before this snapshot can change.",
            "Keep the iPod and archive connected, run Restore Recovery, then retry.",
            detail,
        )
    if isinstance(error, BackupError):
        return BackupFailure(
            BackupFailureCode.ARCHIVE_INVALID,
            "The Backup Archive could not be verified.",
            "Keep the archive unchanged, review its diagnostics, and retry or choose another archive.",
            detail,
        )
    if isinstance(error, OSError):
        return BackupFailure(
            BackupFailureCode.ARCHIVE_UNAVAILABLE,
            "The backup location is unavailable.",
            "Reconnect or choose the storage location, check free space and permissions, then retry.",
            detail,
        )
    logger.error(
        "Unexpected Backup %s failure: %s",
        operation,
        detail,
        exc_info=(type(error), error, error.__traceback__),
    )
    return BackupFailure(
        BackupFailureCode.UNEXPECTED,
        "The backup operation could not complete.",
        "Keep the iPod and backup connected, review diagnostics, and retry.",
    )


__all__ = ["BackupService", "backup_failure_for"]
