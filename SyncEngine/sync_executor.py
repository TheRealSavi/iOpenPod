"""
Sync Executor - Executes a sync plan to synchronize PC library with iPod.

The executor takes a SyncPlan (from FingerprintDiffEngine) and:
1. Copies/transcodes new tracks to iPod
2. Removes deleted tracks from iPod
3. Updates metadata for changed tracks
4. Re-copies files that changed on PC
5. Records play counts from iPod, scrobbles to ListenBrainz
6. Builds a final list[TrackInfo] and calls write_itunesdb() ONCE

The database is always fully rewritten (not patched incrementally).
"""

import errno
import logging
import os
import shutil
import tempfile
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field
from .fingerprint_diff_engine import SyncPlan, SyncItem
from .mapping import MappingManager, MappingFile
from .transcoder import transcode, needs_transcoding, clear_caches as _clear_transcoder_caches
from .audio_fingerprint import get_or_compute_fingerprint
from .itunes_prefs import protect_from_itunes

from iTunesDB_Writer.mhit_writer import TrackInfo
from iTunesDB_Shared.constants import (
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VIDEO_PODCAST,
)
from iTunesDB_Writer.mhyp_writer import PlaylistInfo

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

# Minimum free space (bytes) that must remain on the iPod after each file copy.
_DISK_RESERVE_BYTES = 30 * 1024 * 1024   # 30 MB

# Estimated overhead for the database files themselves.
_DB_OVERHEAD_BYTES = 10 * 1024 * 1024    # 10 MB

# Default number of Fxx music directories (most common across iPod models).
_DEFAULT_MUSIC_DIRS = 20


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


@dataclass
class SyncProgress:
    """Progress info for sync callbacks."""

    stage: str  # "add", "remove", "update_metadata", "update_file", etc.
    current: int
    total: int
    current_item: Optional[SyncItem] = None
    message: str = ""
    # Per-worker status lines (for parallel copy/transcode stages)
    worker_lines: Optional[list[str]] = None
    # Size-weighted progress fraction (0.0–1.0), None when not applicable
    size_progress: Optional[float] = None


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    tracks_added: int = 0
    tracks_removed: int = 0
    tracks_updated_metadata: int = 0
    tracks_updated_file: int = 0
    playcounts_synced: int = 0
    ratings_synced: int = 0
    sound_check_computed: int = 0
    scrobbles_submitted: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def summary(self) -> str:
        lines = []
        if self.tracks_added:
            lines.append(f"  Added {self.tracks_added} tracks")
        if self.tracks_removed:
            lines.append(f"  Removed {self.tracks_removed} tracks")
        if self.tracks_updated_metadata:
            lines.append(f"  Updated metadata for {self.tracks_updated_metadata} tracks")
        if self.tracks_updated_file:
            lines.append(f"  Re-synced {self.tracks_updated_file} tracks")
        if self.playcounts_synced:
            lines.append(f"  Synced play counts for {self.playcounts_synced} tracks")
        if self.ratings_synced:
            lines.append(f"  Synced ratings for {self.ratings_synced} tracks")
        if self.sound_check_computed:
            lines.append(f"  Computed Sound Check for {self.sound_check_computed} tracks")
        if self.scrobbles_submitted:
            lines.append(f"  Scrobbled {self.scrobbles_submitted} plays")
        if self.errors:
            lines.append(f"  {len(self.errors)} errors occurred")

        if not lines:
            return "No changes made."

        status = "Sync completed" if self.success else "Sync completed with errors"
        return f"{status}:\n" + "\n".join(lines)


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
    progress_callback: Optional[Callable[["SyncProgress"], None]]
    dry_run: bool
    aac_quality: str
    write_back_to_pc: bool
    _is_cancelled: Optional[Callable[[], bool]]

    # ── GUI-decoupled inputs (passed forward, not pulled from GUI) ──
    user_playlists: list[dict] = field(default_factory=list)
    on_sync_complete: Optional[Callable[[], None]] = None
    compute_sound_check: bool = False
    scrobble_on_sync: bool = False
    listenbrainz_token: str = ""

    # ── Result accumulator ──────────────────────────────────────────
    result: SyncResult = field(default_factory=lambda: SyncResult(success=True))

    # ── Existing iPod database (populated by _load_existing_database) ──
    existing_tracks_data: list[dict] = field(default_factory=list)
    existing_playlists_raw: list[dict] = field(default_factory=list)
    existing_smart_raw: list[dict] = field(default_factory=list)

    # ── Track state (mutated by stage methods) ──────────────────────
    tracks_by_db_id: dict[int, TrackInfo] = field(default_factory=dict)
    tracks_by_location: dict[str, TrackInfo] = field(default_factory=dict)
    new_tracks: list[TrackInfo] = field(default_factory=list)

    # ── Fingerprint/source tracking for new-track backpatch ─────────
    new_track_fingerprints: dict[int, str] = field(default_factory=dict)
    new_track_info: dict[int, tuple] = field(default_factory=dict)
    pc_file_paths: dict[int, str] = field(default_factory=dict)

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

    def progress(self, stage: str, current: int, total: int,
                 current_item: Optional["SyncItem"] = None,
                 message: str = "", **kwargs) -> None:
        """Send a progress update (no-op when no callback is set)."""
        if self.progress_callback:
            self.progress_callback(
                SyncProgress(stage, current, total, current_item, message, **kwargs)
            )


