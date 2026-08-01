from pathlib import Path
from types import SimpleNamespace

from iopenpod.device.storage_safety import FileSizeLimitError
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync import sync_executor as sync_executor_module
from iopenpod.sync.contracts import SyncPlan
from iopenpod.sync.database_commit import DatabaseCommitPayload
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.sync_executor import SyncExecutor, _SyncContext


def _context() -> _SyncContext:
    return _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )


def test_new_track_artwork_path_normalizes_without_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "Zoe - Azul.m4a"
    source.write_bytes(b"audio")
    destination = tmp_path / "iPod_Control" / "Music" / "F00" / "Azul.m4a"

    track = TrackInfo(
        title="Azul",
        location=":iPod_Control:Music:F00:Azul.m4a",
        db_track_id=12345,
    )
    ctx = _context()
    ctx.new_tracks.append(track)
    ctx.pc_file_paths[id(track)] = str(source)
    ctx.new_track_info[id(track)] = (
        SimpleNamespace(path=str(source)),
        destination,
        False,
    )

    normalized = SyncExecutor._normalize_artwork_pc_paths(ctx, [track])

    assert normalized == {12345: str(source)}


def test_database_size_failure_preserves_recovery_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executor = SyncExecutor(tmp_path)
    ctx = _context()
    payload = DatabaseCommitPayload(
        all_tracks=[
            TrackInfo(
                title="Too Large",
                location=":iPod_Control:Music:F00:TOO-LARGE.m4a",
                lyrics="long lyric " * 100,
            )
        ]
    )
    error = FileSizeLimitError("iTunesDB is too large")
    error.proposed_database_bytes = b"mhbd-proposed"
    error.proposed_database_filename = "iTunesDB"

    monkeypatch.setattr(executor, "_revalidate_device_write_readiness", lambda: None)
    monkeypatch.setattr(
        sync_executor_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=8 * 1024 * 1024),
    )
    monkeypatch.setattr(
        executor,
        "_prepare_database_commit_payload",
        lambda _ctx, **_kwargs: payload,
    )
    monkeypatch.setattr(
        sync_executor_module,
        "write_database_commit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    executor._execute_write_and_finalize(ctx)

    assert ctx.result.success is False
    assert ctx.result.proposed_database_bytes == b"mhbd-proposed"
    assert ctx.result.proposed_database_recovery is not None
    assert ctx.result.proposed_database_recovery.payload is payload
    assert ctx.result.proposed_database_recovery.mapping is ctx.mapping
    assert ctx.result.errors == [("database_size", "iTunesDB is too large")]
