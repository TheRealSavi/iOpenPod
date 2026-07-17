"""Typed public models for the new SyncEngine lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class EngineOperation(StrEnum):
    """Top-level SyncEngine operation."""

    PLAN = "plan"
    EXECUTE = "execute"
    QUICK_WRITE = "quick_write"


class EngineStage(StrEnum):
    """Canonical lifecycle stage names emitted by the engine facade."""

    LOAD = "load"
    MIGRATE = "migrate"
    NORMALIZE = "normalize"
    SCAN = "scan"
    IDENTIFY = "identify"
    PLAN = "plan"
    VALIDATE = "validate"
    EXECUTE_FILES = "execute_files"
    ASSEMBLE_COMMIT = "assemble_commit"
    COMMIT = "commit"
    POST_COMMIT = "post_commit"
    COMPLETE = "complete"


class EngineTransactionPolicy(StrEnum):
    """How cancellation/failure should treat already-completed mutations."""

    USER_CHOICE = "user_choice"
    CONSISTENT_PARTIALS = "consistent_partials"
    ALL_OR_NOTHING = "all_or_nothing"


@dataclass(frozen=True, slots=True)
class EngineDiagnostic:
    """Structured warning/error emitted by a lifecycle stage."""

    stage: EngineStage
    code: str
    message: str
    fatal: bool = False


@dataclass(frozen=True, slots=True)
class EngineProgress:
    """Normalized progress event for all engine operations."""

    stage: EngineStage | str
    current: int = 0
    total: int = 0
    message: str = ""
    legacy_event: Any = None


EngineProgressCallback = Callable[[EngineProgress], None]


@dataclass(frozen=True, slots=True)
class EngineOptions:
    """Execution and planning knobs shared by engine operations."""

    supports_video: bool = True
    supports_podcast: bool = True
    supports_photo: bool = True
    sync_workers: int = 0
    device_write_workers: int = 0
    rating_strategy: str = "ipod_wins"
    fpcalc_path: str = ""
    transcode_options: Any = None
    transcode_cache_dir: str = ""
    max_cache_size_gb: float = 10.0
    photo_sync_settings: Mapping[str, bool] | None = None
    allowed_paths: frozenset[str] | None = None
    selected_playlist_paths: frozenset[str] | None = None
    dry_run: bool = False
    write_back_to_pc: bool = False
    compute_sound_check: bool = False
    scrobble_on_sync: bool = False
    listenbrainz_token: str = ""
    listenbrainz_username: str = ""
    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""
    lastfm_session_key: str = ""
    lastfm_username: str = ""
    sync_until_full: bool = False
    transaction_policy: EngineTransactionPolicy = EngineTransactionPolicy.USER_CHOICE


@dataclass(frozen=True, slots=True)
class EngineRequest:
    """Single typed request accepted by :class:`SyncEngine`."""

    operation: EngineOperation
    ipod_path: str | Path = ""
    pc_folders: tuple[Any, ...] = ()
    ipod_tracks: tuple[dict, ...] = ()
    existing_playlists: tuple[dict, ...] = ()
    track_edits: Mapping[int, dict[str, tuple]] | None = None
    photo_edits: Any = None
    plan: Any = None
    mapping: Any = None
    tracks_data: tuple[dict, ...] = ()
    playlists_data: tuple[dict, ...] = ()
    artwork_sources: Mapping[int, str] | None = None
    options: EngineOptions = field(default_factory=EngineOptions)
    device_info: Any = None
    device_capabilities: Any = None
    device_storage: Any = None
    expected_database_generation: Any = None
    progress_callback: EngineProgressCallback | None = None
    is_cancelled: Callable[[], bool] | None = None
    is_scrobble_cancelled: Callable[[], bool] | None = None
    on_cancel_with_partial: Callable[[int, int], bool] | None = None
    on_sync_complete: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True)
class EngineOutcome:
    """Typed result from a full engine lifecycle run."""

    operation: EngineOperation
    success: bool
    result: Any = None
    diagnostics: tuple[EngineDiagnostic, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(diagnostic.fatal for diagnostic in self.diagnostics)
