"""Publish and recover dependent files through the real Storage interface."""

import hashlib
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

# Reuse the recovery tests' private virtual-volume setup.
from tests.storage.test_recovery import _session  # pyright: ignore[reportPrivateUsage]

from storage import (
    AccessMode,
    ConcurrentModificationError,
    DeviceBusyError,
    DevicePath,
    FileContent,
    FileFingerprint,
    FilePrecondition,
    FilePreconditionError,
    FilesystemSession,
    FlushResult,
    HostPath,
    ReadOnlyFilesystemError,
    RecoverableWriteError,
    Storage,
    StorageCapacityError,
    StorageError,
    StorageOperationError,
    StorageTransaction,
    TransactionActivity,
    TransactionActivityPhase,
    TransactionDurabilityPendingError,
    TransactionInterruptedError,
    TransactionPreparedError,
    TransactionProgress,
    TransactionRecoveryFile,
    TransactionRecoveryMaterial,
    TransactionRemoval,
    TransactionState,
    TransactionWrite,
    UnsafeFilesystemPathError,
    VolumeIdentityChangedError,
)
from storage.models import VolumeObservation


def _content(data: bytes) -> FileContent:
    return FileContent(len(data), hashlib.sha256(data).hexdigest())


def _recovery_file(
    path: DevicePath,
    source: Path,
    fingerprint: FileFingerprint,
) -> TransactionRecoveryFile:
    return TransactionRecoveryFile(
        path,
        HostPath(source),
        FileContent(fingerprint.size, fingerprint.sha256),
        fingerprint.modified_ns,
    )


def _external_plan(
    tmp_path: Path,
    session: FilesystemSession,
) -> tuple[StorageTransaction, TransactionRecoveryMaterial, DevicePath]:
    target = DevicePath("database.bin")
    previous = session.atomic_write(target, b"old database").fingerprint
    original = tmp_path / "original-database.bin"
    original.write_bytes(b"old database")
    desired = tmp_path / "desired-database.bin"
    desired.write_bytes(b"new database")
    recovery = TransactionRecoveryMaterial(
        "safety-snapshot:external",
        (_recovery_file(target, original, previous),),
    )
    return (
        StorageTransaction(
            writes=(
                TransactionWrite(
                    target,
                    HostPath(desired),
                    _content(b"new database"),
                    previous,
                    modified_ns=946_684_800_000_000_000,
                ),
            ),
            recovery_material=recovery,
        ),
        recovery,
        target,
    )


def _plan(root: Path, session: FilesystemSession) -> StorageTransaction:
    for name, data in (
        ("art.bin", b"old art"),
        ("database.bin", b"old database"),
        ("old-media.bin", b"old media"),
        ("retained.bin", b"retained"),
    ):
        (root / name).write_bytes(data)
    writes = tuple(
        TransactionWrite(
            DevicePath(name),
            data,
            _content(data),
            session.fingerprint(DevicePath(name))
            if session.exists(DevicePath(name))
            else None,
        )
        for name, data in (
            ("new/media.bin", b"new media"),
            ("art.bin", b"new art"),
            ("database.bin", b"new database"),
        )
    )
    return StorageTransaction(
        writes,
        (
            TransactionRemoval(
                DevicePath("old-media.bin"),
                session.fingerprint(DevicePath("old-media.bin")),
            ),
        ),
        (
            FilePrecondition(
                DevicePath("retained.bin"),
                session.fingerprint(DevicePath("retained.bin")),
            ),
        ),
    )


def _assert_original(session: FilesystemSession) -> None:
    assert not session.exists(DevicePath("new/media.bin"))
    assert session.read(DevicePath("art.bin")) == b"old art"
    assert session.read(DevicePath("database.bin")) == b"old database"
    assert session.read(DevicePath("old-media.bin")) == b"old media"
    assert session.read(DevicePath("retained.bin")) == b"retained"


@pytest.mark.parametrize("external_recovery", [False, True])
def test_successful_transaction_reuses_verified_files_after_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    external_recovery: bool,
) -> None:
    root, _, session = _session(tmp_path)
    plan = (
        _external_plan(tmp_path, session)[0]
        if external_recovery
        else _plan(root, session)
    )
    committed = False
    post_commit_reads: list[Path] = []
    fingerprint_path = session._fingerprint_path  # pyright: ignore[reportPrivateUsage]
    fingerprint = session.fingerprint

    def observe(event: TransactionProgress) -> None:
        nonlocal committed
        committed = event.state is TransactionState.COMMITTED

    def count_private(path: Path) -> FileFingerprint:
        if committed:
            post_commit_reads.append(path)
        return fingerprint_path(path)

    def count_public(path: DevicePath) -> FileFingerprint:
        if committed:
            post_commit_reads.append(root / str(path))
        return fingerprint(path)

    monkeypatch.setattr(session, "_fingerprint_path", count_private)
    monkeypatch.setattr(session, "fingerprint", count_public)
    result = session.execute_transaction(plan, progress=observe)

    assert post_commit_reads == []
    # Independent recovery inspection remains a full read and produces the same
    # authority as the final verification performed during execution.
    assert session.inspect_transaction(result.recovery.journal_path) == result.recovery


