from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from PyQt6.QtCore import QObject

from app_core import controllers
from app_core.controllers import QuickWriteController
from app_core.jobs import (
    PlaylistImportWorker,
    QuickWriteWorker,
    _snapshot_cache_for_itunesdb_write,
)
from app_core.services import DeviceManagerLike, LibraryCacheLike
from SyncEngine.quick_writes import QuickWriteResult


class _FakeCache:
    def __init__(self) -> None:
        self.committed = 0
        self.discarded = 0
        self.invalidated = 0
        self.loaded = 0
        self._track_edits: dict[int, dict[str, tuple[object, object]]] = {}
        self._artwork_edits: dict[int, str] = {}
        self._pending = [{"playlist_id": 123, "Title": "Pending"}]

    def commit_user_playlists(self) -> None:
        self.committed += 1

    def reload_after_itunesdb_write(self) -> None:
        self.discard_quick_write_state()
        self.invalidate()
        self.start_loading()

    def discard_quick_write_state(self) -> None:
        self.discarded += 1
        self._track_edits.clear()
        self._artwork_edits.clear()
        self._pending.clear()

    def invalidate(self) -> None:
        self.invalidated += 1

    def start_loading(self) -> None:
        self.loaded += 1

    def has_pending_track_edits(self) -> bool:
        return bool(self._track_edits) or bool(self._artwork_edits)

    def get_track_edits(self) -> dict[int, dict[str, tuple[object, object]]]:
        return dict(self._track_edits)

    def get_track_artwork_edits(self) -> dict[int, str]:
        return dict(self._artwork_edits)

    def has_pending_playlists(self) -> bool:
        return bool(self._pending)

    def get_user_playlists(self) -> list[dict]:
        return list(self._pending)


class _FakeDeviceManager:
    def __init__(self) -> None:
        self.device_path = "/fake/ipod"


class _FakeWorker(QObject):
    def wait(self, _timeout_ms: int | None = None) -> bool:
        return True

    def deleteLater(self) -> None:
        pass


def test_quick_playlist_done_does_not_reload_in_controller() -> None:
    cache = _FakeCache()
    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, _FakeDeviceManager()),
        library_cache=cast(LibraryCacheLike, cache),
        is_sync_running=lambda: False,
    )
    controller._quick_worker = cast(controllers.QuickWriteWorker, _FakeWorker())

    class _Result:
        success = True
        errors: list[tuple[str, str]] = []

    controller._on_quick_write_done(_Result())

    assert cache.committed == 0
    assert cache.discarded == 0
    assert cache.invalidated == 0
    assert cache.loaded == 0
    assert controller._quick_worker is None


def test_start_playlist_sync_does_not_clear_pending_before_success(monkeypatch) -> None:
    created: dict[str, object] = {}

    class _FakeSignal:
        def connect(self, _callback) -> None:
            pass

    class _FakeQuickWriteWorker:
        def __init__(
            self,
            ipod_path: str,
            cache=None,
        ) -> None:
            created["ipod_path"] = ipod_path
            created["cache"] = cache
            self.completed = _FakeSignal()
            self.error = _FakeSignal()

        def isRunning(self) -> bool:
            return False

        def start(self) -> None:
            created["started"] = True

    monkeypatch.setattr(controllers, "QuickWriteWorker", _FakeQuickWriteWorker)

    cache = _FakeCache()
    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, _FakeDeviceManager()),
        library_cache=cast(LibraryCacheLike, cache),
        is_sync_running=lambda: False,
    )

    controller.start_playlist_sync()

    assert created["ipod_path"] == "/fake/ipod"
    assert created["cache"] is cache
    assert created["started"] is True
    assert cache.has_pending_playlists()


