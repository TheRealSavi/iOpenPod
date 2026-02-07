"""
Sync Executor - Executes a sync plan to synchronize PC library with iPod.

The executor takes a SyncPlan (from FingerprintDiffEngine) and:
1. Copies/transcodes new tracks to iPod
2. Removes deleted tracks from iPod
3. Updates metadata for changed tracks
4. Re-copies files that changed on PC
5. Syncs play counts and ratings back to PC
6. Builds a final list[TrackInfo] and calls write_itunesdb() ONCE

The database is always fully rewritten (not patched incrementally).
"""

import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field
from .fingerprint_diff_engine import SyncPlan, SyncItem
from .mapping import MappingManager, MappingFile
from .transcoder import transcode, needs_transcoding
from .audio_fingerprint import get_or_compute_fingerprint
from .itunes_prefs import protect_from_itunes

from iTunesDB_Writer.mhit_writer import TrackInfo

logger = logging.getLogger(__name__)


@dataclass
class SyncProgress:
    """Progress info for sync callbacks."""

    stage: str  # "add", "remove", "update_metadata", "update_file", etc.
    current: int
    total: int
    current_item: Optional[SyncItem] = None
    message: str = ""


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
        if self.errors:
            lines.append(f"  {len(self.errors)} errors occurred")

        if not lines:
            return "No changes made."

        status = "Sync completed" if self.success else "Sync completed with errors"
        return f"{status}:\n" + "\n".join(lines)


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
        self.transcode_cache = TranscodeCache(cache_dir)

        self._folder_counter = 0
        self._folder_lock = threading.Lock()

        # 0 = auto (CPU count, capped at 8), 1 = sequential
        import os
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
        aac_bitrate: int = 256,
    ) -> SyncResult:
        """
        Execute the sync plan.

        Args:
            plan: The computed sync plan.
            mapping: The iPod mapping file.
            progress_callback: Optional callback for progress updates.
            dry_run: If True, simulate without making changes.
            is_cancelled: Optional callback returning True if user cancelled.
            write_back_to_pc: If True, write play counts and ratings back to
                PC source files. Defaults to False for safety — users must
                explicitly opt in to having their PC files modified.
            aac_bitrate: Bitrate for lossy transcodes (default 256 kbps).

        Flow:
        1. Parse existing iTunesDB → dict[dbid, TrackInfo]
        2. Remove tracks (delete files, remove from dict)
        3. Update metadata (modify TrackInfo in dict)
        4. Update files (delete old, copy new, update TrackInfo)
        5. Add new tracks (copy/transcode, create TrackInfo)
        6. Sync play counts / ratings back to PC
        7. Build final list[TrackInfo], call write_itunesdb() once
        """
        result = SyncResult(success=True)

        # Store on instance so helper methods can access it
        self._aac_bitrate = aac_bitrate

        # ===== Pre-flight: Storage space check =====
        if not dry_run and plan.storage.bytes_to_add > 0:
            try:
                disk = shutil.disk_usage(self.ipod_path)
                # Need space for new files plus some buffer (10 MB for database overhead)
                needed = plan.storage.bytes_to_add - plan.storage.bytes_to_remove + (10 * 1024 * 1024)
                if needed > 0 and disk.free < needed:
                    free_mb = disk.free / (1024 * 1024)
                    need_mb = needed / (1024 * 1024)
                    result.errors.append((
                        "storage",
                        f"Not enough space on iPod: {free_mb:.0f} MB free, {need_mb:.0f} MB needed"
                    ))
                    result.success = False
                    return result
            except OSError as e:
                logger.warning(f"Could not check disk space: {e}")

        # Load existing tracks from iPod database
        existing_tracks_data = self._read_existing_tracks()

        # Convert to TrackInfo objects, indexed by dbid
        tracks_by_dbid: dict[int, TrackInfo] = {}
        tracks_by_location: dict[str, TrackInfo] = {}
        for t in existing_tracks_data:
            track_info = self._track_dict_to_info(t)
            if track_info.dbid:
                tracks_by_dbid[track_info.dbid] = track_info
            if track_info.location:
                tracks_by_location[track_info.location] = track_info

        new_tracks: list[TrackInfo] = []
        # Maps new TrackInfo object id → fingerprint (for dbid backpatch after write)
        new_track_fingerprints: dict[int, str] = {}
        # Maps new TrackInfo object id → (pc_track, ipod_path, was_transcoded) for mapping creation
        new_track_info: dict[int, tuple] = {}
        # PC source file paths for artwork extraction
        pc_file_paths: dict[int, str] = dict(plan.matched_pc_paths)
        logger.info(f"ART: starting with {len(pc_file_paths)} matched PC paths from sync plan")

        def _check_cancelled() -> bool:
            if is_cancelled and is_cancelled():
                result.errors.append(("cancelled", "Sync was cancelled by user"))
                result.success = False
                return True
            return False

        # ===== Stage 1: Remove deleted tracks =====
        self._execute_removes(plan, mapping, tracks_by_dbid, tracks_by_location, result, progress_callback, dry_run, _check_cancelled)
        if not result.success:
            return result

        # ===== Stage 2: Update files (re-copy/transcode changed files) =====
        self._execute_file_updates(plan, mapping, tracks_by_dbid, tracks_by_location, pc_file_paths, result, progress_callback, dry_run, _check_cancelled, aac_bitrate)
        if not result.success:
            return result

        # ===== Stage 3: Update metadata =====
        self._execute_metadata_updates(plan, mapping, tracks_by_dbid, result, progress_callback, dry_run, _check_cancelled)
        if not result.success:
            return result

        # ===== Stage 3b: Update artwork mapping entries =====
        self._execute_artwork_updates(plan, mapping, dry_run)

        # ===== Stage 4: Add new tracks =====
        self._execute_adds(plan, mapping, new_tracks, new_track_fingerprints, new_track_info, pc_file_paths, result, progress_callback, dry_run, _check_cancelled, aac_bitrate)
        if not result.success:
            return result

        # ===== Stage 5: Sync play counts back to PC =====
        self._execute_playcount_sync(plan, tracks_by_dbid, result, progress_callback, dry_run, _check_cancelled, write_back_to_pc)
        if not result.success:
            return result

        # ===== Stage 6: Sync ratings =====
        self._execute_rating_sync(plan, tracks_by_dbid, result, progress_callback, dry_run, _check_cancelled, write_back_to_pc)
        if not result.success:
            return result

        # ===== Stage 7: Write database (one shot) =====
        if not dry_run:
            if progress_callback:
                progress_callback(SyncProgress("write_database", 0, 1, message="Writing database..."))

            all_tracks = list(tracks_by_dbid.values()) + new_tracks

            # pc_file_paths has mixed keys: dbid (int) for existing tracks,
            # id(track_info) for new tracks.  mhbd_writer.py handles the
            # obj-id → dbid remapping after assigning real dbids.

            logger.info(f"ART: pc_file_paths total={len(pc_file_paths)}, all_tracks={len(all_tracks)}")

            # Always write — even if all_tracks is empty (e.g. all tracks
            # were removed).  Skipping the write would leave the old DB
            # intact and ghost tracks would reappear on next sync.
            try:
                self._write_database(all_tracks, pc_file_paths=pc_file_paths)
                if progress_callback:
                    progress_callback(SyncProgress("write_database", 1, 1, message=f"Database written with {len(all_tracks)} tracks"))

                # ── Backpatch: new tracks now have real dbids assigned by writer ──
                for track in new_tracks:
                    obj_key = id(track)
                    fp = new_track_fingerprints.get(obj_key)
                    info = new_track_info.get(obj_key)
                    if fp and info and track.dbid != 0:
                        pc_track, ipod_dest, was_transcoded = info
                        mapping.add_track(
                            fingerprint=fp,
                            dbid=track.dbid,
                            source_format=Path(pc_track.path).suffix.lstrip("."),
                            ipod_format=ipod_dest.suffix.lstrip("."),
                            source_size=pc_track.size,
                            source_mtime=pc_track.mtime,
                            was_transcoded=was_transcoded,
                            source_path_hint=pc_track.relative_path,
                            art_hash=getattr(pc_track, "art_hash", None),
                        )

                # Save mapping ONLY after successful DB write + backpatch.
                # If write fails, we must NOT save the mutated mapping
                # (stages 1-6 already modified it), or the next sync will
                # see mismatched state and create duplicates.
                self.mapping_manager.save(mapping)

                # ── Apply iTunes protections ────────────────────────────
                # Compute totals from the final track list for the plist
                total_bytes = sum(t.size for t in all_tracks)
                total_secs = sum(t.length for t in all_tracks) // 1000
                try:
                    protect_from_itunes(
                        self.ipod_path,
                        track_count=len(all_tracks),
                        total_music_bytes=total_bytes,
                        total_music_seconds=total_secs,
                    )
                except Exception as e:
                    # Non-fatal — database is already written + mapping saved
                    logger.warning("iTunesPrefs protection failed (non-fatal): %s", e)

            except Exception as e:
                result.errors.append(("database write", str(e)))
                logger.error("Database write failed — mapping NOT saved to preserve consistency")

        result.success = not result.has_errors
        return result

    # ── Stage Implementations ───────────────────────────────────────────────

    def _execute_removes(self, plan, mapping, tracks_by_dbid, tracks_by_location, result, progress_callback, dry_run, check_cancelled=None):
        if not plan.to_remove:
            return

        if progress_callback:
            progress_callback(SyncProgress("remove", 0, len(plan.to_remove), message="Removing tracks..."))

        for i, item in enumerate(plan.to_remove):
            if check_cancelled and check_cancelled():
                return

            if progress_callback:
                progress_callback(SyncProgress("remove", i + 1, len(plan.to_remove), item, item.description))

            if dry_run:
                result.tracks_removed += 1
                continue

            # Delete file from iPod
            if item.ipod_track:
                file_path = item.ipod_track.get("Location")
                if file_path:
                    relative_path = file_path.replace(":", "/").lstrip("/")
                    full_path = self.ipod_path / relative_path
                    self._delete_from_ipod(full_path)

                    if file_path in tracks_by_location:
                        track_to_remove = tracks_by_location.pop(file_path)
                        if track_to_remove.dbid in tracks_by_dbid:
                            del tracks_by_dbid[track_to_remove.dbid]

            # Remove from mapping
            if item.fingerprint:
                mapping.remove_track(item.fingerprint, dbid=item.dbid)
            elif item.dbid:
                mapping.remove_by_dbid(item.dbid)

            # Always ensure track is removed from tracks_by_dbid
            if item.dbid and item.dbid in tracks_by_dbid:
                del tracks_by_dbid[item.dbid]

            result.tracks_removed += 1

        # Clean stale mapping entries (dbid not in iTunesDB, nothing to remove from iPod)
        for fp, dbid in getattr(plan, '_stale_mapping_entries', []):
            mapping.remove_track(fp, dbid=dbid)

    def _execute_file_updates(self, plan, mapping, tracks_by_dbid, tracks_by_location, pc_file_paths, result, progress_callback, dry_run, check_cancelled=None, aac_bitrate=256):
        if not plan.to_update_file:
            return

        if progress_callback:
            progress_callback(SyncProgress("update_file", 0, len(plan.to_update_file), message="Re-syncing changed files..."))

        if dry_run:
            for i, item in enumerate(plan.to_update_file):
                if check_cancelled and check_cancelled():
                    return
                if progress_callback:
                    progress_callback(SyncProgress("update_file", i + 1, len(plan.to_update_file), item, item.description))
                result.tracks_updated_file += 1
            return

        # Pre-process: delete old files and invalidate cache (sequential, fast)
        for item in plan.to_update_file:
            if item.pc_track is None:
                continue
            if item.ipod_track:
                file_path = item.ipod_track.get("Location") or item.ipod_track.get("location")
                if file_path:
                    relative_path = file_path.replace(":", "/").lstrip("/")
                    full_path = self.ipod_path / relative_path
                    self._delete_from_ipod(full_path)
            if item.fingerprint:
                self.transcode_cache.invalidate(item.fingerprint)

        # ── Parallel transcode/copy ─────────────────────────────────────
        items_to_process = [(i, item) for i, item in enumerate(plan.to_update_file) if item.pc_track is not None]
        if not items_to_process:
            return

        completed_count = 0
        completed_lock = threading.Lock()
        total = len(plan.to_update_file)

        def _do_copy(item: SyncItem) -> tuple[SyncItem, bool, Optional[Path], bool]:
            """Transcode/copy a single track. Runs in worker thread."""
            source_path = Path(item.pc_track.path)
            need_transcode = needs_transcoding(source_path)
            success, ipod_path, was_transcoded = self._copy_to_ipod(
                source_path, need_transcode, fingerprint=item.fingerprint,
                aac_bitrate=aac_bitrate,
            )
            return (item, success, ipod_path, was_transcoded)

        workers = self._max_workers
        logger.info(f"Re-syncing {len(items_to_process)} files with {workers} workers")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_idx: dict[Future, int] = {}
            for idx, item in items_to_process:
                if check_cancelled and check_cancelled():
                    return
                fut = pool.submit(_do_copy, item)
                future_to_idx[fut] = idx

            for future in as_completed(future_to_idx):
                if check_cancelled and check_cancelled():
                    for f in future_to_idx:
                        f.cancel()
                    return

                idx = future_to_idx[future]
                try:
                    item, success, ipod_path, was_transcoded = future.result()
                except Exception as e:
                    item = plan.to_update_file[idx]
                    result.errors.append((item.description, f"Worker error: {e}"))
                    logger.error(f"Worker exception for {item.description}: {e}")
                    with completed_lock:
                        completed_count += 1
                    if progress_callback:
                        progress_callback(SyncProgress("update_file", completed_count, total, item, item.description))
                    continue

                with completed_lock:
                    completed_count += 1

                if progress_callback:
                    progress_callback(SyncProgress("update_file", completed_count, total, item, item.description))

                if not success or ipod_path is None:
                    result.errors.append((item.description, "Failed to re-sync"))
                    continue

                ipod_location = ":" + str(ipod_path.relative_to(self.ipod_path)).replace("\\", ":").replace("/", ":")
                source_path = Path(item.pc_track.path)

                # Update existing TrackInfo
                dbid = item.dbid
                if dbid and dbid in tracks_by_dbid:
                    existing_track = tracks_by_dbid[dbid]
                    if existing_track.location in tracks_by_location:
                        del tracks_by_location[existing_track.location]
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
                            existing_track.bitrate = aac_bitrate

                    if item.pc_track.duration_ms:
                        existing_track.length = item.pc_track.duration_ms
                    if item.pc_track.sample_rate:
                        existing_track.sample_rate = item.pc_track.sample_rate

                    tracks_by_location[ipod_location] = existing_track

                if dbid:
                    pc_file_paths[dbid] = str(source_path)

                if item.fingerprint and ipod_path:
                    mapping.add_track(
                        fingerprint=item.fingerprint,
                        dbid=dbid or 0,
                        source_format=source_path.suffix.lstrip("."),
                        ipod_format=ipod_path.suffix.lstrip("."),
                        source_size=item.pc_track.size,
                        source_mtime=item.pc_track.mtime,
                        was_transcoded=was_transcoded,
                        source_path_hint=item.pc_track.relative_path,
                        art_hash=getattr(item.pc_track, "art_hash", None),
                    )

                result.tracks_updated_file += 1

    def _execute_metadata_updates(self, plan, mapping, tracks_by_dbid, result, progress_callback, dry_run, check_cancelled=None):
        if not plan.to_update_metadata:
            return

        if progress_callback:
            progress_callback(SyncProgress("update_metadata", 0, len(plan.to_update_metadata), message="Updating metadata..."))

        for i, item in enumerate(plan.to_update_metadata):
            if check_cancelled and check_cancelled():
                return

            if progress_callback:
                progress_callback(SyncProgress("update_metadata", i + 1, len(plan.to_update_metadata), item, item.description))

            if dry_run:
                result.tracks_updated_metadata += 1
                continue

            dbid = item.dbid
            if dbid and dbid in tracks_by_dbid:
                track = tracks_by_dbid[dbid]
                for field_name, (pc_value, _ipod_value) in item.metadata_changes.items():
                    if field_name == "title":
                        track.title = pc_value
                    elif field_name == "artist":
                        track.artist = pc_value
                    elif field_name == "album":
                        track.album = pc_value
                    elif field_name == "album_artist":
                        track.album_artist = pc_value
                    elif field_name == "genre":
                        track.genre = pc_value
                    elif field_name == "year":
                        track.year = pc_value if pc_value else 0
                    elif field_name == "track_number":
                        track.track_number = pc_value if pc_value else 0
                    elif field_name == "disc_number":
                        track.disc_number = pc_value if pc_value else 0

            # Refresh mapping mtime/size so next sync doesn't see a spurious file change
            if item.fingerprint and item.pc_track and not dry_run:
                fp_result = mapping.get_by_dbid(dbid) if dbid else None
                if fp_result:
                    fp, existing = fp_result
                    mapping.add_track(
                        fingerprint=fp,
                        dbid=dbid,
                        source_format=existing.source_format,
                        ipod_format=existing.ipod_format,
                        source_size=item.pc_track.size,
                        source_mtime=item.pc_track.mtime,
                        was_transcoded=existing.was_transcoded,
                        source_path_hint=item.pc_track.relative_path,
                        art_hash=existing.art_hash,
                    )

            result.tracks_updated_metadata += 1

    def _execute_artwork_updates(self, plan, mapping, dry_run):
        """Update mapping art_hash for tracks with changed artwork.

        The actual artwork re-encoding is handled by the full ArtworkDB rewrite
        since we always pass pc_file_paths to write_artworkdb(). This method
        only ensures the mapping stays in sync so we don't detect the same
        change again next sync.
        """
        if not plan.to_update_artwork or dry_run:
            return

        for item in plan.to_update_artwork:
            if not item.fingerprint:
                continue
            # Update mapping for both art changes AND art removals
            # (new_art_hash=None means art was removed from PC file)
            fp_result = mapping.get_by_dbid(item.dbid) if item.dbid else None
            if fp_result:
                fp, existing = fp_result
                mapping.add_track(
                    fingerprint=fp,
                    dbid=item.dbid,
                    source_format=existing.source_format,
                    ipod_format=existing.ipod_format,
                    source_size=existing.source_size,
                    source_mtime=existing.source_mtime,
                    was_transcoded=existing.was_transcoded,
                    source_path_hint=existing.source_path_hint,
                    art_hash=item.new_art_hash,
                )

    def _execute_adds(self, plan, mapping, new_tracks, new_track_fingerprints, new_track_info, pc_file_paths, result, progress_callback, dry_run, check_cancelled=None, aac_bitrate=256):
        if not plan.to_add:
            return

        if progress_callback:
            progress_callback(SyncProgress("add", 0, len(plan.to_add), message="Adding new tracks..."))

        if dry_run:
            for i, item in enumerate(plan.to_add):
                if check_cancelled and check_cancelled():
                    return
                if progress_callback:
                    progress_callback(SyncProgress("add", i + 1, len(plan.to_add), item, item.description))
                if item.pc_track is not None:
                    result.tracks_added += 1
            return

        # ── Parallel transcode/copy ─────────────────────────────────────
        # Submit all copy/transcode jobs to a thread pool, then process
        # results sequentially for metadata, mapping, and progress updates.

        items_to_process = [(i, item) for i, item in enumerate(plan.to_add) if item.pc_track is not None]
        if not items_to_process:
            return

        completed_count = 0
        completed_lock = threading.Lock()
        total = len(plan.to_add)

        def _do_copy(item: SyncItem) -> tuple[SyncItem, bool, Optional[Path], bool]:
            """Transcode/copy a single track. Runs in worker thread."""
            source_path = Path(item.pc_track.path)
            need_transcode = needs_transcoding(source_path)
            success, ipod_path, was_transcoded = self._copy_to_ipod(
                source_path, need_transcode, fingerprint=item.fingerprint,
                aac_bitrate=aac_bitrate,
            )
            return (item, success, ipod_path, was_transcoded)

        workers = self._max_workers
        logger.info(f"Adding {len(items_to_process)} tracks with {workers} workers")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            # Submit all jobs
            future_to_idx: dict[Future, int] = {}
            for idx, item in items_to_process:
                if check_cancelled and check_cancelled():
                    return
                fut = pool.submit(_do_copy, item)
                future_to_idx[fut] = idx

            # Process results as they complete
            for future in as_completed(future_to_idx):
                if check_cancelled and check_cancelled():
                    # Cancel pending futures
                    for f in future_to_idx:
                        f.cancel()
                    return

                idx = future_to_idx[future]
                try:
                    item, success, ipod_path, was_transcoded = future.result()
                except Exception as e:
                    item = plan.to_add[idx]
                    result.errors.append((item.description, f"Worker error: {e}"))
                    logger.error(f"Worker exception for {item.description}: {e}")
                    with completed_lock:
                        completed_count += 1
                    if progress_callback:
                        progress_callback(SyncProgress("add", completed_count, total, item, item.description))
                    continue

                with completed_lock:
                    completed_count += 1

                if progress_callback:
                    progress_callback(SyncProgress("add", completed_count, total, item, item.description))

                if not success or ipod_path is None:
                    result.errors.append((item.description, "Failed to copy/transcode"))
                    continue

                ipod_location = ":" + str(ipod_path.relative_to(self.ipod_path)).replace("\\", ":").replace("/", ":")
                track_info = self._pc_track_to_info(item.pc_track, ipod_location, was_transcoded, ipod_file_path=ipod_path)
                new_tracks.append(track_info)

                # Track PC path for artwork extraction (keyed by obj id since dbid=0)
                pc_file_paths[id(track_info)] = str(item.pc_track.path)

                # Update mapping
                fingerprint = item.fingerprint
                if not fingerprint:
                    fingerprint = get_or_compute_fingerprint(Path(item.pc_track.path))

                # Remember fingerprint for this track so we can backpatch the real dbid later
                if fingerprint:
                    new_track_fingerprints[id(track_info)] = fingerprint
                    new_track_info[id(track_info)] = (item.pc_track, ipod_path, was_transcoded)

                # Note: mapping entry is NOT created here yet — dbid=0 is useless.
                # Entry will be created after _write_database() assigns real dbids.

                result.tracks_added += 1

    def _execute_playcount_sync(self, plan, tracks_by_dbid, result, progress_callback, dry_run, check_cancelled=None, write_back_to_pc=False):
        if not plan.to_sync_playcount:
            return

        if progress_callback:
            progress_callback(SyncProgress("sync_playcount", 0, len(plan.to_sync_playcount), message="Syncing play counts..."))

        for i, item in enumerate(plan.to_sync_playcount):
            if check_cancelled and check_cancelled():
                return

            if progress_callback:
                progress_callback(SyncProgress("sync_playcount", i + 1, len(plan.to_sync_playcount), item, item.description))

            if dry_run:
                result.playcounts_synced += 1
                continue

            # Play counts are already folded by _track_dict_to_info:
            #   play_count = playCount + playCount2
            # Do NOT add play_count_delta here — it equals playCount2, which
            # was already folded. Adding it again would double-count.
            #
            # The mhit_writer resets playCount2 to 0, so next sync only
            # picks up genuinely new plays.

            # Write play count delta back to PC file metadata (only if user opted in)
            if write_back_to_pc and item.pc_track and item.play_count_delta:
                self._write_playcount_to_pc(
                    item.pc_track.path,
                    item.play_count_delta,
                    item.skip_count_delta or 0,
                )
            logger.debug(f"Play count sync: {item.description} +{item.play_count_delta} plays")
            result.playcounts_synced += 1

    def _execute_rating_sync(self, plan, tracks_by_dbid, result, progress_callback, dry_run, check_cancelled=None, write_back_to_pc=False):
        if not plan.to_sync_rating:
            return

        if progress_callback:
            progress_callback(SyncProgress("sync_rating", 0, len(plan.to_sync_rating), message="Syncing ratings..."))

        for i, item in enumerate(plan.to_sync_rating):
            if check_cancelled and check_cancelled():
                return

            if progress_callback:
                progress_callback(SyncProgress("sync_rating", i + 1, len(plan.to_sync_rating), item, item.description))

            if dry_run:
                result.ratings_synced += 1
                continue

            # Apply the resolved rating (last-write-wins) to the iPod TrackInfo
            dbid = item.dbid
            if dbid and dbid in tracks_by_dbid and item.new_rating is not None:
                tracks_by_dbid[dbid].rating = item.new_rating

            # Write rating to PC file metadata (only if user opted in)
            if write_back_to_pc and item.pc_track and item.new_rating is not None:
                self._write_rating_to_pc(item.pc_track.path, item.new_rating)
            logger.debug(f"Rating sync: {item.description} → {item.new_rating}")
            result.ratings_synced += 1

    # ── File Operations ─────────────────────────────────────────────────────

    def _get_next_music_folder(self) -> Path:
        """Get next music folder (F00-F49) using round-robin. Thread-safe."""
        with self._folder_lock:
            folder_name = f"F{self._folder_counter:02d}"
            self._folder_counter = (self._folder_counter + 1) % 50
        folder = self.music_dir / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _generate_ipod_filename(self, original_name: str, extension: str,
                                dest_folder: Optional[Path] = None) -> str:
        """Generate a unique filename for iPod storage.

        Uses 8 random chars to minimize collision probability.
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
        return source_path.suffix.lstrip(".")

    def _copy_to_ipod(
        self,
        source_path: Path,
        needs_transcode: bool,
        fingerprint: Optional[str] = None,
        aac_bitrate: int = 256,
    ) -> tuple[bool, Optional[Path], bool]:
        """
        Copy or transcode a file to iPod, using cache when possible.

        Returns: (success, ipod_path, was_transcoded)
        """
        dest_folder = self._get_next_music_folder()
        source_size = source_path.stat().st_size

        if needs_transcode:
            target_format = self._get_target_format(source_path)
            bitrate = aac_bitrate if target_format == "aac" else None

            # Check transcode cache
            if fingerprint:
                cached_path = self.transcode_cache.get(
                    fingerprint, target_format, source_size, bitrate,
                )
                if cached_path:
                    ext = cached_path.suffix
                    new_name = self._generate_ipod_filename(source_path.stem, ext, dest_folder)
                    final_path = dest_folder / new_name
                    try:
                        shutil.copy2(cached_path, final_path)
                        logger.info(f"Used cached transcode: {source_path.name}")
                        return True, final_path, True
                    except Exception as e:
                        logger.warning(f"Cache copy failed, will transcode: {e}")

            # Transcode
            result = transcode(source_path, dest_folder, aac_bitrate=aac_bitrate)
            if result.success and result.output_path:
                # Copy metadata tags that ffmpeg may not have preserved
                from .transcoder import copy_metadata
                copy_metadata(source_path, result.output_path)

                new_name = self._generate_ipod_filename(source_path.stem, result.output_path.suffix, dest_folder)
                final_path = dest_folder / new_name
                result.output_path.rename(final_path)

                if fingerprint:
                    self.transcode_cache.add(
                        fingerprint=fingerprint,
                        transcoded_path=final_path,
                        source_format=source_path.suffix.lstrip("."),
                        target_format=target_format,
                        source_size=source_size,
                        bitrate=bitrate,
                    )

                return True, final_path, True
            else:
                logger.error(f"Transcode failed: {result.error_message}")
                return False, None, True
        else:
            # Direct copy
            new_name = self._generate_ipod_filename(source_path.stem, source_path.suffix, dest_folder)
            dest_path = dest_folder / new_name
            try:
                shutil.copy2(source_path, dest_path)
                return True, dest_path, False
            except Exception as e:
                logger.error(f"Copy failed: {e}")
                return False, None, False

    def _delete_from_ipod(self, ipod_path: str | Path) -> bool:
        """Delete a file from iPod."""
        try:
            path = Path(ipod_path)
            if path.exists():
                path.unlink()
                logger.debug(f"Deleted: {path}")
            return True
        except Exception as e:
            logger.error(f"Delete failed for {ipod_path}: {e}")
            return False

    # ── PC Write-Back ───────────────────────────────────────────────────────

    def _write_playcount_to_pc(self, file_path: str, play_delta: int, skip_delta: int) -> bool:
        """Write play count delta back to PC file metadata using mutagen.

        For MP3: uses PCNT (play counter) frame.
        For M4A/FLAC/OGG: uses custom tags.
        """
        try:
            import mutagen  # type: ignore[import-untyped]
            from mutagen.id3._frames import PCNT  # type: ignore[import-untyped]

            ext = Path(file_path).suffix.lower()
            audio = mutagen.File(file_path)  # type: ignore[attr-defined]
            if audio is None:
                return False

            if ext == ".mp3":
                # PCNT frame: increment existing count
                existing = 0
                if "PCNT" in audio.tags:
                    existing = audio.tags["PCNT"].count
                audio.tags.add(PCNT(count=existing + play_delta))
                audio.save()
            elif ext in (".m4a", ".m4p", ".aac"):
                # Custom freeform atom for play count
                key = "----:com.apple.iTunes:PLAY_COUNT"
                existing = 0
                if key in audio.tags:
                    try:
                        existing = int(audio.tags[key][0].decode())
                    except (ValueError, TypeError, IndexError):
                        pass
                from mutagen.mp4 import MP4FreeForm  # type: ignore[import-untyped]
                audio.tags[key] = [MP4FreeForm(str(existing + play_delta).encode())]
                audio.save()
            elif ext in (".flac", ".ogg", ".opus"):
                # Vorbis comment
                existing = 0
                if "PLAY_COUNT" in audio.tags:
                    try:
                        existing = int(audio.tags["PLAY_COUNT"][0])
                    except (ValueError, TypeError, IndexError):
                        pass
                audio.tags["PLAY_COUNT"] = [str(existing + play_delta)]
                audio.save()

            return True
        except Exception as e:
            logger.warning(f"Could not write play count to {file_path}: {e}")
            return False

    def _write_rating_to_pc(self, file_path: str, rating: int) -> bool:
        """Write rating (0-100) to PC file metadata using mutagen.

        For MP3: uses POPM (Popularimeter) frame (0-255 scale).
        For M4A: uses 'rtng' atom (0-100 scale, same as iPod).
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
                audio.tags.add(POPM(email="iOpenPod", rating=popm_rating, count=0))
                audio.save()
            elif ext in (".m4a", ".m4p", ".aac"):
                # rtng atom: stores rating directly (0-100)
                audio.tags["rtng"] = [rating]
                audio.save()
            elif ext in (".flac", ".ogg", ".opus"):
                # RATING vorbis comment (store as 0-100)
                audio.tags["RATING"] = [str(rating)]
                audio.save()

            return True
        except Exception as e:
            logger.warning(f"Could not write rating to {file_path}: {e}")
            return False

    # ── Track Conversion ────────────────────────────────────────────────────

    def _read_existing_tracks(self) -> list[dict]:
        """Read existing tracks from iTunesDB."""
        from iTunesDB_Parser import parse_itunesdb

        itdb_path = self.ipod_path / "iPod_Control" / "iTunes" / "iTunesDB"
        if not itdb_path.exists():
            return []

        try:
            result = parse_itunesdb(str(itdb_path))
            return result.get("mhlt", [])
        except Exception as e:
            logger.error(f"Failed to parse iTunesDB: {e}")
            return []

    def _track_dict_to_info(self, t: dict) -> TrackInfo:
        """Convert parsed track dict to TrackInfo for writing."""
        filetype = t.get("filetype", "MP3")
        if "AAC" in filetype or "M4A" in filetype:
            filetype_code = "m4a"
        elif "Lossless" in filetype:
            filetype_code = "m4a"
        else:
            filetype_code = "mp3"

        return TrackInfo(
            title=t.get("Title", "Unknown"),
            location=t.get("Location", ""),
            size=t.get("size", 0),
            length=t.get("length", 0),
            filetype=filetype_code,
            bitrate=t.get("bitrate", 0),
            sample_rate=t.get("sampleRate", 44100),
            vbr=bool(t.get("vbr", 0)),
            artist=t.get("Artist"),
            album=t.get("Album"),
            album_artist=t.get("Album Artist"),
            genre=t.get("Genre"),
            composer=t.get("Composer"),
            year=t.get("year", 0),
            track_number=t.get("trackNumber", 0),
            total_tracks=t.get("totalTracks", 0),
            disc_number=t.get("discNumber", 1),
            total_discs=t.get("totalDiscs", 1),
            bpm=t.get("bpm", 0),
            compilation=bool(t.get("compilation", 0)),
            rating=t.get("rating", 0),
            play_count=t.get("playCount", 0) + t.get("playCount2", 0),
            skip_count=t.get("skipCount", 0),
            volume=t.get("volume", 0),
            date_added=t.get("dateAdded", 0),
            last_played=t.get("lastPlayed", 0),
            last_skipped=t.get("lastSkipped", 0),
            dbid=t.get("dbid", 0),
            media_type=t.get("mediaType", 1),
            artwork_count=t.get("artworkCount", 0),
            artwork_size=t.get("artworkSize", 0),
            mhii_link=t.get("mhiiLink", 0),
            sort_artist=t.get("Sort Artist"),
            sort_name=t.get("Sort Name"),
            sort_album=t.get("Sort Album"),
            filetype_desc=t.get("filetype"),
        )

    def _pc_track_to_info(self, pc_track, ipod_location: str, was_transcoded: bool,
                          ipod_file_path: Optional[Path] = None) -> TrackInfo:
        """Convert PCTrack to TrackInfo for writing.

        Args:
            pc_track: Source track metadata from PC.
            ipod_location: iPod-style colon-separated path.
            was_transcoded: Whether the file was format-converted.
            ipod_file_path: Actual file on iPod (for accurate size after transcode).
        """
        ext = Path(ipod_location.replace(":", "/")).suffix.lower().lstrip(".")
        if ext in ("m4a", "aac", "alac"):
            filetype = "m4a"
        elif ext == "mp3":
            filetype = "mp3"
        else:
            filetype = ext

        # Rating: PCTrack already stores 0-100 (stars × 20), same as iPod
        rating = pc_track.rating or 0

        # File size: use actual iPod file size (especially important after transcode)
        if ipod_file_path and ipod_file_path.exists():
            file_size = ipod_file_path.stat().st_size
        else:
            file_size = pc_track.size or 0

        # Bitrate/sample_rate: use source values for direct copies,
        # but for transcodes we should probe the actual file.
        # As a practical default, use AAC 256kbps for transcoded AAC.
        bitrate = pc_track.bitrate or 0
        sample_rate = pc_track.sample_rate or 44100
        if was_transcoded:
            if filetype == "m4a" and ext != "alac":
                # AAC transcode — use the configured bitrate
                bitrate = self._aac_bitrate  # user-configured AAC bitrate
            # sample_rate is typically preserved by transcoder

        return TrackInfo(
            title=pc_track.title or Path(pc_track.path).stem,
            location=ipod_location,
            size=file_size,
            length=pc_track.duration_ms or 0,
            filetype=filetype,
            bitrate=bitrate,
            sample_rate=sample_rate,
            artist=pc_track.artist,
            album=pc_track.album,
            album_artist=pc_track.album_artist,
            genre=pc_track.genre,
            composer=getattr(pc_track, "composer", None),
            year=pc_track.year or 0,
            track_number=pc_track.track_number or 0,
            total_tracks=getattr(pc_track, "track_total", None) or 0,
            disc_number=pc_track.disc_number or 1,
            total_discs=getattr(pc_track, "disc_total", None) or 1,
            rating=rating,
            play_count=getattr(pc_track, "play_count", 0) or 0,
            compilation=getattr(pc_track, "compilation", False),
            sort_artist=getattr(pc_track, "sort_artist", None),
            sort_name=getattr(pc_track, "sort_name", None),
            sort_album=getattr(pc_track, "sort_album", None),
        )

    def _write_database(
        self,
        tracks: list[TrackInfo],
        pc_file_paths: Optional[dict] = None,
    ) -> bool:
        """Write tracks to iTunesDB (and ArtworkDB if pc_file_paths provided)."""
        from iTunesDB_Writer import write_itunesdb

        logger.info(f"ART: _write_database called with {len(tracks)} tracks, "
                    f"pc_file_paths={'None' if pc_file_paths is None else len(pc_file_paths)}")

        try:
            return write_itunesdb(
                str(self.ipod_path),
                tracks,
                pc_file_paths=pc_file_paths,
            )
        except Exception as e:
            logger.error(f"Failed to write iTunesDB: {e}")
            import traceback
            traceback.print_exc()
            return False