def test_move_checks_each_original_once_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, session = _session(tmp_path)
    source = DevicePath("source.bin")
    destination = DevicePath("destination.bin")
    source_fingerprint = session.atomic_write(source, b"source").fingerprint
    destination_fingerprint = session.atomic_write(
        destination, b"destination"
    ).fingerprint
    fingerprint_path = session._fingerprint_path  # pyright: ignore[reportPrivateUsage]
    reads: list[Path] = []

    def count(path: Path) -> FileFingerprint:
        reads.append(path)
        return fingerprint_path(path)

    monkeypatch.setattr(session, "_fingerprint_path", count)
    session.move(
        source,
        destination,
        expected_source=source_fingerprint,
        expected_destination=destination_fingerprint,
    )

    assert reads == [
        root / str(source),
        root / str(destination),
        root / str(destination),
    ]


@pytest.mark.parametrize("external_recovery", [False, True])
def test_replacement_validation_reads_scale_with_the_number_of_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    external_recovery: bool,
) -> None:
    root, _, session = _session(tmp_path)
    writes: list[TransactionWrite] = []
    originals: list[TransactionRecoveryFile] = []
    for index in range(4):
        path = DevicePath(f"media-{index}.bin")
        previous = session.atomic_write(path, b"original").fingerprint
        original = tmp_path / f"original-{index}.bin"
        original.write_bytes(b"original")
        desired = tmp_path / f"desired-{index}.bin"
        desired.write_bytes(b"replacement")
        writes.append(
            TransactionWrite(
                path, HostPath(desired), _content(b"replacement"), previous
            )
        )
        originals.append(_recovery_file(path, original, previous))
    plan = StorageTransaction(
        tuple(writes),
        recovery_material=(
            TransactionRecoveryMaterial("originals", tuple(originals))
            if external_recovery
            else None
        ),
    )
    fingerprint_path = session._fingerprint_path  # pyright: ignore[reportPrivateUsage]
    fingerprint = session.fingerprint
    reads: list[DevicePath] = []
    targets = {write.path for write in writes}

    def count_private(path: Path) -> FileFingerprint:
        relative = DevicePath(path.relative_to(root).as_posix())
        if relative in targets:
            reads.append(relative)
        return fingerprint_path(path)

    def count_public(path: DevicePath) -> FileFingerprint:
        if path in targets:
            reads.append(path)
        return fingerprint(path)

    monkeypatch.setattr(session, "_fingerprint_path", count_private)
    monkeypatch.setattr(session, "fingerprint", count_public)
    session.execute_transaction(plan)

    maximum_reads = 6 if external_recovery else 5
    assert len(reads) <= maximum_reads * len(writes)
    assert all(reads.count(write.path) <= maximum_reads for write in writes)


def test_add_without_removals_has_one_final_output_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, session = _session(tmp_path)
    path = DevicePath("media.bin")
    plan = StorageTransaction((TransactionWrite(path, b"media", _content(b"media")),))
    fingerprint = session.fingerprint
    reads: list[DevicePath] = []

    def count(target: DevicePath) -> FileFingerprint:
        if target == path:
            reads.append(target)
        return fingerprint(target)

    monkeypatch.setattr(session, "fingerprint", count)
    session.execute_transaction(plan)
    assert reads == [path]


@pytest.mark.parametrize("replacing", [False, True])
def test_write_without_removals_still_verifies_content_before_commit(
    tmp_path: Path,
    replacing: bool,
) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("media.bin")
    expected = (
        session.atomic_write(path, b"original").fingerprint if replacing else None
    )
    plan = StorageTransaction(
        (TransactionWrite(path, b"media", _content(b"media"), expected),)
    )

    def corrupt(event: TransactionProgress) -> None:
        if event.state is TransactionState.PUBLISHING and event.completed == 1:
            (root / str(path)).write_bytes(b"wrong")

    with pytest.raises(RecoverableWriteError, match="did not verify"):
        session.execute_transaction(plan, progress=corrupt)


@pytest.mark.parametrize("external_recovery", [False, True])
def test_reused_commit_observation_cannot_restore_over_a_later_edit(
    tmp_path: Path,
    external_recovery: bool,
) -> None:
    root, _, session = _session(tmp_path)
    plan = (
        _external_plan(tmp_path, session)[0]
        if external_recovery
        else _plan(root, session)
    )

    def edit_after_commit(event: TransactionProgress) -> None:
        if event.state is TransactionState.COMMITTED:
            target = root / "database.bin"
            metadata = target.stat()
            target.write_bytes(b"bad database")
            # Hash validation must still reject a same-size edit even on a
            # coarse-timestamp filesystem or after the modification time is reset.
            os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

    result = session.execute_transaction(plan, progress=edit_after_commit)
    with pytest.raises(FilePreconditionError, match="changed"):
        session.restore_transaction(
            result.recovery, recovery_material=plan.recovery_material
        )
    assert session.read(DevicePath("database.bin")) == b"bad database"


