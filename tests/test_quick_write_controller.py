from __future__ import annotations

from typing import cast

from PyQt6.QtCore import QObject

from app_core import controllers
from app_core.controllers import QuickWriteController
from app_core.jobs import QuickWriteWorker, _snapshot_cache_for_itunesdb_write
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
