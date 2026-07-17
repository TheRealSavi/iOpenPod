from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from iopenpod.application.jobs import SyncToolAvailability
from iopenpod.application.services import (
    DeviceManagerLike,
    DeviceSessionService,
    LibraryCacheLike,
    SettingsService,
)
from iopenpod.application.sync_session import (
    PodcastPlanningInput,
    SyncExecutionIntent,
    SyncPlanningIntent,
    SyncSessionBlocked,
    SyncSessionController,
)
from iopenpod.device.write_guard import DatabaseGeneration
from iopenpod.infrastructure.settings_schema import AppSettings
from iopenpod.sync.contracts import StorageSummary, SyncAction, SyncItem, SyncPlan


class _FakeSignal:
    def __init__(self) -> None:
        self.connections: list[Any] = []
        self.disconnect_count = 0

    def connect(self, callback: Any) -> None:
        self.connections.append(callback)

    def disconnect(self) -> None:
        self.disconnect_count += 1

    def emit(self, *args: Any) -> None:
        for callback in list(self.connections):
            callback(*args)


class _FakeWorker:
    def __init__(self, request: Any = None, **kwargs: Any) -> None:
        self.request = request
        self.kwargs = kwargs
        self.progress = _FakeSignal()
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.confirm_partial_save = _FakeSignal()
        self.started = False
        self.interruptions = 0
        self.deleted = False
        self._running = False
        self.partial_save_responses: list[bool] = []
        self.skip_backup_requests = 0
        self.give_up_scrobble_requests = 0

    def start(self) -> None:
        self.started = True
        self._running = True

    def isRunning(self) -> bool:
        return self._running

    def requestInterruption(self) -> None:
        self.interruptions += 1

    def respond_to_partial_save(self, save: bool) -> None:
        self.partial_save_responses.append(save)

    def request_skip_backup(self) -> None:
        self.skip_backup_requests += 1

    def request_give_up_scrobble(self) -> None:
        self.give_up_scrobble_requests += 1

    def wait(self, _timeout_ms: int) -> bool:
        self._running = False
        return True

    def deleteLater(self) -> None:
        self.deleted = True


class _FakeLibraryCache:
    def __init__(self) -> None:
        self.loading = False
        self.tracks = [{"db_track_id": 10, "Title": "iPod Track"}]
        self.track_edits = {10: {"rating": (0, 80)}}
        self.photo_edits = SimpleNamespace(has_changes=True)
        self.playlists = [{"master_flag": True, "Title": "RoadPod"}]
        self.data = {
            "mhlp": [{"Title": "Existing", "_mhsd_dataset_type": 2}],
            "mhlp_podcast": [],
            "mhlp_smart": [],
        }
        self.clear_pending_calls = 0
        self.database_generation = DatabaseGeneration(
            "iTunesDB",
            True,
            digest="loaded",
        )

    def is_loading(self) -> bool:
        return self.loading

    def get_tracks(self) -> list[dict]:
        return list(self.tracks)

    def get_track_edits(self) -> dict:
        return dict(self.track_edits)

    def get_photo_edits(self) -> Any:
        return self.photo_edits

    def get_data(self) -> dict:
        return self.data

    def get_playlists(self) -> list[dict]:
        return list(self.playlists)

    def clear_pending_sync_state(self) -> None:
        self.clear_pending_calls += 1

    def get_database_generation(self) -> DatabaseGeneration:
        return self.database_generation


class _FakeQuickWrites:
    def __init__(self, result: tuple[bool, str | None] = (True, None)) -> None:
        self.result = result
        self.calls = 0

    def prepare_for_full_sync(self) -> tuple[bool, str | None]:
        self.calls += 1
        return self.result


class _FakeSettingsService:
    def __init__(self) -> None:
        self.settings = AppSettings()
        self.settings.sync_workers = 3
        self.settings.rating_conflict_strategy = "pc_wins"
        self.settings.fpcalc_path = "fpcalc-custom"

    def get_effective_settings(self) -> AppSettings:
        return self.settings


class _FakeDeviceSessionService:
    def __init__(self, device_path: str = "/ipod") -> None:
        self.session = SimpleNamespace(
            device_path=device_path,
            identity=SimpleNamespace(model_family="classic"),
            capabilities=SimpleNamespace(
                supports_video=False,
                supports_podcast=True,
                supports_photo=True,
            ),
        )

    def current_session(self) -> Any:
        return self.session


class _FakeDeviceManager:
    def __init__(self, device_path: str = "/ipod") -> None:
        self.device_path = device_path