def test_transaction_publishes_in_order_and_restores_all_originals(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    plan = _plan(root, session)
    events: list[TransactionProgress] = []

    def observe(event: TransactionProgress) -> None:
        events.append(event)
        if event.state is TransactionState.PUBLISHING and event.completed < 3:
            assert session.read(DevicePath("database.bin")) == b"old database"
        if event.state is TransactionState.PUBLISHING and event.completed < 4:
            assert session.read(DevicePath("old-media.bin")) == b"old media"

    validation = session.validate_transaction(plan)
    assert validation.required_bytes > sum(w.content.size for w in plan.writes)
    assert not (root / ".iopenpod-recovery").exists()
    result = session.execute_transaction(plan, progress=observe)
    assert result.flush.complete and result.recovery.state is TransactionState.COMMITTED
    assert session.read(DevicePath("new/media.bin")) == b"new media"
    assert session.read(DevicePath("art.bin")) == b"new art"
    assert session.read(DevicePath("database.bin")) == b"new database"
    assert not session.exists(DevicePath("old-media.bin"))
    restored = session.restore_transaction(result.recovery)
    assert restored.recovery.state is TransactionState.RESTORED
    _assert_original(session)
    session.restore_transaction(restored.recovery)
    _assert_original(session)
    assert [e.completed for e in events if e.state is TransactionState.PUBLISHING] == [
        1,
        2,
        3,
        4,
    ]


def test_verification_and_recovery_report_files_before_reading_them(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    plan = _plan(root, session)
    events: list[TransactionActivity] = []
    published = False

    def progress(event: TransactionProgress) -> None:
        nonlocal published
        if event.state is TransactionState.PUBLISHING and event.completed == len(
            plan.writes
        ):
            published = True

    def activity(event: TransactionActivity) -> None:
        events.append(event)
        if event.phase is TransactionActivityPhase.VERIFYING_WRITES:
            assert published
            assert event.path is not None
            assert session.exists(event.path)

    result = session.execute_transaction(plan, progress=progress, activity=activity)
    verified = [
        event
        for event in events
        if event.phase is TransactionActivityPhase.VERIFYING_WRITES
    ]
    assert tuple(event.path for event in verified) == tuple(
        write.path for write in plan.writes
    )
    assert verified[0].completed == 0
    assert verified[0].total == len(plan.writes)
    assert any(
        event.phase is TransactionActivityPhase.FLUSHING and event.total is None
        for event in events
    )
    events.clear()
    observed = session.inspect_transaction(
        result.recovery.journal_path, activity=events.append
    )
    assert any(event.phase is TransactionActivityPhase.INSPECTING for event in events)
    assert any(event.phase is TransactionActivityPhase.RECHECKING for event in events)
    events.clear()
    session.restore_transaction(observed, activity=events.append)
    assert any(
        event.phase is TransactionActivityPhase.VERIFYING_RECOVERY for event in events
    )
    _assert_original(session)


def test_cleanup_tolerates_companion_deleted_with_its_data_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))
    namespace = root / str(result.recovery.journal_path.parent)
    data = namespace / "retired-test.bin"
    companion = namespace / "._retired-test.bin"
    data.write_bytes(b"retired")
    companion.write_bytes(b"AppleDouble")
    unlink = Path.unlink

    def remove_with_companion(path: Path, missing_ok: bool = False) -> None:
        unlink(path, missing_ok=missing_ok)
        if path == data:
            unlink(companion, missing_ok=True)

    # Make the companion appear later in the already captured directory listing.
    enumerate_entries = session._transaction_namespace_entries  # pyright: ignore[reportPrivateUsage]

    def entries(directory: Path, *, preserved: Path) -> tuple[tuple[Path, bool], ...]:
        found = enumerate_entries(directory, preserved=preserved)
        return tuple(sorted(found, key=lambda item: item[0] == companion))

    monkeypatch.setattr(session, "_transaction_namespace_entries", entries)
    monkeypatch.setattr(Path, "unlink", remove_with_companion)
    assert session.finalize_transaction(result.recovery).complete
    assert not namespace.exists()


def test_restored_cleanup_uses_verified_marker_and_never_rehashes_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))
    with pytest.raises(FilePreconditionError, match="verified restored"):
        session.finalize_restored_transaction(result.recovery.journal_path)
    restored = session.restore_transaction(result.recovery)
    fingerprint = session.fingerprint

    def only_journal(path: DevicePath) -> FileFingerprint:
        assert path == restored.recovery.journal_path
        return fingerprint(path)

    monkeypatch.setattr(session, "fingerprint", only_journal)
    assert session.finalize_restored_transaction(
        restored.recovery.journal_path
    ).complete
    _assert_original(session)


