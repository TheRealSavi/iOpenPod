from types import SimpleNamespace
from typing import Any, cast

from GUI.app import (
    MainWindow,
    _library_load_failure_message,
    _sync_execute_failure_message,
)
from GUI.internal_drag import IOP_EXPORT_DRAG_MIME
from infrastructure.settings_schema import AppSettings
from SyncEngine.contracts import SyncPlan


class _FakeStack:
    def __init__(self, current_index: int = 0, current_widget=None):
        self._current_index = current_index
        self._current_widget = current_widget
        self.set_indices: list[int] = []

    def currentIndex(self) -> int:
        return self._current_index

    def currentWidget(self):
        return self._current_widget

    def setCurrentIndex(self, index: int) -> None:
        self.set_indices.append(index)
        self._current_index = index


class _FakeSignal:
    def __init__(self) -> None:
        self.connections: list[object] = []
        self.disconnect_count = 0

    def connect(self, callback: object) -> None:
        self.connections.append(callback)

    def disconnect(self) -> None:
        self.disconnect_count += 1


class _FakeBackSyncWorker:
    def __init__(self, *, running: bool = True) -> None:
        self._running = running
        self.progress = _FakeSignal()
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.request_count = 0
        self.delete_later_count = 0

    def isRunning(self) -> bool:
        return self._running

    def requestInterruption(self) -> None:
        self.request_count += 1

    def deleteLater(self) -> None:
        self.delete_later_count += 1


class _FakeSyncExecuteWorker(_FakeBackSyncWorker):
    pass


class _FakeSidebar:
    def __init__(self):
        self.library_tabs_visible: list[bool] = []
        self.tag_fixes_available: list[bool] = []
        self.device_info_updates: list[dict] = []
        self.clear_count = 0

    def setLibraryTabsVisible(self, visible: bool) -> None:
        self.library_tabs_visible.append(visible)

    def setTagFixesAvailable(self, available: bool) -> None:
        self.tag_fixes_available.append(available)

    def updateDeviceInfo(self, **kwargs) -> None:
        self.device_info_updates.append(kwargs)

    def clearDeviceInfo(self) -> None:
        self.clear_count += 1


class _FakeSettingsService:
    def __init__(self) -> None:
        self.settings = AppSettings()
        self.saved_settings: list[AppSettings] = []

    def get_global_settings(self) -> AppSettings:
        return self.settings

    def get_effective_settings(self) -> AppSettings:
        return self.settings

    def save_global_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.saved_settings.append(settings)


def test_main_window_device_name_ignores_dataset5_category_master() -> None:
    assert MainWindow._device_name_from_playlists(
        [
            {
                "master_flag": True,
                "Title": "Rentals",
                "_source": "category",
                "mhsd5_type": 7,
            },
            {"master_flag": True, "Title": "RoadPod"},
        ]
    ) == "RoadPod"


def test_failed_sync_result_gets_user_visible_message() -> None:
    result = SimpleNamespace(
        success=False,
        partial_save=False,
        errors=[("read-only", "iOpenPod cannot write to this iPod.")],
    )

    assert _sync_execute_failure_message(result) == (
        "iOpenPod cannot write to this iPod."
    )


def test_library_load_permission_message_includes_linux_recovery_steps() -> None:
    message = _library_load_failure_message(
        "/media/user/IPOD",
        "Could not load iTunesDB: [Errno 13] Permission denied",
    )

    assert "iOpenPod could not read this iPod cleanly" in message
    assert "/media/user/IPOD" in message
    assert "mount -o remount,rw" in message
    assert "fsck.vfat" in message


