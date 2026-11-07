"""Read budgets and mutation checks for normal Host-backed publication."""

import os
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from os import PathLike
from pathlib import Path

import pytest
from tests.storage.test_host_transaction_recovery import (
    _small_plan,  # pyright: ignore[reportPrivateUsage]
)

from storage import (
    ConcurrentModificationError,
    CopyResult,
    DevicePath,
    FileFingerprint,
    FilePrecondition,
    FilePreconditionError,
    HostPath,
    RecoverableWriteError,
    TransactionProgress,
    TransactionRecoveryFile,
    TransactionState,
    TransactionWrite,
)
from storage import _transactions as tx
from storage import session as session_module
from storage._filesystem import read_and_fingerprint


@pytest.mark.parametrize("desired_time", [None, 946_684_800_000_000_000])
def test_publication_reads_each_new_file_once_even_with_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, desired_time: int | None
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)
    (root / "dependency").write_bytes(b"retained")
    writes: list[TransactionWrite] = []
    for write in plan.writes:
        assert isinstance(write.source, bytes)
        source = tmp_path / f"incoming-{write.path.name}"
        source.write_bytes(write.source)
        writes.append(replace(write, source=HostPath(source), modified_ns=desired_time))
    plan = replace(
        plan,
        writes=tuple(writes),
        dependencies=(
            FilePrecondition(
                DevicePath("dependency"), session.fingerprint(DevicePath("dependency"))
            ),
        ),
    )
    hashes: Counter[tuple[str, str]] = Counter()
    captures: Counter[str] = Counter()
    host_checks: Counter[str] = Counter()
    original_copy = session.copy_to_host
    original_verify = tx._verify_host_content  # pyright: ignore[reportPrivateUsage]

    def read(
        path: Path,
        *,
        collect_data: bool,
        max_bytes: int | None,
        assert_active: Callable[[], None],
    ) -> tuple[bytes, FileFingerprint]:
        result = read_and_fingerprint(
            path,
            collect_data=collect_data,
            max_bytes=max_bytes,
            assert_active=assert_active,
        )
        if path.parent == root:
            hashes[path.name, result[1].sha256] += 1
        return result

    def copy(
        source: DevicePath,
        destination: HostPath,
        *,
        prepare_staged: Callable[[HostPath], None] | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> CopyResult:
        captures[str(source)] += 1
        return original_copy(
            source, destination, prepare_staged=prepare_staged, progress=progress
        )

    def verify(
        file: TransactionRecoveryFile | TransactionWrite,
        *,
        checkpoint: Callable[[], None] | None,
    ) -> None:
        if isinstance(file.source, HostPath):
            host_checks[Path(file.source).name] += 1
        original_verify(file, checkpoint=checkpoint)

    monkeypatch.setattr(session_module, "read_and_fingerprint", read)
    monkeypatch.setattr(session, "copy_to_host", copy)
    monkeypatch.setattr(tx, "_verify_host_content", verify)
    result = session.execute_transaction(plan)
    session.finalize_committed_transaction(result.recovery.journal_path)

    assert captures == {"replace.bin": 1, "remove.bin": 1}
    for write in writes:
        # Hash the outgoing stream; read the destination once before commit.
        assert hashes[write.path.name, write.content.sha256] == 1, hashes
        if desired_time is not None:
            assert session.stat(write.path).modified_ns == desired_time
    before = plan.writes[0].expected
    assert before is not None
    # Capture validates the initial observation; later checks protect both the
    # complete prepublication boundary and each destructive deletion.
    assert hashes["replace.bin", before.sha256] == 2, hashes
    assert hashes["remove.bin", before.sha256] == 2, hashes
    dependency = plan.dependencies[0].fingerprint
    assert dependency is not None
    assert hashes["dependency", dependency.sha256] == 2, hashes
    assert host_checks == {
        "incoming-replace.bin": 1,
        "incoming-added.bin": 1,
        "original-0.bin": 1,
        "original-2.bin": 1,
    }


@pytest.mark.parametrize("changed", ["target", "dependency", "original", "input"])
def test_changes_at_prepared_callback_block_all_device_publication(
    tmp_path: Path, changed: str
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)
    (root / "dependency").write_bytes(b"retained")
    source = tmp_path / "incoming.bin"
    source.write_bytes(b"new")
    plan = replace(
        plan,
        writes=(replace(plan.writes[0], source=HostPath(source)), plan.writes[1]),
        dependencies=(
            FilePrecondition(
                DevicePath("dependency"), session.fingerprint(DevicePath("dependency"))
            ),
        ),
    )
    publishing = False

    def progress(event: TransactionProgress) -> None:
        nonlocal publishing
        publishing |= event.state is TransactionState.PUBLISHING
        if event.state is TransactionState.PREPARED:
            target = (
                root / "replace.bin"
                if changed == "target"
                else root / "dependency"
                if changed == "dependency"
                else source
                if changed == "input"
                else next((tmp_path / "recovery").rglob("original-0.bin"))
            )
            metadata = target.stat()
            target.write_bytes(b"X" * metadata.st_size)
            os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

    with pytest.raises(RecoverableWriteError):
        session.execute_transaction(plan, progress=progress)
    assert not publishing
    assert (root / "replace.bin").read_bytes() == (
        b"XXXXXXXX" if changed == "target" else b"original"
    )
    assert (root / "remove.bin").read_bytes() == b"original"
    assert not (root / "added.bin").exists()


def test_capture_rejects_replaced_original_even_if_bytes_and_mtime_match(
    tmp_path: Path,
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)
    target = root / "replace.bin"
    metadata = target.stat()
    replacement = root / "external.bin"
    replacement.write_bytes(target.read_bytes())
    os.utime(replacement, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    replacement.replace(target)
    with pytest.raises(FilePreconditionError, match="changed"):
        session.execute_transaction(plan)
    assert (root / "remove.bin").read_bytes() == b"original"
    assert not (root / "added.bin").exists()


def test_final_verification_still_catches_edits_after_individual_publication(
    tmp_path: Path,
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)

    def progress(event: TransactionProgress) -> None:
        if (
            event.state is TransactionState.PUBLISHING
            and event.completed > 0
            and event.path == DevicePath("replace.bin")
        ):
            target = root / "replace.bin"
            metadata = target.stat()
            target.write_bytes(b"bad")
            os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

    with pytest.raises(RecoverableWriteError, match="did not verify") as caught:
        session.execute_transaction(plan, progress=progress)
    assert (
        session.read_transaction_state(DevicePath(caught.value.recovery_path))
        is TransactionState.PUBLISHING
    )
    assert (
        next((tmp_path / "recovery").rglob("original-0.bin")).read_bytes()
        == b"original"
    )


@pytest.mark.parametrize("restoring", [False, True])
def test_corrupted_publication_cannot_record_a_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restoring: bool
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)
    committed = session.execute_transaction(plan) if restoring else None
    native_replace = os.replace

    def corrupt(source: str | PathLike[str], target: str | PathLike[str]) -> None:
        native_replace(source, target)
        destination = Path(target)
        if destination == root / "replace.bin":
            metadata = destination.stat()
            destination.write_bytes(b"X" * metadata.st_size)
            os.utime(destination, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

    monkeypatch.setattr(os, "replace", corrupt)
    with pytest.raises(RecoverableWriteError, match="did not verify") as caught:
        if committed is None:
            session.execute_transaction(plan)
        else:
            session.restore_transaction(committed.recovery)
    assert session.read_transaction_state(DevicePath(caught.value.recovery_path)) is (
        TransactionState.RESTORING if restoring else TransactionState.PUBLISHING
    )
    assert (
        next((tmp_path / "recovery").rglob("original-0.bin")).read_bytes()
        == b"original"
    )


def test_outgoing_stream_hash_rejects_changed_input_before_publication(
    tmp_path: Path,
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)
    source = tmp_path / "incoming.bin"
    source.write_bytes(b"new")
    plan = replace(
        plan,
        writes=(replace(plan.writes[0], source=HostPath(source)), plan.writes[1]),
    )

    def progress(event: TransactionProgress) -> None:
        if event.state is TransactionState.PUBLISHING and event.completed == 0:
            source.write_bytes(b"bad")

    with pytest.raises(RecoverableWriteError, match="captured SHA-256") as caught:
        session.execute_transaction(plan, progress=progress)
    assert not (root / "replace.bin").exists()
    restored = session.restore_transaction(
        session.inspect_transaction(DevicePath(caught.value.recovery_path))
    )
    assert restored.recovery.state is TransactionState.RESTORED
    assert (root / "replace.bin").read_bytes() == b"original"


def test_restored_outputs_are_read_once_before_terminal_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)
    committed = session.execute_transaction(plan)
    original = plan.writes[0].expected
    assert original is not None
    restored_reads: Counter[str] = Counter()

    def read(
        path: Path,
        *,
        collect_data: bool,
        max_bytes: int | None,
        assert_active: Callable[[], None],
    ) -> tuple[bytes, FileFingerprint]:
        result = read_and_fingerprint(
            path,
            collect_data=collect_data,
            max_bytes=max_bytes,
            assert_active=assert_active,
        )
        if path.parent == root and result[1].sha256 == original.sha256:
            restored_reads[path.name] += 1
        return result

    monkeypatch.setattr(session_module, "read_and_fingerprint", read)
    restored = session.restore_transaction(committed.recovery)
    session.finalize_transaction(restored.recovery)
    assert restored_reads == {"replace.bin": 1, "remove.bin": 1}


def test_standalone_atomic_write_still_verifies_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _, session, _ = _small_plan(tmp_path)
    native_replace = os.replace

    def corrupt(source: str | PathLike[str], target: str | PathLike[str]) -> None:
        native_replace(source, target)
        Path(target).write_bytes(b"bad")

    monkeypatch.setattr(os, "replace", corrupt)
    with pytest.raises(ConcurrentModificationError, match="did not verify"):
        session.atomic_write(DevicePath("standalone.bin"), b"new")
    assert (root / "standalone.bin").read_bytes() == b"bad"