def test_external_recovery_transaction_restores_verified_host_originals(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    database = DevicePath("database.bin")
    obsolete = DevicePath("old-media.bin")
    (root / str(database)).write_bytes(b"old database")
    (root / str(obsolete)).write_bytes(b"old media")
    old_database = session.fingerprint(database)
    old_obsolete = session.fingerprint(obsolete)
    recovery_database = tmp_path / "recovery-database.bin"
    recovery_obsolete = tmp_path / "recovery-old-media.bin"
    recovery_database.write_bytes(b"old database")
    recovery_obsolete.write_bytes(b"old media")
    desired = tmp_path / "desired-database.bin"
    desired.write_bytes(b"new database")
    desired_mtime = 946_684_800_000_000_000
    recovery = TransactionRecoveryMaterial(
        "safety-snapshot:abc123",
        (
            _recovery_file(database, recovery_database, old_database),
            _recovery_file(obsolete, recovery_obsolete, old_obsolete),
        ),
    )
    plan = StorageTransaction(
        writes=(
            TransactionWrite(
                database,
                HostPath(desired),
                _content(b"new database"),
                old_database,
                modified_ns=desired_mtime,
            ),
        ),
        removals=(TransactionRemoval(obsolete, old_obsolete),),
        recovery_material=recovery,
    )

    committed = session.execute_transaction(plan)

    assert session.read(database) == b"new database"
    assert session.stat(database).modified_ns == desired_mtime
    assert not session.exists(obsolete)
    assert committed.recovery.recovery_material_identity == "safety-snapshot:abc123"

    session.restore_transaction(
        committed.recovery,
        recovery_material=recovery,
    )

    assert session.read(database) == b"old database"
    assert session.stat(database).modified_ns == old_database.modified_ns
    assert session.read(obsolete) == b"old media"


def test_recovery_observation_names_only_required_external_material_paths(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    plan, _material, target = _external_plan(tmp_path, session)
    retained = DevicePath("retained.bin")
    (root / retained.name).write_bytes(b"unchanged")
    plan = replace(
        plan,
        dependencies=(FilePrecondition(retained, session.fingerprint(retained)),),
    )

    result = session.execute_transaction(plan)

    assert result.recovery.recovery_material_paths == (target,)
    assert tuple(file.path for file in result.recovery.files) == (target, retained)


def test_external_transaction_journal_retains_identity_without_host_paths(
    tmp_path: Path,
) -> None:
    _, _, session = _session(tmp_path)
    plan, material, _ = _external_plan(tmp_path, session)

    committed = session.execute_transaction(plan)
    journal = session.read(committed.recovery.journal_path)

    assert b'"version":2' in journal
    assert material.identity.encode() in journal
    for file in material.files:
        assert os.fsencode(file.source) not in journal
    for write in plan.writes:
        if isinstance(write.source, HostPath):
            assert os.fsencode(write.source) not in journal


def test_transaction_uses_caller_chosen_journal_identity(tmp_path: Path) -> None:
    _, _, session = _session(tmp_path)
    plan, _, _ = _external_plan(tmp_path, session)
    identity = "0123456789abcdef0123456789abcdef"

    result = session.execute_transaction(replace(plan, journal_identity=identity))

    assert result.recovery.journal_path == DevicePath(
        f".iopenpod-recovery/{identity}/transaction.json"
    )


@pytest.mark.parametrize(
    "identity",
    ("", "ABCDEF0123456789abcdef0123456789", "g" * 32, "0" * 31, "0" * 33),
)
def test_transaction_rejects_invalid_journal_identity(identity: str) -> None:
    with pytest.raises(ValueError, match="journal identity"):
        StorageTransaction((), journal_identity=identity)


def test_external_transaction_capacity_is_bounded_by_largest_file(
    tmp_path: Path,
) -> None:
    _, _, session = _session(tmp_path)
    plan, _, _ = _external_plan(tmp_path, session)

    bounded = session.validate_transaction(plan)
    retained = session.validate_transaction(replace(plan, recovery_material=None))

    assert bounded.required_bytes < retained.required_bytes


def test_external_transaction_capacity_includes_accumulated_new_files(
    tmp_path: Path,
) -> None:
    _, _, session = _session(tmp_path)
    recovery = TransactionRecoveryMaterial("empty-safety-snapshot", ())
    first = TransactionWrite(DevicePath("first.bin"), b"a", _content(b"a"))
    second = TransactionWrite(DevicePath("second.bin"), b"b", _content(b"b"))

    one_file = session.validate_transaction(
        StorageTransaction((first,), recovery_material=recovery)
    )
    two_files = session.validate_transaction(
        StorageTransaction((first, second), recovery_material=recovery)
    )

    unit = session.mounted_volume.volume.capabilities.allocation_unit_size
    assert unit is not None
    assert two_files.required_bytes >= one_file.required_bytes + unit


def test_external_transaction_incomplete_prepare_flush_never_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, platform, session = _session(tmp_path)
    plan, _, target = _external_plan(tmp_path, session)

    def incomplete_flush(_observation: VolumeObservation) -> FlushResult:
        return FlushResult(False, "barrier unavailable")

    monkeypatch.setattr(
        platform,
        "flush",
        incomplete_flush,
    )

    with pytest.raises(TransactionPreparedError) as caught:
        session.execute_transaction(plan)

    assert session.read(target) == b"old database"
    assert not caught.value.facts.publication_started
    assert not caught.value.facts.content_verified
    assert caught.value.facts.recovery_material_identity == "safety-snapshot:external"


def test_external_transaction_rejects_corrupt_recovery_before_journaling(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    plan, material, target = _external_plan(tmp_path, session)
    Path(material.files[0].source).write_bytes(b"corrupt")

    with pytest.raises(ConcurrentModificationError, match="did not verify"):
        session.execute_transaction(plan)

    assert session.read(target) == b"old database"
    assert not (root / ".iopenpod-recovery").exists()


def test_external_transaction_native_publish_then_error_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, session = _session(tmp_path)
    plan, _, target = _external_plan(tmp_path, session)
    native_replace = os.replace

    def publish_then_fail(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        native_replace(source, destination)
        if Path(destination) == root / str(target):
            raise OSError("directory flush failed after publication")

    monkeypatch.setattr(os, "replace", publish_then_fail)

    with pytest.raises(TransactionInterruptedError) as caught:
        session.execute_transaction(plan)

    assert (root / str(target)).read_bytes() == b"new database"
    assert caught.value.facts.publication_started
    assert caught.value.facts.device_changed
    assert not caught.value.facts.content_verified
    assert caught.value.facts.state is TransactionState.PUBLISHING


def test_external_transaction_recovers_after_publish_then_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, session = _session(tmp_path)
    plan, material, target = _external_plan(tmp_path, session)
    original_mtime = plan.writes[0].expected
    assert original_mtime is not None
    native_replace = os.replace

    def publish_then_fail(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        native_replace(source, destination)
        if Path(destination) == root / str(target):
            raise OSError("failed after replacement")

    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", publish_then_fail)
        with pytest.raises(TransactionInterruptedError) as caught:
            session.execute_transaction(plan)

    recovery = session.inspect_transaction(DevicePath(caught.value.recovery_path))
    session.restore_transaction(recovery, recovery_material=material)

    assert session.read(target) == b"old database"
    assert session.stat(target).modified_ns == original_mtime.modified_ns


def test_external_recovery_resumes_after_restore_publish_then_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, session = _session(tmp_path)
    plan, material, target = _external_plan(tmp_path, session)
    original = plan.writes[0].expected
    assert original is not None
    committed = session.execute_transaction(plan)
    native_replace = os.replace

    def restore_then_fail(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        native_replace(source, destination)
        if Path(destination) == root / str(target):
            raise OSError("failed after restoring content")

    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", restore_then_fail)
        with pytest.raises(TransactionInterruptedError):
            session.restore_transaction(
                committed.recovery,
                recovery_material=material,
            )

    recovery = session.inspect_transaction(committed.recovery.journal_path)
    assert recovery.state is TransactionState.RESTORING
    session.restore_transaction(recovery, recovery_material=material)

    assert session.read(target) == b"old database"
    assert session.stat(target).modified_ns == original.modified_ns


def test_external_transaction_verified_content_with_incomplete_flush_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, platform, session = _session(tmp_path)
    plan, _, target = _external_plan(tmp_path, session)
    flush_count = 0

    def flush(_observation: object) -> FlushResult:
        nonlocal flush_count
        flush_count += 1
        if flush_count == 4:
            return FlushResult(False, "volume barrier pending")
        return FlushResult(True, "flushed")

    monkeypatch.setattr(platform, "flush", flush)

    with pytest.raises(TransactionDurabilityPendingError) as caught:
        session.execute_transaction(plan)

    assert session.read(target) == b"new database"
    assert caught.value.facts.publication_started
    assert caught.value.facts.content_verified
    assert caught.value.facts.state is TransactionState.PUBLISHING


@pytest.mark.parametrize("restore_first", [False, True])
def test_finalize_terminal_transaction_removes_only_its_exact_namespace(
    tmp_path: Path,
    restore_first: bool,
) -> None:
    _, _, session = _session(tmp_path)
    plan, material, _ = _external_plan(tmp_path, session)
    result = session.execute_transaction(plan)
    if restore_first:
        result = session.restore_transaction(
            result.recovery,
            recovery_material=material,
        )
    sibling = DevicePath(".iopenpod-recovery/ffffffffffffffffffffffffffffffff/keep.bin")
    session.atomic_write(sibling, b"keep", create_parents=True)
    namespace = result.recovery.journal_path.parent
    assert namespace is not None

    first = session.finalize_transaction(result.recovery)
    second = session.finalize_transaction(result.recovery)

    assert first.complete and second.complete
    assert not session.exists(namespace)
    assert session.read(sibling) == b"keep"


def test_finalize_missing_transaction_removes_an_exact_empty_namespace(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    journal = DevicePath(
        ".iopenpod-recovery/0123456789abcdef0123456789abcdef/transaction.json"
    )
    namespace = journal.parent
    assert namespace is not None
    root.joinpath(*namespace.parts).mkdir(parents=True)
    sibling = DevicePath(".iopenpod-recovery/ffffffffffffffffffffffffffffffff/keep.bin")
    session.atomic_write(sibling, b"keep", create_parents=True)

    result = session.finalize_missing_transaction(journal)

    assert result.complete
    assert not session.exists(namespace)
    assert session.read(sibling) == b"keep"


def test_finalize_missing_transaction_rejects_a_nonempty_namespace(
    tmp_path: Path,
) -> None:
    _, _, session = _session(tmp_path)
    journal = DevicePath(
        ".iopenpod-recovery/0123456789abcdef0123456789abcdef/transaction.json"
    )
    namespace = journal.parent
    assert namespace is not None
    unexpected = namespace.joinpath("unexpected.bin")
    session.atomic_write(unexpected, b"keep", create_parents=True)

    with pytest.raises(FilePreconditionError, match="not empty"):
        session.finalize_missing_transaction(journal)

    assert session.read(unexpected) == b"keep"


def test_finalize_rejects_stale_terminal_journal_observation(tmp_path: Path) -> None:
    _, _, session = _session(tmp_path)
    plan, _, _ = _external_plan(tmp_path, session)
    result = session.execute_transaction(plan)
    journal = result.recovery.journal_path
    payload = session.read(journal)
    session.atomic_write(
        journal,
        payload + b" ",
        expected=result.recovery.journal_fingerprint,
    )

    with pytest.raises(FilePreconditionError, match="changed"):
        session.finalize_transaction(result.recovery)

    namespace = journal.parent
    assert namespace is not None
    assert session.exists(namespace)


def test_finalize_rejects_prepared_transaction(tmp_path: Path) -> None:
    _, _, session = _session(tmp_path)
    plan, _, _ = _external_plan(tmp_path, session)

    def stop_at_prepared(event: TransactionProgress) -> None:
        if event.state is TransactionState.PREPARED:
            raise InterruptedError("stop before publication")

    with pytest.raises(TransactionPreparedError) as caught:
        session.execute_transaction(plan, progress=stop_at_prepared)
    recovery = session.inspect_transaction(DevicePath(caught.value.recovery_path))

    with pytest.raises(FilePreconditionError, match="committed or restored"):
        session.finalize_transaction(recovery)

    assert session.exists(recovery.journal_path)


def test_finalize_preflights_unsafe_namespace_before_deleting_entries(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    plan, _, _ = _external_plan(tmp_path, session)
    result = session.execute_transaction(plan)
    namespace = result.recovery.journal_path.parent
    assert namespace is not None
    safe = namespace.joinpath("safe.bin")
    session.atomic_write(safe, b"keep", create_parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root.joinpath(*namespace.parts, "unsafe-link")
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory links unavailable: {error}")

    with pytest.raises(UnsafeFilesystemPathError):
        session.finalize_transaction(result.recovery)

    assert session.read(safe) == b"keep"
    assert outside.exists()


def test_finalize_durability_failure_is_typed_and_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, platform, session = _session(tmp_path)
    plan, _, _ = _external_plan(tmp_path, session)
    result = session.execute_transaction(plan)
    namespace = result.recovery.journal_path.parent
    assert namespace is not None
    native_flush = platform.flush

    def incomplete_flush(_observation: VolumeObservation) -> FlushResult:
        return FlushResult(False, "barrier pending")

    monkeypatch.setattr(
        platform,
        "flush",
        incomplete_flush,
    )

    with pytest.raises(TransactionDurabilityPendingError) as caught:
        session.finalize_transaction(result.recovery)

    assert caught.value.facts.state is TransactionState.COMMITTED
    assert caught.value.facts.content_verified
    assert not session.exists(namespace)
    monkeypatch.setattr(platform, "flush", native_flush)
    assert session.finalize_transaction(result.recovery).complete


@pytest.mark.parametrize("completed", [1, 2, 3, 4])
def test_interrupted_restoration_resumes_after_reconnection(
    tmp_path: Path, completed: int
) -> None:
    root, platform, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))

    def interrupt(event: TransactionProgress) -> None:
        if event.completed == completed:
            platform.disconnect(root)
            raise OSError("unplugged during restoration")

    with pytest.raises(RecoverableWriteError):
        session.restore_transaction(result.recovery, progress=interrupt)
    platform.reconnect(root)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        recovery = reconnected.inspect_transaction(result.recovery.journal_path)
        assert recovery.state is TransactionState.RESTORING
        reconnected.restore_transaction(recovery)
        _assert_original(reconnected)


@pytest.mark.parametrize("boundary", range(1, 14))
def test_disconnect_after_each_native_rename_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: int
) -> None:
    root, platform, session = _session(tmp_path)
    plan = _plan(root, session)
    native_replace = os.replace
    count = 0

    def interrupt(
        source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        nonlocal count
        native_replace(source, target)
        count += 1
        if count == boundary:
            platform.disconnect(root)

    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", interrupt)
        with pytest.raises(RecoverableWriteError) as caught:
            session.execute_transaction(plan)
    assert count == boundary
    platform.reconnect(root)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        reconnected.restore_transaction(
            reconnected.inspect_transaction(DevicePath(caught.value.recovery_path))
        )
        _assert_original(reconnected)


@pytest.mark.parametrize("boundary", range(1, 7))
def test_disconnect_after_each_restoration_rename_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: int
) -> None:
    root, platform, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))
    native_replace = os.replace
    count = 0

    def interrupt(
        source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        nonlocal count
        native_replace(source, target)
        count += 1
        if count == boundary:
            platform.disconnect(root)

    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", interrupt)
        with pytest.raises(RecoverableWriteError):
            session.restore_transaction(result.recovery)
    assert count == boundary
    platform.reconnect(root)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        reconnected.restore_transaction(
            reconnected.inspect_transaction(result.recovery.journal_path)
        )
        _assert_original(reconnected)


def test_other_thread_waits_for_whole_transaction(tmp_path: Path) -> None:
    root, platform, session = _session(tmp_path)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    plan = _plan(root, session)
    attempted = threading.Event()
    finished = threading.Event()
    with (
        storage.open_session(
            storage.discover().volumes[0], access=AccessMode.READ_WRITE
        ) as competitor,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):

        def other_write() -> None:
            attempted.set()
            competitor.atomic_write(DevicePath("competitor.bin"), b"later")
            finished.set()

        def observe(event: TransactionProgress) -> None:
            if event.state is TransactionState.PREPARED:
                executor.submit(other_write)
                assert attempted.wait(5)
                assert not finished.wait(0.05)
            if event.state is TransactionState.COMMITTED:
                assert not finished.is_set()

        session.execute_transaction(plan, progress=observe)
        assert finished.wait(5)
    assert session.read(DevicePath("competitor.bin")) == b"later"


def test_insufficient_restoration_space_blocks_before_any_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, session = _session(tmp_path)
    plan = _plan(root, session)
    (root / "art.bin").write_bytes(b"large original art" * 10000)
    plan = replace(
        plan,
        writes=(
            plan.writes[0],
            replace(
                plan.writes[1], expected=session.fingerprint(DevicePath("art.bin"))
            ),
            plan.writes[2],
        ),
    )
    result = session.execute_transaction(plan)
    usage = shutil.disk_usage(root)

    def limited_disk_usage(_path: Path) -> tuple[int, int, int]:
        return usage._replace(free=32768)

    # Enough for restoring the first two (small) originals, but not the later art.
    monkeypatch.setattr(shutil, "disk_usage", limited_disk_usage)
    with pytest.raises(StorageCapacityError):
        session.restore_transaction(result.recovery)
    assert (
        session.fingerprint(result.recovery.journal_path)
        == result.recovery.journal_fingerprint
    )
    assert session.read(DevicePath("database.bin")) == b"new database"
    assert not session.exists(DevicePath("old-media.bin"))


@pytest.mark.parametrize(
    "other",
    ["new/media.bin", "new", ".iopenpod-recovery/anything", ".iopenpod-trash/anything"],
)
def test_colliding_or_reserved_paths_rejected_without_staging(
    tmp_path: Path, other: str
) -> None:
    root, _, session = _session(tmp_path)
    plan = _plan(root, session)
    plan = replace(
        plan, dependencies=(*plan.dependencies, FilePrecondition(DevicePath(other)))
    )
    with pytest.raises(ValueError):
        session.execute_transaction(plan)
    assert not (root / ".iopenpod-recovery").exists()
    _assert_original(session)


def test_normalization_equivalent_transaction_paths_are_rejected(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    plan = StorageTransaction(
        writes=(
            TransactionWrite(
                DevicePath.from_parts(("café.bin",)),
                b"new",
                _content(b"new"),
            ),
        ),
        dependencies=(FilePrecondition(DevicePath.from_parts(("café.bin",))),),
    )

    with pytest.raises(ValueError, match="duplicate or aliased"):
        session.execute_transaction(plan)
    assert not (root / ".iopenpod-recovery").exists()


def test_capacity_reserve_rejected_before_staging(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    plan = replace(_plan(root, session), reserve_bytes=10**30)
    with pytest.raises(StorageCapacityError):
        session.execute_transaction(plan)
    assert not (root / ".iopenpod-recovery").exists()
    _assert_original(session)


def test_initial_cancellation_does_not_report_nonexistent_recovery(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    plan = _plan(root, session)

    def cancel() -> None:
        raise InterruptedError("cancelled before staging")

    with pytest.raises(InterruptedError):
        session.execute_transaction(plan, checkpoint=cancel)
    assert not (root / ".iopenpod-recovery").exists()
    _assert_original(session)


def test_recovery_refuses_another_physical_device(tmp_path: Path) -> None:
    root, platform, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))
    platform.replace_identity(
        root, device_id="different-device", volume_id="different-volume"
    )
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with (
        storage.open_session(
            storage.discover().volumes[0], access=AccessMode.READ_WRITE
        ) as other,
        pytest.raises(VolumeIdentityChangedError),
    ):
        other.inspect_transaction(result.recovery.journal_path)
    assert (root / "database.bin").read_bytes() == b"new database"


@pytest.mark.parametrize("completed", [1, 2, 3, 4])
def test_interrupted_publication_recovers_after_reconnection(
    tmp_path: Path, completed: int
) -> None:
    root, platform, session = _session(tmp_path)
    plan = _plan(root, session)

    def interrupt(event: TransactionProgress) -> None:
        if event.state is TransactionState.PUBLISHING and event.completed == completed:
            platform.disconnect(root)
            raise OSError("unplugged")

    with pytest.raises(RecoverableWriteError) as caught:
        session.execute_transaction(plan, progress=interrupt)
    assert caught.value.publication_started
    with pytest.raises(StorageError):
        session.read(DevicePath("database.bin"))
    platform.reconnect(root)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        recovery = reconnected.inspect_transaction(
            DevicePath(caught.value.recovery_path)
        )
        assert recovery.state is TransactionState.PUBLISHING
        reconnected.restore_transaction(recovery)
        _assert_original(reconnected)


def test_later_edit_blocks_entire_recovery_before_any_restore(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))
    (root / "art.bin").write_bytes(b"unrelated edit")
    recovery = session.inspect_transaction(result.recovery.journal_path)
    with pytest.raises(FilePreconditionError, match="unrelated edit"):
        session.restore_transaction(recovery)
    assert session.read(DevicePath("database.bin")) == b"new database"
    assert not session.exists(DevicePath("old-media.bin"))


def test_corrupt_original_blocks_all_recovery(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))
    (root / str(result.recovery.journal_path)).with_name("original-1.bin").write_bytes(
        b"corrupt"
    )
    with pytest.raises(FilePreconditionError, match="content did not verify"):
        session.restore_transaction(result.recovery)
    assert session.read(DevicePath("database.bin")) == b"new database"
    assert not session.exists(DevicePath("old-media.bin"))


def test_stale_observation_cannot_restore(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))
    (root / "retained.bin").write_bytes(b"changed")
    with pytest.raises(FilePreconditionError):
        session.restore_transaction(result.recovery)
    assert session.read(DevicePath("database.bin")) == b"new database"


def test_cancel_before_publication_keeps_originals(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)

    def cancel(event: TransactionProgress) -> None:
        if event.state is TransactionState.PREPARED:
            raise InterruptedError("cancelled")

    with pytest.raises(RecoverableWriteError) as caught:
        session.execute_transaction(_plan(root, session), progress=cancel)
    assert not caught.value.publication_started
    _assert_original(session)
    session.restore_transaction(
        session.inspect_transaction(DevicePath(caught.value.recovery_path))
    )
    _assert_original(session)


@pytest.mark.parametrize("same_size", [False, True])
def test_host_source_is_streamed_and_its_content_verified(
    tmp_path: Path, same_size: bool
) -> None:
    _, _, session = _session(tmp_path)
    data = b"payload" * 400000
    host = tmp_path / "host.bin"
    host.write_bytes(data)
    plan = StorageTransaction(
        (TransactionWrite(DevicePath("large.bin"), HostPath(host), _content(data)),)
    )
    result = session.execute_transaction(plan)
    assert session.fingerprint(DevicePath("large.bin")).sha256 == _content(data).sha256
    session.restore_transaction(result.recovery)
    assert not session.exists(DevicePath("large.bin"))
    host.write_bytes(b"x" * len(data) if same_size else b"changed after capture")
    with pytest.raises(RecoverableWriteError) as caught:
        session.execute_transaction(plan)
    assert not caught.value.publication_started
    assert not session.exists(DevicePath("large.bin"))


def test_transaction_holds_one_writer_lease(tmp_path: Path) -> None:
    root, platform, session = _session(tmp_path)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as competitor:

        def attempt(event: TransactionProgress) -> None:
            with pytest.raises(DeviceBusyError):
                competitor.atomic_write(DevicePath("competitor.bin"), b"unexpected")

        session.execute_transaction(_plan(root, session), progress=attempt)
    assert not session.exists(DevicePath("competitor.bin"))


def test_readonly_session_can_validate_but_cannot_execute(tmp_path: Path) -> None:
    root, platform, session = _session(tmp_path)
    plan = _plan(root, session)
    storage = Storage(platform)
    with storage.open_session(storage.discover().volumes[0]) as reader:
        assert reader.validate_transaction(plan).required_bytes > 0
        with pytest.raises(ReadOnlyFilesystemError):
            reader.execute_transaction(plan)
    _assert_original(session)


def test_changed_later_stage_is_detected_before_first_publication(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)

    def corrupt(event: TransactionProgress) -> None:
        if event.state is TransactionState.PREPARED:
            files = tuple((root / ".iopenpod-recovery").glob("*/staged-2.bin"))
            assert len(files) == 1
            files[0].write_bytes(b"corrupt")

    with pytest.raises(RecoverableWriteError) as caught:
        session.execute_transaction(_plan(root, session), progress=corrupt)
    assert not caught.value.publication_started
    _assert_original(session)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (b'"version":1', b'"version":true'),
        (b'"version":1', b'"version":2'),
        (b'"version":1', b'"version":1,"version":1'),
        (b'"state":"committed"', b'"state":"unknown"'),
        (b'"path":"art.bin"', b'"path":"new/media.bin"'),
        (b'"path":"art.bin"', b'"path":"new"'),
        (b'"path":"art.bin"', b'"path":"../outside.bin"'),
        (b'"path":"art.bin"', b'"path":".iopenpod-recovery/overwrite.bin"'),
        (b'"size":7', b'"size":-1'),
    ],
)
def test_invalid_journal_cannot_authorize_recovery(
    tmp_path: Path, before: bytes, after: bytes
) -> None:
    root, _, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))
    path = root / str(result.recovery.journal_path)
    original = path.read_bytes()
    assert before in original
    path.write_bytes(original.replace(before, after))
    with pytest.raises((StorageOperationError, ValueError)):
        session.inspect_transaction(result.recovery.journal_path)
    assert session.read(DevicePath("database.bin")) == b"new database"
    assert not session.exists(DevicePath("old-media.bin"))


