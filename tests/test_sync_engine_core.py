from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from iopenpod.sync.core import (
    EngineOperation,
    EngineOptions,
    EnginePlanContext,
    EngineProgress,
    EngineRequest,
    EngineStage,
    EngineTransactionPolicy,
    SyncEngine,
)
from iopenpod.sync.path_identity import stable_path_key


def test_quick_write_wraps_progress_and_copies_payloads(monkeypatch) -> None:
    from iopenpod.sync import quick_writes

    captured: dict[str, Any] = {}

    def fake_write_cached_itunesdb(
        ipod_path,
        *,
        tracks_data,
        playlists_data,
        artwork_sources=None,
        progress_callback=None,
        expected_database_generation=None,
        reported_volume_format="",
        expected_volume_identity_key="",
    ):
        captured["ipod_path"] = ipod_path
        captured["tracks_data"] = tracks_data
        captured["playlists_data"] = playlists_data
        captured["artwork_sources"] = artwork_sources
        captured["expected_database_generation"] = expected_database_generation
        captured["reported_volume_format"] = reported_volume_format
        captured["expected_volume_identity_key"] = expected_volume_identity_key
        tracks_data[0]["Title"] = "mutated"
        if progress_callback is not None:
            progress_callback(
                SimpleNamespace(current=1, total=2, message="Writing database")
            )
        return SimpleNamespace(success=True)

    monkeypatch.setattr(quick_writes, "write_cached_itunesdb", fake_write_cached_itunesdb)

    progress_events: list[EngineProgress] = []
    original_track = {"Title": "Original"}
    database_generation = object()
    result = SyncEngine().quick_write(
        EngineRequest(
            operation=EngineOperation.QUICK_WRITE,
            ipod_path="/Volumes/iPod",
            tracks_data=(original_track,),
            playlists_data=({"Title": "Playlist"},),
            artwork_sources={101: "/tmp/art.jpg"},
            device_storage=SimpleNamespace(
                reported_volume_format="FAT32",
                volume_identity_key="scan-volume",
            ),
            expected_database_generation=database_generation,
            progress_callback=progress_events.append,
        )
    )

    assert result.success
    assert captured["ipod_path"] == "/Volumes/iPod"
    assert captured["artwork_sources"] == {101: "/tmp/art.jpg"}
    assert captured["expected_database_generation"] is database_generation
    assert captured["reported_volume_format"] == "FAT32"
    assert captured["expected_volume_identity_key"] == "scan-volume"
    assert original_track == {"Title": "Original"}
    assert progress_events[0].stage == EngineStage.ASSEMBLE_COMMIT
    assert progress_events[1].stage == EngineStage.COMMIT
    assert progress_events[1].message == "Writing database"


def test_engine_plan_context_normalizes_paths_and_indexes(tmp_path) -> None:
    music_root = tmp_path / "Music"
    selected_track = music_root / "song.mp3"
    selected_playlist = music_root / "mix.m3u8"
    ipod_root = tmp_path / "iPod"

    context = EnginePlanContext.from_request(
        EngineRequest(
            operation=EngineOperation.PLAN,
            ipod_path=ipod_root,
            pc_folders=(music_root, "", "  "),
            ipod_tracks=(
                {"track_id": "7", "db_track_id": "101", "Title": "Song"},
                {"track_id": 8, "db_id": 202, "Title": "Other"},
            ),
            existing_playlists=(
                {"playlist_id": "55", "Title": "Mix"},
                {"playlist_id": 0, "Title": "No ID"},
            ),
            track_edits={101: {"rating": (0, 80)}},
            options=EngineOptions(
                allowed_paths=frozenset({str(selected_track)}),
                selected_playlist_paths=frozenset({str(selected_playlist)}),
                photo_sync_settings={"fit_photo_thumbnails": True},
            ),
        )
    )

    assert context.ipod_path == str(ipod_root)
    assert context.pc_folders == (music_root,)
    assert context.pc_folder_keys == (stable_path_key(music_root),)
    assert set(context.ipod_by_db_track_id) == {101, 202}
    assert context.old_track_id_to_db_track_id == {7: 101, 8: 202}
    assert set(context.playlist_by_id) == {55}
    assert context.track_edits == {101: {"rating": (0, 80)}}
    assert context.allowed_path_keys == frozenset({stable_path_key(selected_track)})
    assert context.selected_playlist_source_keys == frozenset(
        {stable_path_key(selected_playlist)}
    )
    assert context.photo_sync_settings == {"fit_photo_thumbnails": True}


