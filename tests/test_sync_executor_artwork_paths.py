from pathlib import Path
from types import SimpleNamespace

from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync.contracts import SyncPlan
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
