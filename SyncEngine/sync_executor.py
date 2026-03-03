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

import base64
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

from iTunesDB_Writer.mhit_writer import (
    TrackInfo,
    MEDIA_TYPE_AUDIO,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_VIDEO_PODCAST,
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_TV_SHOW,
)
from iTunesDB_Writer.mhyp_writer import PlaylistInfo, PlaylistItemMeta
from iTunesDB_Writer.mhod_spl_writer import (
    prefs_from_parsed, rules_from_parsed,
    SmartPlaylistPrefs, SmartPlaylistRule, SmartPlaylistRules,
)

logger = logging.getLogger(__name__)


class _OutOfSpaceError(Exception):
    """Raised when iPod disk space drops below the 30 MB safety reserve."""
    pass


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

        # Load existing tracks and playlists from iPod database
        existing_db = self._read_existing_database()
        existing_tracks_data = existing_db["tracks"]
        existing_playlists_raw = existing_db["playlists"]
        existing_smart_raw = existing_db["smart_playlists"]

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
        logger.debug(f"ART: starting with {len(pc_file_paths)} matched PC paths from sync plan")

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

            # ── Auto-detect gapless_album_flag ────────────────────────
            # If ALL tracks in an album have gapless_track_flag set, mark
            # them all with gapless_album_flag=1 (tells iPod to apply
            # gapless playback across album transitions).
            from collections import defaultdict
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

            # pc_file_paths has mixed keys: dbid (int) for existing tracks,
            # id(track_info) for new tracks.  mhbd_writer.py handles the
            # obj-id → dbid remapping after assigning real dbids.

            logger.debug(f"ART: pc_file_paths total={len(pc_file_paths)}, all_tracks={len(all_tracks)}")

            # ── Merge user-created playlists from GUI cache ────────────
            playlist_merge_count = 0
            try:
                from GUI.app import iTunesDBCache
                cache = iTunesDBCache.get_instance()
                user_pls = cache.get_user_playlists()
                if user_pls and progress_callback:
                    progress_callback(SyncProgress("playlists", 0, len(user_pls), message="Merging playlists..."))
                for idx, upl in enumerate(user_pls):
                    is_new = upl.get("_isNew", False)
                    pid = upl.get("playlistID", 0)
                    if is_new:
                        # Brand-new playlist — add to the regular list
                        # (smart playlists in dataset 2 are fully supported)
                        existing_playlists_raw.append(upl)
                    else:
                        # Edited existing playlist — replace in-place
                        replaced = False
                        for i, epl in enumerate(existing_playlists_raw):
                            if epl.get("playlistID") == pid:
                                existing_playlists_raw[i] = upl
                                replaced = True
                                break
                        if not replaced:
                            for i, epl in enumerate(existing_smart_raw):
                                if epl.get("playlistID") == pid:
                                    existing_smart_raw[i] = upl
                                    replaced = True
                                    break
                        if not replaced:
                            existing_playlists_raw.append(upl)
                    playlist_merge_count += 1
                    logger.info("Merged user playlist '%s' (id=0x%X, new=%s)",
                                upl.get("Title", "?"), pid, is_new)
                    if progress_callback:
                        progress_callback(SyncProgress("playlists", idx + 1, len(user_pls),
                                                       message=f"Merged playlist: {upl.get('Title', '?')}"))
            except Exception as e:
                logger.debug("No GUI cache available (headless sync?): %s", e)

            # ── Build playlists and evaluate smart playlists ──────────
            playlists, smart_playlists = self._build_and_evaluate_playlists(
                existing_tracks_data, all_tracks,
                existing_playlists_raw, existing_smart_raw,
            )

            # Always write — even if all_tracks is empty (e.g. all tracks
            # were removed).  Skipping the write would leave the old DB
            # intact and ghost tracks would reappear on next sync.
            try:
                self._write_database(
                    all_tracks, pc_file_paths=pc_file_paths,
                    playlists=playlists, smart_playlists=smart_playlists,
                )
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

                # Clear user playlists from cache — they've been written
                try:
                    from GUI.app import iTunesDBCache
                    gui_cache = iTunesDBCache.get_instance()
                    if gui_cache.has_pending_playlists():
                        gui_cache._user_playlists.clear()
                        logger.info("Cleared pending user playlists after successful write")
                    if gui_cache.has_pending_track_edits():
                        gui_cache.clear_track_edits()
                        logger.info("Cleared pending track flag edits after successful write")
                except Exception:
                    pass

                # ── Apply iTunes protections ────────────────────────────
                # Compute totals from the final track list for the plist
                # Break down by media type category for accurate reporting
                music_bytes = music_secs = music_count = 0
                video_bytes = video_secs = video_count = 0
                podcast_bytes = podcast_secs = podcast_count = 0
                audiobook_bytes = audiobook_secs = audiobook_count = 0
                tv_bytes = tv_secs = tv_count = 0
                mv_bytes = mv_secs = mv_count = 0
                for t in all_tracks:
                    mt = t.media_type
                    if mt & 0x04:  # Podcast (including video podcast)
                        podcast_bytes += t.size
                        podcast_secs += t.length // 1000
                        podcast_count += 1
                    elif mt & 0x08:  # Audiobook
                        audiobook_bytes += t.size
                        audiobook_secs += t.length // 1000
                        audiobook_count += 1
                    elif mt & 0x40:  # TV Show
                        tv_bytes += t.size
                        tv_secs += t.length // 1000
                        tv_count += 1
                    elif mt & 0x20:  # Music Video
                        mv_bytes += t.size
                        mv_secs += t.length // 1000
                        mv_count += 1
                    elif mt & 0x02:  # Movie/Video (generic)
                        video_bytes += t.size
                        video_secs += t.length // 1000
                        video_count += 1
                    else:  # Music/Audio
                        music_bytes += t.size
                        music_secs += t.length // 1000
                        music_count += 1
                try:
                    protect_from_itunes(
                        self.ipod_path,
                        track_count=music_count,
                        total_music_bytes=music_bytes,
                        total_music_seconds=music_secs,
                        video_tracks=video_count,
                        video_bytes=video_bytes,
                        video_seconds=video_secs,
                        podcast_tracks=podcast_count,
                        podcast_bytes=podcast_bytes,
                        podcast_seconds=podcast_secs,
                        audiobook_tracks=audiobook_count,
                        audiobook_bytes=audiobook_bytes,
                        audiobook_seconds=audiobook_secs,
                        tv_show_tracks=tv_count,
                        tv_show_bytes=tv_bytes,
                        tv_show_seconds=tv_secs,
                        music_video_tracks=mv_count,
                        music_video_bytes=mv_bytes,
                        music_video_seconds=mv_secs,
                    )
                except Exception as e:
                    # Non-fatal — database is already written + mapping saved
                    logger.warning("iTunesPrefs protection failed (non-fatal): %s", e)

                # ── Delete Play Counts file ─────────────────────────────
                # The iPod firmware creates this file to record play/skip/
                # rating deltas since the last sync.  Now that we've merged
                # the deltas into the new iTunesDB, it must be deleted so
                # the iPod creates a fresh one.  (Matches libgpod's
                # playcounts_reset() behaviour.)
                self._delete_playcounts_file()

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
                file_path = item.ipod_track.get("Location") or item.ipod_track.get("location")
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
            # Defensive check - should never fail as we pre-filtered items
            if item.pc_track is None:
                logger.error(f"_do_copy called with None pc_track for {item.description}")
                return (item, False, None, False)
            source_path = Path(item.pc_track.path)
            need_transcode = needs_transcoding(source_path)

            # Build a transcode progress callback that emits UI updates
            tc_progress: Optional[Callable[[float], None]] = None
            if progress_callback and need_transcode:
                filename = source_path.name

                def _make_tc_cb(_fn: str) -> Callable[[float], None]:
                    def _cb(frac: float) -> None:
                        pct = int(frac * 100)
                        progress_callback(SyncProgress(
                            "transcode", pct, 100, message=f"Transcoding {_fn} \u2014 {pct}%",
                        ))
                    return _cb

                tc_progress = _make_tc_cb(filename)

            success, ipod_path, was_transcoded = self._copy_to_ipod(
                source_path, need_transcode, fingerprint=item.fingerprint,
                aac_bitrate=aac_bitrate,
                transcode_progress=tc_progress,
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
                except _OutOfSpaceError as e:
                    logger.error(str(e))
                    result.errors.append(("storage", str(e)))
                    result.success = False
                    for f in future_to_idx:
                        f.cancel()
                    return
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
                    elif field_name == "track_total":
                        track.total_tracks = pc_value if pc_value else 0
                    elif field_name == "disc_number":
                        track.disc_number = pc_value if pc_value else 0
                    elif field_name == "disc_total":
                        track.total_discs = pc_value if pc_value else 1
                    elif field_name == "composer":
                        track.composer = pc_value
                    elif field_name == "comment":
                        track.comment = pc_value
                    elif field_name == "grouping":
                        track.grouping = pc_value
                    elif field_name == "bpm":
                        track.bpm = pc_value if pc_value else 0
                    elif field_name == "compilation":
                        track.compilation = bool(pc_value)
                    elif field_name == "explicit_flag":
                        track.explicit_flag = pc_value if pc_value else 0
                    # Sort fields
                    elif field_name == "sort_name":
                        track.sort_name = pc_value
                    elif field_name == "sort_artist":
                        track.sort_artist = pc_value
                    elif field_name == "sort_album":
                        track.sort_album = pc_value
                    elif field_name == "sort_album_artist":
                        track.sort_album_artist = pc_value
                    elif field_name == "sort_composer":
                        track.sort_composer = pc_value
                    elif field_name == "sort_show":
                        track.sort_show = pc_value
                    # Video/TV show fields
                    elif field_name == "show_name":
                        track.show_name = pc_value
                    elif field_name == "season_number":
                        track.season_number = pc_value if pc_value else 0
                    elif field_name == "episode_number":
                        track.episode_number = pc_value if pc_value else 0
                    elif field_name == "description":
                        track.description = pc_value
                    elif field_name == "episode_id":
                        track.episode_id = pc_value
                    elif field_name == "network_name":
                        track.network_name = pc_value
                    elif field_name == "sound_check":
                        track.sound_check = pc_value if pc_value else 0
                    elif field_name == "subtitle":
                        track.subtitle = pc_value
                    elif field_name == "category":
                        track.category = pc_value
                    elif field_name == "podcast_url":
                        track.podcast_enclosure_url = pc_value
                    elif field_name == "lyrics":
                        track.lyrics = pc_value
                    elif field_name == "sort_show":
                        track.sort_show = pc_value
                    # ── iPod-only flags (from GUI edits) ──────────────
                    elif field_name == "skipWhenShuffling":
                        track.skip_when_shuffling = bool(pc_value)
                    elif field_name == "rememberPosition":
                        track.remember_position = bool(pc_value)
                    elif field_name == "gaplessTrackFlag":
                        track.gapless_track_flag = pc_value if pc_value else 0
                    elif field_name == "gaplessAlbumFlag":
                        track.gapless_album_flag = pc_value if pc_value else 0
                    elif field_name == "checked":
                        track.checked = pc_value if pc_value else 0
                    elif field_name == "playedMark":
                        track.played_mark = pc_value if pc_value else 0
                    elif field_name == "volume":
                        track.volume = pc_value if pc_value else 0
                    elif field_name == "startTime":
                        track.start_time = pc_value if pc_value else 0
                    elif field_name == "stopTime":
                        track.stop_time = pc_value if pc_value else 0

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
            # Defensive check - should never fail as we pre-filtered items
            if item.pc_track is None:
                logger.error(f"_do_copy called with None pc_track for {item.description}")
                return (item, False, None, False)
            source_path = Path(item.pc_track.path)
            need_transcode = needs_transcoding(source_path)

            # Build a transcode progress callback that emits UI updates
            tc_progress: Optional[Callable[[float], None]] = None
            if progress_callback and need_transcode:
                filename = source_path.name

                def _make_tc_cb(_fn: str) -> Callable[[float], None]:
                    def _cb(frac: float) -> None:
                        pct = int(frac * 100)
                        progress_callback(SyncProgress(
                            "transcode", pct, 100, message=f"Transcoding {_fn} \u2014 {pct}%",
                        ))
                    return _cb

                tc_progress = _make_tc_cb(filename)

            success, ipod_path, was_transcoded = self._copy_to_ipod(
                source_path, need_transcode, fingerprint=item.fingerprint,
                aac_bitrate=aac_bitrate,
                transcode_progress=tc_progress,
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
                except _OutOfSpaceError as e:
                    logger.error(str(e))
                    result.errors.append(("storage", str(e)))
                    result.success = False
                    for f in future_to_idx:
                        f.cancel()
                    return
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

            # Play/skip counts are already correct in tracks_by_dbid:
            #   _read_existing_database() merged the Play Counts file into
            #   the parsed track dicts (playCount += delta, skipCount += delta).
            #   _track_dict_to_info() then copied the cumulative values into
            #   TrackInfo.play_count / .skip_count.
            #
            # The mhit_writer writes these cumulative values to disk.
            # After the database is written, the Play Counts file is deleted
            # (see _delete_playcounts_file), so the iPod creates a fresh one.
            #
            # No manual adjustments to tracks_by_dbid are needed here.

            # Write play/skip count deltas back to PC file metadata (only if user opted in)
            if write_back_to_pc and item.pc_track and (item.play_count_delta or item.skip_count_delta):
                self._write_playcount_to_pc(
                    item.pc_track.path,
                    item.play_count_delta or 0,
                    item.skip_count_delta or 0,
                )
            logger.debug(f"Play count sync: {item.description} +{item.play_count_delta} plays, +{item.skip_count_delta} skips")
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
        """Get next music folder (F00-Fxx) using round-robin. Thread-safe.

        The number of Fxx directories varies by device (3-50); defaults to
        20 (most common value) if device capabilities are unknown.
        """
        # Determine music_dirs from device capabilities
        music_dirs = 20  # most common default across all non-Classic models
        try:
            from device_info import get_current_device
            from ipod_models import capabilities_for_family_gen
            dev = get_current_device()
            if dev and dev.model_family and dev.generation:
                caps = capabilities_for_family_gen(dev.model_family, dev.generation)
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
        aac_bitrate: int = 256,
        transcode_progress: Optional[Callable[[float], None]] = None,
    ) -> tuple[bool, Optional[Path], bool]:
        """
        Copy or transcode a file to iPod, using cache when possible.

        Args:
            transcode_progress: Optional callback receiving 0.0-1.0 fraction
                for transcode progress (forwarded to ffmpeg).

        Returns: (success, ipod_path, was_transcoded)
        """
        dest_folder = self._get_next_music_folder()
        source_size = source_path.stat().st_size

        # Safety check: abort if writing this file would leave < 30 MB free
        RESERVE_BYTES = 30 * 1024 * 1024  # 30 MB
        try:
            free = shutil.disk_usage(self.ipod_path).free
            if free - source_size < RESERVE_BYTES:
                free_mb = free / (1024 * 1024)
                raise _OutOfSpaceError(
                    f"iPod is out of space ({free_mb:.0f} MB remaining, "
                    f"30 MB reserve required). Stopping file writes."
                )
        except OSError:
            pass  # Can't check — proceed and let the copy fail naturally

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
            result = transcode(source_path, dest_folder, aac_bitrate=aac_bitrate,
                               progress_callback=transcode_progress)
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
        """Write play count and skip count deltas back to PC file metadata.

        For MP3: uses PCNT frame (play count) and TXXX:SKIP_COUNT (skip count).
        For M4A: uses freeform atoms PLAY_COUNT and SKIP_COUNT.
        For FLAC/OGG: uses PLAY_COUNT and SKIP_COUNT vorbis comments.
        """
        try:
            import mutagen  # type: ignore[import-untyped]
            from mutagen.id3._frames import PCNT, TXXX  # type: ignore[import-untyped]

            ext = Path(file_path).suffix.lower()
            audio = mutagen.File(file_path)  # type: ignore[attr-defined]
            if audio is None:
                return False

            if ext == ".mp3":
                # PCNT frame: increment existing play count
                if play_delta:
                    existing = 0
                    if "PCNT" in audio.tags:
                        existing = audio.tags["PCNT"].count
                    audio.tags.add(PCNT(count=existing + play_delta))
                # TXXX:SKIP_COUNT — no standard ID3 frame for skip count
                if skip_delta:
                    existing_skip = 0
                    txxx_key = "TXXX:SKIP_COUNT"
                    if txxx_key in audio.tags:
                        try:
                            existing_skip = int(audio.tags[txxx_key].text[0])
                        except (ValueError, TypeError, IndexError):
                            pass
                    audio.tags.add(TXXX(encoding=3, desc="SKIP_COUNT",
                                        text=[str(existing_skip + skip_delta)]))
                audio.save()
            elif ext in (".m4a", ".m4p", ".aac"):
                from mutagen.mp4 import MP4FreeForm  # type: ignore[import-untyped]
                # Play count freeform atom
                if play_delta:
                    key = "----:com.apple.iTunes:PLAY_COUNT"
                    existing = 0
                    if key in audio.tags:
                        try:
                            existing = int(audio.tags[key][0].decode())
                        except (ValueError, TypeError, IndexError):
                            pass
                    audio.tags[key] = [MP4FreeForm(str(existing + play_delta).encode())]
                # Skip count freeform atom
                if skip_delta:
                    skip_key = "----:com.apple.iTunes:SKIP_COUNT"
                    existing_skip = 0
                    if skip_key in audio.tags:
                        try:
                            existing_skip = int(audio.tags[skip_key][0].decode())
                        except (ValueError, TypeError, IndexError):
                            pass
                    audio.tags[skip_key] = [MP4FreeForm(str(existing_skip + skip_delta).encode())]
                audio.save()
            elif ext in (".flac", ".ogg", ".opus"):
                # Vorbis comments
                if play_delta:
                    existing = 0
                    if "PLAY_COUNT" in audio.tags:
                        try:
                            existing = int(audio.tags["PLAY_COUNT"][0])
                        except (ValueError, TypeError, IndexError):
                            pass
                    audio.tags["PLAY_COUNT"] = [str(existing + play_delta)]
                if skip_delta:
                    existing_skip = 0
                    if "SKIP_COUNT" in audio.tags:
                        try:
                            existing_skip = int(audio.tags["SKIP_COUNT"][0])
                        except (ValueError, TypeError, IndexError):
                            pass
                    audio.tags["SKIP_COUNT"] = [str(existing_skip + skip_delta)]
                audio.save()

            return True
        except Exception as e:
            logger.warning(f"Could not write play/skip count to {file_path}: {e}")
            return False

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
            logger.warning(f"Could not write rating to {file_path}: {e}")
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
        itunes_dir = self.ipod_path / "iPod_Control" / "iTunes"
        for name in ("Play Counts", "iTunesStats", "PlayCounts.plist",
                     "OTGPlaylistInfo"):
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

    # ── Track Conversion ────────────────────────────────────────────────────

    def _read_existing_database(self) -> dict:
        """Read existing tracks, playlists, and smart playlists from iTunesDB.

        Also reads the Play Counts file (if present) and merges per-track
        deltas into the track dicts.  After merging:
        - ``playCount`` / ``skipCount`` are the new cumulative values
        - ``recent_playcount`` / ``recent_skipcount`` are the deltas
        - ``rating`` may be overridden if the user rated on the iPod
        """
        from iTunesDB_Parser import parse_itunesdb
        from iTunesDB_Parser.playcounts import parse_playcounts, merge_playcounts

        empty = {"tracks": [], "playlists": [], "smart_playlists": []}
        from device_info import resolve_itdb_path
        _resolved = resolve_itdb_path(str(self.ipod_path))
        itdb_path = Path(_resolved) if _resolved else self.ipod_path / "iPod_Control" / "iTunes" / "iTunesDB"
        if not itdb_path.exists():
            return empty

        try:
            result = parse_itunesdb(str(itdb_path))
            tracks = result.get("mhlt", [])

            # ── Merge Play Counts file (iPod-generated deltas) ──────────
            pc_path = self.ipod_path / "iPod_Control" / "iTunes" / "Play Counts"
            pc_entries = parse_playcounts(pc_path)
            if pc_entries is not None:
                merge_playcounts(tracks, pc_entries)
            else:
                # No Play Counts file → zero deltas for all tracks
                for t in tracks:
                    t.setdefault("recent_playcount", 0)
                    t.setdefault("recent_skipcount", 0)

            # NOTE: GUI track edits (rating, flags, etc.) are no longer
            # silently applied here.  They flow through the diff engine as
            # proper SyncItems so they appear in the sync review UI.

            # Dataset 2: regular + user playlists (mhlp)
            all_playlists = result.get("mhlp", [])
            # Deduplicate by playlistID
            seen_ids: set[int] = set()
            playlists: list[dict] = []
            for pl in all_playlists:
                pid = pl.get("playlistID", 0)
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    playlists.append(pl)

            # Dataset 5: smart playlists for browsing (mhsp)
            smart_playlists = result.get("mhsp", [])

            logger.info(
                "Parsed iPod database: %d tracks, %d playlists, %d smart playlists",
                len(tracks), len(playlists), len(smart_playlists),
            )
            return {
                "tracks": tracks,
                "playlists": playlists,
                "smart_playlists": smart_playlists,
            }
        except Exception as e:
            logger.error(f"Failed to parse iTunesDB: {e}")
            return empty

    def _track_dict_to_info(self, t: dict) -> TrackInfo:
        """Convert parsed track dict to TrackInfo for writing."""
        filetype = t.get("filetype", "MP3")
        if "AAC" in filetype or "M4A" in filetype or "Lossless" in filetype:
            filetype_code = "m4a"
        elif "Protected" in filetype:
            filetype_code = "m4p"
        elif "Audiobook" in filetype:
            filetype_code = "m4b"
        elif "WAV" in filetype:
            filetype_code = "wav"
        elif "AIFF" in filetype:
            filetype_code = "aiff"
        elif "M4V" in filetype:
            filetype_code = "m4v"
        elif "MP4" in filetype:
            filetype_code = "mp4"
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
            comment=t.get("Comment"),
            grouping=t.get("Grouping"),
            year=t.get("year", 0),
            track_number=t.get("trackNumber", 0),
            total_tracks=t.get("totalTracks", 0),
            disc_number=t.get("discNumber", 1),
            total_discs=t.get("totalDiscs", 1),
            bpm=t.get("bpm", 0),
            compilation=bool(t.get("compilation", 0)),
            skip_when_shuffling=bool(t.get("skipWhenShuffling", 0)),
            remember_position=bool(t.get("rememberPosition", 0)),
            rating=t.get("rating", 0),
            # playCount already includes the Play Counts file delta
            # (merged by merge_playcounts in _read_existing_database).
            # Do NOT add playCount2 — that was the old pre-merge approach.
            play_count=t.get("playCount", 0),
            skip_count=t.get("skipCount", 0),
            volume=t.get("volume", 0),
            start_time=t.get("startTime", 0),
            stop_time=t.get("stopTime", 0),
            sound_check=t.get("soundCheck", 0),
            bookmark_time=t.get("bookmarkTime", 0),
            checked=t.get("checked", 0),
            gapless_data=t.get("gaplessData", 0),
            gapless_track_flag=t.get("gaplessTrackFlag", 0),
            gapless_album_flag=t.get("gaplessAlbumFlag", 0),
            pregap=t.get("pregap", 0),
            postgap=t.get("postgap", 0),
            sample_count=t.get("sampleCount", 0),
            encoder_flag=t.get("encoderFlag", 0),
            explicit_flag=t.get("explicitFlag", 0),
            has_lyrics=bool(t.get("lyricsFlag", 0)),
            lyrics=t.get("Lyrics"),
            eq_setting=t.get("EQ Setting"),
            date_added=t.get("dateAdded", 0),
            date_released=t.get("dateReleased", 0),
            last_played=t.get("lastPlayed", 0),
            last_skipped=t.get("lastSkipped", 0),
            last_modified=t.get("lastModified", 0),
            dbid=t.get("dbid", 0),
            media_type=t.get("mediaType", 1),
            movie_file_flag=t.get("movieFileFlag", 0),
            season_number=t.get("seasonNumber", 0),
            episode_number=t.get("episodeNumber", 0),
            artwork_count=t.get("artworkCount", 0),
            artwork_size=t.get("artworkSize", 0),
            mhii_link=t.get("mhiiLink", 0),
            sort_artist=t.get("Sort Artist"),
            sort_name=t.get("Sort Name"),
            sort_album=t.get("Sort Album"),
            sort_album_artist=t.get("Sort Album Artist"),
            sort_composer=t.get("Sort Composer"),
            filetype_desc=t.get("filetype"),
            # Video string fields from parsed MHOD types
            show_name=t.get("Show"),
            episode_id=t.get("Episode"),
            description=t.get("Description Text"),
            subtitle=t.get("Subtitle"),
            network_name=t.get("TV Network"),
            sort_show=t.get("Sort Show"),
            show_locale=t.get("Show Locale"),
            keywords=t.get("Track Keywords"),
            # Podcast/audiobook fields from parsed track
            podcast_enclosure_url=t.get("Podcast Enclosure URL"),
            podcast_rss_url=t.get("Podcast RSS URL"),
            category=t.get("Category"),
            played_mark=t.get("playedMark", -1),
            podcast_flag=t.get("podcastFlag", 0),
            # Round-trip fields (preserved from existing iPod database)
            user_id=t.get("userID", 0),
            app_rating=t.get("appRating", 0),
            unk144=t.get("unk144", 0),
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
            # Lossless sources (.flac, .wav, .aif, .aiff) transcode to ALAC —
            # keep the source bitrate.  Lossy sources (.ogg, .opus, .wma) go
            # to AAC — use the user-configured bitrate.
            source_ext = pc_track.extension.lower().lstrip(".")
            is_lossless_source = source_ext in ("flac", "wav", "aif", "aiff")
            if filetype == "m4a" and not is_lossless_source:
                bitrate = self._aac_bitrate  # user-configured AAC bitrate
            # sample_rate is typically preserved by transcoder

        # ── Media type auto-detection ────────────────────────────────
        is_video = getattr(pc_track, "is_video", False)
        video_kind = getattr(pc_track, "video_kind", "") or ""
        is_podcast = getattr(pc_track, "is_podcast", False)
        is_audiobook = getattr(pc_track, "is_audiobook", False)
        movie_file_flag = 0
        media_type = MEDIA_TYPE_AUDIO
        podcast_flag = 0
        skip_when_shuffling = False
        remember_position = False

        if is_video:
            movie_file_flag = 1
            if is_podcast:
                media_type = MEDIA_TYPE_VIDEO_PODCAST
                podcast_flag = 1
                skip_when_shuffling = True
                remember_position = True
            elif video_kind == "tv_show":
                media_type = MEDIA_TYPE_TV_SHOW
            elif video_kind == "music_video":
                media_type = MEDIA_TYPE_MUSIC_VIDEO
            else:
                # Default to movie for generic video files
                media_type = MEDIA_TYPE_VIDEO
        elif is_podcast:
            media_type = MEDIA_TYPE_PODCAST
            podcast_flag = 1
            skip_when_shuffling = True
            remember_position = True
        elif is_audiobook:
            media_type = MEDIA_TYPE_AUDIOBOOK
            skip_when_shuffling = True
            remember_position = True

        # ── Gapless & encoder flags ──────────────────────────────────
        pregap = getattr(pc_track, "pregap", 0) or 0
        postgap = getattr(pc_track, "postgap", 0) or 0
        sample_count = getattr(pc_track, "sample_count", 0) or 0
        gapless_data = getattr(pc_track, "gapless_data", 0) or 0
        # Auto-set gapless_track_flag when we have meaningful gapless data
        gapless_track_flag = 1 if (pregap or postgap or sample_count) else 0
        # encoder_flag: set to 1 for MP3 (iPod needs this for LAME gapless)
        encoder_flag = 1 if filetype == "mp3" else 0
        # VBR detection from mutagen bitrate_mode
        vbr = getattr(pc_track, "vbr", False)

        return TrackInfo(
            title=pc_track.title or Path(pc_track.path).stem,
            location=ipod_location,
            size=file_size,
            length=pc_track.duration_ms or 0,
            filetype=filetype,
            bitrate=bitrate,
            sample_rate=sample_rate,
            vbr=vbr,
            artist=pc_track.artist,
            album=pc_track.album,
            album_artist=pc_track.album_artist,
            genre=pc_track.genre,
            composer=getattr(pc_track, "composer", None),
            comment=getattr(pc_track, "comment", None),
            grouping=getattr(pc_track, "grouping", None),
            year=pc_track.year or 0,
            track_number=pc_track.track_number or 0,
            total_tracks=getattr(pc_track, "track_total", None) or 0,
            disc_number=pc_track.disc_number or 1,
            total_discs=getattr(pc_track, "disc_total", None) or 1,
            bpm=getattr(pc_track, "bpm", None) or 0,
            rating=rating,
            play_count=getattr(pc_track, "play_count", 0) or 0,
            compilation=getattr(pc_track, "compilation", False),
            sound_check=getattr(pc_track, "sound_check", 0) or 0,
            pregap=pregap,
            postgap=postgap,
            sample_count=sample_count,
            gapless_data=gapless_data,
            gapless_track_flag=gapless_track_flag,
            encoder_flag=encoder_flag,
            explicit_flag=getattr(pc_track, "explicit_flag", 0) or 0,
            has_lyrics=getattr(pc_track, "has_lyrics", False),
            lyrics=getattr(pc_track, "lyrics", None),
            date_released=getattr(pc_track, "date_released", 0) or 0,
            subtitle=getattr(pc_track, "subtitle", None),
            sort_artist=getattr(pc_track, "sort_artist", None),
            sort_name=getattr(pc_track, "sort_name", None),
            sort_album=getattr(pc_track, "sort_album", None),
            sort_album_artist=getattr(pc_track, "sort_album_artist", None),
            sort_composer=getattr(pc_track, "sort_composer", None),
            # Video fields
            media_type=media_type,
            movie_file_flag=movie_file_flag,
            season_number=getattr(pc_track, "season_number", None) or 0,
            episode_number=getattr(pc_track, "episode_number", None) or 0,
            show_name=getattr(pc_track, "show_name", None),
            episode_id=getattr(pc_track, "episode_id", None),
            description=getattr(pc_track, "description", None),
            network_name=getattr(pc_track, "network_name", None),
            sort_show=getattr(pc_track, "sort_show", None),
            # Podcast/audiobook flags
            podcast_flag=podcast_flag,
            skip_when_shuffling=skip_when_shuffling,
            remember_position=remember_position,
            category=getattr(pc_track, "category", None),
            podcast_rss_url=getattr(pc_track, "podcast_url", None),
        )

    @staticmethod
    def _decode_raw_blob(value) -> Optional[bytes]:
        """Decode a raw MHOD blob from parsed playlist data.

        The parser stores bytes, but mhbd_parser's replace_bytes_with_base64()
        converts them to base64 strings for JSON serialization. This method
        handles both cases.
        """
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            try:
                return base64.b64decode(value)
            except Exception:
                return None
        return None

    def _build_and_evaluate_playlists(
        self,
        parsed_tracks: list[dict],
        all_track_infos: list[TrackInfo],
        parsed_playlists: list[dict],
        parsed_smart: list[dict],
    ) -> tuple[list[PlaylistInfo], list[PlaylistInfo]]:
        """Build PlaylistInfo lists and evaluate smart playlist rules.

        Playlist *definitions* (names, rules, sort orders) come from the
        existing iPod database, but smart playlist *evaluation* runs against
        the NEW track list being written — so newly added tracks are
        included and removed tracks are excluded.

        Returns (regular_playlists, smart_playlists) ready for write_itunesdb().
        """
        from .spl_evaluator import spl_update

        # Map old trackID → dbid so we can remap regular playlist items
        old_tid_to_dbid: dict[int, int] = {}
        for t in parsed_tracks:
            tid = t.get("trackID", 0)
            dbid = t.get("dbid", 0)
            if tid and dbid:
                old_tid_to_dbid[tid] = dbid

        # Set of valid dbids in the final track list
        valid_dbids: set[int] = {t.dbid for t in all_track_infos if t.dbid}

        # Convert the NEW TrackInfo list → evaluator-compatible dicts.
        # The evaluator expects parsed-track-style dicts with keys like
        # "trackID", "Title", "Artist", "rating", etc.
        eval_tracks = [self._trackinfo_to_eval_dict(t) for t in all_track_infos]

        # ── Regular playlists (dataset 2) ────────────────────────────
        playlists: list[PlaylistInfo] = []
        for pl in parsed_playlists:
            if pl.get("isMaster", False):
                continue  # master playlist is auto-generated by the writer

            # Resolve track IDs → dbids, filtering out removed tracks.
            # Also preserve per-MHIP metadata for round-trip fidelity.
            items = pl.get("items", [])
            track_ids = []
            item_meta = []
            for item in items:
                tid = item.get("trackID", 0)
                dbid = old_tid_to_dbid.get(tid, 0)
                if dbid in valid_dbids:
                    track_ids.append(dbid)
                    item_meta.append(PlaylistItemMeta(
                        podcast_group_flag=item.get("podcastGroupFlag", 0),
                        group_id=item.get("groupID", 0),
                        podcast_group_ref=item.get("podcastGroupRef", 0),
                    ))

            info = PlaylistInfo(
                name=pl.get("Title", "Untitled"),
                track_ids=track_ids,
                playlist_id=pl.get("playlistID"),
                hidden=False,
                sortorder=pl.get("sortOrder", 0),
                podcast_flag=pl.get("podcastFlag", 0),
                group_flag=pl.get("groupFlag", 0),
                raw_mhod100=self._decode_raw_blob(pl.get("rawMhod100")),
                raw_mhod102=self._decode_raw_blob(pl.get("rawMhod102")),
                item_metadata=item_meta if item_meta else None,
            )

            # Smart playlist rules (dataset 2 smart playlists)
            if pl.get("isSmartPlaylist", False):
                prefs_data = pl.get("smartPlaylistData")
                rules_data = pl.get("smartPlaylistRules")
                if prefs_data and rules_data:
                    info.smart_prefs = prefs_from_parsed(prefs_data)
                    info.smart_rules = rules_from_parsed(rules_data)

                    # Evaluate rules against the NEW track list
                    matched_dbids = spl_update(
                        info.smart_prefs, info.smart_rules, eval_tracks,
                    )
                    # Filter to valid dbids (should already be, but be safe)
                    info.track_ids = [
                        d for d in matched_dbids if d in valid_dbids
                    ]
                    logger.debug(
                        "SPL (ds2) '%s': %d tracks matched",
                        info.name, len(info.track_ids),
                    )

            playlists.append(info)

        logger.info(
            "Prepared %d user playlists for writing", len(playlists)
        )

        # ── Smart playlists (dataset 5) ──────────────────────────────
        smart_playlists: list[PlaylistInfo] = []
        for pl in parsed_smart:
            prefs_data = pl.get("smartPlaylistData")
            rules_data = pl.get("smartPlaylistRules")

            info = PlaylistInfo(
                name=pl.get("Title", "Untitled"),
                playlist_id=pl.get("playlistID"),
                hidden=bool(pl.get("type", 0)),
                sortorder=pl.get("sortOrder", 0),
                mhsd5_type=pl.get("mhsd5Type", 0),
                raw_mhod100=self._decode_raw_blob(pl.get("rawMhod100")),
                raw_mhod102=self._decode_raw_blob(pl.get("rawMhod102")),
            )

            if prefs_data and rules_data:
                info.smart_prefs = prefs_from_parsed(prefs_data)
                info.smart_rules = rules_from_parsed(rules_data)

                # Dataset 5 smart playlists: iPod evaluates these at runtime,
                # so we write 0 MHIPs.  But we still evaluate for logging.
                matched_dbids = spl_update(
                    info.smart_prefs, info.smart_rules, eval_tracks,
                )
                logger.debug(
                    "SPL (ds5) '%s': %d tracks would match (iPod evaluates at runtime)",
                    info.name, len(matched_dbids),
                )
                # track_ids stays empty — iPod firmware evaluates these

            smart_playlists.append(info)

        logger.info(
            "Prepared %d smart playlists (dataset 5) for writing",
            len(smart_playlists),
        )

        # ── Auto-generate video browsing playlists (dataset 5) ───────
        # iPods often already have these from iTunes.  Only add if missing
        # by checking mhsd5_type of existing playlists.
        existing_mhsd5_types = {sp.mhsd5_type for sp in smart_playlists}

        # Video browsing playlists: (mhsd5_type, name, media_type_bitmask)
        _VIDEO_BROWSING = [
            (2, "Movies", MEDIA_TYPE_VIDEO),
            (3, "TV Shows", MEDIA_TYPE_TV_SHOW),
            (4, "Music Videos", MEDIA_TYPE_MUSIC_VIDEO),
        ]

        # Podcast and Audiobook browsing playlists
        _MEDIA_BROWSING = [
            (5, "Podcasts", MEDIA_TYPE_PODCAST),
            (6, "Audiobooks", MEDIA_TYPE_AUDIOBOOK),
        ]

        for mhsd5, name, media_mask in _VIDEO_BROWSING + _MEDIA_BROWSING:
            if mhsd5 in existing_mhsd5_types:
                logger.debug(
                    "Browsing playlist '%s' (mhsd5_type=%d) already exists, skipping",
                    name, mhsd5,
                )
                continue

            # Build a smart playlist rule: mediaType includes <mask>
            rule = SmartPlaylistRule(
                field_id=0x3C,           # mediaType
                action_id=0x00000400,    # binary AND (includes)
                from_value=media_mask,
            )
            prefs = SmartPlaylistPrefs(
                live_update=True,
                check_rules=True,
                check_limits=False,
            )
            rules = SmartPlaylistRules(conjunction="AND", rules=[rule])

            info = PlaylistInfo(
                name=name,
                hidden=True,           # Browsing playlists are hidden
                mhsd5_type=mhsd5,
                smart_prefs=prefs,
                smart_rules=rules,
                track_ids=[],          # iPod evaluates at runtime
            )
            smart_playlists.append(info)
            logger.info(
                "Auto-generated browsing playlist '%s' (mhsd5_type=%d)",
                name, mhsd5,
            )

        return playlists, smart_playlists

    @staticmethod
    def _trackinfo_to_eval_dict(t: TrackInfo) -> dict:
        """Convert a TrackInfo to a dict the SPL evaluator can consume.

        The evaluator expects parsed-track-style dicts with keys matching
        the accessor maps in spl_evaluator.py (e.g. "Title", "Artist",
        "rating", "trackID").  We use dbid as the trackID so that
        spl_update() returns dbids directly.
        """
        d: dict = {
            # Use dbid as trackID so evaluator returns dbids
            "trackID": t.dbid,
            # String fields
            "Title": t.title or "",
            "Album": t.album or "",
            "Artist": t.artist or "",
            "Genre": t.genre or "",
            "filetype": t.filetype_desc or t.filetype or "",
            "Comment": t.comment or "",
            "Composer": t.composer or "",
            "Album Artist": t.album_artist or "",
            "Sort Title": t.sort_name or "",
            "Sort Album": t.sort_album or "",
            "Sort Artist": t.sort_artist or "",
            "Sort Album Artist": t.sort_album_artist or "",
            "Sort Composer": t.sort_composer or "",
            "Grouping": t.grouping or "",
            # Integer fields
            "bitrate": t.bitrate,
            "sampleRate": t.sample_rate,
            "year": t.year,
            "trackNumber": t.track_number,
            "size": t.size,
            "length": t.length,
            "playCount": t.play_count,
            "discNumber": t.disc_number,
            "rating": t.rating,
            "bpm": t.bpm,
            "skipCount": t.skip_count,
            # Date fields (Unix timestamps)
            "dateAdded": t.date_added,
            "lastPlayed": t.last_played,
            "lastSkipped": t.last_skipped,
            # Boolean fields
            "compilation": 1 if t.compilation else 0,
            # Binary AND fields
            "mediaType": t.media_type,
            # Checked flag (0=checked, 1=unchecked in iPod convention)
            "checked": t.checked,
            # Video fields for smart playlist evaluation
            "seasonNumber": t.season_number,
            "Show": t.show_name or "",
            "TVShow": t.show_name or "",  # alias: spl_evaluator uses "TVShow"
            "Sort TV Show": t.sort_show or "",
            # Podcast/audiobook fields for smart playlist evaluation
            "Description": t.description or "",
            "Category": t.category or "",
            "podcast": t.podcast_flag,
        }
        return d

    def _write_database(
        self,
        tracks: list[TrackInfo],
        pc_file_paths: Optional[dict] = None,
        playlists: Optional[list[PlaylistInfo]] = None,
        smart_playlists: Optional[list[PlaylistInfo]] = None,
    ) -> bool:
        """Write tracks to iTunesDB (and ArtworkDB if pc_file_paths provided).

        Automatically detects device capabilities from the centralized store
        and passes them to the writer for db_version, gapless/video filtering,
        and conditional podcast MHSD inclusion.
        """
        from iTunesDB_Writer import write_itunesdb

        logger.debug(f"ART: _write_database called with {len(tracks)} tracks, "
                     f"pc_file_paths={'None' if pc_file_paths is None else len(pc_file_paths)}")
        logger.debug(
            "DB: playlists=%s, smart_playlists=%s",
            len(playlists) if playlists else 0,
            len(smart_playlists) if smart_playlists else 0,
        )

        # Resolve capabilities once for the writer
        capabilities = None
        try:
            from device_info import get_current_device
            from ipod_models import capabilities_for_family_gen
            dev = get_current_device()
            if dev and dev.model_family and dev.generation:
                capabilities = capabilities_for_family_gen(
                    dev.model_family, dev.generation,
                )
        except Exception as exc:
            logger.debug("Could not load device capabilities: %s", exc)

        try:
            return write_itunesdb(
                str(self.ipod_path),
                tracks,
                pc_file_paths=pc_file_paths,
                playlists=playlists,
                smart_playlists=smart_playlists,
                capabilities=capabilities,
            )
        except Exception as e:
            logger.error(f"Failed to write iTunesDB: {e}")
            import traceback
            traceback.print_exc()
            return False