def test_removal_only_transaction_is_recoverable(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("media.bin")
    (root / str(path)).write_bytes(b"old media")
    result = session.execute_transaction(
        StorageTransaction((), (TransactionRemoval(path, session.fingerprint(path)),))
    )
    assert not session.exists(path)
    session.restore_transaction(result.recovery)
    assert session.read(path) == b"old media"


def test_changed_target_at_final_checkpoint_prevents_all_publication(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    plan = _plan(root, session)

    def edit(event: TransactionProgress) -> None:
        if event.state is TransactionState.PREPARED:
            (root / "database.bin").write_bytes(b"external edit")

    with pytest.raises(RecoverableWriteError) as caught:
        session.execute_transaction(plan, progress=edit)
    assert not caught.value.publication_started
    assert not session.exists(DevicePath("new/media.bin"))
    assert session.read(DevicePath("art.bin")) == b"old art"
    assert session.read(DevicePath("database.bin")) == b"external edit"


def test_cancelling_restoration_leaves_committed_state_and_journal(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    result = session.execute_transaction(_plan(root, session))

    def cancel() -> None:
        raise InterruptedError("cancel restoration")

    with pytest.raises(InterruptedError):
        session.restore_transaction(result.recovery, checkpoint=cancel)
    assert session.inspect_transaction(result.recovery.journal_path) == result.recovery
    assert session.read(DevicePath("database.bin")) == b"new database"
