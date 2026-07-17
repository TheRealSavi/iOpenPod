from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from PyQt6.QtCore import QObject, QTimer

from iopenpod.application import controllers
from iopenpod.application.controllers import QuickWriteController
from iopenpod.application.jobs import (
    EjectDeviceWorker,
    PlaylistImportWorker,
    QuickWriteWorker,
    _snapshot_cache_for_itunesdb_write,
)
from iopenpod.application.services import (
    DeviceManagerLike,
    DeviceStorageSnapshot,
    LibraryCacheLike,
)
from iopenpod.device.write_guard import DatabaseGeneration
from iopenpod.sync.core.models import EngineRequest
from iopenpod.sync.quick_writes import QuickWriteResult


class _FakeCache:
    def __init__(self) -> None:
        self.committed = 0
        self.discarded = 0
        self.invalidated = 0
        self.loaded = 0
        self.revision = 1
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

    def get_tracks(self) -> list[dict]:
        return []

    def get_playlists(self) -> list[dict]:
        return []

    def capture_quick_write_state(self) -> SimpleNamespace:
        return SimpleNamespace(
            tracks=self.get_tracks(),
            playlists=self.get_playlists(),
            track_edits={},
            artwork_sources=self.get_track_artwork_edits(),
            revision=self.revision,
        )

    def has_pending_playlists(self) -> bool:
        return bool(self._pending)

    def get_user_playlists(self) -> list[dict]:
        return list(self._pending)


class _FakeDeviceManager:
    def __init__(self) -> None:
        self.device_path = "/fake/ipod"
        self.discovered_ipod: object | None = None


class _WorkerCache:
    def __init__(self, artwork_edits: dict[int, str] | None = None) -> None:
        self.commit_count = 0
        self.reload_count = 0
        self._artwork_edits = artwork_edits or {}
        self.revision = 1

    def get_tracks(self) -> list[dict]:
        return [{"track_id": 1, "db_track_id": 100, "Title": "Song"}]

    def get_playlists(self) -> list[dict]:
        return [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}]

    def get_track_artwork_edits(self) -> dict[int, str]:
        return dict(self._artwork_edits)

    def get_quick_write_revision(self) -> int:
        return self.revision

    def commit_quick_write_state(self, expected_revision: int) -> bool:
        if expected_revision != self.revision:
            return False
        self.commit_count += 1
        return True

    def reload_after_itunesdb_write(self) -> None:
        self.reload_count += 1


def _run_quick_write_worker(
    monkeypatch,
    cache: _WorkerCache,
    result: QuickWriteResult,
) -> None:
    from iopenpod.sync import quick_writes

    monkeypatch.setattr(
        quick_writes,
        "write_cached_itunesdb",
        lambda *_args, **_kwargs: result,
    )
    worker = QuickWriteWorker("/fake/ipod", cast(LibraryCacheLike, cache))
    worker.run()


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


def test_quick_write_done_keeps_saving_status_for_newer_changes() -> None:
    cache = _FakeCache()
    cache._pending.clear()
    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, _FakeDeviceManager()),
        library_cache=cast(LibraryCacheLike, cache),
        is_sync_running=lambda: False,
    )
    controller._quick_worker = cast(controllers.QuickWriteWorker, _FakeWorker())
    statuses: list[str] = []
    timer_starts: list[int] = []
    controller._metadata_timer = cast(
        QTimer,
        SimpleNamespace(start=timer_starts.append),
    )
    controller.save_status_changed.connect(statuses.append)

    controller._on_quick_write_done(
        QuickWriteResult(success=True, newer_changes_pending=True)
    )

    assert statuses == ["saving"]
    assert timer_starts == [0]
    assert controller._force_snapshot_write is True


def test_forced_snapshot_write_starts_without_staged_rows(monkeypatch) -> None:
    created: dict[str, object] = {}

    class _Signal:
        def connect(self, _callback) -> None:
            pass

    class _QuickWriteWorker:
        def __init__(self, ipod_path: str, cache) -> None:
            created["ipod_path"] = ipod_path
            created["cache"] = cache
            self.completed = _Signal()
            self.error = _Signal()

        def start(self) -> None:
            created["started"] = True

    monkeypatch.setattr(controllers, "QuickWriteWorker", _QuickWriteWorker)
    cache = _FakeCache()
    cache._pending.clear()
    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, _FakeDeviceManager()),
        library_cache=cast(LibraryCacheLike, cache),
        is_sync_running=lambda: False,
    )
    controller._force_snapshot_write = True

    controller.start_quick_write()

    assert created["cache"] is cache
    assert created["started"] is True
    assert controller._force_snapshot_write is False


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


