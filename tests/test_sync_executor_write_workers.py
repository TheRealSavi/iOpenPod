from __future__ import annotations

import errno
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from iopenpod.device.filesystem_profile import FilesystemProfile
from iopenpod.device.write_guard import DatabaseGeneration, DeviceWriteSafetyError
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync.contracts import (
    SYNC_DB_OVERHEAD_BYTES,
    SYNC_DB_WRITE_RESERVE_BYTES,
    StorageSummary,
    SyncAction,
    SyncItem,
    SyncPlan,
    SyncRequest,
    sync_plan_required_free_bytes,
)
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.pc_library import PCTrack
from iopenpod.sync.sync_executor import SyncExecutor, _ExecutionLifecycle, _SyncContext
from iopenpod.sync.sync_playlist_files import normalize_sync_playlist_path, sync_playlist_file_id
from iopenpod.sync.transcoder import TranscodeResult, TranscodeTarget, resolve_transcode_plan


def _make_sync_ctx(
    playlist_updates: list[dict],
    existing_dataset2_standard_playlists_raw: list[dict],
    existing_dataset5_smart_playlists_raw: list[dict],
    existing_dataset3_podcast_playlists_raw: list[dict] | None = None,
) -> _SyncContext:
    ctx = _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=True,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.plan.playlists_to_add = list(playlist_updates)
    ctx.existing_dataset2_standard_playlists_raw = (
        existing_dataset2_standard_playlists_raw
    )
    ctx.existing_dataset3_podcast_playlists_raw = (
        existing_dataset3_podcast_playlists_raw or []
    )
    ctx.existing_dataset5_smart_playlists_raw = existing_dataset5_smart_playlists_raw
    return ctx


def _make_pc_track(source: Path) -> PCTrack:
    return PCTrack(
        path=str(source),
        relative_path=source.name,
        filename=source.name,
        extension=source.suffix.lower(),
        mtime=0.0,
        size=source.stat().st_size,
        title=source.stem,
        artist="Unknown Artist",
        album="Unknown Album",
        album_artist=None,
        genre=None,
        year=None,
        track_number=None,
        track_total=None,
        disc_number=None,
        disc_total=None,
        duration_ms=1000,
        bitrate=None,
        sample_rate=None,
        rating=None,
    )


def test_auto_write_workers_use_hdd_safe_default_for_classic(tmp_path: Path) -> None:
    executor = SyncExecutor(
        tmp_path,
        max_workers=6,
        max_device_write_workers=0,
        device_info=SimpleNamespace(model_family="iPod Classic", generation="6th Gen"),
    )

    assert executor._max_workers == 6
    assert executor._max_device_write_workers == 1


def test_commit_file_mutations_writes_normal_database(monkeypatch, tmp_path: Path) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    writes: list[str] = []

    monkeypatch.setattr(
        executor,
        "_execute_write_and_finalize",
        lambda _ctx: writes.append("write"),
    )

    executor._commit_file_mutations(ctx, on_cancel_with_partial=None)

    assert writes == ["write"]
    assert not ctx.result.partial_save


def test_execution_lifecycle_runs_named_phases_in_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    lifecycle = _ExecutionLifecycle(on_cancel_with_partial=lambda _a, _b: True)
    order: list[str] = []

    def fake_prepare(_ctx) -> bool:
        order.append("prepare")
        return True

    def fake_preflight(_ctx) -> bool:
        order.append("preflight")
        return True

    monkeypatch.setattr(executor, "_prepare_execution_plan", fake_prepare)
    monkeypatch.setattr(executor, "_run_preflight_phase", fake_preflight)
    monkeypatch.setattr(
        executor,
        "_run_file_mutation_phase",
        lambda _ctx: order.append("mutate"),
    )

    def fake_commit(_ctx, commit_lifecycle):
        assert commit_lifecycle is lifecycle
        order.append("commit")

    monkeypatch.setattr(executor, "_run_database_commit_phase", fake_commit)
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.flush_filesystem",
        lambda _mount_path: (True, "flushed"),
    )

    executor._run_execution_lifecycle(ctx, lifecycle)

    assert order == ["prepare", "preflight", "mutate", "commit"]
    assert ctx.result.success


def test_full_sync_holds_one_writer_guard_for_the_execution_lifecycle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    expected_generation = DatabaseGeneration("iTunesDB", True, digest="loaded")
    guard_arguments: dict[str, object] = {}

    class FakeGuard:
        def __init__(self, ipod_path, **kwargs) -> None:
            assert Path(ipod_path) == tmp_path
            guard_arguments.update(kwargs)

        def __enter__(self):
            events.append("guard-enter")
            return self

        def __exit__(self, *_args) -> None:
            events.append("guard-exit")

    executor = SyncExecutor(
        tmp_path,
        expected_database_generation=expected_generation,
    )
    profile = SimpleNamespace()
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.inspect_device_write_readiness",
        lambda *_args, **_kwargs: profile,
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.volume_lock_key",
        lambda _profile: "test-volume",
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.revalidate_device_write_readiness",
        lambda retained, **_kwargs: retained,
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.DeviceWriteGuard",
        FakeGuard,
        raising=False,
    )

    def fake_lifecycle(ctx, _lifecycle) -> None:
        assert isinstance(ctx.write_guard, FakeGuard)
        events.append("lifecycle")

    monkeypatch.setattr(executor, "_run_execution_lifecycle", fake_lifecycle)

    executor.execute_request(
        SyncRequest(
            plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
            mapping=MappingFile(),
        )
    )

    assert events == ["guard-enter", "lifecycle", "guard-exit"]
    assert guard_arguments["expected_database_generation"] == expected_generation