def test_engine_plan_context_accepts_structured_media_folder_entries(tmp_path) -> None:
    music_root = tmp_path / "Music"
    music_root.mkdir()
    raw_entry = {
        "directory": str(music_root),
        "recurse": False,
        "media_types": ["music", "playlists"],
    }

    context = EnginePlanContext.from_request(
        EngineRequest(
            operation=EngineOperation.PLAN,
            pc_folders=(raw_entry,),
        )
    )

    assert context.pc_folders == (raw_entry,)
    assert context.pc_folder_keys == (stable_path_key(music_root),)


def test_compute_plan_uses_normalized_plan_context(monkeypatch, tmp_path) -> None:
    import iopenpod.sync.fingerprint_diff_engine as diff_module
    import iopenpod.sync.pc_library as pc_library_module

    captured: dict[str, Any] = {}

    class FakePCLibrary:
        def __init__(self, roots):
            captured["pc_roots"] = roots

    class FakeDiffEngine:
        def __init__(self, pc_library, ipod_path, **kwargs):
            captured["pc_library"] = pc_library
            captured["ipod_path"] = ipod_path
            captured["diff_kwargs"] = kwargs

        def compute_diff(self, ipod_tracks, **kwargs):
            captured["ipod_tracks"] = ipod_tracks
            captured["compute_kwargs"] = kwargs
            kwargs["progress_callback"]("diff", 1, 1, "Done")
            return SimpleNamespace(success=True)

    monkeypatch.setattr(pc_library_module, "PCLibrary", FakePCLibrary)
    monkeypatch.setattr(diff_module, "FingerprintDiffEngine", FakeDiffEngine)

    music_root = tmp_path / "Music"
    allowed_track = music_root / "song.mp3"
    selected_playlist = music_root / "mix.m3u8"
    progress_events: list[EngineProgress] = []

    result = cast(
        Any,
        SyncEngine().compute_plan(
            EngineRequest(
                operation=EngineOperation.PLAN,
                ipod_path=tmp_path / "iPod",
                pc_folders=(music_root, ""),
                ipod_tracks=({"db_track_id": 101},),
                existing_playlists=({"playlist_id": 55},),
                track_edits={101: {"rating": (0, 80)}},
                options=EngineOptions(
                    supports_video=False,
                    allowed_paths=frozenset({str(allowed_track)}),
                    selected_playlist_paths=frozenset({str(selected_playlist)}),
                    photo_sync_settings={"fit_photo_thumbnails": True},
                ),
                progress_callback=progress_events.append,
            )
        )
    )

    assert result.success
    assert captured["pc_roots"] == (music_root,)
    assert captured["ipod_path"] == str(tmp_path / "iPod")
    assert captured["diff_kwargs"]["supports_video"] is False
    assert captured["diff_kwargs"]["photo_sync_settings"] == {
        "fit_photo_thumbnails": True
    }
    assert captured["ipod_tracks"] == [{"db_track_id": 101}]
    compute_kwargs = captured["compute_kwargs"]
    assert compute_kwargs["track_edits"] == {101: {"rating": (0, 80)}}
    assert compute_kwargs["allowed_paths"] == frozenset({stable_path_key(allowed_track)})
    assert compute_kwargs["selected_playlist_paths"] == frozenset(
        {stable_path_key(selected_playlist)}
    )
    assert compute_kwargs["existing_playlists"] == [{"playlist_id": 55}]
    assert progress_events[-2].stage == EngineStage.IDENTIFY
    assert progress_events[-1].stage == EngineStage.PLAN


