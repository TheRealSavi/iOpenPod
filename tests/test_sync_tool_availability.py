from pathlib import Path
from types import SimpleNamespace

from iopenpod.application.jobs import (
    DropScanWorker,
    SyncExecuteWorker,
    SyncToolAvailability,
    check_sync_tool_availability,
)
from iopenpod.infrastructure.settings_schema import AppSettings


def test_sync_tool_availability_summarizes_missing_tools() -> None:
    availability = SyncToolAvailability(
        missing_ffmpeg=True,
        missing_fpcalc=True,
        can_download=False,
    )

    assert availability.has_missing is True
    assert availability.can_continue_without_download is False
    assert availability.tool_names == ("fpcalc (Chromaprint)", "FFmpeg/ffprobe")
    assert availability.tool_list == "fpcalc (Chromaprint) and FFmpeg/ffprobe"
    assert "ffprobe" in availability.install_help_text
    assert "Settings -> External Tools" in availability.install_help_text


def test_sync_tool_availability_blocks_missing_ffmpeg_only() -> None:
    availability = SyncToolAvailability(
        missing_ffmpeg=True,
        missing_fpcalc=False,
        can_download=True,
    )

    assert availability.has_missing is True
    assert availability.can_continue_without_download is False
    assert availability.tool_names == ("FFmpeg/ffprobe",)


