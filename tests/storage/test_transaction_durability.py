"""Unconfirmed durability permits publication but never unchecked recovery cleanup."""

import json
from pathlib import Path

import pytest
from tests.storage.test_recovery import _session  # pyright: ignore[reportPrivateUsage]
from tests.storage.test_transactions import (
    _assert_original,  # pyright: ignore[reportPrivateUsage]
    _plan,  # pyright: ignore[reportPrivateUsage]
)

from storage import (
    AccessMode,
    DevicePath,
    FileFingerprint,
    FilePreconditionError,
    FlushResult,
    Storage,
    TransactionDurabilityPendingError,
    TransactionState,
)
from storage.models import VolumeObservation


@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize("direct", [False, True])
def test_unavailable_volume_barrier_allows_writes_but_keeps_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restore: bool, direct: bool
) -> None:
    root, platform, session = _session(tmp_path)
    plan = _plan(root, session)

    def flush(_observation: VolumeObservation) -> FlushResult:
        return FlushResult(False, "volume access denied")

    monkeypatch.setattr(platform, "flush", flush)

    result = session.execute_transaction(plan)
    if restore:
        result = session.restore_transaction(result.recovery)

    assert not result.flush.complete
    assert result.recovery.state is (
        TransactionState.RESTORED if restore else TransactionState.COMMITTED
    )
    journal = result.recovery.journal_path
    with pytest.raises(TransactionDurabilityPendingError):
        if direct:
            session.finalize_transaction(result.recovery)
        elif restore:
            session.finalize_restored_transaction(journal)
        else:
            session.finalize_committed_transaction(journal)
    assert session.exists(journal)
    assert tuple((root / str(journal.parent)).glob("original-*.bin"))
    if restore:
        _assert_original(session)
    else:
        assert session.read(DevicePath("art.bin")) == b"new art"


@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize("changed", [None, "art.bin", "retained.bin", "old-media.bin"])
@pytest.mark.parametrize("legacy_version", [None, 1, 2])
def test_unconfirmed_or_legacy_terminal_journal_reverifies_after_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore: bool,
    changed: str | None,
    legacy_version: int | None,
) -> None:
    root, platform, session = _session(tmp_path)
    plan = _plan(root, session)
    native_flush = platform.flush

    def flush(_observation: VolumeObservation) -> FlushResult:
        return FlushResult(False, "volume barrier unavailable")

    monkeypatch.setattr(platform, "flush", flush)
    result = session.execute_transaction(plan)
    if restore:
        result = session.restore_transaction(result.recovery)
    journal = result.recovery.journal_path
    session.close()
    platform.disconnect(root)
    # Simulate persisted legacy terminal intent with no durability evidence.
    if legacy_version is not None:
        journal_file = root / str(journal)
        document = json.loads(journal_file.read_bytes())
        document["version"] = legacy_version
        document.pop("content_durability_confirmed", None)
        if legacy_version == 1:
            document.pop("recovery_material_identity", None)
            for entry in document["entries"]:
                entry.pop("before_modified_ns", None)
                entry.pop("after_modified_ns", None)
        journal_file.write_text(json.dumps(document), encoding="utf-8")
    if changed is not None:
        (root / changed).write_bytes(b"partial or unexpectedly retained content")
    platform.reconnect(root)
    monkeypatch.setattr(platform, "flush", native_flush)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        finalize = (
            reconnected.finalize_restored_transaction
            if restore
            else reconnected.finalize_committed_transaction
        )
        if changed is not None:
            with pytest.raises(FilePreconditionError, match="did not verify"):
                finalize(journal)
            assert reconnected.exists(journal)
            assert tuple((root / str(journal.parent)).glob("original-*.bin"))
        else:
            assert finalize(journal).complete
            assert not reconnected.exists(journal)
            if restore:
                _assert_original(reconnected)
            else:
                assert reconnected.read(DevicePath("art.bin")) == b"new art"


@pytest.mark.parametrize("restore", [False, True])
def test_terminal_marker_flush_warning_retains_confirmed_content_fast_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restore: bool
) -> None:
    root, platform, session = _session(tmp_path)
    plan = _plan(root, session)
    committed = session.execute_transaction(plan) if restore else None
    flush_count = 0

    def flush(_observation: VolumeObservation) -> FlushResult:
        nonlocal flush_count
        flush_count += 1
        return FlushResult(
            flush_count != (3 if restore else 4), "terminal marker pending"
        )

    monkeypatch.setattr(platform, "flush", flush)
    result = (
        session.restore_transaction(committed.recovery)
        if committed is not None
        else session.execute_transaction(plan)
    )
    assert not result.flush.complete
    journal = result.recovery.journal_path
    original = session.fingerprint

    def fingerprint(path: DevicePath) -> FileFingerprint:
        assert path == journal, "durable content must not be rehashed during cleanup"
        return original(path)

    monkeypatch.setattr(session, "fingerprint", fingerprint)
    if restore:
        assert session.finalize_restored_transaction(journal).complete
    else:
        assert session.finalize_committed_transaction(journal).complete


@pytest.mark.parametrize("direct", [False, True])
def test_unconfirmed_restoration_cannot_inherit_confirmed_commit_cleanup_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, direct: bool
) -> None:
    root, platform, session = _session(tmp_path)
    committed = session.execute_transaction(_plan(root, session))
    native_flush = platform.flush

    def flush(_observation: VolumeObservation) -> FlushResult:
        return FlushResult(False, "restoration not durable")

    monkeypatch.setattr(platform, "flush", flush)
    restored = session.restore_transaction(committed.recovery)
    assert not restored.flush.complete
    monkeypatch.setattr(platform, "flush", native_flush)
    (root / "art.bin").write_bytes(b"restored artwork did not survive")

    with pytest.raises(FilePreconditionError, match="did not verify"):
        if direct:
            session.finalize_transaction(restored.recovery)
        else:
            session.finalize_restored_transaction(restored.recovery.journal_path)

    assert session.exists(restored.recovery.journal_path)
    assert tuple(
        (root / str(restored.recovery.journal_path.parent)).glob("original-*.bin")
    )
