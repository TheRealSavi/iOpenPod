"""
Sync Executor - Executes a sync plan to synchronize PC library with iPod.

The executor takes a SyncPlan (from FingerprintDiffEngine) and:
1. Copies/transcodes new tracks to iPod
2. Removes deleted tracks from iPod
3. Updates metadata for changed tracks
4. Re-copies files that changed on PC
5. Records play counts from iPod, scrobbles to connected services
6. Builds a final list[TrackInfo] and calls write_itunesdb() ONCE

The database is always fully rewritten (not patched incrementally).
"""

import errno
import logging
import os
import shutil
import stat
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from iopenpod.device.durability import (
    durable_replace,
    durable_unlink,
    flush_filesystem,
    flush_parent_directory,
    flush_written_file,
)
from iopenpod.device.filesystem_profile import FilesystemProfile
from iopenpod.device.metadata_write import DeviceMetadataWriteSession
from iopenpod.device.path_safety import (
    UnsafeDevicePathError,
    resolve_device_path,
)
from iopenpod.device.storage_safety import (
    allocated_size,
    effective_max_file_size_bytes,
    require_file_size_supported,
)
from iopenpod.device.write_guard import (
    DatabaseGeneration,
    DeviceWriteGuard,
    DeviceWriteSafetyError,
)
from iopenpod.device.write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)
from iopenpod.itunesdb_shared.constants import (
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VIDEO_PODCAST,
)
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo

from ._formats import MEDIA_EXTENSIONS as _MEDIA_EXTENSIONS
from .album_chapters import (
    ResolvedAlbumSource,
    convert_album_to_chaptered_track,
)
from .audio_fingerprint import get_or_compute_fingerprint_with_status
from .capability_filter import (
    is_track_supported_by_device,
    unsupported_track_reason,
)
from .contracts import (
    SYNC_DB_OVERHEAD_BYTES,
    SYNC_DB_WRITE_RESERVE_BYTES,
    SYNC_DISK_RESERVE_BYTES,
    SYNC_UNTIL_FULL_RESERVE_BYTES,
    SyncItem,
    SyncOutcome,
    SyncPlan,
    SyncProgress,
    SyncRequest,
    sync_plan_required_free_bytes,
)
from .database_commit import (
    DatabaseCommitPayload,
    apply_itunes_protections_from_tracks,
    write_database_commit,
)
from .ipod_track_paths import (
    expected_ipod_track_file_path,
    ipod_location_from_file_path,
)
from .mapping import MappingFile, MappingManager
from .path_identity import coerce_int, stable_path_key
from .photos import apply_photo_sync_plan, read_photo_db
from .plan_validator import validate_sync_plan
from .source_identity import source_content_hash
from .transcoder import (
    TranscodeOptions,
    TranscodePlan,
    TranscodeTarget,
    quality_to_nominal_bitrate,
    resolve_transcode_plan,
    strip_metadata,
    transcode,
)
from .transcoder import (
    clear_caches as _clear_transcoder_caches,
)

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

# Minimum free space (bytes) that must remain on the iPod after each file copy.
_DISK_RESERVE_BYTES = SYNC_DISK_RESERVE_BYTES

# Minimum free space required before attempting to write the database.
# Smaller than _DISK_RESERVE_BYTES so a sync that fills the iPod to ~4 MB
# remaining can still commit its database.
_DB_WRITE_RESERVE_BYTES = SYNC_DB_WRITE_RESERVE_BYTES

# Estimated overhead for the database files themselves.
_DB_OVERHEAD_BYTES = SYNC_DB_OVERHEAD_BYTES

_SYNC_UNTIL_FULL_RESERVE_BYTES = SYNC_UNTIL_FULL_RESERVE_BYTES

# Default number of Fxx music directories (most common across iPod models).
_DEFAULT_MUSIC_DIRS = 20


def _mhsd5_type_value(playlist: dict) -> int:
    return coerce_int(playlist.get("mhsd5_type", 0))


def _is_ipod_category_playlist(playlist: dict) -> bool:
    dataset_type = coerce_int(playlist.get("_mhsd_dataset_type", 0))
    if dataset_type:
        return dataset_type == 5
    return playlist.get("_source") == "category" or bool(_mhsd5_type_value(playlist))


def _playlist_dataset_type(playlist: dict) -> int:
    dataset_type = coerce_int(playlist.get("_mhsd_dataset_type", 0))
    if dataset_type:
        return dataset_type
    if playlist.get("_mhsd_result_key") == "mhlp_podcast":
        return 3
    if playlist.get("_mhsd_result_key") == "mhlp_smart":
        return 5
    if _is_ipod_category_playlist(playlist):
        return 5
    if playlist.get("podcast_flag", 0) == 1 or playlist.get("_source") == "podcast":
        return 3
    return 2 if playlist.get("playlist_id") else 0


def _playlist_result_key_for_dataset(dataset_type: int) -> str:
    return {2: "mhlp", 3: "mhlp_podcast", 5: "mhlp_smart"}.get(
        dataset_type,
        "mhlp",
    )


def _playlist_row_for_dataset(playlist: dict, dataset_type: int) -> dict:
    row = dict(playlist)
    row["_mhsd_dataset_type"] = dataset_type
    row["_mhsd_result_key"] = _playlist_result_key_for_dataset(dataset_type)
    if dataset_type in (2, 3):
        row.setdefault("_source", "regular")
    return row


def _is_regular_playlist_mirror_candidate(playlist: dict) -> bool:
    dataset_type = _playlist_dataset_type(playlist)
    if dataset_type not in (0, 2):
        return False
    if _is_ipod_category_playlist(playlist):
        return False
    if playlist.get("podcast_flag", 0) == 1 or playlist.get("_source") == "podcast":
        return False
    return True


def _format_bytes(val: int) -> str:
    """Format bytes as compact human-readable text for progress messages."""
    value = float(max(0, val))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _write_permission_failure_detail(error: OSError) -> str:
    return str(error).strip() or error.__class__.__name__


def _strict_device_path_stat(
    path: Path,
    *,
    action: str,
) -> os.stat_result | None:
    """Stat a device path without treating an I/O failure as absence."""
    try:
        return path.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"Could not safely inspect the iPod path before {action}: {exc}"
        ) from exc


class _OutOfSpaceError(Exception):
    """Raised when iPod disk space drops below the disk safety reserve."""
    pass


class _CancelledError(Exception):
    """Raised when a copy/transcode detects user cancellation."""
    pass


def _current_source_stat(pc_track) -> tuple[int, float]:
    """Re-stat the PC source file to get its current size and mtime.

    The fingerprinting phase writes the acoustic fingerprint tag back
    into the source file (FLAC, OGG, etc.), which changes its size and
    mtime *after* the initial scan.  If we record the pre-fingerprint
    values in the mapping, the next sync sees a "changed" file and
    re-copies/re-transcodes unnecessarily.

    Falls back to the values from the scan if stat fails (e.g. the
    file was on removable media that's gone).
    """
    try:
        st = os.stat(pc_track.path)
        return st.st_size, st.st_mtime
    except OSError:
        return pc_track.size, pc_track.mtime


def _current_source_identity(pc_track) -> tuple[int, float, str | None]:
    """Return current source size, mtime, and metadata-insensitive content hash."""
    source_size, source_mtime = _current_source_stat(pc_track)
    try:
        source_hash = source_content_hash(pc_track.path)
    except OSError:
        source_hash = None
    return source_size, source_mtime, source_hash


_SourceIdentitySnapshot = tuple[int, float, str | None]


@dataclass
class _SyncContext:
    """Shared mutable state flowing through all sync stages.

    Created once by ``execute()`` and threaded through every ``_execute_*``
    method, eliminating the 8-14 parameter explosion that previously made
    each call site hard to read.
    """

    # ── Inputs (set once, read-only during sync) ────────────────────
    plan: SyncPlan
    mapping: MappingFile
    progress_callback: Callable[["SyncProgress"], None] | None
    dry_run: bool
    write_back_to_pc: bool
    _is_cancelled: Callable[[], bool] | None
    sync_until_full: bool = False

    # ── GUI-decoupled inputs (passed forward, not pulled from GUI) ──
    on_sync_complete: Callable[[], None] | None = None
    compute_sound_check: bool = False
    scrobble_on_sync: bool = False
    listenbrainz_token: str = ""
    listenbrainz_username: str = ""
    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""
    lastfm_session_key: str = ""
    lastfm_username: str = ""
    _is_scrobble_cancelled: Callable[[], bool] | None = None

    # ── Result accumulator ──────────────────────────────────────────
    result: SyncOutcome = field(default_factory=lambda: SyncOutcome(success=True))

    # ── Existing iPod database (populated by _load_existing_database) ──
    existing_tracks_data: list[dict] = field(default_factory=list)
    existing_dataset2_standard_playlists_raw: list[dict] = field(default_factory=list)
    existing_dataset3_podcast_playlists_raw: list[dict] = field(default_factory=list)
    existing_dataset5_smart_playlists_raw: list[dict] = field(default_factory=list)

    # ── Track state (mutated by stage methods) ──────────────────────
    tracks_by_db_track_id: dict[int, TrackInfo] = field(default_factory=dict)
    tracks_by_location: dict[str, TrackInfo] = field(default_factory=dict)
    new_tracks: list[TrackInfo] = field(default_factory=list)

    # ── Fingerprint/source tracking for new-track backpatch ─────────
    new_track_fingerprints: dict[int, str] = field(default_factory=dict)
    new_track_info: dict[int, tuple] = field(default_factory=dict)
    sync_item_source_identities: dict[int, _SourceIdentitySnapshot] = field(default_factory=dict)
    conversion_group_add_counts: dict[str, int] = field(default_factory=dict)
    conversion_group_success_counts: dict[str, int] = field(default_factory=dict)
    completed_conversion_groups: set[str] = field(default_factory=set)
    pc_file_paths: dict[int, str] = field(default_factory=dict)
    final_photo_db: object | None = None
    database_committed: bool = False
    device_changes_committed: bool = False
    integrity_orphans_removed: int = 0
    write_guard: DeviceWriteGuard | None = None
    filesystem_profile: FilesystemProfile | None = None

    _cancel_recorded: bool = False

    def cancelled(self) -> bool:
        """Check if the user cancelled.  Updates *result* once."""
        if self._is_cancelled and self._is_cancelled():
            if not self._cancel_recorded:
                self._cancel_recorded = True
                self.result.errors.append(("cancelled", "Sync was cancelled by user"))
                self.result.success = False
            return True
        return False

    def is_cancelled(self) -> bool:
        """CancelToken-compatible alias used by streaming downloads."""
        return self.cancelled()

    def progress(self, stage: str, current: int, total: int,
                 current_item: Optional["SyncItem"] = None,
                 message: str = "", **kwargs) -> None:
        """Send a progress update (no-op when no callback is set)."""
        if self.progress_callback:
            self.progress_callback(
                SyncProgress(stage, current, total, current_item, message, **kwargs)
            )


@dataclass(frozen=True, slots=True)
class _FileMutationSummary:
    """Completed file mutations that must be reflected in the database."""

    added: int = 0
    removed: int = 0
    updated: int = 0

    @property
    def anything_done(self) -> bool:
        return self.added > 0 or self.removed > 0 or self.updated > 0


@dataclass(frozen=True, slots=True)
class _ExecutionLifecycle:
    """Callbacks and policy used while running one executor lifecycle."""

    on_cancel_with_partial: Callable[[int, int], bool] | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedPlaylistCommitPayload:
    """Final playlist state to serialize during database commit."""

    master_playlist_name: str
    master_playlist_id: int | None
    standard_playlists: list[PlaylistInfo]
    podcast_master_playlist_name: str
    podcast_master_playlist_id: int | None
    podcast_playlists: list[PlaylistInfo]
    smart_playlists: list[PlaylistInfo]


@dataclass(slots=True)
class _ScrobbleServiceOutcome:
    """Executor-level result for one external scrobbling service."""

    service_key: str
    display_name: str
    stage: str
    accepted: int = 0
    errors: list[str] = field(default_factory=list)
    gave_up: bool = False