def test_start_quick_write_combines_track_and_playlist_edits(monkeypatch) -> None:
    created: dict[str, object] = {}

    class _FakeSignal:
        def connect(self, _callback) -> None:
            pass

    class _FakeQuickWriteWorker:
        def __init__(
            self,
            ipod_path: str,
            cache=None,
        ) -> None:
            created["ipod_path"] = ipod_path
            created["cache"] = cache
            self.completed = _FakeSignal()
            self.error = _FakeSignal()

        def isRunning(self) -> bool:
            return False

        def start(self) -> None:
            created["started"] = True

    monkeypatch.setattr(controllers, "QuickWriteWorker", _FakeQuickWriteWorker)

    cache = _FakeCache()
    cache._track_edits = {100: {"Title": ("Old", "New")}}
    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, _FakeDeviceManager()),
        library_cache=cast(LibraryCacheLike, cache),
        is_sync_running=lambda: False,
    )

    controller.start_quick_write()

    assert created["cache"] is cache
    assert created["started"] is True


def test_prepare_for_full_sync_flushes_pending_quick_write(monkeypatch) -> None:
    created: dict[str, object] = {}

    class _FakeSignal:
        def connect(self, _callback) -> None:
            pass

    class _FakeQuickWriteWorker:
        def __init__(self, ipod_path: str, cache=None) -> None:
            created["ipod_path"] = ipod_path
            created["cache"] = cache
            self.completed = _FakeSignal()
            self.error = _FakeSignal()

        def isRunning(self) -> bool:
            return False

        def start(self) -> None:
            created["started"] = True

        def wait(self, _timeout_ms: int | None = None) -> bool:
            return True

    monkeypatch.setattr(controllers, "QuickWriteWorker", _FakeQuickWriteWorker)

    cache = _FakeCache()
    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, _FakeDeviceManager()),
        library_cache=cast(LibraryCacheLike, cache),
        is_sync_running=lambda: False,
    )

    assert controller.prepare_for_full_sync() == (True, None)
    assert created["ipod_path"] == "/fake/ipod"
    assert created["cache"] is cache
    assert created["started"] is True


def test_prepare_for_full_sync_reports_blocked_quick_write() -> None:
    class _HungWorker:
        def isRunning(self) -> bool:
            return True

        def wait(self, _timeout_ms: int | None = None) -> bool:
            return False

    cache = _FakeCache()
    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, _FakeDeviceManager()),
        library_cache=cast(LibraryCacheLike, cache),
        is_sync_running=lambda: False,
    )
    controller._quick_worker = cast(controllers.QuickWriteWorker, _HungWorker())

    assert controller.prepare_for_full_sync() == (False, "quick changes")


def test_artwork_edits_start_itunesdb_quick_write(monkeypatch) -> None:
    created: dict[str, object] = {}

    class _FakeSignal:
        def connect(self, _callback) -> None:
            pass

    class _FakeQuickWriteWorker:
        def __init__(self, *args, **kwargs) -> None:
            created["worker"] = (args, kwargs)
            self.completed = _FakeSignal()
            self.error = _FakeSignal()

        def isRunning(self) -> bool:
            return False

        def start(self) -> None:
            created["started"] = True

    monkeypatch.setattr(controllers, "QuickWriteWorker", _FakeQuickWriteWorker)

    cache = _FakeCache()
    cache._pending.clear()
    cache._artwork_edits = {100: "/tmp/iopenpod-artwork-test.png"}
    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, _FakeDeviceManager()),
        library_cache=cast(LibraryCacheLike, cache),
        is_sync_running=lambda: False,
    )

    controller.start_quick_write()

    assert "worker" in created
    assert created.get("started") is True


def test_quick_write_failure_discards_and_reloads() -> None:
    cache = _FakeCache()
    cache._track_edits = {100: {"Title": ("Old", "New")}}
    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, _FakeDeviceManager()),
        library_cache=cast(LibraryCacheLike, cache),
        is_sync_running=lambda: False,
    )

    class _Result:
        success = False
        errors = [("quick_write", "Database write failed")]

    controller._on_quick_write_done(_Result())

    assert cache.discarded == 0
    assert cache.invalidated == 0
    assert cache.loaded == 0