def _controller(
    *,
    cache: _FakeLibraryCache | None = None,
    device_path: str = "/ipod",
    quick_writes: _FakeQuickWrites | None = None,
    tool_availability: SyncToolAvailability | None = None,
    podcast_input_provider: Any = None,
) -> SyncSessionController:
    return SyncSessionController(
        cast(DeviceManagerLike, _FakeDeviceManager(device_path)),
        cast(LibraryCacheLike, cache or _FakeLibraryCache()),
        cast(SettingsService, _FakeSettingsService()),
        cast(DeviceSessionService, _FakeDeviceSessionService(device_path)),
        quick_writes or _FakeQuickWrites(),
        podcast_input_provider=podcast_input_provider,
        tool_availability_check=lambda _settings: tool_availability
        or SyncToolAvailability(False, False, False),
    )


def test_start_planning_blocks_when_quick_changes_are_saving(qapp) -> None:
    controller = _controller(quick_writes=_FakeQuickWrites((False, "metadata edits")))
    blocked: list[SyncSessionBlocked] = []
    controller.blocked.connect(blocked.append)

    controller.start_planning(
        SyncPlanningIntent(
            mode="full",
            folder_entries=({"directory": "/music", "recurse": True},),
        )
    )

    assert blocked == [
        SyncSessionBlocked(reason="quick_changes_saving", label="metadata edits")
    ]


def test_start_planning_emits_missing_tools_instead_of_creating_worker(qapp) -> None:
    controller = _controller(
        tool_availability=SyncToolAvailability(
            missing_ffmpeg=True,
            missing_fpcalc=False,
            can_download=True,
        )
    )
    missing: list[Any] = []
    controller.missing_tools.connect(missing.append)

    intent = SyncPlanningIntent(
        mode="full",
        folder_entries=({"directory": "/music", "recurse": True},),
    )
    controller.start_planning(intent)

    assert len(missing) == 1
    assert missing[0].availability.missing_ffmpeg is True
    assert missing[0].planning_intent == intent
    assert controller.is_running() is False


def test_start_execution_emits_missing_tools_instead_of_creating_worker(qapp) -> None:
    controller = _controller(
        tool_availability=SyncToolAvailability(
            missing_ffmpeg=False,
            missing_fpcalc=True,
            can_download=True,
        )
    )
    missing: list[Any] = []
    controller.missing_tools.connect(missing.append)
    intent = SyncExecutionIntent(
        plan=SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)])
    )

    controller.start_execution(intent)

    assert len(missing) == 1
    assert missing[0].availability.missing_fpcalc is True
    assert missing[0].execution_intent == intent
    assert controller.is_running() is False


def test_start_planning_builds_full_sync_request_and_emits_plan_ready(
    qapp,
    monkeypatch,
) -> None:
    workers: list[_FakeWorker] = []

    def fake_worker(request: Any) -> _FakeWorker:
        worker = _FakeWorker(request)
        workers.append(worker)
        return worker

    monkeypatch.setattr("iopenpod.application.sync_session.SyncDiffWorker", fake_worker)
    controller = _controller()
    plans: list[Any] = []
    controller.plan_ready.connect(plans.append)

    controller.start_planning(
        SyncPlanningIntent(
            mode="full",
            folder_entries=({"directory": "/music", "recurse": True},),
        )
    )

    assert len(workers) == 1
    worker = workers[0]
    assert worker.started is True
    assert worker.request.pc_folder == "/music"
    assert worker.request.ipod_path == "/ipod"
    assert worker.request.supports_video is False
    assert worker.request.track_edits == {10: {"rating": (0, 80)}}
    assert worker.request.existing_playlists == (
        {"Title": "Existing", "_mhsd_dataset_type": 2},
    )

    plan = SyncPlan()
    worker.finished.emit(plan)

    assert plans == [plan]
    assert controller.is_running() is False


def test_start_planning_builds_selective_sync_request(
    qapp,
    monkeypatch,
) -> None:
    workers: list[_FakeWorker] = []
    monkeypatch.setattr(
        "iopenpod.application.sync_session.SyncDiffWorker",
        lambda request: workers.append(_FakeWorker(request)) or workers[-1],
    )
    controller = _controller()

    controller.start_planning(
        SyncPlanningIntent(
            mode="selective",
            folder_entries=({"directory": "/music", "recurse": True},),
            selected_paths={
                "tracks": {"/music/song.mp3"},
                "photos": (("/photos/a.jpg", "Album"),),
                "playlists": {"/music/list.m3u"},
            },
        )
    )

    request = workers[0].request
    assert request.allowed_paths == frozenset({"/music/song.mp3"})
    assert request.selected_playlist_paths == frozenset({"/music/list.m3u"})
    assert tuple(request.photo_edits.imported_files) == (("/photos/a.jpg", "Album"),)