def test_full_sync_reports_filesystem_safety_failure_before_lifecycle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    lifecycle_calls: list[bool] = []
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.inspect_device_write_readiness",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DeviceWriteSafetyError("mounted read-only")
        ),
    )
    monkeypatch.setattr(
        executor,
        "_run_execution_lifecycle",
        lambda *_args: lifecycle_calls.append(True),
    )

    result = executor.execute_request(
        SyncRequest(
            plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
            mapping=MappingFile(),
        )
    )

    assert result.success is False
    assert result.errors == [("filesystem_safety", "mounted read-only")]
    assert lifecycle_calls == []


def test_full_sync_rejects_volume_changed_since_worker_was_created(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(
        tmp_path,
        device_storage=SimpleNamespace(
            reported_volume_format="FAT32",
            volume_identity_key="original-volume",
        ),
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.inspect_device_write_readiness",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.volume_lock_key",
        lambda _profile: "replacement-volume",
    )

    result = executor.execute_request(
        SyncRequest(
            plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
            mapping=MappingFile(),
        )
    )

    assert result.success is False
    assert result.errors[0][0] == "filesystem_safety"
    assert "different volume" in result.errors[0][1]


def test_execution_lifecycle_rejects_success_when_device_flush_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    lifecycle = _ExecutionLifecycle(on_cancel_with_partial=None)

    monkeypatch.setattr(executor, "_prepare_execution_plan", lambda _ctx: True)
    monkeypatch.setattr(executor, "_run_preflight_phase", lambda _ctx: True)
    monkeypatch.setattr(executor, "_run_file_mutation_phase", lambda _ctx: None)
    monkeypatch.setattr(executor, "_run_database_commit_phase", lambda *_args: None)
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.flush_filesystem",
        lambda _mount_path: (False, "filesystem flush timed out"),
    )

    executor._run_execution_lifecycle(ctx, lifecycle)

    assert ctx.result.success is False
    assert ctx.result.errors == [
        ("filesystem_flush", "filesystem flush timed out")
    ]


def test_execution_lifecycle_does_not_flush_a_stale_mount_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    executor._filesystem_profile = cast(FilesystemProfile, SimpleNamespace())
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    flushes: list[Path] = []
    monkeypatch.setattr(executor, "_prepare_execution_plan", lambda _ctx: True)
    monkeypatch.setattr(executor, "_run_preflight_phase", lambda _ctx: True)
    monkeypatch.setattr(executor, "_run_file_mutation_phase", lambda _ctx: None)
    monkeypatch.setattr(executor, "_run_database_commit_phase", lambda *_args: None)
    monkeypatch.setattr(
        executor,
        "_revalidate_device_write_readiness",
        lambda: (_ for _ in ()).throw(DeviceWriteSafetyError("volume changed")),
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.flush_filesystem",
        lambda path: (flushes.append(Path(path)) or True, "flushed"),
    )

    executor._run_execution_lifecycle(
        ctx,
        _ExecutionLifecycle(on_cancel_with_partial=None),
    )

    assert flushes == []
    assert ctx.result.success is False
    assert ctx.result.errors[0][0] == "filesystem_flush"
    assert "skipped" in ctx.result.errors[0][1]


def test_execution_lifecycle_flushes_after_a_file_stage_safety_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    flushes: list[Path] = []
    monkeypatch.setattr(executor, "_prepare_execution_plan", lambda _ctx: True)
    monkeypatch.setattr(executor, "_run_preflight_phase", lambda _ctx: True)
    monkeypatch.setattr(
        executor,
        "_run_file_mutation_phase",
        lambda _ctx: (_ for _ in ()).throw(
            DeviceWriteSafetyError("volume changed")
        ),
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.flush_filesystem",
        lambda path: (flushes.append(Path(path)) or True, "flushed"),
    )

    with pytest.raises(DeviceWriteSafetyError, match="volume changed"):
        executor._run_execution_lifecycle(
            ctx,
            _ExecutionLifecycle(on_cancel_with_partial=None),
        )

    assert flushes == [tmp_path]


def test_sync_complete_callback_runs_only_after_committed_writes_are_flushed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    order: list[str] = []
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
        on_sync_complete=lambda: order.append("complete"),
    )
    lifecycle = _ExecutionLifecycle(on_cancel_with_partial=None)

    monkeypatch.setattr(executor, "_prepare_execution_plan", lambda _ctx: True)
    monkeypatch.setattr(executor, "_run_preflight_phase", lambda _ctx: True)
    monkeypatch.setattr(executor, "_run_file_mutation_phase", lambda _ctx: None)

    def fake_commit(commit_ctx, _lifecycle) -> None:
        commit_ctx.database_committed = True

    monkeypatch.setattr(executor, "_run_database_commit_phase", fake_commit)
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.flush_filesystem",
        lambda _mount_path: (order.append("flush") or True, "flushed"),
    )

    executor._run_execution_lifecycle(ctx, lifecycle)

    assert order == ["flush", "complete"]


def test_prepare_execution_plan_rejects_structurally_invalid_plan(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )

    assert not executor._prepare_execution_plan(ctx)
    assert not ctx.result.success
    assert ctx.result.errors[0][0] == "add_missing_source"


def test_prepare_execution_plan_keeps_plan_playlist_only_changes(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(
            playlists_to_add=[
                {
                    "playlist_id": 42,
                    "Title": "Manual",
                    "_isNew": True,
                    "items": [{"db_track_id": 101}],
                }
            ]
        ),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )

    assert executor._prepare_execution_plan(ctx)
    assert ctx.result.success


