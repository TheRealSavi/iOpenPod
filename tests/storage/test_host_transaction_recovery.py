"""Host recovery remains usable across all device mutation boundaries."""

import os
import shutil
from dataclasses import replace
from os import PathLike
from pathlib import Path

import pytest
from tests.storage.test_transactions import (
    _content,  # pyright: ignore[reportPrivateUsage]
)

from storage import (
    AccessMode,
    ConcurrentModificationError,
    DevicePath,
    FilePrecondition,
    FilePreconditionError,
    FilesystemSession,
    FlushResult,
    HostPathOnPhysicalDeviceError,
    RecoverableWriteError,
    Storage,
    StorageCapacityError,
    StorageTransaction,
    TransactionDurabilityPendingError,
    TransactionProgress,
    TransactionRemoval,
    TransactionState,
    TransactionWrite,
)
from storage.testing import VirtualStoragePlatform


def _small_plan(
    tmp_path: Path,
) -> tuple[
    Path, VirtualStoragePlatform, Storage, FilesystemSession, StorageTransaction
]:
    root = tmp_path / "volume"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(
        platform,
        writer_lock_directory=tmp_path / "locks",
        transaction_recovery_directory=tmp_path / "recovery",
    )
    session = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    )
    for name in ("replace.bin", "remove.bin"):
        (root / name).write_bytes(b"original")
    plan = StorageTransaction(
        (
            TransactionWrite(
                DevicePath("replace.bin"),
                b"new",
                _content(b"new"),
                session.fingerprint(DevicePath("replace.bin")),
            ),
            TransactionWrite(DevicePath("added.bin"), b"added", _content(b"added")),
        ),
        (
            TransactionRemoval(
                DevicePath("remove.bin"), session.fingerprint(DevicePath("remove.bin"))
            ),
        ),
        host_recovery=True,
    )
    return root, platform, storage, session, plan


@pytest.mark.parametrize(
    "restoring,boundary",
    [(False, i) for i in range(1, 9)] + [(True, i) for i in range(1, 7)],
)
def test_disconnect_at_every_device_publication_or_restoration_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restoring: bool, boundary: int
) -> None:
    root, platform, storage, session, plan = _small_plan(tmp_path)
    result = session.execute_transaction(plan) if restoring else None
    native_replace = os.replace
    native_unlink = Path.unlink
    count = 0

    def boundary_after(path: Path) -> None:
        nonlocal count
        if path.is_relative_to(root):
            count += 1
            if count == boundary:
                platform.disconnect(root)

    def move(source: str | PathLike[str], target: str | PathLike[str]) -> None:
        native_replace(source, target)
        boundary_after(Path(target))

    def delete(path: Path, *, missing_ok: bool = False) -> None:
        existed = path.exists()
        native_unlink(path, missing_ok=missing_ok)
        if existed:
            boundary_after(path)

    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", move)
        fault.setattr(Path, "unlink", delete)
        with pytest.raises(RecoverableWriteError) as caught:
            if result is not None:
                session.restore_transaction(result.recovery)
            else:
                session.execute_transaction(plan)
    assert count == boundary
    platform.reconnect(root)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        path = DevicePath(caught.value.recovery_path)
        restored = reconnected.restore_transaction(
            reconnected.inspect_transaction(path)
        )
        assert (root / "replace.bin").read_bytes() == b"original"
        assert (root / "remove.bin").read_bytes() == b"original"
        assert not (root / "added.bin").exists()
        reconnected.finalize_transaction(restored.recovery)


@pytest.mark.parametrize("terminal", [False, True])
def test_lost_device_journal_is_discovered_from_host_after_restart(
    tmp_path: Path, terminal: bool
) -> None:
    root, _, storage, session, plan = _small_plan(tmp_path)

    def fail(event: TransactionProgress) -> None:
        if (
            not terminal
            and event.state is TransactionState.PUBLISHING
            and event.completed == 1
        ):
            raise OSError("interrupted")

    if terminal:
        path = session.execute_transaction(plan).recovery.journal_path
    else:
        with pytest.raises(RecoverableWriteError) as caught:
            session.execute_transaction(plan, progress=fail)
        path = DevicePath(caught.value.recovery_path)
    (root / str(path)).unlink()
    session.close()
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as reconnected:
        assert reconnected.host_transaction_journals() == (path,)
        restored = reconnected.restore_transaction(
            reconnected.inspect_transaction(path)
        )
        reconnected.finalize_transaction(restored.recovery)
    assert (root / "replace.bin").read_bytes() == b"original"


