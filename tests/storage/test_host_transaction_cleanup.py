"""Terminal Host recovery cleanup spends device reads only on unconfirmed results."""

from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from tests.storage.test_host_transaction_recovery import (
    _small_plan,  # pyright: ignore[reportPrivateUsage]
)

from storage import (
    AccessMode,
    DevicePath,
    FileFingerprint,
    FilePrecondition,
    FilePreconditionError,
    FlushResult,
    TransactionDurabilityPendingError,
)
from storage import session as session_module
from storage._filesystem import read_and_fingerprint
from storage.models import VolumeObservation


def _record_content_reads(monkeypatch: pytest.MonkeyPatch, root: Path) -> list[str]:
    reads: list[str] = []

    def read(
        path: Path,
        *,
        collect_data: bool,
        max_bytes: int | None,
        assert_active: Callable[[], None],
    ) -> tuple[bytes, FileFingerprint]:
        if path.parent == root:
            reads.append(path.name)
        return read_and_fingerprint(
            path,
            collect_data=collect_data,
            max_bytes=max_bytes,
            assert_active=assert_active,
        )

    monkeypatch.setattr(session_module, "read_and_fingerprint", read)
    return reads


def _unavailable_flush(_observation: VolumeObservation) -> FlushResult:
    return FlushResult(False, "volume barrier unavailable")


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("restoring", [False, True])
@pytest.mark.parametrize("direct", [False, True])
def test_cleanup_read_budget_after_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    confirmed: bool,
    restoring: bool,
    direct: bool,
) -> None:
    root, platform, storage, session, plan = _small_plan(tmp_path)
    (root / "dependency").write_bytes(b"retained")
    plan = replace(
        plan,
        dependencies=(
            FilePrecondition(
                DevicePath("dependency"), session.fingerprint(DevicePath("dependency"))
            ),
        ),
    )
    with monkeypatch.context() as publication:
        if not confirmed:
            publication.setattr(platform, "flush", _unavailable_flush)
        result = session.execute_transaction(plan)
        if restoring:
            result = session.restore_transaction(result.recovery)
    session.close()
    platform.disconnect(root)
    platform.reconnect(root)
    expected = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    reads = _record_content_reads(monkeypatch, root)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        if direct:
            flushed = reconnected.finalize_transaction(result.recovery)
        elif restoring:
            flushed = reconnected.finalize_restored_transaction(
                result.recovery.journal_path
            )
        else:
            flushed = reconnected.finalize_committed_transaction(
                result.recovery.journal_path
            )
        assert flushed.complete
        assert not reconnected.has_transaction(result.recovery.journal_path)
        assert not reconnected.host_transaction_journals()
    assert Counter(reads) == (Counter() if confirmed else Counter(expected.keys()))
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == expected
    assert not tuple((tmp_path / "recovery").rglob("original-*.bin"))


@pytest.mark.parametrize("restoring", [False, True])
@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("changed", ["replace.bin", "dependency", "absent"])
def test_unconfirmed_cleanup_keeps_originals_if_result_did_not_survive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restoring: bool,
    direct: bool,
    changed: str,
) -> None:
    root, platform, storage, session, plan = _small_plan(tmp_path)
    (root / "dependency").write_bytes(b"retained")
    plan = replace(
        plan,
        dependencies=(
            FilePrecondition(
                DevicePath("dependency"), session.fingerprint(DevicePath("dependency"))
            ),
        ),
    )
    with monkeypatch.context() as publication:
        publication.setattr(platform, "flush", _unavailable_flush)
        result = session.execute_transaction(plan)
        if restoring:
            result = session.restore_transaction(result.recovery)
    session.close()
    platform.disconnect(root)
    if changed == "absent":
        changed = "added.bin" if restoring else "remove.bin"
    (root / changed).write_bytes(b"unexpected content after reconnect")
    platform.reconnect(root)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        with pytest.raises(FilePreconditionError, match="did not verify"):
            if direct:
                reconnected.finalize_transaction(result.recovery)
            elif restoring:
                reconnected.finalize_restored_transaction(result.recovery.journal_path)
            else:
                reconnected.finalize_committed_transaction(result.recovery.journal_path)
        assert reconnected.has_transaction(result.recovery.journal_path)
    assert (root / changed).read_bytes() == b"unexpected content after reconnect"
    assert (
        next((tmp_path / "recovery").rglob("original-0.bin")).read_bytes()
        == b"original"
    )


@pytest.mark.parametrize("confirmed", [False, True])
def test_failed_cleanup_barrier_keeps_originals_without_reading_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, confirmed: bool
) -> None:
    root, platform, _, session, plan = _small_plan(tmp_path)
    with monkeypatch.context() as publication:
        if not confirmed:
            publication.setattr(platform, "flush", _unavailable_flush)
        result = session.execute_transaction(plan)
    reads = _record_content_reads(monkeypatch, root)
    monkeypatch.setattr(platform, "flush", _unavailable_flush)
    with pytest.raises(TransactionDurabilityPendingError):
        session.finalize_committed_transaction(result.recovery.journal_path)
    assert not reads
    assert session.has_transaction(result.recovery.journal_path)
    assert (
        next((tmp_path / "recovery").rglob("original-0.bin")).read_bytes()
        == b"original"
    )


def test_cleanup_rejects_stale_host_journal_observation(tmp_path: Path) -> None:
    _, _, _, session, plan = _small_plan(tmp_path)
    result = session.execute_transaction(plan)
    journal = next((tmp_path / "recovery").rglob("transaction.json"))
    journal.write_bytes(journal.read_bytes() + b"\n")
    with pytest.raises(FilePreconditionError, match="changed since inspection"):
        session.finalize_transaction(result.recovery)
    assert session.has_transaction(result.recovery.journal_path)
    assert (
        next((tmp_path / "recovery").rglob("original-0.bin")).read_bytes()
        == b"original"
    )


@pytest.mark.parametrize("failed_barrier", [1, 2])
def test_cleanup_flush_failure_can_retry_from_host_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_barrier: int
) -> None:
    root, platform, _, session, plan = _small_plan(tmp_path)
    result = session.execute_transaction(plan)
    journal = result.recovery.journal_path
    native_flush = platform.flush
    calls = 0

    def flush(observation: VolumeObservation) -> FlushResult:
        nonlocal calls
        calls += 1
        if calls == failed_barrier:
            return FlushResult(False, "cleanup barrier unavailable")
        return native_flush(observation)

    reads = _record_content_reads(monkeypatch, root)
    with monkeypatch.context() as cleanup:
        cleanup.setattr(platform, "flush", flush)
        with pytest.raises(TransactionDurabilityPendingError):
            session.finalize_committed_transaction(journal)
    assert calls == failed_barrier
    assert session.host_transaction_journals() == (journal,)
    assert session.exists(journal) is (failed_barrier == 1)
    assert (
        next((tmp_path / "recovery").rglob("original-0.bin")).read_bytes()
        == b"original"
    )
    assert session.finalize_committed_transaction(journal).complete
    assert not reads
    assert not session.host_transaction_journals()
    assert not tuple((tmp_path / "recovery").rglob("original-*.bin"))