def test_sync_plan_required_free_bytes_excludes_deferred_removal_credit() -> None:
    add = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        estimated_size=100,
    )
    immediate_remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        ipod_track={"size": 30},
    )
    deferred_remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        ipod_track={"size": 80},
        defer_removal_until_after_add=True,
    )
    file_update = SyncItem(
        action=SyncAction.UPDATE_FILE,
        estimated_size=90,
        ipod_track={"size": 50},
    )
    plan = SyncPlan(
        to_add=[add],
        to_remove=[immediate_remove, deferred_remove],
        to_update_file=[file_update],
        storage=StorageSummary(
            bytes_to_add=100,
            bytes_to_remove=110,
            bytes_to_update=90,
        ),
    )

    assert sync_plan_required_free_bytes(plan) == (
        SYNC_DB_OVERHEAD_BYTES
        + 100
        - 30
        + 40
    )


def test_sync_plan_required_free_bytes_rounds_each_new_file_to_cluster_size() -> None:
    plan = SyncPlan(
        to_add=[
            SyncItem(action=SyncAction.ADD_TO_IPOD, estimated_size=1),
            SyncItem(action=SyncAction.ADD_TO_IPOD, estimated_size=1),
        ],
        storage=StorageSummary(bytes_to_add=2),
    )

    assert sync_plan_required_free_bytes(
        plan,
        db_overhead_bytes=0,
        allocation_unit_size=4096,
    ) == 8192


def test_preflight_blocks_over_capacity_without_until_full(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(
            storage=StorageSummary(bytes_to_add=SYNC_DB_OVERHEAD_BYTES + 1)
        ),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )

    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.shutil.disk_usage",
        lambda _path: SimpleNamespace(
            total=SYNC_DB_OVERHEAD_BYTES * 2,
            used=SYNC_DB_OVERHEAD_BYTES,
            free=SYNC_DB_OVERHEAD_BYTES,
        ),
    )

    assert not executor._preflight_checks(ctx)
    assert ctx.result.errors[0][0] == "storage"
    assert "Not enough space on iPod" in ctx.result.errors[0][1]


def test_preflight_fails_closed_when_free_space_cannot_be_read(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(storage=StorageSummary(bytes_to_add=1)),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.shutil.disk_usage",
        lambda _path: (_ for _ in ()).throw(OSError(errno.EIO, "device I/O error")),
    )

    assert executor._preflight_checks(ctx) is False
    assert ctx.result.success is False
    assert ctx.result.errors[0][0] == "filesystem_safety"
    assert "free space" in ctx.result.errors[0][1]


def test_per_file_space_guard_fails_closed_when_volume_state_is_unreadable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.shutil.disk_usage",
        lambda _path: (_ for _ in ()).throw(OSError(errno.ENOENT, "disconnected")),
    )

    with pytest.raises(DeviceWriteSafetyError, match="free space"):
        executor._ensure_device_has_space_for_write(1, 1)


def test_preflight_allows_over_capacity_with_until_full(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(
            storage=StorageSummary(bytes_to_add=SYNC_DB_OVERHEAD_BYTES + 1)
        ),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
        sync_until_full=True,
    )

    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.shutil.disk_usage",
        lambda _path: SimpleNamespace(
            total=SYNC_DB_OVERHEAD_BYTES * 2,
            used=SYNC_DB_OVERHEAD_BYTES,
            free=SYNC_DB_WRITE_RESERVE_BYTES + 1,
        ),
    )

    assert executor._preflight_checks(ctx)
    assert ctx.result.success


def test_preflight_blocks_read_only_or_permission_denied_mount(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    probe_path = tmp_path / "iPod_Control" / "iTunes" / ".iOpenPod_write_test_x"

    def raise_permission_denied(*_args, **_kwargs):
        raise OSError(errno.EACCES, "Permission denied", str(probe_path))

    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.tempfile.mkstemp",
        raise_permission_denied,
    )

    assert not executor._preflight_checks(ctx)
    assert not ctx.result.success
    assert ctx.result.errors[0][0] == "read-only"
    message = ctx.result.errors[0][1]
    assert "Permission denied" in message
    assert "fsck" not in message


def test_preflight_rejects_file_above_ipod_or_filesystem_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "iTunes").mkdir(parents=True)
    executor = SyncExecutor(
        tmp_path,
        device_storage=SimpleNamespace(device_max_file_size_bytes=4),
    )
    ctx = _SyncContext(
        plan=SyncPlan(
            to_add=[
                SyncItem(
                    action=SyncAction.ADD_TO_IPOD,
                    estimated_size=5,
                    description="oversized.flac",
                )
            ],
            storage=StorageSummary(bytes_to_add=5),
        ),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=10**9, used=0, free=10**9),
    )

    assert executor._preflight_checks(ctx) is False
    assert ctx.result.errors[0][0] == "filesystem_safety"
    assert "oversized.flac" in ctx.result.errors[0][1]


def test_media_copy_flushes_destination_before_reporting_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp3"
    destination = tmp_path / "ipod" / "song.mp3"
    source.write_bytes(b"audio payload")
    destination.parent.mkdir()
    flushed: list[Path] = []

    def record_flush(file, *, full: bool = False) -> None:
        assert full is False
        flushed.append(Path(file.name))

    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.flush_written_file",
        record_flush,
    )

    SyncExecutor._copy_file_chunked(source, destination)

    assert destination.read_bytes() == b"audio payload"
    assert flushed == [destination]