def test_check_sync_tool_availability_uses_configured_paths(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_ffmpeg_available(path: str) -> bool:
        seen["ffmpeg"] = path
        return path == "ffmpeg-ok"

    def fake_fpcalc_available(path: str) -> bool:
        seen["fpcalc"] = path
        return path == "fpcalc-ok"

    monkeypatch.setattr(
        "iopenpod.sync.transcoder.is_ffmpeg_available",
        fake_ffmpeg_available,
    )
    monkeypatch.setattr(
        "iopenpod.sync.audio_fingerprint.is_fpcalc_available",
        fake_fpcalc_available,
    )
    monkeypatch.setattr(
        "iopenpod.sync.dependency_manager.is_platform_supported",
        lambda: False,
    )

    settings = AppSettings()
    settings.ffmpeg_path = "missing-ffmpeg"
    settings.fpcalc_path = "fpcalc-ok"

    availability = check_sync_tool_availability(settings)

    assert availability.missing_ffmpeg is True
    assert availability.missing_fpcalc is False
    assert availability.can_download is False
    assert seen == {"ffmpeg": "missing-ffmpeg", "fpcalc": "fpcalc-ok"}


def test_sync_execute_worker_blocks_missing_required_tools(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "iopenpod.application.jobs.check_sync_tool_availability",
        lambda _settings: SyncToolAvailability(
            missing_ffmpeg=True,
            missing_fpcalc=False,
            can_download=False,
        ),
    )

    worker = SyncExecuteWorker(
        str(tmp_path),
        SimpleNamespace(),
        settings=AppSettings(),
    )
    errors: list[str] = []
    worker.error.connect(errors.append)

    worker.run()

    assert len(errors) == 1
    assert "FFmpeg/ffprobe required before sync" in errors[0]


def test_drop_scan_worker_matches_existing_ipod_tracks_for_playlist_import(
    monkeypatch,
    tmp_path,
) -> None:
    from iopenpod.sync import _db_io, audio_fingerprint
    from iopenpod.sync import mapping as mapping_module
    from iopenpod.sync.pc_library import PCLibrary

    source = tmp_path / "song.mp3"
    playlist = tmp_path / "mix.m3u8"
    ipod_root = tmp_path / "ipod"
    ipod_track = ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    ipod_track.parent.mkdir(parents=True)
    source.write_bytes(b"pc audio")
    ipod_track.write_bytes(b"ipod audio")
    playlist.write_text(str(source), encoding="utf-8")
    fresh_tracks = [
        {
            "db_track_id": 888,
            "Title": "Song",
            "Artist": "Artist",
            "Album": "Album",
            "Location": ":iPod_Control:Music:F00:Song.mp3",
            "length": 1000,
            "track_number": 1,
            "disc_number": 1,
        }
    ]
    fresh_playlists = [
        {
            "playlist_id": 222,
            "Title": "Mix",
            "items": [],
        }
    ]

    class _MappingManager:
        def __init__(self, _ipod_path: str) -> None:
            pass

        def load(self) -> object:
            return SimpleNamespace(get_entries=lambda _fingerprint: [])

    monkeypatch.setattr(
        audio_fingerprint,
        "get_or_compute_fingerprint_with_status",
        lambda path, *_args, **_kwargs: (
            ("fp-song", "computed")
            if Path(path) in {source, ipod_track}
            else (None, "failed")
        ),
    )
    monkeypatch.setattr(
        PCLibrary,
        "_read_track",
        lambda _self, path: SimpleNamespace(
            path=str(path),
            relative_path=Path(path).name,
            filename=Path(path).name,
            size=5,
            artist="Artist",
            album="Album",
            title="Song",
            extension="mp3",
            is_video=False,
            is_podcast=False,
            track_number=1,
            disc_number=1,
            duration_ms=1000,
        ),
    )
    monkeypatch.setattr(mapping_module, "MappingManager", _MappingManager)
    monkeypatch.setattr(
        _db_io,
        "read_existing_database",
        lambda _ipod_path: {
            "tracks": fresh_tracks,
            "dataset2_standard_playlists": fresh_playlists,
        },
    )

    results = []
    worker = DropScanWorker(
        [],
        playlist_paths=[playlist],
        ipod_path=str(ipod_root),
    )
    worker.finished.connect(results.append)
    worker.run()

    assert len(results) == 1
    plan = results[0]
    assert plan.to_add == []
    assert plan.matched_pc_paths == {888: str(source)}
    assert plan.playlists_to_add == []
    assert len(plan.playlists_to_edit) == 1
    assert plan.playlists_to_edit[0]["playlist_id"] == 222
    assert plan.playlists_to_edit[0]["items"] == [{"source_path": str(source)}]


def test_drop_scan_worker_matches_ipod_file_fingerprint_without_readding(
    monkeypatch,
    tmp_path,
) -> None:
    from iopenpod.sync import _db_io, audio_fingerprint
    from iopenpod.sync import mapping as mapping_module
    from iopenpod.sync.pc_library import PCLibrary

    playlist = tmp_path / "mix.m3u8"
    ipod_root = tmp_path / "ipod"
    ipod_track = ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    ipod_track.parent.mkdir(parents=True)
    ipod_track.write_bytes(b"ipod audio")
    playlist.write_text(str(ipod_track), encoding="utf-8")
    fresh_tracks = [
        {
            "db_track_id": 888,
            "Title": "Song",
            "Location": ":iPod_Control:Music:F00:Song.mp3",
            "Artist": "Artist",
            "Album": "Album",
            "length": 1000,
            "track_number": 1,
            "disc_number": 1,
        }
    ]
    fresh_playlists = [
        {
            "playlist_id": 222,
            "Title": "Mix",
            "items": [],
        }
    ]

    class _MappingManager:
        def __init__(self, _ipod_path: str) -> None:
            pass

        def load(self) -> object:
            return SimpleNamespace(get_entries=lambda _fingerprint: [])

    fingerprinted_paths: list[Path] = []

    def fake_fingerprint(path, *_args, **_kwargs):
        fingerprinted_paths.append(Path(path))
        fingerprint = "fp-song" if Path(path) == ipod_track else None
        return fingerprint, "computed" if fingerprint else "failed"

    monkeypatch.setattr(
        audio_fingerprint,
        "get_or_compute_fingerprint_with_status",
        fake_fingerprint,
    )
    monkeypatch.setattr(
        PCLibrary,
        "_read_track",
        lambda _self, path: SimpleNamespace(
            path=str(path),
            relative_path=Path(path).name,
            filename=Path(path).name,
            size=5,
            artist="Artist",
            album="Album",
            title="Song",
            extension="mp3",
            is_video=False,
            is_podcast=False,
            track_number=1,
            disc_number=1,
            duration_ms=1000,
        ),
    )
    monkeypatch.setattr(mapping_module, "MappingManager", _MappingManager)
    monkeypatch.setattr(
        _db_io,
        "read_existing_database",
        lambda _ipod_path: {
            "tracks": fresh_tracks,
            "dataset2_standard_playlists": fresh_playlists,
        },
    )

    results = []
    worker = DropScanWorker(
        [],
        playlist_paths=[playlist],
        ipod_path=str(ipod_root),
    )
    worker.finished.connect(results.append)
    worker.run()

    assert len(results) == 1
    plan = results[0]
    assert plan.to_add == []
    assert ipod_track in fingerprinted_paths
    assert plan.matched_pc_paths == {888: str(ipod_track)}
    assert plan.playlists_to_add == []
    assert len(plan.playlists_to_edit) == 1
    assert plan.playlists_to_edit[0]["playlist_id"] == 222
    assert plan.playlists_to_edit[0]["items"] == [{"source_path": str(ipod_track)}]


def test_drop_scan_worker_does_not_scan_entire_ipod_for_unmatched_new_track(
    monkeypatch,
    tmp_path,
) -> None:
    from iopenpod.sync import _db_io, audio_fingerprint
    from iopenpod.sync import mapping as mapping_module
    from iopenpod.sync.pc_library import PCLibrary

    source = tmp_path / "new-song.mp3"
    ipod_root = tmp_path / "ipod"
    ipod_track = ipod_root / "iPod_Control" / "Music" / "F00" / "Old.mp3"
    ipod_track.parent.mkdir(parents=True)
    source.write_bytes(b"new audio")
    ipod_track.write_bytes(b"old audio")

    class _MappingManager:
        def __init__(self, _ipod_path: str) -> None:
            pass

        def load(self) -> object:
            return SimpleNamespace(get_entries=lambda _fingerprint: [])

    fingerprinted_paths: list[Path] = []

    def fake_fingerprint(path, *_args, **_kwargs):
        fingerprinted_paths.append(Path(path))
        return ("fp-new" if Path(path) == source else "fp-old"), "computed"

    monkeypatch.setattr(
        audio_fingerprint,
        "get_or_compute_fingerprint_with_status",
        fake_fingerprint,
    )
    monkeypatch.setattr(
        PCLibrary,
        "_read_track",
        lambda _self, path: SimpleNamespace(
            path=str(path),
            relative_path=Path(path).name,
            filename=Path(path).name,
            size=5,
            artist="New Artist",
            album="New Album",
            title="New Song",
            extension="mp3",
            is_video=False,
            is_podcast=False,
            track_number=1,
            disc_number=1,
            duration_ms=1000,
        ),
    )
    monkeypatch.setattr(mapping_module, "MappingManager", _MappingManager)
    monkeypatch.setattr(
        _db_io,
        "read_existing_database",
        lambda _ipod_path: {
            "tracks": [
                {
                    "db_track_id": 888,
                    "Title": "Old Song",
                    "Artist": "Old Artist",
                    "Album": "Old Album",
                    "Location": ":iPod_Control:Music:F00:Old.mp3",
                    "length": 1000,
                    "track_number": 1,
                    "disc_number": 1,
                }
            ],
            "dataset2_standard_playlists": [],
        },
    )

    results = []
    errors: list[str] = []
    worker = DropScanWorker([source], ipod_path=str(ipod_root))
    worker.finished.connect(results.append)
    worker.error.connect(errors.append)
    worker.run()

    assert errors == []
    assert len(results) == 1
    assert len(results[0].to_add) == 1
    assert results[0].to_add[0].pc_track.title == "New Song"
    assert fingerprinted_paths == [source]
