import struct
import zlib
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

from iopenpod.application.database_storage import DatabaseStorageReport
from iopenpod.application.jobs import SyncToolAvailability
from iopenpod.application.sync_session import (
    SyncExecutionIntent,
    SyncPlanningIntent,
    SyncSessionMissingTools,
)
from iopenpod.gui.app import (
    MainWindow,
    _database_file_size_bytes,
    _library_load_failure_message,
    _sync_execute_failure_message,
)
from iopenpod.gui.internal_drag import IOP_EXPORT_DRAG_MIME
from iopenpod.infrastructure.settings_schema import AppSettings
from iopenpod.sync.contracts import SyncPlan


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
        self.connections: list[Callable[..., object]] = []
        self.disconnect_count = 0

    def connect(self, callback: Callable[..., object]) -> None:
        self.connections.append(callback)

    def disconnect(self) -> None:
        self.disconnect_count += 1

    def emit(self, *args: object) -> None:
        for callback in list(self.connections):
            callback(*args)


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


class _FakeSidebar:
    def __init__(self):
        self.library_tabs_visible: list[bool] = []
        self.tag_fixes_available: list[bool] = []
        self.tag_fix_counts: list[tuple[int, int]] = []
        self.device_info_updates: list[dict] = []
        self.clear_count = 0

    def setLibraryTabsVisible(self, visible: bool) -> None:
        self.library_tabs_visible.append(visible)

    def setTagFixesAvailable(self, available: bool) -> None:
        self.tag_fixes_available.append(available)

    def setTagFixCount(self, field_count: int, track_count: int = 0) -> None:
        self.tag_fix_counts.append((field_count, track_count))

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


def test_sync_session_progress_targets_rebuilt_review_widget() -> None:
    class _FakeSyncReview:
        def __init__(self) -> None:
            self.planning_progress: list[tuple[object, ...]] = []
            self.execution_progress: list[object] = []
            self.executing_count = 0

        def update_progress(self, *args: object) -> None:
            self.planning_progress.append(args)

        def show_executing(self) -> None:
            self.executing_count += 1

        def update_execute_progress(self, progress: object) -> None:
            self.execution_progress.append(progress)

    session = SimpleNamespace(
        planning_progress=_FakeSignal(),
        execution_started=_FakeSignal(),
        execution_progress=_FakeSignal(),
    )
    old_review = _FakeSyncReview()
    current_review = _FakeSyncReview()
    window = SimpleNamespace(_sync_session=session, syncReview=old_review)
    window._on_sync_session_planning_progress = (
        MainWindow._on_sync_session_planning_progress.__get__(window)
    )
    window._on_sync_session_execution_started = (
        MainWindow._on_sync_session_execution_started.__get__(window)
    )
    window._on_sync_session_execution_progress = (
        MainWindow._on_sync_session_execution_progress.__get__(window)
    )

    MainWindow._connect_sync_session_review_signals(cast(Any, window))
    window.syncReview = current_review  # live theme changes rebuild this widget

    planning_event = ("fingerprint", 2, 3, "track-02.mp3")
    execution_event = SimpleNamespace(
        stage="add",
        current=2,
        total=3,
        worker_lines=["Copying track-02.mp3 — 75%"],
    )
    session.planning_progress.emit(*planning_event)
    session.execution_started.emit()
    session.execution_progress.emit(execution_event)

    assert current_review.planning_progress == [planning_event]
    assert current_review.executing_count == 1
    assert current_review.execution_progress == [execution_event]
    assert old_review.planning_progress == []
    assert old_review.executing_count == 0
    assert old_review.execution_progress == []


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


