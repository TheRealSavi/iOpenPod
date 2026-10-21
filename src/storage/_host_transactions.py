"""Host-backed transactions that need only net growth on the selected Volume.

The Host journal is authoritative and survives loss of the device journal. All
originals are verified and retained before any device allocation is reclaimed.
Targets are absent or contain complete verified files; partial copies stay in
Storage's private temporary files. Recovery never accepts arbitrary target bytes.

Like the device-backed implementation, this module shares private transaction
and session primitives. Targeted exceptions keep them off Storage's public API.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import replace
from typing import TYPE_CHECKING

from storage import _transactions as tx
from storage._filesystem import allocated_size, is_link_or_reparse, open_read_no_follow
from storage._transaction_journal import (
    MAX_JOURNAL_BYTES,
    TransactionJournal,
    decode,
    encode,
    journal_root,
    validate_paths,
)
from storage.errors import (
    FilePreconditionError,
    RecoverableWriteError,
    StorageCapacityError,
    StorageOperationError,
)
from storage.host_files import (
    AtomicHostFile,
    _flush_directory,  # pyright: ignore[reportPrivateUsage]
)
from storage.models import FileFingerprint, FileIdentity
from storage.paths import DevicePath, HostPath
from storage.transactions import (
    FileContent,
    FilePrecondition,
    TransactionActivityPhase,
    TransactionRecoveryFile,
    TransactionResult,
    TransactionState,
    TransactionValidation,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from storage._transaction_journal import JournalEntry
    from storage.models import FlushResult
    from storage.session import FilesystemSession
    from storage.transactions import (
        StorageTransaction,
        TransactionActivity,
        TransactionProgress,
        TransactionRecovery,
    )

IDENTITY = "storage-host-v1"


def _directory(session: FilesystemSession, path: DevicePath | None = None) -> Path:
    configured = session._transaction_recovery_directory  # pyright: ignore[reportPrivateUsage]
    check = session._check_recovery_location  # pyright: ignore[reportPrivateUsage]
    if configured is None or check is None:
        raise StorageOperationError(
            "A persistent Host transaction recovery directory is required"
        )
    check(HostPath(configured), session.mounted_volume)
    root = configured.resolve()
    volume = session.mounted_volume
    identity = hashlib.sha256(
        (volume.physical_device.id.value + "\0" + volume.volume.id.value).encode()
    ).hexdigest()
    directory = root / identity
    children = [directory]
    if path is not None:
        journal_root(path)
        directory = directory / path.parts[1]
        children.append(directory)
    for child in children:
        if os.path.lexists(child) and (
            is_link_or_reparse(child.lstat()) or not child.is_dir()
        ):
            raise StorageOperationError("Host transaction recovery directory is unsafe")
    return directory


def _read_host(path: Path) -> tuple[TransactionJournal, FileFingerprint]:
    with open_read_no_follow(path) as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(MAX_JOURNAL_BYTES + 1)
        after = os.fstat(stream.fileno())
    if tx._host_identity(before) != tx._host_identity(after):  # pyright: ignore[reportPrivateUsage]
        raise FilePreconditionError("Host recovery journal changed while reading")
    journal = decode(data)
    if journal.recovery_material_identity != IDENTITY:
        raise StorageOperationError("Invalid Host recovery journal")
    return journal, FileFingerprint(
        after.st_size,
        after.st_mtime_ns,
        after.st_dev,
        after.st_ino,
        hashlib.sha256(data).hexdigest(),
    )


def read(
    session: FilesystemSession, path: DevicePath
) -> tuple[TransactionJournal, FileFingerprint] | None:
    if not session.supports_host_transaction_recovery:
        return None
    directory = _directory(session, path)
    manifest = directory / "transaction.json"
    if not os.path.lexists(manifest):
        return None
    journal, fingerprint = _read_host(manifest)
    if not tx._identity_matches(session, journal):  # pyright: ignore[reportPrivateUsage]
        raise FilePreconditionError("Host recovery belongs to another device or Volume")
    validate_paths(
        tuple(e.path for e in journal.entries)
        + tuple(d.path for d in journal.dependencies),
        case_sensitive=session.mounted_volume.volume.capabilities.case_sensitive
        is True,
    )
    if session.exists(path):
        device = decode(session.read(path, max_bytes=MAX_JOURNAL_BYTES))
        # Host state can be ahead of the removable device after a power loss.
        if (
            replace(
                device,
                state=journal.state,
                content_durability_confirmed=journal.content_durability_confirmed,
            )
            != journal
        ):
            raise FilePreconditionError("Host and device transaction intent differ")
    return journal, fingerprint


def journals(session: FilesystemSession) -> tuple[DevicePath, ...]:
    if not session.supports_host_transaction_recovery:
        return ()
    directory = _directory(session)
    if not directory.exists():
        return ()
    return tuple(
        DevicePath(f".iopenpod-recovery/{item.name}/transaction.json")
        for item in sorted(directory.iterdir())
        if re.fullmatch(r"[a-f0-9]{32}", item.name)
        and os.path.lexists(item / "transaction.json")
    )


def _reserve(session: FilesystemSession, journal: TransactionJournal) -> int:
    unit = session.mounted_volume.volume.capabilities.allocation_unit_size
    # Keep this headroom throughout publication. Directory allocation is charged
    # separately up front, since that reserve is consumed as directories appear.
    return 64 * 1024 + 3 * tx._journal_allocation(journal, unit)  # pyright: ignore[reportPrivateUsage]


def validate(
    session: FilesystemSession, plan: StorageTransaction, journal: TransactionJournal
) -> TransactionValidation:
    directory = _directory(session)
    unit = session.mounted_volume.volume.capabilities.allocation_unit_size
    before = sum(
        allocated_size(e.before.size, unit)
        for e in journal.entries
        if e.before is not None
    )
    after = sum(
        allocated_size(e.after.size, unit)
        for e in journal.entries
        if e.after is not None
    )
    parents = {
        entry.path.parts[:length]
        for entry in journal.entries
        for length in range(1, len(entry.path.parts))
    }
    required = (
        max(0, after - before)
        + _reserve(session, journal)
        + plan.reserve_bytes
        + len(parents) * (unit or 4096)
    )
    session._check_write_capacity(  # pyright: ignore[reportPrivateUsage]
        0,
        session._revalidate(),  # pyright: ignore[reportPrivateUsage]
        reserve_bytes=required,
        display_name="transaction growth and journal",
    )
    ancestor = directory
    while not ancestor.exists():
        ancestor = ancestor.parent
    host_required = sum(
        allocated_size(e.before.size, 4096)
        for e in journal.entries
        if e.before is not None
    ) + 3 * allocated_size(len(encode(journal)), 4096)
    if shutil.disk_usage(ancestor).free < host_required:
        raise StorageCapacityError(
            f"Host transaction recovery requires {host_required} bytes on the computer"
        )
    return TransactionValidation(required)


def _persist(
    session: FilesystemSession,
    path: DevicePath,
    journal: TransactionJournal,
    expected: FileFingerprint | None,
) -> FileFingerprint:
    directory = _directory(session, path)
    retained = read(session, path)
    if (retained[1] if retained is not None else None) != expected:
        raise FilePreconditionError("Host recovery journal changed before publication")
    device_expected = session.fingerprint(path) if session.exists(path) else None
    if expected is None and device_expected is not None:
        raise FilePreconditionError("Transaction journal already exists")
    AtomicHostFile(directory / "transaction.json").replace_bytes(encode(journal))
    # Persist Host intent first. Recovery discovers it even if the device marker
    # is lost or still contains an earlier state after unplugging.
    tx._persist(session, path, journal, device_expected)  # pyright: ignore[reportPrivateUsage]
    return _read_host(directory / "transaction.json")[1]


def _material(
    session: FilesystemSession,
    path: DevicePath,
    journal: TransactionJournal,
    checkpoint: Callable[[], None] | None,
) -> dict[DevicePath, TransactionRecoveryFile]:
    directory = _directory(session, path)
    result: dict[DevicePath, TransactionRecoveryFile] = {}
    for index, entry in enumerate(journal.entries):
        if entry.before is not None:
            file = TransactionRecoveryFile(
                entry.path,
                HostPath(directory / f"original-{index}.bin"),
                entry.before,
                entry.before_modified_ns,
            )
            try:
                tx._verify_host_content(file, checkpoint=checkpoint)  # pyright: ignore[reportPrivateUsage]
            except OSError as error:
                raise StorageOperationError(
                    f"Host recovery material is unavailable for {entry.path}: {error}"
                ) from error
            result[entry.path] = file
    return result


def _delete(
    session: FilesystemSession, path: DevicePath, expected: FileFingerprint
) -> None:
    if session.fingerprint(path) != expected:
        raise FilePreconditionError(
            f"Transaction file changed before reclaiming space: {path}"
        )
    session._delete_unrecoverably(  # pyright: ignore[reportPrivateUsage]
        path,
        expected=FileIdentity(
            expected.size, expected.modified_ns, expected.device, expected.inode
        ),
    )


def execute(
    session: FilesystemSession,
    plan: StorageTransaction,
    *,
    checkpoint: Callable[[], None] | None,
    progress: Callable[[TransactionProgress], None] | None,
    activity: Callable[[TransactionActivity], None] | None,
) -> TransactionResult:
    from storage.transactions import TransactionProgress

    tx.validate(session, plan, checkpoint=checkpoint)
    path = tx._journal_path(plan)  # pyright: ignore[reportPrivateUsage]
    directory = _directory(session, path)
    directory.mkdir(parents=True, exist_ok=False)
    _flush_directory(directory.parent)
    journal = tx._journal(session, plan)  # pyright: ignore[reportPrivateUsage]
    started = False

    def notify(
        state: TransactionState, count: int, target: DevicePath | None = None
    ) -> None:
        if progress is not None:
            progress(TransactionProgress(state, count, len(journal.entries), target))

    try:
        # No device writes until every captured original is on the Host.
        for index, entry in enumerate(journal.entries):
            if checkpoint is not None:
                checkpoint()
            notify(TransactionState.STAGING, index, entry.path)
            if entry.before is not None:
                copied = session.copy_to_host(
                    entry.path,
                    HostPath(directory / f"original-{index}.bin"),
                    progress=(lambda _: checkpoint())
                    if checkpoint is not None
                    else None,
                )
                if (
                    FileContent.from_fingerprint(copied.source_fingerprint)
                    != entry.before
                ):
                    raise FilePreconditionError(
                        f"Recovery source changed: {entry.path}"
                    )
        _material(session, path, journal, checkpoint)
        for write in plan.writes:
            tx._verify_host_content(write, checkpoint=checkpoint)  # pyright: ignore[reportPrivateUsage]
        tx._check_preconditions(session, tx._preconditions(plan), activity=activity)  # pyright: ignore[reportPrivateUsage]
        fingerprint = _persist(session, path, journal, None)
        journal = replace(journal, state=TransactionState.PREPARED)
        fingerprint = _persist(session, path, journal, fingerprint)
        notify(TransactionState.PREPARED, 0)
        if checkpoint is not None:
            checkpoint()
        _material(session, path, journal, None)
        for write in plan.writes:
            tx._verify_host_content(write, checkpoint=None)  # pyright: ignore[reportPrivateUsage]
        tx._check_preconditions(session, tx._preconditions(plan), activity=activity)  # pyright: ignore[reportPrivateUsage]
        journal = replace(journal, state=TransactionState.PUBLISHING)
        fingerprint = _persist(session, path, journal, fingerprint)
        started = True
        notify(TransactionState.PUBLISHING, 0, journal.entries[0].path)
        # Reclaim all reviewed originals so Adds can use space from Removes.
        for precondition in tx._preconditions(plan)[: len(journal.entries)]:  # pyright: ignore[reportPrivateUsage]
            if precondition.fingerprint is not None:
                _delete(session, precondition.path, precondition.fingerprint)
        reserve = (
            _reserve(session, journal)
            + plan.reserve_bytes
            - tx._journal_allocation(  # pyright: ignore[reportPrivateUsage]
                journal, session.mounted_volume.volume.capabilities.allocation_unit_size
            )
        )
        for index, write in enumerate(plan.writes):
            written = session._copy_transaction_file(  # pyright: ignore[reportPrivateUsage]
                write.source,
                write.path,
                write.content,
                reserve_bytes=reserve,
            ).fingerprint
            tx._apply_modified_time(session, write.path, written, write.modified_ns)  # pyright: ignore[reportPrivateUsage]
            notify(TransactionState.PUBLISHING, index + 1, write.path)
        return _finish(
            session,
            path,
            journal,
            fingerprint,
            restoring=False,
            activity=activity,
            progress=progress,
        )
    except Exception as error:
        if not (directory / "transaction.json").exists():
            # Nothing on the device was changed. Only our fresh namespace exists.
            _cleanup_host(directory, journal)
            raise
        raise RecoverableWriteError(str(error), str(path), started) from error


def _finish(
    session: FilesystemSession,
    path: DevicePath,
    journal: TransactionJournal,
    expected: FileFingerprint,
    *,
    restoring: bool,
    activity: Callable[[TransactionActivity], None] | None,
    progress: Callable[[TransactionProgress], None] | None,
) -> TransactionResult:
    from storage.transactions import TransactionProgress

    dependencies = tuple(
        FilePrecondition(d.path, tx._expected_content(session, d.path, d.content))  # pyright: ignore[reportPrivateUsage]
        for d in journal.dependencies
    )
    verified: list[FilePrecondition] = []
    for index, entry in enumerate(journal.entries):
        tx._activity(  # pyright: ignore[reportPrivateUsage]
            activity,
            TransactionActivityPhase.VERIFYING_WRITES,
            index,
            len(journal.entries),
            entry.path,
        )
        fingerprint = tx._expected_file(  # pyright: ignore[reportPrivateUsage]
            session,
            entry.path,
            entry.before if restoring else entry.after,
            entry.before_modified_ns if restoring else entry.after_modified_ns,
        )
        verified.append(FilePrecondition(entry.path, fingerprint))
    tx._activity(activity, TransactionActivityPhase.FLUSHING)  # pyright: ignore[reportPrivateUsage]
    flushed = session.flush()
    journal = replace(
        journal,
        state=TransactionState.RESTORED if restoring else TransactionState.COMMITTED,
        content_durability_confirmed=flushed.complete,
    )
    fingerprint = _persist(session, path, journal, expected)
    final_flush = session.flush()
    if progress is not None:
        progress(
            TransactionProgress(
                journal.state, len(journal.entries), len(journal.entries)
            )
        )
    return TransactionResult(
        tx._recovery_observation(  # pyright: ignore[reportPrivateUsage]
            path,
            fingerprint,
            journal,
            (
                *verified,
                *dependencies,
            ),
        ),
        tx._flush_result([flushed, final_flush]),  # pyright: ignore[reportPrivateUsage]
    )


def restore(
    session: FilesystemSession,
    recovery: TransactionRecovery,
    journal: TransactionJournal,
    *,
    checkpoint: Callable[[], None] | None,
    progress: Callable[[TransactionProgress], None] | None,
    activity: Callable[[TransactionActivity], None] | None,
) -> TransactionResult:
    from storage.transactions import TransactionProgress

    path = recovery.journal_path
    material = _material(session, path, journal, checkpoint)
    current = {f.path: f.fingerprint for f in recovery.files}
    filesystem = session.mounted_volume.volume.filesystem_type
    for dependency in journal.dependencies:
        if tx._content(current[dependency.path]) != dependency.content:  # pyright: ignore[reportPrivateUsage]
            raise FilePreconditionError(
                f"An unchanged transaction dependency was modified: {dependency.path}"
            )
    changed: list[JournalEntry] = []
    for entry in journal.entries:
        observed = current[entry.path]
        if tx._matches_file(  # pyright: ignore[reportPrivateUsage]
            observed, entry.before, entry.before_modified_ns, filesystem
        ):
            continue
        permitted = journal.state in (
            TransactionState.PUBLISHING,
            TransactionState.COMMITTED,
            TransactionState.RESTORING,
        )
        if not permitted or (
            observed is not None
            and tx._content(observed) not in (entry.before, entry.after)  # pyright: ignore[reportPrivateUsage]
        ):
            raise FilePreconditionError(
                f"Recovery would overwrite an unrelated edit: {entry.path}"
            )
        changed.append(entry)
    unit = session.mounted_volume.volume.capabilities.allocation_unit_size
    reclaimed = sum(
        allocated_size(observed.size, unit)
        for e in changed
        if (observed := current[e.path]) is not None
    )
    needed = sum(
        allocated_size(e.before.size, unit) for e in changed if e.before is not None
    )
    reserve = _reserve(session, journal)
    if session.exists(path):
        reserve -= tx._journal_allocation(journal, unit)  # pyright: ignore[reportPrivateUsage]
    session._check_write_capacity(  # pyright: ignore[reportPrivateUsage]
        0,
        session._revalidate(),  # pyright: ignore[reportPrivateUsage]
        reserve_bytes=max(0, needed - reclaimed) + reserve,
        display_name="transaction restoration",
    )
    if checkpoint is not None:
        checkpoint()
    try:
        journal = replace(
            journal,
            state=TransactionState.RESTORING,
            content_durability_confirmed=False,
        )
        fingerprint = _persist(session, path, journal, recovery.journal_fingerprint)
        for entry in changed:
            observed = current[entry.path]
            if observed is not None:
                _delete(session, entry.path, observed)
        for index, entry in enumerate(reversed(changed)):
            if entry.before is not None:
                written = session._copy_transaction_file(  # pyright: ignore[reportPrivateUsage]
                    material[entry.path].source,
                    entry.path,
                    entry.before,
                    reserve_bytes=_reserve(session, journal)
                    - tx._journal_allocation(journal, unit),  # pyright: ignore[reportPrivateUsage]
                ).fingerprint
                tx._apply_modified_time(  # pyright: ignore[reportPrivateUsage]
                    session, entry.path, written, entry.before_modified_ns
                )
            if progress is not None:
                progress(
                    TransactionProgress(
                        TransactionState.RESTORING, index + 1, len(changed), entry.path
                    )
                )
        return _finish(
            session,
            path,
            journal,
            fingerprint,
            restoring=True,
            activity=activity,
            progress=progress,
        )
    except Exception as error:
        raise RecoverableWriteError(str(error), str(path), True) from error


def _cleanup_host(directory: Path, journal: TransactionJournal) -> None:
    # Enumerate exact owned names; never recurse through unexpected paths.
    for index, entry in enumerate(journal.entries):
        if entry.before is not None:
            (directory / f"original-{index}.bin").unlink(missing_ok=True)
    (directory / "transaction.json").unlink(missing_ok=True)
    directory.rmdir()
    _flush_directory(directory.parent)


def finalize(session: FilesystemSession, recovery: TransactionRecovery) -> FlushResult:
    path = recovery.journal_path
    journal, fingerprint = tx._read(session, path)  # pyright: ignore[reportPrivateUsage]
    if fingerprint != recovery.journal_fingerprint or journal.state != recovery.state:
        raise FilePreconditionError("Transaction journal changed since inspection")
    restoring = journal.state is TransactionState.RESTORED
    for entry in journal.entries:
        tx._expected_file(  # pyright: ignore[reportPrivateUsage]
            session,
            entry.path,
            entry.before if restoring else entry.after,
            entry.before_modified_ns if restoring else entry.after_modified_ns,
        )
    for dependency in journal.dependencies:
        tx._expected_content(session, dependency.path, dependency.content)  # pyright: ignore[reportPrivateUsage]
    tx._require_complete_flush(  # pyright: ignore[reportPrivateUsage]
        session.flush(), path, journal, publication_started=True, content_verified=True
    )
    if session.exists(path):
        session._remove_transaction_namespace(  # pyright: ignore[reportPrivateUsage]
            journal_root(path), path, expected_journal=session.fingerprint(path)
        )
    elif session.exists(journal_root(path)):
        session._remove_empty_transaction_namespace(journal_root(path))  # pyright: ignore[reportPrivateUsage]
    tx._require_complete_flush(  # pyright: ignore[reportPrivateUsage]
        session.flush(), path, journal, publication_started=True, content_verified=True
    )
    _cleanup_host(_directory(session, path), journal)
    return session.flush()


def decline(
    session: FilesystemSession, path: DevicePath, expected: FileFingerprint
) -> None:
    retained = read(session, path)
    if retained is not None:
        if retained[1] != expected:
            raise FilePreconditionError(
                "Host recovery journal changed since inspection"
            )
        directory = _directory(session, path)
        if session.exists(path):
            session._move_file(  # pyright: ignore[reportPrivateUsage]
                path,
                journal_root(path).joinpath("declined-transaction.json"),
                expected_source=session.fingerprint(path),
                expected_destination=None,
                create_parents=False,
            )
        os.replace(
            directory / "transaction.json", directory / "declined-transaction.json"
        )
        _flush_directory(directory)
    else:
        session._move_file(  # pyright: ignore[reportPrivateUsage]
            path,
            journal_root(path).joinpath("declined-transaction.json"),
            expected_source=expected,
            expected_destination=None,
            create_parents=False,
        )