def test_execute_plan_builds_legacy_request_from_typed_options(monkeypatch, tmp_path) -> None:
    import iopenpod.sync.mapping as mapping_module
    import iopenpod.sync.sync_executor as sync_executor_module

    captured: dict[str, Any] = {}

    class FakeMappingManager:
        def __init__(self, ipod_path):
            captured["mapping_path"] = ipod_path

        def load(self):
            return {"loaded": True}

    class FakeExecutor:
        def __init__(self, ipod_path, **kwargs):
            captured["executor_path"] = ipod_path
            captured["executor_kwargs"] = kwargs

        def execute_request(self, request):
            captured["sync_request"] = request
            request.progress_callback(
                SimpleNamespace(
                    stage="write_database",
                    current=3,
                    total=4,
                    message="Committing database",
                )
            )
            return SimpleNamespace(success=True)

    monkeypatch.setattr(mapping_module, "MappingManager", FakeMappingManager)
    monkeypatch.setattr(sync_executor_module, "SyncExecutor", FakeExecutor)

    progress_events: list[EngineProgress] = []
    result = SyncEngine().execute_plan(
        EngineRequest(
            operation=EngineOperation.EXECUTE,
            ipod_path=tmp_path,
            plan=SimpleNamespace(name="plan"),
            options=EngineOptions(
                sync_workers=2,
                device_write_workers=1,
                transcode_cache_dir=str(tmp_path / "cache"),
                write_back_to_pc=True,
                compute_sound_check=True,
                sync_until_full=True,
            ),
            progress_callback=progress_events.append,
        )
    )

    assert result.success
    assert captured["mapping_path"] == str(tmp_path)
    assert captured["executor_path"] == str(tmp_path)
    assert captured["executor_kwargs"]["max_workers"] == 2
    assert captured["executor_kwargs"]["max_device_write_workers"] == 1
    assert captured["executor_kwargs"]["cache_dir"] == tmp_path / "cache"
    sync_request = captured["sync_request"]
    assert sync_request.mapping == {"loaded": True}
    assert sync_request.write_back_to_pc is True
    assert sync_request.compute_sound_check is True
    assert sync_request.sync_until_full is True
    assert progress_events[0].stage == EngineStage.VALIDATE
    assert progress_events[-1].stage == EngineStage.COMMIT


def test_engine_progress_stage_classification_covers_current_pipeline() -> None:
    engine = SyncEngine()

    assert engine._planning_stage("scan_pc") == EngineStage.SCAN
    assert engine._planning_stage("scan_playlists") == EngineStage.SCAN
    assert engine._planning_stage("scan_photos") == EngineStage.SCAN
    assert engine._planning_stage("fingerprint") == EngineStage.IDENTIFY
    assert engine._planning_stage("load_mapping") == EngineStage.LOAD

    for stage in (
        "add",
        "update_file",
        "remove",
        "remove_chapter",
        "replace_remove",
        "podcast_download",
        "transcode",
    ):
        assert engine._execution_stage(stage) == EngineStage.EXECUTE_FILES

    for stage in (
        "update_metadata",
        "playlists",
        "sound_check",
        "sync_playcount",
        "sync_rating",
        "scrobble_listenbrainz",
        "scrobble_lastfm",
    ):
        assert engine._execution_stage(stage) == EngineStage.ASSEMBLE_COMMIT

    for stage in (
        "write_database",
        "quick_write",
        "photos",
        "photo_prepare",
        "photo_write",
        "photo_compact",
    ):
        assert engine._execution_stage(stage) == EngineStage.COMMIT

    assert engine._execution_stage("backpatch") == EngineStage.POST_COMMIT


def test_run_reports_transaction_policy_diagnostic(monkeypatch) -> None:
    from iopenpod.sync import quick_writes

    monkeypatch.setattr(
        quick_writes,
        "write_cached_itunesdb",
        lambda *args, **kwargs: SimpleNamespace(success=True),
    )

    outcome = SyncEngine().run(
        EngineRequest(
            operation=EngineOperation.QUICK_WRITE,
            tracks_data=({"Title": "Track"},),
            options=EngineOptions(
                transaction_policy=EngineTransactionPolicy.ALL_OR_NOTHING
            ),
        )
    )

    assert outcome.success
    assert [diagnostic.code for diagnostic in outcome.diagnostics] == [
        "unsupported_transaction_policy"
    ]