def test_plan_ready_waits_for_podcast_plan_merge(qapp, monkeypatch) -> None:
    diff_workers: list[_FakeWorker] = []
    podcast_workers: list[_FakeWorker] = []

    monkeypatch.setattr(
        "iopenpod.application.sync_session.SyncDiffWorker",
        lambda request: diff_workers.append(_FakeWorker(request)) or diff_workers[-1],
    )
    monkeypatch.setattr(
        "iopenpod.application.sync_session.PodcastPlanWorker",
        lambda request: podcast_workers.append(_FakeWorker(request)) or podcast_workers[-1],
    )
    controller = _controller(
        podcast_input_provider=lambda: PodcastPlanningInput(
            feeds=(SimpleNamespace(feed_url="https://example.test/feed"),),
            store=SimpleNamespace(),
        )
    )
    plans: list[SyncPlan] = []
    controller.plan_ready.connect(plans.append)

    controller.start_planning(
        SyncPlanningIntent(
            mode="full",
            folder_entries=({"directory": "/music", "recurse": True},),
        )
    )
    base_plan = SyncPlan(storage=StorageSummary(bytes_to_add=10))
    diff_workers[0].finished.emit(base_plan)

    assert plans == []
    assert len(podcast_workers) == 1

    podcast_plan = SyncPlan(
        to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)],
        storage=StorageSummary(bytes_to_add=25),
    )
    podcast_workers[0].finished.emit(podcast_plan)

    assert plans == [base_plan]
    assert len(base_plan.to_add) == 1
    assert base_plan.storage.bytes_to_add == 35


def test_cancelled_planning_worker_cannot_publish_stale_plan(
    qapp,
    monkeypatch,
) -> None:
    workers: list[_FakeWorker] = []
    monkeypatch.setattr(
        "iopenpod.application.sync_session.SyncDiffWorker",
        lambda request: workers.append(_FakeWorker(request)) or workers[-1],
    )
    controller = _controller()
    plans: list[SyncPlan] = []
    controller.plan_ready.connect(plans.append)

    controller.start_planning(
        SyncPlanningIntent(
            mode="full",
            folder_entries=({"directory": "/music", "recurse": True},),
        )
    )
    worker = workers[0]

    controller.cancel()
    worker.finished.emit(SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)]))

    assert worker.interruptions == 1
    assert plans == []
    assert controller.is_running() is False


def test_start_execution_owns_worker_controls(qapp, monkeypatch) -> None:
    workers: list[_FakeWorker] = []

    def fake_execute_worker(ipod_path: str, plan: Any, **kwargs: Any) -> _FakeWorker:
        worker = _FakeWorker(ipod_path=ipod_path, plan=plan, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("iopenpod.application.sync_session.SyncExecuteWorker", fake_execute_worker)
    cache = _FakeLibraryCache()
    controller = _controller(cache=cache)
    completed: list[Any] = []
    started: list[bool] = []
    partial: list[tuple[int, int]] = []
    controller.execution_started.connect(lambda: started.append(True))
    controller.execution_complete.connect(completed.append)
    controller.partial_save_requested.connect(
        lambda added, skipped: partial.append((added, skipped))
    )

    plan = SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)])
    controller.start_execution(
        SyncExecutionIntent(
            plan=plan,
            skip_backup=True,
            sync_until_full=True,
        )
    )

    worker = workers[0]
    assert worker.kwargs["settings"].sync_workers == 3
    assert worker.kwargs["backup_device_name"] == "RoadPod"
    assert worker.kwargs["sync_until_full"] is True
    assert (
        worker.kwargs["expected_database_generation"]
        == cache.database_generation
    )
    assert worker.started is True
    assert started == [True]

    worker.confirm_partial_save.emit(2, 1)
    controller.respond_to_partial_save(False)
    controller.request_skip_backup()
    controller.request_give_up_scrobble()
    result = SimpleNamespace(success=True)
    worker.finished.emit(result)

    assert partial == [(2, 1)]
    assert worker.partial_save_responses == [False]
    assert worker.skip_backup_requests == 1
    assert worker.give_up_scrobble_requests == 1
    assert completed == [result]
    worker.kwargs["on_sync_complete"]()
    assert cache.clear_pending_calls == 1
