"""Journal status and terminal cleanup avoid rescanning media over a slow device bus."""

import hashlib
from pathlib import Path

import pytest

from storage import (
    AccessMode,
    DevicePath,
    FileContent,
    FileFingerprint,
    FilePreconditionError,
    FlushResult,
    RecoverableWriteError,
    Storage,
    StorageTransaction,
    TransactionDurabilityPendingError,
    TransactionProgress,
    TransactionState,
    TransactionWrite,
)
from storage.testing import VirtualStoragePlatform


def test_committed_journal_cleanup_does_not_hash_published_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    data = b"verified media"
    path = DevicePath("media.bin")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        result = session.execute_transaction(
            StorageTransaction(
                (
                    TransactionWrite(
                        path,
                        data,
                        FileContent(len(data), hashlib.sha256(data).hexdigest()),
                    ),
                )
            )
        )
        original = session.fingerprint

        def fingerprint(target: DevicePath) -> FileFingerprint:
            assert target != path, "status and cleanup must not reread published media"
            return original(target)

        monkeypatch.setattr(session, "fingerprint", fingerprint)
        journal = result.recovery.journal_path
        assert session.read_transaction_state(journal) is TransactionState.COMMITTED
        assert session.finalize_committed_transaction(journal).complete
        assert not session.exists(journal)
        assert session.read(path) == data


def test_nonterminal_journal_cannot_be_cleaned_as_a_committed_sync(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    data = b"staged media"

    def interrupt(progress: TransactionProgress) -> None:
        if progress.state is TransactionState.PREPARED:
            raise InterruptedError("cancel before publication")

    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        with pytest.raises(RecoverableWriteError) as failure:
            session.execute_transaction(
                StorageTransaction(
                    (
                        TransactionWrite(
                            DevicePath("media.bin"),
                            data,
                            FileContent(len(data), hashlib.sha256(data).hexdigest()),
                        ),
                    )
                ),
                progress=interrupt,
            )
        journal = DevicePath(failure.value.recovery_path)
        assert session.read_transaction_state(journal) is TransactionState.PREPARED
        with pytest.raises(FilePreconditionError, match="verified committed"):
            session.finalize_committed_transaction(journal)
        assert session.exists(journal)
        assert not session.exists(DevicePath("media.bin"))


def test_cleanup_keeps_recovery_material_until_committed_flush_is_confirmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    data = b"verified media"
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        committed = session.execute_transaction(
            StorageTransaction(
                (
                    TransactionWrite(
                        DevicePath("media.bin"),
                        data,
                        FileContent(len(data), hashlib.sha256(data).hexdigest()),
                    ),
                )
            )
        )
        journal = committed.recovery.journal_path
        monkeypatch.setattr(session, "flush", lambda: FlushResult(False, "not durable"))
        with pytest.raises(TransactionDurabilityPendingError):
            session.finalize_committed_transaction(journal)
        assert session.exists(journal)
        assert session.read(DevicePath("media.bin")) == data