class SyncExecutor:
    """
    Executes a sync plan to synchronize PC library with iPod.

    Features:
    - Transcode cache: Avoids re-transcoding for multiple iPods
    - Round-robin file distribution across F00-F49 folders
    - Full database rewrite: builds final list[TrackInfo], writes once

    Usage:
        executor = SyncExecutor(ipod_path)
        result = executor.execute_request(request)
    """

    def __init__(
        self,
        ipod_path: str | Path,
        cache_dir: Path | None = None,
        max_workers: int = 0,
        max_device_write_workers: int = 0,
        max_cache_size_gb: float = 5.0,
        fpcalc_path: str = "",
        photo_sync_settings: dict[str, bool] | None = None,
        transcode_options: TranscodeOptions | None = None,
        device_info: object | None = None,
        device_capabilities: object | None = None,
        device_storage: object | None = None,
        expected_database_generation: DatabaseGeneration | None = None,
    ):
        from .transcode_cache import TranscodeCache

        self.ipod_path = Path(ipod_path)
        self.music_dir = self.ipod_path / "iPod_Control" / "Music"
        self.mapping_manager = MappingManager(ipod_path)
        self.transcode_cache = TranscodeCache.get_instance(
            cache_dir,
            max_cache_size_gb=max_cache_size_gb,
        )
        self.fpcalc_path = fpcalc_path
        self.photo_sync_settings = photo_sync_settings
        self.transcode_options = transcode_options or TranscodeOptions()
        self.device_info = device_info
        self.device_capabilities = device_capabilities
        self.device_storage = device_storage
        self.expected_database_generation = expected_database_generation
        self._filesystem_profile: FilesystemProfile | None = None

        self._folder_counter = 0
        self._folder_lock = threading.Lock()
        self._space_guard_lock = threading.Lock()
        self._metadata_strip_lock = threading.Lock()
        self._reset_metadata_strip_summary()

        # 0 = auto (CPU count, capped at 8), 1 = sequential
        if max_workers <= 0:
            self._max_workers = min(os.cpu_count() or 4, 8)
        else:
            self._max_workers = max_workers
        self._max_device_write_workers = self._resolve_device_write_workers(
            max_device_write_workers,
            self._max_workers,
            device_info,
        )
        self._device_write_semaphore = threading.Semaphore(
            self._max_device_write_workers
        )

    @staticmethod
    def _is_likely_hdd_device(device_info: object | None) -> bool:
        if device_info is None:
            return False

        family = str(getattr(device_info, "model_family", "") or "").strip().lower()
        if not family:
            return False

        if any(token in family for token in ("nano", "shuffle")):
            return False
        if any(token in family for token in ("classic", "video", "photo", "mini")):
            return True
        return family.startswith("ipod")

    @classmethod
    def _resolve_device_write_workers(
        cls,
        configured_write_workers: int,
        max_workers: int,
        device_info: object | None,
    ) -> int:
        overall_workers = max(1, max_workers)
        if configured_write_workers > 0:
            return max(1, min(configured_write_workers, overall_workers))

        if device_info is None:
            return overall_workers

        auto_workers = (
            1 if cls._is_likely_hdd_device(device_info) else min(overall_workers, 4)
        )
        return max(1, min(auto_workers, overall_workers))

    # ── Public API ──────────────────────────────────────────────────────────

    def execute_request(self, request: SyncRequest) -> SyncOutcome:
        """Execute a typed request object."""
        # Be tolerant of older callers that may still construct SyncRequest
        # without the ListenBrainz username field.
        listenbrainz_username = getattr(request, "listenbrainz_username", "")
        lastfm_api_key = getattr(request, "lastfm_api_key", "")
        lastfm_api_secret = getattr(request, "lastfm_api_secret", "")
        lastfm_session_key = getattr(request, "lastfm_session_key", "")
        lastfm_username = getattr(request, "lastfm_username", "")
        sync_until_full = bool(getattr(request, "sync_until_full", False))

        _clear_transcoder_caches()

        ctx = self._build_sync_context(
            plan=request.plan,
            mapping=request.mapping,
            progress_callback=request.progress_callback,
            dry_run=request.dry_run,
            is_cancelled=request.is_cancelled,
            write_back_to_pc=request.write_back_to_pc,
            on_sync_complete=request.on_sync_complete,
            compute_sound_check=request.compute_sound_check,
            scrobble_on_sync=request.scrobble_on_sync,
            listenbrainz_token=request.listenbrainz_token,
            listenbrainz_username=listenbrainz_username,
            lastfm_api_key=lastfm_api_key,
            lastfm_api_secret=lastfm_api_secret,
            lastfm_session_key=lastfm_session_key,
            lastfm_username=lastfm_username,
            is_scrobble_cancelled=request.is_scrobble_cancelled,
            sync_until_full=sync_until_full,
        )
        lifecycle = _ExecutionLifecycle(
            on_cancel_with_partial=request.on_cancel_with_partial,
        )

        logger.info(
            "Sync executor using %d overall workers and %d device write workers",
            self._max_workers,
            self._max_device_write_workers,
        )

        self._reset_metadata_strip_summary()
        try:
            if ctx.dry_run:
                self._run_execution_lifecycle(ctx, lifecycle)
            else:
                try:
                    reported_format = str(
                        getattr(
                            self.device_storage,
                            "reported_volume_format",
                            "",
                        )
                        or ""
                    )
                    profile = inspect_device_write_readiness(
                        self.ipod_path,
                        reported_volume_format=reported_format,
                    )
                    current_volume_key = volume_lock_key(profile)
                    expected_volume_key = str(
                        getattr(
                            self.device_storage,
                            "volume_identity_key",
                            "",
                        )
                        or ""
                    )
                    if (
                        expected_volume_key
                        and current_volume_key != expected_volume_key
                    ):
                        raise DeviceWriteSafetyError(
                            "A different volume is mounted at the selected iPod "
                            "path. iOpenPod stopped before writing."
                        )
                    self._filesystem_profile = profile
                    ctx.filesystem_profile = profile
                    with DeviceWriteGuard(
                        self.ipod_path,
                        volume_key=current_volume_key,
                        expected_database_generation=(
                            self.expected_database_generation
                        ),
                    ) as write_guard:
                        profile = revalidate_device_write_readiness(
                            profile,
                            probe_case_sensitivity=True,
                        )
                        self._filesystem_profile = profile
                        ctx.filesystem_profile = profile
                        ctx.write_guard = write_guard
                        self._run_execution_lifecycle(ctx, lifecycle)
                except DeviceWriteSafetyError as exc:
                    logger.error("Sync stopped by device safety guard: %s", exc)
                    ctx.result.errors.append(("filesystem_safety", str(exc)))
                    ctx.result.success = False
        finally:
            self._log_metadata_strip_summary()
        return ctx.result

    def _reset_metadata_strip_summary(self) -> None:
        self._metadata_stripped_files = 0
        self._metadata_saved_bytes = 0
        self._metadata_strip_failures = 0
        self._metadata_strip_failure_exts: Counter[str] = Counter()

    def _record_metadata_strip(self, saved_bytes: int) -> None:
        if saved_bytes <= 0:
            return
        with self._metadata_strip_lock:
            self._metadata_stripped_files += 1
            self._metadata_saved_bytes += saved_bytes

    def _record_metadata_strip_failure(self, suffix: str) -> None:
        with self._metadata_strip_lock:
            self._metadata_strip_failures += 1
            self._metadata_strip_failure_exts[suffix or "<none>"] += 1

    def _log_metadata_strip_summary(self) -> None:
        with self._metadata_strip_lock:
            stripped_files = self._metadata_stripped_files
            saved_bytes = self._metadata_saved_bytes
            failures = self._metadata_strip_failures
            failure_exts = self._metadata_strip_failure_exts.copy()

        if stripped_files:
            logger.debug(
                "Metadata stripping: removed tags from %d file(s), saved %s",
                stripped_files,
                _format_bytes(saved_bytes),
            )
        if failures:
            ext_text = ""
            if failure_exts:
                by_ext = ", ".join(
                    f"{ext}={count}"
                    for ext, count in sorted(failure_exts.items())
                )
                ext_text = f" By extension: {by_ext}"
            logger.warning(
                "Could not strip metadata from %d file(s); copied unmodified payloads.%s",
                failures,
                ext_text,
            )

    def _build_sync_context(
        self,
        *,
        plan: SyncPlan,
        mapping: MappingFile,
        progress_callback: Callable[[SyncProgress], None] | None,
        dry_run: bool,
        is_cancelled: Callable[[], bool] | None,
        write_back_to_pc: bool,
        on_sync_complete: Callable[[], None] | None,
        compute_sound_check: bool,
        scrobble_on_sync: bool,
        listenbrainz_token: str,
        listenbrainz_username: str,
        lastfm_api_key: str,
        lastfm_api_secret: str,
        lastfm_session_key: str,
        lastfm_username: str,
        is_scrobble_cancelled: Callable[[], bool] | None,
        sync_until_full: bool,
    ) -> _SyncContext:
        ctx = _SyncContext(
            plan,
            mapping,
            progress_callback,
            dry_run,
            write_back_to_pc,
            is_cancelled,
        )
        ctx.sync_until_full = bool(sync_until_full)
        ctx.on_sync_complete = on_sync_complete
        ctx.compute_sound_check = compute_sound_check
        ctx.scrobble_on_sync = scrobble_on_sync
        ctx.listenbrainz_token = listenbrainz_token
        ctx.listenbrainz_username = listenbrainz_username
        ctx.lastfm_api_key = lastfm_api_key
        ctx.lastfm_api_secret = lastfm_api_secret
        ctx.lastfm_session_key = lastfm_session_key
        ctx.lastfm_username = lastfm_username
        ctx._is_scrobble_cancelled = is_scrobble_cancelled
        return ctx

    def _run_execution_lifecycle(
        self,
        ctx: _SyncContext,
        lifecycle: _ExecutionLifecycle,
    ) -> None:
        """Run one sync in ordered phases from plan to database commit."""

        if not self._prepare_execution_plan(ctx):
            return
        if not self._run_preflight_phase(ctx):
            return

        flush_ok = True
        try:
            self._run_file_mutation_phase(ctx)
            self._run_database_commit_phase(ctx, lifecycle)
        finally:
            if not ctx.dry_run:
                try:
                    # Never run a mount-scoped flush against a path that may
                    # now refer to a replacement volume or an ordinary host
                    # directory after the iPod was unplugged.
                    self._revalidate_device_write_readiness()
                    flush_ok, flush_message = flush_filesystem(self.ipod_path)
                except DeviceWriteSafetyError as exc:
                    flush_ok = False
                    flush_message = (
                        "filesystem flush was skipped because the selected "
                        f"iPod mount is no longer safe: {exc}"
                    )
                except Exception as exc:
                    flush_ok = False
                    flush_message = f"filesystem flush failed: {exc}"

                if flush_ok:
                    logger.info(
                        "Sync filesystem flush completed: mount=%s result=%s",
                        self.ipod_path,
                        flush_message,
                    )
                else:
                    logger.error(
                        "Sync filesystem flush failed: mount=%s result=%s",
                        self.ipod_path,
                        flush_message,
                    )
                    ctx.result.errors.append((
                        "filesystem_flush",
                        flush_message,
                    ))
        if (ctx.database_committed or ctx.device_changes_committed) and flush_ok:
            self._clear_gui_cache(ctx)
        ctx.result.success = not ctx.result.has_errors

    def _prepare_execution_plan(self, ctx: _SyncContext) -> bool:
        """Normalize plan inputs before touching the device."""

        self._apply_device_capability_filters(ctx)
        validation = validate_sync_plan(ctx.plan)
        for issue in validation.warnings:
            logger.warning("Sync plan warning [%s]: %s", issue.code, issue.message)
        if not validation.is_valid:
            for issue in validation.errors:
                ctx.result.errors.append((issue.code, issue.message))
            ctx.result.success = False
            logger.error(
                "Sync plan validation failed with %d error(s)",
                len(validation.errors),
            )
            return False
        self._prepare_conversion_group_counts(ctx)
        if not ctx.plan.has_changes:
            ctx.result.success = not ctx.result.has_errors
            return False
        return True

    def _run_preflight_phase(self, ctx: _SyncContext) -> bool:
        """Validate device state and load existing database records."""

        if not self._preflight_checks(ctx):
            return False
        self._load_existing_database_into(ctx)
        if not self._validate_loaded_database_targets(ctx):
            return False
        return True

    def _validate_loaded_database_targets(self, ctx: _SyncContext) -> bool:
        """Reject plans whose target database rows disappeared before execute."""

        missing: list[tuple[str, str]] = []
        unsafe_paths: list[tuple[str, str]] = []

        def _check_safe_location(
            bucket: str,
            item: SyncItem,
            location: str,
        ) -> None:
            if location and expected_ipod_track_file_path(
                self.ipod_path,
                location,
            ) is None:
                unsafe_paths.append((
                    bucket,
                    f"{item.display_label} has an unsafe iPod media path: {location}",
                ))

        def _check_db_items(bucket: str, items: list[SyncItem]) -> None:
            for item in items:
                db_track_id = coerce_int(item.db_track_id)
                if db_track_id and db_track_id in ctx.tracks_by_db_track_id:
                    if bucket == "to_update_file":
                        current = ctx.tracks_by_db_track_id[db_track_id]
                        _check_safe_location(
                            bucket,
                            item,
                            str(current.location or item.ipod_location or ""),
                        )
                    continue
                missing.append((
                    bucket,
                    (
                        f"{item.display_label} targets db_track_id "
                        f"{db_track_id or '?'} but that track is not in the "
                        "current iPod database."
                    ),
                ))

        _check_db_items("to_update_metadata", ctx.plan.to_update_metadata)
        _check_db_items("to_update_file", ctx.plan.to_update_file)
        _check_db_items("to_update_artwork", ctx.plan.to_update_artwork)
        _check_db_items("to_sync_playcount", ctx.plan.to_sync_playcount)
        _check_db_items("to_sync_rating", ctx.plan.to_sync_rating)

        for bucket, items in (
            ("to_remove", ctx.plan.to_remove),
            ("_integrity_removals", getattr(ctx.plan, "_integrity_removals", [])),
        ):
            for item in items:
                db_track_id = coerce_int(item.db_track_id)
                location = item.ipod_location
                if db_track_id and db_track_id in ctx.tracks_by_db_track_id:
                    current = ctx.tracks_by_db_track_id[db_track_id]
                    _check_safe_location(
                        bucket,
                        item,
                        str(current.location or location or ""),
                    )
                    continue
                if location and location in ctx.tracks_by_location:
                    _check_safe_location(bucket, item, location)
                    continue
                missing.append((
                    bucket,
                    (
                        f"{item.display_label} is planned for removal, but "
                        "its target track is not in the current iPod database."
                    ),
                ))

        if not missing and not unsafe_paths:
            return True

        for code, message in missing:
            ctx.result.errors.append((f"stale_plan_{code}", message))
        for code, message in unsafe_paths:
            ctx.result.errors.append((f"unsafe_device_path_{code}", message))
        ctx.result.success = False
        logger.error(
            "Sync plan target validation failed: missing=%d unsafe_paths=%d",
            len(missing),
            len(unsafe_paths),
        )
        return False

    def _run_file_mutation_phase(self, ctx: _SyncContext) -> None:
        """Apply file and in-memory mutations before database commit."""

        self._execute_file_mutation_phases(ctx)

    def _run_database_commit_phase(
        self,
        ctx: _SyncContext,
        lifecycle: _ExecutionLifecycle,
    ) -> None:
        """Persist database state required by completed mutations."""

        self._commit_file_mutations(
            ctx,
            on_cancel_with_partial=lifecycle.on_cancel_with_partial,
        )

    def _execute_file_mutation_phases(self, ctx: _SyncContext) -> None:
        """Run all pre-commit mutation phases in deterministic order."""

        for stage in self._file_mutation_phases():
            if ctx.cancelled():
                break
            stage(ctx)
            if not ctx.result.success:
                break

    def _file_mutation_phases(self) -> tuple[Callable[[_SyncContext], None], ...]:
        """File and in-memory mutation stages that precede database commit."""

        return (
            self._execute_integrity_housekeeping,
            self._execute_removes,
            self._execute_file_updates,
            self._execute_metadata_updates,
            self._execute_artwork_updates,
            self._download_podcast_episodes,
            self._execute_adds,
            self._execute_deferred_replacement_removes,
            self._execute_sound_check,
            self._execute_playcount_sync,
            self._execute_rating_sync,
        )

    def _commit_file_mutations(
        self,
        ctx: _SyncContext,
        *,
        on_cancel_with_partial: Callable[[int, int], bool] | None,
    ) -> None:
        """Commit the database state required by completed file mutations."""

        if ctx.dry_run:
            return

        if self._is_integrity_housekeeping_only(ctx.plan):
            self._commit_integrity_housekeeping(ctx)
            return

        was_cancelled = ctx.cancelled()
        had_failure = not ctx.result.success
        summary = self._file_mutation_summary(ctx)
        should_write = True

        if was_cancelled and summary.anything_done and on_cancel_with_partial is not None:
            n_planned = len(getattr(ctx.plan, "to_add", []))
            n_skipped = max(0, n_planned - summary.added)
            should_write = on_cancel_with_partial(summary.added, n_skipped)
            logger.info(
                "User chose to %s partial sync results (%d added).",
                "save" if should_write else "discard",
                summary.added,
            )

        if should_write and (was_cancelled or had_failure):
            self._write_partial_database(ctx, summary, was_cancelled=was_cancelled)
            return

        if not should_write:
            self._handle_discarded_partial_commit(ctx, summary)
            return

        self._execute_write_and_finalize(ctx)

    @staticmethod
    def _is_integrity_housekeeping_only(plan: SyncPlan) -> bool:
        """Return True when execution needs no iTunesDB rewrite."""
        database_changes = any((
            plan.to_add,
            plan.to_remove,
            plan.to_update_metadata,
            plan.to_update_file,
            plan.to_update_artwork,
            plan.to_sync_playcount,
            plan.to_sync_rating,
            plan._integrity_removals,
            plan.playlists_to_add,
            plan.playlists_to_edit,
            plan.playlists_to_remove,
            plan.photo_plan and plan.photo_plan.has_changes,
        ))
        housekeeping = bool(
            plan.has_integrity_housekeeping or plan._refreshed_podcast_feeds
        )
        return bool(housekeeping and not database_changes)

    def _commit_integrity_housekeeping(self, ctx: _SyncContext) -> None:
        """Persist mapping-only maintenance without rewriting iTunesDB."""
        if ctx.cancelled() or not ctx.result.success:
            return

        mapping_saved = False
        if ctx.plan._mapping_requires_persistence:
            self._revalidate_device_write_readiness()
            if self.mapping_manager.save(ctx.mapping) is False:
                ctx.result.errors.append((
                    "mapping",
                    "Could not safely save the cleaned iPod mapping file.",
                ))
                ctx.result.success = False
                return
            mapping_saved = True

        podcast_metadata_saved = False
        if ctx.plan._refreshed_podcast_feeds:
            self._update_podcast_subscriptions(ctx)
            podcast_metadata_saved = True

        if (
            mapping_saved
            or podcast_metadata_saved
            or ctx.integrity_orphans_removed
        ):
            ctx.device_changes_committed = True

    @staticmethod
    def _file_mutation_summary(ctx: _SyncContext) -> _FileMutationSummary:
        return _FileMutationSummary(
            added=len(ctx.new_tracks),
            removed=ctx.result.tracks_removed,
            updated=ctx.result.tracks_updated_file,
        )

    def _write_partial_database(
        self,
        ctx: _SyncContext,
        summary: _FileMutationSummary,
        *,
        was_cancelled: bool,
    ) -> None:
        ctx.result.partial_save = True

        if was_cancelled and not any(e[0] == "cancelled" for e in ctx.result.errors):
            ctx.result.errors.append((
                "cancelled",
                self._partial_commit_message(summary),
            ))

        logger.info(
            "Sync stopped early — attempting partial database write "
            "(%d existing + %d newly added tracks).",
            len(ctx.tracks_by_db_track_id),
            summary.added,
        )
        self._execute_write_and_finalize(ctx)

    @staticmethod
    def _partial_commit_message(summary: _FileMutationSummary) -> str:
        parts = []
        if summary.added > 0:
            parts.append(f"{summary.added} track{'s' if summary.added != 1 else ''} copied")
        if summary.removed > 0:
            parts.append(f"{summary.removed} track{'s' if summary.removed != 1 else ''} removed")
        if summary.updated > 0:
            parts.append(f"{summary.updated} file{'s' if summary.updated != 1 else ''} updated")

        if parts:
            return (
                f"Sync was cancelled after {', '.join(parts)}. "
                "The database has been updated with those changes."
            )
        return "Sync was cancelled. No file changes had been made."

    def _handle_discarded_partial_commit(
        self,
        ctx: _SyncContext,
        summary: _FileMutationSummary,
    ) -> None:
        # User chose to discard — but if removes or file updates already
        # happened, the database MUST be written or the iPod is left in
        # an inconsistent state (DB references deleted files).
        if summary.removed > 0 or summary.updated > 0:
            logger.info(
                "User chose discard, but %d removes and %d file updates "
                "already committed — writing DB anyway to stay consistent.",
                summary.removed,
                summary.updated,
            )
            ctx.result.partial_save = True
            ctx.result.errors.append((
                "cancelled",
                self._discarded_partial_commit_message(summary),
            ))
            # Strip new_tracks so only removes/updates are saved.
            ctx.new_tracks.clear()
            self._execute_write_and_finalize(ctx)
            return

        ctx.result.errors.append((
            "cancelled",
            "Sync was cancelled. "
            + (
                f"{summary.added} track{'s' if summary.added != 1 else ''} were "
                "copied to the iPod but the database was not updated — "
                "they will be cleaned up automatically on the next sync."
                if summary.added > 0
                else "No changes were made."
            ),
        ))

    @staticmethod
    def _discarded_partial_commit_message(summary: _FileMutationSummary) -> str:
        if summary.removed > 0 and summary.updated > 0:
            return (
                "Sync was cancelled. New tracks were discarded, but "
                "the database was updated to reflect "
                f"{summary.removed} removal{'s' if summary.removed != 1 else ''} "
                f"and {summary.updated} file update{'s' if summary.updated != 1 else ''} "
                "that had already completed."
            )
        if summary.removed > 0:
            return (
                "Sync was cancelled. New tracks were discarded, but "
                "the database was updated to reflect "
                f"{summary.removed} removal{'s' if summary.removed != 1 else ''} "
                "that had already completed."
            )
        return (
            "Sync was cancelled. New tracks were discarded, but "
            "the database was updated to reflect "
            f"{summary.updated} file update{'s' if summary.updated != 1 else ''} "
            "that had already completed."
        )

    def _current_device_capabilities(self) -> object | None:
        if self.device_capabilities is not None:
            return self.device_capabilities
        try:
            capabilities = getattr(self.device_info, "capabilities", None)
        except Exception:
            capabilities = None
        if capabilities is not None:
            return capabilities
        try:
            from iopenpod.device import get_current_device_for_path

            device = get_current_device_for_path(self.ipod_path)
            return getattr(device, "capabilities", None) if device is not None else None
        except Exception:
            return None

    def _capability_flag(self, field_name: str, default: bool = True) -> bool:
        capabilities = self._current_device_capabilities()
        if capabilities is None:
            return default
        return bool(getattr(capabilities, field_name, default))

    @staticmethod
    def _sync_item_size(item: SyncItem) -> int:
        return item.planned_add_size

    def _apply_device_capability_filters(self, ctx: _SyncContext) -> None:
        """Drop plan entries that would write unsupported media types."""

        supports_video = self._capability_flag("supports_video", True)
        supports_podcast = self._capability_flag("supports_podcast", True)
        supports_photo = self._capability_flag("supports_photo", True)

        skipped: list[str] = []

        def _filter_items(items: list[SyncItem], storage_field: str) -> list[SyncItem]:
            kept: list[SyncItem] = []
            for item in items:
                pc_track = item.pc_track
                if pc_track is None or is_track_supported_by_device(
                    pc_track,
                    supports_video=supports_video,
                    supports_podcast=supports_podcast,
                ):
                    kept.append(item)
                    continue
                reason = unsupported_track_reason(
                    pc_track,
                    supports_video=supports_video,
                    supports_podcast=supports_podcast,
                )
                label = item.display_label
                skipped.append(f"{label}: {reason}")
                setattr(
                    ctx.plan.storage,
                    storage_field,
                    max(0, getattr(ctx.plan.storage, storage_field) - self._sync_item_size(item)),
                )
            return kept

        ctx.plan.to_add = _filter_items(ctx.plan.to_add, "bytes_to_add")
        ctx.plan.to_update_file = _filter_items(
            ctx.plan.to_update_file,
            "bytes_to_update",
        )

        if not supports_photo and ctx.plan.photo_plan is not None:
            photo_plan = ctx.plan.photo_plan
            if bool(getattr(photo_plan, "has_changes", False)):
                skipped.append("photos: photos are not supported by this iPod")
            ctx.plan.storage.bytes_to_add = max(
                0,
                ctx.plan.storage.bytes_to_add
                - int(getattr(photo_plan, "thumb_bytes_to_add", 0) or 0),
            )
            ctx.plan.storage.bytes_to_remove = max(
                0,
                ctx.plan.storage.bytes_to_remove
                - int(getattr(photo_plan, "thumb_bytes_to_remove", 0) or 0),
            )
            ctx.plan.photo_plan = None

        if skipped:
            detail = "; ".join(skipped[:5])
            remaining = len(skipped) - 5
            if remaining > 0:
                detail += f"; and {remaining} more"
            ctx.result.errors.append(("device capabilities", f"Skipped unsupported media: {detail}"))

    @staticmethod
    def _prepare_conversion_group_counts(ctx: _SyncContext) -> None:
        counts = Counter(
            item.conversion_group_key
            for item in ctx.plan.to_add
            if item.conversion_group_key
        )
        for item in ctx.plan.to_add:
            group_id = item.conversion_group_key
            if not group_id:
                continue
            expected = item.conversion_group_expected_count
            if expected:
                counts[group_id] = max(counts[group_id], expected)
        ctx.conversion_group_add_counts = dict(counts)
        ctx.conversion_group_success_counts = {}
        ctx.completed_conversion_groups = set()

    @staticmethod
    def _record_conversion_group_add_success(ctx: _SyncContext, item: SyncItem) -> None:
        group_id = item.conversion_group_key
        if not group_id:
            return
        ctx.conversion_group_success_counts[group_id] = (
            ctx.conversion_group_success_counts.get(group_id, 0) + 1
        )
        expected = ctx.conversion_group_add_counts.get(group_id, 1)
        if ctx.conversion_group_success_counts[group_id] >= expected:
            ctx.completed_conversion_groups.add(group_id)

    # ── Pre-flight & Loading ────────────────────────────────────────────────

    def _preflight_checks(self, ctx: _SyncContext) -> bool:
        """Return False (and populate ctx.result) if sync cannot proceed."""
        if not ctx.dry_run and (ctx.plan.storage.bytes_to_add > 0 or ctx.plan.to_update_file):
            try:
                disk = shutil.disk_usage(self.ipod_path)

                needed = sync_plan_required_free_bytes(
                    ctx.plan,
                    db_overhead_bytes=_DB_OVERHEAD_BYTES,
                    allocation_unit_size=getattr(
                        ctx.filesystem_profile,
                        "allocation_unit_size",
                        None,
                    ),
                )
                if needed > 0 and disk.free < needed:
                    if ctx.sync_until_full:
                        if disk.free < _DB_WRITE_RESERVE_BYTES:
                            reserve_mb = _DB_WRITE_RESERVE_BYTES / (1024 * 1024)
                            free_mb = disk.free / (1024 * 1024)
                            ctx.result.errors.append((
                                "storage",
                                f"Not enough space to start sync: "
                                f"{free_mb:.1f} MB free, "
                                f"{reserve_mb:.0f} MB required.",
                            ))
                            ctx.result.success = False
                            return False
                        logger.info(
                            "Sync plan needs about %s with %s free; "
                            "continuing with sync-until-full policy.",
                            _format_bytes(needed),
                            _format_bytes(disk.free),
                        )
                    else:
                        free_mb = disk.free / (1024 * 1024)
                        need_mb = needed / (1024 * 1024)
                        ctx.result.errors.append((
                            "storage",
                            f"Not enough space on iPod: {free_mb:.0f} MB free, "
                            f"{need_mb:.0f} MB needed",
                        ))
                        ctx.result.success = False
                        return False
            except OSError as e:
                message = f"Could not verify iPod free space before sync: {e}"
                logger.error(message)
                ctx.result.errors.append(("filesystem_safety", message))
                ctx.result.success = False
                return False

        # On Linux the iPod may be auto-mounted read-only (dirty VFAT,
        # missing write permissions).  Detect early for a clear error.
        if not ctx.dry_run:
            probe_dir = self.ipod_path / "iPod_Control" / "iTunes"
            try:
                self._revalidate_device_write_readiness()
                fd, raw_probe_path = tempfile.mkstemp(
                    prefix=".iOpenPod_write_test_", dir=str(probe_dir),
                )
                os.close(fd)
                probe_path = Path(raw_probe_path)
                self._revalidate_device_write_readiness()
                durable_unlink(probe_path)
            except OSError as e:
                if e.errno in (errno.EROFS, errno.EACCES):
                    detail = _write_permission_failure_detail(e)
                    logger.error("iPod is read-only: %s", e)
                    ctx.result.errors.append(("read-only", detail))
                    ctx.result.success = False
                    return False
                message = f"Could not verify that the iPod is writable: {e}"
                logger.error(message)
                ctx.result.errors.append(("filesystem_safety", message))
                ctx.result.success = False
                return False

        try:
            max_file_size = self._effective_max_file_size_bytes()
            for item in (*ctx.plan.to_add, *ctx.plan.to_update_file):
                require_file_size_supported(
                    item.planned_add_size,
                    max_file_size_bytes=max_file_size,
                    display_name=item.display_label,
                )
        except DeviceWriteSafetyError as exc:
            ctx.result.errors.append(("filesystem_safety", str(exc)))
            ctx.result.success = False
            return False

        return True

    def _load_existing_database_into(self, ctx: _SyncContext) -> None:
        """Parse existing iPod database and populate ctx track/playlist state."""
        existing_db = self._read_existing_database()
        ctx.existing_tracks_data = existing_db["tracks"]
        ctx.existing_dataset2_standard_playlists_raw = existing_db[
            "dataset2_standard_playlists"
        ]
        ctx.existing_dataset3_podcast_playlists_raw = existing_db[
            "dataset3_podcast_playlists"
        ]
        ctx.existing_dataset5_smart_playlists_raw = existing_db[
            "dataset5_smart_playlists"
        ]

        for t in ctx.existing_tracks_data:
            track_info = self._track_dict_to_info(t)
            if track_info.db_track_id:
                ctx.tracks_by_db_track_id[track_info.db_track_id] = track_info
            if track_info.location:
                ctx.tracks_by_location[track_info.location] = track_info

        ctx.pc_file_paths = dict(ctx.plan.matched_pc_paths)
        logger.debug("ART: starting with %d matched PC paths from sync plan",
                     len(ctx.pc_file_paths))

    @staticmethod
    def _source_path_key(path: str) -> str:
        return stable_path_key(path)

    @staticmethod
    def _normalize_artwork_pc_paths(
        ctx: _SyncContext,
        all_tracks: list[TrackInfo],
    ) -> dict[int, str]:
        """Normalize artwork source paths to db_track_id -> absolute source path."""
        normalized: dict[int, str] = {}
        valid_db_track_ids = {
            int(track.db_track_id)
            for track in all_tracks
            if track.db_track_id
        }

        for db_track_id, path in ctx.pc_file_paths.items():
            try:
                normalized_id = int(db_track_id)
            except (TypeError, ValueError):
                continue
            if normalized_id in valid_db_track_ids:
                normalized[normalized_id] = str(path)

        new_track_by_obj = {id(track): track for track in all_tracks}
        for obj_key, info in ctx.new_track_info.items():
            track = new_track_by_obj.get(obj_key)
            if track is None or not track.db_track_id:
                continue
            pc_track = info[0]
            normalized[track.db_track_id] = str(pc_track.path)

        return normalized

    @staticmethod
    def _annotate_artwork_sync_hints(
        ctx: _SyncContext,
        all_tracks: list[TrackInfo],
        normalized_pc_paths: dict[int, str],
    ) -> None:
        """Attach per-track hints for the ArtworkDB writer fast-path."""
        update_artwork_ids: set[int] = set()
        clear_art_ids: set[int] = set()
        for item in ctx.plan.to_update_artwork:
            if not item.db_track_id:
                continue
            update_artwork_ids.add(item.db_track_id)
            if not item.new_art_hash:
                clear_art_ids.add(item.db_track_id)

        new_track_ids = {
            track.db_track_id
            for track in ctx.new_tracks
            if track.db_track_id
        }

        for track in all_tracks:
            hint = ""
            if track.db_track_id in clear_art_ids:
                hint = "clear_art"
            elif track.db_track_id in normalized_pc_paths:
                if track.db_track_id not in update_artwork_ids and track.db_track_id not in new_track_ids:
                    hint = "preserve_existing"
            track._iop_artwork_sync_hint = hint

    def _prepare_database_commit_payload(
        self,
        ctx: _SyncContext,
        *,
        advance: Callable[[str], None],
    ) -> DatabaseCommitPayload:
        """Prepare the fully resolved payload for the database writer."""

        advance("Preparing tracks")
        all_tracks = self._prepare_tracks_for_database_commit(ctx)
        normalized_pc_paths = self._normalize_artwork_pc_paths(ctx, all_tracks)
        self._annotate_artwork_sync_hints(ctx, all_tracks, normalized_pc_paths)
        logger.debug(
            "ART: normalized pc_file_paths total=%d, all_tracks=%d",
            len(normalized_pc_paths),
            len(all_tracks),
        )

        advance("Resolving playlists")
        playlist_payload = self._prepare_playlist_commit_payload(ctx, all_tracks)
        return DatabaseCommitPayload(
            all_tracks=all_tracks,
            pc_file_paths=normalized_pc_paths,
            playlists=playlist_payload.standard_playlists,
            podcast_playlists=playlist_payload.podcast_playlists,
            smart_playlists=playlist_payload.smart_playlists,
            master_playlist_name=playlist_payload.master_playlist_name,
            master_playlist_id=playlist_payload.master_playlist_id,
            podcast_master_playlist_name=playlist_payload.podcast_master_playlist_name,
            podcast_master_playlist_id=playlist_payload.podcast_master_playlist_id,
        )

    def _prepare_tracks_for_database_commit(self, ctx: _SyncContext) -> list[TrackInfo]:
        all_tracks = list(ctx.tracks_by_db_track_id.values()) + ctx.new_tracks
        self._assign_missing_db_track_ids(all_tracks)

        from .unknown_metadata import apply_unknown_placeholders
        apply_unknown_placeholders(all_tracks)

        self._apply_gapless_album_flags(all_tracks)
        return all_tracks

    @staticmethod
    def _assign_missing_db_track_ids(all_tracks: list[TrackInfo]) -> None:
        from iopenpod.itunesdb_writer.mhit_writer import generate_db_track_id

        for track in all_tracks:
            if not track.db_track_id:
                track.db_track_id = generate_db_track_id()

    @staticmethod
    def _apply_gapless_album_flags(all_tracks: list[TrackInfo]) -> None:
        from iopenpod.itunesdb_shared.album_identity import (
            album_identity_from_track,
            group_tracks_by_album_identity,
        )

        albums = group_tracks_by_album_identity(all_tracks, album_identity_from_track)
        for group in albums:
            album_tracks = group.tracks
            if len(album_tracks) >= 2 and all(
                track.gapless_track_flag for track in album_tracks
            ):
                for track in album_tracks:
                    track.gapless_album_flag = 1

    def _prepare_playlist_commit_payload(
        self,
        ctx: _SyncContext,
        all_tracks: list[TrackInfo],
    ) -> _ResolvedPlaylistCommitPayload:
        """Apply playlist actions and resolve final playlist memberships."""

        self._apply_playlist_commit_actions(ctx)
        return self._resolve_playlist_commit_payload(ctx, all_tracks)

    def _resolve_playlist_commit_payload(
        self,
        ctx: _SyncContext,
        all_tracks: list[TrackInfo],
    ) -> _ResolvedPlaylistCommitPayload:
        """Resolve final playlist memberships after track IDs are assigned."""

        (
            master_playlist_name,
            master_playlist_id,
            playlists,
            podcast_master_playlist_name,
            podcast_master_playlist_id,
            podcast_playlists,
            smart_playlists,
        ) = self._build_and_evaluate_playlists(ctx, all_tracks)
        return _ResolvedPlaylistCommitPayload(
            master_playlist_name=master_playlist_name,
            master_playlist_id=master_playlist_id,
            standard_playlists=playlists,
            podcast_master_playlist_name=podcast_master_playlist_name,
            podcast_master_playlist_id=podcast_master_playlist_id,
            podcast_playlists=podcast_playlists,
            smart_playlists=smart_playlists,
        )

    def _execute_write_and_finalize(self, ctx: _SyncContext) -> None:
        """Stage 7: assemble final track list, write database, backpatch and finalize."""
        # Define sub-steps so the progress bar advances smoothly through
        # the database-write phase instead of jumping from 0% to 100%.
        # Steps: prepare tracks → build playlists → prepare db → artwork phases
        #        (scanning / converting / writing) → build db structure → sign db
        #        → write to iPod (+ SQLite)
        _TOTAL_STEPS = 10
        _step = 0

        def _advance(msg: str) -> None:
            nonlocal _step
            ctx.progress("write_database", _step, _TOTAL_STEPS, message=msg)
            _step += 1

        # ── Pre-write space guard ─────────────────────────────────
        # The copy loop stops at 4 MB free; here we only need 1 MB to write
        # the database itself.  This lets a sync that fills the iPod close to
        # the wire still commit successfully.
        try:
            self._revalidate_device_write_readiness()
            free_now = shutil.disk_usage(self.ipod_path).free
            if free_now < _DB_WRITE_RESERVE_BYTES:
                reserve_mb = _DB_WRITE_RESERVE_BYTES / (1024 * 1024)
                free_mb = free_now / (1024 * 1024)
                ctx.result.errors.append((
                    "storage",
                    f"Not enough space to write the database: "
                    f"{free_mb:.1f} MB free, {reserve_mb:.0f} MB required.",
                ))
                ctx.result.success = False
                return
        except OSError as e:
            message = f"Could not verify iPod free space before database write: {e}"
            logger.error(message)
            ctx.result.errors.append(("filesystem_safety", message))
            ctx.result.success = False
            return

        # Scrobble before clearing transient play deltas or deleting Play
        # Counts.  Each service receives its own snapshot of the original
        # deltas, then the in-memory DB state is cleared once before write.
        if ctx.plan.to_sync_playcount:
            self._execute_scrobble(ctx)
            self._clear_playcount_deltas(ctx)

        commit_payload = self._prepare_database_commit_payload(ctx, advance=_advance)

        try:
            # The inner writer calls our callback to advance the bar
            # through artwork → db structure → signing → writing.
            def _db_progress(msg: str) -> None:
                nonlocal _step
                ctx.progress("write_database", _step, _TOTAL_STEPS, message=msg)
                _step += 1

            db_ok = write_database_commit(
                self.ipod_path,
                commit_payload,
                progress_callback=_db_progress,
                raise_on_error=True,
                protect_itunes=False,
                flush_after_write=False,
                write_guard=ctx.write_guard,
                filesystem_profile=ctx.filesystem_profile,
            )
            if not db_ok:
                logger.error("Database write returned failure — skipping mapping save")
                ctx.progress("write_database", _TOTAL_STEPS, _TOTAL_STEPS,
                             message="Database write FAILED")
                ctx.result.success = False
                ctx.result.errors.append(("database", "Database write failed"))
                return
            ctx.progress("write_database", _TOTAL_STEPS, _TOTAL_STEPS,
                         message=f"Database written — {len(commit_payload.all_tracks)} tracks")

            # ── Backpatch: new tracks now have real db_track_ids ──
            self._backpatch_new_tracks(ctx)

            # Save mapping ONLY after successful DB write + backpatch.
            self._revalidate_device_write_readiness()
            if self.mapping_manager.save(ctx.mapping) is False:
                ctx.result.errors.append((
                    "mapping",
                    "The iPod database was written, but the iOpenPod mapping "
                    "file could not be saved.",
                ))
                ctx.result.success = False
                return

            # ── Update podcast subscription store ──────────────────
            self._update_podcast_subscriptions(ctx)

            # The lifecycle invokes the sync-complete callback only after the
            # target filesystem has passed its final durability flush.
            ctx.database_committed = True
            ctx.device_changes_committed = True

            if ctx.plan.photo_plan:
                self._revalidate_device_write_readiness()
                ctx.final_photo_db = apply_photo_sync_plan(
                    self.ipod_path,
                    ctx.plan.photo_plan,
                    progress_callback=lambda stage, cur, total, msg: ctx.progress(
                        stage, cur, total, message=msg,
                    ),
                    is_cancelled=ctx._is_cancelled,
                    sync_settings=self.photo_sync_settings,
                    before_device_mutation=self._revalidate_device_write_readiness,
                    filesystem_profile=ctx.filesystem_profile,
                )
                ctx.result.photos_added = len(ctx.plan.photo_plan.photos_to_add)
                ctx.result.photos_removed = len(ctx.plan.photo_plan.photos_to_remove)
                ctx.result.photos_updated = len(ctx.plan.photo_plan.photos_to_update)
                ctx.result.photo_albums_added = len(ctx.plan.photo_plan.albums_to_add)
                ctx.result.photo_albums_removed = len(ctx.plan.photo_plan.albums_to_remove)
            else:
                ctx.final_photo_db = read_photo_db(self.ipod_path)

            photo_db = ctx.final_photo_db if ctx.final_photo_db is not None else read_photo_db(
                self.ipod_path
            )
            self._revalidate_device_write_readiness()
            apply_itunes_protections_from_tracks(
                self.ipod_path,
                commit_payload.all_tracks,
                photo_db=photo_db,
                include_photo_totals=True,
                before_device_mutation=self._revalidate_device_write_readiness,
            )

            self._revalidate_device_write_readiness()
            self._delete_playcounts_file()

        except DeviceWriteSafetyError as e:
            ctx.result.errors.append(("filesystem_safety", str(e)))
            ctx.result.success = False
            logger.error("Database commit stopped by device safety guard: %s", e)
        except Exception as e:
            ctx.result.errors.append(("database write", str(e)))
            logger.exception("Database/post-write phase failed")

    def _apply_playlist_commit_actions(self, ctx: _SyncContext) -> None:
        """Apply reviewed playlist add/edit/remove actions to commit sources."""

        playlist_updates = [
            *list(ctx.plan.playlists_to_add or []),
            *list(ctx.plan.playlists_to_edit or []),
        ]
        remove_pls = list(ctx.plan.playlists_to_remove or [])
        if not playlist_updates and not remove_pls:
            return
        total = len(playlist_updates) + len(remove_pls)
        current = 0
        ctx.progress("playlists", 0, total, message="Updating playlists...")

        def _uses_dataset3_mirrors() -> bool:
            return bool(ctx.existing_dataset3_podcast_playlists_raw)

        def _upsert_playlist(bucket: list[dict], row: dict) -> bool:
            pid = coerce_int(row.get("playlist_id", 0))
            if pid:
                for i, epl in enumerate(bucket):
                    if coerce_int(epl.get("playlist_id")) == pid:
                        bucket[i] = row
                        return True
            bucket.append(row)
            return False

        def _remove_playlist(removal: dict) -> bool:
            playlist_id = coerce_int(removal.get("playlist_id"))
            if not playlist_id:
                return False
            target_dataset = _playlist_dataset_type(removal)
            mirrored_regular_removal = (
                target_dataset == 2
                and _uses_dataset3_mirrors()
                and _is_regular_playlist_mirror_candidate(removal)
            )
            buckets = (
                (ctx.existing_dataset2_standard_playlists_raw, 2),
                (ctx.existing_dataset3_podcast_playlists_raw, 3),
                (ctx.existing_dataset5_smart_playlists_raw, 5),
            )
            removed = False
            for bucket, bucket_dataset in buckets:
                kept = []
                for existing in bucket:
                    existing_dataset = _playlist_dataset_type(existing) or bucket_dataset
                    if (
                        coerce_int(existing.get("playlist_id")) == playlist_id
                        and not existing.get("master_flag")
                        and (
                            not target_dataset
                            or target_dataset == existing_dataset
                            or target_dataset == bucket_dataset
                            or (
                                mirrored_regular_removal
                                and existing_dataset in (2, 3)
                                and bucket_dataset in (2, 3)
                            )
                        )
                    ):
                        removed = True
                        continue
                    kept.append(existing)
                if len(kept) != len(bucket):
                    bucket[:] = kept
            return removed

        for removal in remove_pls:
            current += 1
            removed = _remove_playlist(removal)
            logger.info(
                "Removed playlist '%s' (id=%s, removed=%s)",
                removal.get("Title", "?"),
                removal.get("playlist_id", 0),
                removed,
            )
            ctx.progress(
                "playlists",
                current,
                total,
                message=f"Removed playlist: {removal.get('Title', '?')}",
            )

        for playlist in playlist_updates:
            current += 1
            if playlist.get("master_flag"):
                logger.debug(
                    "Skipping master playlist from sync plan (id=0x%X)",
                    playlist.get("playlist_id", 0),
                )
                ctx.progress(
                    "playlists",
                    current,
                    total,
                    message=f"Skipped master playlist: {playlist.get('Title', '?')}",
                )
                continue
            is_new = playlist.get("_isNew", False)
            pid = coerce_int(playlist.get("playlist_id", 0))
            dataset_type = coerce_int(playlist.get("_mhsd_dataset_type", 0))

            if dataset_type == 3 or playlist.get("_source") == "podcast":
                target = ctx.existing_dataset3_podcast_playlists_raw
            elif dataset_type == 5 or _is_ipod_category_playlist(playlist):
                target = ctx.existing_dataset5_smart_playlists_raw
            else:
                target = ctx.existing_dataset2_standard_playlists_raw

            if (
                target is ctx.existing_dataset2_standard_playlists_raw
                and _uses_dataset3_mirrors()
                and _is_regular_playlist_mirror_candidate(playlist)
            ):
                _upsert_playlist(
                    ctx.existing_dataset2_standard_playlists_raw,
                    _playlist_row_for_dataset(playlist, 2),
                )
                _upsert_playlist(
                    ctx.existing_dataset3_podcast_playlists_raw,
                    _playlist_row_for_dataset(playlist, 3),
                )
            else:
                _upsert_playlist(target, playlist)
            logger.info(
                "Merged plan playlist '%s' (id=%s, new=%s)",
                playlist.get("Title", "?"),
                (f"0x{pid:X}") if pid is not None else "new",
                is_new,
            )
            ctx.progress("playlists", current, total,
                         message=f"Merged playlist: {playlist.get('Title', '?')}")

    def _merge_plan_playlists(self, ctx: _SyncContext) -> None:
        """Apply reviewed playlist actions from the sync plan."""

        self._apply_playlist_commit_actions(ctx)

    def _backpatch_new_tracks(self, ctx: _SyncContext) -> None:
        """Create mapping entries for newly added tracks (db_track_ids now assigned)."""
        if not ctx.new_tracks:
            return

        total = len(ctx.new_tracks)
        ctx.progress(
            "backpatch",
            0,
            total,
            message="Recording source file identities...",
        )

        for index, track in enumerate(ctx.new_tracks, start=1):
            obj_key = id(track)
            fp = ctx.new_track_fingerprints.get(obj_key)
            info = ctx.new_track_info.get(obj_key)
            label = getattr(track, "title", "") or getattr(track, "location", "") or "track"
            ctx.progress(
                "backpatch",
                index,
                total,
                message=f"Recording source identity for {label}",
            )
            if fp and info and track.db_track_id != 0:
                pc_track, ipod_dest, was_transcoded = info[:3]
                item = info[3] if len(info) > 3 else None
                cached_identity = (
                    ctx.sync_item_source_identities.get(id(item))
                    if item is not None else None
                )
                if cached_identity is not None:
                    source_size, source_mtime, source_hash = cached_identity
                else:
                    # Capture post-fingerprint size/mtime.  The fingerprinting
                    # phase may have written a tag after the initial scan.
                    source_size, source_mtime, source_hash = _current_source_identity(pc_track)
                source_path_hint = pc_track.relative_path
                source_format = Path(pc_track.path).suffix.lstrip(".")
                if item is not None and item.mapping_source_metadata:
                    source_meta = item.mapping_source_metadata
                    try:
                        source_size = int(source_meta.get("source_size") or source_size)
                    except (TypeError, ValueError):
                        pass
                    try:
                        source_mtime = float(source_meta.get("source_mtime") or source_mtime)
                    except (TypeError, ValueError):
                        pass
                    source_path_hint = (
                        str(source_meta.get("source_path_hint") or "").strip()
                        or source_path_hint
                    )
                    source_format = (
                        Path(source_path_hint).suffix.lstrip(".")
                        or source_format
                    )
                    source_hash = source_meta.get("source_hash")
                contains_fingerprints = None
                contains_sources = None
                aggregate_kind = None
                if item is not None:
                    aggregate_kind = getattr(item, "aggregate_kind", None)
                    if aggregate_kind:
                        contains_fingerprints = (
                            getattr(item, "aggregate_contains_fingerprints", None)
                            or getattr(item, "conversion_source_fingerprints", ())
                        )
                        contains_sources = (
                            getattr(item, "aggregate_contains_sources", None)
                            or getattr(item, "conversion_source_metadata", ())
                        )
                ctx.mapping.add_track(
                    fingerprint=fp,
                    db_track_id=track.db_track_id,
                    source_format=source_format,
                    ipod_format=ipod_dest.suffix.lstrip("."),
                    source_size=source_size,
                    source_mtime=source_mtime,
                    was_transcoded=was_transcoded,
                    source_path_hint=source_path_hint,
                    art_hash=pc_track.art_hash,
                    source_hash=source_hash,
                    aggregate_kind=aggregate_kind,
                    contains_fingerprints=contains_fingerprints,
                    contains_sources=contains_sources,
                )

    def _update_podcast_subscriptions(self, ctx: _SyncContext) -> None:
        """Mark added podcast episodes as on_ipod and removed ones as downloaded
        in the subscription store so the state persists across sessions."""
        try:
            from iopenpod.podcasts.models import (
                STATUS_DOWNLOADED,
                STATUS_NOT_DOWNLOADED,
                STATUS_ON_IPOD,
            )
            from iopenpod.podcasts.subscription_store import SubscriptionStore
        except ImportError:
            return

        def _coerce_int(value: Any) -> int:
            try:
                return int(value) if value is not None else 0
            except (TypeError, ValueError):
                return 0

        def _listened_override(ep) -> bool | None:
            override = getattr(ep, "listened_override", None)
            if override is None:
                return None
            return bool(override)

        def _remember_track_playback(ep, track) -> None:
            recent_play_count = _coerce_int(track.get("recent_playcount"))
            if recent_play_count > 0 and _listened_override(ep) is False:
                ep.listened_override = None

            if _listened_override(ep) is False:
                return

            play_count = max(
                _coerce_int(track.get("play_count_1")),
                recent_play_count,
            )
            if play_count > _coerce_int(getattr(ep, "play_count", 0)):
                ep.play_count = play_count

            last_played = _coerce_int(track.get("last_played"))
            if last_played > _coerce_int(getattr(ep, "last_played", 0)):
                ep.last_played = last_played

        def _remember_trackinfo_playback(ep, track) -> None:
            if _listened_override(ep) is False:
                return

            play_count = _coerce_int(getattr(track, "play_count", 0))
            if play_count > _coerce_int(getattr(ep, "play_count", 0)):
                ep.play_count = play_count

            last_played = _coerce_int(getattr(track, "last_played", 0))
            if last_played > _coerce_int(getattr(ep, "last_played", 0)):
                ep.last_played = last_played

        profile = ctx.filesystem_profile or self._filesystem_profile
        if profile is None:
            raise DeviceWriteSafetyError(
                "Podcast metadata cannot be written without a retained "
                "filesystem safety profile."
            )
        metadata_session = DeviceMetadataWriteSession(
            Path(os.path.realpath(self.ipod_path)),
            profile,
        )
        store = SubscriptionStore(
            str(self.ipod_path),
            reported_volume_format=str(
                getattr(self.device_storage, "reported_volume_format", "") or ""
            ),
            expected_volume_identity_key=str(
                getattr(self.device_storage, "volume_identity_key", "") or ""
            ),
            metadata_write_session=metadata_session,
        )
        refreshed_feeds = ctx.plan._refreshed_podcast_feeds
        feeds = list(refreshed_feeds) if refreshed_feeds is not None else store.get_feeds()
        if not feeds:
            return

        if refreshed_feeds is not None:
            for feed in feeds:
                store.cache_feed_artwork(feed)

        # Index episodes by enclosure URL across all feeds
        ep_by_url: dict[str, tuple] = {}
        ep_by_db_track_id: dict[int, tuple] = {}
        for feed in feeds:
            for ep in feed.episodes:
                if ep.audio_url:
                    ep_by_url[ep.audio_url] = (ep, feed)
                if ep.ipod_db_track_id:
                    ep_by_db_track_id[ep.ipod_db_track_id] = (ep, feed)

        changed = refreshed_feeds is not None

        # Mark added podcast episodes as on_ipod with their db_track_id
        for track in ctx.new_tracks:
            if not (track.media_type & MEDIA_TYPE_PODCAST):
                continue
            enc_url = track.podcast_enclosure_url or ""
            if not enc_url:
                continue
            entry = ep_by_url.get(enc_url)
            if entry:
                ep, _feed = entry
                _remember_trackinfo_playback(ep, track)
                ep.status = STATUS_ON_IPOD
                ep.ipod_db_track_id = track.db_track_id
                changed = True
                logger.debug("Podcast subscription: marked '%s' as on_ipod (db_track_id=%d)",
                             ep.title, track.db_track_id)

        # Mark removed podcast episodes as downloaded (no longer on iPod)
        all_removals = list(ctx.plan.to_remove) + list(
            getattr(ctx.plan, '_integrity_removals', [])
        )
        for item in all_removals:
            ipod_track = item.ipod_track
            if not ipod_track:
                continue
            if not (ipod_track.get("media_type", 0) & MEDIA_TYPE_PODCAST):
                continue
            enc_url = ipod_track.get("Podcast Enclosure URL", "")
            entry = ep_by_url.get(enc_url) if enc_url else None
            if entry is None and item.db_track_id:
                entry = ep_by_db_track_id.get(item.db_track_id)
            if entry:
                ep, _feed = entry
                _remember_track_playback(ep, ipod_track)
                ep.status = STATUS_DOWNLOADED if ep.downloaded_path else STATUS_NOT_DOWNLOADED
                ep.ipod_db_track_id = 0
                changed = True
                logger.debug("Podcast subscription: marked '%s' as removed from iPod",
                             ep.title)

        if changed:
            store.update_feeds(feeds)
            logger.info("Updated podcast subscription store after sync")

    @staticmethod
    def _clear_gui_cache(ctx: _SyncContext) -> None:
        """Notify caller that sync completed (so it can clear pending state)."""
        if ctx.on_sync_complete:
            try:
                ctx.on_sync_complete()
                logger.info("Sync-complete callback invoked")
            except Exception:
                pass

    # ── Stage Implementations ───────────────────────────────────────────────

    def _execute_integrity_housekeeping(self, ctx: _SyncContext) -> None:
        """Delete planned orphan media under the active device writer guard."""
        report = ctx.plan.integrity_report
        orphan_files = list(
            getattr(report, "orphan_files", ()) if report is not None else ()
        )
        if not orphan_files:
            return

        ctx.progress(
            "integrity",
            0,
            len(orphan_files),
            message="Removing unreferenced iPod media...",
        )
        for index, planned_path in enumerate(orphan_files, start=1):
            if ctx.cancelled():
                return
            ctx.progress(
                "integrity",
                index,
                len(orphan_files),
                message=Path(planned_path).name,
            )
            if ctx.dry_run:
                continue
            try:
                removed = self._delete_planned_integrity_orphan(ctx, planned_path)
            except DeviceWriteSafetyError:
                raise
            except OSError as exc:
                message = (
                    "Could not remove unreferenced iPod media "
                    f"{Path(planned_path).name}: {exc}"
                )
                logger.error(message)
                ctx.result.errors.append(("integrity_cleanup", message))
                ctx.result.success = False
                return
            if removed:
                ctx.integrity_orphans_removed += 1

    def _delete_planned_integrity_orphan(
        self,
        ctx: _SyncContext,
        planned_path: str | Path,
    ) -> bool:
        """Revalidate, contain, and durably delete one planned orphan."""
        with self._device_write_semaphore:
            self._revalidate_device_write_readiness()
            candidate = self._resolve_integrity_orphan_path(planned_path)
            candidate_stat = _strict_device_path_stat(
                candidate,
                action="integrity cleanup",
            )
            if candidate_stat is None:
                logger.info("Planned orphan is already absent: %s", candidate)
                return False
            if self._database_references_media_path(ctx, candidate):
                logger.warning(
                    "Skipped planned orphan because the current iTunesDB now "
                    "references it: %s",
                    candidate,
                )
                return False
            if not stat.S_ISREG(candidate_stat.st_mode):
                raise DeviceWriteSafetyError(
                    f"Planned orphan is no longer a regular media file: {candidate}"
                )
            try:
                durable_unlink(candidate)
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not durably remove planned orphan {candidate}: {exc}"
                ) from exc
            logger.info("Removed unreferenced iPod media: %s", candidate)
            return True

    def _resolve_integrity_orphan_path(self, planned_path: str | Path) -> Path:
        """Resolve one planner-reported orphan inside Music/F## only."""
        root = Path(os.path.abspath(self.ipod_path))
        lexical = Path(os.path.abspath(Path(planned_path)))
        try:
            relative = lexical.relative_to(root)
        except ValueError as exc:
            raise DeviceWriteSafetyError(
                f"Refusing orphan cleanup outside the selected iPod: {planned_path}"
            ) from exc

        parts = relative.parts
        if (
            len(parts) != 4
            or parts[0].casefold() != "ipod_control"
            or parts[1].casefold() != "music"
            or not (
                len(parts[2]) >= 2
                and parts[2][0].casefold() == "f"
                and parts[2][1:].isdigit()
            )
            or Path(parts[3]).suffix.lower() not in _MEDIA_EXTENSIONS
        ):
            raise DeviceWriteSafetyError(
                f"Refusing unexpected orphan cleanup path: {planned_path}"
            )

        try:
            resolved = resolve_device_path(
                root,
                relative,
                allowed_subtree=Path("iPod_Control") / "Music",
            )
        except UnsafeDevicePathError as exc:
            raise DeviceWriteSafetyError(str(exc)) from exc

        if os.path.normcase(str(lexical)) != os.path.normcase(str(resolved)):
            raise DeviceWriteSafetyError(
                "Refusing orphan cleanup through a symlink or reparse point: "
                f"{planned_path}"
            )
        return resolved

    def _database_references_media_path(
        self,
        ctx: _SyncContext,
        candidate: Path,
    ) -> bool:
        candidate_key = stable_path_key(candidate)
        for track in ctx.tracks_by_db_track_id.values():
            location = str(track.location or "")
            if not location:
                continue
            referenced = expected_ipod_track_file_path(self.ipod_path, location)
            if referenced is not None and stable_path_key(referenced) == candidate_key:
                return True
        return False

    def _transcode_plan_for_item(
        self,
        item: SyncItem,
        source_path: Path,
    ) -> TranscodePlan:
        planned = getattr(item, "transcode_plan", None)
        if planned is not None:
            try:
                if Path(planned.source_path) == source_path:
                    return planned
            except Exception:
                pass
            logger.debug(
                "Ignoring stale transcode plan for %s; resolving from executor settings",
                source_path.name,
            )
        return resolve_transcode_plan(source_path, options=self.transcode_options)

    def _execute_removes(self, ctx: _SyncContext) -> None:
        # Combine user-selected removals with mandatory integrity removals
        # (ghost tracks whose files are missing from iPod).
        all_removes = [
            item for item in ctx.plan.to_remove
            if not item.is_deferred_removal
        ]
        integrity_removals = getattr(ctx.plan, '_integrity_removals', [])
        if integrity_removals:
            # Deduplicate by db_track_id in case any overlap
            existing_db_track_ids = {item.db_track_id for item in all_removes if item.db_track_id}
            for item in integrity_removals:
                if item.db_track_id and item.db_track_id not in existing_db_track_ids:
                    all_removes.append(item)
                    existing_db_track_ids.add(item.db_track_id)

        aggregate_rebuilds = [
            item for item in all_removes
            if self._is_chaptered_aggregate_rebuild(item)
        ]
        normal_removes = [
            item for item in all_removes
            if not self._is_chaptered_aggregate_rebuild(item)
        ]

        self._execute_chaptered_aggregate_rebuild_items(
            ctx,
            aggregate_rebuilds,
            stage_name="remove_chapter",
            start_message="Rebuilding chaptered albums...",
        )

        self._execute_remove_items(
            ctx,
            normal_removes,
            stage_name="remove",
            start_message="Removing tracks...",
        )

        for fp, db_track_id in getattr(ctx.plan, '_stale_mapping_entries', []):
            ctx.mapping.remove_track(fp, db_track_id=db_track_id)

    def _execute_remove_items(
        self,
        ctx: _SyncContext,
        items: list[SyncItem],
        *,
        stage_name: str,
        start_message: str,
    ) -> None:
        if not items:
            return

        ctx.progress(stage_name, 0, len(items), message=start_message)

        for i, item in enumerate(items):
            if ctx.cancelled():
                return

            ctx.progress(stage_name, i + 1, len(items), item, item.description)

            if ctx.dry_run:
                ctx.result.tracks_removed += 1
                continue

            file_path = item.ipod_location
            if item.db_track_id:
                current_track = ctx.tracks_by_db_track_id.get(item.db_track_id)
                if current_track is not None and current_track.location:
                    file_path = current_track.location
            if file_path:
                full_path = expected_ipod_track_file_path(self.ipod_path, file_path)
                if full_path is not None and not self._delete_from_ipod(full_path):
                    ctx.result.errors.append((
                        item.display_label,
                        f"Could not delete iPod file {file_path}; "
                        "the database entry will still be removed.",
                    ))

                if file_path in ctx.tracks_by_location:
                    track_to_remove = ctx.tracks_by_location.pop(file_path)
                    if track_to_remove.db_track_id in ctx.tracks_by_db_track_id:
                        del ctx.tracks_by_db_track_id[track_to_remove.db_track_id]

            if item.fingerprint:
                ctx.mapping.remove_track(item.fingerprint, db_track_id=item.db_track_id)
            elif item.db_track_id:
                ctx.mapping.remove_by_db_track_id(item.db_track_id)

            if item.db_track_id and item.db_track_id in ctx.tracks_by_db_track_id:
                del ctx.tracks_by_db_track_id[item.db_track_id]

            ctx.result.tracks_removed += 1

    def _execute_deferred_replacement_removes(self, ctx: _SyncContext) -> None:
        deferred = [
            item for item in ctx.plan.to_remove
            if (
                item.is_deferred_replacement_removal
                and item.conversion_group_key in ctx.completed_conversion_groups
            )
        ]
        self._execute_remove_items(
            ctx,
            deferred,
            stage_name="replace_remove",
            start_message="Removing replaced album tracks...",
        )

    def _parallel_copy_stage(
        self,
        ctx: _SyncContext,
        stage_name: str,
        items: list,
        on_success: Callable,
        error_prefix: str = "Failed",
    ) -> None:
        """Shared ThreadPoolExecutor loop for transcode/copy stages.

        *on_success(item, ipod_path, was_transcoded)* is called for each
        successfully copied track.
        """
        items_to_process = [
            (i, item) for i, item in enumerate(items) if item.has_pc_source
        ]
        if not items_to_process:
            return

        completed_count = 0
        completed_lock = threading.Lock()
        worker_fractions: dict[int, float] = {}
        worker_sizes: dict[int, int] = {}
        worker_status: dict[int, str] = {}
        stop_writes = threading.Event()
        total = len(items)

        total_sync_bytes = sum(
            item.planned_add_size for _, item in items_to_process
        ) or 1
        completed_bytes = 0

        def _build_progress() -> SyncProgress:
            in_flight = sum(
                worker_fractions.get(wid, 0.0) * worker_sizes.get(wid, 0)
                for wid in worker_fractions
            )
            size_frac = min((completed_bytes + in_flight) / total_sync_bytes, 1.0)
            lines = list(worker_status.values())
            return SyncProgress(
                stage_name, min(completed_count, total), total,
                worker_lines=lines if lines else None,
                size_progress=size_frac,
            )

        def _do_copy(
            item: SyncItem,
            worker_id: int,
        ) -> tuple[SyncItem, bool, Path | None, bool, str, _SourceIdentitySnapshot | None]:
            if item.pc_track is None:
                logger.error("_do_copy called with None pc_track for %s", item.description)
                return (item, False, None, False, "No source track", None)
            source_path = Path(item.pc_track.path)
            transcode_plan = self._transcode_plan_for_item(item, source_path)
            need_transcode = transcode_plan.target != TranscodeTarget.COPY
            expected_write_bytes = item.planned_add_size

            with completed_lock:
                worker_sizes[worker_id] = item.pc_track.size
                verb = "Transcoding" if need_transcode else "Copying"
                worker_status[worker_id] = f"{verb} {source_path.name} \u2014 0%"
                if ctx.progress_callback:
                    ctx.progress_callback(_build_progress())

            transcode_cb: Callable[[float], None] | None = None
            copy_cb: Callable[[float], None] | None = None
            if ctx.progress_callback:
                filename = source_path.name

                def _make_io_cb(_fn: str, _wid: int, _verb: str) -> Callable[[float], None]:
                    # Throttle to ~20 fps so parallel workers don't saturate the
                    # Qt event queue and cause the UI to lag/freeze after copy ends.
                    # The transcoder uses the same pattern at 250 ms; 50 ms feels
                    # responsive enough for a copy bar.
                    _last_report: list[float] = [0.0]

                    def _cb(frac: float) -> None:
                        now = time.monotonic()
                        if frac < 1.0 and now - _last_report[0] < 0.05:
                            return
                        _last_report[0] = now
                        pct = int(frac * 100)
                        with completed_lock:
                            worker_fractions[_wid] = frac
                            worker_status[_wid] = f"{_verb} {_fn} \u2014 {pct}%"
                            prog = _build_progress()
                        ctx.progress_callback(prog)  # type: ignore[misc]
                    return _cb

                if need_transcode:
                    transcode_cb = _make_io_cb(filename, worker_id, "Transcoding")
                copy_cb = _make_io_cb(filename, worker_id, "Copying")

            action_name = getattr(item.action, "name", str(item.action))
            if action_name == "ADD_TO_IPOD" and not item.fingerprint:
                item.fingerprint, _fingerprint_status = (
                    get_or_compute_fingerprint_with_status(
                        source_path,
                        fpcalc_path=self.fpcalc_path,
                    )
                )

            try:
                source_identity = _current_source_identity(item.pc_track)
            except Exception as exc:
                logger.debug(
                    "Could not precompute source identity for %s: %s",
                    source_path,
                    exc,
                )
                source_identity = None

            success, ipod_path, was_transcoded, err_msg = self._copy_to_ipod(
                source_path, transcode_plan, fingerprint=item.fingerprint,
                transcode_progress=transcode_cb,
                copy_progress=copy_cb,
                is_cancelled=lambda: stop_writes.is_set()
                or bool(ctx._is_cancelled and ctx._is_cancelled()),
                expected_write_bytes=expected_write_bytes,
                source_identity=source_identity,
                sync_until_full=ctx.sync_until_full,
            )
            return (item, success, ipod_path, was_transcoded, err_msg, source_identity)

        workers = 1 if ctx.sync_until_full else self._max_workers
        logger.info("Stage '%s': processing %d items with %d workers", stage_name, len(items_to_process), workers)

        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            future_to_idx: dict[Future, int] = {}
            for idx, item in items_to_process:
                if ctx.cancelled():
                    stop_writes.set()
                    pool.shutdown(wait=True, cancel_futures=True)
                    return
                fut = pool.submit(_do_copy, item, idx)
                future_to_idx[fut] = idx

            for future in as_completed(future_to_idx):
                if ctx.cancelled():
                    stop_writes.set()
                    for f in future_to_idx:
                        f.cancel()
                    pool.shutdown(wait=True, cancel_futures=True)
                    return

                idx = future_to_idx[future]
                try:
                    (
                        item,
                        success,
                        ipod_path,
                        was_transcoded,
                        err_msg,
                        source_identity,
                    ) = future.result()
                except (_CancelledError, _OutOfSpaceError) as e:
                    stop_writes.set()
                    is_oom = isinstance(e, _OutOfSpaceError)
                    if is_oom:
                        logger.error(str(e))
                        summary = self._file_mutation_summary(ctx)
                        n_done = completed_count
                        n_left = total - completed_count
                        if n_done > 0 or summary.anything_done:
                            oom_msg = (
                                "Ran out of space before copying the next file. "
                                f"{n_left} more file{'s' if n_left != 1 else ''} "
                                "could not be copied. The database will be saved "
                                "with what completed."
                            )
                        else:
                            oom_msg = (
                                "Not enough space to copy the next file. "
                                "The iPod database was not changed."
                            )
                        ctx.result.errors.append(("storage", oom_msg))
                        ctx.result.success = False
                    for f in future_to_idx:
                        f.cancel()
                    pool.shutdown(wait=True, cancel_futures=True)
                    return
                except DeviceWriteSafetyError:
                    stop_writes.set()
                    for f in future_to_idx:
                        f.cancel()
                    pool.shutdown(wait=True, cancel_futures=True)
                    raise
                except Exception as e:
                    item = items[idx]
                    ctx.result.errors.append((item.description, f"Worker error: {e}"))
                    logger.error("Worker exception for %s: %s", item.description, e)
                    with completed_lock:
                        completed_count += 1
                        completed_bytes += worker_sizes.pop(idx, 0)
                        worker_fractions.pop(idx, None)
                        worker_status.pop(idx, None)
                        prog = _build_progress()
                    if ctx.progress_callback:
                        ctx.progress_callback(prog)
                    continue

                with completed_lock:
                    completed_count += 1
                    completed_bytes += worker_sizes.pop(idx, 0)
                    worker_fractions.pop(idx, None)
                    worker_status.pop(idx, None)
                    prog = _build_progress()

                if ctx.progress_callback:
                    ctx.progress_callback(prog)

                if not success or ipod_path is None:
                    detail = f"{error_prefix}: {err_msg}" if err_msg else error_prefix
                    ctx.result.errors.append((item.description, detail))
                    continue

                if source_identity is not None:
                    ctx.sync_item_source_identities[id(item)] = source_identity
                on_success(item, ipod_path, was_transcoded)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _is_chaptered_aggregate_rebuild(item: SyncItem) -> bool:
        return item.is_chaptered_aggregate_rebuild

    def _execute_chaptered_aggregate_rebuild_items(
        self,
        ctx: _SyncContext,
        items: list[SyncItem],
        *,
        stage_name: str,
        start_message: str,
    ) -> None:
        if not items:
            return

        ctx.progress(stage_name, 0, len(items), message=start_message)
        for i, item in enumerate(items):
            if ctx.cancelled():
                return
            ctx.progress(stage_name, i + 1, len(items), item, item.description)
            if ctx.dry_run:
                ctx.result.tracks_updated_file += 1
                continue
            if self._execute_chaptered_aggregate_rebuild(ctx, item):
                ctx.result.tracks_updated_file += 1

    @staticmethod
    def _track_dict_from_pc_track(pc_track, index: int) -> dict:
        return {
            "Title": pc_track.title or f"Track {index}",
            "Artist": pc_track.artist or "",
            "Album": pc_track.album or "",
            "Album Artist": pc_track.album_artist or pc_track.artist or "",
            "Genre": pc_track.genre or "",
            "year": pc_track.year or 0,
            "track_number": pc_track.track_number or index,
            "total_tracks": pc_track.track_total or 0,
            "disc_number": pc_track.disc_number or 1,
            "total_discs": pc_track.disc_total or 1,
            "length": pc_track.duration_ms or 0,
        }

    @staticmethod
    def _unique_rebuild_destination(path: Path, suffix: str) -> Path:
        candidate = path.with_suffix(suffix)
        if candidate == path or _strict_device_path_stat(
            candidate,
            action="choosing a rebuild destination",
        ) is None:
            return candidate
        stem = candidate.stem
        parent = candidate.parent
        for index in range(1, 10_000):
            numbered = parent / f"{stem} {index}{suffix}"
            if _strict_device_path_stat(
                numbered,
                action="choosing a rebuild destination",
            ) is None:
                return numbered
        raise RuntimeError(f"Could not choose rebuild destination for {path.name}")

    @staticmethod
    def _preserve_trackinfo_state(rebuilt: TrackInfo, existing: TrackInfo) -> None:
        for attr in (
            "track_id",
            "db_track_id",
            "rating",
            "play_count",
            "play_count_2",
            "skip_count",
            "last_played",
            "last_skipped",
            "date_added",
            "date_added_to_itunes",
            "bookmark_time",
            "checked_flag",
            "media_type",
            "album_id",
            "artwork_count",
            "artwork_size",
            "mhii_link",
            "user_id",
            "app_rating",
            "store_track_id",
            "store_artist_id",
            "store_album_id",
            "store_content_flag",
        ):
            if hasattr(existing, attr):
                setattr(rebuilt, attr, getattr(existing, attr))

    def _execute_chaptered_aggregate_rebuild(
        self,
        ctx: _SyncContext,
        item: SyncItem,
    ) -> bool:
        db_track_id = item.db_track_id or 0
        existing = ctx.tracks_by_db_track_id.get(db_track_id)
        if existing is None:
            ctx.result.errors.append((
                item.description,
                f"Chaptered album track {db_track_id} was not found in the iPod database",
            ))
            return False

        old_location = existing.location
        if not old_location:
            ctx.result.errors.append((item.description, "Chaptered album has no iPod location"))
            return False

        old_full_path = expected_ipod_track_file_path(self.ipod_path, old_location)
        if old_full_path is None:
            ctx.result.errors.append((
                item.description,
                f"Could not resolve chaptered album iPod location {old_location}",
            ))
            return False
        track_dicts = [
            self._track_dict_from_pc_track(pc_track, index)
            for index, pc_track in enumerate(item.aggregate_rebuild_pc_tracks, start=1)
        ]
        album_item = {
            "album": track_dicts[0].get("Album") or existing.album or existing.title,
            "title": track_dicts[0].get("Album") or existing.album or existing.title,
            "artist": track_dicts[0].get("Album Artist") or existing.album_artist or existing.artist or "",
        }
        source_fps = list(item.aggregate_contains_fingerprints or [])
        sources = [
            ResolvedAlbumSource(
                track=track,
                source_path=Path(pc_track.path),
                source_kind="pc",
                fingerprint=source_fps[index - 1] if index - 1 < len(source_fps) else None,
            )
            for index, (track, pc_track) in enumerate(
                zip(track_dicts, item.aggregate_rebuild_pc_tracks, strict=False),
                start=1,
            )
        ]

        try:
            with tempfile.TemporaryDirectory(prefix="iopenpod_rebuild_chaptered_") as tmp:
                converted = convert_album_to_chaptered_track(
                    album_item=album_item,
                    tracks=track_dicts,
                    sources=sources,
                    output_dir=Path(tmp),
                    settings=self.transcode_options,
                    artwork_bytes=None,
                )

                destination = self._unique_rebuild_destination(
                    old_full_path,
                    converted.output_path.suffix,
                )
                tmp_destination = destination.with_name(
                    f"{destination.name}.iopenpodtmp"
                )
                try:
                    self._copy_stripped_file_to_device(
                        converted.output_path,
                        tmp_destination,
                        is_cancelled=ctx._is_cancelled,
                    )
                    with self._device_write_semaphore:
                        self._revalidate_device_write_readiness()
                        durable_replace(tmp_destination, destination)
                finally:
                    with self._device_write_semaphore:
                        self._revalidate_device_write_readiness()
                        durable_unlink(tmp_destination, missing_ok=True)

                ipod_location = ipod_location_from_file_path(
                    self.ipod_path,
                    destination,
                )
                rebuilt = self._pc_track_to_info(
                    converted.pc_track,
                    ipod_location,
                    False,
                    ipod_file_path=destination,
                )
                self._preserve_trackinfo_state(rebuilt, existing)
                rebuilt.db_track_id = db_track_id
                rebuilt.location = ipod_location
                rebuilt.size = destination.stat().st_size
                rebuilt.chapter_data = {"chapters": converted.chapters}

                if old_location in ctx.tracks_by_location:
                    del ctx.tracks_by_location[old_location]
                ctx.tracks_by_location[ipod_location] = rebuilt
                ctx.tracks_by_db_track_id[db_track_id] = rebuilt

                if old_full_path != destination:
                    self._delete_from_ipod(old_full_path)

                new_fingerprint, _fingerprint_status = (
                    get_or_compute_fingerprint_with_status(
                        converted.output_path,
                        fpcalc_path=self.fpcalc_path,
                        write_to_file=False,
                    )
                )
                new_fingerprint = new_fingerprint or item.fingerprint

                existing_mapping = (
                    ctx.mapping.get_by_db_track_id(db_track_id)
                    if db_track_id else None
                )
                old_fingerprint = existing_mapping[0] if existing_mapping else item.fingerprint
                if old_fingerprint and new_fingerprint != old_fingerprint:
                    ctx.mapping.remove_track(old_fingerprint, db_track_id=db_track_id)
                mapping_fingerprint = new_fingerprint or old_fingerprint
                if not mapping_fingerprint:
                    ctx.result.errors.append((
                        item.description,
                        "Rebuilt chaptered album, but could not determine its fingerprint",
                    ))
                    return False

                source_hash = None
                try:
                    source_hash = source_content_hash(converted.output_path)
                except OSError:
                    pass
                converted_stat = converted.output_path.stat()
                ctx.mapping.add_track(
                    fingerprint=mapping_fingerprint,
                    db_track_id=db_track_id,
                    source_format=converted.output_path.suffix.lstrip("."),
                    ipod_format=destination.suffix.lstrip("."),
                    source_size=converted_stat.st_size,
                    source_mtime=converted_stat.st_mtime,
                    was_transcoded=False,
                    source_path_hint=(
                        existing_mapping[1].source_path_hint
                        if existing_mapping else None
                    ),
                    art_hash=(
                        existing_mapping[1].art_hash
                        if existing_mapping else None
                    ),
                    source_hash=source_hash,
                    aggregate_kind="chaptered_album",
                    contains_fingerprints=item.aggregate_contains_fingerprints,
                    contains_sources=item.aggregate_contains_sources,
                )
                ctx.pc_file_paths[db_track_id] = str(destination)
                return True
        except (_CancelledError, _OutOfSpaceError):
            raise
        except Exception as exc:
            ctx.result.errors.append((item.description, f"Failed to rebuild chaptered album: {exc}"))
            logger.error("Failed to rebuild chaptered album %s: %s", db_track_id, exc)
            return False

    def _execute_file_updates(self, ctx: _SyncContext) -> None:
        if not ctx.plan.to_update_file:
            return

        aggregate_rebuilds = [
            item for item in ctx.plan.to_update_file
            if self._is_chaptered_aggregate_rebuild(item)
        ]
        regular_updates = [
            item for item in ctx.plan.to_update_file
            if not self._is_chaptered_aggregate_rebuild(item)
        ]

        self._execute_chaptered_aggregate_rebuild_items(
            ctx,
            aggregate_rebuilds,
            stage_name="update_file",
            start_message="Rebuilding changed chaptered albums...",
        )

        if not regular_updates:
            return

        ctx.progress("update_file", 0, len(regular_updates),
                     message="Re-syncing changed files...")

        if ctx.dry_run:
            for i, item in enumerate(regular_updates):
                if ctx.cancelled():
                    return
                ctx.progress("update_file", i + 1, len(regular_updates),
                             item, item.description)
                ctx.result.tracks_updated_file += 1
            return

        def _on_success(item: SyncItem, ipod_path: Path, was_transcoded: bool) -> None:
            assert item.pc_track is not None  # guaranteed by _parallel_copy_stage filter
            ipod_location = ipod_location_from_file_path(self.ipod_path, ipod_path)
            source_path = Path(item.pc_track.path)

            # Update existing TrackInfo
            db_track_id = item.db_track_id
            if db_track_id and db_track_id in ctx.tracks_by_db_track_id:
                existing_track = ctx.tracks_by_db_track_id[db_track_id]
                old_location = existing_track.location
                if existing_track.location in ctx.tracks_by_location:
                    del ctx.tracks_by_location[existing_track.location]
                existing_track.location = ipod_location
                existing_track.size = ipod_path.stat().st_size

                ext = ipod_path.suffix.lower().lstrip(".")
                if ext in ("m4a", "mp4"):
                    existing_track.filetype = "m4a"
                elif ext == "mp3":
                    existing_track.filetype = "mp3"
                elif ext == "wav":
                    existing_track.filetype = "wav"
                else:
                    existing_track.filetype = ext

                if was_transcoded:
                    if ext in ("m4a", "aac", "mp3") and ext != "alac":
                        plan = self._transcode_plan_for_item(item, source_path)
                        existing_track.bitrate = (
                            plan.cache_bitrate_kbps
                            if plan.cache_bitrate_kbps is not None
                            else quality_to_nominal_bitrate(
                                plan.effective_quality,
                                self.transcode_options,
                            )
                        )

                if item.pc_track.duration_ms:
                    existing_track.length = item.pc_track.duration_ms
                if item.pc_track.sample_rate:
                    existing_track.sample_rate = item.pc_track.sample_rate
                if item.pc_track.chapters:
                    existing_track.chapter_data = {"chapters": item.pc_track.chapters}

                # IMPORTANT: Preserve media_type from the existing iPod track.
                # Don't recalculate it from the current file's metadata (stik atom),
                # which may be missing or inconsistent between syncs.
                # (media_type is already set from the original file, no change needed)

                ctx.tracks_by_location[ipod_location] = existing_track

                # Replacement succeeded: remove the old on-device file path.
                if old_location and old_location != ipod_location:
                    try:
                        old_full = expected_ipod_track_file_path(
                            self.ipod_path,
                            old_location,
                        )
                        if old_full is not None:
                            self._delete_from_ipod(old_full)
                    except Exception as exc:
                        logger.warning("Could not remove old iPod file %s: %s", old_location, exc)

            if db_track_id:
                ctx.pc_file_paths[db_track_id] = str(source_path)

            if item.fingerprint and ipod_path:
                source_size, source_mtime, source_hash = _current_source_identity(item.pc_track)
                existing = None
                fp_result = ctx.mapping.get_by_db_track_id(db_track_id) if db_track_id else None
                if fp_result:
                    _old_fp, existing = fp_result
                ctx.mapping.add_track(
                    fingerprint=item.fingerprint,
                    db_track_id=db_track_id or 0,
                    source_format=source_path.suffix.lstrip("."),
                    ipod_format=ipod_path.suffix.lstrip("."),
                    source_size=source_size,
                    source_mtime=source_mtime,
                    was_transcoded=was_transcoded,
                    source_path_hint=item.pc_track.relative_path,
                    art_hash=getattr(item.pc_track, "art_hash", None),
                    source_hash=source_hash,
                    aggregate_kind=(
                        item.aggregate_kind
                        or (existing.aggregate_kind if existing else None)
                    ),
                    contains_fingerprints=(
                        item.aggregate_contains_fingerprints
                        or (existing.contains_fingerprints if existing else None)
                    ),
                    contains_sources=(
                        item.aggregate_contains_sources
                        or (existing.contains_sources if existing else None)
                    ),
                )

            ctx.result.tracks_updated_file += 1

        self._parallel_copy_stage(
            ctx,
            stage_name="update_file",
            items=regular_updates,
            on_success=_on_success,
            error_prefix="Failed to re-sync",
        )

    # Metadata field name → (TrackInfo attribute, coercion).
    # Coercion: None = pass-through, "int" = int-or-0, "int1" = int-or-1,
    #           "bool" = bool().
    _META_FIELD_MAP: dict[str, tuple[str, str | None]] = {
        # Core string fields
        "title": ("title", None),
        "artist": ("artist", None),
        "album": ("album", None),
        "album_artist": ("album_artist", None),
        "genre": ("genre", None),
        "composer": ("composer", None),
        "comment": ("comment", None),
        "grouping": ("grouping", None),
        "lyrics": ("lyrics", None),
        # Integer-or-zero fields
        "year": ("year", "int"),
        "track_number": ("track_number", "int"),
        "track_total": ("total_tracks", "int"),
        "disc_number": ("disc_number", "int"),
        "disc_total": ("total_discs", "int1"),
        "bpm": ("bpm", "int"),
        "explicit_flag": ("explicit_flag", "int"),
        "play_count_1": ("play_count", "int"),
        "skip_count": ("skip_count", "int"),
        "media_type": ("media_type", "int"),
        "date_added": ("date_added", "int"),
        "last_modified": ("last_modified", "int"),
        "last_played": ("last_played", "int"),
        "last_skipped": ("last_skipped", "int"),
        "date_added_to_itunes": ("date_added_to_itunes", "int"),
        "season_number": ("season_number", "int"),
        "episode_number": ("episode_number", "int"),
        "sound_check": ("sound_check", "int"),
        "gapless_track_flag": ("gapless_track_flag", "int"),
        "gapless_album_flag": ("gapless_album_flag", "int"),
        "checked_flag": ("checked_flag", "int"),
        "not_played_flag": ("played_mark", "int"),
        "volume": ("volume", "int"),
        "start_time": ("start_time", "int"),
        "stop_time": ("stop_time", "int"),
        "bookmark_time": ("bookmark_time", "int"),
        "movie_flag": ("movie_file_flag", "int"),
        "use_podcast_now_playing_flag": ("podcast_flag", "int"),
        # Boolean fields
        "compilation": ("compilation_flag", "bool"),
        "skip_when_shuffling": ("skip_when_shuffling", "bool"),
        "remember_position": ("remember_position", "bool"),
        # Sort fields
        "sort_name": ("sort_name", None),
        "Sort Title": ("sort_name", None),
        "sort_artist": ("sort_artist", None),
        "sort_album": ("sort_album", None),
        "sort_album_artist": ("sort_album_artist", None),
        "sort_composer": ("sort_composer", None),
        "sort_show": ("sort_show", None),
        "Sort Name": ("sort_name", None),
        # Video/TV show fields
        "show_name": ("show_name", None),
        "description": ("description", None),
        "episode_id": ("episode_id", None),
        "network_name": ("network_name", None),
        "subtitle": ("subtitle", None),
        "category": ("category", None),
        # Other MHOD string fields
        "eq_setting": ("eq_setting", None),
        "Track Keywords": ("keywords", None),
        "Show Locale": ("show_locale", None),
        # Podcast fields (field_name ≠ attr_name)
        "podcast_url": ("podcast_rss_url", None),
        "podcast_enclosure_url": ("podcast_enclosure_url", None),
        "date_released": ("date_released", "int"),
        "duration_ms": ("length", "int"),
        # iTunesDB chapter data is DB-side and applies regardless of filetype.
        "chapter_data": ("chapter_data", None),
    }

    def _execute_metadata_updates(self, ctx: _SyncContext) -> None:
        if not ctx.plan.to_update_metadata:
            return

        ctx.progress("update_metadata", 0, len(ctx.plan.to_update_metadata),
                     message="Updating metadata...")

        for i, item in enumerate(ctx.plan.to_update_metadata):
            if ctx.cancelled():
                return

            ctx.progress("update_metadata", i + 1, len(ctx.plan.to_update_metadata),
                         item, item.description)

            if ctx.dry_run:
                ctx.result.tracks_updated_metadata += 1
                continue

            db_track_id = item.db_track_id
            if db_track_id and db_track_id in ctx.tracks_by_db_track_id:
                track = ctx.tracks_by_db_track_id[db_track_id]
                for field_name, (pc_value, _ipod_value) in item.metadata_changes.items():
                    mapping_entry = self._META_FIELD_MAP.get(field_name)
                    if mapping_entry is not None:
                        attr, coerce = mapping_entry
                        if coerce == "int":
                            setattr(track, attr, pc_value if pc_value else 0)
                        elif coerce == "int1":
                            setattr(track, attr, pc_value if pc_value else 1)
                        elif coerce == "bool":
                            setattr(track, attr, bool(pc_value))
                        else:
                            setattr(track, attr, pc_value)

            # Refresh mapping mtime/size so next sync doesn't see a spurious file change
            if item.fingerprint and item.pc_track and not ctx.dry_run:
                fp_result = ctx.mapping.get_by_db_track_id(db_track_id) if db_track_id else None
                if fp_result:
                    fp, existing = fp_result
                    source_size, source_mtime, source_hash = _current_source_identity(item.pc_track)
                    ctx.mapping.add_track(
                        fingerprint=fp,
                        db_track_id=db_track_id or 0,
                        source_format=existing.source_format,
                        ipod_format=existing.ipod_format,
                        source_size=source_size,
                        source_mtime=source_mtime,
                        was_transcoded=existing.was_transcoded,
                        source_path_hint=item.pc_track.relative_path,
                        art_hash=existing.art_hash,
                        source_hash=source_hash,
                        aggregate_kind=(
                            item.aggregate_kind or existing.aggregate_kind
                        ),
                        contains_fingerprints=(
                            item.aggregate_contains_fingerprints
                            or existing.contains_fingerprints
                        ),
                        contains_sources=(
                            item.aggregate_contains_sources
                            or existing.contains_sources
                        ),
                    )
            elif item.aggregate_kind and item.fingerprint and db_track_id and not ctx.dry_run:
                fp_result = ctx.mapping.get_by_db_track_id(db_track_id)
                if fp_result:
                    fp, existing = fp_result
                    ctx.mapping.add_track(
                        fingerprint=fp,
                        db_track_id=db_track_id,
                        source_format=existing.source_format,
                        ipod_format=existing.ipod_format,
                        source_size=existing.source_size,
                        source_mtime=existing.source_mtime,
                        was_transcoded=existing.was_transcoded,
                        source_path_hint=existing.source_path_hint,
                        art_hash=existing.art_hash,
                        source_hash=existing.source_hash,
                        aggregate_kind=item.aggregate_kind or existing.aggregate_kind,
                        contains_fingerprints=(
                            item.aggregate_contains_fingerprints
                            or existing.contains_fingerprints
                        ),
                        contains_sources=(
                            item.aggregate_contains_sources
                            or existing.contains_sources
                        ),
                    )

            ctx.result.tracks_updated_metadata += 1

    def _execute_artwork_updates(self, ctx: _SyncContext) -> None:
        """Update mapping art_hash for tracks with changed artwork.

        The actual artwork re-encoding is handled by the full ArtworkDB rewrite
        since we always pass pc_file_paths to write_artworkdb(). This method
        only ensures the mapping stays in sync so we don't detect the same
        change again next sync.
        """
        if not ctx.plan.to_update_artwork or ctx.dry_run:
            return

        for item in ctx.plan.to_update_artwork:
            if not item.fingerprint:
                continue
            fp_result = ctx.mapping.get_by_db_track_id(item.db_track_id) if item.db_track_id else None
            if fp_result:
                fp, existing = fp_result
                source_size = existing.source_size
                source_mtime = existing.source_mtime
                source_hash = existing.source_hash
                source_path_hint = existing.source_path_hint
                if item.pc_track:
                    source_size, source_mtime, source_hash = _current_source_identity(
                        item.pc_track
                    )
                    source_path_hint = item.pc_track.relative_path
                ctx.mapping.add_track(
                    fingerprint=fp,
                    db_track_id=item.db_track_id or 0,
                    source_format=existing.source_format,
                    ipod_format=existing.ipod_format,
                    source_size=source_size,
                    source_mtime=source_mtime,
                    was_transcoded=existing.was_transcoded,
                    source_path_hint=source_path_hint,
                    art_hash=item.new_art_hash,
                    source_hash=source_hash,
                    aggregate_kind=existing.aggregate_kind,
                    contains_fingerprints=existing.contains_fingerprints,
                    contains_sources=existing.contains_sources,
                )

    def _download_podcast_episodes(self, ctx: _SyncContext) -> None:
        """Download podcast episodes that were selected in the plan but
        don't have local files yet.  Runs before the add stage so the
        copy/transcode pipeline has real files to work with.
        """
        if not ctx.plan.to_add:
            return

        from iopenpod.podcasts.downloader import DeviceDownloadSafety

        podcast_subtree = Path("iPod_Control") / "iOpenPodPodcasts"

        def _device_cache_context(
            path: Path,
        ) -> tuple[Path, DeviceDownloadSafety] | None:
            """Return a contained device path and its retained safety policy.

            Podcast episode downloads normally live in the host transcode
            cache.  Legacy subscription data can still name an iPod-resident
            cache file; only those paths receive device write policy.
            """
            if not path.is_absolute():
                return None

            root = Path(os.path.abspath(self.ipod_path))
            candidate = Path(os.path.abspath(path))
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                return None

            try:
                contained = resolve_device_path(
                    self.ipod_path,
                    relative,
                    allowed_subtree=podcast_subtree,
                )
                subtree_root = resolve_device_path(
                    self.ipod_path,
                    podcast_subtree,
                    allowed_subtree=podcast_subtree,
                )
            except (OSError, UnsafeDevicePathError) as exc:
                raise DeviceWriteSafetyError(
                    "A podcast cache path is outside the contained "
                    "iPod_Control/iOpenPodPodcasts directory. iOpenPod "
                    "stopped before accessing it."
                ) from exc

            profile = ctx.filesystem_profile or self._filesystem_profile
            if profile is None:
                raise DeviceWriteSafetyError(
                    "An iPod-resident podcast cache cannot be accessed "
                    "without a retained filesystem safety profile."
                )
            safety = DeviceDownloadSafety(
                before_device_io=self._revalidate_device_write_readiness,
                free_space_path=self.ipod_path,
                max_file_size_bytes=self._effective_max_file_size_bytes(),
                max_component_length=profile.max_component_length,
                allocation_unit_size=profile.allocation_unit_size,
            )
            try:
                descendant = contained.relative_to(subtree_root)
            except ValueError as exc:
                raise DeviceWriteSafetyError(
                    "A podcast cache path escaped the contained iPod "
                    "podcast directory."
                ) from exc
            for component in descendant.parts:
                safety.require_component_supported(component)
            return contained, safety

        def _source_if_present(
            source: Path,
        ) -> tuple[Path | None, DeviceDownloadSafety | None]:
            device_context = _device_cache_context(source)
            if device_context is None:
                return (source, None) if source.exists() else (None, None)

            contained, safety = device_context
            safety.revalidate()
            try:
                source_stat = contained.stat()
            except FileNotFoundError:
                return None, safety
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    "Could not safely inspect the iPod podcast cache file "
                    f"{contained.name}: {exc}"
                ) from exc
            if not stat.S_ISREG(source_stat.st_mode):
                raise DeviceWriteSafetyError(
                    "The selected iPod podcast cache source is not a regular "
                    f"file: {contained}"
                )
            safety.require_size_supported(source_stat.st_size, contained.name)
            return contained, safety

        # Existing podcast cache files may still need artwork embedded or
        # their art hash refreshed before the final ArtworkDB pass.
        existing: list[SyncItem] = []

        # Identify podcast add items whose source file is missing
        pending: list[SyncItem] = []
        for item in ctx.plan.to_add:
            if item.pc_track is None:
                continue
            if not item.pc_track.is_podcast:
                continue
            source = Path(item.pc_track.path) if item.pc_track.path else None
            present_source, _source_safety = (
                _source_if_present(source) if source is not None else (None, None)
            )
            if present_source is not None:
                existing.append(item)
                continue
            if item.pc_track.podcast_enclosure_url:
                pending.append(item)

        if not pending and not existing:
            return

        from iopenpod.podcasts.artwork import (
            is_remote_artwork_source,
            resolve_feed_artwork_source,
            resolve_local_artwork_path,
        )
        from iopenpod.podcasts.downloader import download_and_probe_episode, probe_episode_file
        from iopenpod.podcasts.models import normalize_artwork_url

        from ._formats import IPOD_NATIVE_AUDIO

        failed_items: list[SyncItem] = []
        artwork_source_cache: dict[str, str] = {}

        def _artwork_source(feed_url: str) -> str:
            if feed_url in artwork_source_cache:
                return artwork_source_cache[feed_url]
            if not feed_url:
                artwork_source_cache[feed_url] = ""
                return ""
            source = ""
            try:
                from iopenpod.podcasts.subscription_store import SubscriptionStore
                if self.ipod_path:
                    reported_format = str(
                        getattr(self.device_storage, "reported_volume_format", "") or ""
                    )
                    expected_volume_key = str(
                        getattr(self.device_storage, "volume_identity_key", "") or ""
                    )
                    subscriptions_path = resolve_device_path(
                        self.ipod_path,
                        podcast_subtree / "subscriptions.json",
                        allowed_subtree=podcast_subtree,
                    )
                    self._revalidate_device_write_readiness()
                    try:
                        subscriptions_stat = subscriptions_path.stat()
                    except FileNotFoundError:
                        artwork_source_cache[feed_url] = ""
                        return ""
                    except OSError as exc:
                        raise DeviceWriteSafetyError(
                            "Could not safely inspect podcast subscriptions "
                            f"on the iPod: {exc}"
                        ) from exc
                    if not stat.S_ISREG(subscriptions_stat.st_mode):
                        raise DeviceWriteSafetyError(
                            "The iPod podcast subscriptions path is not a "
                            "regular file."
                        )
                    _store = SubscriptionStore(
                        str(self.ipod_path),
                        reported_volume_format=reported_format,
                        expected_volume_identity_key=expected_volume_key,
                    )
                    _feed = _store.get_feed(feed_url)
                    self._revalidate_device_write_readiness()
                    if _feed:
                        artwork_path = str(
                            getattr(_feed, "artwork_path", "") or ""
                        ).strip()
                        local_path = resolve_local_artwork_path(
                            artwork_path,
                            _store.podcast_dir,
                        )
                        local_context = (
                            _device_cache_context(local_path)
                            if local_path is not None
                            else None
                        )
                        if local_context is not None:
                            contained_artwork, artwork_safety = local_context
                            artwork_safety.revalidate()
                            try:
                                artwork_stat = contained_artwork.stat()
                            except FileNotFoundError:
                                artwork_stat = None
                            except OSError as exc:
                                raise DeviceWriteSafetyError(
                                    "Could not safely inspect cached podcast "
                                    f"artwork on the iPod: {exc}"
                                ) from exc
                            if artwork_stat is not None:
                                if not stat.S_ISREG(artwork_stat.st_mode):
                                    raise DeviceWriteSafetyError(
                                        "Cached podcast artwork on the iPod "
                                        "is not a regular file."
                                    )
                                source = str(contained_artwork)
                        elif local_path is not None:
                            source = resolve_feed_artwork_source(
                                _feed,
                                _store.podcast_dir,
                            )

                        if not source:
                            artwork_url = normalize_artwork_url(
                                str(getattr(_feed, "artwork_url", "") or "")
                            )
                            if artwork_url:
                                source = artwork_url
                            elif is_remote_artwork_source(artwork_path):
                                source = artwork_path
            except DeviceWriteSafetyError:
                raise
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not safely read podcast artwork metadata: {exc}"
                ) from exc
            except Exception as exc:
                logger.debug(
                    "Could not resolve artwork for podcast feed %s: %s",
                    feed_url,
                    exc,
                )
            artwork_source_cache[feed_url] = source
            return source

        def _apply_episode_info(pc, info) -> None:
            pc.path = info.path
            pc.size = info.size
            pc.mtime = info.mtime
            pc.filename = Path(info.path).name
            pc.relative_path = Path(info.path).name
            pc.extension = info.extension
            if info.bitrate is not None:
                pc.bitrate = info.bitrate
            if info.sample_rate is not None:
                pc.sample_rate = info.sample_rate
            if info.duration_ms is not None:
                pc.duration_ms = info.duration_ms
            if info.art_hash is not None or not getattr(pc, "art_hash", None):
                pc.art_hash = info.art_hash
            pc.needs_transcoding = pc.extension not in IPOD_NATIVE_AUDIO

        pending_estimates = [
            max(
                int(item.estimated_size or 0),
                int(getattr(item.pc_track, "size", 0) or 0),
            )
            for item in pending
        ]
        completed_download_bytes = 0

        def _download_total(current_idx: int, current_downloaded: int) -> int:
            total = completed_download_bytes
            for idx, estimate in enumerate(pending_estimates):
                if idx < current_idx:
                    continue
                if idx == current_idx:
                    total += max(estimate, current_downloaded)
                else:
                    total += estimate
            return total

        if pending:
            initial_total = sum(pending_estimates)
            ctx.progress(
                "podcast_download",
                0,
                initial_total,
                message=(
                    f"Downloading {len(pending)} podcast episode"
                    f"{'s' if len(pending) != 1 else ''}..."
                ),
                size_progress=0.0 if initial_total > 0 else None,
            )

        for item in existing:
            pc = item.pc_track
            assert pc is not None
            source = Path(pc.path) if pc.path else None
            present_source, source_safety = (
                _source_if_present(source) if source is not None else (None, None)
            )
            if present_source is None:
                continue
            try:
                info = probe_episode_file(
                    str(present_source),
                    artwork_url=_artwork_source(pc.podcast_url or ""),
                    device_safety=source_safety,
                )
                _apply_episode_info(pc, info)
            except DeviceWriteSafetyError:
                raise
            except OSError as exc:
                if source_safety is not None:
                    raise DeviceWriteSafetyError(
                        "Could not safely prepare the iPod podcast cache file "
                        f"{present_source.name}: {exc}"
                    ) from exc
                logger.debug(
                    "Could not prepare existing podcast file %s: %s",
                    present_source,
                    exc,
                )
            except Exception as exc:
                logger.debug(
                    "Could not prepare existing podcast file %s: %s",
                    present_source,
                    exc,
                )

        for idx, item in enumerate(pending):
            if ctx.cancelled():
                return

            pc = item.pc_track
            assert pc is not None
            enc_url = pc.podcast_enclosure_url or ""
            feed_url = pc.podcast_url or ""
            title = pc.title or "Episode"

            # Determine download destination directory
            dest_dir = str(Path(pc.path).parent) if pc.path else ""
            if not dest_dir:
                import hashlib
                url_hash = hashlib.sha256(feed_url.encode()).hexdigest()[:16]
                base = str(self.transcode_cache.cache_dir)
                dest_dir = str(Path(base) / "podcasts" / url_hash)

            device_destination = _device_cache_context(Path(dest_dir))
            if device_destination is not None:
                contained_destination, download_safety = device_destination
                dest_dir = str(contained_destination)
            else:
                download_safety = None

            try:
                last_downloaded = 0
                last_report = 0.0
                download_base = completed_download_bytes

                def _on_download_progress(
                    downloaded: int,
                    total_bytes: int,
                    *,
                    _idx: int = idx,
                    _item: SyncItem = item,
                    _title: str = title,
                    _base: int = download_base,
                ) -> None:
                    nonlocal last_downloaded, last_report
                    last_downloaded = max(0, int(downloaded or 0))
                    if total_bytes and total_bytes > 0:
                        pending_estimates[_idx] = int(total_bytes)

                    stage_total = _download_total(_idx, last_downloaded)
                    current = _base + last_downloaded
                    now = time.monotonic()
                    if current < stage_total and now - last_report < 0.05:
                        return
                    last_report = now

                    progress_fraction = (
                        min(current / stage_total, 1.0)
                        if stage_total > 0
                        else None
                    )
                    if stage_total > 0:
                        progress_text = (
                            f"{_format_bytes(current)} / {_format_bytes(stage_total)}"
                        )
                    else:
                        progress_text = _format_bytes(current)
                    ctx.progress(
                        "podcast_download",
                        current,
                        stage_total,
                        _item,
                        f"Downloading {_title} ({progress_text})",
                        size_progress=progress_fraction,
                    )

                info = download_and_probe_episode(
                    audio_url=enc_url,
                    title=title,
                    dest_dir=dest_dir,
                    artwork_url=_artwork_source(feed_url),
                    progress_cb=_on_download_progress,
                    cancel_token=ctx,
                    device_safety=download_safety,
                )
                _apply_episode_info(pc, info)
                completed_download_bytes += max(
                    int(info.size or 0),
                    last_downloaded,
                )
                final_total = _download_total(idx + 1, 0)
                ctx.progress(
                    "podcast_download",
                    completed_download_bytes,
                    final_total,
                    item,
                    f"Downloaded {title}",
                    size_progress=(
                        min(completed_download_bytes / final_total, 1.0)
                        if final_total > 0
                        else None
                    ),
                )

                logger.info("Downloaded podcast: %s", title)

            except DeviceWriteSafetyError:
                raise
            except OSError as exc:
                if download_safety is not None:
                    raise DeviceWriteSafetyError(
                        "Could not safely write the iPod podcast cache for "
                        f"{title}: {exc}"
                    ) from exc
                logger.warning("Failed to download podcast %s: %s", title, exc)
                failed_items.append(item)
            except Exception as exc:
                logger.warning("Failed to download podcast %s: %s", title, exc)
                failed_items.append(item)

        # Remove failed downloads from the add list
        if failed_items:
            failed_set = set(id(item) for item in failed_items)
            ctx.plan.to_add = [
                item for item in ctx.plan.to_add
                if id(item) not in failed_set
            ]

        if pending:
            final_total = max(completed_download_bytes, sum(pending_estimates))
            ctx.progress(
                "podcast_download",
                completed_download_bytes,
                final_total,
                message=f"Downloaded {len(pending) - len(failed_items)} podcast episodes",
                size_progress=(
                    min(completed_download_bytes / final_total, 1.0)
                    if final_total > 0
                    else None
                ),
            )

    def _execute_adds(self, ctx: _SyncContext) -> None:
        if not ctx.plan.to_add:
            return

        ctx.progress("add", 0, len(ctx.plan.to_add), message="Adding new tracks...")

        if ctx.dry_run:
            for i, item in enumerate(ctx.plan.to_add):
                if ctx.cancelled():
                    return
                ctx.progress("add", i + 1, len(ctx.plan.to_add), item, item.description)
                if item.pc_track is not None:
                    self._record_conversion_group_add_success(ctx, item)
                    ctx.result.tracks_added += 1
            return

        def _on_success(item: SyncItem, ipod_path: Path, was_transcoded: bool) -> None:
            assert item.pc_track is not None  # guaranteed by _parallel_copy_stage filter
            ipod_location = ipod_location_from_file_path(self.ipod_path, ipod_path)
            track_info = self._pc_track_to_info(item.pc_track, ipod_location, was_transcoded, ipod_file_path=ipod_path)
            ctx.new_tracks.append(track_info)

            ctx.pc_file_paths[id(track_info)] = str(item.pc_track.path)
            ctx.new_track_info[id(track_info)] = (item.pc_track, ipod_path, was_transcoded, item)

            fingerprint = item.fingerprint
            if fingerprint:
                ctx.new_track_fingerprints[id(track_info)] = fingerprint

            self._record_conversion_group_add_success(ctx, item)

            ctx.result.tracks_added += 1

        self._parallel_copy_stage(
            ctx,
            stage_name="add",
            items=ctx.plan.to_add,
            on_success=_on_success,
            error_prefix="Failed to copy/transcode",
        )

    def _execute_sound_check(self, ctx: _SyncContext) -> None:
        """Compute Sound Check (loudness normalization) for tracks missing it."""
        if not ctx.compute_sound_check:
            return

        write_back = ctx.write_back_to_pc

        VIDEO_TYPES = {
            MEDIA_TYPE_VIDEO, MEDIA_TYPE_MUSIC_VIDEO,
            MEDIA_TYPE_TV_SHOW, MEDIA_TYPE_VIDEO_PODCAST,
        }

        candidates: list[tuple[TrackInfo, str]] = []

        for t in ctx.new_tracks:
            if t.sound_check or t.media_type in VIDEO_TYPES:
                continue
            info = ctx.new_track_info.get(id(t))
            if info:
                pc_track, _ipod_path, _was_transcoded = info[:3]
                candidates.append((t, pc_track.path))

        for db_track_id, pc_path in ctx.pc_file_paths.items():
            existing_track: TrackInfo | None = ctx.tracks_by_db_track_id.get(db_track_id)
            if (
                existing_track
                and not existing_track.sound_check
                and existing_track.media_type not in VIDEO_TYPES
            ):
                candidates.append((existing_track, pc_path))

        if not candidates:
            return

        from iopenpod.sync.pc_library import compute_sound_check, write_sound_check_tag

        ctx.progress("sound_check", 0, len(candidates),
                     message=f"Computing Sound Check for {len(candidates)} tracks…")

        computed = 0
        for idx, (track_info, pc_path) in enumerate(candidates):
            if ctx.cancelled():
                return

            sc_val = compute_sound_check(pc_path) if not ctx.dry_run else 0
            if sc_val:
                track_info.sound_check = sc_val
                computed += 1
                if write_back:
                    write_sound_check_tag(pc_path, sc_val)

            label = track_info.title or Path(pc_path).stem
            ctx.progress("sound_check", idx + 1, len(candidates),
                         message=f"Sound Check: {label}")

        ctx.result.sound_check_computed = computed
        logger.info("Computed Sound Check for %d / %d tracks", computed, len(candidates))

    def _execute_playcount_sync(self, ctx: _SyncContext) -> None:
        """Report iPod play count deltas (merged in _read_existing_database)."""
        if not ctx.plan.to_sync_playcount:
            return

        ctx.progress("sync_playcount", 0, len(ctx.plan.to_sync_playcount),
                     message="Syncing play counts...")

        for i, item in enumerate(ctx.plan.to_sync_playcount):
            if ctx.cancelled():
                return

            ctx.progress("sync_playcount", i + 1, len(ctx.plan.to_sync_playcount),
                         item, item.description)

            logger.debug(
                "Play count sync: %s  +%d plays  +%d skips",
                item.description, item.play_count_delta, item.skip_count_delta,
            )
            ctx.result.playcounts_synced += 1

    def _execute_scrobble(self, ctx: _SyncContext) -> bool:
        """Submit new plays to each connected scrobbling service."""
        if not ctx.scrobble_on_sync:
            return True

        listenbrainz_enabled = bool(ctx.listenbrainz_token)
        lastfm_configured = bool(ctx.lastfm_session_key)
        lastfm_enabled = all(
            (
                ctx.lastfm_api_key,
                ctx.lastfm_api_secret,
                ctx.lastfm_session_key,
            )
        )

        if not listenbrainz_enabled and not lastfm_configured:
            return True

        outcomes: list[_ScrobbleServiceOutcome] = []

        if listenbrainz_enabled:
            outcomes.append(self._execute_listenbrainz_scrobble(ctx))

        if lastfm_enabled:
            outcomes.append(self._execute_lastfm_scrobble(ctx))
        elif lastfm_configured:
            outcome = _ScrobbleServiceOutcome(
                service_key="lastfm",
                display_name="Last.fm",
                stage="scrobble_lastfm",
                errors=[
                    "Last.fm credentials are incomplete. Reconnect Last.fm in Settings."
                ],
            )
            self._finish_scrobble_service_progress(ctx, outcome)
            outcomes.append(outcome)

        total_accepted = sum(outcome.accepted for outcome in outcomes)
        ctx.result.scrobbles_submitted = total_accepted
        logger.info("Scrobbled %d plays across connected services", total_accepted)

        for outcome in outcomes:
            for error in outcome.errors:
                ctx.result.errors.append((outcome.service_key, error))

        return not any(outcome.errors for outcome in outcomes)

    @staticmethod
    def _format_scrobble_elapsed(seconds: float) -> str:
        total = max(int(seconds), 0)
        mins, secs = divmod(total, 60)
        hrs, mins = divmod(mins, 60)
        if hrs:
            return f"{hrs}h {mins}m {secs}s"
        if mins:
            return f"{mins}m {secs}s"
        return f"{secs}s"

    def _scrobble_should_abort(self, ctx: _SyncContext) -> bool:
        if ctx._is_scrobble_cancelled and ctx._is_scrobble_cancelled():
            return True
        if ctx._is_cancelled and ctx._is_cancelled():
            return True
        return False

    def _execute_listenbrainz_scrobble(self, ctx: _SyncContext) -> _ScrobbleServiceOutcome:
        from .lb_scrobbler import scrobble_plays

        return self._execute_scrobble_service(
            ctx,
            service_key="listenbrainz",
            display_name="ListenBrainz",
            stage="scrobble_listenbrainz",
            submit=lambda on_timeout, should_abort: scrobble_plays(
                playcount_items=self._scrobble_playcount_snapshot(ctx),
                listenbrainz_token=ctx.listenbrainz_token,
                listenbrainz_username=ctx.listenbrainz_username,
                on_timeout=on_timeout,
                should_abort=should_abort,
            ),
        )

    def _execute_lastfm_scrobble(self, ctx: _SyncContext) -> _ScrobbleServiceOutcome:
        from .lastfm_scrobbler import scrobble_plays

        return self._execute_scrobble_service(
            ctx,
            service_key="lastfm",
            display_name="Last.fm",
            stage="scrobble_lastfm",
            submit=lambda on_timeout, should_abort: scrobble_plays(
                playcount_items=self._scrobble_playcount_snapshot(ctx),
                api_key=ctx.lastfm_api_key,
                api_secret=ctx.lastfm_api_secret,
                session_key=ctx.lastfm_session_key,
                on_timeout=on_timeout,
                should_abort=should_abort,
            ),
        )

    @staticmethod
    def _scrobble_playcount_snapshot(ctx: _SyncContext) -> list[SyncItem]:
        """Return independent play-count items for one scrobbling service."""
        snapshot: list[SyncItem] = []
        for item in ctx.plan.to_sync_playcount:
            copied = copy(item)
            copied.ipod_track = dict(item.ipod_track) if item.ipod_track else None
            copied.metadata_changes = dict(item.metadata_changes)
            snapshot.append(copied)
        return snapshot

    @staticmethod
    def _clear_playcount_deltas(ctx: _SyncContext) -> None:
        """Clear transient iPod play deltas after every scrobble service has run."""
        for item in ctx.plan.to_sync_playcount:
            if item.db_track_id:
                track_info = ctx.tracks_by_db_track_id.get(item.db_track_id)
                if track_info is not None:
                    track_info.play_count_2 = 0
            if item.ipod_track is not None:
                item.ipod_track["play_count_2"] = 0
                item.ipod_track["recent_playcount"] = 0

    def _execute_scrobble_service(
        self,
        ctx: _SyncContext,
        *,
        service_key: str,
        display_name: str,
        stage: str,
        submit: Callable[
            [Callable[[float, int, int], None], Callable[[], bool]],
            list,
        ],
    ) -> _ScrobbleServiceOutcome:
        outcome = _ScrobbleServiceOutcome(
            service_key=service_key,
            display_name=display_name,
            stage=stage,
        )

        ctx.progress(stage, 0, 1, message=f"Submitting iPod plays to {display_name}...")

        def _on_timeout(elapsed: float, attempt: int, timeout_s: int) -> None:
            ctx.progress(
                stage,
                0,
                1,
                message=(
                    f"{display_name} is taking longer than usual to respond. "
                    "iOpenPod will keep trying. "
                    f"Elapsed {self._format_scrobble_elapsed(elapsed)} "
                    f"(attempt {attempt}, request timeout {timeout_s}s)."
                ),
            )

        try:
            logger.info("Invoking %s scrobbler module...", display_name)
            results = submit(_on_timeout, lambda: self._scrobble_should_abort(ctx))
            logger.info("%s scrobbler module returned %d result(s)", display_name, len(results))
        except Exception as exc:
            logger.error("%s scrobbling failed: %s", display_name, exc, exc_info=True)
            outcome.errors.append(str(exc))
            self._finish_scrobble_service_progress(ctx, outcome)
            return outcome

        for result in results:
            outcome.accepted += int(getattr(result, "accepted", 0) or 0)
            for error in list(getattr(result, "errors", []) or []):
                if "User gave up" in error:
                    outcome.gave_up = True
                logger.warning("%s scrobble error: %s", display_name, error)
                outcome.errors.append(str(error))

        self._finish_scrobble_service_progress(ctx, outcome)
        return outcome

    def _finish_scrobble_service_progress(
        self,
        ctx: _SyncContext,
        outcome: _ScrobbleServiceOutcome,
    ) -> None:
        accepted = outcome.accepted
        play_word = "play" if accepted == 1 else "plays"

        if outcome.gave_up:
            message = (
                f"Stopped retrying {outcome.display_name}. "
                f"{outcome.display_name} did not receive the remaining iPod plays."
            )
        elif outcome.errors:
            if accepted:
                message = (
                    f"{outcome.display_name} accepted {accepted} {play_word}, "
                    "but needs attention."
                )
            else:
                message = f"{outcome.display_name} did not accept any plays from this sync."
        elif accepted:
            message = f"{outcome.display_name} accepted {accepted} {play_word}."
        else:
            message = f"No qualifying iPod plays were submitted to {outcome.display_name}."

        ctx.progress(outcome.stage, 1, 1, message=message)

    def _execute_rating_sync(self, ctx: _SyncContext) -> None:
        if not ctx.plan.to_sync_rating:
            return

        ctx.progress("sync_rating", 0, len(ctx.plan.to_sync_rating),
                     message="Syncing ratings...")

        for i, item in enumerate(ctx.plan.to_sync_rating):
            if ctx.cancelled():
                return

            ctx.progress("sync_rating", i + 1, len(ctx.plan.to_sync_rating),
                         item, item.description)

            if ctx.dry_run:
                ctx.result.ratings_synced += 1
                continue

            db_track_id = item.db_track_id
            if db_track_id and db_track_id in ctx.tracks_by_db_track_id and item.new_rating is not None:
                ctx.tracks_by_db_track_id[db_track_id].rating = item.new_rating

            if ctx.write_back_to_pc and item.pc_track and item.new_rating is not None:
                self._write_rating_to_pc(item.pc_track.path, item.new_rating)
            logger.debug("Rating sync: %s → %s", item.description, item.new_rating)
            ctx.result.ratings_synced += 1

    # ── File Operations ─────────────────────────────────────────────────────

    def _get_next_media_folder(self) -> Path:
        """Get next media folder (F00-Fxx) using round-robin. Thread-safe.

        The number of Fxx directories varies by device (3-50); defaults to
        20 (most common value) if device capabilities are unknown.
        """
        # Determine music_dirs from device capabilities
        music_dirs = _DEFAULT_MUSIC_DIRS
        try:
            from iopenpod.device import (
                capabilities_for_family_gen,
                get_current_device_for_path,
            )
            dev = get_current_device_for_path(self.ipod_path)
            if dev and dev.model_family:
                caps = capabilities_for_family_gen(
                    dev.model_family, dev.generation or "",
                )
                if caps:
                    music_dirs = caps.music_dirs
        except Exception:
            pass

        with self._folder_lock:
            folder_name = f"F{self._folder_counter:02d}"
            self._folder_counter = (self._folder_counter + 1) % music_dirs
        return self.music_dir / folder_name

    def _generate_ipod_filename(self, _original_name: str, extension: str,
                                dest_folder: Path | None = None) -> str:
        """Generate a unique filename for iPod storage.

        Uses 4 random alphanumeric chars (36^4 = 1.7M combinations).
        If dest_folder is provided, checks for existence and retries.
        """
        import random
        import string

        chars = string.ascii_uppercase + string.digits
        for _ in range(50):  # max attempts
            random_name = "".join(random.choices(chars, k=4))
            filename = f"{random_name}{extension}"
            if dest_folder is None or _strict_device_path_stat(
                dest_folder / filename,
                action="choosing a media filename",
            ) is None:
                return filename
        # Fallback — extremely unlikely with collision check + 50 retries
        return f"{''.join(random.choices(chars, k=8))}{extension}"

    def _get_target_format(self, source_path: Path) -> str:
        """Determine the target format for transcoding."""
        return resolve_transcode_plan(
            source_path,
            options=self.transcode_options,
        ).cache_target_format

    def _copy_to_ipod(
        self,
        source_path: Path,
        transcode_plan: TranscodePlan,
        fingerprint: str | None = None,
        transcode_progress: Callable[[float], None] | None = None,
        copy_progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        expected_write_bytes: int | None = None,
        source_identity: _SourceIdentitySnapshot | None = None,
        sync_until_full: bool = False,
    ) -> tuple[bool, Path | None, bool, str]:
        """
        Copy or transcode a file to iPod, using cache when possible.

        Args:
            transcode_progress: Optional callback receiving 0.0-1.0 fraction
                for transcode progress (forwarded to ffmpeg).
            copy_progress: Optional callback receiving 0.0-1.0 fraction
                for direct file copy progress.

        Returns: (success, ipod_path, was_transcoded, error_message)
        """
        dest_folder = self._get_next_media_folder()
        source_size = source_path.stat().st_size
        write_size = expected_write_bytes if expected_write_bytes and expected_write_bytes > 0 else source_size
        reserve_bytes = (
            _SYNC_UNTIL_FULL_RESERVE_BYTES
            if sync_until_full
            else _DISK_RESERVE_BYTES
        )

        # Ordinary syncs keep the estimate-based precheck for quick feedback.
        # Sync-until-full waits for the real staged/transcoded payload size.
        if not sync_until_full:
            self._ensure_device_has_space_for_write(write_size, reserve_bytes)

        needs_transcode = transcode_plan.target != TranscodeTarget.COPY
        if needs_transcode:
            plan = transcode_plan
            target_format = plan.cache_target_format
            bitrate = plan.cache_bitrate_kbps
            cache_source_hash = None
            cache_source_mtime = 0.0
            if fingerprint:
                if source_identity is not None:
                    _source_size, cache_source_mtime, cache_source_hash = source_identity
                else:
                    cache_source_hash, cache_source_mtime = (
                        self.transcode_cache.describe_source(source_path)
                    )

            # Check transcode cache
            if fingerprint:
                cached_path = self.transcode_cache.get(
                    fingerprint,
                    target_format,
                    source_size,
                    bitrate,
                    source_path=source_path,
                    source_hash=cache_source_hash,
                    source_mtime=cache_source_mtime,
                )
                if cached_path:
                    ext = cached_path.suffix
                    new_name = self._generate_ipod_filename(source_path.stem, ext, dest_folder)
                    final_path = dest_folder / new_name
                    try:
                        self._copy_stripped_file_to_device(
                            cached_path, final_path,
                            copy_progress,
                            is_cancelled=is_cancelled,
                            reserve_bytes=reserve_bytes,
                            serialize_space_check=sync_until_full,
                        )
                        logger.info("Used cached transcode: %s", source_path.name)
                        return True, final_path, True, ""
                    except _OutOfSpaceError:
                        raise
                    except DeviceWriteSafetyError:
                        raise
                    except Exception as e:
                        logger.warning("Cache copy failed, will transcode: %s", e)

            # Transcode directly into the cache directory so ffmpeg writes
            # to local disk at full speed (8 workers truly parallel) and we
            # avoid a redundant copy.  Only the USB copy to iPod remains.
            if fingerprint:
                cache_path = self.transcode_cache.reserve(
                    fingerprint,
                    target_format,
                    bitrate,
                    source_hash=cache_source_hash,
                )
                output_dir = cache_path.parent
                output_filename = cache_path.stem
            else:
                import tempfile
                output_dir = Path(tempfile.mkdtemp())
                output_filename = None

            result = transcode(
                source_path, output_dir,
                output_filename=output_filename,
                progress_callback=transcode_progress,
                options=self.transcode_options,
                plan=plan,
                is_cancelled=is_cancelled,
            )
            if result.success and result.output_path:
                # Register in cache index (file already in place)
                if fingerprint:
                    self.transcode_cache.commit(
                        fingerprint=fingerprint,
                        source_format=source_path.suffix.lstrip("."),
                        target_format=target_format,
                        source_size=source_size,
                        bitrate=bitrate,
                        source_path=source_path,
                        source_hash=cache_source_hash,
                        source_mtime=cache_source_mtime,
                    )

                # Copy to iPod (the actual bottleneck — USB I/O)
                new_name = self._generate_ipod_filename(
                    source_path.stem, result.output_path.suffix, dest_folder,
                )
                final_path = dest_folder / new_name
                self._copy_stripped_file_to_device(
                    result.output_path,
                    final_path,
                    copy_progress,
                    is_cancelled=is_cancelled,
                    reserve_bytes=reserve_bytes,
                    serialize_space_check=sync_until_full,
                )

                # Clean up temp dir for non-fingerprinted tracks
                if not fingerprint:
                    try:
                        result.output_path.unlink(missing_ok=True)
                        output_dir.rmdir()
                    except Exception:
                        pass

                return True, final_path, True, ""
            else:
                logger.error("Transcode failed: %s", result.error_message)
                return False, None, True, result.error_message or "Transcode failed"
        else:
            # Direct copy — chunked to report progress over USB.
            # Uses raw open/read/write to avoid macOS xattr/ACL issues
            # when writing to FAT32-formatted iPods.
            new_name = self._generate_ipod_filename(source_path.stem, source_path.suffix, dest_folder)
            dest_path = dest_folder / new_name
            try:
                self._copy_stripped_file_to_device(
                    source_path,
                    dest_path,
                    copy_progress,
                    is_cancelled=is_cancelled,
                    reserve_bytes=reserve_bytes,
                    serialize_space_check=sync_until_full,
                )
                return True, dest_path, False, ""
            except _OutOfSpaceError:
                raise
            except DeviceWriteSafetyError:
                raise
            except Exception as e:
                logger.error("Copy failed: %s", e)
                return False, None, False, str(e)

    def _copy_stripped_file_to_device(
        self,
        src: Path,
        dst: Path,
        progress: Callable[[float], None] | None = None,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        reserve_bytes: int = _DISK_RESERVE_BYTES,
        serialize_space_check: bool = False,
    ) -> None:
        """Copy a metadata-stripped temporary payload to the iPod."""
        with tempfile.TemporaryDirectory(prefix="iopenpod_stripped_") as tmp:
            staged = Path(tmp) / src.name
            shutil.copyfile(src, staged)
            before_size = staged.stat().st_size
            if strip_metadata(staged):
                after_size = staged.stat().st_size
                self._record_metadata_strip(before_size - after_size)
            else:
                self._record_metadata_strip_failure(src.suffix.lower())
            self._copy_file_to_device(
                staged,
                dst,
                progress,
                is_cancelled=is_cancelled,
                reserve_bytes=reserve_bytes,
                serialize_space_check=serialize_space_check,
            )

    def _copy_file_to_device(
        self,
        src: Path,
        dst: Path,
        progress: Callable[[float], None] | None = None,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        reserve_bytes: int = _DISK_RESERVE_BYTES,
        serialize_space_check: bool = False,
    ) -> None:
        if serialize_space_check:
            with self._space_guard_lock:
                self._copy_file_to_device_guarded(
                    src,
                    dst,
                    progress,
                    is_cancelled=is_cancelled,
                    reserve_bytes=reserve_bytes,
                )
            return

        self._copy_file_to_device_guarded(
            src,
            dst,
            progress,
            is_cancelled=is_cancelled,
            reserve_bytes=reserve_bytes,
        )

    def _copy_file_to_device_guarded(
        self,
        src: Path,
        dst: Path,
        progress: Callable[[float], None] | None = None,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        reserve_bytes: int = _DISK_RESERVE_BYTES,
    ) -> None:
        with self._device_write_semaphore:
            self._revalidate_device_write_readiness()
            dst.parent.mkdir(parents=True, exist_ok=True)
            source_size = src.stat().st_size
            require_file_size_supported(
                source_size,
                max_file_size_bytes=self._effective_max_file_size_bytes(),
                display_name=src.name,
            )
            self._ensure_device_has_space_for_write(source_size, reserve_bytes)
            try:
                self._copy_file_chunked(
                    src,
                    dst,
                    progress,
                    is_cancelled=is_cancelled,
                )
            except Exception:
                self._revalidate_device_write_readiness()
                durable_unlink(dst, missing_ok=True)
                raise

    def _ensure_device_has_space_for_write(
        self,
        write_size: int,
        reserve_bytes: int,
    ) -> None:
        """Raise when writing bytes would leave less than reserve on the iPod."""

        try:
            free = shutil.disk_usage(self.ipod_path).free
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"Could not verify iPod free space before writing a file: {exc}"
            ) from exc

        allocation_unit = getattr(
            self._filesystem_profile,
            "allocation_unit_size",
            None,
        )
        allocated_write = allocated_size(write_size, allocation_unit)
        if free - allocated_write >= max(0, int(reserve_bytes or 0)):
            return

        free_mb = free / (1024 * 1024)
        write_mb = allocated_write / (1024 * 1024)
        reserve_mb = max(0, int(reserve_bytes or 0)) / (1024 * 1024)
        raise _OutOfSpaceError(
            f"iPod is out of space ({free_mb:.1f} MB remaining, "
            f"{write_mb:.1f} MB to write, {reserve_mb:.0f} MB reserve required). "
            "Stopping file writes."
        )

    @staticmethod
    def _copy_file_chunked(
        src: Path, dst: Path,
        progress: Callable[[float], None] | None = None,
        chunk_size: int = 256 * 1024,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        """Copy *src* to *dst* in chunks, calling *progress(0.0‒1.0)* periodically."""
        total = src.stat().st_size
        copied = 0
        try:
            with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                while True:
                    if is_cancelled and is_cancelled():
                        raise _CancelledError()
                    buf = fsrc.read(chunk_size)
                    if not buf:
                        break
                    fdst.write(buf)
                    copied += len(buf)
                    if progress and total:
                        progress(copied / total)
                flush_written_file(fdst)
            flush_parent_directory(dst)
            # Final callback in case total was 0 (empty file)
            if progress:
                progress(1.0)
        except Exception as e:
            if isinstance(e, OSError) and e.errno == errno.ENOSPC:
                raise _OutOfSpaceError("No space left on iPod while writing file") from e
            raise

    def _delete_from_ipod(self, ipod_path: str | Path) -> bool:
        """Delete a file from iPod."""
        try:
            with self._device_write_semaphore:
                self._revalidate_device_write_readiness()
                path = Path(ipod_path)
                try:
                    path.stat()
                except FileNotFoundError:
                    return True
                except OSError as exc:
                    raise DeviceWriteSafetyError(
                        f"Could not safely inspect the iPod file before deletion: {exc}"
                    ) from exc
                durable_unlink(path)
                logger.debug("Deleted: %s", path)
            return True
        except DeviceWriteSafetyError:
            raise
        except Exception as e:
            logger.error("Delete failed for %s: %s", ipod_path, e)
            return False

    def _effective_max_file_size_bytes(self) -> int | None:
        filesystem_limit = getattr(
            self._filesystem_profile,
            "max_file_size_bytes",
            None,
        )
        device_limit = getattr(
            self.device_storage,
            "device_max_file_size_bytes",
            None,
        )
        return effective_max_file_size_bytes(filesystem_limit, device_limit)

    def _revalidate_device_write_readiness(self) -> None:
        profile = self._filesystem_profile
        if profile is None:
            return
        self._filesystem_profile = revalidate_device_write_readiness(profile)

    # ── PC Write-Back ───────────────────────────────────────────────────────

    def _write_rating_to_pc(self, file_path: str, rating: int) -> bool:
        """Write rating (0-100) to PC file metadata using mutagen.

        For MP3: uses POPM (Popularimeter) frame (0-255 scale).
        For M4A: uses freeform atom (0-100 scale, same as iPod).
            NOTE: 'rtng' is the Content Advisory atom (0=none, 1=explicit,
            2=clean) and must NOT be used for star ratings.
        For FLAC/OGG: uses RATING vorbis comment.
        """
        try:
            import mutagen  # type: ignore[import-untyped]

            ext = Path(file_path).suffix.lower()
            audio = mutagen.File(file_path)  # type: ignore[attr-defined]
            if audio is None:
                return False

            if ext == ".mp3":
                from mutagen.id3._frames import POPM  # type: ignore[import-untyped]
                # Convert 0-100 to 0-255 POPM scale
                stars = min(5, rating // 20) if rating > 0 else 0
                popm_map = {0: 0, 1: 1, 2: 64, 3: 128, 4: 196, 5: 255}
                popm_rating = popm_map.get(stars, 0)
                # Preserve existing play count stored in POPM frame
                existing_count = 0
                popm_key = "POPM:iOpenPod"
                if popm_key in audio.tags:
                    existing_count = audio.tags[popm_key].count
                audio.tags.add(POPM(email="iOpenPod", rating=popm_rating, count=existing_count))
                audio.save()
            elif ext in (".m4a", ".m4p", ".aac"):
                from mutagen.mp4 import MP4FreeForm  # type: ignore[import-untyped]
                # Freeform atom for star rating (0-100)
                key = "----:com.apple.iTunes:RATING"
                audio.tags[key] = [MP4FreeForm(str(rating).encode())]
                audio.save()
            elif ext in (".flac", ".ogg", ".opus"):
                # RATING vorbis comment (store as 0-100)
                audio.tags["RATING"] = [str(rating)]
                audio.save()

            return True
        except Exception as e:
            logger.warning("Could not write rating to %s: %s", file_path, e)
            return False

    # ── Play Counts cleanup ─────────────────────────────────────────────────

    def _delete_playcounts_file(self) -> None:
        """Delete Play Counts (and related) files after a successful sync.

        The iPod firmware creates these files to record play/skip/rating
        deltas since the last sync.  After merging the deltas into the new
        iTunesDB and writing it, these files must be removed so the iPod
        creates fresh ones.

        Matches libgpod's ``playcounts_reset()`` which deletes:
        - ``Play Counts``
        - ``iTunesStats``
        - ``PlayCounts.plist``
        - ``OTGPlaylistInfo`` (On-The-Go playlists created on device)
        """
        from ._db_io import delete_playcounts_files

        delete_playcounts_files(
            self.ipod_path,
            before_device_mutation=self._revalidate_device_write_readiness,
        )

    # ── Track Conversion ────────────────────────────────────────────────────

    def _read_existing_database(self) -> dict:
        """Read existing tracks, playlists, and smart playlists from iTunesDB."""
        from ._db_io import read_existing_database
        return read_existing_database(self.ipod_path)

    def _track_dict_to_info(self, t: dict) -> TrackInfo:
        """Convert parsed track dict to TrackInfo for writing."""
        from ._track_conversion import track_dict_to_info
        return track_dict_to_info(t)

    def _pc_track_to_info(self, pc_track, ipod_location: str, was_transcoded: bool,
                          ipod_file_path: Path | None = None) -> TrackInfo:
        """Convert PCTrack to TrackInfo for writing."""
        from ._track_conversion import pc_track_to_info
        return pc_track_to_info(
            pc_track, ipod_location, was_transcoded,
            ipod_file_path=ipod_file_path,
            transcode_options=self.transcode_options if was_transcoded else None,
        )

    @staticmethod
    def _decode_raw_blob(value) -> bytes | None:
        """Decode a raw MHOD blob from parsed playlist data."""
        from ._playlist_builder import decode_raw_blob
        return decode_raw_blob(value)

    def _build_and_evaluate_playlists(
        self,
        ctx: _SyncContext,
        all_track_infos: list[TrackInfo],
    ) -> tuple[
        str,
        int | None,
        list[PlaylistInfo],
        str,
        int | None,
        list[PlaylistInfo],
        list[PlaylistInfo],
    ]:
        """Build PlaylistInfo lists and evaluate smart playlist rules."""
        from ._playlist_builder import build_and_evaluate_playlists

        source_path_to_db_track_id = {
            self._source_path_key(track.source_path): track.db_track_id
            for track in all_track_infos
            if track.source_path and track.db_track_id
        }
        matched_pc_paths = {
            **dict(getattr(ctx.plan, "matched_pc_paths", {}) or {}),
            **ctx.pc_file_paths,
        }
        for db_track_id, pc_path in matched_pc_paths.items():
            try:
                normalized_id = int(db_track_id)
            except (TypeError, ValueError):
                continue
            if normalized_id and pc_path:
                source_path_to_db_track_id.setdefault(
                    self._source_path_key(str(pc_path)),
                    normalized_id,
                )
        return build_and_evaluate_playlists(
            ctx.existing_tracks_data,
            ctx.existing_dataset2_standard_playlists_raw,
            ctx.existing_dataset3_podcast_playlists_raw,
            ctx.existing_dataset5_smart_playlists_raw,
            all_track_infos,
            source_path_to_db_track_id,
        )

    @staticmethod
    def _trackinfo_to_eval_dict(t: TrackInfo) -> dict:
        """Convert a TrackInfo to a dict the SPL evaluator can consume."""
        from ._track_conversion import trackinfo_to_eval_dict
        return trackinfo_to_eval_dict(t)