def test_quick_write_controller_passes_scan_time_storage_snapshot(monkeypatch) -> None:
    created: dict[str, object] = {}

    class _Signal:
        def connect(self, _callback) -> None:
            pass

    class _QuickWriteWorker:
        def __init__(self, **kwargs) -> None:
            created.update(kwargs)
            self.completed = _Signal()
            self.error = _Signal()

        def start(self) -> None:
            created["started"] = True

    manager = _FakeDeviceManager()
    manager.discovered_ipod = SimpleNamespace(
        reported_volume_format="win",
        filesystem_type="vfat",
        max_file_size_gb=4,
        volume_identity_key="scan-volume",
    )
    monkeypatch.setattr(controllers, "QuickWriteWorker", _QuickWriteWorker)

    controller = QuickWriteController(
        device_manager=cast(DeviceManagerLike, manager),
        library_cache=cast(LibraryCacheLike, _FakeCache()),
        is_sync_running=lambda: False,
    )
    controller.start_quick_write()

    storage = created["device_storage"]
    assert isinstance(storage, DeviceStorageSnapshot)
    assert storage.reported_volume_format == "win"
    assert storage.volume_identity_key == "scan-volume"


def test_engine_quick_write_passes_device_storage_to_request(monkeypatch) -> None:
    from iopenpod.application import jobs
    from iopenpod.sync.core import SyncEngine

    storage = DeviceStorageSnapshot("win", "vfat", None, "scan-volume")
    requests: list[EngineRequest] = []
    monkeypatch.setattr(
        SyncEngine,
        "quick_write",
        lambda _self, request: requests.append(request) or object(),
    )

    jobs._engine_quick_write(
        "/fake/ipod",
        tracks_data=[],
        playlists_data=[],
        artwork_sources={},
        device_storage=storage,
    )

    assert requests[0].device_storage is storage


def test_eject_worker_passes_scan_time_filesystem_facts(monkeypatch) -> None:
    from iopenpod.device import eject

    captured: dict[str, object] = {}
    storage = DeviceStorageSnapshot("win", "vfat", None, "scan-volume")
    monkeypatch.setattr(
        eject,
        "eject_ipod",
        lambda path, **kwargs: captured.update(path=path, **kwargs) or (True, "ok"),
    )
    messages: list[str] = []
    worker = EjectDeviceWorker("/fake/ipod", device_storage=storage)
    worker.finished_ok.connect(messages.append)

    worker.run()

    assert captured == {
        "path": "/fake/ipod",
        "reported_volume_format": "win",
        "expected_volume_identity_key": "scan-volume",
    }
    assert messages == ["ok"]


def test_otg_cleanup_is_guarded_identity_checked_and_durable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from iopenpod.application import jobs
    from iopenpod.device import durability, write_readiness

    otg_path = tmp_path / "iPod_Control" / "iTunes" / "OTGPlaylistInfo"
    otg_path.parent.mkdir(parents=True)
    otg_path.write_bytes(b"mhpo")
    profile = SimpleNamespace()
    events: list[object] = []

    class _Guard:
        def __init__(self, path, **kwargs) -> None:
            events.append(("guard", Path(path), kwargs))

        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, *_args) -> None:
            events.append("exit")

        def assert_database_unchanged(self) -> None:
            events.append("generation-check")

    monkeypatch.setattr(jobs, "DeviceWriteGuard", _Guard)
    monkeypatch.setattr(
        write_readiness,
        "inspect_device_write_readiness",
        lambda *_args, **_kwargs: profile,
    )
    monkeypatch.setattr(
        write_readiness,
        "volume_lock_key",
        lambda _profile: "scan-volume",
    )
    monkeypatch.setattr(
        write_readiness,
        "revalidate_device_write_readiness",
        lambda retained, **kwargs: events.append(("revalidate", kwargs)) or retained,
    )
    monkeypatch.setattr(
        durability,
        "durable_unlink",
        lambda path: events.append(("unlink", Path(path))),
    )
    monkeypatch.setattr(
        durability,
        "flush_filesystem",
        lambda path: events.append(("flush", Path(path))) or (True, "ok"),
    )
    generation = DatabaseGeneration("iTunesDB", True)
    storage = DeviceStorageSnapshot("win", "vfat", None, "scan-volume")

    jobs._delete_imported_otg_files(
        str(tmp_path),
        device_storage=storage,
        expected_database_generation=generation,
    )

    assert events[0] == (
        "guard",
        tmp_path,
        {
            "volume_key": "scan-volume",
            "expected_database_generation": generation,
        },
    )
    assert ("unlink", otg_path) in events
    assert events.index("generation-check") < events.index(("unlink", otg_path))
    assert ("flush", tmp_path) in events
    assert events[-1] == "exit"


