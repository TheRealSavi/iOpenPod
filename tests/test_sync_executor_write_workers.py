from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from iTunesDB_Writer.mhit_writer import TrackInfo
from SyncEngine.fingerprint_diff_engine import SyncAction, SyncItem, SyncPlan
from SyncEngine.mapping import MappingFile
from SyncEngine.pc_library import PCTrack
from SyncEngine.sync_executor import SyncExecutor, _SyncContext
from SyncEngine.transcoder import TranscodeResult, TranscodeTarget, resolve_transcode_plan


def _make_sync_ctx(
    user_playlists: list[dict],
    existing_dataset2_standard_playlists_raw: list[dict],
    existing_dataset5_smart_playlists_raw: list[dict],
) -> _SyncContext:
    ctx = _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=True,
        write_back_to_pc=False,
        _is_cancelled=None,
        user_playlists=user_playlists,
    )
    ctx.existing_dataset2_standard_playlists_raw = (
        existing_dataset2_standard_playlists_raw
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
    transcode_plan = resolve_transcode_plan(source, options=executor.transcode_options)

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
    transcode_plan = resolve_transcode_plan(source, options=executor.transcode_options)

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
    transcode_plan = resolve_transcode_plan(source, options=executor.transcode_options)
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
        "SyncEngine.sync_executor.resolve_transcode_plan",
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
    transcode_plan = resolve_transcode_plan(source, options=executor.transcode_options)
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

    monkeypatch.setattr("SyncEngine.sync_executor.strip_metadata", fake_strip_metadata)
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

    monkeypatch.setattr("SyncEngine.sync_executor.transcode", fake_transcode)
    monkeypatch.setattr("SyncEngine.sync_executor.strip_metadata", fake_strip_metadata)

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


def test_merge_gui_playlists_does_not_remove_same_id_from_dataset5(
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
        user_playlists=[user_playlist],
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

    executor._merge_gui_playlists(ctx)

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


def test_merge_gui_playlists_leaves_ipod_categories_in_smart_bucket(
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
        user_playlists=[category],
        existing_dataset2_standard_playlists_raw=[],
        existing_dataset5_smart_playlists_raw=[],
    )

    executor._merge_gui_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == []
    assert ctx.existing_dataset5_smart_playlists_raw == [category]


def test_merge_gui_playlists_removes_reviewed_playlist_rows(tmp_path: Path) -> None:
    executor = SyncExecutor(tmp_path)
    remove_playlist = {
        "playlist_id": 42,
        "Title": "Synced Mix",
        "_mhsd_dataset_type": 2,
    }
    kept_playlist = {
        "playlist_id": 43,
        "Title": "Manual Mix",
        "_mhsd_dataset_type": 2,
    }
    ctx = _make_sync_ctx(
        user_playlists=[],
        existing_dataset2_standard_playlists_raw=[remove_playlist, kept_playlist],
        existing_dataset5_smart_playlists_raw=[],
    )
    ctx.plan.playlists_to_remove = [remove_playlist]

    executor._merge_gui_playlists(ctx)

    assert ctx.existing_dataset2_standard_playlists_raw == [kept_playlist]
    assert ctx.existing_dataset5_smart_playlists_raw == []