def test_quick_write_worker_reloads_cache_after_write(monkeypatch) -> None:
    from SyncEngine import quick_writes

    class _WorkerCache:
        def __init__(self) -> None:
            self.loaded = 0

        def get_tracks(self) -> list[dict]:
            return [{"track_id": 1, "db_track_id": 100, "Title": "Song"}]

        def get_playlists(self) -> list[dict]:
            return [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}]

        def get_track_artwork_edits(self) -> dict[int, str]:
            return {}

        def reload_after_itunesdb_write(self) -> None:
            self.loaded += 1

    cache = _WorkerCache()

    monkeypatch.setattr(
        quick_writes,
        "write_cached_itunesdb",
        lambda *_args, **_kwargs: QuickWriteResult(success=True),
    )

    worker = QuickWriteWorker("/fake/ipod", cast(LibraryCacheLike, cache))
    worker.run()

    assert cache.loaded == 1


def test_snapshot_uses_artwork_edit_map_and_strips_pending_marker() -> None:
    class _Cache:
        def get_tracks(self) -> list[dict]:
            return [
                {
                    "db_track_id": 100,
                    "Title": "Song",
                    "_iop_pending_artwork_path": "/tmp/marker.png",
                }
            ]

        def get_playlists(self) -> list[dict]:
            return [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}]

        def get_track_artwork_edits(self) -> dict[int, str]:
            return {100: "/tmp/cache.png"}

    tracks, playlists, artwork_sources = _snapshot_cache_for_itunesdb_write(
        cast(LibraryCacheLike, _Cache())
    )

    assert "_iop_pending_artwork_path" not in tracks[0]
    assert playlists == [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}]
    assert artwork_sources == {100: "/tmp/cache.png"}


def test_snapshot_applies_pending_track_edits_to_copied_tracks() -> None:
    class _Cache:
        def get_tracks(self) -> list[dict]:
            return [{"db_track_id": 100, "Title": "Song", "rating": 40}]

        def get_playlists(self) -> list[dict]:
            return [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}]

        def get_track_edits(self) -> dict[int, dict[str, tuple[object, object]]]:
            return {100: {"rating": (40, 100)}}

        def get_track_artwork_edits(self) -> dict[int, str]:
            return {}

    tracks, _playlists, _artwork_sources = _snapshot_cache_for_itunesdb_write(
        cast(LibraryCacheLike, _Cache())
    )

    assert tracks == [{"db_track_id": 100, "Title": "Song", "rating": 100}]