def test_device_changed_rejects_unwritable_device_before_loading(monkeypatch) -> None:
    calls: list[str] = []
    criticals: list[tuple[str, str]] = []
    fake_pool = SimpleNamespace(clear=lambda: calls.append("clear_pool"))

    monkeypatch.setattr(
        "GUI.app.ThreadPoolSingleton.get_instance",
        staticmethod(lambda: fake_pool),
    )
    monkeypatch.setattr("GUI.imgMaker.clear_artwork_api", lambda: calls.append("art"))
    monkeypatch.setattr(
        "GUI.app.check_ipod_write_access",
        lambda _path: SimpleNamespace(writable=False, message="not writable"),
    )
    monkeypatch.setattr(
        "GUI.app.QMessageBox.critical",
        lambda _parent, title, message: criticals.append((title, message)),
    )

    window = SimpleNamespace(
        _theme_rebuild_timer=SimpleNamespace(
            isActive=lambda: False,
            stop=lambda: calls.append("stop_timer"),
        ),
        _pending_theme_rebuild=True,
        musicBrowser=SimpleNamespace(reloadData=lambda: calls.append("reload")),
        sidebar=_FakeSidebar(),
        device_manager=SimpleNamespace(device_path="/media/user/IPOD"),
        library_cache=SimpleNamespace(start_loading=lambda: calls.append("load")),
        _apply_effective_theme=lambda: False,
        _schedule_themed_rebuild=lambda restore_page=0: calls.append("theme"),
        _reset_library_category_for_new_device=lambda path: calls.append(
            f"category:{path}"
        ),
        _show_default_page=lambda: calls.append("default"),
    )

    MainWindow.onDeviceChanged(cast(Any, window), "/media/user/IPOD")

    assert window.device_manager.device_path is None
    assert "load" not in calls
    assert "category:/media/user/IPOD" not in calls
    assert criticals == [("iPod Not Writable", "not writable")]


def test_pc_media_folder_edits_persist_to_global_settings_immediately(tmp_path) -> None:
    media_dir = tmp_path / "Media"
    service = _FakeSettingsService()
    window = SimpleNamespace(settings_service=service)

    MainWindow._persist_pc_folder_entries(
        cast(Any, window),
        [
            {
                "directory": str(media_dir),
                "recurse": False,
                "media": ["audio", "playlist_files"],
            }
        ],
    )

    assert window._last_pc_folders == [str(media_dir)]
    assert window._last_pc_folder_entries == [
        {
            "directory": str(media_dir),
            "recurse": False,
            "media_types": ["music", "playlists"],
        }
    ]
    assert service.settings.media_folder == str(media_dir)
    assert service.settings.media_folders == window._last_pc_folder_entries
    assert service.saved_settings == [service.settings]


def test_start_pc_sync_without_device_opens_media_folder_dialog(monkeypatch) -> None:
    calls: list[object] = []

    class _FakeSignal:
        def __init__(self) -> None:
            self.callbacks: list[object] = []

        def connect(self, callback: object) -> None:
            self.callbacks.append(callback)

    class _FakeDialog:
        DialogCode = SimpleNamespace(Accepted=1)

        def __init__(
            self,
            parent: object,
            folder_entries: object,
            *,
            sync_available: bool,
        ) -> None:
            calls.append(
                {
                    "parent": parent,
                    "folder_entries": folder_entries,
                    "sync_available": sync_available,
                }
            )
            self.foldersChanged = _FakeSignal()

        def exec(self) -> int:
            calls.append("exec")
            return 0

    def _unexpected_tool_check(settings: object) -> None:
        raise AssertionError("tool availability should not be checked without a device")

    def _unexpected_warning(*args: object, **kwargs: object) -> None:
        raise AssertionError("no-device sync should open the media folder dialog")

    service = _FakeSettingsService()
    entries = [{"directory": "/tmp/Music", "recurse": True, "media_types": ["music"]}]
    window = SimpleNamespace(
        _quick_write_controller=SimpleNamespace(
            prepare_for_full_sync=lambda: calls.append("prepared") or (True, None)
        ),
        device_manager=SimpleNamespace(device_path=""),
        settings_service=service,
        _last_pc_folder_entries=entries,
        _persist_pc_folder_entries=lambda folder_entries: calls.append(
            {"persisted": folder_entries}
        ),
    )

    monkeypatch.setattr("GUI.app.PCFolderDialog", _FakeDialog)
    monkeypatch.setattr("GUI.app.check_sync_tool_availability", _unexpected_tool_check)
    monkeypatch.setattr("GUI.app.QMessageBox.warning", _unexpected_warning)

    MainWindow.startPCSync(cast(Any, window))

    assert calls[0] == {
        "parent": window,
        "folder_entries": entries,
        "sync_available": False,
    }
    assert calls[1] == "exec"
    assert "prepared" not in calls