def test_otg_cleanup_does_not_swallow_durability_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from iopenpod.application import jobs
    from iopenpod.device import durability, write_readiness

    otg_path = tmp_path / "iPod_Control" / "iTunes" / "OTGPlaylistInfo"
    otg_path.parent.mkdir(parents=True)
    otg_path.write_bytes(b"mhpo")
    profile = SimpleNamespace()

    class _Guard:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def assert_database_unchanged(self) -> None:
            pass

    monkeypatch.setattr(jobs, "DeviceWriteGuard", _Guard)
    monkeypatch.setattr(
        write_readiness,
        "inspect_device_write_readiness",
        lambda *_args, **_kwargs: profile,
    )
    monkeypatch.setattr(
        write_readiness,
        "volume_lock_key",
        lambda _profile: "scan-volume",
    )
    monkeypatch.setattr(
        write_readiness,
        "revalidate_device_write_readiness",
        lambda retained, **_kwargs: retained,
    )

    def fail_unlink(_path: object) -> None:
        raise OSError("unlink failed")

    monkeypatch.setattr(
        durability,
        "durable_unlink",
        fail_unlink,
    )

    with pytest.raises(OSError, match="unlink failed"):
        jobs._delete_imported_otg_files(str(tmp_path))


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


def test_quick_write_worker_commits_cache_in_place_after_write(monkeypatch) -> None:
    cache = _WorkerCache()
    _run_quick_write_worker(monkeypatch, cache, QuickWriteResult(success=True))

    assert cache.commit_count == 1
    assert cache.reload_count == 0


def test_quick_write_worker_reloads_cache_when_artwork_changed(monkeypatch) -> None:
    cache = _WorkerCache({100: "/tmp/new-cover.png"})
    _run_quick_write_worker(monkeypatch, cache, QuickWriteResult(success=True))

    assert cache.commit_count == 0
    assert cache.reload_count == 1


def test_quick_write_worker_reloads_cache_after_failed_write(monkeypatch) -> None:
    cache = _WorkerCache()
    _run_quick_write_worker(
        monkeypatch,
        cache,
        QuickWriteResult(
            success=False,
            errors=[("quick_write", "Database write failed")],
        ),
    )

    assert cache.commit_count == 0
    assert cache.reload_count == 1


def test_quick_write_worker_reports_newer_staged_changes(monkeypatch) -> None:
    from iopenpod.sync import quick_writes

    cache = _WorkerCache()
    result = QuickWriteResult(success=True)
    monkeypatch.setattr(
        quick_writes,
        "write_cached_itunesdb",
        lambda *_args, **_kwargs: result,
    )
    worker = QuickWriteWorker("/fake/ipod", cast(LibraryCacheLike, cache))
    cache.revision += 1

    worker.run()

    assert result.newer_changes_pending is True
    assert cache.commit_count == 0


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
    from iopenpod.application import jobs
    from iopenpod.sync import _db_io, audio_fingerprint
    from iopenpod.sync import mapping as mapping_module
    from iopenpod.sync.pc_library import PCLibrary

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
    from iopenpod.application import jobs
    from iopenpod.sync import _db_io, audio_fingerprint
    from iopenpod.sync import mapping as mapping_module
    from iopenpod.sync.pc_library import PCLibrary

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
    from iopenpod.application import jobs
    from iopenpod.sync import _db_io, audio_fingerprint
    from iopenpod.sync import mapping as mapping_module
    from iopenpod.sync.core import SyncEngine as CoreSyncEngine
    from iopenpod.sync.pc_library import PCLibrary

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
    from iopenpod.application import jobs
    from iopenpod.sync import _db_io, audio_fingerprint
    from iopenpod.sync import mapping as mapping_module
    from iopenpod.sync.core import SyncEngine as CoreSyncEngine
    from iopenpod.sync.pc_library import PCLibrary

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