def test_playlist_import_refreshes_tracks_for_already_present_fingerprints(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app_core import jobs
    from SyncEngine import _db_io, audio_fingerprint
    from SyncEngine import mapping as mapping_module
    from SyncEngine.pc_library import PCLibrary

    source = tmp_path / "song.mp3"
    playlist = tmp_path / "mix.m3u8"
    source.write_bytes(b"audio")
    playlist.write_text(str(source), encoding="utf-8")
    fresh_tracks = [{"db_track_id": 777, "Title": "Fresh Song"}]
    captured: dict[str, object] = {}

    class _Cache:
        def __init__(self) -> None:
            self.playlists: list[dict] = []
            self.reloads = 0

        def get_track_id_index(self) -> dict[int, dict]:
            return {}

        def get_tracks(self) -> list[dict]:
            return [{"db_track_id": 111, "Title": "Stale Cache Song"}]

        def get_playlists(self) -> list[dict]:
            return list(self.playlists)

        def get_track_artwork_edits(self) -> dict[int, str]:
            return {}

        def save_user_playlist(self, playlist: dict) -> None:
            self.playlists.append(playlist)

        def reload_after_itunesdb_write(self) -> None:
            self.reloads += 1

    class _MappingManager:
        def __init__(self, _ipod_path: str) -> None:
            pass

        def load(self) -> object:
            return SimpleNamespace(
                get_entries=lambda fingerprint: [
                    SimpleNamespace(db_track_id=777)
                ]
                if fingerprint == "fp-song"
                else []
            )

    def fake_quick_write(_ipod_path: str, **kwargs):
        captured.update(kwargs)
        return QuickWriteResult(success=True, playlist_counts={})

    monkeypatch.setattr(
        audio_fingerprint,
        "get_or_compute_fingerprint_with_status",
        lambda *_args, **_kwargs: ("fp-song", "computed"),
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
        lambda _ipod_path: {"tracks": fresh_tracks},
    )
    monkeypatch.setattr(jobs, "_engine_quick_write", fake_quick_write)

    cache = _Cache()
    worker = PlaylistImportWorker(
        str(playlist),
        str(tmp_path / "ipod"),
        "",
        cast(LibraryCacheLike, cache),
    )

    worker.run()

    assert captured["tracks_data"] == fresh_tracks
    written_playlists = captured["playlists_data"]
    assert isinstance(written_playlists, list)
    assert written_playlists[0]["items"] == [{"db_track_id": 777}]
    assert cache.reloads == 1


def test_playlist_import_merges_same_name_playlist_without_duplicate_members(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app_core import jobs
    from SyncEngine import _db_io, audio_fingerprint
    from SyncEngine import mapping as mapping_module
    from SyncEngine.pc_library import PCLibrary

    source = tmp_path / "song.mp3"
    playlist_file = tmp_path / "mix.m3u8"
    source.write_bytes(b"audio")
    playlist_file.write_text(str(source), encoding="utf-8")
    fresh_tracks = [
        {"track_id": 10, "db_track_id": 555, "Title": "Existing"},
        {"track_id": 11, "db_track_id": 777, "Title": "Imported"},
    ]
    captured: dict[str, object] = {}

    class _Cache:
        def __init__(self) -> None:
            self.saved: list[dict] = []

        def get_track_id_index(self) -> dict[int, dict]:
            return {}

        def get_tracks(self) -> list[dict]:
            return []

        def get_playlists(self) -> list[dict]:
            if self.saved:
                return list(self.saved)
            return [
                {
                    "playlist_id": 222,
                    "Title": "Mix",
                    "_mhsd_dataset_type": 2,
                    "items": [{"track_id": 10}],
                }
            ]

        def get_track_artwork_edits(self) -> dict[int, str]:
            return {}

        def save_user_playlist(self, playlist: dict) -> None:
            self.saved = [playlist]

        def reload_after_itunesdb_write(self) -> None:
            pass

    class _MappingManager:
        def __init__(self, _ipod_path: str) -> None:
            pass

        def load(self) -> object:
            return SimpleNamespace(
                get_entries=lambda fingerprint: [
                    SimpleNamespace(db_track_id=777)
                ]
                if fingerprint == "fp-song"
                else []
            )

    monkeypatch.setattr(
        audio_fingerprint,
        "get_or_compute_fingerprint_with_status",
        lambda *_args, **_kwargs: ("fp-song", "computed"),
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
            title="Imported",
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
        lambda _ipod_path: {"tracks": fresh_tracks},
    )
    monkeypatch.setattr(
        jobs,
        "_engine_quick_write",
        lambda _ipod_path, **kwargs: (
            captured.update(kwargs) or QuickWriteResult(success=True)
        ),
    )

    cache = _Cache()
    worker = PlaylistImportWorker(
        str(playlist_file),
        str(tmp_path / "ipod"),
        "",
        cast(LibraryCacheLike, cache),
    )

    worker.run()

    written_playlists = captured["playlists_data"]
    assert isinstance(written_playlists, list)
    assert written_playlists[0]["playlist_id"] == 222
    assert written_playlists[0]["_isNew"] is False
    assert written_playlists[0]["items"] == [
        {"track_id": 10},
        {"db_track_id": 777},
    ]


def test_playlist_import_finds_existing_ipod_track_when_mapping_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app_core import jobs
    from SyncEngine import _db_io, audio_fingerprint
    from SyncEngine import mapping as mapping_module
    from SyncEngine.core import SyncEngine as CoreSyncEngine
    from SyncEngine.pc_library import PCLibrary

    source = tmp_path / "song.mp3"
    playlist_file = tmp_path / "mix.m3u8"
    ipod_root = tmp_path / "ipod"
    ipod_track = ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    ipod_track.parent.mkdir(parents=True)
    source.write_bytes(b"pc audio")
    ipod_track.write_bytes(b"ipod audio")
    playlist_file.write_text(str(source), encoding="utf-8")
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
    captured: dict[str, object] = {}
    execute_calls: list[object] = []

    class _Cache:
        def __init__(self) -> None:
            self.playlists: list[dict] = []

        def get_track_id_index(self) -> dict[int, dict]:
            return {}

        def get_tracks(self) -> list[dict]:
            return []

        def get_playlists(self) -> list[dict]:
            return list(self.playlists)

        def get_track_artwork_edits(self) -> dict[int, str]:
            return {}

        def save_user_playlist(self, playlist: dict) -> None:
            self.playlists = [playlist]

        def reload_after_itunesdb_write(self) -> None:
            pass

    class _MappingManager:
        def __init__(self, _ipod_path: str) -> None:
            pass

        def load(self) -> object:
            return SimpleNamespace(get_entries=lambda _fingerprint: [])

    def fake_fingerprint(path, *_args, **_kwargs):
        fingerprint = "fp-song" if Path(path) in {source, ipod_track} else None
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
        lambda _ipod_path: {"tracks": fresh_tracks},
    )
    monkeypatch.setattr(
        CoreSyncEngine,
        "execute_plan",
        lambda _self, request: execute_calls.append(request),
    )
    monkeypatch.setattr(
        jobs,
        "_engine_quick_write",
        lambda _ipod_path, **kwargs: (
            captured.update(kwargs) or QuickWriteResult(success=True)
        ),
    )

    cache = _Cache()
    worker = PlaylistImportWorker(
        str(playlist_file),
        str(ipod_root),
        "",
        cast(LibraryCacheLike, cache),
    )

    worker.run()

    assert execute_calls == []
    written_playlists = captured["playlists_data"]
    assert isinstance(written_playlists, list)
    assert written_playlists[0]["items"] == [{"db_track_id": 888}]


def test_playlist_import_matches_ipod_file_fingerprint_without_readding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app_core import jobs
    from SyncEngine import _db_io, audio_fingerprint
    from SyncEngine import mapping as mapping_module
    from SyncEngine.core import SyncEngine as CoreSyncEngine
    from SyncEngine.pc_library import PCLibrary

    playlist_file = tmp_path / "mix.m3u8"
    ipod_root = tmp_path / "ipod"
    ipod_track = ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    ipod_track.parent.mkdir(parents=True)
    ipod_track.write_bytes(b"ipod audio")
    playlist_file.write_text(str(ipod_track), encoding="utf-8")
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
    captured: dict[str, object] = {}
    execute_calls: list[object] = []
    fingerprinted_paths: list[Path] = []

    class _Cache:
        def __init__(self) -> None:
            self.playlists: list[dict] = []

        def get_track_id_index(self) -> dict[int, dict]:
            return {}

        def get_tracks(self) -> list[dict]:
            return []

        def get_playlists(self) -> list[dict]:
            return list(self.playlists)

        def get_track_artwork_edits(self) -> dict[int, str]:
            return {}

        def save_user_playlist(self, playlist: dict) -> None:
            self.playlists = [playlist]

        def reload_after_itunesdb_write(self) -> None:
            pass

    class _MappingManager:
        def __init__(self, _ipod_path: str) -> None:
            pass

        def load(self) -> object:
            return SimpleNamespace(get_entries=lambda _fingerprint: [])

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
        lambda _ipod_path: {"tracks": fresh_tracks},
    )
    monkeypatch.setattr(
        CoreSyncEngine,
        "execute_plan",
        lambda _self, request: execute_calls.append(request),
    )
    monkeypatch.setattr(
        jobs,
        "_engine_quick_write",
        lambda _ipod_path, **kwargs: (
            captured.update(kwargs) or QuickWriteResult(success=True)
        ),
    )

    cache = _Cache()
    worker = PlaylistImportWorker(
        str(playlist_file),
        str(ipod_root),
        "",
        cast(LibraryCacheLike, cache),
    )

    worker.run()

    assert execute_calls == []
    assert ipod_track in fingerprinted_paths
    written_playlists = captured["playlists_data"]
    assert isinstance(written_playlists, list)
    assert written_playlists[0]["items"] == [{"db_track_id": 888}]
