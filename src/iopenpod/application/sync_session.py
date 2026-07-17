"""Sync Session orchestration for PC-to-iPod sync."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from iopenpod.device.write_guard import DatabaseGeneration
from iopenpod.infrastructure.media_folders import (
    media_folder_entries_to_settings,
    media_folder_paths,
)

from .jobs import (
    PodcastPlanRequest,
    PodcastPlanWorker,
    SyncDiffRequest,
    SyncDiffWorker,
    SyncExecuteWorker,
    SyncToolAvailability,
    backup_device_name_from_playlists,
    build_imported_photo_edit_state,
    check_sync_tool_availability,
)
from .services import (
    DeviceManagerLike,
    DeviceSessionService,
    LibraryCacheLike,
    SettingsService,
)
from .sync_options import build_transcode_options

logger = logging.getLogger(__name__)

SyncPlanningMode = Literal["full", "selective"]


class QuickWritePreparer(Protocol):
    def prepare_for_full_sync(self) -> tuple[bool, str | None]:
        ...


@dataclass(frozen=True)
class SyncPlanningIntent:
    """User intent for planning a PC-to-iPod sync."""

    mode: SyncPlanningMode
    folder_entries: tuple[Any, ...]
    selected_paths: Any = None


@dataclass(frozen=True)
class SyncExecutionIntent:
    """User intent for executing a reviewed sync plan."""

    plan: Any
    skip_backup: bool = False
    sync_until_full: bool = False


@dataclass(frozen=True)
class PodcastPlanningInput:
    """Podcast source data needed to merge managed podcast changes into a plan."""

    feeds: tuple[Any, ...]
    store: Any


@dataclass(frozen=True)
class SyncSessionBlocked:
    """Typed reason a Sync Session could not start or continue."""

    reason: str
    label: str | None = None


@dataclass(frozen=True)
class SyncSessionMissingTools:
    """Missing external tools required before a Sync Session can start."""

    availability: SyncToolAvailability
    planning_intent: SyncPlanningIntent | None = None
    execution_intent: SyncExecutionIntent | None = None


class SyncSessionController(QObject):
    """Own PC-to-iPod Sync Session orchestration behind a small Qt seam."""

    blocked = pyqtSignal(object)
    missing_tools = pyqtSignal(object)
    planning_started = pyqtSignal()
    planning_progress = pyqtSignal(str, int, int, str)
    plan_ready = pyqtSignal(object)
    plan_failed = pyqtSignal(str)
    execution_started = pyqtSignal()
    execution_progress = pyqtSignal(object)
    execution_complete = pyqtSignal(object)
    execution_failed = pyqtSignal(str)
    partial_save_requested = pyqtSignal(int, int)

    def __init__(
        self,
        device_manager: DeviceManagerLike,
        library_cache: LibraryCacheLike,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
        quick_writes: QuickWritePreparer,
        *,
        podcast_input_provider: Callable[[], PodcastPlanningInput | None] | None = None,
        tool_availability_check: Callable[[Any], SyncToolAvailability] = check_sync_tool_availability,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_manager = device_manager
        self._library_cache = library_cache
        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._quick_writes = quick_writes
        self._podcast_input_provider = podcast_input_provider
        self._tool_availability_check = tool_availability_check
        self._planning_worker: Any | None = None
        self._podcast_plan_worker: Any | None = None
        self._execute_worker: Any | None = None
        self._cancelled_workers: list[Any] = []

    def is_running(self) -> bool:
        return (
            self._worker_is_running(self._planning_worker)
            or self._worker_is_running(self._podcast_plan_worker)
            or self._worker_is_running(self._execute_worker)
        )

    def is_executing(self) -> bool:
        return self._worker_is_running(self._execute_worker)

    def start_planning(self, intent: SyncPlanningIntent) -> None:
        if not self._device_manager.device_path:
            self.blocked.emit(SyncSessionBlocked("no_device"))
            return
        if self.is_running():
            self.blocked.emit(SyncSessionBlocked("busy"))
            return

        quick_ready, blocked_label = self._quick_writes.prepare_for_full_sync()
        if not quick_ready:
            self.blocked.emit(
                SyncSessionBlocked(
                    "quick_changes_saving",
                    blocked_label or "quick changes",
                )
            )
            return
        if self._library_cache.is_loading():
            self.blocked.emit(SyncSessionBlocked("library_loading"))
            return

        settings = self._settings_service.get_effective_settings()
        tools = self._tool_availability_check(settings)
        if tools.has_missing:
            self.missing_tools.emit(SyncSessionMissingTools(tools, intent))
            return

        request = self._build_diff_request(intent, settings)
        worker = SyncDiffWorker(request)
        self._planning_worker = worker
        worker.progress.connect(
            lambda stage, current, total, message: self.planning_progress.emit(
                stage,
                current,
                total,
                message,
            )
        )
        worker.finished.connect(
            lambda plan, w=worker: self._on_planning_finished(plan, w)
        )
        worker.error.connect(lambda error, w=worker: self._on_planning_error(error, w))
        self.planning_started.emit()
        worker.start()

    def start_execution(self, intent: SyncExecutionIntent) -> None:
        ipod_path = self._device_manager.device_path or ""
        if not ipod_path:
            self.blocked.emit(SyncSessionBlocked("no_device"))
            return
        if self.is_running():
            self.blocked.emit(SyncSessionBlocked("busy"))
            return
        if intent.plan is None or not getattr(intent.plan, "has_changes", True):
            self.blocked.emit(SyncSessionBlocked("no_changes"))
            return

        settings = self._settings_service.get_effective_settings()
        tools = self._tool_availability_check(settings)
        if tools.has_missing:
            self.missing_tools.emit(
                SyncSessionMissingTools(tools, execution_intent=intent)
            )
            return

        device_session = self._device_sessions.current_session()
        generation_getter = getattr(
            self._library_cache,
            "get_database_generation",
            None,
        )
        if callable(generation_getter):
            get_database_generation = cast(
                "Callable[[], DatabaseGeneration | None]",
                generation_getter,
            )
            expected_database_generation = get_database_generation()
        else:
            expected_database_generation = None

        worker = SyncExecuteWorker(
            ipod_path,
            intent.plan,
            settings=settings,
            skip_backup=bool(intent.skip_backup),
            backup_device_name=backup_device_name_from_playlists(
                self._library_cache.get_playlists()
            ),
            device_info=device_session.identity,
            device_capabilities=device_session.capabilities,
            device_storage=getattr(device_session, "storage", None),
            expected_database_generation=expected_database_generation,
            on_sync_complete=self._library_cache.clear_pending_sync_state,
            sync_until_full=bool(intent.sync_until_full),
        )
        self._execute_worker = worker
        worker.progress.connect(lambda progress: self.execution_progress.emit(progress))
        worker.finished.connect(
            lambda result, w=worker: self._on_execution_complete(result, w)
        )
        worker.error.connect(lambda error, w=worker: self._on_execution_error(error, w))
        worker.confirm_partial_save.connect(
            lambda added, skipped: self.partial_save_requested.emit(added, skipped)
        )
        self.execution_started.emit()
        worker.start()

    def request_execution_cancel(self) -> None:
        worker = self._execute_worker
        if worker is not None and self._worker_is_running(worker):
            worker.requestInterruption()

    def request_skip_backup(self) -> None:
        worker = self._execute_worker
        if worker is not None:
            worker.request_skip_backup()

    def request_give_up_scrobble(self) -> None:
        worker = self._execute_worker
        if worker is not None:
            worker.request_give_up_scrobble()

    def respond_to_partial_save(self, save: bool) -> None:
        worker = self._execute_worker
        if worker is not None:
            worker.respond_to_partial_save(save)

    def cancel(self) -> None:
        self._cleanup_worker(
            "_planning_worker",
            ("progress", "finished", "error"),
        )
        self._cleanup_worker(
            "_podcast_plan_worker",
            ("finished", "error"),
        )
        self._cleanup_worker(
            "_execute_worker",
            ("progress", "finished", "error", "confirm_partial_save"),
        )

    def shutdown(self, timeout_ms: int = 3000) -> None:
        for attr_name in (
            "_planning_worker",
            "_podcast_plan_worker",
            "_execute_worker",
        ):
            worker = getattr(self, attr_name, None)
            if worker is not None and self._worker_is_running(worker):
                worker.requestInterruption()
                worker.wait(timeout_ms)
            setattr(self, attr_name, None)
        for worker in list(self._cancelled_workers):
            if self._worker_is_running(worker):
                worker.requestInterruption()
                worker.wait(timeout_ms)
            self._reap_cancelled_worker(worker)

    def _build_diff_request(self, intent: SyncPlanningIntent, settings: Any) -> SyncDiffRequest:
        folder_entries = tuple(media_folder_entries_to_settings(intent.folder_entries))
        pc_folders = tuple(folder_entries)
        folder_paths = media_folder_paths(folder_entries)
        primary_pc_folder = folder_paths[0] if folder_paths else ""

        device_session = self._device_sessions.current_session()
        caps = device_session.capabilities
        supports_video = bool(caps and caps.supports_video)
        supports_podcast = bool(caps and caps.supports_podcast)
        supports_photo = bool(caps and caps.supports_photo)

        track_edits = self._library_cache.get_track_edits()
        photo_edits = self._library_cache.get_photo_edits()
        allowed_paths = None
        selected_playlist_paths = None

        if intent.mode == "selective":
            selected_track_paths = intent.selected_paths
            selected_photo_imports: Iterable[Any] = ()
            if isinstance(intent.selected_paths, dict):
                selected_track_paths = intent.selected_paths.get("tracks", ())
                selected_photo_imports = tuple(intent.selected_paths.get("photos", ()))
                selected_playlist_paths = frozenset(
                    intent.selected_paths.get("playlists", ())
                )
            allowed_paths = frozenset(selected_track_paths or ())
            photo_edits = (
                build_imported_photo_edit_state(selected_photo_imports)
                if supports_photo
                else None
            )

        sync_workers = getattr(settings, "sync_workers", 0)
        rating_strategy = getattr(settings, "rating_conflict_strategy", "ipod_wins")
        fpcalc_path = getattr(settings, "fpcalc_path", "")
        return SyncDiffRequest(
            pc_folder=primary_pc_folder,
            pc_folders=pc_folders,
            ipod_tracks=self._library_cache.get_tracks(),
            ipod_path=self._device_manager.device_path or "",
            supports_video=supports_video,
            supports_podcast=supports_podcast,
            supports_photo=supports_photo,
            track_edits=track_edits,
            photo_edits=photo_edits,
            sync_workers=sync_workers,
            rating_strategy=rating_strategy,
            existing_playlists=_existing_playlist_rows_for_sync(self._library_cache),
            fpcalc_path=fpcalc_path,
            photo_sync_settings={
                "rotate_tall_photos_for_device": (
                    settings.rotate_tall_photos_for_device
                ),
                "fit_photo_thumbnails": settings.fit_photo_thumbnails,
            },
            transcode_options=build_transcode_options(settings),
            allowed_paths=allowed_paths,
            selected_playlist_paths=selected_playlist_paths,
        )

    def _on_planning_finished(self, plan: Any, worker: Any) -> None:
        if self._planning_worker is not worker:
            return
        self._planning_worker = None
        podcast_input = self._current_podcast_input()
        supports_podcast = self._supports_podcast()
        if podcast_input is None or not podcast_input.feeds or not supports_podcast:
            self.plan_ready.emit(plan)
            return

        self.planning_progress.emit(
            "podcast_sync",
            0,
            0,
            "Refreshing podcast feeds...",
        )
        podcast_worker = PodcastPlanWorker(
            PodcastPlanRequest(
                feeds=list(podcast_input.feeds),
                ipod_tracks=self._library_cache.get_tracks() or [],
                store=podcast_input.store,
                supports_podcast=supports_podcast,
            )
        )
        self._podcast_plan_worker = podcast_worker
        podcast_worker.finished.connect(
            lambda podcast_plan, w=podcast_worker: self._on_podcast_plan_ready(
                plan,
                podcast_plan,
                w,
            )
        )
        podcast_worker.error.connect(
            lambda error, w=podcast_worker: self._on_podcast_plan_error(
                plan,
                error,
                w,
            )
        )
        podcast_worker.start()

    def _on_planning_error(self, error_msg: str, worker: Any) -> None:
        if self._planning_worker is not worker:
            return
        self._planning_worker = None
        self.plan_failed.emit(error_msg)

    def _on_podcast_plan_ready(
        self,
        plan: Any,
        podcast_plan: Any,
        worker: Any,
    ) -> None:
        if self._podcast_plan_worker is not worker:
            return
        self._podcast_plan_worker = None
        if getattr(podcast_plan, "to_add", None):
            plan.to_add.extend(podcast_plan.to_add)
            plan.storage.bytes_to_add += podcast_plan.storage.bytes_to_add
        if getattr(podcast_plan, "to_remove", None):
            plan.to_remove.extend(podcast_plan.to_remove)
            plan.storage.bytes_to_remove += podcast_plan.storage.bytes_to_remove
        self.plan_ready.emit(plan)

    def _on_podcast_plan_error(self, plan: Any, error_msg: str, worker: Any) -> None:
        if self._podcast_plan_worker is not worker:
            return
        self._podcast_plan_worker = None
        logger.warning("Failed to build podcast plan: %s", error_msg)
        self.plan_ready.emit(plan)

    def _on_execution_complete(self, result: Any, worker: Any) -> None:
        if self._execute_worker is not worker:
            return
        self._execute_worker = None
        self.execution_complete.emit(result)

    def _on_execution_error(self, error_msg: str, worker: Any) -> None:
        if self._execute_worker is not worker:
            return
        self._execute_worker = None
        self.execution_failed.emit(error_msg)

    def _current_podcast_input(self) -> PodcastPlanningInput | None:
        if self._podcast_input_provider is None:
            return None
        return self._podcast_input_provider()

    def _supports_podcast(self) -> bool:
        caps = self._device_sessions.current_session().capabilities
        return bool(caps and caps.supports_podcast)

    @staticmethod
    def _worker_is_running(worker: Any | None) -> bool:
        return bool(worker is not None and worker.isRunning())

    def _retain_cancelled_worker(self, worker: Any) -> None:
        if worker in self._cancelled_workers:
            return
        self._cancelled_workers.append(worker)
        try:
            QThread.finished.__get__(worker, type(worker)).connect(
                lambda w=worker: self._reap_cancelled_worker(w)
            )
        except Exception:
            pass

    def _reap_cancelled_worker(self, worker: Any) -> None:
        for attr_name in (
            "_planning_worker",
            "_podcast_plan_worker",
            "_execute_worker",
        ):
            if getattr(self, attr_name, None) is worker:
                setattr(self, attr_name, None)
        try:
            self._cancelled_workers.remove(worker)
        except ValueError:
            pass
        try:
            worker.deleteLater()
        except (AttributeError, RuntimeError):
            pass

    def _cleanup_worker(self, attr_name: str, signal_names: tuple[str, ...]) -> None:
        worker = getattr(self, attr_name, None)
        if worker is None:
            return
        if self._worker_is_running(worker):
            worker.requestInterruption()
        for signal_name in signal_names:
            try:
                getattr(worker, signal_name).disconnect()
            except (AttributeError, TypeError, RuntimeError):
                pass
        setattr(self, attr_name, None)
        if self._worker_is_running(worker):
            self._retain_cancelled_worker(worker)
        else:
            self._reap_cancelled_worker(worker)


def _existing_playlist_rows_for_sync(cache: LibraryCacheLike | None) -> tuple[dict, ...]:
    data = cache.get_data() if cache else None
    if not data:
        return ()
    rows: list[dict] = []
    for key in ("mhlp", "mhlp_podcast", "mhlp_smart"):
        for playlist in data.get(key, []):
            if isinstance(playlist, dict):
                rows.append(dict(playlist))
    return tuple(rows)
