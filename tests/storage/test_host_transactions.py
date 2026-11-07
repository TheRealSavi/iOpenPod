"""Low-space publication retains durable recovery on the Host."""

import shutil
from os import PathLike
from pathlib import Path

import pytest
from tests.storage.test_transactions import (
    _content,  # pyright: ignore[reportPrivateUsage]
)

from storage import (
    AccessMode,
    DevicePath,
    FilesystemSession,
    RecoverableWriteError,
    Storage,
    StorageTransaction,
    TransactionProgress,
    TransactionRemoval,
    TransactionState,
    TransactionWrite,
)
from storage.testing import VirtualStoragePlatform


@pytest.mark.parametrize("include_writes", [False, True])
def test_publication_progress_counts_removals_and_writes_in_execution_order(
    tmp_path: Path,
    include_writes: bool,
) -> None:
    root = tmp_path / "volume"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform, transaction_recovery_directory=tmp_path / "recovery")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        removed = (DevicePath("one.bin"), DevicePath("two.bin"))
        for path in removed:
            (root / str(path)).write_bytes(b"old")
        writes = (
            (TransactionWrite(DevicePath("new.bin"), b"new", _content(b"new")),)
            if include_writes
            else ()
        )
        plan = StorageTransaction(
            writes,
            tuple(
                TransactionRemoval(path, session.fingerprint(path)) for path in removed
            ),
            host_recovery=True,
        )
        events: list[TransactionProgress] = []
        result = session.execute_transaction(plan, progress=events.append)
        publishing = [
            event for event in events if event.state is TransactionState.PUBLISHING
        ]
        total = 2 + int(include_writes)
        assert [event.completed for event in publishing] == list(range(total + 1))
        assert all(event.total == total for event in publishing)
        assert [event.path for event in publishing[1:]] == [
            *removed,
            *(write.path for write in writes),
        ]
        assert session.finalize_committed_transaction(
            result.recovery.journal_path
        ).complete


@pytest.mark.parametrize("interrupt", [False, True])
@pytest.mark.parametrize("exact_capacity", [False, True])
def test_nearly_full_replacement_and_removal_survive_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: bool,
    exact_capacity: bool,
) -> None:
    root = tmp_path / "volume"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    recovery = tmp_path / "recovery"

    def open_session() -> FilesystemSession:
        storage = Storage(
            platform,
            writer_lock_directory=tmp_path / "locks",
            transaction_recovery_directory=recovery,
        )
        return storage.open_session(
            storage.discover().volumes[0], access=AccessMode.READ_WRITE
        )

    session = open_session()
    size = 1024 * 1024
    old = b"a" * size
    new = b"b" * size
    for name in ("retag.bin", "remove.bin"):
        (root / name).write_bytes(old)
    plan = StorageTransaction(
        (
            TransactionWrite(
                DevicePath("retag.bin"),
                new,
                _content(new),
                session.fingerprint(DevicePath("retag.bin")),
            ),
            TransactionWrite(DevicePath("added.bin"), new, _content(new)),
        ),
        (
            TransactionRemoval(
                DevicePath("remove.bin"), session.fingerprint(DevicePath("remove.bin"))
            ),
        ),
        host_recovery=True,
    )
    unit = 4096

    def allocated() -> int:
        return sum(
            ((p.stat().st_size + unit - 1) // unit) * unit
            for p in root.rglob("*")
            if p.is_file()
        )

    baseline = allocated()
    real_usage = shutil.disk_usage
    budget = (
        session.validate_transaction(plan).required_bytes
        if exact_capacity
        else 128 * 1024
    )

    def usage(path: str | PathLike[str]) -> tuple[int, int, int]:
        actual = real_usage(path)
        if Path(path).resolve() == root:
            return actual._replace(free=budget - (allocated() - baseline))
        return actual

    monkeypatch.setattr(shutil, "disk_usage", usage)
    assert session.validate_transaction(plan).required_bytes <= budget

    def fail(event: TransactionProgress) -> None:
        if (
            interrupt
            and event.state is TransactionState.PUBLISHING
            and event.completed == 1
        ):
            raise OSError("simulated process exit")

    if interrupt:
        with pytest.raises(RecoverableWriteError) as caught:
            session.execute_transaction(plan, progress=fail)
        path = DevicePath(caught.value.recovery_path)
    else:
        result = session.execute_transaction(plan)
        path = result.recovery.journal_path
        assert session.read(DevicePath("retag.bin")) == new
        assert session.read(DevicePath("added.bin")) == new
        assert not session.exists(DevicePath("remove.bin"))
    session.close()
    session = open_session()
    observed = session.inspect_transaction(path)
    restored = session.restore_transaction(observed)
    assert session.read(DevicePath("retag.bin")) == old
    assert session.read(DevicePath("remove.bin")) == old
    assert not session.exists(DevicePath("added.bin"))
    session.finalize_transaction(restored.recovery)
    assert not session.host_transaction_journals()
