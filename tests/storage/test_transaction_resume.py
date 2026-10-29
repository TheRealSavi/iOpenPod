"""Resume interrupted create-only staging without recopying verified files."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from tests.storage.test_recovery import _session  # pyright: ignore[reportPrivateUsage]

from storage import (
    AccessMode,
    DevicePath,
    FileContent,
    FilePreconditionError,
    HostPath,
    RecoverableWriteError,
    Storage,
    StorageTransaction,
    TransactionProgress,
    TransactionState,
    TransactionWrite,
)


@pytest.mark.parametrize("damaged", [False, True])
def test_resume_reuses_valid_stage_and_only_recopies_damaged_stage(
    tmp_path: Path,
    damaged: bool,
) -> None:
    root, platform, session = _session(tmp_path)
    sources = [tmp_path / "one.bin", tmp_path / "two.bin"]
    payloads = [b"one", b"two"]
    for source, data in zip(sources, payloads, strict=True):
        source.write_bytes(data)
    plan = StorageTransaction(
        tuple(
            TransactionWrite(
                DevicePath(f"games/{index}.bin"),
                HostPath(source),
                FileContent(len(data), hashlib.sha256(data).hexdigest()),
            )
            for index, (source, data) in enumerate(zip(sources, payloads, strict=True))
        )
    )

    def interrupt(event: TransactionProgress) -> None:
        if event.state is TransactionState.STAGING and event.completed == 1:
            raise InterruptedError("disconnect during staging")

    with pytest.raises(RecoverableWriteError) as caught:
        session.execute_transaction(plan, progress=interrupt)
    journal = DevicePath(caught.value.recovery_path)
    assert journal.parent is not None
    stage = journal.parent.joinpath("staged-0.bin")
    if damaged:
        (root / str(stage)).write_bytes(b"incomplete")
    else:
        # A successful resume proves the first Host source is never reopened.
        sources[0].unlink()
    session.close()
    portal = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with portal.open_session(
        portal.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        wrong = replace(plan, writes=tuple(reversed(plan.writes)))
        with pytest.raises(FilePreconditionError, match="exact original"):
            reconnected.resume_transaction(wrong, journal)
        result = reconnected.resume_transaction(plan, journal)
        assert result.recovery.state is TransactionState.COMMITTED
        assert reconnected.read(DevicePath("games/0.bin")) == b"one"
        assert reconnected.read(DevicePath("games/1.bin")) == b"two"
        assert reconnected.finalize_committed_transaction(journal).complete