class SyncExecutor:
    """
    Executes a sync plan to synchronize PC library with iPod.

    Features:
    - Transcode cache: Avoids re-transcoding for multiple iPods
    - Round-robin file distribution across F00-F49 folders
    - Full database rewrite: builds final list[TrackInfo], writes once

    Usage:
        executor = SyncExecutor(ipod_path)
        result = executor.execute(plan, mapping, progress_callback)
    """

    def __init__(self, ipod_path: str | Path, cache_dir: Optional[Path] = None,
                 max_workers: int = 0):
        from .transcode_cache import TranscodeCache

        self.ipod_path = Path(ipod_path)
        self.music_dir = self.ipod_path / "iPod_Control" / "Music"
        self.mapping_manager = MappingManager(ipod_path)
        self.transcode_cache = TranscodeCache.get_instance(cache_dir)

        self._folder_counter = 0
        self._folder_lock = threading.Lock()

        # 0 = auto (CPU count, capped at 8), 1 = sequential
        if max_workers <= 0:
            self._max_workers = min(os.cpu_count() or 4, 8)
        else:
            self._max_workers = max_workers

    # ── Public API ──────────────────────────────────────────────────────────

    def execute(
        self,
        plan: SyncPlan,
        mapping: MappingFile,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
        dry_run: bool = False,
        is_cancelled: Optional[Callable[[], bool]] = None,
        write_back_to_pc: bool = False,
        aac_quality: str = "normal",
        *,
        user_playlists: Optional[list[dict]] = None,
        on_sync_complete: Optional[Callable[[], None]] = None,
        compute_sound_check: bool = False,
        scrobble_on_sync: bool = False,
        listenbrainz_token: str = "",
    ) -> SyncResult:
        """Execute the sync plan.

        Flow:
        1. Pre-flight checks (storage, writability)
        2. Load existing iPod database
        3. Run stages 1-6 (remove → file update → metadata → artwork →
           add → sound check → play counts → ratings)
        4. Write database in one shot (stage 7)
        """
        self._aac_quality = aac_quality
        _clear_transcoder_caches()

        ctx = _SyncContext(
            plan=plan,
            mapping=mapping,
            progress_callback=progress_callback,
            dry_run=dry_run,
            aac_quality=aac_quality,
            write_back_to_pc=write_back_to_pc,
            _is_cancelled=is_cancelled,
            user_playlists=list(user_playlists) if user_playlists else [],
            on_sync_complete=on_sync_complete,
            compute_sound_check=compute_sound_check,
            scrobble_on_sync=scrobble_on_sync,
            listenbrainz_token=listenbrainz_token,
        )

        if not self._preflight_checks(ctx):
            return ctx.result

        ctx.progress(
            "load_database", 0, 1,
            message="Reading iTunesDB and playlists from iPod…",
        )
        self._load_existing_database_into(ctx)
        ctx.progress(
            "load_database", 1, 1,
            message=(
                f"Loaded {len(ctx.existing_tracks_data)} tracks, "
                f"{len(ctx.existing_playlists_raw)} playlists"
            ),
        )

        # Run stages 1-6; bail on first failure.
        stages = [
            self._execute_removes,          # Stage 1
            self._execute_file_updates,     # Stage 2
            self._execute_metadata_updates,  # Stage 3
            self._execute_artwork_updates,  # Stage 3b
            self._download_podcast_episodes,  # Stage 3c (podcast prep)
            self._execute_adds,             # Stage 4
            self._execute_sound_check,      # Stage 4b
            self._execute_playcount_sync,   # Stage 5
            self._execute_rating_sync,      # Stage 6
        ]
        for stage in stages:
            if ctx.cancelled():
                return ctx.result
            stage(ctx)
            if not ctx.result.success:
                return ctx.result

        # Stage 7: write database (one shot)
        if ctx.cancelled():
            return ctx.result
        if not ctx.dry_run:
            self._execute_write_and_finalize(ctx)

        ctx.result.success = not ctx.result.has_errors
        return ctx.result

    def quick_write_playlists(
        self,
        user_playlists: list[dict],
        progress_callback: Optional[Callable[["SyncProgress"], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> SyncResult:
        """Rewrite the iPod database with only playlist changes (no file ops).

        Reads the existing database, merges *user_playlists* into the existing
        playlist lists, rebuilds every track as-is, and writes the DB in one
        shot.  Much faster than a full sync because no fingerprinting,
        transcoding, or file copying is involved.
        """
        result = SyncResult(success=True)

        def _progress(stage, cur, total, message=""):
            if progress_callback:
                progress_callback(SyncProgress(stage, cur, total, message=message))

        _progress("playlist_sync", 0, 3, "Reading iPod database…")

        # 1. Read existing DB
        existing_db = self._read_existing_database()
        tracks_data = existing_db["tracks"]
        playlists_raw = existing_db["playlists"]
        smart_raw = existing_db["smart_playlists"]

        if not tracks_data:
            result.success = False
            result.errors.append(("playlist_sync", "No existing database found on iPod"))
            return result

        # 2. Convert existing tracks to TrackInfo (unchanged)
        all_tracks: list[TrackInfo] = []
        for t in tracks_data:
            ti = self._track_dict_to_info(t)
            if ti.db_id:
                all_tracks.append(ti)

        _progress("playlist_sync", 1, 3, "Merging playlists…")

        # 3. Merge user playlists into existing raw lists
        for upl in user_playlists:
            if upl.get("master_flag"):
                continue
            pid = upl.get("playlist_id", 0)
            is_new = upl.get("_isNew", False)
            if is_new:
                playlists_raw.append(upl)
            else:
                replaced = False
                for i, epl in enumerate(playlists_raw):
                    if epl.get("playlist_id") == pid:
                        playlists_raw[i] = upl
                        replaced = True
                        break
                if not replaced:
                    for i, epl in enumerate(smart_raw):
                        if epl.get("playlist_id") == pid:
                            smart_raw[i] = upl
                            replaced = True
                            break
                if not replaced:
                    playlists_raw.append(upl)

        # 4. Build PlaylistInfo objects
        from ._playlist_builder import build_and_evaluate_playlists
        master_name, playlists, smart_playlists = build_and_evaluate_playlists(
            tracks_data, playlists_raw, smart_raw, all_tracks, user_playlists,
        )

        _progress("playlist_sync", 2, 3, "Writing database…")

        # 5. Write DB (no artwork pc_file_paths needed — tracks unchanged)
        db_ok = self._write_database(
            all_tracks,
            playlists=playlists,
            smart_playlists=smart_playlists,
            master_playlist_name=master_name,
        )

        if not db_ok:
            result.success = False
            result.errors.append(("playlist_sync", "Database write failed"))
            return result

        # 6. iTunes protection + cleanup
        try:
            self._apply_itunes_protections_from_tracks(all_tracks)
        except Exception as e:
            logger.warning("iTunesPrefs protection failed (non-fatal): %s", e)

        if on_complete:
            try:
                on_complete()
            except Exception:
                pass

        _progress("playlist_sync", 3, 3, "Playlists synced")
        result.success = True
        return result

    def _apply_itunes_protections_from_tracks(self, all_tracks: list[TrackInfo]) -> None:
        """Lightweight iTunesPrefs update from a track list (no _SyncContext)."""
        from .itunes_prefs import protect_from_itunes

        _MEDIA_BUCKETS = [
            (0x04, "podcast"), (0x08, "audiobook"), (0x40, "tv"),
            (0x20, "mv"), (0x02, "video"),
        ]
        totals: dict[str, list[int]] = {
            k: [0, 0, 0] for k in ("music", "video", "podcast", "audiobook", "tv", "mv")
        }
        for t in all_tracks:
            mt = t.media_type
            bucket = "music"
            for mask, label in _MEDIA_BUCKETS:
                if mt & mask:
                    bucket = label
                    break
            totals[bucket][0] += t.size
            totals[bucket][1] += t.length // 1000
            totals[bucket][2] += 1

        protect_from_itunes(
            self.ipod_path,
            track_count=totals["music"][2],
            total_music_bytes=totals["music"][0],
            total_music_seconds=totals["music"][1],
            video_tracks=totals["video"][2],
            video_bytes=totals["video"][0],
            video_seconds=totals["video"][1],
            podcast_tracks=totals["podcast"][2],
            podcast_bytes=totals["podcast"][0],
            podcast_seconds=totals["podcast"][1],
            audiobook_tracks=totals["audiobook"][2],
            audiobook_bytes=totals["audiobook"][0],
            audiobook_seconds=totals["audiobook"][1],
            tv_show_tracks=totals["tv"][2],
            tv_show_bytes=totals["tv"][0],
            tv_show_seconds=totals["tv"][1],
            music_video_tracks=totals["mv"][2],
            music_video_bytes=totals["mv"][0],
            music_video_seconds=totals["mv"][1],
        )

    # ── Pre-flight & Loading ────────────────────────────────────────────────

    def _preflight_checks(self, ctx: _SyncContext) -> bool:
        """Return False (and populate ctx.result) if sync cannot proceed."""
        if not ctx.dry_run and ctx.plan.storage.bytes_to_add > 0:
            try:
                disk = shutil.disk_usage(self.ipod_path)
                needed = (ctx.plan.storage.bytes_to_add
                          - ctx.plan.storage.bytes_to_remove
                          + _DB_OVERHEAD_BYTES)
                if needed > 0 and disk.free < needed:
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
                logger.warning("Could not check disk space: %s", e)

        # On Linux the iPod may be auto-mounted read-only (dirty VFAT,
        # missing write permissions).  Detect early for a clear error.
        if not ctx.dry_run:
            probe_dir = self.ipod_path / "iPod_Control" / "iTunes"
            try:
                fd, probe_path = tempfile.mkstemp(
                    prefix=".iOpenPod_write_test_", dir=str(probe_dir),
                )
                os.close(fd)
                os.unlink(probe_path)
            except OSError as e:
                if e.errno in (errno.EROFS, errno.EACCES):
                    hint = (
                        "The iPod filesystem is mounted read-only. "
                        "On Linux, try remounting with write access:\n"
                        "  sudo mount -o remount,rw /media/…/iPod\n"
                        "If the filesystem is dirty, run:\n"
                        "  sudo fsck.vfat -a /dev/sdXN\n"
                        "then re-mount."
                    )
                    logger.error("iPod is read-only: %s", e)
                    ctx.result.errors.append(("read-only", hint))
                    ctx.result.success = False
                    return False
                else:
                    logger.warning("Writability probe failed (non-fatal): %s", e)

        return True

    def _load_existing_database_into(self, ctx: _SyncContext) -> None:
        """Parse existing iPod database and populate ctx track/playlist state."""
        existing_db = self._read_existing_database()
        ctx.existing_tracks_data = existing_db["tracks"]
        ctx.existing_playlists_raw = existing_db["playlists"]
        ctx.existing_smart_raw = existing_db["smart_playlists"]

        for t in ctx.existing_tracks_data:
            track_info = self._track_dict_to_info(t)
            if track_info.db_id:
                ctx.tracks_by_db_id[track_info.db_id] = track_info
            if track_info.location:
                ctx.tracks_by_location[track_info.location] = track_info

        ctx.pc_file_paths = dict(ctx.plan.matched_pc_paths)
        logger.debug("ART: starting with %d matched PC paths from sync plan",
                     len(ctx.pc_file_paths))

    def _execute_write_and_finalize(self, ctx: _SyncContext) -> None:
        """Stage 7: assemble final track list, write database, backpatch and finalize."""
        # Define sub-steps so the progress bar advances smoothly through
        # the database-write phase instead of jumping from 0% to 100%.
        # Steps: prepare tracks → build playlists → prepare db → write artwork
        #        → build db structure → sign db → write to iPod (+ SQLite)
        _TOTAL_STEPS = 8
        _step = 0

        def _advance(msg: str) -> None:
            nonlocal _step
            ctx.progress("write_database", _step, _TOTAL_STEPS, message=msg)
            _step += 1

        _advance("Preparing tracks")

        all_tracks = list(ctx.tracks_by_db_id.values()) + ctx.new_tracks

        # ── Pre-assign db_ids for new tracks ──────────────────────
        # New tracks arrive with db_id=0.  Assign now so
        # _build_and_evaluate_playlists can build correct track lists.
        from iTunesDB_Writer.mhit_writer import generate_db_id
        for t in all_tracks:
            if not t.db_id:
                t.db_id = generate_db_id()

        # ── Auto-detect gapless_album_flag ────────────────────────
        albums: dict[tuple[str, str], list[TrackInfo]] = defaultdict(list)
        for t in all_tracks:
            key = (t.album or "", t.album_artist or t.artist or "")
            albums[key].append(t)
        for album_tracks in albums.values():
            if len(album_tracks) >= 2 and all(
                t.gapless_track_flag for t in album_tracks
            ):
                for t in album_tracks:
                    t.gapless_album_flag = 1

        logger.debug("ART: pc_file_paths total=%d, all_tracks=%d",
                     len(ctx.pc_file_paths), len(all_tracks))

        # ── Merge user-created playlists ──────────────────────────
        self._merge_gui_playlists(ctx)

        # ── Build playlists and evaluate smart playlists ──────────
        _advance("Building playlists")
        master_playlist_name, playlists, smart_playlists = (
            self._build_and_evaluate_playlists(ctx, all_tracks)
        )

        try:
            # The inner writer calls our callback to advance the bar
            # through artwork → db structure → signing → writing.
            def _db_progress(msg: str) -> None:
                nonlocal _step
                ctx.progress("write_database", _step, _TOTAL_STEPS, message=msg)
                _step += 1

            db_ok = self._write_database(
                all_tracks, pc_file_paths=ctx.pc_file_paths,
                playlists=playlists, smart_playlists=smart_playlists,
                master_playlist_name=master_playlist_name,
                progress_callback=_db_progress,
            )
            if not db_ok:
                logger.error("Database write returned failure — skipping mapping save")
                ctx.progress("write_database", _TOTAL_STEPS, _TOTAL_STEPS,
                             message="Database write FAILED")
                ctx.result.success = False
                ctx.result.errors.append(("database", "Database write failed"))
                return
            ctx.progress("write_database", _TOTAL_STEPS, _TOTAL_STEPS,
                         message=f"Database written — {len(all_tracks)} tracks")

            # ── Backpatch: new tracks now have real db_ids ──
            self._backpatch_new_tracks(ctx)

            # Save mapping ONLY after successful DB write + backpatch.
            self.mapping_manager.save(ctx.mapping)

            # ── Update podcast subscription store ──────────────────
            self._update_podcast_subscriptions(ctx)

            self._clear_gui_cache(ctx)

            self._apply_itunes_protections(ctx, all_tracks)
            self._delete_playcounts_file()

            # Scrobble AFTER DB write + Play Counts deletion
            if ctx.plan.to_sync_playcount:
                self._execute_scrobble(ctx)

        except Exception as e:
            ctx.result.errors.append(("database write", str(e)))
            logger.error("Database write failed — mapping NOT saved to preserve consistency")

    def _merge_gui_playlists(self, ctx: _SyncContext) -> None:
        """Merge user-created playlists into ctx."""
        user_pls = ctx.user_playlists
        if not user_pls:
            return
        ctx.progress("playlists", 0, len(user_pls), message="Merging playlists...")
        for idx, upl in enumerate(user_pls):
            if upl.get("master_flag"):
                logger.debug("Skipping master playlist from user playlists (id=0x%X)",
                             upl.get("playlist_id", 0))
                continue
            is_new = upl.get("_isNew", False)
            pid = upl.get("playlist_id", 0)
            if is_new:
                ctx.existing_playlists_raw.append(upl)
            else:
                replaced = False
                for i, epl in enumerate(ctx.existing_playlists_raw):
                    if epl.get("playlist_id") == pid:
                        ctx.existing_playlists_raw[i] = upl
                        replaced = True
                        break
                if not replaced:
                    for i, epl in enumerate(ctx.existing_smart_raw):
                        if epl.get("playlist_id") == pid:
                            ctx.existing_smart_raw[i] = upl
                            replaced = True
                            break
                if not replaced:
                    ctx.existing_playlists_raw.append(upl)
            logger.info("Merged user playlist '%s' (id=0x%X, new=%s)",
                        upl.get("Title", "?"), pid, is_new)
            ctx.progress("playlists", idx + 1, len(user_pls),
                         message=f"Merged playlist: {upl.get('Title', '?')}")

    def _backpatch_new_tracks(self, ctx: _SyncContext) -> None:
        """Create mapping entries for newly added tracks (db_ids now assigned)."""
        for track in ctx.new_tracks:
            obj_key = id(track)
            fp = ctx.new_track_fingerprints.get(obj_key)
            info = ctx.new_track_info.get(obj_key)
            if fp and info and track.db_id != 0:
                pc_track, ipod_dest, was_transcoded = info
                # Re-stat the source file to capture post-fingerprint
                # size/mtime.  The fingerprinting phase may have written
                # the acoustic fingerprint tag back into the source file,
                # changing its size and mtime after the initial scan.
                source_size, source_mtime = _current_source_stat(pc_track)
                ctx.mapping.add_track(
                    fingerprint=fp,
                    db_id=track.db_id,
                    source_format=Path(pc_track.path).suffix.lstrip("."),
                    ipod_format=ipod_dest.suffix.lstrip("."),
                    source_size=source_size,
                    source_mtime=source_mtime,
                    was_transcoded=was_transcoded,
                    source_path_hint=pc_track.relative_path,
                    art_hash=pc_track.art_hash,
                )

    def _update_podcast_subscriptions(self, ctx: _SyncContext) -> None:
        """Mark added podcast episodes as on_ipod and removed ones as downloaded
        in the subscription store so the state persists across sessions."""
        try:
            from PodcastManager.subscription_store import SubscriptionStore
            from PodcastManager.models import STATUS_ON_IPOD, STATUS_DOWNLOADED
        except ImportError:
            return

        store = SubscriptionStore(str(self.ipod_path))
        feeds = store.get_feeds()
        if not feeds:
            return

        # Index episodes by enclosure URL across all feeds
        ep_by_url: dict[str, tuple] = {}
        for feed in feeds:
            for ep in feed.episodes:
                if ep.audio_url:
                    ep_by_url[ep.audio_url] = (ep, feed)

        changed = False

        # Mark added podcast episodes as on_ipod with their db_id
        for track in ctx.new_tracks:
            if not (track.media_type & 0x04):
                continue
            enc_url = track.podcast_enclosure_url or ""
            if not enc_url:
                continue
            entry = ep_by_url.get(enc_url)
            if entry:
                ep, _feed = entry
                ep.status = STATUS_ON_IPOD
                ep.ipod_db_id = track.db_id
                changed = True
                logger.debug("Podcast subscription: marked '%s' as on_ipod (db_id=%d)",
                             ep.title, track.db_id)

        # Mark removed podcast episodes as downloaded (no longer on iPod)
        all_removals = list(ctx.plan.to_remove) + list(
            getattr(ctx.plan, '_integrity_removals', [])
        )
        for item in all_removals:
            ipod_track = item.ipod_track
            if not ipod_track:
                continue
            if not (ipod_track.get("media_type", 0) & 0x04):
                continue
            enc_url = ipod_track.get("Podcast Enclosure URL", "")
            if not enc_url:
                continue
            entry = ep_by_url.get(enc_url)
            if entry:
                ep, _feed = entry
                ep.status = STATUS_DOWNLOADED if ep.downloaded_path else "not_downloaded"
                ep.ipod_db_id = 0
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

    def _execute_removes(self, ctx: _SyncContext) -> None:
        # Combine user-selected removals with mandatory integrity removals
        # (ghost tracks whose files are missing from iPod).
        all_removes = list(ctx.plan.to_remove)
        integrity_removals = getattr(ctx.plan, '_integrity_removals', [])
        if integrity_removals:
            # Deduplicate by db_id in case any overlap
            existing_db_ids = {item.db_id for item in all_removes if item.db_id}
            for item in integrity_removals:
                if item.db_id and item.db_id not in existing_db_ids:
                    all_removes.append(item)
                    existing_db_ids.add(item.db_id)

        if not all_removes:
            return

        ctx.progress("remove", 0, len(all_removes), message="Removing tracks...")

        for i, item in enumerate(all_removes):
            if ctx.cancelled():
                return

            ctx.progress("remove", i + 1, len(all_removes), item, item.description)

            if ctx.dry_run:
                ctx.result.tracks_removed += 1
                continue

            if item.ipod_track:
                file_path = item.ipod_track.get("Location") or item.ipod_track.get("location")
                if file_path:
                    relative_path = file_path.replace(":", "/").lstrip("/")
                    full_path = self.ipod_path / relative_path
                    self._delete_from_ipod(full_path)

                    if file_path in ctx.tracks_by_location:
                        track_to_remove = ctx.tracks_by_location.pop(file_path)
                        if track_to_remove.db_id in ctx.tracks_by_db_id:
                            del ctx.tracks_by_db_id[track_to_remove.db_id]

            if item.fingerprint:
                ctx.mapping.remove_track(item.fingerprint, db_id=item.db_id)
            elif item.db_id:
                ctx.mapping.remove_by_db_id(item.db_id)

            if item.db_id and item.db_id in ctx.tracks_by_db_id:
                del ctx.tracks_by_db_id[item.db_id]

            ctx.result.tracks_removed += 1

        for fp, db_id in getattr(ctx.plan, '_stale_mapping_entries', []):
            ctx.mapping.remove_track(fp, db_id=db_id)

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
        items_to_process = [(i, item) for i, item in enumerate(items) if item.pc_track is not None]
        if not items_to_process:
            return

        completed_count = 0
        completed_lock = threading.Lock()
        worker_fractions: dict[int, float] = {}
        worker_sizes: dict[int, int] = {}
        worker_status: dict[int, str] = {}
        total = len(items)

        total_sync_bytes = sum(
            item.pc_track.size for _, item in items_to_process if item.pc_track
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

        def _do_copy(item: SyncItem, worker_id: int) -> tuple[SyncItem, bool, Optional[Path], bool, str]:
            if item.pc_track is None:
                logger.error("_do_copy called with None pc_track for %s", item.description)
                return (item, False, None, False, "No source track")
            source_path = Path(item.pc_track.path)
            need_transcode = needs_transcoding(source_path)

            with completed_lock:
                worker_sizes[worker_id] = item.pc_track.size
                verb = "Transcoding" if need_transcode else "Copying"
                worker_status[worker_id] = f"{verb} {source_path.name} \u2014 0%"
                if ctx.progress_callback:
                    ctx.progress_callback(_build_progress())

            transcode_cb: Optional[Callable[[float], None]] = None
            copy_cb: Optional[Callable[[float], None]] = None
            if ctx.progress_callback:
                filename = source_path.name

                def _make_io_cb(_fn: str, _wid: int, _verb: str) -> Callable[[float], None]:
                    def _cb(frac: float) -> None:
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

            success, ipod_path, was_transcoded, err_msg = self._copy_to_ipod(
                source_path, need_transcode, fingerprint=item.fingerprint,
                aac_quality=ctx.aac_quality,
                transcode_progress=transcode_cb,
                copy_progress=copy_cb,
                is_cancelled=ctx._is_cancelled,
            )
            return (item, success, ipod_path, was_transcoded, err_msg)

        workers = self._max_workers
        logger.info("Stage '%s': processing %d items with %d workers", stage_name, len(items_to_process), workers)

        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            future_to_idx: dict[Future, int] = {}
            for idx, item in items_to_process:
                if ctx.cancelled():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return
                fut = pool.submit(_do_copy, item, idx)
                future_to_idx[fut] = idx

            for future in as_completed(future_to_idx):
                if ctx.cancelled():
                    for f in future_to_idx:
                        f.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    return

                idx = future_to_idx[future]
                try:
                    item, success, ipod_path, was_transcoded, err_msg = future.result()
                except (_CancelledError, _OutOfSpaceError) as e:
                    is_oom = isinstance(e, _OutOfSpaceError)
                    if is_oom:
                        logger.error(str(e))
                        ctx.result.errors.append(("storage", str(e)))
                        ctx.result.success = False
                    for f in future_to_idx:
                        f.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    return
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

                on_success(item, ipod_path, was_transcoded)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _execute_file_updates(self, ctx: _SyncContext) -> None:
        if not ctx.plan.to_update_file:
            return

        n_updates = len(ctx.plan.to_update_file)
        ctx.progress(
            "update_file", 0, n_updates,
            message="Re-syncing changed files…",
        )

        if ctx.dry_run:
            for i, item in enumerate(ctx.plan.to_update_file):
                if ctx.cancelled():
                    return
                ctx.progress("update_file", i + 1, len(ctx.plan.to_update_file),
                             item, item.description)
                ctx.result.tracks_updated_file += 1
            return

        # Pre-process: delete old files and invalidate cache (sequential, fast)
        for pi, item in enumerate(ctx.plan.to_update_file):
            if ctx.cancelled():
                return
            if item.pc_track is None:
                continue
            ctx.progress(
                "update_file", 0, n_updates,
                message=(
                    f"Preparing re-sync ({pi + 1} of {n_updates}): "
                    f"removing old iPod copy — {item.description}"
                ),
            )
            if item.ipod_track:
                file_path = item.ipod_track.get("Location") or item.ipod_track.get("location")
                if file_path:
                    relative_path = file_path.replace(":", "/").lstrip("/")
                    full_path = self.ipod_path / relative_path
                    self._delete_from_ipod(full_path)
            if item.fingerprint:
                self.transcode_cache.invalidate(item.fingerprint)

        def _on_success(item: SyncItem, ipod_path: Path, was_transcoded: bool) -> None:
            assert item.pc_track is not None  # guaranteed by _parallel_copy_stage filter
            ipod_location = ":" + str(ipod_path.relative_to(self.ipod_path)).replace("\\", ":").replace("/", ":")
            source_path = Path(item.pc_track.path)

            # Update existing TrackInfo
            db_id = item.db_id
            if db_id and db_id in ctx.tracks_by_db_id:
                existing_track = ctx.tracks_by_db_id[db_id]
                if existing_track.location in ctx.tracks_by_location:
                    del ctx.tracks_by_location[existing_track.location]
                existing_track.location = ipod_location
                existing_track.size = ipod_path.stat().st_size if ipod_path.exists() else item.pc_track.size

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
                    if ext in ("m4a", "aac") and ext != "alac":
                        from .transcoder import quality_to_nominal_bitrate
                        existing_track.bitrate = quality_to_nominal_bitrate(ctx.aac_quality)

                if item.pc_track.duration_ms:
                    existing_track.length = item.pc_track.duration_ms
                if item.pc_track.sample_rate:
                    existing_track.sample_rate = item.pc_track.sample_rate

                # IMPORTANT: Preserve media_type from the existing iPod track.
                # Don't recalculate it from the current file's metadata (stik atom),
                # which may be missing or inconsistent between syncs.
                # (media_type is already set from the original file, no change needed)

                ctx.tracks_by_location[ipod_location] = existing_track

            if db_id:
                ctx.pc_file_paths[db_id] = str(source_path)

            if item.fingerprint and ipod_path:
                source_size, source_mtime = _current_source_stat(item.pc_track)
                ctx.mapping.add_track(
                    fingerprint=item.fingerprint,
                    db_id=db_id or 0,
                    source_format=source_path.suffix.lstrip("."),
                    ipod_format=ipod_path.suffix.lstrip("."),
                    source_size=source_size,
                    source_mtime=source_mtime,
                    was_transcoded=was_transcoded,
                    source_path_hint=item.pc_track.relative_path,
                    art_hash=getattr(item.pc_track, "art_hash", None),
                )

            ctx.result.tracks_updated_file += 1

        self._parallel_copy_stage(
            ctx,
            stage_name="update_file",
            items=ctx.plan.to_update_file,
            on_success=_on_success,
            error_prefix="Failed to re-sync",
        )

    # Metadata field name → (TrackInfo attribute, coercion).
    # Coercion: None = pass-through, "int" = int-or-0, "int1" = int-or-1,
    #           "bool" = bool().
    _META_FIELD_MAP: dict[str, tuple[str, Optional[str]]] = {
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
        "season_number": ("season_number", "int"),
        "episode_number": ("episode_number", "int"),
        "sound_check": ("sound_check", "int"),
        "gapless_track_flag": ("gapless_track_flag", "int"),
        "gapless_album_flag": ("gapless_album_flag", "int"),
        "checked_flag": ("checked", "int"),
        "not_played_flag": ("played_mark", "int"),
        "volume": ("volume", "int"),
        "start_time": ("start_time", "int"),
        "stop_time": ("stop_time", "int"),
        # Boolean fields
        "compilation": ("compilation", "bool"),
        "skip_when_shuffling": ("skip_when_shuffling", "bool"),
        "remember_position": ("remember_position", "bool"),
        # Sort fields
        "sort_name": ("sort_name", None),
        "sort_artist": ("sort_artist", None),
        "sort_album": ("sort_album", None),
        "sort_album_artist": ("sort_album_artist", None),
        "sort_composer": ("sort_composer", None),
        "sort_show": ("sort_show", None),
        # Video/TV show fields
        "show_name": ("show_name", None),
        "description": ("description", None),
        "episode_id": ("episode_id", None),
        "network_name": ("network_name", None),
        "subtitle": ("subtitle", None),
        "category": ("category", None),
        # Podcast fields (field_name ≠ attr_name)
        "podcast_url": ("podcast_rss_url", None),
        "podcast_enclosure_url": ("podcast_enclosure_url", None),
        "date_released": ("date_released", "int"),
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

            db_id = item.db_id
            if db_id and db_id in ctx.tracks_by_db_id:
                track = ctx.tracks_by_db_id[db_id]
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
                fp_result = ctx.mapping.get_by_db_id(db_id) if db_id else None
                if fp_result:
                    fp, existing = fp_result
                    source_size, source_mtime = _current_source_stat(item.pc_track)
                    ctx.mapping.add_track(
                        fingerprint=fp,
                        db_id=db_id or 0,
                        source_format=existing.source_format,
                        ipod_format=existing.ipod_format,
                        source_size=source_size,
                        source_mtime=source_mtime,
                        was_transcoded=existing.was_transcoded,
                        source_path_hint=item.pc_track.relative_path,
                        art_hash=existing.art_hash,
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

        work_art = [x for x in ctx.plan.to_update_artwork if x.fingerprint]
        n_art = len(work_art)
        for ai, item in enumerate(work_art):
            if ctx.cancelled():
                return
            ctx.progress(
                "update_artwork", ai + 1, n_art,
                message=item.description or "Recording artwork change",
            )
            fp_result = ctx.mapping.get_by_db_id(item.db_id) if item.db_id else None
            if fp_result:
                fp, existing = fp_result
                ctx.mapping.add_track(
                    fingerprint=fp,
                    db_id=item.db_id or 0,
                    source_format=existing.source_format,
                    ipod_format=existing.ipod_format,
                    source_size=existing.source_size,
                    source_mtime=existing.source_mtime,
                    was_transcoded=existing.was_transcoded,
                    source_path_hint=existing.source_path_hint,
                    art_hash=item.new_art_hash,
                )

    def _download_podcast_episodes(self, ctx: _SyncContext) -> None:
        """Download podcast episodes that were selected in the plan but
        don't have local files yet.  Runs before the add stage so the
        copy/transcode pipeline has real files to work with.
        """
        if not ctx.plan.to_add:
            return

        # Identify podcast add items whose source file is missing
        pending: list[SyncItem] = []
        for item in ctx.plan.to_add:
            if item.pc_track is None:
                continue
            if not item.pc_track.is_podcast:
                continue
            source = Path(item.pc_track.path) if item.pc_track.path else None
            if source and source.exists():
                continue
            if item.pc_track.podcast_enclosure_url:
                pending.append(item)

        if not pending:
            return

        ctx.progress(
            "podcast_download", 0, len(pending),
            message=f"Downloading {len(pending)} podcast episodes…",
        )

        from PodcastManager.downloader import download_and_probe_episode
        from ._formats import IPOD_NATIVE_AUDIO

        failed_items: list[SyncItem] = []

        for idx, item in enumerate(pending):
            if ctx.cancelled():
                return

            pc = item.pc_track
            assert pc is not None
            enc_url = pc.podcast_enclosure_url or ""
            feed_url = pc.podcast_url or ""
            title = pc.title or "Episode"

            ctx.progress(
                "podcast_download", idx + 1, len(pending),
                item, f"Downloading {title}",
            )

            # Determine download destination directory
            dest_dir = str(Path(pc.path).parent) if pc.path else ""
            if not dest_dir:
                import hashlib
                url_hash = hashlib.sha256(feed_url.encode()).hexdigest()[:16]
                try:
                    from settings import get_settings
                    base = get_settings().transcode_cache_dir
                except Exception:
                    base = ""
                if not base:
                    from settings import default_cache_dir
                    base = default_cache_dir()
                dest_dir = str(Path(base) / "podcasts" / url_hash)

            # Look up feed artwork URL from the subscription store
            artwork_url = ""
            try:
                from PodcastManager.subscription_store import SubscriptionStore
                if self.ipod_path:
                    _store = SubscriptionStore(str(self.ipod_path))
                    _feed = _store.get_feed(feed_url)
                    if _feed and _feed.artwork_url:
                        artwork_url = _feed.artwork_url
            except Exception:
                pass

            try:
                info = download_and_probe_episode(
                    audio_url=enc_url,
                    title=title,
                    dest_dir=dest_dir,
                    artwork_url=artwork_url,
                )

                # Update the PCTrack with real file info
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
                pc.needs_transcoding = pc.extension not in IPOD_NATIVE_AUDIO

                logger.info("Downloaded podcast: %s", title)

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

        ctx.progress(
            "podcast_download", len(pending), len(pending),
            message=f"Downloaded {len(pending) - len(failed_items)} podcast episodes",
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
                    ctx.result.tracks_added += 1
            return

        def _on_success(item: SyncItem, ipod_path: Path, was_transcoded: bool) -> None:
            assert item.pc_track is not None  # guaranteed by _parallel_copy_stage filter
            ipod_location = ":" + str(ipod_path.relative_to(self.ipod_path)).replace("\\", ":").replace("/", ":")
            track_info = self._pc_track_to_info(item.pc_track, ipod_location, was_transcoded, ipod_file_path=ipod_path)
            ctx.new_tracks.append(track_info)

            ctx.pc_file_paths[id(track_info)] = str(item.pc_track.path)

            fingerprint = item.fingerprint
            if not fingerprint:
                fingerprint = get_or_compute_fingerprint(Path(item.pc_track.path))

            if fingerprint:
                ctx.new_track_fingerprints[id(track_info)] = fingerprint
                ctx.new_track_info[id(track_info)] = (item.pc_track, ipod_path, was_transcoded)

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
                pc_track, _ipod_path, _was_transcoded = info
                candidates.append((t, pc_track.path))

        for db_id, pc_path in ctx.pc_file_paths.items():
            t = ctx.tracks_by_db_id.get(db_id)
            if t and not t.sound_check and t.media_type not in VIDEO_TYPES:
                candidates.append((t, pc_path))

        if not candidates:
            return

        from SyncEngine.pc_library import compute_sound_check, write_sound_check_tag

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

    def _execute_scrobble(self, ctx: _SyncContext) -> None:
        """Submit new plays to ListenBrainz (non-fatal)."""
        if not ctx.scrobble_on_sync:
            return

        lb_token = ctx.listenbrainz_token
        if not lb_token:
            return

        ctx.progress(
            "scrobble", 0, 1,
            message="Submitting new plays to ListenBrainz…",
        )

        try:
            from .scrobbler import scrobble_plays

            scrobble_results = scrobble_plays(
                playcount_items=ctx.plan.to_sync_playcount,
                listenbrainz_token=lb_token,
            )

            total_accepted = 0
            for sr in scrobble_results:
                total_accepted += sr.accepted
                for err in sr.errors:
                    logger.warning("Scrobble error (%s): %s", sr.service, err)

            ctx.result.scrobbles_submitted = total_accepted
            logger.info("Scrobbled %d plays total", total_accepted)

        except Exception as exc:
            logger.warning("Scrobbling failed (non-fatal): %s", exc)

        ctx.progress("scrobble", 1, 1,
                     message=f"Scrobbled {ctx.result.scrobbles_submitted} plays")

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

            db_id = item.db_id
            if db_id and db_id in ctx.tracks_by_db_id and item.new_rating is not None:
                ctx.tracks_by_db_id[db_id].rating = item.new_rating

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
            from device_info import get_current_device
            from ipod_models import capabilities_for_family_gen
            dev = get_current_device()
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
        folder = self.music_dir / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _generate_ipod_filename(self, _original_name: str, extension: str,
                                dest_folder: Optional[Path] = None) -> str:
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
            if dest_folder is None or not (dest_folder / filename).exists():
                return filename
        # Fallback — extremely unlikely with collision check + 50 retries
        return f"{''.join(random.choices(chars, k=8))}{extension}"

    def _get_target_format(self, source_path: Path) -> str:
        """Determine the target format for transcoding."""
        from .transcoder import get_transcode_target, TranscodeTarget

        target = get_transcode_target(source_path)
        if target == TranscodeTarget.ALAC:
            return "alac"
        elif target == TranscodeTarget.AAC:
            return "aac"
        elif target == TranscodeTarget.VIDEO_H264:
            return "m4v"
        return source_path.suffix.lstrip(".")

    def _copy_to_ipod(
        self,
        source_path: Path,
        needs_transcode: bool,
        fingerprint: Optional[str] = None,
        aac_quality: str = "normal",
        transcode_progress: Optional[Callable[[float], None]] = None,
        copy_progress: Optional[Callable[[float], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> tuple[bool, Optional[Path], bool, str]:
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

        # Safety check: abort if writing this file would leave below the reserve
        try:
            free = shutil.disk_usage(self.ipod_path).free
            if free - source_size < _DISK_RESERVE_BYTES:
                free_mb = free / (1024 * 1024)
                reserve_mb = _DISK_RESERVE_BYTES / (1024 * 1024)
                raise _OutOfSpaceError(
                    f"iPod is out of space ({free_mb:.0f} MB remaining, "
                    f"{reserve_mb:.0f} MB reserve required). Stopping file writes."
                )
        except OSError:
            pass  # Can't check — proceed and let the copy fail naturally

        if needs_transcode:
            target_format = self._get_target_format(source_path)
            from .transcoder import quality_to_nominal_bitrate
            bitrate = quality_to_nominal_bitrate(aac_quality) if target_format == "aac" else None

            # Check transcode cache
            if fingerprint:
                cached_path = self.transcode_cache.get(
                    fingerprint, target_format, source_size, bitrate,
                    source_path=source_path,
                )
                if cached_path:
                    ext = cached_path.suffix
                    new_name = self._generate_ipod_filename(source_path.stem, ext, dest_folder)
                    final_path = dest_folder / new_name
                    try:
                        self._copy_file_chunked(
                            cached_path, final_path,
                            copy_progress,
                            is_cancelled=is_cancelled,
                        )
                        logger.info("Used cached transcode: %s", source_path.name)
                        return True, final_path, True, ""
                    except Exception as e:
                        logger.warning("Cache copy failed, will transcode: %s", e)

            # Transcode directly into the cache directory so ffmpeg writes
            # to local disk at full speed (8 workers truly parallel) and we
            # avoid a redundant copy.  Only the USB copy to iPod remains.
            if fingerprint:
                cache_path = self.transcode_cache.reserve(
                    fingerprint, target_format, bitrate,
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
                aac_quality=aac_quality,
                progress_callback=transcode_progress,
                is_cancelled=is_cancelled,
            )
            if result.success and result.output_path:
                # Copy metadata tags that ffmpeg may not have preserved
                from .transcoder import copy_metadata
                copy_metadata(source_path, result.output_path)

                # Register in cache index (file already in place)
                if fingerprint:
                    self.transcode_cache.commit(
                        fingerprint=fingerprint,
                        source_format=source_path.suffix.lstrip("."),
                        target_format=target_format,
                        source_size=source_size,
                        bitrate=bitrate,
                        source_path=source_path,
                    )

                # Copy to iPod (the actual bottleneck — USB I/O)
                new_name = self._generate_ipod_filename(
                    source_path.stem, result.output_path.suffix, dest_folder,
                )
                final_path = dest_folder / new_name
                self._copy_file_chunked(result.output_path, final_path, copy_progress, is_cancelled=is_cancelled)

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
                self._copy_file_chunked(source_path, dest_path, copy_progress, is_cancelled=is_cancelled)
                return True, dest_path, False, ""
            except Exception as e:
                logger.error("Copy failed: %s", e)
                return False, None, False, str(e)

    @staticmethod
    def _copy_file_chunked(
        src: Path, dst: Path,
        progress: Optional[Callable[[float], None]] = None,
        chunk_size: int = 256 * 1024,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Copy *src* to *dst* in chunks, calling *progress(0.0‒1.0)* periodically."""
        total = src.stat().st_size
        copied = 0
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while True:
                if is_cancelled and is_cancelled():
                    # Clean up partial file
                    fdst.close()
                    fsrc.close()
                    try:
                        dst.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise _CancelledError()
                buf = fsrc.read(chunk_size)
                if not buf:
                    break
                fdst.write(buf)
                copied += len(buf)
                if progress and total:
                    progress(copied / total)
        # Final callback in case total was 0 (empty file)
        if progress:
            progress(1.0)

    def _delete_from_ipod(self, ipod_path: str | Path) -> bool:
        """Delete a file from iPod."""
        try:
            path = Path(ipod_path)
            if path.exists():
                path.unlink()
                logger.debug("Deleted: %s", path)
            return True
        except Exception as e:
            logger.error("Delete failed for %s: %s", ipod_path, e)
            return False

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

    # ── iTunes protection ───────────────────────────────────────────────────

    def _apply_itunes_protections(self, ctx: _SyncContext,
                                  all_tracks: list[TrackInfo]) -> None:
        """Compute media-type totals and write iTunesPrefs protection."""
        # (media_type_mask, label) → (bytes, secs, count)
        _MEDIA_BUCKETS: list[tuple[int, str]] = [
            (0x04, "podcast"),
            (0x08, "audiobook"),
            (0x40, "tv"),
            (0x20, "mv"),
            (0x02, "video"),
        ]

        totals: dict[str, list[int]] = {
            "music": [0, 0, 0], "video": [0, 0, 0], "podcast": [0, 0, 0],
            "audiobook": [0, 0, 0], "tv": [0, 0, 0], "mv": [0, 0, 0],
        }

        for t in all_tracks:
            mt = t.media_type
            bucket = "music"
            for mask, label in _MEDIA_BUCKETS:
                if mt & mask:
                    bucket = label
                    break
            totals[bucket][0] += t.size
            totals[bucket][1] += t.length // 1000
            totals[bucket][2] += 1

        try:
            protect_from_itunes(
                self.ipod_path,
                track_count=totals["music"][2],
                total_music_bytes=totals["music"][0],
                total_music_seconds=totals["music"][1],
                video_tracks=totals["video"][2],
                video_bytes=totals["video"][0],
                video_seconds=totals["video"][1],
                podcast_tracks=totals["podcast"][2],
                podcast_bytes=totals["podcast"][0],
                podcast_seconds=totals["podcast"][1],
                audiobook_tracks=totals["audiobook"][2],
                audiobook_bytes=totals["audiobook"][0],
                audiobook_seconds=totals["audiobook"][1],
                tv_show_tracks=totals["tv"][2],
                tv_show_bytes=totals["tv"][0],
                tv_show_seconds=totals["tv"][1],
                music_video_tracks=totals["mv"][2],
                music_video_bytes=totals["mv"][0],
                music_video_seconds=totals["mv"][1],
            )
        except Exception as e:
            logger.warning("iTunesPrefs protection failed (non-fatal): %s", e)

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
        itunes_dir = self.ipod_path / "iPod_Control" / "iTunes"
        for name in ("Play Counts", "iTunesStats", "PlayCounts.plist"):
            path = itunes_dir / name
            if path.exists():
                try:
                    path.unlink()
                    logger.info("Deleted %s", path)
                except OSError as exc:
                    # Non-fatal — the file will be re-read next sync but
                    # that just means the same deltas get applied again
                    # (idempotent for play/skip counts since they're additive
                    # and the cumulative was already written).
                    logger.warning("Could not delete %s: %s", path, exc)
        # Delete all OTGPlaylistInfo files (base + numbered variants).
        # OTG playlists were imported into the iTunesDB above, so these
        # files are no longer needed.
        from iTunesDB_Parser.otg import delete_otg_files
        delete_otg_files(str(itunes_dir))

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
                          ipod_file_path: Optional[Path] = None) -> TrackInfo:
        """Convert PCTrack to TrackInfo for writing."""
        from ._track_conversion import pc_track_to_info
        return pc_track_to_info(
            pc_track, ipod_location, was_transcoded,
            ipod_file_path=ipod_file_path,
            aac_quality=self._aac_quality,
        )

    @staticmethod
    def _decode_raw_blob(value) -> Optional[bytes]:
        """Decode a raw MHOD blob from parsed playlist data."""
        from ._playlist_builder import decode_raw_blob
        return decode_raw_blob(value)

    def _build_and_evaluate_playlists(
        self,
        ctx: _SyncContext,
        all_track_infos: list[TrackInfo],
    ) -> tuple[str, list[PlaylistInfo], list[PlaylistInfo]]:
        """Build PlaylistInfo lists and evaluate smart playlist rules."""
        from ._playlist_builder import build_and_evaluate_playlists
        return build_and_evaluate_playlists(
            ctx.existing_tracks_data,
            ctx.existing_playlists_raw,
            ctx.existing_smart_raw,
            all_track_infos,
            ctx.user_playlists,
        )

    @staticmethod
    def _trackinfo_to_eval_dict(t: TrackInfo) -> dict:
        """Convert a TrackInfo to a dict the SPL evaluator can consume."""
        from ._track_conversion import trackinfo_to_eval_dict
        return trackinfo_to_eval_dict(t)

    def _write_database(
        self,
        tracks: list[TrackInfo],
        pc_file_paths: Optional[dict] = None,
        playlists: Optional[list[PlaylistInfo]] = None,
        smart_playlists: Optional[list[PlaylistInfo]] = None,
        master_playlist_name: str = "iPod",
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Write tracks to iTunesDB (and ArtworkDB/SQLite if applicable)."""
        from ._db_io import write_database
        return write_database(
            self.ipod_path, tracks,
            pc_file_paths=pc_file_paths,
            playlists=playlists,
            smart_playlists=smart_playlists,
            master_playlist_name=master_playlist_name,
            progress_callback=progress_callback,
        )