@pytest.mark.parametrize("corrupt", ["original", "target", "dependency"])
def test_corruption_blocks_recovery_before_mutating_any_file(
    tmp_path: Path, corrupt: str
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)
    (root / "dependency").write_bytes(b"retained")
    plan = replace(
        plan,
        dependencies=(
            FilePrecondition(
                DevicePath("dependency"), session.fingerprint(DevicePath("dependency"))
            ),
        ),
    )
    result = session.execute_transaction(plan)
    if corrupt == "original":
        next((tmp_path / "recovery").rglob("original-0.bin")).write_bytes(b"corrupt")
    elif corrupt == "target":
        (root / "replace.bin").write_bytes(b"unrelated edit")
    else:
        (root / "dependency").write_bytes(b"unrelated edit")
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    with pytest.raises((FilePreconditionError, ConcurrentModificationError)):
        session.restore_transaction(
            session.inspect_transaction(result.recovery.journal_path)
        )
    assert {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    } == before


def test_net_growth_that_does_not_fit_is_rejected_without_device_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)
    payload = b"x" * (1024 * 1024)
    plan = replace(
        plan,
        writes=(
            replace(plan.writes[0], source=payload, content=_content(payload)),
            *plan.writes[1:],
        ),
    )
    usage = shutil.disk_usage(root)

    def limited_disk_usage(_path: str | PathLike[str]) -> tuple[int, int, int]:
        return usage._replace(free=128 * 1024)

    monkeypatch.setattr(shutil, "disk_usage", limited_disk_usage)
    with pytest.raises(StorageCapacityError):
        session.execute_transaction(plan)
    assert (root / "replace.bin").read_bytes() == b"original"
    assert not session.host_transaction_journals()


def test_recovery_store_cannot_be_on_the_selected_device(tmp_path: Path) -> None:
    root, platform, _, session, plan = _small_plan(tmp_path)
    session.close()
    storage = Storage(platform, transaction_recovery_directory=root / "recovery")
    with (
        storage.open_session(
            storage.discover().volumes[0], access=AccessMode.READ_WRITE
        ) as selected,
        pytest.raises(HostPathOnPhysicalDeviceError),
    ):
        selected.execute_transaction(plan)
    assert (root / "replace.bin").read_bytes() == b"original"


def test_unconfirmed_flush_retains_host_originals_until_verified_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _, session, plan = _small_plan(tmp_path)

    def unavailable_flush(_session: FilesystemSession) -> FlushResult:
        return FlushResult(False, "unavailable")

    with monkeypatch.context() as fault:
        fault.setattr(FilesystemSession, "flush", unavailable_flush)
        result = session.execute_transaction(plan)
        assert not result.flush.complete
        with pytest.raises(TransactionDurabilityPendingError):
            session.finalize_transaction(result.recovery)
        assert tuple((tmp_path / "recovery").rglob("original-0.bin"))
    session.finalize_committed_transaction(result.recovery.journal_path)
    assert not session.host_transaction_journals()


@pytest.mark.parametrize("missing_device_journal", [False, True])
def test_declining_recovery_retires_both_journals_and_keeps_originals(
    tmp_path: Path, missing_device_journal: bool
) -> None:
    root, _, _, session, plan = _small_plan(tmp_path)
    result = session.execute_transaction(plan)
    path = result.recovery.journal_path
    if missing_device_journal:
        (root / str(path)).unlink()
    session.decline_transaction(
        path, expected=session.transaction_journal_fingerprint(path)
    )
    assert not session.has_transaction(path)
    assert not session.host_transaction_journals()
    assert (root / "replace.bin").read_bytes() == b"new"
    assert (
        next((tmp_path / "recovery").rglob("original-0.bin")).read_bytes()
        == b"original"
    )
    assert tuple((tmp_path / "recovery").rglob("declined-transaction.json"))