def test_media_copy_creates_device_directory_only_after_revalidation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    ipod_root.mkdir()
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio payload")
    destination = ipod_root / "iPod_Control" / "Music" / "F00" / "song.mp3"
    executor = SyncExecutor(ipod_root, max_workers=1, max_device_write_workers=1)
    executor._filesystem_profile = cast(FilesystemProfile, SimpleNamespace())
    checks: list[bool] = []

    monkeypatch.setattr(
        executor,
        "_revalidate_device_write_readiness",
        lambda: checks.append(destination.parent.exists()),
    )
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=10**9, used=0, free=10**9),
    )

    executor._copy_file_to_device(source, destination)

    assert checks == [False]
    assert destination.read_bytes() == b"audio payload"


def test_until_full_copy_uses_actual_staged_size_instead_of_estimate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    source = tmp_path / "source.mp3"
    ipod_root.mkdir()
    source.write_bytes(b"source-with-tags")
    executor = SyncExecutor(ipod_root, max_workers=1, max_device_write_workers=1)
    transcode_plan = replace(
        resolve_transcode_plan(source, options=executor.transcode_options),
        target=TranscodeTarget.COPY,
    )

    def fake_strip_metadata(path: Path) -> bool:
        path.write_bytes(b"ok")
        return True

    monkeypatch.setattr("iopenpod.sync.sync_executor.strip_metadata", fake_strip_metadata)
    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.shutil.disk_usage",
        lambda _path: SimpleNamespace(
            total=SYNC_DB_WRITE_RESERVE_BYTES + 2,
            used=0,
            free=SYNC_DB_WRITE_RESERVE_BYTES + 2,
        ),
    )

    success, ipod_path, _was_transcoded, err = executor._copy_to_ipod(
        source,
        transcode_plan,
        expected_write_bytes=SYNC_DB_WRITE_RESERVE_BYTES + 3,
        sync_until_full=True,
    )

    assert success
    assert err == ""
    assert ipod_path is not None
    assert ipod_path.read_bytes() == b"ok"


def test_loaded_database_validation_rejects_missing_update_target(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(
            to_update_metadata=[
                SyncItem(
                    action=SyncAction.UPDATE_METADATA,
                    db_track_id=404,
                    metadata_changes={"title": ("New", "Old")},
                )
            ]
        ),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )

    assert not executor._validate_loaded_database_targets(ctx)
    assert not ctx.result.success
    assert ctx.result.errors[0][0] == "stale_plan_to_update_metadata"


