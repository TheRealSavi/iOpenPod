"""Recoverable ordered file publication behind the Filesystem Session interface.

This private implementation shares the session's internal filesystem primitives.
Targeted type-checker exceptions keep those primitives off the public interface.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from storage._filesystem import (
    COPY_CHUNK_SIZE,
    allocated_size,
    modified_time_matches,
    open_read_no_follow,
)
from storage._transaction_journal import (
    MAX_JOURNAL_BYTES,
    JournalDependency,
    JournalEntry,
    TransactionJournal,
    decode,
    encode,
    journal_root,
    validate_paths,
)
from storage.errors import (
    ConcurrentModificationError,
    FilePreconditionError,
    ReadOnlyFilesystemError,
    RecoverableWriteError,
    StorageOperationError,
    VolumeIdentityChangedError,
)
from storage.models import FileFingerprint, FlushResult
from storage.paths import DevicePath, HostPath
from storage.transactions import (
    FileContent,
    FilePrecondition,
    StorageTransaction,
    TransactionActivity,
    TransactionActivityPhase,
    TransactionDurabilityPendingError,
    TransactionFailureFacts,
    TransactionInterruptedError,
    TransactionJournalStatus,
    TransactionPreparedError,
    TransactionProgress,
    TransactionRecovery,
    TransactionRecoveryFile,
    TransactionRecoveryMaterial,
    TransactionResult,
    TransactionState,
    TransactionValidation,
    TransactionWrite,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage.session import FilesystemSession

logger = logging.getLogger(__name__)


def _activity(
    callback: Callable[[TransactionActivity], None] | None,
    phase: TransactionActivityPhase,
    completed: int = 0,
    total: int | None = None,
    path: DevicePath | None = None,
) -> None:
    if callback is not None:
        callback(TransactionActivity(phase, completed, total, path))


def _fingerprint(
    session: FilesystemSession, path: DevicePath
) -> FileFingerprint | None:
    return session.fingerprint(path) if session.exists(path) else None


def _content(fingerprint: FileFingerprint | None) -> FileContent | None:
    return None if fingerprint is None else FileContent.from_fingerprint(fingerprint)


def _check_preconditions(
    session: FilesystemSession,
    files: tuple[FilePrecondition, ...],
    *,
    activity: Callable[[TransactionActivity], None] | None = None,
) -> None:
    for index, file in enumerate(files):
        _activity(
            activity, TransactionActivityPhase.RECHECKING, index, len(files), file.path
        )
        if _fingerprint(session, file.path) != file.fingerprint:
            raise FilePreconditionError(
                f"Transaction source or destination changed: {file.path}"
            )


def _expected_content(
    session: FilesystemSession, path: DevicePath, content: FileContent | None
) -> FileFingerprint | None:
    fingerprint = _fingerprint(session, path)
    if _content(fingerprint) != content:
        raise FilePreconditionError(f"Transaction content did not verify: {path}")
    return fingerprint


def _expected_file(
    session: FilesystemSession,
    path: DevicePath,
    content: FileContent | None,
    modified_ns: int | None,
) -> FileFingerprint | None:
    fingerprint = _expected_content(session, path, content)
    if (
        fingerprint is not None
        and modified_ns is not None
        and not modified_time_matches(
            fingerprint.modified_ns,
            modified_ns,
            session.mounted_volume.volume.filesystem_type,
        )
    ):
        raise FilePreconditionError(
            f"Transaction modification time did not verify: {path}"
        )
    return fingerprint


def _matches_file(
    fingerprint: FileFingerprint | None,
    content: FileContent | None,
    modified_ns: int | None,
    filesystem_type: str,
) -> bool:
    return _content(fingerprint) == content and (
        fingerprint is None
        or modified_ns is None
        or modified_time_matches(fingerprint.modified_ns, modified_ns, filesystem_type)
    )


def _apply_modified_time(
    session: FilesystemSession,
    path: DevicePath,
    fingerprint: FileFingerprint,
    modified_ns: int | None,
) -> FileFingerprint:
    if modified_ns is None or modified_time_matches(
        fingerprint.modified_ns,
        modified_ns,
        session.mounted_volume.volume.filesystem_type,
    ):
        return fingerprint
    session._set_modified_time(  # pyright: ignore[reportPrivateUsage]
        path,
        modified_ns,
        expected=fingerprint,
    )
    result = session.fingerprint(path)
    if not modified_time_matches(
        result.modified_ns,
        modified_ns,
        session.mounted_volume.volume.filesystem_type,
    ):
        raise StorageOperationError(
            f"Transaction modification time could not be represented: {path}"
        )
    return result


def _host_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _verify_host_content(
    file: TransactionRecoveryFile | TransactionWrite,
    *,
    checkpoint: Callable[[], None] | None,
) -> None:
    if not isinstance(file.source, HostPath):
        return
    source = Path(os.fspath(file.source))
    with open_read_no_follow(source) as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.sha256()
        copied = 0
        while chunk := stream.read(COPY_CHUNK_SIZE):
            if checkpoint is not None:
                checkpoint()
            digest.update(chunk)
            copied += len(chunk)
        after = os.fstat(stream.fileno())
    if (
        _host_identity(before) != _host_identity(after)
        or copied != file.content.size
        or digest.hexdigest() != file.content.sha256
    ):
        raise ConcurrentModificationError(
            f"Transaction Host material did not verify: {source.name}"
        )


def _recovery_files(
    material: TransactionRecoveryMaterial,
) -> dict[DevicePath, TransactionRecoveryFile]:
    result: dict[DevicePath, TransactionRecoveryFile] = {}
    for file in material.files:
        if file.path in result:
            raise ValueError("Transaction recovery material contains duplicate paths")
        result[file.path] = file
    return result


def _validate_recovery_material(
    plan: StorageTransaction,
    *,
    checkpoint: Callable[[], None] | None,
) -> None:
    material = plan.recovery_material
    if material is None:
        return
    supplied = _recovery_files(material)
    expected = {
        write.path: write.expected
        for write in plan.writes
        if write.expected is not None
    }
    expected.update({removal.path: removal.expected for removal in plan.removals})
    if set(supplied) != set(expected):
        raise ValueError(
            "External recovery material must cover every prior transaction file"
        )
    for path, fingerprint in expected.items():
        file = supplied[path]
        if (
            file.content != FileContent.from_fingerprint(fingerprint)
            or file.modified_ns != fingerprint.modified_ns
        ):
            raise FilePreconditionError(
                f"External recovery material does not match {path}"
            )
        _verify_host_content(file, checkpoint=checkpoint)
    for write in plan.writes:
        _verify_host_content(write, checkpoint=checkpoint)


def _preconditions(plan: StorageTransaction) -> tuple[FilePrecondition, ...]:
    return (
        *(FilePrecondition(w.path, w.expected) for w in plan.writes),
        *(FilePrecondition(r.path, r.expected) for r in plan.removals),
        *plan.dependencies,
    )


def _journal(
    session: FilesystemSession, plan: StorageTransaction
) -> TransactionJournal:
    volume = session.mounted_volume
    record_metadata = plan.recovery_material is not None or any(
        write.modified_ns is not None for write in plan.writes
    )
    return TransactionJournal(
        volume.physical_device.id.value,
        volume.volume.id.value,
        TransactionState.STAGING,
        tuple(
            JournalEntry(
                write.path,
                _content(write.expected),
                write.content,
                write.expected.modified_ns
                if record_metadata and write.expected is not None
                else None,
                write.modified_ns,
            )
            for write in plan.writes
        )
        + tuple(
            JournalEntry(
                removal.path,
                _content(removal.expected),
                None,
                removal.expected.modified_ns if record_metadata else None,
            )
            for removal in plan.removals
        ),
        tuple(
            JournalDependency(f.path, _content(f.fingerprint))
            for f in plan.dependencies
        ),
        plan.recovery_material.identity if plan.recovery_material is not None else "",
    )


def _journal_allocation(journal: TransactionJournal, unit: int | None) -> int:
    return max(
        allocated_size(len(encode(replace(journal, state=state))), unit)
        for state in TransactionState
    )


def _external_staging_peak(plan: StorageTransaction, unit: int | None) -> int:
    """Return peak extra allocation while bounded writes publish in order."""

    committed_delta = 0
    peak = 0
    for write in plan.writes:
        after = allocated_size(write.content.size, unit)
        before = (
            allocated_size(write.expected.size, unit)
            if write.expected is not None
            else 0
        )
        peak = max(peak, committed_delta + after)
        committed_delta += after - before
    return peak


def validate(
    session: FilesystemSession,
    plan: StorageTransaction,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> TransactionValidation:
    observation = session._revalidate()  # pyright: ignore[reportPrivateUsage]
    capabilities = observation.volume.capabilities
    if not capabilities.safe_for_writes:
        raise ReadOnlyFilesystemError("This Volume cannot safely publish a transaction")
    if not plan.writes and not plan.removals:
        raise ValueError("A Storage transaction needs at least one file change")
    if plan.reserve_bytes < 0:
        raise ValueError("Transaction reserve must be nonnegative")
    files = _preconditions(plan)
    validate_paths(
        tuple(f.path for f in files), case_sensitive=capabilities.case_sensitive is True
    )
    _check_preconditions(session, files)
    for write in plan.writes:
        if isinstance(write.source, bytes) and (
            len(write.source) != write.content.size
            or hashlib.sha256(write.source).hexdigest() != write.content.sha256
        ):
            raise ConcurrentModificationError(
                f"Transaction input differs from captured content: {write.path}"
            )
        session._check_write_capacity(  # pyright: ignore[reportPrivateUsage]
            write.content.size,
            observation,
            reserve_bytes=0,
            display_name=write.path.name,
        )
    _validate_recovery_material(plan, checkpoint=checkpoint)
    unit = capabilities.allocation_unit_size
    journal_size = _journal_allocation(_journal(session, plan), unit)
    if plan.recovery_material is None:
        staged = sum(allocated_size(w.content.size, unit) for w in plan.writes)
        originals = sum(
            allocated_size(w.expected.size, unit)
            for w in plan.writes
            if w.expected is not None
        )
    else:
        staged = _external_staging_peak(plan, unit)
        originals = 0
    rollback = max(
        (
            allocated_size(f.fingerprint.size, unit)
            for f in files[: len(plan.writes) + len(plan.removals)]
            if f.fingerprint is not None
        ),
        default=0,
    )
    required = staged + originals + rollback + 3 * journal_size + plan.reserve_bytes
    session._check_write_capacity(  # pyright: ignore[reportPrivateUsage]
        0,
        observation,
        reserve_bytes=required,
        display_name="transaction staging and recovery",
    )
    logger.debug(
        "Storage transaction validated writes=%d removals=%d dependencies=%d required_bytes=%d",
        len(plan.writes),
        len(plan.removals),
        len(plan.dependencies),
        required,
    )
    return TransactionValidation(required)


def _persist(
    session: FilesystemSession,
    path: DevicePath,
    journal: TransactionJournal,
    expected: FileFingerprint | None,
) -> FileFingerprint:
    payload = encode(journal)
    result = session._atomic_publish(  # pyright: ignore[reportPrivateUsage]
        path,
        source_size=len(payload),
        chunks=(payload,),
        expected=expected,
        create_parents=True,
        reserve_bytes=0,
    )
    logger.debug(
        "Storage transaction journal=%s state=%s entries=%d",
        path,
        journal.state,
        len(journal.entries),
    )
    return result.fingerprint


def _backup(root: DevicePath, index: int) -> DevicePath:
    return root.joinpath(f"original-{index}.bin")


def _stage(root: DevicePath, index: int) -> DevicePath:
    return root.joinpath(f"staged-{index}.bin")


def _journal_path(plan: StorageTransaction) -> DevicePath:
    identity = plan.journal_identity or uuid.uuid4().hex
    return DevicePath(f".iopenpod-recovery/{identity}/transaction.json")


def _failure_facts(
    path: DevicePath,
    journal: TransactionJournal,
    *,
    publication_started: bool,
    content_verified: bool,
) -> TransactionFailureFacts:
    return TransactionFailureFacts(
        path,
        journal.state,
        publication_started,
        content_verified,
        journal.recovery_material_identity,
    )


def _require_complete_flush(
    result: FlushResult,
    path: DevicePath,
    journal: TransactionJournal,
    *,
    publication_started: bool,
    content_verified: bool,
) -> None:
    if result.complete:
        return
    facts = _failure_facts(
        path,
        journal,
        publication_started=publication_started,
        content_verified=content_verified,
    )
    message = f"The Volume durability barrier did not complete: {result.detail}"
    if content_verified:
        raise TransactionDurabilityPendingError(message, facts)
    if publication_started:
        raise TransactionInterruptedError(message, facts)
    raise TransactionPreparedError(message, facts)


def _execute_external(
    session: FilesystemSession,
    plan: StorageTransaction,
    *,
    checkpoint: Callable[[], None] | None,
    progress: Callable[[TransactionProgress], None] | None,
) -> TransactionResult:
    if checkpoint is not None:
        checkpoint()
    validate(session, plan, checkpoint=checkpoint)
    journal = _journal(session, plan)
    path = _journal_path(plan)
    root = journal_root(path)
    journal_started = False
    publication_started = False
    content_verified = False
    fingerprint: FileFingerprint | None = None

    def notify(
        state: TransactionState, completed: int, target: DevicePath | None = None
    ) -> None:
        if progress is not None:
            progress(
                TransactionProgress(state, completed, len(journal.entries), target)
            )

    try:
        journal_started = True
        fingerprint = _persist(session, path, journal, None)
        _require_complete_flush(
            session.flush(),
            path,
            journal,
            publication_started=False,
            content_verified=False,
        )
        journal = replace(journal, state=TransactionState.PREPARED)
        fingerprint = _persist(session, path, journal, fingerprint)
        _require_complete_flush(
            session.flush(),
            path,
            journal,
            publication_started=False,
            content_verified=False,
        )
        notify(TransactionState.PREPARED, 0)
        if checkpoint is not None:
            checkpoint()
        _check_preconditions(session, _preconditions(plan))
        journal = replace(journal, state=TransactionState.PUBLISHING)
        fingerprint = _persist(session, path, journal, fingerprint)
        _require_complete_flush(
            session.flush(),
            path,
            journal,
            publication_started=False,
            content_verified=False,
        )
        notify(TransactionState.PUBLISHING, 0)

        for index, write in enumerate(plan.writes):
            staged = session._copy_transaction_file(  # pyright: ignore[reportPrivateUsage]
                write.source,
                _stage(root, index),
                write.content,
                checkpoint=None,
            ).fingerprint
            # The complete plan was checked before publication. The move checks
            # this destination again, and dependencies are checked before commit;
            # rereading every later destination here makes N writes quadratic.
            publication_started = True
            written = session._move_file(  # pyright: ignore[reportPrivateUsage]
                _stage(root, index),
                write.path,
                expected_source=staged,
                expected_destination=write.expected,
                create_parents=True,
            ).fingerprint
            _apply_modified_time(
                session,
                write.path,
                written,
                write.modified_ns,
            )
            _expected_file(session, write.path, write.content, write.modified_ns)
            notify(TransactionState.PUBLISHING, index + 1, write.path)

        for offset, removal in enumerate(plan.removals):
            index = len(plan.writes) + offset
            publication_started = True
            session._move_file(  # pyright: ignore[reportPrivateUsage]
                removal.path,
                _backup(root, index),
                expected_source=removal.expected,
                expected_destination=None,
                create_parents=False,
            )
            notify(TransactionState.PUBLISHING, index + 1, removal.path)

        _check_preconditions(session, plan.dependencies)
        verified = tuple(
            FilePrecondition(
                entry.path,
                _expected_file(
                    session,
                    entry.path,
                    entry.after,
                    entry.after_modified_ns,
                ),
            )
            for entry in journal.entries
        )
        content_verified = True
        _require_complete_flush(
            session.flush(),
            path,
            journal,
            publication_started=publication_started,
            content_verified=True,
        )
        journal = replace(journal, state=TransactionState.COMMITTED)
        fingerprint = _persist(session, path, journal, fingerprint)
        _require_complete_flush(
            session.flush(),
            path,
            journal,
            publication_started=publication_started,
            content_verified=True,
        )
        notify(TransactionState.COMMITTED, len(journal.entries))
        session._revalidate(write=True)  # pyright: ignore[reportPrivateUsage]
        return TransactionResult(
            _recovery_observation(
                path, fingerprint, journal, (*verified, *plan.dependencies)
            ),
            FlushResult(True, "transaction writes flushed"),
        )
    except (
        TransactionPreparedError,
        TransactionInterruptedError,
        TransactionDurabilityPendingError,
    ):
        raise
    except Exception as error:
        if not journal_started:
            raise
        facts = _failure_facts(
            path,
            journal,
            publication_started=publication_started,
            content_verified=content_verified,
        )
        if content_verified:
            raise TransactionDurabilityPendingError(str(error), facts) from error
        if publication_started:
            raise TransactionInterruptedError(str(error), facts) from error
        raise TransactionPreparedError(str(error), facts) from error


def execute(
    session: FilesystemSession,
    plan: StorageTransaction,
    *,
    checkpoint: Callable[[], None] | None,
    progress: Callable[[TransactionProgress], None] | None,
    activity: Callable[[TransactionActivity], None] | None = None,
) -> TransactionResult:
    if plan.recovery_material is not None:
        return _execute_external(
            session,
            plan,
            checkpoint=checkpoint,
            progress=progress,
        )
    validate(session, plan)
    journal = _journal(session, plan)
    path = _journal_path(plan)
    root = journal_root(path)
    started = False
    flushes: list[FlushResult] = []

    def notify(
        state: TransactionState, completed: int, target: DevicePath | None = None
    ) -> None:
        logger.debug(
            "Storage transaction journal=%s state=%s completed=%d total=%d path=%s",
            path,
            state,
            completed,
            len(journal.entries),
            target,
        )
        if progress is not None:
            progress(
                TransactionProgress(state, completed, len(journal.entries), target)
            )

    if checkpoint is not None:
        checkpoint()
    try:
        fingerprint = _persist(session, path, journal, None)
        staged: list[FileFingerprint] = []
        # Keep enough free space for a restoration copy after every staged file.
        unit = session.mounted_volume.volume.capabilities.allocation_unit_size
        reserve = (
            plan.reserve_bytes
            + max(
                (
                    allocated_size(e.before.size, unit)
                    for e in journal.entries
                    if e.before
                ),
                default=0,
            )
            + 2 * _journal_allocation(journal, unit)
        )
        for index, write in enumerate(plan.writes):
            if checkpoint is not None:
                checkpoint()
            notify(TransactionState.STAGING, index, write.path)
            if write.expected is not None:
                session._copy_transaction_file(  # pyright: ignore[reportPrivateUsage]
                    write.path,
                    _backup(root, index),
                    FileContent.from_fingerprint(write.expected),
                    reserve_bytes=reserve,
                    checkpoint=checkpoint,
                )
            staged.append(
                session._copy_transaction_file(  # pyright: ignore[reportPrivateUsage]
                    write.source,
                    _stage(root, index),
                    write.content,
                    reserve_bytes=reserve,
                    checkpoint=checkpoint,
                ).fingerprint
            )
        journal = replace(journal, state=TransactionState.PREPARED)
        fingerprint = _persist(session, path, journal, fingerprint)
        _activity(activity, TransactionActivityPhase.FLUSHING)
        flushes.append(session.flush())
        notify(TransactionState.PREPARED, 0)
        if checkpoint is not None:
            checkpoint()
        # Recheck the entire staged set after the final caller checkpoint, so a
        # changed later file cannot leave an earlier file already published.
        for index, write in enumerate(plan.writes):
            _activity(
                activity,
                TransactionActivityPhase.VERIFYING_STAGED,
                index,
                len(plan.writes),
                write.path,
            )
            if write.expected is not None:
                _expected_content(
                    session, _backup(root, index), _content(write.expected)
                )
            if session.fingerprint(_stage(root, index)) != staged[index]:
                raise FilePreconditionError(
                    "A transaction stage changed before publication"
                )
        _check_preconditions(session, _preconditions(plan), activity=activity)
        journal = replace(journal, state=TransactionState.PUBLISHING)
        fingerprint = _persist(session, path, journal, fingerprint)
        _activity(activity, TransactionActivityPhase.FLUSHING)
        flushes.append(session.flush())
        started = True
        for index, write in enumerate(plan.writes):
            written = session._move_file(  # pyright: ignore[reportPrivateUsage]
                _stage(root, index),
                write.path,
                expected_source=staged[index],
                expected_destination=write.expected,
                create_parents=True,
            ).fingerprint
            _apply_modified_time(
                session,
                write.path,
                written,
                write.modified_ns,
            )
            notify(TransactionState.PUBLISHING, index + 1, write.path)
        # Removals require verified replacements first. Without removals the
        # final verification below is sufficient; do not scan every output twice.
        if plan.removals:
            for index, write in enumerate(plan.writes):
                _activity(
                    activity,
                    TransactionActivityPhase.VERIFYING_WRITES,
                    index,
                    len(plan.writes),
                    write.path,
                )
                _expected_file(
                    session,
                    write.path,
                    write.content,
                    write.modified_ns,
                )
        for offset, removal in enumerate(plan.removals):
            index = len(plan.writes) + offset
            session._move_file(  # pyright: ignore[reportPrivateUsage]
                removal.path,
                _backup(root, index),
                expected_source=removal.expected,
                expected_destination=None,
                create_parents=False,
            )
            notify(TransactionState.PUBLISHING, index + 1, removal.path)
        _check_preconditions(session, plan.dependencies, activity=activity)
        verified: list[FilePrecondition] = []
        for index, entry in enumerate(journal.entries):
            _activity(
                activity,
                TransactionActivityPhase.VERIFYING_RECOVERY,
                index,
                len(journal.entries),
                entry.path,
            )
            verified.append(
                FilePrecondition(
                    entry.path,
                    _expected_file(
                        session,
                        entry.path,
                        entry.after,
                        entry.after_modified_ns,
                    ),
                )
            )
            if entry.before is not None:
                _expected_content(session, _backup(root, index), entry.before)
        _activity(activity, TransactionActivityPhase.FLUSHING)
        flushes.append(session.flush())
        journal = replace(journal, state=TransactionState.COMMITTED)
        fingerprint = _persist(session, path, journal, fingerprint)
        _activity(activity, TransactionActivityPhase.FLUSHING)
        flushes.append(session.flush())
        notify(TransactionState.COMMITTED, len(journal.entries))
        session._revalidate(write=True)  # pyright: ignore[reportPrivateUsage]
        return TransactionResult(
            _recovery_observation(
                path, fingerprint, journal, (*verified, *plan.dependencies)
            ),
            _flush_result(flushes),
        )
    except Exception as error:
        logger.debug(
            "Storage transaction interrupted journal=%s publication_started=%s",
            path,
            started,
            exc_info=True,
        )
        raise RecoverableWriteError(str(error), str(path), started) from error


def _read_journal(
    session: FilesystemSession, path: DevicePath
) -> tuple[TransactionJournal, FileFingerprint]:
    try:
        journal_root(path)
        snapshot = session.read_snapshot(path, max_bytes=MAX_JOURNAL_BYTES)
        journal = decode(snapshot.data)
        validate_paths(
            tuple(e.path for e in journal.entries)
            + tuple(d.path for d in journal.dependencies),
            case_sensitive=session.mounted_volume.volume.capabilities.case_sensitive
            is True,
        )
    except (ValueError, RecursionError) as error:
        raise StorageOperationError(f"Invalid transaction journal: {error}") from error
    return journal, snapshot.fingerprint


def _identity_matches(session: FilesystemSession, journal: TransactionJournal) -> bool:
    volume = session.mounted_volume
    return (
        journal.device_id == volume.physical_device.id.value
        and journal.volume_id == volume.volume.id.value
    )


def _read(
    session: FilesystemSession, path: DevicePath
) -> tuple[TransactionJournal, FileFingerprint]:
    journal, fingerprint = _read_journal(session, path)
    if not _identity_matches(session, journal):
        raise VolumeIdentityChangedError(
            "Transaction journal belongs to another device or Volume"
        )
    return journal, fingerprint


def read_status(
    session: FilesystemSession, path: DevicePath
) -> TransactionJournalStatus:
    """Report the recorded state without granting recovery or cleanup authority."""
    journal, _fingerprint = _read_journal(session, path)
    return TransactionJournalStatus(journal.state, _identity_matches(session, journal))


def read_state(session: FilesystemSession, path: DevicePath) -> TransactionState:
    """Validate the small identity-bound journal without rereading its media files."""
    journal, _fingerprint = _read(session, path)
    return journal.state


def finalize_committed(session: FilesystemSession, path: DevicePath) -> FlushResult:
    """Discard recovery data for a verified commit without rehashing published media.

    The durable COMMITTED marker is written only after content verification. The
    writer lease and exact journal fingerprint bind this cleanup to that marker.
    This is cleanup authority only; restoration still requires full inspection.
    """
    return _finalize_terminal(session, path, TransactionState.COMMITTED)


def finalize_restored(session: FilesystemSession, path: DevicePath) -> FlushResult:
    """Clean a verified restoration marker without another media inspection."""
    return _finalize_terminal(session, path, TransactionState.RESTORED)


def _finalize_terminal(
    session: FilesystemSession,
    path: DevicePath,
    state: TransactionState,
) -> FlushResult:
    journal, fingerprint = _read(session, path)
    if journal.state is not state:
        raise FilePreconditionError(
            f"Only a verified {state.value} transaction can be cleaned up"
        )
    _require_complete_flush(
        session.flush(),
        path,
        journal,
        publication_started=True,
        content_verified=True,
    )
    return finalize(
        session,
        TransactionRecovery(
            path,
            fingerprint,
            journal.state,
            (),
            journal.recovery_material_identity,
        ),
    )


def _recovery_observation(
    path: DevicePath,
    fingerprint: FileFingerprint,
    journal: TransactionJournal,
    files: tuple[FilePrecondition, ...],
) -> TransactionRecovery:
    """Retain verified observations; restore always rechecks their full content."""

    return TransactionRecovery(
        path,
        fingerprint,
        journal.state,
        files,
        journal.recovery_material_identity,
        tuple(entry.path for entry in journal.entries if entry.before is not None),
    )


def inspect(
    session: FilesystemSession,
    path: DevicePath,
    *,
    activity: Callable[[TransactionActivity], None] | None = None,
) -> TransactionRecovery:
    journal, fingerprint = _read(session, path)
    paths = (
        *(e.path for e in journal.entries),
        *(d.path for d in journal.dependencies),
    )
    observed: list[FilePrecondition] = []
    for index, target in enumerate(paths):
        _activity(
            activity, TransactionActivityPhase.INSPECTING, index, len(paths), target
        )
        observed.append(FilePrecondition(target, _fingerprint(session, target)))
    files = tuple(observed)
    if session.fingerprint(path) != fingerprint:
        raise FilePreconditionError("Transaction journal changed during inspection")
    _check_preconditions(session, files, activity=activity)
    return _recovery_observation(path, fingerprint, journal, files)


def finalize(
    session: FilesystemSession,
    recovery: TransactionRecovery,
) -> FlushResult:
    """Remove only an exactly observed terminal transaction namespace."""

    if recovery.state not in (TransactionState.COMMITTED, TransactionState.RESTORED):
        raise FilePreconditionError(
            "Only a committed or restored transaction can be finalized"
        )
    path = recovery.journal_path
    root = journal_root(path)
    if not session.exists(root):
        return _finalize_flush(session, recovery)
    if not session.exists(path):
        if session.list_directory(root):
            raise FilePreconditionError(
                "A transaction namespace exists without its verified journal"
            )
        session._remove_empty_transaction_namespace(  # pyright: ignore[reportPrivateUsage]
            root
        )
        return _finalize_flush(session, recovery)

    journal, fingerprint = _read(session, path)
    if fingerprint != recovery.journal_fingerprint:
        raise FilePreconditionError("Transaction journal changed since inspection")
    if journal.state != recovery.state or journal.state not in (
        TransactionState.COMMITTED,
        TransactionState.RESTORED,
    ):
        raise FilePreconditionError("Transaction journal is not in its inspected state")
    if journal.recovery_material_identity != recovery.recovery_material_identity:
        raise FilePreconditionError("Transaction recovery material identity changed")
    session._remove_transaction_namespace(  # pyright: ignore[reportPrivateUsage]
        root,
        path,
        expected_journal=fingerprint,
    )
    return _finalize_flush(session, recovery)


def finalize_missing(
    session: FilesystemSession,
    journal_path: DevicePath,
) -> FlushResult:
    """Finish cleanup only when an exact transaction namespace is empty."""

    root = journal_root(journal_path)
    if session.exists(journal_path):
        raise FilePreconditionError(
            "A transaction journal still exists and requires verified inspection"
        )
    if session.exists(root):
        session._remove_empty_transaction_namespace(  # pyright: ignore[reportPrivateUsage]
            root
        )
    return session.flush()


def _finalize_flush(
    session: FilesystemSession,
    recovery: TransactionRecovery,
) -> FlushResult:
    result = session.flush()
    if result.complete:
        return result
    facts = TransactionFailureFacts(
        recovery.journal_path,
        recovery.state,
        publication_started=True,
        content_verified=True,
        recovery_material_identity=recovery.recovery_material_identity,
    )
    raise TransactionDurabilityPendingError(
        f"Transaction cleanup durability is pending: {result.detail}",
        facts,
    )


def _material_for_journal(
    journal: TransactionJournal,
    material: TransactionRecoveryMaterial | None,
    *,
    checkpoint: Callable[[], None] | None,
) -> dict[DevicePath, TransactionRecoveryFile]:
    if material is None or material.identity != journal.recovery_material_identity:
        raise FilePreconditionError(
            "Recovery requires the exact external recovery material"
        )
    supplied = _recovery_files(material)
    required = {entry.path for entry in journal.entries if entry.before is not None}
    if set(supplied) != required:
        raise FilePreconditionError(
            "External recovery material does not cover the transaction journal"
        )
    for entry in journal.entries:
        if entry.before is None:
            continue
        file = supplied[entry.path]
        if file.content != entry.before or file.modified_ns != entry.before_modified_ns:
            raise FilePreconditionError(
                f"External recovery material does not match {entry.path}"
            )
        _verify_host_content(file, checkpoint=checkpoint)
    return supplied


def _restore_external(
    session: FilesystemSession,
    recovery: TransactionRecovery,
    journal: TransactionJournal,
    fingerprint: FileFingerprint,
    *,
    recovery_material: TransactionRecoveryMaterial | None,
    checkpoint: Callable[[], None] | None,
    progress: Callable[[TransactionProgress], None] | None,
) -> TransactionResult:
    path = recovery.journal_path
    root = journal_root(path)
    material = _material_for_journal(
        journal,
        recovery_material,
        checkpoint=checkpoint,
    )
    current = {file.path: file.fingerprint for file in recovery.files}
    filesystem_type = session.mounted_volume.volume.filesystem_type
    for dependency in journal.dependencies:
        if _content(current[dependency.path]) != dependency.content:
            raise FilePreconditionError(
                f"An unchanged transaction dependency was modified: {dependency.path}"
            )
    for index, entry in enumerate(journal.entries):
        observed = current[entry.path]
        if _matches_file(
            observed,
            entry.before,
            entry.before_modified_ns,
            filesystem_type,
        ):
            continue
        restoring_before_content = (
            journal.state is TransactionState.RESTORING
            and _content(observed) == entry.before
        )
        after_matches = _matches_file(
            observed,
            entry.after,
            entry.after_modified_ns,
            filesystem_type,
        ) or (
            journal.state in (TransactionState.PUBLISHING, TransactionState.RESTORING)
            and _content(observed) == entry.after
        )
        if journal.state in (
            TransactionState.STAGING,
            TransactionState.PREPARED,
            TransactionState.RESTORED,
        ) or (not after_matches and not restoring_before_content):
            raise FilePreconditionError(
                f"Recovery would overwrite an unrelated edit: {entry.path}"
            )
        if entry.before is None and session.exists(
            root.joinpath(f"retired-{index}.bin")
        ):
            raise FilePreconditionError(
                "Recovery destination for new content already exists"
            )

    observation = session._revalidate(write=True)  # pyright: ignore[reportPrivateUsage]
    unit = observation.volume.capabilities.allocation_unit_size
    required = max(
        (
            allocated_size(entry.before.size, unit)
            for entry in journal.entries
            if entry.before is not None
            and not _matches_file(
                current[entry.path],
                entry.before,
                entry.before_modified_ns,
                filesystem_type,
            )
        ),
        default=0,
    ) + 2 * _journal_allocation(journal, unit)
    session._check_write_capacity(  # pyright: ignore[reportPrivateUsage]
        0,
        observation,
        reserve_bytes=required,
        display_name="transaction restoration",
    )

    content_verified = False
    try:
        journal = replace(journal, state=TransactionState.RESTORING)
        fingerprint = _persist(session, path, journal, fingerprint)
        _require_complete_flush(
            session.flush(),
            path,
            journal,
            publication_started=True,
            content_verified=False,
        )
        for completed, index in enumerate(reversed(range(len(journal.entries))), 1):
            entry = journal.entries[index]
            prior = current[entry.path]
            if _matches_file(
                prior,
                entry.before,
                entry.before_modified_ns,
                filesystem_type,
            ):
                pass
            elif entry.before is None:
                assert prior is not None
                session._move_file(  # pyright: ignore[reportPrivateUsage]
                    entry.path,
                    root.joinpath(f"retired-{index}.bin"),
                    expected_source=prior,
                    expected_destination=None,
                    create_parents=False,
                )
            else:
                restored = session._copy_transaction_file(  # pyright: ignore[reportPrivateUsage]
                    material[entry.path].source,
                    entry.path,
                    entry.before,
                    expected=prior,
                ).fingerprint
                _apply_modified_time(
                    session,
                    entry.path,
                    restored,
                    entry.before_modified_ns,
                )
            if progress is not None:
                progress(
                    TransactionProgress(
                        TransactionState.RESTORING,
                        completed,
                        len(journal.entries),
                        entry.path,
                    )
                )
        for entry in journal.entries:
            _expected_file(
                session,
                entry.path,
                entry.before,
                entry.before_modified_ns,
            )
        for dependency in journal.dependencies:
            _expected_content(session, dependency.path, dependency.content)
        content_verified = True
        _require_complete_flush(
            session.flush(),
            path,
            journal,
            publication_started=True,
            content_verified=True,
        )
        journal = replace(journal, state=TransactionState.RESTORED)
        fingerprint = _persist(session, path, journal, fingerprint)
        _require_complete_flush(
            session.flush(),
            path,
            journal,
            publication_started=True,
            content_verified=True,
        )
        return TransactionResult(
            inspect(session, path),
            FlushResult(True, "transaction restoration flushed"),
        )
    except (
        TransactionPreparedError,
        TransactionInterruptedError,
        TransactionDurabilityPendingError,
    ):
        raise
    except Exception as error:
        facts = _failure_facts(
            path,
            journal,
            publication_started=True,
            content_verified=content_verified,
        )
        if content_verified:
            raise TransactionDurabilityPendingError(str(error), facts) from error
        raise TransactionInterruptedError(str(error), facts) from error


def restore(
    session: FilesystemSession,
    recovery: TransactionRecovery,
    *,
    recovery_material: TransactionRecoveryMaterial | None,
    checkpoint: Callable[[], None] | None,
    progress: Callable[[TransactionProgress], None] | None,
    activity: Callable[[TransactionActivity], None] | None = None,
) -> TransactionResult:
    if checkpoint is not None:
        checkpoint()
    path = recovery.journal_path
    journal, fingerprint = _read(session, path)
    if fingerprint != recovery.journal_fingerprint:
        raise FilePreconditionError("Transaction journal changed since inspection")
    if recovery.recovery_material_identity != journal.recovery_material_identity:
        raise FilePreconditionError("Transaction recovery material identity changed")
    expected_paths = tuple(e.path for e in journal.entries) + tuple(
        d.path for d in journal.dependencies
    )
    if tuple(f.path for f in recovery.files) != expected_paths:
        raise FilePreconditionError("Recovery must capture every target and dependency")
    _check_preconditions(session, recovery.files, activity=activity)
    if journal.recovery_material_identity:
        return _restore_external(
            session,
            recovery,
            journal,
            fingerprint,
            recovery_material=recovery_material,
            checkpoint=checkpoint,
            progress=progress,
        )
    if recovery_material is not None:
        raise FilePreconditionError(
            "This transaction does not use external recovery material"
        )
    root = journal_root(path)
    current = {f.path: f.fingerprint for f in recovery.files}
    # Preflight the entire rollback, not merely the next file to restore.
    for dependency in journal.dependencies:
        if _content(current[dependency.path]) != dependency.content:
            raise FilePreconditionError(
                f"An unchanged transaction dependency was modified: {dependency.path}"
            )
    for index, entry in enumerate(journal.entries):
        _activity(
            activity,
            TransactionActivityPhase.VERIFYING_RECOVERY,
            index,
            len(journal.entries),
            entry.path,
        )
        observed = current[entry.path]
        if _matches_file(
            observed,
            entry.before,
            entry.before_modified_ns,
            session.mounted_volume.volume.filesystem_type,
        ):
            continue
        if journal.state in (
            TransactionState.STAGING,
            TransactionState.PREPARED,
            TransactionState.RESTORED,
        ) or not _matches_file(
            observed,
            entry.after,
            entry.after_modified_ns,
            session.mounted_volume.volume.filesystem_type,
        ):
            raise FilePreconditionError(
                f"Recovery would overwrite an unrelated edit: {entry.path}"
            )
        if entry.before is not None:
            _expected_content(session, _backup(root, index), entry.before)
        elif session.exists(root.joinpath(f"retired-{index}.bin")):
            raise FilePreconditionError(
                "Recovery destination for new content already exists"
            )
    _check_preconditions(session, recovery.files, activity=activity)
    observation = session._revalidate(write=True)  # pyright: ignore[reportPrivateUsage]
    unit = observation.volume.capabilities.allocation_unit_size
    required = max(
        (
            allocated_size(e.before.size, unit)
            for e in journal.entries
            if e.before is not None and _content(current[e.path]) != e.before
        ),
        default=0,
    ) + 2 * _journal_allocation(journal, unit)
    session._check_write_capacity(  # pyright: ignore[reportPrivateUsage]
        0, observation, reserve_bytes=required, display_name="transaction restoration"
    )
    try:
        journal = replace(journal, state=TransactionState.RESTORING)
        fingerprint = _persist(session, path, journal, fingerprint)
        _activity(activity, TransactionActivityPhase.FLUSHING)
        flushes = [session.flush()]
        for completed, index in enumerate(reversed(range(len(journal.entries))), 1):
            entry = journal.entries[index]
            prior = current[entry.path]
            if _matches_file(
                prior,
                entry.before,
                entry.before_modified_ns,
                session.mounted_volume.volume.filesystem_type,
            ):
                pass
            elif entry.before is None:
                assert prior is not None
                session._move_file(  # pyright: ignore[reportPrivateUsage]
                    entry.path,
                    root.joinpath(f"retired-{index}.bin"),
                    expected_source=prior,
                    expected_destination=None,
                    create_parents=False,
                )
            else:
                restored = session._copy_transaction_file(  # pyright: ignore[reportPrivateUsage]
                    _backup(root, index), entry.path, entry.before, expected=prior
                ).fingerprint
                _apply_modified_time(
                    session,
                    entry.path,
                    restored,
                    entry.before_modified_ns,
                )
            logger.debug(
                "Storage transaction restoring journal=%s completed=%d total=%d path=%s",
                path,
                completed,
                len(journal.entries),
                entry.path,
            )
            if progress is not None:
                progress(
                    TransactionProgress(
                        TransactionState.RESTORING,
                        completed,
                        len(journal.entries),
                        entry.path,
                    )
                )
        for index, entry in enumerate(journal.entries):
            _activity(
                activity,
                TransactionActivityPhase.VERIFYING_WRITES,
                index,
                len(journal.entries),
                entry.path,
            )
            _expected_file(
                session,
                entry.path,
                entry.before,
                entry.before_modified_ns,
            )
        for index, dependency in enumerate(journal.dependencies):
            _activity(
                activity,
                TransactionActivityPhase.CHECKING_DEPENDENCIES,
                index,
                len(journal.dependencies),
                dependency.path,
            )
            _expected_content(session, dependency.path, dependency.content)
        _activity(activity, TransactionActivityPhase.FLUSHING)
        flushes.append(session.flush())
        journal = replace(journal, state=TransactionState.RESTORED)
        _persist(session, path, journal, fingerprint)
        _activity(activity, TransactionActivityPhase.FLUSHING)
        flushes.append(session.flush())
        return TransactionResult(
            inspect(session, path, activity=activity), _flush_result(flushes)
        )
    except Exception as error:
        logger.debug(
            "Storage transaction restoration interrupted journal=%s",
            path,
            exc_info=True,
        )
        raise RecoverableWriteError(str(error), str(path), True) from error


def _flush_result(flushes: list[FlushResult]) -> FlushResult:
    failures = [f.detail for f in flushes if not f.complete]
    return FlushResult(
        not failures, "; ".join(failures) if failures else "transaction writes flushed"
    )