def test_execute_sync_plan_passes_playlist_actions_only_in_plan(
    monkeypatch,
) -> None:
    plan = SyncPlan(
        playlists_to_add=[
            {
                "playlist_id": 5282529579168309310,
                "Title": "Test",
                "_isNew": True,
                "_mhsd_dataset_type": 2,
                "items": [{"db_track_id": 101}],
            }
        ]
    )
    workers: list[object] = []

    class _CapturingSyncExecuteWorker:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.progress = _FakeSignal()
            self.finished = _FakeSignal()
            self.error = _FakeSignal()
            self.confirm_partial_save = _FakeSignal()
            self.started = False
            workers.append(self)

        def request_skip_backup(self) -> None:
            pass

        def request_give_up_scrobble(self) -> None:
            pass

        def start(self) -> None:
            self.started = True

    class _FakeSyncReview:
        _skip_presync_backup = False

        def __init__(self) -> None:
            self.skip_backup_signal = _FakeSignal()
            self.give_up_scrobble_signal = _FakeSignal()
            self.executing_count = 0

        def get_selected_playlist_changes(self) -> dict:
            return {"playlists_to_add": plan.playlists_to_add}

        def get_selected_photo_plan(self) -> None:
            return None

        def show_executing(self) -> None:
            self.executing_count += 1

        def update_execute_progress(self, *_args: object) -> None:
            pass

    monkeypatch.setattr("GUI.app.SyncExecuteWorker", _CapturingSyncExecuteWorker)
    monkeypatch.setattr(
        "GUI.app.build_filtered_sync_plan",
        lambda original_plan, _selected_items, **_kwargs: original_plan,
    )

    sync_review = _FakeSyncReview()
    clear_calls: list[bool] = []
    window = SimpleNamespace(
        device_manager=SimpleNamespace(device_path="/media/IPOD"),
        _plan=plan,
        syncReview=sync_review,
        _confirm_sync_until_full_if_needed=lambda _plan, _path: False,
        settings_service=_FakeSettingsService(),
        library_cache=SimpleNamespace(
            clear_pending_sync_state=lambda: clear_calls.append(True),
            get_playlists=lambda: [],
        ),
        device_session_service=SimpleNamespace(
            current_session=lambda: SimpleNamespace(identity={}, capabilities={})
        ),
        _sync_execute_worker=None,
        _onSyncExecuteComplete=lambda *_args: None,
        _onSyncExecuteError=lambda *_args: None,
        _onConfirmPartialSave=lambda *_args: None,
    )

    MainWindow.executeSyncPlan(cast(Any, window), selected_items=[])

    assert len(workers) == 1
    worker = cast(Any, workers[0])
    assert worker.kwargs["plan"] is plan
    assert "user_playlists" not in worker.kwargs
    assert worker.started is True


class _FakeDropOverlay:
    def __init__(self, *, visible: bool = False):
        self._visible = visible
        self.show_count = 0
        self.hide_count = 0

    def isVisible(self) -> bool:
        return self._visible

    def show_overlay(self) -> None:
        self.show_count += 1
        self._visible = True

    def hide_overlay(self) -> None:
        self.hide_count += 1
        self._visible = False


class _FakeMime:
    def __init__(self, *, formats: set[str] | None = None, urls: list | None = None):
        self._formats = formats or set()
        self._urls = urls or []

    def hasFormat(self, name: str) -> bool:
        return name in self._formats

    def hasUrls(self) -> bool:
        return bool(self._urls)

    def urls(self) -> list:
        return self._urls