def test_loaded_database_validation_accepts_remove_target_by_location(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    location = ":iPod_Control:Music:F00:Song.mp3"
    ctx = _SyncContext(
        plan=SyncPlan(
            to_remove=[
                SyncItem(
                    action=SyncAction.REMOVE_FROM_IPOD,
                    ipod_track={"Location": location},
                )
            ]
        ),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.tracks_by_location[location] = TrackInfo(location=location, title="Song")

    assert executor._validate_loaded_database_targets(ctx)
    assert ctx.result.success


def test_loaded_database_validation_rejects_unsafe_remove_path_before_mutation(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    item = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        db_track_id=7,
        ipod_track={"Location": str(tmp_path.parent / "host-file.mp3")},
    )
    ctx = _SyncContext(
        plan=SyncPlan(to_remove=[item]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.tracks_by_db_track_id[7] = TrackInfo(
        db_track_id=7,
        location=str(tmp_path.parent / "host-file.mp3"),
        title="Unsafe",
    )

    assert executor._validate_loaded_database_targets(ctx) is False
    assert ctx.result.errors[0][0] == "unsafe_device_path_to_remove"


def test_metadata_update_repairs_video_duration(tmp_path: Path) -> None:
    executor = SyncExecutor(tmp_path)
    item = SyncItem(
        action=SyncAction.UPDATE_METADATA,
        db_track_id=42,
        metadata_changes={"duration_ms": (90_250, 0)},
        description="Repair video duration",
    )
    ctx = _SyncContext(
        plan=SyncPlan(to_update_metadata=[item]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    track = TrackInfo(
        title="Movie",
        location=":iPod_Control:Music:F00:MOVI.m4v",
        db_track_id=42,
        length=0,
    )
    ctx.tracks_by_db_track_id[42] = track

    executor._execute_metadata_updates(ctx)

    assert track.length == 90_250


def test_remove_uses_loaded_database_location_over_stale_plan_location(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    stale_location = ":iPod_Control:Music:F00:Old.mp3"
    current_location = ":iPod_Control:Music:F01:Current.mp3"
    ctx = _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.tracks_by_db_track_id[42] = TrackInfo(
        db_track_id=42,
        location=current_location,
        title="Current",
    )
    ctx.tracks_by_location[current_location] = ctx.tracks_by_db_track_id[42]
    item = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        db_track_id=42,
        ipod_track={"Location": stale_location},
    )
    deleted_paths: list[Path] = []

    def record_deleted_path(path: str | Path) -> bool:
        deleted_paths.append(Path(path))
        return True

    monkeypatch.setattr(
        executor,
        "_delete_from_ipod",
        record_deleted_path,
    )

    executor._execute_remove_items(
        ctx,
        [item],
        stage_name="remove",
        start_message="Removing tracks...",
    )

    assert deleted_paths == [tmp_path / "iPod_Control/Music/F01/Current.mp3"]
    assert 42 not in ctx.tracks_by_db_track_id


def test_remove_reports_delete_failure_but_removes_database_row(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    location = ":iPod_Control:Music:F00:Song.mp3"
    ctx = _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.tracks_by_db_track_id[42] = TrackInfo(
        db_track_id=42,
        location=location,
        title="Song",
    )
    ctx.tracks_by_location[location] = ctx.tracks_by_db_track_id[42]
    item = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        db_track_id=42,
        ipod_track={"Location": location},
    )
    monkeypatch.setattr(executor, "_delete_from_ipod", lambda _path: False)

    executor._execute_remove_items(
        ctx,
        [item],
        stage_name="remove",
        start_message="Removing tracks...",
    )

    assert ctx.result.errors
    assert "Could not delete iPod file" in ctx.result.errors[0][1]
    assert 42 not in ctx.tracks_by_db_track_id


def test_commit_file_mutations_can_discard_cancelled_adds_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=lambda: True,
    )
    ctx.new_tracks.append(TrackInfo(location=":iPod_Control:Music:F00:copied.mp3", title="Copied"))
    writes: list[str] = []

    monkeypatch.setattr(
        executor,
        "_execute_write_and_finalize",
        lambda _ctx: writes.append("write"),
    )

    executor._commit_file_mutations(
        ctx,
        on_cancel_with_partial=lambda _added, _skipped: False,
    )

    assert writes == []
    assert not ctx.result.partial_save
    assert "database was not updated" in ctx.result.errors[-1][1]


def test_commit_file_mutations_forces_db_write_after_cancelled_removal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=lambda: True,
    )
    ctx.new_tracks.append(
        TrackInfo(
            location=":iPod_Control:Music:F00:discarded.mp3",
            title="Discarded",
        )
    )
    ctx.result.tracks_removed = 1
    writes: list[str] = []

    monkeypatch.setattr(
        executor,
        "_execute_write_and_finalize",
        lambda _ctx: writes.append("write"),
    )

    executor._commit_file_mutations(
        ctx,
        on_cancel_with_partial=lambda _added, _skipped: False,
    )

    assert writes == ["write"]
    assert ctx.result.partial_save
    assert ctx.new_tracks == []
    assert "removal" in ctx.result.errors[-1][1]


def test_prepare_database_commit_payload_resolves_pending_playlist_source_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "new.mp3"
    source.write_bytes(b"audio")
    source_key = normalize_sync_playlist_path(source)
    playlist_id = sync_playlist_file_id(tmp_path / "mix.m3u8")
    ctx = _SyncContext(
        plan=SyncPlan(
            playlists_to_add=[
                {
                    "Title": "Mix",
                    "playlist_id": playlist_id,
                    "_isNew": True,
                    "_source": "sync_playlist_file",
                    "_mhsd_dataset_type": 2,
                    "items": [{"source_path": source_key}],
                }
            ]
        ),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.new_tracks.append(
        TrackInfo(
            title="New",
            location=":iPod_Control:Music:F00:New.mp3",
            source_path=source_key,
        )
    )
    progress_messages: list[str] = []

    commit_payload = SyncExecutor(tmp_path)._prepare_database_commit_payload(
        ctx,
        advance=progress_messages.append,
    )

    assigned_db_id = ctx.new_tracks[0].db_track_id
    assert assigned_db_id
    assert progress_messages == ["Preparing tracks", "Resolving playlists"]
    assert commit_payload.all_tracks == ctx.new_tracks
    assert [playlist.track_ids for playlist in commit_payload.playlists] == [
        [assigned_db_id]
    ]


def test_parallel_copy_stage_caches_source_identity_for_backpatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        fingerprint="fp-one",
        pc_track=_make_pc_track(source),
        estimated_size=source.stat().st_size,
    )
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[item]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    executor = SyncExecutor(tmp_path, max_workers=1)
    cached_identity = (123, 456.0, "source-hash")
    passed_identities: list[tuple[int, float, str | None] | None] = []

    monkeypatch.setattr(
        "iopenpod.sync.sync_executor._current_source_identity",
        lambda _pc_track: cached_identity,
    )

    def fake_copy_to_ipod(_source_path, _transcode_plan, **kwargs):
        passed_identities.append(kwargs.get("source_identity"))
        destination = tmp_path / "iPod_Control" / "Music" / "F00" / "source.mp3"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"audio")
        return True, destination, False, ""

    monkeypatch.setattr(executor, "_copy_to_ipod", fake_copy_to_ipod)
    successes: list[Path] = []

    executor._parallel_copy_stage(
        ctx,
        stage_name="add",
        items=[item],
        on_success=lambda _item, ipod_path, _was_transcoded: successes.append(
            ipod_path
        ),
    )

    assert successes
    assert ctx.sync_item_source_identities[id(item)] == cached_identity
    assert passed_identities == [cached_identity]


def test_backpatch_new_tracks_reuses_cached_source_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    pc_track = _make_pc_track(source)
    ipod_dest = tmp_path / "iPod_Control" / "Music" / "F00" / "source.mp3"
    ipod_dest.parent.mkdir(parents=True)
    ipod_dest.write_bytes(b"audio")
    track_info = TrackInfo(
        title="Source",
        location=":iPod_Control:Music:F00:source.mp3",
        db_track_id=77,
    )
    item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        fingerprint="fp-one",
        pc_track=pc_track,
    )
    ctx = _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.new_tracks.append(track_info)
    ctx.new_track_fingerprints[id(track_info)] = "fp-one"
    ctx.new_track_info[id(track_info)] = (pc_track, ipod_dest, False, item)
    ctx.sync_item_source_identities[id(item)] = (987, 654.0, "cached-source-hash")

    def fail_current_identity(_pc_track):
        raise AssertionError("backpatch should use the worker-cached identity")

    monkeypatch.setattr(
        "iopenpod.sync.sync_executor._current_source_identity",
        fail_current_identity,
    )

    SyncExecutor(tmp_path)._backpatch_new_tracks(ctx)

    entry = ctx.mapping.get_entries("fp-one")[0]
    assert entry.source_size == 987
    assert entry.source_mtime == 654.0
    assert entry.source_hash == "cached-source-hash"


def test_auto_write_workers_use_flash_friendly_default_for_nano(tmp_path: Path) -> None:
    executor = SyncExecutor(
        tmp_path,
        max_workers=6,
        max_device_write_workers=0,
        device_info=SimpleNamespace(model_family="iPod Nano", generation="7th Gen"),
    )

    assert executor._max_device_write_workers == 4


def test_explicit_write_workers_override_auto_and_clamp_to_overall(tmp_path: Path) -> None:
    executor = SyncExecutor(
        tmp_path,
        max_workers=2,
        max_device_write_workers=4,
        device_info=SimpleNamespace(model_family="iPod Classic", generation="6th Gen"),
    )

    assert executor._max_device_write_workers == 2


def test_auto_write_workers_preserve_existing_behavior_without_device_info(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(
        tmp_path,
        max_workers=5,
        max_device_write_workers=0,
        device_info=None,
    )

    assert executor._max_device_write_workers == 5


def test_device_write_limit_serializes_final_ipod_writes(monkeypatch, tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    source = tmp_path / "source.mp3"
    ipod_root.mkdir()
    source.write_bytes(b"source-bytes")

    executor = SyncExecutor(
        ipod_root,
        max_workers=4,
        max_device_write_workers=1,
    )

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_copy_file_chunked(src, dst, progress=None, chunk_size=256 * 1024, is_cancelled=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            Path(dst).write_bytes(Path(src).read_bytes())
            if progress:
                progress(1.0)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(executor, "_copy_file_chunked", fake_copy_file_chunked)
    transcode_plan = replace(
        resolve_transcode_plan(source, options=executor.transcode_options),
        target=TranscodeTarget.COPY,
    )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(executor._copy_to_ipod, source, transcode_plan)
            for _ in range(4)
        ]
        results = [future.result() for future in futures]

    assert all(success for success, _path, _was_transcoded, _err in results)
    assert max_active == 1


def test_device_write_limit_allows_multiple_parallel_writes_when_configured(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    source = tmp_path / "source.mp3"
    ipod_root.mkdir()
    source.write_bytes(b"source-bytes")

    executor = SyncExecutor(
        ipod_root,
        max_workers=4,
        max_device_write_workers=2,
    )

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_copy_file_chunked(src, dst, progress=None, chunk_size=256 * 1024, is_cancelled=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            Path(dst).write_bytes(Path(src).read_bytes())
            if progress:
                progress(1.0)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(executor, "_copy_file_chunked", fake_copy_file_chunked)
    transcode_plan = replace(
        resolve_transcode_plan(source, options=executor.transcode_options),
        target=TranscodeTarget.COPY,
    )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(executor._copy_to_ipod, source, transcode_plan)
            for _ in range(4)
        ]
        results = [future.result() for future in futures]

    assert all(success for success, _path, _was_transcoded, _err in results)
    assert 1 < max_active <= 2


def test_copy_stage_uses_planned_transcode_decision(monkeypatch, tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    source = tmp_path / "source.mp3"
    ipod_root.mkdir()
    source.write_bytes(b"source-bytes")

    executor = SyncExecutor(
        ipod_root,
        max_workers=1,
        max_device_write_workers=1,
    )
    transcode_plan = replace(
        resolve_transcode_plan(source, options=executor.transcode_options),
        target=TranscodeTarget.COPY,
    )
    item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=_make_pc_track(source),
        estimated_size=source.stat().st_size,
        transcode_plan=transcode_plan,
    )
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[item]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    copied: list[tuple[Path, bool]] = []

    def fail_resolve(*_args, **_kwargs):
        raise AssertionError("executor should use the SyncItem transcode_plan")

    monkeypatch.setattr(
        "iopenpod.sync.sync_executor.resolve_transcode_plan",
        fail_resolve,
    )

    executor._parallel_copy_stage(
        ctx,
        stage_name="add",
        items=[item],
        on_success=lambda _item, ipod_path, was_transcoded: copied.append(
            (ipod_path, was_transcoded)
        ),
    )

    assert len(copied) == 1
    assert copied[0][0].exists()
    assert copied[0][1] is False


def test_direct_copy_writes_metadata_stripped_payload_without_touching_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    source = tmp_path / "source.mp3"
    ipod_root.mkdir()
    source.write_bytes(b"source-with-tags")

    executor = SyncExecutor(
        ipod_root,
        max_workers=1,
        max_device_write_workers=1,
    )
    transcode_plan = replace(
        resolve_transcode_plan(source, options=executor.transcode_options),
        target=TranscodeTarget.COPY,
    )
    copied_from: list[Path] = []

    def fake_strip_metadata(path: Path) -> bool:
        assert path != source
        path.write_bytes(b"stripped")
        return True

    def fake_copy_file_chunked(src, dst, progress=None, chunk_size=256 * 1024, is_cancelled=None):
        copied_from.append(Path(src))
        Path(dst).write_bytes(Path(src).read_bytes())
        if progress:
            progress(1.0)

    monkeypatch.setattr("iopenpod.sync.sync_executor.strip_metadata", fake_strip_metadata)
    monkeypatch.setattr(executor, "_copy_file_chunked", fake_copy_file_chunked)

    success, ipod_path, was_transcoded, err = executor._copy_to_ipod(source, transcode_plan)

    assert success is True
    assert err == ""
    assert was_transcoded is False
    assert ipod_path is not None
    assert ipod_path.read_bytes() == b"stripped"
    assert source.read_bytes() == b"source-with-tags"
    assert copied_from and copied_from[0] != source
    assert not copied_from[0].exists()


def test_transcoded_file_is_stripped_before_device_write(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    source = tmp_path / "source.flac"
    transcoded = tmp_path / "out.m4a"
    ipod_root.mkdir()
    source.write_bytes(b"source")
    transcoded.write_bytes(b"transcoded-with-tags")

    executor = SyncExecutor(
        ipod_root,
        max_workers=1,
        max_device_write_workers=1,
    )
    transcode_plan = replace(
        resolve_transcode_plan(source, options=executor.transcode_options),
        target=TranscodeTarget.AAC,
    )

    def fake_transcode(*_args, **_kwargs):
        return TranscodeResult(
            success=True,
            source_path=source,
            output_path=transcoded,
            target_format=TranscodeTarget.AAC,
            was_transcoded=True,
        )

    stripped_inputs: list[Path] = []

    def fake_strip_metadata(path: Path) -> bool:
        assert path != transcoded
        stripped_inputs.append(path)
        path.write_bytes(b"stripped-transcode")
        return True

    monkeypatch.setattr("iopenpod.sync.sync_executor.transcode", fake_transcode)
    monkeypatch.setattr("iopenpod.sync.sync_executor.strip_metadata", fake_strip_metadata)

    success, ipod_path, was_transcoded, err = executor._copy_to_ipod(source, transcode_plan)

    assert success is True
    assert err == ""
    assert was_transcoded is True
    assert ipod_path is not None
    assert ipod_path.read_bytes() == b"stripped-transcode"
    assert stripped_inputs and not stripped_inputs[0].exists()


def test_file_updates_do_not_preinvalidate_transcode_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    source = tmp_path / "source.m4a"
    source.write_bytes(b"x")
    pc_track = _make_pc_track(source)
    item = SyncItem(
        action=SyncAction.UPDATE_FILE,
        fingerprint="123,456,789",
        pc_track=pc_track,
        estimated_size=pc_track.size,
    )
    ctx = _SyncContext(
        plan=SyncPlan(to_update_file=[item]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )

    def fail_invalidate(*_args, **_kwargs):
        raise AssertionError("cache should validate on lookup, not pre-invalidate")

    monkeypatch.setattr(executor.transcode_cache, "invalidate", fail_invalidate)
    monkeypatch.setattr(
        executor,
        "_parallel_copy_stage",
        lambda *_args, **_kwargs: None,
    )

    executor._execute_file_updates(ctx)


def test_playlist_build_resolves_existing_tracks_from_matched_pc_paths(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    ctx = _SyncContext(
        plan=SyncPlan(matched_pc_paths={101: str(source)}),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=True,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.existing_dataset2_standard_playlists_raw = [
        {
            "Title": "Synced Mix",
            "playlist_id": 42,
            "items": [{"source_path": str(source)}],
        }
    ]
    existing_track = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:Song.mp3",
        db_track_id=101,
    )

    _master_name, _master_id, playlists, *_rest = executor._build_and_evaluate_playlists(
        ctx,
        [existing_track],
    )

    assert len(playlists) == 1
    assert playlists[0].track_ids == [101]


def test_merge_plan_playlists_does_not_remove_same_id_from_dataset5(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    user_playlist = {
        "playlist_id": 42,
        "Title": "Recently Played",
        "_source": "smart",
        "smart_playlist_data": {"live_update": True},
        "smart_playlist_rules": {"rules": []},
    }
    ctx = _make_sync_ctx(
        playlist_updates=[user_playlist],
        existing_dataset2_standard_playlists_raw=[],
        existing_dataset5_smart_playlists_raw=[
            {
                "playlist_id": 42,
                "Title": "Old Smart Bucket Copy",
                "_source": "smart",
                "smart_playlist_data": {"live_update": True},
                "smart_playlist_rules": {"rules": []},
            }
        ],
    )

    executor._merge_plan_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == [user_playlist]
    assert ctx.existing_dataset5_smart_playlists_raw == [
        {
            "playlist_id": 42,
            "Title": "Old Smart Bucket Copy",
            "_source": "smart",
            "smart_playlist_data": {"live_update": True},
            "smart_playlist_rules": {"rules": []},
        }
    ]


def test_merge_plan_playlists_leaves_ipod_categories_in_smart_bucket(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    category = {
        "playlist_id": 43,
        "Title": "Music",
        "_source": "category",
        "mhsd5_type": 4,
    }
    ctx = _make_sync_ctx(
        playlist_updates=[category],
        existing_dataset2_standard_playlists_raw=[],
        existing_dataset5_smart_playlists_raw=[],
    )

    executor._merge_plan_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == []
    assert ctx.existing_dataset5_smart_playlists_raw == [category]


def test_merge_plan_playlists_applies_playlist_adds_and_edits(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    new_playlist = {
        "playlist_id": 101,
        "Title": "Synced Mix",
        "_isNew": True,
        "_mhsd_dataset_type": 2,
        "items": [{"source_path": "/music/a.mp3"}],
    }
    edited_playlist = {
        "playlist_id": 202,
        "Title": "Updated Mix",
        "_isNew": False,
        "_mhsd_dataset_type": 2,
        "items": [{"db_track_id": 99}],
    }
    ctx = _make_sync_ctx(
        playlist_updates=[],
        existing_dataset2_standard_playlists_raw=[
            {
                "playlist_id": 202,
                "Title": "Old Mix",
                "_mhsd_dataset_type": 2,
                "items": [],
            }
        ],
        existing_dataset5_smart_playlists_raw=[],
    )
    ctx.plan.playlists_to_add = [new_playlist]
    ctx.plan.playlists_to_edit = [edited_playlist]

    executor._merge_plan_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == [
        edited_playlist,
        new_playlist,
    ]


def test_merge_plan_playlists_mirrors_regular_rows_to_dataset3(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    new_playlist = {
        "playlist_id": 101,
        "Title": "Synced Mix",
        "_isNew": True,
        "_mhsd_dataset_type": 2,
        "items": [{"db_track_id": 99}],
    }
    ctx = _make_sync_ctx(
        playlist_updates=[],
        existing_dataset2_standard_playlists_raw=[],
        existing_dataset3_podcast_playlists_raw=[
            {
                "playlist_id": 1,
                "Title": "iPod",
                "master_flag": 1,
                "_mhsd_dataset_type": 3,
            }
        ],
        existing_dataset5_smart_playlists_raw=[],
    )
    ctx.plan.playlists_to_add = [new_playlist]

    executor._merge_plan_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == [
        {
            **new_playlist,
            "_mhsd_dataset_type": 2,
            "_mhsd_result_key": "mhlp",
            "_source": "regular",
        }
    ]
    assert ctx.existing_dataset3_podcast_playlists_raw == [
        {
            "playlist_id": 1,
            "Title": "iPod",
            "master_flag": 1,
            "_mhsd_dataset_type": 3,
        },
        {
            **new_playlist,
            "_mhsd_dataset_type": 3,
            "_mhsd_result_key": "mhlp_podcast",
            "_source": "regular",
        },
    ]


def test_merge_plan_playlist_edit_updates_dataset2_and_dataset3_twins(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    edited_playlist = {
        "playlist_id": 202,
        "Title": "Updated Mix",
        "_isNew": False,
        "_mhsd_dataset_type": 2,
        "items": [{"db_track_id": 99}],
    }
    ctx = _make_sync_ctx(
        playlist_updates=[],
        existing_dataset2_standard_playlists_raw=[
            {
                "playlist_id": 202,
                "Title": "Old Mix",
                "_mhsd_dataset_type": 2,
                "items": [],
            }
        ],
        existing_dataset3_podcast_playlists_raw=[
            {
                "playlist_id": 1,
                "Title": "iPod",
                "master_flag": 1,
                "_mhsd_dataset_type": 3,
            },
            {
                "playlist_id": 202,
                "Title": "Old Mix",
                "_mhsd_dataset_type": 3,
                "items": [],
            },
        ],
        existing_dataset5_smart_playlists_raw=[],
    )
    ctx.plan.playlists_to_edit = [edited_playlist]

    executor._merge_plan_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == [
        {
            **edited_playlist,
            "_mhsd_dataset_type": 2,
            "_mhsd_result_key": "mhlp",
            "_source": "regular",
        }
    ]
    assert ctx.existing_dataset3_podcast_playlists_raw[1] == {
        **edited_playlist,
        "_mhsd_dataset_type": 3,
        "_mhsd_result_key": "mhlp_podcast",
        "_source": "regular",
    }


def test_merge_plan_playlist_removal_deletes_dataset2_and_dataset3_twins(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    removal = {
        "playlist_id": 202,
        "Title": "Synced Mix",
        "_mhsd_dataset_type": 2,
        "_source": "sync_playlist_file",
    }
    ctx = _make_sync_ctx(
        playlist_updates=[],
        existing_dataset2_standard_playlists_raw=[
            {
                "playlist_id": 202,
                "Title": "Synced Mix",
                "_mhsd_dataset_type": 2,
                "_source": "sync_playlist_file",
            }
        ],
        existing_dataset3_podcast_playlists_raw=[
            {
                "playlist_id": 1,
                "Title": "iPod",
                "master_flag": 1,
                "_mhsd_dataset_type": 3,
            },
            {
                "playlist_id": 202,
                "Title": "Synced Mix",
                "_mhsd_dataset_type": 3,
                "_source": "sync_playlist_file",
            },
        ],
        existing_dataset5_smart_playlists_raw=[],
    )
    ctx.plan.playlists_to_remove = [removal]

    executor._merge_plan_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == []
    assert ctx.existing_dataset3_podcast_playlists_raw == [
        {
            "playlist_id": 1,
            "Title": "iPod",
            "master_flag": 1,
            "_mhsd_dataset_type": 3,
        }
    ]


def test_merge_plan_playlists_replaces_new_playlist_id_collision(
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    incoming = {
        "playlist_id": 101,
        "Title": "Incoming Mix",
        "_isNew": True,
        "_mhsd_dataset_type": 2,
        "items": [{"db_track_id": 1}],
    }
    ctx = _make_sync_ctx(
        playlist_updates=[incoming],
        existing_dataset2_standard_playlists_raw=[
            {
                "playlist_id": 101,
                "Title": "Existing Mix",
                "_mhsd_dataset_type": 2,
                "items": [{"db_track_id": 2}],
            }
        ],
        existing_dataset5_smart_playlists_raw=[],
    )

    executor._merge_plan_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == [incoming]


def test_merge_plan_playlists_removes_reviewed_playlist_rows(tmp_path: Path) -> None:
    executor = SyncExecutor(tmp_path)
    remove_playlist = {
        "playlist_id": "42",
        "Title": "Synced Mix",
        "_mhsd_dataset_type": 2,
    }
    kept_playlist = {
        "playlist_id": 43,
        "Title": "Manual Mix",
        "_mhsd_dataset_type": 2,
    }
    ctx = _make_sync_ctx(
        playlist_updates=[],
        existing_dataset2_standard_playlists_raw=[remove_playlist, kept_playlist],
        existing_dataset5_smart_playlists_raw=[],
    )
    ctx.plan.playlists_to_remove = [remove_playlist]

    executor._merge_plan_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == [kept_playlist]
    assert ctx.existing_dataset5_smart_playlists_raw == []
