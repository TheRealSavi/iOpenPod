from pathlib import Path

import pytest

from iopenpod.device.write_guard import DeviceWriteSafetyError
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync.contracts import SyncPlan
from iopenpod.sync.integrity import IntegrityReport
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.sync_executor import SyncExecutor, _SyncContext


def _context(plan: SyncPlan) -> _SyncContext:
    return _SyncContext(
        plan=plan,
        mapping=plan.mapping or MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )


def _orphan(ipod_root: Path, name: str = "ORPHAN.mp3") -> Path:
    path = ipod_root / "iPod_Control" / "Music" / "F00" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"orphan")
    return path


def test_execution_durably_removes_planned_orphan_after_revalidation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    orphan = _orphan(tmp_path)
    plan = SyncPlan(integrity_report=IntegrityReport(orphan_files=[orphan]))
    ctx = _context(plan)
    executor = SyncExecutor(tmp_path)
    checks: list[bool] = []
    monkeypatch.setattr(
        executor,
        "_revalidate_device_write_readiness",
        lambda: checks.append(orphan.exists()),
    )

    executor._execute_integrity_housekeeping(ctx)

    assert checks == [True]
    assert not orphan.exists()
    assert ctx.integrity_orphans_removed == 1
    assert ctx.result.success is True


def test_execution_refuses_planned_orphan_outside_ipod(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-host-library-song.mp3"
    outside.write_bytes(b"host audio")
    plan = SyncPlan(integrity_report=IntegrityReport(orphan_files=[outside]))
    ctx = _context(plan)

    with pytest.raises(DeviceWriteSafetyError, match="outside the selected iPod"):
        SyncExecutor(tmp_path)._execute_integrity_housekeeping(ctx)

    assert outside.read_bytes() == b"host audio"


def test_execution_skips_orphan_that_current_database_references(
    tmp_path: Path,
) -> None:
    orphan = _orphan(tmp_path)
    plan = SyncPlan(integrity_report=IntegrityReport(orphan_files=[orphan]))
    ctx = _context(plan)
    ctx.tracks_by_db_track_id[7] = TrackInfo(
        db_track_id=7,
        location=":iPod_Control:Music:F00:ORPHAN.mp3",
        title="Orphan",
    )

    SyncExecutor(tmp_path)._execute_integrity_housekeeping(ctx)

    assert orphan.is_file()
    assert ctx.integrity_orphans_removed == 0


def test_mapping_only_housekeeping_saves_under_execution_without_database_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mapping = MappingFile()
    plan = SyncPlan(
        mapping=mapping,
        _mapping_requires_persistence=True,
    )
    ctx = _context(plan)
    executor = SyncExecutor(tmp_path)
    saves: list[MappingFile] = []
    monkeypatch.setattr(executor, "_revalidate_device_write_readiness", lambda: None)
    monkeypatch.setattr(
        executor.mapping_manager,
        "save",
        lambda value: (saves.append(value) or True),
    )
    monkeypatch.setattr(
        executor,
        "_execute_write_and_finalize",
        lambda _ctx: pytest.fail("mapping-only maintenance rewrote iTunesDB"),
    )

    executor._commit_file_mutations(ctx, on_cancel_with_partial=None)

    assert saves == [mapping]
    assert ctx.database_committed is False
    assert ctx.device_changes_committed is True


def test_mapping_only_housekeeping_stops_and_alerts_when_save_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = SyncPlan(
        mapping=MappingFile(),
        _mapping_requires_persistence=True,
    )
    ctx = _context(plan)
    executor = SyncExecutor(tmp_path)
    monkeypatch.setattr(executor, "_revalidate_device_write_readiness", lambda: None)
    monkeypatch.setattr(executor.mapping_manager, "save", lambda _value: False)

    executor._commit_file_mutations(ctx, on_cancel_with_partial=None)

    assert ctx.result.success is False
    assert ctx.result.errors[0][0] == "mapping"
    assert ctx.device_changes_committed is False
