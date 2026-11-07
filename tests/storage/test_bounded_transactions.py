"""Publish large replacement batches with complete on-device recovery."""

import shutil
from dataclasses import replace
from os import PathLike
from pathlib import Path

import pytest
from tests.storage.test_recovery import _session  # pyright: ignore[reportPrivateUsage]
from tests.storage.test_transactions import (
    _assert_original,  # pyright: ignore[reportPrivateUsage]
    _content,  # pyright: ignore[reportPrivateUsage]
    _plan,  # pyright: ignore[reportPrivateUsage]
)

from storage import (
    DevicePath,
    HostPath,
    RecoverableWriteError,
    StorageCapacityError,
    StorageTransaction,
    TransactionProgress,
    TransactionState,
    TransactionWrite,
)


def test_replacement_batch_fits_with_one_stage_and_restores_every_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, session = _session(tmp_path)
    size = 256 * 1024
    before, after = b"a" * size, b"b" * size
    writes: list[TransactionWrite] = []
    for index in range(3):
        path = DevicePath(f"media-{index}.bin")
        (root / str(path)).write_bytes(before)
        writes.append(
            TransactionWrite(path, after, _content(after), session.fingerprint(path))
        )
    plan = StorageTransaction(tuple(writes), stage_one_at_a_time=True)
    unit = 4096

    def allocated() -> int:
        return sum(
            ((p.stat().st_size + unit - 1) // unit) * unit
            for p in root.rglob("*")
            if p.is_file()
        )

    baseline = allocated()
    budget = 5 * size + 64 * 1024
    usage = shutil.disk_usage(root)

    def limited_disk_usage(_path: str | PathLike[str]) -> tuple[int, int, int]:
        return usage._replace(free=budget - (allocated() - baseline))

    monkeypatch.setattr(shutil, "disk_usage", limited_disk_usage)
    with pytest.raises(StorageCapacityError):
        session.validate_transaction(replace(plan, stage_one_at_a_time=False))
    assert session.validate_transaction(plan).required_bytes <= budget
    result = session.execute_transaction(plan)
    assert all(session.read(w.path) == after for w in writes)
    assert not result.recovery.recovery_material_identity
    restored = session.restore_transaction(result.recovery)
    assert all(session.read(w.path) == before for w in writes)
    session.finalize_transaction(restored.recovery)


@pytest.mark.parametrize("after_publication", [False, True])
def test_changed_later_host_source_preserves_complete_recovery(
    tmp_path: Path, after_publication: bool
) -> None:
    root, _, session = _session(tmp_path)
    plan = _plan(root, session)
    source = tmp_path / "replacement.bin"
    source.write_bytes(b"new database")
    plan = replace(
        plan,
        writes=(*plan.writes[:-1], replace(plan.writes[-1], source=HostPath(source))),
        stage_one_at_a_time=True,
    )

    def change_source(event: TransactionProgress) -> None:
        if (
            event.state is TransactionState.PUBLISHING and event.completed == 1
            if after_publication
            else event.state is TransactionState.PREPARED
        ):
            source.write_bytes(b"bad database")

    with pytest.raises(RecoverableWriteError) as caught:
        session.execute_transaction(plan, progress=change_source)
    assert caught.value.publication_started is after_publication
    if not after_publication:
        _assert_original(session)
    recovery = session.inspect_transaction(DevicePath(caught.value.recovery_path))
    session.restore_transaction(recovery)
    _assert_original(session)