class _FakeDropEvent:
    def __init__(self, mime: _FakeMime):
        self._mime = mime
        self.accepted = False
        self.ignored = False

    def mimeData(self) -> _FakeMime:
        return self._mime

    def acceptProposedAction(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _FakeCache:
    def is_ready(self) -> bool:
        return True

    def get_tracks(self) -> list:
        return []

    def get_albums(self) -> list:
        return []

    def get_album_index(self) -> dict:
        return {}

    def get_album_only_index(self) -> dict:
        return {}

    def get_data(self) -> dict:
        return {}

    def get_playlists(self) -> list:
        return []


def _build_window_for_data_ready(
    *,
    current_page_index: int = 1,
    sync_results_visible: bool = True,
):
    window = SimpleNamespace()
    sync_review = SimpleNamespace(stack=_FakeStack(current_index=3))
    current_widget = sync_review if sync_results_visible else object()

    window.syncReview = sync_review
    window.centralStack = _FakeStack(
        current_index=current_page_index,
        current_widget=current_widget,
    )
    window.mainContentStack = _FakeStack()
    identity = SimpleNamespace(ipod_name="RoadPod", display_name="iPod Classic")
    window.device_manager = SimpleNamespace(
        device_path="E:/iPod",
        discovered_ipod=SimpleNamespace(path=""),
    )
    window.device_session_service = SimpleNamespace(
        current_session=lambda: SimpleNamespace(identity=identity),
    )
    window.sidebar = _FakeSidebar()
    window.library_cache = _FakeCache()
    window.musicBrowser = SimpleNamespace(
        browserTrack=SimpleNamespace(clearTable=lambda clear_cache=False: None),
        onDataReady=lambda: None,
    )
    window._classify_tracks = lambda tracks: {
        "video": [],
        "podcast": [],
        "audiobook": [],
    }
    window._update_sidebar_visibility = lambda classified: None
    window._update_podcast_statuses = lambda: None
    window._is_sync_results_visible = MainWindow._is_sync_results_visible.__get__(
        window
    )
    window._refresh_default_page_state = MainWindow._refresh_default_page_state.__get__(
        window
    )
    window._show_default_page = MainWindow._show_default_page.__get__(window)
    window._should_show_default_page_on_data_ready = (
        MainWindow._should_show_default_page_on_data_ready.__get__(window)
    )
    return window


def _build_window_for_drop_events(*, overlay_visible: bool = False):
    window = SimpleNamespace()
    window._drop_overlay = _FakeDropOverlay(visible=overlay_visible)
    window.device_manager = SimpleNamespace(device_path="E:/iPod")
    window._sync_execute_worker = None
    window.device_session_service = SimpleNamespace(
        current_session=lambda: SimpleNamespace(capabilities=None),
    )
    window.dropped_paths = []
    window._on_files_dropped = lambda paths: window.dropped_paths.extend(paths)
    return window


def _call_on_data_ready(window: object) -> None:
    MainWindow.onDataReady(cast(Any, window))


def test_post_sync_rescan_refreshes_library_without_leaving_results():
    window = _build_window_for_data_ready(sync_results_visible=True)
    window._keep_sync_results_visible_after_rescan = True
    scheduled_rebuild_pages: list[int] = []
    window._apply_match_ipod_accent = lambda dev: True
    window._schedule_themed_rebuild = (
        lambda restore_page=0: scheduled_rebuild_pages.append(restore_page)
    )

    _call_on_data_ready(window)

    assert window.centralStack.set_indices == []
    assert window.mainContentStack.set_indices == [0]
    assert window._keep_sync_results_visible_after_rescan is False
    assert scheduled_rebuild_pages == [1]


def test_data_ready_preserves_settings_page():
    window = _build_window_for_data_ready(
        current_page_index=2,
        sync_results_visible=False,
    )
    window._keep_sync_results_visible_after_rescan = False
    window._apply_match_ipod_accent = lambda dev: False

    _call_on_data_ready(window)

    assert window.centralStack.set_indices == []
    assert window.mainContentStack.set_indices == [0]
    assert window._keep_sync_results_visible_after_rescan is False


def test_data_ready_updates_main_page_when_main_page_is_visible():
    window = _build_window_for_data_ready(
        current_page_index=0,
        sync_results_visible=False,
    )
    window._keep_sync_results_visible_after_rescan = False
    window._apply_match_ipod_accent = lambda dev: False

    _call_on_data_ready(window)

    assert window.centralStack.set_indices == [0]
    assert window.mainContentStack.set_indices == [0]


def test_own_export_drag_is_ignored_for_sync_drag_enter():
    window = _build_window_for_drop_events()
    event = _FakeDropEvent(_FakeMime(formats={IOP_EXPORT_DRAG_MIME}))

    MainWindow.dragEnterEvent(cast(Any, window), cast(Any, event))

    assert event.ignored
    assert not event.accepted
    assert window._drop_overlay.hide_count == 1
    assert window._drop_overlay.show_count == 0


def test_own_export_drag_is_ignored_for_sync_drop():
    window = _build_window_for_drop_events(overlay_visible=True)
    event = _FakeDropEvent(_FakeMime(formats={IOP_EXPORT_DRAG_MIME}))

    MainWindow.dropEvent(cast(Any, window), cast(Any, event))

    assert event.ignored
    assert not event.accepted
    assert window.dropped_paths == []
    assert window._drop_overlay.hide_count == 1


def test_drop_scan_complete_merges_import_context_into_existing_plan():
    shown: list[SyncPlan] = []
    existing = SyncPlan(
        matched_pc_paths={1: "C:/Music/existing.mp3"},
        playlists_to_edit=[{"Title": "Existing"}],
    )
    dropped = SyncPlan(
        matched_pc_paths={2: "C:/Music/dropped.mp3"},
        playlists_to_add=[{"Title": "New"}],
        playlists_to_edit=[{"Title": "Dropped"}],
    )
    dropped.storage.bytes_to_add = 100
    window = SimpleNamespace(
        _drop_merge=True,
        _plan=existing,
        syncReview=SimpleNamespace(show_plan=shown.append),
    )

    MainWindow._on_drop_scan_complete(cast(Any, window), dropped)

    assert window._plan is existing
    assert shown == [existing]
    assert existing.matched_pc_paths == {
        1: "C:/Music/existing.mp3",
        2: "C:/Music/dropped.mp3",
    }
    assert existing.playlists_to_add == [{"Title": "New"}]
    assert existing.playlists_to_edit == [
        {"Title": "Existing"},
        {"Title": "Dropped"},
    ]
    assert existing.storage.bytes_to_add == 100


def test_sync_review_edit_selection_opens_selective_plan_editor():
    selection = {"sync_items": {1, 2}}
    plan = object()
    load_calls: list[tuple[object, object]] = []
    window = SimpleNamespace(
        _plan=plan,
        centralStack=_FakeStack(),
        selectiveSyncBrowser=SimpleNamespace(
            load_sync_plan=lambda p, state: load_calls.append((p, state))
        ),
    )

    MainWindow._onSyncReviewEditSelection(cast(Any, window), selection)

    assert window.centralStack.set_indices == [4]
    assert load_calls == [(plan, selection)]


def test_selective_plan_editor_done_applies_state_and_returns_to_review():
    selection = {"sync_items": {42}}
    applied: list[object] = []
    window = SimpleNamespace(
        centralStack=_FakeStack(),
        syncReview=SimpleNamespace(
            apply_selection_state=lambda state: applied.append(state)
        ),
    )

    MainWindow._onPlanSelectionDone(cast(Any, window), selection)

    assert applied == [selection]
    assert window.centralStack.set_indices == [1]


def test_selective_plan_editor_cancel_returns_to_review_without_changes():
    window = SimpleNamespace(centralStack=_FakeStack())

    MainWindow._onPlanSelectionCancelled(cast(Any, window))

    assert window.centralStack.set_indices == [1]


def _build_window_for_back_sync_cancel(worker: _FakeBackSyncWorker):
    default_page_calls: list[bool] = []
    window = SimpleNamespace(
        _sync_worker=None,
        _back_sync_worker=worker,
        _back_sync_workers=[worker],
        _cancelled_workers=[],
        _podcast_plan_worker=None,
        _album_conversion_worker=None,
        _chapter_split_worker=None,
        _sync_execute_worker=None,
        _keep_sync_results_visible_after_rescan=True,
    )
    window._cleanup_sync_execute_worker = lambda: None
    window._show_default_page = lambda: default_page_calls.append(True)
    window._clear_worker_reference = MainWindow._clear_worker_reference.__get__(window)
    window._retain_cancelled_worker = MainWindow._retain_cancelled_worker.__get__(window)
    window._reap_cancelled_worker = MainWindow._reap_cancelled_worker.__get__(window)
    window._cleanup_worker = MainWindow._cleanup_worker.__get__(window)
    window._clear_back_sync_worker = MainWindow._clear_back_sync_worker.__get__(window)
    window._retain_back_sync_worker = MainWindow._retain_back_sync_worker.__get__(window)
    window._reap_back_sync_worker = MainWindow._reap_back_sync_worker.__get__(window)
    window._cleanup_back_sync_worker = MainWindow._cleanup_back_sync_worker.__get__(window)
    window._cleanup_sync_diff_worker = MainWindow._cleanup_sync_diff_worker.__get__(window)
    window._cleanup_podcast_plan_worker = MainWindow._cleanup_podcast_plan_worker.__get__(window)
    window._cleanup_album_conversion_worker = MainWindow._cleanup_album_conversion_worker.__get__(window)
    window._cleanup_chapter_split_worker = MainWindow._cleanup_chapter_split_worker.__get__(window)
    window.hideSyncReview = MainWindow.hideSyncReview.__get__(window)
    return window, default_page_calls


def test_sync_review_cancel_detaches_back_sync_worker_and_returns_to_library():
    worker = _FakeBackSyncWorker(running=True)
    window, default_page_calls = _build_window_for_back_sync_cancel(worker)

    MainWindow._onSyncReviewCancelled(cast(Any, window))

    assert worker.request_count == 1
    assert worker.progress.disconnect_count == 1
    assert worker.finished.disconnect_count == 1
    assert worker.error.disconnect_count == 1
    assert window._back_sync_worker is None
    assert window._back_sync_workers == [worker]
    assert window._keep_sync_results_visible_after_rescan is False
    assert default_page_calls == [True]


def test_reap_back_sync_worker_releases_retained_thread_reference():
    worker = _FakeBackSyncWorker(running=False)
    window = SimpleNamespace(_back_sync_worker=worker, _back_sync_workers=[worker])
    window._clear_back_sync_worker = MainWindow._clear_back_sync_worker.__get__(window)

    MainWindow._reap_back_sync_worker(cast(Any, window), worker)

    assert window._back_sync_worker is None
    assert window._back_sync_workers == []
    assert worker.delete_later_count == 1


def test_stale_back_sync_completion_after_cancel_is_ignored():
    worker = _FakeBackSyncWorker(running=False)
    shown_results: list[object] = []
    window = SimpleNamespace(
        _back_sync_worker=None,
        syncReview=SimpleNamespace(
            show_back_sync_result=lambda result: shown_results.append(result)
        ),
    )
    window._clear_back_sync_worker = MainWindow._clear_back_sync_worker.__get__(window)

    MainWindow._onBackSyncComplete(
        cast(Any, window),
        {"exported": 1, "missing_on_pc": 1},
        worker,
    )

    assert shown_results == []


def test_sync_review_cancel_detaches_sync_diff_worker_and_returns_to_library():
    worker = _FakeBackSyncWorker(running=True)
    window, default_page_calls = _build_window_for_back_sync_cancel(
        _FakeBackSyncWorker(running=False)
    )
    window._back_sync_worker = None
    window._back_sync_workers = []
    window._sync_worker = worker

    MainWindow._onSyncReviewCancelled(cast(Any, window))

    assert worker.request_count == 1
    assert worker.progress.disconnect_count == 1
    assert worker.finished.disconnect_count == 1
    assert worker.error.disconnect_count == 1
    assert window._sync_worker is None
    assert window._cancelled_workers == [worker]
    assert default_page_calls == [True]


def test_sync_review_execute_cancel_stays_on_review_page():
    execute_worker = _FakeSyncExecuteWorker(running=True)
    default_page_calls: list[bool] = []
    window = SimpleNamespace(
        _sync_execute_worker=execute_worker,
        hideSyncReview=lambda: default_page_calls.append(True),
    )

    MainWindow._onSyncReviewCancelled(cast(Any, window))

    assert execute_worker.request_count == 1
    assert default_page_calls == []


def test_stale_sync_diff_completion_after_cancel_is_ignored():
    worker = _FakeBackSyncWorker(running=False)
    window = SimpleNamespace(_sync_worker=None)

    MainWindow._onSyncDiffComplete(cast(Any, window), object(), worker)

    assert not hasattr(window, "_plan")