def test_successful_sync_queues_silent_normalization_after_rescan(monkeypatch) -> None:
    shown_results: list[object] = []
    scheduled: list[tuple[int, object]] = []
    monkeypatch.setattr(
        "iopenpod.gui.app.QTimer.singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )
    window = SimpleNamespace(
        syncReview=SimpleNamespace(show_result=shown_results.append),
        settings_service=SimpleNamespace(
            get_effective_settings=lambda: AppSettings(
                normalize_tags_after_sync=True,
            )
        ),
        isActiveWindow=lambda: True,
        _rescanAfterSync=lambda: None,
        _normalize_tags_after_sync_pending=False,
    )
    result = SimpleNamespace(success=True, partial_save=False, errors=[])

    MainWindow._onSyncExecuteComplete(cast(Any, window), result)

    assert shown_results == [result]
    assert window._normalize_tags_after_sync_pending is True
    assert scheduled == [(500, window._rescanAfterSync)]


def test_post_sync_tag_scan_applies_silently_to_unchanged_cache() -> None:
    tracks = [
        {"db_track_id": 1, "Title": "  Song  "},
        {"db_track_id": 2, "Title": "Already Clean"},
    ]
    staged_changes: list[tuple[list[dict], dict[int, dict]]] = []
    sidebar = _FakeSidebar()
    window = SimpleNamespace(
        _tag_fix_scan_generation=7,
        _tag_fix_scan_worker=object(),
        _normalize_tags_after_sync_pending=True,
        sidebar=sidebar,
        settings_service=SimpleNamespace(
            get_effective_settings=lambda: AppSettings(
                normalize_tags_after_sync=True,
            )
        ),
        library_cache=SimpleNamespace(
            get_tracks=lambda: tracks,
            update_track_flags_by_track=lambda current, changes: staged_changes.append(
                (current, changes)
            ),
        ),
        _schedule_tag_fix_scan=lambda: None,
    )
    result = SimpleNamespace(
        changes_by_index={0: {"Title": "Song", "Sort Title": "Song"}},
        changed_track_count=1,
        changed_field_count=2,
    )

    MainWindow._on_tag_fix_scan_ready(
        cast(Any, window),
        result,
        generation=7,
        scanned_track_count=2,
        apply_after_scan=True,
    )

    assert sidebar.tag_fix_counts == [(2, 1)]
    assert staged_changes == [
        (tracks, {id(tracks[0]): {"Title": "Song", "Sort Title": "Song"}})
    ]
    assert window._normalize_tags_after_sync_pending is False


def test_stale_tag_scan_does_not_update_badge_or_cache() -> None:
    sidebar = _FakeSidebar()
    window = SimpleNamespace(
        _tag_fix_scan_generation=8,
        sidebar=sidebar,
    )

    MainWindow._on_tag_fix_scan_ready(
        cast(Any, window),
        SimpleNamespace(
            changes_by_index={0: {"Title": "Song"}},
            changed_track_count=1,
            changed_field_count=1,
        ),
        generation=7,
        scanned_track_count=1,
        apply_after_scan=True,
    )

    assert sidebar.tag_fix_counts == []


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
        "iopenpod.gui.app.ThreadPoolSingleton.get_instance",
        staticmethod(lambda: fake_pool),
    )
    monkeypatch.setattr("iopenpod.gui.imgMaker.clear_artwork_api", lambda: calls.append("art"))
    monkeypatch.setattr(
        "iopenpod.gui.app.check_ipod_write_access",
        lambda _path: SimpleNamespace(writable=False, message="not writable"),
    )
    monkeypatch.setattr(
        "iopenpod.gui.app.QMessageBox.critical",
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
        _invalidate_tag_fix_scan=lambda: calls.append("invalidate_tag_scan"),
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
    assert "invalidate_tag_scan" in calls
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

    monkeypatch.setattr("iopenpod.gui.app.PCFolderDialog", _FakeDialog)
    monkeypatch.setattr("iopenpod.gui.app.QMessageBox.warning", _unexpected_warning)

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
    execution_intents: list[SyncExecutionIntent] = []

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

    monkeypatch.setattr(
        "iopenpod.gui.app.build_filtered_sync_plan",
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
        _sync_session=SimpleNamespace(
            start_execution=lambda intent: execution_intents.append(intent)
        ),
        _onSyncExecuteComplete=lambda *_args: None,
        _onSyncExecuteError=lambda *_args: None,
        _onConfirmPartialSave=lambda *_args: None,
    )

    MainWindow.executeSyncPlan(cast(Any, window), selected_items=[])

    assert len(execution_intents) == 1
    intent = execution_intents[0]
    assert intent.plan is plan
    assert not hasattr(intent, "user_playlists")


def test_missing_tools_download_preserves_sync_planning_intent(monkeypatch) -> None:
    downloads: list[tuple[bool, bool, SyncPlanningIntent | None]] = []
    intent = SyncPlanningIntent(
        mode="full",
        folder_entries=({"directory": "/music", "recurse": True},),
    )

    class _FakeMissingToolsDialog:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def exec(self) -> int:
            return 1

    monkeypatch.setattr("iopenpod.gui.app._MissingToolsDialog", _FakeMissingToolsDialog)
    monkeypatch.setattr(
        "iopenpod.gui.app.QDialog.DialogCode",
        SimpleNamespace(Accepted=1),
    )
    window = SimpleNamespace(
        _download_missing_tools_then_sync=lambda need_ffmpeg, need_fpcalc, planning_intent=None: downloads.append(
            (need_ffmpeg, need_fpcalc, planning_intent)
        )
    )

    MainWindow._on_sync_session_missing_tools(
        cast(Any, window),
        SyncSessionMissingTools(
            SyncToolAvailability(
                missing_ffmpeg=True,
                missing_fpcalc=False,
                can_download=True,
            ),
            planning_intent=intent,
        ),
    )

    assert downloads == [(True, False, intent)]


def test_tool_download_completion_resumes_pending_sync_planning_intent() -> None:
    closed: list[bool] = []
    planned: list[SyncPlanningIntent] = []
    reopened_dialog: list[bool] = []
    intent = SyncPlanningIntent(
        mode="selective",
        folder_entries=({"directory": "/music", "recurse": True},),
        selected_paths={"tracks": {"/music/song.mp3"}},
    )
    window = SimpleNamespace(
        _dl_progress=SimpleNamespace(close=lambda: closed.append(True)),
        _pending_tool_sync_intent=intent,
        _sync_session=SimpleNamespace(start_planning=lambda ready: planned.append(ready)),
        startPCSync=lambda: reopened_dialog.append(True),
    )

    MainWindow._on_tools_downloaded(cast(Any, window))

    assert closed == [True]
    assert planned == [intent]
    assert reopened_dialog == []
    assert window._pending_tool_sync_intent is None


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
        current_session=lambda: SimpleNamespace(
            identity=identity,
            capabilities=None,
            itunesdb_path=None,
        ),
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
    window.tag_fix_scan_schedules = 0
    window._schedule_tag_fix_scan = lambda: setattr(
        window,
        "tag_fix_scan_schedules",
        window.tag_fix_scan_schedules + 1,
    )
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
    window._sync_session = SimpleNamespace(is_executing=lambda: False)
    window.device_session_service = SimpleNamespace(
        current_session=lambda: SimpleNamespace(capabilities=None),
    )
    window.dropped_paths = []
    window._on_files_dropped = lambda paths: window.dropped_paths.extend(paths)
    return window


def _call_on_data_ready(window: object) -> None:
    MainWindow.onDataReady(cast(Any, window))


def test_database_file_size_helper_reads_existing_file(tmp_path) -> None:
    db_path = tmp_path / "iTunesDB"
    db_path.write_bytes(b"itunesdb")

    assert _database_file_size_bytes(str(db_path)) == 8
    assert _database_file_size_bytes(str(tmp_path / "missing")) == 0
    assert _database_file_size_bytes(None) == 0


def test_database_file_size_helper_uses_decompressed_cdb_size(tmp_path) -> None:
    header = bytearray(16)
    header[:4] = b"mhbd"
    struct.pack_into("<I", header, 4, len(header))
    struct.pack_into("<I", header, 12, 2)
    payload = b"x" * 2048
    cdb_path = tmp_path / "iTunesCDB"
    cdb_path.write_bytes(bytes(header) + zlib.compress(payload))

    assert _database_file_size_bytes(str(cdb_path)) == len(header) + len(payload)


def test_database_file_size_helper_keeps_cdb_physical_size_for_sqlite_ipods(
    tmp_path,
) -> None:
    header = bytearray(16)
    header[:4] = b"mhbd"
    struct.pack_into("<I", header, 4, len(header))
    struct.pack_into("<I", header, 12, 2)
    payload = b"x" * 2048
    cdb_path = tmp_path / "iTunesCDB"
    cdb_path.write_bytes(bytes(header) + zlib.compress(payload))

    assert _database_file_size_bytes(
        str(cdb_path),
        uses_sqlite_db=True,
    ) == cdb_path.stat().st_size


def test_data_ready_includes_database_storage_metric(tmp_path) -> None:
    window = _build_window_for_data_ready()
    window._keep_sync_results_visible_after_rescan = False
    window._apply_match_ipod_accent = lambda dev: False

    db_path = tmp_path / "iTunesDB"
    db_path.write_bytes(b"x" * 1024)
    identity = SimpleNamespace(ipod_name="RoadPod", display_name="iPod Classic")
    window.device_session_service = SimpleNamespace(
        current_session=lambda: SimpleNamespace(
            identity=identity,
            capabilities=SimpleNamespace(
                max_database_bytes=64 * 1024 * 1024,
                uses_sqlite_db=False,
            ),
            itunesdb_path=str(db_path),
        ),
    )

    _call_on_data_ready(window)

    update = window.sidebar.device_info_updates[-1]
    assert update["database_size_bytes"] == 1024
    assert update["max_database_bytes"] == 64 * 1024 * 1024
    assert update["database_path"] == str(db_path)


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
    assert window.tag_fix_scan_schedules == 1


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
        _show_sync_plan=lambda plan: shown.append(plan),
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


def test_show_database_storage_loads_current_device_report(tmp_path) -> None:
    db_path = tmp_path / "iTunesDB"
    db_path.write_bytes(b"not an iTunesDB")
    load_calls: list[tuple[DatabaseStorageReport, int]] = []
    window = SimpleNamespace(
        centralStack=_FakeStack(),
        databaseStorageBrowser=SimpleNamespace(
            load_report=lambda report, *, max_database_bytes=0: load_calls.append(
                (report, max_database_bytes)
            )
        ),
        device_manager=SimpleNamespace(device_path=str(tmp_path)),
        device_session_service=SimpleNamespace(
            current_session=lambda: SimpleNamespace(
                capabilities=SimpleNamespace(
                    max_database_bytes=64 * 1024 * 1024,
                    uses_sqlite_db=False,
                ),
                itunesdb_path=str(db_path),
            ),
        ),
    )

    MainWindow.showDatabaseStorage(cast(Any, window))

    assert window.centralStack.set_indices == [5]
    report, max_database_bytes = load_calls[-1]
    assert report.database_path == str(db_path)
    assert max_database_bytes == 64 * 1024 * 1024


def test_hide_database_storage_returns_to_default_page() -> None:
    default_calls: list[bool] = []
    window = SimpleNamespace(_show_default_page=lambda: default_calls.append(True))

    MainWindow.hideDatabaseStorage(cast(Any, window))

    assert default_calls == [True]


def test_selective_plan_editor_cancel_returns_to_review_without_changes():
    window = SimpleNamespace(centralStack=_FakeStack())

    MainWindow._onPlanSelectionCancelled(cast(Any, window))

    assert window.centralStack.set_indices == [1]


def _build_window_for_back_sync_cancel(worker: _FakeBackSyncWorker):
    default_page_calls: list[bool] = []
    sync_cancel_calls: list[bool] = []
    window = SimpleNamespace(
        _back_sync_worker=worker,
        _back_sync_workers=[worker],
        _cancelled_workers=[],
        _album_conversion_worker=None,
        _chapter_split_worker=None,
        _sync_session=SimpleNamespace(
            is_executing=lambda: False,
            request_execution_cancel=lambda: None,
            cancel=lambda: sync_cancel_calls.append(True),
        ),
        _sync_session_cancel_calls=sync_cancel_calls,
        _keep_sync_results_visible_after_rescan=True,
    )
    window._show_default_page = lambda: default_page_calls.append(True)
    window._clear_worker_reference = MainWindow._clear_worker_reference.__get__(window)
    window._retain_cancelled_worker = MainWindow._retain_cancelled_worker.__get__(window)
    window._reap_cancelled_worker = MainWindow._reap_cancelled_worker.__get__(window)
    window._cleanup_worker = MainWindow._cleanup_worker.__get__(window)
    window._clear_back_sync_worker = MainWindow._clear_back_sync_worker.__get__(window)
    window._retain_back_sync_worker = MainWindow._retain_back_sync_worker.__get__(window)
    window._reap_back_sync_worker = MainWindow._reap_back_sync_worker.__get__(window)
    window._cleanup_back_sync_worker = MainWindow._cleanup_back_sync_worker.__get__(window)
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
    assert window._sync_session_cancel_calls == [True]
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


def test_sync_review_cancel_cancels_sync_session_and_returns_to_library():
    window, default_page_calls = _build_window_for_back_sync_cancel(
        _FakeBackSyncWorker(running=False)
    )
    window._back_sync_worker = None
    window._back_sync_workers = []

    MainWindow._onSyncReviewCancelled(cast(Any, window))

    assert window._sync_session_cancel_calls == [True]
    assert default_page_calls == [True]


def test_sync_review_execute_cancel_stays_on_review_page():
    cancel_calls: list[bool] = []
    default_page_calls: list[bool] = []
    window = SimpleNamespace(
        _sync_session=SimpleNamespace(
            is_executing=lambda: True,
            request_execution_cancel=lambda: cancel_calls.append(True),
        ),
        hideSyncReview=lambda: default_page_calls.append(True),
    )

    MainWindow._onSyncReviewCancelled(cast(Any, window))

    assert cancel_calls == [True]
    assert default_page_calls == []


def test_sync_session_plan_ready_updates_review():
    plan = object()
    shown: list[object] = []
    stack = _FakeStack()
    window = SimpleNamespace(
        centralStack=stack,
        library_cache=SimpleNamespace(get_tracks=lambda: [{"db_track_id": 1}]),
        syncReview=SimpleNamespace(
            _ipod_tracks_cache=[],
            show_plan=lambda ready_plan: shown.append(ready_plan),
        ),
    )
    window._show_sync_plan = MainWindow._show_sync_plan.__get__(window)

    MainWindow._onSyncDiffComplete(cast(Any, window), plan)

    assert window._plan is plan
    assert window.syncReview._ipod_tracks_cache == [{"db_track_id": 1}]
    assert stack.set_indices == [1]
    assert shown == [plan]
