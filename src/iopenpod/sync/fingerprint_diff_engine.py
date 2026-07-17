"""
Fingerprint-Based Diff Engine - Computes sync plan using acoustic fingerprints.

Uses Chromaprint acoustic fingerprints for reliable track identification:
- Same song at different quality/format = same fingerprint
- Metadata changes don't affect fingerprint
- Only audio content changes create new fingerprint

Identity model: (fingerprint, album) — same song on different albums
(e.g., original album vs Greatest Hits) syncs as separate iPod tracks.
True duplicates (same fingerprint AND same album) are deduplicated silently.

Handles fingerprint collisions (same song on multiple albums) via disambiguation:
  1. source_path_hint matches → unique
  2. Claimed-db_track_id filtering → prevents double-matching
  3. Unresolved → surfaced to user

Change detection uses size+mtime as a fast gate:
  - If neither changed → skip (nothing to do)
  - If mtime changed → compare format+bitrate+sample_rate+duration for
    quality change vs metadata-only change.

Artwork change detection via art_hash (MD5 of embedded image bytes):
  - art_hash changed → to_update_artwork

Rating strategy: last-write-wins (NOT average).
Play counts: additive (iPod→PC).
"""

import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from iopenpod.itunesdb_shared.constants import MEDIA_TYPE_PODCAST

from .audio_fingerprint import (
    get_or_compute_fingerprint_with_status,
    is_fpcalc_available,
)
from .contracts import SyncAction, SyncItem, SyncPlan
from .existing_track_matcher import score_pc_to_ipod_track
from .ipod_track_paths import existing_ipod_track_file_path
from .mapping import MappingFile, MappingManager, TrackMapping
from .pc_library import PCLibrary, PCTrack
from .photos import (
    PCPhotoLibrary,
    PhotoEditState,
    build_photo_sync_plan,
    read_photo_db,
    scan_pc_photos,
)
from .planning_stages import scan_source_libraries
from .source_identity import source_content_hash
from .sync_playlist_files import normalize_sync_playlist_path
from .track_identity import SyncTrackIdentityState, build_fingerprint_identity_plan
from .transcoder import TranscodeOptions, TranscodePlan, resolve_transcode_plan

logger = logging.getLogger(__name__)

_MP4_CONTAINER_EXTS = {".m4a", ".m4b", ".mp4", ".m4v", ".mov"}


def _fingerprint_worker_count(sync_workers: int, tracks: list[PCTrack]) -> int:
    """Keep video decoding serial so large media cannot saturate the machine."""
    requested = max(1, min(sync_workers or (os.cpu_count() or 4), 8))
    if any(track.is_video for track in tracks):
        return 1
    return requested


# ─── Storage Estimation ───────────────────────────────────────────────────────

def estimate_transcode_size(
    pc_track: PCTrack,
    options: TranscodeOptions | None = None,
) -> int:
    """Estimate the size of a file after transcode, based on metadata and settings.

    For files that don't need transcoding (native COPY), returns the actual file size.
    For transcoded files (AAC/ALAC/VIDEO), estimates based on duration and codec bitrate
    from the shared transcode plan.

    Returns the estimated bytes on the iPod after transcode.
    """
    plan, estimated_size = resolve_track_transcode_plan(pc_track, options)
    return estimated_size


def resolve_track_transcode_plan(
    pc_track: PCTrack,
    options: TranscodeOptions | None = None,
) -> tuple[TranscodePlan, int]:
    """Resolve transfer policy and estimated output size for a PC track."""
    plan = resolve_transcode_plan(pc_track.path, options=options)
    estimated_size = plan.estimate_output_size(
        source_size=pc_track.size,
        duration_ms=pc_track.duration_ms,
    )
    return plan, estimated_size


# ─── Metadata Comparison ──────────────────────────────────────────────────────

# PC field name → iPod track dict key
METADATA_FIELDS: dict[str, str] = {
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "Album Artist",
    "genre": "Genre",
    "year": "year",
    "track_number": "track_number",
    "track_total": "total_tracks",
    "disc_number": "disc_number",
    "disc_total": "total_discs",
    "composer": "Composer",
    "comment": "Comment",
    "grouping": "Grouping",
    "eq_setting": "eq_setting",
    "bpm": "bpm",
    "compilation": "compilation_flag",
    "explicit_flag": "explicit_flag",
    # Sort fields
    "sort_name": "Sort Title",
    "sort_artist": "Sort Artist",
    "sort_album": "Sort Album",
    "sort_album_artist": "Sort Album Artist",
    "sort_composer": "Sort Composer",
    "sort_show": "Sort Show",
    # Video/TV show fields
    "show_name": "Show",
    "season_number": "season_number",
    "episode_number": "episode_number",
    "description": "Description Text",
    "episode_id": "Episode",
    "network_name": "TV Network",
    # Podcast / extra string fields
    "category": "Category",
    "subtitle": "Subtitle",
    "podcast_url": "Podcast RSS URL",
    "podcast_enclosure_url": "Podcast Enclosure URL",
    "lyrics": "Lyrics",
    # Volume normalization
    "sound_check": "sound_check",

    # Dates
    "date_released": "date_released",
}

# Writer defaults for fields where "empty" on PC becomes a non-zero value
# on iPod.  When PC is empty/None/0 and iPod has the writer default, that's
# not a real change — the writer just filled it in.  Prevents false-positive
# metadata diffs on every sync.
_WRITER_DEFAULTS: dict[str, int | str] = {
    "disc_number": 1,   # _pc_track_to_info: disc_number or 1
    "disc_total": 1,    # _pc_track_to_info: disc_total or 1
}

# Fields where a falsy/absent PC value must NOT overwrite a truthy iPod value.
# Compilation and Sound Check are only authoritative when explicitly present;
# absent tags often scan as 0 and should not strip iPod-side values.
_PC_ABSENT_PRESERVES_IPOD: frozenset[str] = frozenset({"compilation", "sound_check"})

# Scanner defaults are not real tags.  They should not demote better metadata
# already on the iPod, including folder-derived placeholders from a previous
# write.  Real user-provided values still win normally.
_PC_DEFAULT_TEXT_BY_FIELD: dict[str, tuple[str, ...]] = {
    "title": ("unknown", "unknown title"),
    "artist": ("unknown artist",),
    "album": ("unknown album",),
    "album_artist": ("unknown artist", "unknown album artist"),
    "genre": ("unknown genre",),
}

# NOTE: media_type is intentionally NOT in METADATA_FIELDS to prevent it from
# being compared or updated during UPDATE_METADATA operations.  The media_type
# (video category: music video vs movie vs TV show vs audio) is determined once
# at ADD time and never changed afterward, even if the file's metadata tags
# (stik atom) change or are missing on subsequent syncs.


# ─── Engine ────────────────────────────────────────────────────────────────────


class FingerprintDiffEngine:
    """
    Computes sync differences using acoustic fingerprints.

    Usage:
        engine = FingerprintDiffEngine(pc_library, ipod_path)
        plan = engine.compute_diff(ipod_tracks)
        print(plan.summary)
    """

    def __init__(
        self,
        pc_library: PCLibrary,
        ipod_path: str | Path,
        supports_video: bool = True,
        supports_podcast: bool = True,
        supports_photo: bool = True,
        fpcalc_path: str = "",
        photo_sync_settings: dict[str, bool] | None = None,
        transcode_options: TranscodeOptions | None = None,
    ):
        self.pc_library = pc_library
        self.ipod_path = Path(ipod_path)
        self.supports_video = supports_video
        self.supports_podcast = supports_podcast
        self.supports_photo = supports_photo
        self.fpcalc_path = fpcalc_path
        self.photo_sync_settings = photo_sync_settings
        self.transcode_options = transcode_options or TranscodeOptions()
        self.mapping_manager = MappingManager(ipod_path)

    # ── Public API ──────────────────────────────────────────────────────────

    def compute_diff(
        self,
        ipod_tracks: list[dict],
        progress_callback: Callable[[str, int, int, str], None] | None = None,
        write_fingerprints: bool = True,
        is_cancelled: Callable[[], bool] | None = None,
        *,
        track_edits: dict[int, dict[str, tuple]] | None = None,
        photo_edits: PhotoEditState | None = None,
        sync_workers: int = 0,
        rating_strategy: str = "ipod_wins",
        allowed_paths: frozenset[str] | None = None,
        selected_playlist_paths: frozenset[str] | None = None,
        existing_playlists: list[dict] | None = None,
    ) -> SyncPlan:
        """
        Compute the full sync plan.

        Args:
            ipod_tracks: Track dicts from iTunesDB parser
            progress_callback: Optional callback(stage, current, total, message)
            write_fingerprints: Store computed fingerprints in PC file metadata
            is_cancelled: Optional callable returning True when the caller
                          wants to abort early.  Checked between stages.
            track_edits: Pending GUI track edits: db_track_id → {field: (original, new)}.
                         When provided, in-memory track dicts are reverted to
                         originals before comparison, then edits are overlaid.
            sync_workers: Number of parallel fingerprint workers (0 = auto).
            rating_strategy: Conflict resolution for ratings: ipod_wins,
                             pc_wins, highest, lowest, average.
            selected_playlist_paths: In selective mode, playlist source files
                                     eligible for managed add/update. Managed
                                     removals still compare against every
                                     discovered playlist file.
            existing_playlists: Parsed iPod playlist rows used to plan managed
                                media-folder playlist-file add/edit/remove.

        Returns:
            SyncPlan
        """
        if not is_fpcalc_available(self.fpcalc_path):
            raise RuntimeError(
                "fpcalc not found. Install Chromaprint: https://acoustid.org/chromaprint"
            )

        plan = SyncPlan()

        # Load mapping
        mapping_file_exists = self.mapping_manager.exists()
        if progress_callback:
            progress_callback("load_mapping", 0, 0, "Loading iPod mapping...")
        mapping = self.mapping_manager.load()

        # ===== Pre-flight: Integrity check =====
        # Validate consistency between filesystem, iTunesDB, and mapping.
        # Integrity inspection is read-only; this planner applies the report
        # only to its private in-memory working state and schedules guarded
        # persistence/deletion for execution.
        from .integrity import check_integrity
        if progress_callback:
            progress_callback("integrity", 0, 0, "Checking iPod integrity…")
        integrity_report = check_integrity(
            self.ipod_path,
            ipod_tracks,
            mapping,
            delete_orphans=False,
            progress_callback=progress_callback,
            is_cancelled=is_cancelled,
        )
        mapping_source_was_corrupt = bool(
            getattr(mapping, "source_was_corrupt", False)
        )
        integrity_report.mapping_rebuild_required = mapping_source_was_corrupt
        if is_cancelled and is_cancelled():
            return plan
        integrity_errors = list(getattr(integrity_report, "errors", ()) or ())
        if integrity_errors:
            examples = "; ".join(integrity_errors[:3])
            raise RuntimeError(
                "Could not safely inspect the iPod filesystem before sync: "
                f"{examples}"
            )
        if not integrity_report.is_clean:
            logger.info(integrity_report.summary)

        plan.integrity_report = integrity_report
        plan._mapping_requires_persistence = mapping_source_was_corrupt

        # Build the diff against a clean private view.  The source list and
        # on-device mapping file remain untouched until guarded execution.
        missing_track_objects = {id(track) for track in integrity_report.missing_files}
        if missing_track_objects:
            ipod_tracks[:] = [
                track for track in ipod_tracks if id(track) not in missing_track_objects
            ]
        for fingerprint, db_track_id in integrity_report.stale_mappings:
            mapping.remove_track(fingerprint, db_track_id=db_track_id)
            plan._stale_mapping_entries.append((fingerprint, db_track_id))
            plan._mapping_requires_persistence = True

        # Tracks whose files are missing must be explicitly removed from the
        # iPod database.  The integrity check pulled them out of ipod_tracks
        # (so the diff engine won't try to match them), but the executor
        # re-reads the full iTunesDB from disk — so without a REMOVE action
        # they'd be written straight back.
        for ghost_track in integrity_report.missing_files:
            ghost_db_track_id = ghost_track.get("db_track_id", ghost_track.get("db_id"))
            plan._integrity_removals.append(SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                fingerprint=None,
                db_track_id=ghost_db_track_id,
                ipod_track=ghost_track,
                description=(
                    f"File missing on iPod: "
                    f"{ghost_track.get('Artist', 'Unknown')} - "
                    f"{ghost_track.get('Title', 'Unknown')}"
                ),
            ))

        # Rebuild db_track_id lookup in case integrity check removed some tracks
        ipod_by_db_track_id = {}
        for track in ipod_tracks:
            db_track_id = track.get("db_track_id", track.get("db_id"))
            if db_track_id:
                ipod_by_db_track_id[db_track_id] = track
        plan.total_ipod_tracks = len(ipod_by_db_track_id)

        # ── Revert GUI edits so ipod_tracks reflect the true iPod state ──
        # update_track_flags() modifies the in-memory dicts for instant UI
        # feedback, but we need the originals for accurate PC-vs-iPod comparison.
        # Edits are stored as {db_track_id: {key: (original, new)}} — revert to originals.
        gui_edits = track_edits or {}

        if gui_edits:
            for db_track_id, field_edits in gui_edits.items():
                ipod_track = ipod_by_db_track_id.get(db_track_id)
                if ipod_track is None:
                    continue
                for edit_key, (orig_val, _new_val) in field_edits.items():
                    ipod_track[edit_key] = orig_val
            logger.info("Reverted GUI edits on %d tracks for accurate diff", len(gui_edits))

        # ===== Phase 1: Scan PC & playlist-file references =====
        source_scan = scan_source_libraries(
            self.pc_library,
            supports_video=self.supports_video,
            supports_podcast=self.supports_podcast,
            sync_workers=sync_workers,
            allowed_paths=allowed_paths,
            selected_playlist_paths=selected_playlist_paths,
            progress_callback=progress_callback,
            is_cancelled=is_cancelled,
        )
        if source_scan.cancelled:
            return plan

        pc_tracks = list(source_scan.pc_tracks)
        playlist_discovery = source_scan.playlist_discovery
        selected_playlist_source_keys = source_scan.selected_playlist_source_keys
        playlist_extra_source_keys = source_scan.playlist_extra_source_keys

        plan.total_pc_tracks = len(pc_tracks)

        # fingerprint → list[PCTrack]  (to detect PC-side duplicates)
        pc_by_fp: dict[str, list[PCTrack]] = {}
        seen_fps: set[str] = set()

        # Parallel fingerprinting — fpcalc is a subprocess so threading
        # scales well.  Respect the user's sync_workers setting.
        fp_workers = _fingerprint_worker_count(sync_workers, pc_tracks)

        completed = 0
        completed_lock = threading.Lock()
        total = len(pc_tracks)

        fingerprint_counts = {
            "cache": 0,
            "tag": 0,
            "computed": 0,
            "failed": 0,
        }
        fingerprint_failure_samples: list[str] = []

        def _fingerprint_one(track: PCTrack) -> tuple[PCTrack, str | None, str]:
            track_source_key = normalize_sync_playlist_path(track.path)
            fp, status = get_or_compute_fingerprint_with_status(
                track.path,
                fpcalc_path=self.fpcalc_path,
                write_to_file=(
                    write_fingerprints
                    and track_source_key not in playlist_extra_source_keys
                ),
            )
            return (track, fp, status)

        logger.info(f"Fingerprinting {total} tracks with {fp_workers} workers")

        with ThreadPoolExecutor(max_workers=fp_workers) as pool:
            futures = {pool.submit(_fingerprint_one, t): t for t in pc_tracks}

            for future in as_completed(futures):
                if is_cancelled and is_cancelled():
                    # Cancel remaining futures and bail out
                    for f in futures:
                        f.cancel()
                    # Save partial fingerprint progress
                    from iopenpod.sync.audio_fingerprint import FingerprintCache
                    FingerprintCache.get_instance().save()
                    return plan

                with completed_lock:
                    completed += 1
                    current = completed

                fingerprinted_track, fp, fp_status = future.result()
                fingerprint_counts[fp_status] = fingerprint_counts.get(fp_status, 0) + 1

                if progress_callback:
                    progress_callback("fingerprint", current, total, fingerprinted_track.filename)

                if not fp:
                    plan.fingerprint_errors.append((fingerprinted_track.path, "Could not compute fingerprint"))
                    if len(fingerprint_failure_samples) < 5:
                        fingerprint_failure_samples.append(fingerprinted_track.path)
                    continue

                pc_by_fp.setdefault(fp, []).append(fingerprinted_track)
                seen_fps.add(fp)

        # Persist the fingerprint cache so the next sync is fast
        from iopenpod.sync.audio_fingerprint import FingerprintCache
        FingerprintCache.get_instance().save()

        summary = (
            "Fingerprinting complete: "
            f"{total} tracks, "
            f"{fingerprint_counts.get('cache', 0)} cache hits, "
            f"{fingerprint_counts.get('tag', 0)} tag reads, "
            f"{fingerprint_counts.get('computed', 0)} computed, "
            f"{fingerprint_counts.get('failed', 0)} failed"
        )
        if fingerprint_failure_samples:
            summary += "; examples: " + ", ".join(fingerprint_failure_samples)
        if fingerprint_counts.get("failed", 0):
            logger.warning(summary)
        else:
            logger.info(summary)

        # Bootstrap unmapped iPod tracks:
        # Fingerprint any iPod tracks that are not yet represented in mapping
        # and seed entries for those that match the PC library.
        bootstrap_protected_db_track_ids: set[int] = set()
        mapped_db_track_ids = mapping.all_db_track_ids()
        unmapped_db_count = sum(
            1
            for db_track_id, ipod_track in ipod_by_db_track_id.items()
            if (
                db_track_id not in mapped_db_track_ids
                and not (ipod_track.get("media_type", 0) & MEDIA_TYPE_PODCAST)
            )
        )

        logger.info(
            "Bootstrap precheck: mapping_exists=%s, mapped_db_track_ids=%d, unmapped_ipod_tracks=%d",
            mapping_file_exists,
            len(mapped_db_track_ids),
            unmapped_db_count,
        )

        if unmapped_db_count > 0:
            if progress_callback:
                progress_callback(
                    "bootstrap_mapping",
                    0,
                    unmapped_db_count,
                    f"Bootstrapping {unmapped_db_count} unmapped iPod tracks...",
                )

            (
                boot_added,
                boot_scanned,
                bootstrap_protected_db_track_ids,
            ) = self._bootstrap_mapping_from_existing_ipod_tracks(
                mapping,
                ipod_by_db_track_id,
                pc_by_fp,
                progress_callback=progress_callback,
                is_cancelled=is_cancelled,
            )

            if boot_added > 0:
                plan._mapping_requires_persistence = True
                logger.info(
                    "Bootstrap seeded %d in-memory mapping entries from %d "
                    "unmapped iPod tracks; guarded execution will persist them",
                    boot_added,
                    boot_scanned,
                )
            else:
                logger.info(
                    "Bootstrap scanned %d unmapped iPod tracks and found 0 PC matches",
                    boot_scanned,
                )
        elif not mapping_file_exists:
            logger.info(
                "No mapping reconciliation was needed during preflight; iOpenPod.json remains absent",
            )

        # ===== Phase 2: Group by identity (fingerprint + album) =====
        # Same fingerprint + same album = true duplicate (pick one, report rest)
        # Same fingerprint + different album = independent tracks (greatest hits)
        identity_plan = build_fingerprint_identity_plan(pc_by_fp)
        for display_key, duplicate_tracks in identity_plan.duplicates.items():
            plan.duplicates[display_key] = list(duplicate_tracks)

        represented_by_aggregate, detached_from_aggregate, claimed_aggregate_db_ids = (
            self._plan_chaptered_aggregate_updates(
                plan,
                mapping,
                pc_by_fp,
                ipod_by_db_track_id,
                seen_fps,
            )
        )

        # ===== Phase 3: Match & Diff =====
        if is_cancelled and is_cancelled():
            return plan

        if progress_callback:
            progress_callback("diff", 0, 0, "Computing differences...")

        # For fingerprints with multiple album groups, we need to track which
        # mapping entries have already been claimed so each PC track gets its own.
        track_identity = SyncTrackIdentityState()
        ipod_path_lookup = (
            self._ipod_track_file_path_lookup(ipod_by_db_track_id)
            if playlist_extra_source_keys
            else {}
        )
        ipod_fingerprint_index: dict[str, list[tuple[int, dict, Path]]] | None = None

        def _get_ipod_fingerprint_index() -> dict[str, list[tuple[int, dict, Path]]]:
            nonlocal ipod_fingerprint_index
            if ipod_fingerprint_index is None:
                ipod_fingerprint_index = self._ipod_track_fingerprint_index(
                    ipod_path_lookup,
                )
            return ipod_fingerprint_index

        def _record_playlist_existing_match(
            pc_track: PCTrack,
            db_track_id: int,
        ) -> None:
            track_identity.claim(db_track_id)
            bootstrap_protected_db_track_ids.add(db_track_id)
            plan.matched_tracks += 1
            plan.matched_pc_paths[db_track_id] = str(pc_track.path)
            track_identity.record_matched_source(pc_track.path, db_track_id)

        sorted_groups = identity_plan.sorted_groups_for_matching(
            mapping=mapping,
            ipod_by_db_track_id=ipod_by_db_track_id,
        )

        for (fp, _album_key), pc_tracks_for_group in sorted_groups:
            # Pick representative track (first one from this album group)
            pc_track = pc_tracks_for_group[0]
            track_identity.record_duplicate_group_aliases(pc_tracks_for_group)
            if fp in represented_by_aggregate and fp not in detached_from_aggregate:
                aggregate_db_track_id = represented_by_aggregate[fp].db_track_id
                track_identity.claim(aggregate_db_track_id)
                plan.matched_tracks += 1
                continue

            playlist_existing_db_track_id = (
                self._playlist_existing_db_track_id(
                    pc_track,
                    fp,
                    ipod_path_lookup=ipod_path_lookup,
                    ipod_fingerprint_index_getter=_get_ipod_fingerprint_index,
                )
                if normalize_sync_playlist_path(pc_track.path) in playlist_extra_source_keys
                else 0
            )
            if playlist_existing_db_track_id:
                _record_playlist_existing_match(
                    pc_track,
                    playlist_existing_db_track_id,
                )
                continue

            mapping_entries = mapping.get_entries(fp)

            if not mapping_entries:
                # NEW TRACK: Not in mapping → Add
                transcode_plan, estimated_size = resolve_track_transcode_plan(
                    pc_track,
                    self.transcode_options,
                )
                plan.to_add.append(SyncItem(
                    action=SyncAction.ADD_TO_IPOD,
                    fingerprint=fp,
                    pc_track=pc_track,
                    estimated_size=estimated_size,
                    transcode_plan=transcode_plan,
                    description=f"New: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))
                plan.storage.bytes_to_add += estimated_size
                continue

            # Filter out mapping entries already claimed by another album group
            available_entries = [
                e for e in mapping_entries
                if not track_identity.is_claimed(e.db_track_id)
            ]

            if not available_entries:
                # All mapping entries for this fingerprint are claimed by other
                # album groups → this is a new album variant (greatest hits case)
                transcode_plan, estimated_size = resolve_track_transcode_plan(
                    pc_track,
                    self.transcode_options,
                )
                plan.to_add.append(SyncItem(
                    action=SyncAction.ADD_TO_IPOD,
                    fingerprint=fp,
                    pc_track=pc_track,
                    estimated_size=estimated_size,
                    transcode_plan=transcode_plan,
                    description=f"New (album variant): {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename} [{pc_track.album or 'Unknown'}]",
                ))
                plan.storage.bytes_to_add += estimated_size
                continue

            # MATCHED: Resolve which mapping entry this PC track matches
            matched_entry = self._resolve_collision(pc_track, available_entries, ipod_by_db_track_id)

            if matched_entry is None:
                # Collision couldn't be resolved
                plan.unresolved_collisions.append((fp, list(pc_tracks_for_group)))
                continue

            track_identity.claim(matched_entry.db_track_id)

            db_track_id = matched_entry.db_track_id
            ipod_track = ipod_by_db_track_id.get(db_track_id)

            if ipod_track is None:
                # Mapping exists but track missing from iTunesDB (stale mapping)
                logger.warning(f"Mapping for {fp} points to missing db_track_id {db_track_id}")
                transcode_plan, estimated_size = resolve_track_transcode_plan(
                    pc_track,
                    self.transcode_options,
                )
                plan.to_add.append(SyncItem(
                    action=SyncAction.ADD_TO_IPOD,
                    fingerprint=fp,
                    pc_track=pc_track,
                    estimated_size=estimated_size,
                    transcode_plan=transcode_plan,
                    description=f"Re-add (stale mapping): {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))
                plan.storage.bytes_to_add += estimated_size
                continue

            plan.matched_tracks += 1

            # Record PC path for artwork extraction (all matched tracks)
            plan.matched_pc_paths[db_track_id] = str(pc_track.path)
            track_identity.record_matched_source(pc_track.path, db_track_id)

            self._plan_matched_track_changes(
                plan,
                fingerprint=fp,
                pc_track=pc_track,
                matched_entry=matched_entry,
                db_track_id=db_track_id,
                ipod_track=ipod_track,
                rating_strategy=rating_strategy,
            )

        # ===== Phase 4: Find tracks to remove =====
        if is_cancelled and is_cancelled():
            return plan

        self._plan_removed_tracks(
            plan,
            mapping=mapping,
            seen_fps=seen_fps,
            ipod_by_db_track_id=ipod_by_db_track_id,
            track_identity=track_identity,
            claimed_aggregate_db_ids=claimed_aggregate_db_ids,
            bootstrap_protected_db_track_ids=bootstrap_protected_db_track_ids,
        )

        # ===== Phase 5: GUI edits overlay ==============================
        self._apply_gui_edit_overlay(
            plan,
            ipod_by_db_track_id=ipod_by_db_track_id,
            gui_edits=gui_edits,
        )
        self._restore_gui_edit_values(
            ipod_by_db_track_id=ipod_by_db_track_id,
            gui_edits=gui_edits,
        )

        self._plan_sync_playlists(
            plan,
            playlist_discovery=playlist_discovery,
            existing_playlists=existing_playlists,
            pc_tracks=pc_tracks,
            ipod_tracks=ipod_tracks,
            track_identity=track_identity,
            selected_playlist_source_keys=selected_playlist_source_keys,
        )

        if self._plan_photos(
            plan,
            allowed_paths=allowed_paths,
            photo_edits=photo_edits,
            sync_workers=sync_workers,
            progress_callback=progress_callback,
            is_cancelled=is_cancelled,
        ):
            return plan

        # Attach the mapping so the executor can reuse it instead of
        # loading from disk a second time.
        if plan._stale_mapping_entries:
            plan._mapping_requires_persistence = True
        plan.mapping = mapping

        return plan

    # ── Private Helpers ─────────────────────────────────────────────────────

    def _resolve_collision(
        self,
        pc_track: PCTrack,
        entries: list[TrackMapping],
        ipod_by_db_track_id: dict | None = None,
    ) -> TrackMapping | None:
        """
        Resolve a fingerprint collision (multiple mapping entries).

        Disambiguation cascade:
          1. source_path_hint matches → unique
          2. Album name matches exactly one entry → unique
          3. Album + track number matches → unique
          4. Single entry, no album data available → accept on faith
          5. Otherwise → None (unresolved)

        Phase 3 sorts identity groups so matching-album groups process first,
        ensuring this function sees the right PC track before a non-matching
        group can claim the entry via the single-entry fallback.
        """
        # Try source_path_hint (works for any entry count including 1)
        for entry in entries:
            if entry.source_path_hint and entry.source_path_hint == pc_track.relative_path:
                return entry

        # Score-based resolution against iPod-side metadata.
        if ipod_by_db_track_id:
            scored: list[tuple[int, int, TrackMapping]] = []
            for entry in entries:
                ipod_track = ipod_by_db_track_id.get(entry.db_track_id)
                if not ipod_track:
                    continue
                score = self._score_pc_to_ipod_track(pc_track, ipod_track)
                scored.append((score, entry.db_track_id, entry))

            if scored:
                scored.sort(key=lambda x: (-x[0], x[1]))
                if len(scored) > 1 and scored[0][0] == scored[1][0]:
                    logger.info(
                        "Collision tie for '%s' (%d entries, score=%d); selecting lowest db_track_id",
                        pc_track.relative_path,
                        len(scored),
                        scored[0][0],
                    )
                return scored[0][2]

        # Single entry with no album data to verify — accept it on faith.
        # (No ipod_by_db_track_id, or ipod track missing from DB.)
        if len(entries) == 1:
            return entries[0]

        # Last resort: deterministic selection instead of unresolved None.
        entries_sorted = sorted(entries, key=lambda e: e.db_track_id)
        logger.info(
            "Deterministic fallback for '%s' (%d entries) using lowest db_track_id",
            pc_track.relative_path,
            len(entries_sorted),
        )
        return entries_sorted[0] if entries_sorted else None

    def _bootstrap_mapping_from_existing_ipod_tracks(
        self,
        mapping: MappingFile,
        ipod_by_db_track_id: dict[int, dict],
        pc_by_fp: dict[str, list[PCTrack]],
        *,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, int, set[int]]:
        """Seed mapping entries by fingerprinting unmapped iPod tracks.

        Used for first sync and for repairing partial/legacy mappings. It
        fingerprints iPod files without writing tags back to the device, then
        links confident fingerprint matches to PC tracks.

        Returns:
            (entries_added, tracks_scanned, protected_db_track_ids)
        """
        existing_db_track_ids = mapping.all_db_track_ids()
        bootstrap_candidates: list[tuple[int, dict]] = []
        protected_db_track_ids: set[int] = set()
        claimed_pc_paths_by_fp: dict[str, set[str]] = {}

        for db_track_id, ipod_track in ipod_by_db_track_id.items():
            if db_track_id in existing_db_track_ids:
                continue
            # Podcast tracks are managed by PodcastManager and are excluded
            # from normal PC-folder matching/removal logic.
            if ipod_track.get("media_type", 0) & MEDIA_TYPE_PODCAST:
                continue
            bootstrap_candidates.append((db_track_id, ipod_track))

        total = len(bootstrap_candidates)
        if total == 0:
            return 0, 0, protected_db_track_ids

        added = 0
        skipped_no_path = 0
        skipped_no_fp = 0
        skipped_no_pc_match = 0
        sample_no_match_fp: str | None = None
        for index, (db_track_id, ipod_track) in enumerate(bootstrap_candidates, start=1):
            if is_cancelled and is_cancelled():
                break

            if progress_callback:
                label = ipod_track.get("Title") or ipod_track.get("Location") or str(db_track_id)
                progress_callback("bootstrap_mapping", index, total, str(label))

            ipod_path = self._ipod_track_file_path(ipod_track)
            if ipod_path is None:
                skipped_no_path += 1
                continue

            fp, _fingerprint_status = get_or_compute_fingerprint_with_status(
                ipod_path,
                fpcalc_path=self.fpcalc_path,
                write_to_file=False,
            )
            if not fp:
                skipped_no_fp += 1
                continue

            pc_candidates = pc_by_fp.get(fp)
            if not pc_candidates:
                skipped_no_pc_match += 1
                if sample_no_match_fp is None:
                    sample_no_match_fp = fp[:120]
                continue
            # Protect any iPod track whose fingerprint exists on PC from
            # first-sync removals, even when exact disambiguation is ambiguous.
            protected_db_track_ids.add(db_track_id)

            used_paths = claimed_pc_paths_by_fp.setdefault(fp, set())

            pc_track = self._select_bootstrap_pc_candidate(
                ipod_track,
                pc_candidates,
                used_paths=used_paths,
            )
            if pc_track is None:
                continue
            used_paths.add(pc_track.relative_path)

            source_size, source_mtime = self._current_pc_track_stat(pc_track)
            source_ext = Path(pc_track.path).suffix.lstrip(".").lower()
            ipod_ext = ipod_path.suffix.lstrip(".").lower()
            try:
                source_hash = source_content_hash(pc_track.path)
            except OSError:
                source_hash = None
            mapping.add_track(
                fingerprint=fp,
                db_track_id=db_track_id,
                source_format=source_ext,
                ipod_format=ipod_ext,
                source_size=source_size,
                source_mtime=source_mtime,
                was_transcoded=(source_ext != ipod_ext),
                source_path_hint=pc_track.relative_path,
                art_hash=pc_track.art_hash,
                source_hash=source_hash,
            )
            added += 1

        if progress_callback:
            progress_callback(
                "bootstrap_mapping",
                total,
                total,
                f"Bootstrap matched {added}/{total} unmapped iPod tracks",
            )

        logger.info(
            "Bootstrap summary: scanned=%d matched=%d skipped_no_path=%d skipped_no_fingerprint=%d skipped_no_pc_match=%d",
            total,
            added,
            skipped_no_path,
            skipped_no_fp,
            skipped_no_pc_match,
        )
        if sample_no_match_fp:
            logger.info("Bootstrap sample unmatched fingerprint prefix: %s", sample_no_match_fp)

        return added, total, protected_db_track_ids

    def _ipod_track_file_path(self, ipod_track: dict) -> Path | None:
        """Resolve a track Location field to an on-disk path on the iPod."""

        return existing_ipod_track_file_path(self.ipod_path, ipod_track)

    def _ipod_track_file_path_lookup(
        self,
        ipod_by_db_track_id: dict[int, dict],
    ) -> dict[str, tuple[int, dict, Path]]:
        """Build a normalized on-device file path lookup for iPod tracks."""

        lookup: dict[str, tuple[int, dict, Path]] = {}
        for db_track_id, ipod_track in ipod_by_db_track_id.items():
            ipod_path = self._ipod_track_file_path(ipod_track)
            if ipod_path is None:
                continue
            lookup[normalize_sync_playlist_path(ipod_path)] = (
                db_track_id,
                ipod_track,
                ipod_path,
            )
        return lookup

    def _playlist_existing_db_track_id(
        self,
        pc_track: PCTrack,
        fingerprint: str,
        *,
        ipod_path_lookup: dict[str, tuple[int, dict, Path]],
        ipod_fingerprint_index_getter: Callable[
            [],
            dict[str, list[tuple[int, dict, Path]]],
        ],
    ) -> int:
        """Resolve a playlist-only iPod file reference to an existing track.

        A direct iPod path is used only to find the likely candidate device
        row. The fingerprint comparison is the identity check that prevents a
        re-add. If the playlist path is not an iPod file path, fall back to a
        fingerprint index of existing device files.
        """

        source_key = normalize_sync_playlist_path(pc_track.path)
        match = ipod_path_lookup.get(source_key)
        if match is not None:
            db_track_id, _ipod_track, ipod_path = match
            ipod_fingerprint, _fingerprint_status = (
                get_or_compute_fingerprint_with_status(
                    ipod_path,
                    fpcalc_path=self.fpcalc_path,
                    write_to_file=False,
                )
            )
            if not ipod_fingerprint:
                return 0
            if ipod_fingerprint == fingerprint:
                return db_track_id
            logger.warning(
                "Playlist-referenced iPod file %s did not match the existing device fingerprint",
                ipod_path,
            )
            return 0

        candidates = ipod_fingerprint_index_getter().get(fingerprint, [])
        if not candidates:
            return 0

        if len(candidates) == 1:
            return candidates[0][0]

        scored = [
            (
                self._score_pc_to_ipod_track(pc_track, ipod_track),
                db_track_id,
            )
            for db_track_id, ipod_track, _ipod_path in candidates
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][1]

    def _ipod_track_fingerprint_index(
        self,
        ipod_path_lookup: dict[str, tuple[int, dict, Path]],
    ) -> dict[str, list[tuple[int, dict, Path]]]:
        """Fingerprint existing iPod files for playlist-only source matching."""

        index: dict[str, list[tuple[int, dict, Path]]] = {}
        seen_paths: set[str] = set()
        for db_track_id, ipod_track, ipod_path in ipod_path_lookup.values():
            path_key = normalize_sync_playlist_path(ipod_path)
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            fingerprint, _fingerprint_status = (
                get_or_compute_fingerprint_with_status(
                    ipod_path,
                    fpcalc_path=self.fpcalc_path,
                    write_to_file=False,
                )
            )
            if fingerprint:
                index.setdefault(fingerprint, []).append((
                    db_track_id,
                    ipod_track,
                    ipod_path,
                ))
        return index

    def _select_bootstrap_pc_candidate(
        self,
        ipod_track: dict,
        pc_candidates: list[PCTrack],
        *,
        used_paths: set[str] | None = None,
    ) -> PCTrack | None:
        """Pick one PC candidate for a matched iPod fingerprint.

        Uses score-based disambiguation and deterministic tie-breaking.
        If prior picks exist for this fingerprint, prefer unclaimed paths.
        """
        if not pc_candidates:
            return None

        pool = pc_candidates
        if used_paths:
            unclaimed = [t for t in pc_candidates if t.relative_path not in used_paths]
            if unclaimed:
                pool = unclaimed

        if len(pool) == 1:
            return pool[0]

        scored = [
            (
                self._score_pc_to_ipod_track(pc_track, ipod_track),
                (pc_track.path or "").lower(),
                pc_track,
            )
            for pc_track in pool
        ]
        scored.sort(key=lambda x: (-x[0], x[1]))

        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            logger.info(
                "Bootstrap tie for iPod track '%s' (score=%d); selecting lexicographically first full path",
                ipod_track.get("Title", "?"),
                scored[0][0],
            )

        return scored[0][2]

    def _score_pc_to_ipod_track(self, pc_track: PCTrack, ipod_track: dict) -> int:
        """Score how well a PC track matches an iPod track's metadata."""
        return score_pc_to_ipod_track(pc_track, ipod_track)

    @staticmethod
    def _album_key_for_pc_track(pc_track: PCTrack) -> str:
        """Return the aggregate membership key for a PC track."""
        return str(pc_track.album or "").strip().lower()

    @staticmethod
    def _track_dict_from_pc_track(pc_track: PCTrack, index: int) -> dict:
        """Build the album conversion track dict shape from a PCTrack."""
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

    def _contained_source_from_pc_track(
        self,
        pc_track: PCTrack,
        fingerprint: str,
        chapter: dict,
        index: int,
    ) -> dict:
        source_size, source_mtime = self._current_pc_track_stat(pc_track)
        source_hash = None
        try:
            source_hash = source_content_hash(pc_track.path)
        except OSError:
            pass
        return {
            "fingerprint": fingerprint,
            "source_path_hint": str(pc_track.path),
            "source_size": source_size,
            "source_mtime": source_mtime,
            "source_hash": source_hash,
            "album_key": self._album_key_for_pc_track(pc_track),
            "title": str(pc_track.title or ""),
            "artist": str(pc_track.artist or ""),
            "album": str(pc_track.album or ""),
            "disc_number": int(pc_track.disc_number or 1),
            "track_number": int(pc_track.track_number or index),
            "startpos": int(chapter.get("startpos") or 0),
            "endpos": int(chapter.get("endpos") or 0),
        }

    def _source_identity_changed(
        self,
        pc_track: PCTrack,
        source_meta: dict,
        *,
        fingerprint_unchanged: bool = False,
    ) -> bool:
        """Return whether a contained source needs the aggregate file rebuilt."""
        try:
            mapped_size = int(source_meta.get("source_size") or 0)
        except (TypeError, ValueError):
            mapped_size = 0
        try:
            mapped_mtime = float(source_meta.get("source_mtime") or 0)
        except (TypeError, ValueError):
            mapped_mtime = 0

        current_size, current_mtime = self._current_pc_track_stat(pc_track)
        if mapped_size == current_size and mapped_mtime == current_mtime:
            return False
        if not mapped_size and not mapped_mtime:
            return False
        mapped_hash = str(source_meta.get("source_hash") or "").strip()
        if mapped_hash:
            if fingerprint_unchanged and not mapped_hash.startswith("mp4-mdat-sha256:"):
                return False
            try:
                current_hash = source_content_hash(pc_track.path)
            except OSError:
                current_hash = None
            if current_hash:
                return current_hash != mapped_hash
        if fingerprint_unchanged:
            return False
        return True

    def _plan_chaptered_aggregate_updates(
        self,
        plan: SyncPlan,
        mapping: MappingFile,
        pc_by_fp: dict[str, list[PCTrack]],
        ipod_by_db_track_id: dict[int, dict],
        seen_fps: set[str],
    ) -> tuple[dict[str, TrackMapping], set[str], set[int]]:
        """Plan updates for chaptered-album tracks that contain source tracks."""
        from .album_chapters import build_chapter_timeline

        represented: dict[str, TrackMapping] = {}
        detached: set[str] = set()
        claimed_db_track_ids: set[int] = set()

        for aggregate_fp, entry in mapping.aggregate_entries():
            if entry.aggregate_kind != "chaptered_album":
                continue
            db_track_id = entry.db_track_id
            ipod_track = ipod_by_db_track_id.get(db_track_id)
            if not ipod_track:
                continue

            source_rows = list(entry.contains_sources or [])
            if not source_rows:
                source_rows = [
                    {"fingerprint": fp}
                    for fp in (entry.contains_fingerprints or [])
                    if fp
                ]
            if not source_rows:
                continue

            claimed_db_track_ids.add(db_track_id)
            retained: list[tuple[str, dict, PCTrack]] = []
            removed_rows: list[dict] = []
            moved_rows: list[tuple[str, dict, PCTrack]] = []
            changed_audio = False

            for row in source_rows:
                fp = str(row.get("fingerprint") or "").strip()
                if not fp:
                    continue
                pc_candidates = pc_by_fp.get(fp) or []
                if not pc_candidates:
                    removed_rows.append(row)
                    continue
                pc_track = min(pc_candidates, key=lambda t: (t.path or "").lower())

                represented[fp] = entry
                stored_album_key = str(row.get("album_key") or "").strip().lower()
                current_album_key = self._album_key_for_pc_track(pc_track)
                if stored_album_key and stored_album_key != current_album_key:
                    moved_rows.append((fp, row, pc_track))
                    detached.add(fp)
                    continue

                if self._source_identity_changed(
                    pc_track,
                    row,
                    fingerprint_unchanged=True,
                ):
                    changed_audio = True
                retained.append((fp, row, pc_track))

            if not removed_rows and not moved_rows and not retained:
                continue

            if not retained:
                if removed_rows or moved_rows:
                    plan.to_remove.append(
                        SyncItem(
                            action=SyncAction.REMOVE_FROM_IPOD,
                            fingerprint=aggregate_fp,
                            db_track_id=db_track_id,
                            ipod_track=ipod_track,
                            description=(
                                "Remove chaptered album: "
                                f"{ipod_track.get('Title') or ipod_track.get('Location') or db_track_id}"
                            ),
                            aggregate_kind="chaptered_album",
                        )
                    )
                    plan.storage.bytes_to_remove += int(ipod_track.get("size", 0) or 0)
                continue

            if len(retained) < 2 and (removed_rows or moved_rows):
                for fp, _row, _pc_track in retained:
                    detached.add(fp)
                plan.to_remove.append(
                    SyncItem(
                        action=SyncAction.REMOVE_FROM_IPOD,
                        fingerprint=aggregate_fp,
                        db_track_id=db_track_id,
                        ipod_track=ipod_track,
                        description=(
                            "Remove chaptered album: "
                            f"{ipod_track.get('Title') or ipod_track.get('Location') or db_track_id}"
                        ),
                        aggregate_kind="chaptered_album",
                    )
                )
                plan.storage.bytes_to_remove += int(ipod_track.get("size", 0) or 0)
                continue

            track_dicts = [
                self._track_dict_from_pc_track(pc_track, index)
                for index, (_fp, _row, pc_track) in enumerate(retained, start=1)
            ]
            chapters = build_chapter_timeline(track_dicts)
            new_sources = tuple(
                self._contained_source_from_pc_track(pc_track, fp, chapter, index)
                for index, ((fp, _row, pc_track), chapter) in enumerate(
                    zip(retained, chapters, strict=False),
                    start=1,
                )
            )
            new_fps = tuple(source["fingerprint"] for source in new_sources)
            retained_tracks = tuple(pc_track for _fp, _row, pc_track in retained)

            if removed_rows or moved_rows:
                removed_names = [
                    str(row.get("title") or row.get("fingerprint") or "chapter")
                    for row in removed_rows
                ] + [
                    pc_track.title or fp
                    for fp, _row, pc_track in moved_rows
                ]
                display_name = ", ".join(removed_names[:3])
                if len(removed_names) > 3:
                    display_name += f", +{len(removed_names) - 3} more"
                partial_ipod_track = dict(ipod_track)
                partial_ipod_track["size"] = 0
                plan.to_remove.append(
                    SyncItem(
                        action=SyncAction.REMOVE_FROM_IPOD,
                        fingerprint=aggregate_fp,
                        db_track_id=db_track_id,
                        ipod_track=partial_ipod_track,
                        description=f"Remove chapter from chaptered album: {display_name}",
                        aggregate_kind="chaptered_album",
                        aggregate_contains_fingerprints=new_fps,
                        aggregate_contains_sources=new_sources,
                        aggregate_rebuild_pc_tracks=retained_tracks,
                        aggregate_removed_fingerprint=str(
                            (removed_rows[0].get("fingerprint") if removed_rows else moved_rows[0][0])
                            or ""
                        ),
                    )
                )
                continue

            new_chapter_data = {"chapters": chapters}
            old_chapter_data = ipod_track.get("chapter_data") or {"chapters": []}
            if changed_audio:
                estimated_size = sum(max(0, pc_track.size) for pc_track in retained_tracks)
                plan.to_update_file.append(
                    SyncItem(
                        action=SyncAction.UPDATE_FILE,
                        fingerprint=aggregate_fp,
                        db_track_id=db_track_id,
                        ipod_track=ipod_track,
                        estimated_size=estimated_size,
                        description=(
                            "Rebuild chaptered album: "
                            f"{ipod_track.get('Title') or ipod_track.get('Location') or db_track_id}"
                        ),
                        aggregate_kind="chaptered_album",
                        aggregate_contains_fingerprints=new_fps,
                        aggregate_contains_sources=new_sources,
                        aggregate_rebuild_pc_tracks=retained_tracks,
                    )
                )
                plan.storage.bytes_to_update += estimated_size
            elif (
                self._normalized_chapter_entries(new_chapter_data)
                != self._normalized_chapter_entries(old_chapter_data)
            ):
                plan.to_update_metadata.append(
                    SyncItem(
                        action=SyncAction.UPDATE_METADATA,
                        fingerprint=aggregate_fp,
                        db_track_id=db_track_id,
                        ipod_track=ipod_track,
                        metadata_changes={
                            "chapter_data": (new_chapter_data, old_chapter_data),
                        },
                        description=(
                            "Update chapter titles: "
                            f"{ipod_track.get('Title') or ipod_track.get('Location') or db_track_id}"
                        ),
                        aggregate_kind="chaptered_album",
                        aggregate_contains_fingerprints=new_fps,
                        aggregate_contains_sources=new_sources,
                    )
                )

        return represented, detached, claimed_db_track_ids

    def _current_pc_track_stat(self, pc_track: PCTrack) -> tuple[int, float]:
        """Return current source size/mtime, falling back to scan-time values."""
        try:
            st = Path(pc_track.path).stat()
            return st.st_size, st.st_mtime
        except OSError:
            return pc_track.size, pc_track.mtime

    @staticmethod
    def _metadata_has_value(value) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return bool(value)

    @staticmethod
    def _is_pc_default_text(pc_field: str, value) -> bool:
        if not isinstance(value, str):
            return False
        text = value.strip().casefold()
        return text in _PC_DEFAULT_TEXT_BY_FIELD.get(pc_field, ())

    @staticmethod
    def _chapter_data_from_pc_track(pc_track: PCTrack) -> dict | None:
        chapters = getattr(pc_track, "chapters", None)
        if not chapters:
            return None
        return {"chapters": chapters}

    @staticmethod
    def _normalized_chapter_entries(chapter_data) -> list[tuple[int, str]]:
        if not isinstance(chapter_data, dict):
            return []
        chapters = chapter_data.get("chapters")
        if not isinstance(chapters, list):
            return []

        normalized: list[tuple[int, str]] = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            try:
                startpos = int(chapter.get("startpos") or 0)
            except (TypeError, ValueError):
                startpos = 0
            title = str(chapter.get("title") or "").strip()
            normalized.append((startpos, title))
        return normalized

    @staticmethod
    def _track_description_name(pc_track: PCTrack) -> str:
        return f"{pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}"

    @staticmethod
    def _ipod_track_name(ipod_track: dict) -> str:
        return (
            f"{ipod_track.get('Artist', 'Unknown')} - "
            f"{ipod_track.get('Title', 'Unknown')}"
        )

    @staticmethod
    def _is_podcast_ipod_track(ipod_track: dict) -> bool:
        return bool(ipod_track.get("media_type", 0) & MEDIA_TYPE_PODCAST)

    @classmethod
    def _append_removal_item(
        cls,
        plan: SyncPlan,
        *,
        fingerprint: str | None,
        db_track_id: int,
        ipod_track: dict,
        description: str,
    ) -> None:
        plan.to_remove.append(SyncItem(
            action=SyncAction.REMOVE_FROM_IPOD,
            fingerprint=fingerprint,
            db_track_id=db_track_id,
            ipod_track=ipod_track,
            description=description,
        ))
        plan.storage.bytes_to_remove += int(ipod_track.get("size", 0) or 0)

    @classmethod
    def _plan_removed_tracks(
        cls,
        plan: SyncPlan,
        *,
        mapping: MappingFile,
        seen_fps: set[str],
        ipod_by_db_track_id: dict[int, dict],
        track_identity: SyncTrackIdentityState,
        claimed_aggregate_db_ids: set[int],
        bootstrap_protected_db_track_ids: set[int],
    ) -> None:
        aggregate_mapping_fps = {
            aggregate_fp for aggregate_fp, _entry in mapping.aggregate_entries()
        }
        mapping_fps = mapping.all_fingerprints()

        cls._plan_orphaned_mapping_removals(
            plan,
            mapping=mapping,
            orphaned_fps=mapping_fps - seen_fps,
            aggregate_mapping_fps=aggregate_mapping_fps,
            ipod_by_db_track_id=ipod_by_db_track_id,
            bootstrap_protected_db_track_ids=bootstrap_protected_db_track_ids,
        )
        cls._plan_unclaimed_mapping_removals(
            plan,
            mapping=mapping,
            candidate_fps=seen_fps & mapping_fps,
            aggregate_mapping_fps=aggregate_mapping_fps,
            ipod_by_db_track_id=ipod_by_db_track_id,
            track_identity=track_identity,
            bootstrap_protected_db_track_ids=bootstrap_protected_db_track_ids,
        )
        cls._plan_unmapped_ipod_removals(
            plan,
            ipod_by_db_track_id=ipod_by_db_track_id,
            track_identity=track_identity,
            claimed_aggregate_db_ids=claimed_aggregate_db_ids,
            bootstrap_protected_db_track_ids=bootstrap_protected_db_track_ids,
        )

    @classmethod
    def _plan_orphaned_mapping_removals(
        cls,
        plan: SyncPlan,
        *,
        mapping: MappingFile,
        orphaned_fps: set[str],
        aggregate_mapping_fps: set[str],
        ipod_by_db_track_id: dict[int, dict],
        bootstrap_protected_db_track_ids: set[int],
    ) -> None:
        for fingerprint in orphaned_fps:
            if fingerprint in aggregate_mapping_fps:
                continue
            for entry in mapping.get_entries(fingerprint):
                db_track_id = entry.db_track_id
                if db_track_id in bootstrap_protected_db_track_ids:
                    continue
                ipod_track = ipod_by_db_track_id.get(db_track_id)
                if not ipod_track:
                    plan._stale_mapping_entries.append((fingerprint, db_track_id))
                    continue
                if cls._is_podcast_ipod_track(ipod_track):
                    continue
                cls._append_removal_item(
                    plan,
                    fingerprint=fingerprint,
                    db_track_id=db_track_id,
                    ipod_track=ipod_track,
                    description=f"Removed from PC: {cls._ipod_track_name(ipod_track)}",
                )

    @classmethod
    def _plan_unclaimed_mapping_removals(
        cls,
        plan: SyncPlan,
        *,
        mapping: MappingFile,
        candidate_fps: set[str],
        aggregate_mapping_fps: set[str],
        ipod_by_db_track_id: dict[int, dict],
        track_identity: SyncTrackIdentityState,
        bootstrap_protected_db_track_ids: set[int],
    ) -> None:
        for fingerprint in candidate_fps:
            if fingerprint in aggregate_mapping_fps:
                continue
            for entry in mapping.get_entries(fingerprint):
                db_track_id = entry.db_track_id
                if track_identity.is_claimed(db_track_id):
                    continue
                if db_track_id in bootstrap_protected_db_track_ids:
                    continue
                ipod_track = ipod_by_db_track_id.get(db_track_id)
                if not ipod_track:
                    plan._stale_mapping_entries.append((fingerprint, db_track_id))
                    continue
                if cls._is_podcast_ipod_track(ipod_track):
                    continue
                cls._append_removal_item(
                    plan,
                    fingerprint=fingerprint,
                    db_track_id=db_track_id,
                    ipod_track=ipod_track,
                    description=(
                        f"Album variant removed: {cls._ipod_track_name(ipod_track)} "
                        f"[{ipod_track.get('Album', '')}]"
                    ),
                )

    @classmethod
    def _plan_unmapped_ipod_removals(
        cls,
        plan: SyncPlan,
        *,
        ipod_by_db_track_id: dict[int, dict],
        track_identity: SyncTrackIdentityState,
        claimed_aggregate_db_ids: set[int],
        bootstrap_protected_db_track_ids: set[int],
    ) -> None:
        accounted_db_track_ids = set(track_identity.claimed_db_track_ids)
        accounted_db_track_ids.update(claimed_aggregate_db_ids)
        accounted_db_track_ids.update(bootstrap_protected_db_track_ids)
        for item in plan.to_remove:
            if item.db_track_id:
                accounted_db_track_ids.add(item.db_track_id)
        for _fingerprint, db_track_id in plan._stale_mapping_entries:
            accounted_db_track_ids.add(db_track_id)

        for db_track_id, ipod_track in ipod_by_db_track_id.items():
            if db_track_id in accounted_db_track_ids:
                continue
            if cls._is_podcast_ipod_track(ipod_track):
                continue
            cls._append_removal_item(
                plan,
                fingerprint=None,
                db_track_id=db_track_id,
                ipod_track=ipod_track,
                description=f"Not in PC library: {cls._ipod_track_name(ipod_track)}",
            )

    @classmethod
    def _apply_gui_edit_overlay(
        cls,
        plan: SyncPlan,
        *,
        ipod_by_db_track_id: dict[int, dict],
        gui_edits: dict[int, dict[str, tuple]],
    ) -> None:
        """Overlay pending GUI edits onto the already-computed sync plan."""

        if not gui_edits:
            return

        ipod_key_to_pc = {v: k for k, v in METADATA_FIELDS.items()}
        meta_by_db_track_id = cls._metadata_items_by_db_track_id(plan)
        rating_by_db_track_id = cls._rating_item_indexes_by_db_track_id(plan)

        for db_track_id, field_edits in gui_edits.items():
            ipod_track = ipod_by_db_track_id.get(db_track_id)
            if ipod_track is None:
                continue

            track_name = cls._ipod_track_name(ipod_track)
            for edit_key, (orig_val, new_val) in field_edits.items():
                if orig_val == new_val:
                    continue

                if edit_key == "rating":
                    cls._overlay_gui_rating_edit(
                        plan,
                        db_track_id=db_track_id,
                        ipod_track=ipod_track,
                        track_name=track_name,
                        orig_val=orig_val,
                        new_val=new_val,
                        rating_by_db_track_id=rating_by_db_track_id,
                    )
                    continue

                pc_field = ipod_key_to_pc.get(edit_key, edit_key)
                cls._overlay_gui_metadata_edit(
                    plan,
                    db_track_id=db_track_id,
                    ipod_track=ipod_track,
                    track_name=track_name,
                    pc_field=pc_field,
                    orig_val=orig_val,
                    new_val=new_val,
                    meta_by_db_track_id=meta_by_db_track_id,
                )

        logger.info("GUI edit overlay: processed %d edited tracks", len(gui_edits))

    @staticmethod
    def _metadata_items_by_db_track_id(plan: SyncPlan) -> dict[int, SyncItem]:
        return {
            item.db_track_id: item
            for item in plan.to_update_metadata
            if item.db_track_id
        }

    @staticmethod
    def _rating_item_indexes_by_db_track_id(plan: SyncPlan) -> dict[int, int]:
        return {
            item.db_track_id: idx
            for idx, item in enumerate(plan.to_sync_rating)
            if item.db_track_id
        }

    @staticmethod
    def _overlay_gui_rating_edit(
        plan: SyncPlan,
        *,
        db_track_id: int,
        ipod_track: dict,
        track_name: str,
        orig_val: Any,
        new_val: Any,
        rating_by_db_track_id: dict[int, int],
    ) -> None:
        if db_track_id in rating_by_db_track_id:
            idx = rating_by_db_track_id[db_track_id]
            plan.to_sync_rating[idx].new_rating = new_val
            plan.to_sync_rating[idx].pc_rating = new_val
            plan.to_sync_rating[idx].description = (
                f"Rating (edited in iOpenPod): {track_name}"
            )
            return

        plan.to_sync_rating.append(SyncItem(
            action=SyncAction.SYNC_RATING,
            db_track_id=db_track_id,
            ipod_track=ipod_track,
            ipod_rating=orig_val if orig_val else 0,
            pc_rating=new_val,
            new_rating=new_val,
            description=f"Rating (edited in iOpenPod): {track_name}",
        ))
        rating_by_db_track_id[db_track_id] = len(plan.to_sync_rating) - 1

    @staticmethod
    def _overlay_gui_metadata_edit(
        plan: SyncPlan,
        *,
        db_track_id: int,
        ipod_track: dict,
        track_name: str,
        pc_field: str,
        orig_val: Any,
        new_val: Any,
        meta_by_db_track_id: dict[int, SyncItem],
    ) -> None:
        if db_track_id in meta_by_db_track_id:
            meta_item = meta_by_db_track_id[db_track_id]
            meta_item.metadata_changes[pc_field] = (new_val, orig_val)
            fields_str = ", ".join(meta_item.metadata_changes.keys())
            meta_item.description = f"Metadata: {track_name} ({fields_str})"
            return

        new_item = SyncItem(
            action=SyncAction.UPDATE_METADATA,
            db_track_id=db_track_id,
            ipod_track=ipod_track,
            metadata_changes={pc_field: (new_val, orig_val)},
            description=f"Metadata (edited in iOpenPod): {track_name} ({pc_field})",
        )
        plan.to_update_metadata.append(new_item)
        meta_by_db_track_id[db_track_id] = new_item

    @staticmethod
    def _restore_gui_edit_values(
        *,
        ipod_by_db_track_id: dict[int, dict],
        gui_edits: dict[int, dict[str, tuple]],
    ) -> None:
        """Restore GUI-visible values after planning against original values."""

        for db_track_id, field_edits in gui_edits.items():
            ipod_track = ipod_by_db_track_id.get(db_track_id)
            if ipod_track is None:
                continue
            for edit_key, (_orig_val, new_val) in field_edits.items():
                ipod_track[edit_key] = new_val

    @staticmethod
    def _plan_sync_playlists(
        plan: SyncPlan,
        *,
        playlist_discovery: Any,
        existing_playlists: list[dict] | None,
        pc_tracks: list[PCTrack],
        ipod_tracks: list[dict],
        track_identity: SyncTrackIdentityState,
        selected_playlist_source_keys: frozenset[str] | None,
    ) -> None:
        if playlist_discovery is None or existing_playlists is None:
            return

        try:
            from .sync_playlist_files import normalize_sync_playlist_path
            from .sync_playlist_planner import SyncPlaylistPlanner

            valid_source_paths = {
                normalize_sync_playlist_path(track.path)
                for track in pc_tracks
            }
            pending_add_source_paths = {
                normalize_sync_playlist_path(item.pc_track.path)
                for item in plan.to_add
                if item.pc_track is not None
            }
            playlist_plan = SyncPlaylistPlanner(
                identity_index=track_identity.build_playlist_index(
                    pending_add_source_paths=pending_add_source_paths,
                    valid_source_paths=valid_source_paths,
                ),
                ipod_tracks=ipod_tracks,
            ).plan(
                playlist_discovery,
                existing_playlists,
                selected_playlist_source_paths=selected_playlist_source_keys,
            )
            plan.playlists_to_add.extend(playlist_plan.to_add)
            plan.playlists_to_edit.extend(playlist_plan.to_edit)
            plan.playlists_to_remove.extend(playlist_plan.to_remove)
            logger.info(
                "Playlist-file sync plan: %d add, %d edit, %d remove",
                len(playlist_plan.to_add),
                len(playlist_plan.to_edit),
                len(playlist_plan.to_remove),
            )
        except Exception as exc:
            logger.warning("Playlist-file sync planning failed: %s", exc)

    def _plan_photos(
        self,
        plan: SyncPlan,
        *,
        allowed_paths: frozenset[str] | None,
        photo_edits: PhotoEditState | None,
        sync_workers: int,
        progress_callback: Callable[[str, int, int, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> bool:
        """Plan photo sync actions. Returns True when cancelled mid-scan."""

        if not self.supports_photo:
            if photo_edits and photo_edits.has_changes:
                logger.info("Skipping photo sync plan: device does not support photos")
            return False

        try:
            device_photos = read_photo_db(self.ipod_path)
            if allowed_paths is None:
                if progress_callback:
                    progress_callback("scan_photos", 0, 0, "Scanning photos...")

                def _photo_progress(current: int, total: int, filename: str) -> None:
                    if progress_callback:
                        progress_callback("scan_photos", current, total, filename)

                pc_photos = scan_pc_photos(
                    self.pc_library.root_entries,
                    progress_callback=_photo_progress,
                    max_workers=min(sync_workers or (os.cpu_count() or 4), 8),
                    is_cancelled=is_cancelled,
                )
                if is_cancelled and is_cancelled():
                    return True
                plan.photo_plan = build_photo_sync_plan(
                    pc_photos,
                    device_photos,
                    photo_edits,
                    ipod_path=self.ipod_path,
                    sync_settings=self.photo_sync_settings,
                )
            elif photo_edits and photo_edits.has_changes:
                plan.photo_plan = build_photo_sync_plan(
                    PCPhotoLibrary(sync_root=str(self.pc_library.root_path)),
                    device_photos,
                    photo_edits,
                    ipod_path=self.ipod_path,
                    sync_settings=self.photo_sync_settings,
                )
        except Exception as exc:
            logger.warning("Photo sync planning failed: %s", exc)

        if plan.photo_plan is not None:
            # Include photo transfer deltas in the shared storage estimate so
            # preflight checks and sync-review +/- totals reflect full sync cost.
            plan.storage.bytes_to_add += plan.photo_plan.thumb_bytes_to_add
            plan.storage.bytes_to_remove += plan.photo_plan.thumb_bytes_to_remove

        return False

    def _plan_matched_track_changes(
        self,
        plan: SyncPlan,
        *,
        fingerprint: str,
        pc_track: PCTrack,
        matched_entry: TrackMapping,
        db_track_id: int,
        ipod_track: dict,
        rating_strategy: str,
    ) -> None:
        track_name = self._track_description_name(pc_track)

        # File change: size+mtime gate
        if self._source_file_changed(pc_track, matched_entry):
            transcode_plan, estimated_size = resolve_track_transcode_plan(
                pc_track,
                self.transcode_options,
            )
            plan.to_update_file.append(SyncItem(
                action=SyncAction.UPDATE_FILE,
                fingerprint=fingerprint,
                pc_track=pc_track,
                db_track_id=db_track_id,
                ipod_track=ipod_track,
                estimated_size=estimated_size,
                transcode_plan=transcode_plan,
                description=f"File changed: {track_name}",
            ))
            plan.storage.bytes_to_update += estimated_size

        metadata_changes = self._compare_metadata(pc_track, ipod_track)
        if metadata_changes:
            plan.to_update_metadata.append(SyncItem(
                action=SyncAction.UPDATE_METADATA,
                fingerprint=fingerprint,
                pc_track=pc_track,
                db_track_id=db_track_id,
                ipod_track=ipod_track,
                metadata_changes=metadata_changes,
                description=f"Metadata: {track_name} ({', '.join(metadata_changes.keys())})",
            ))

        # Artwork change: compare art_hash (covers add, change, AND removal)
        pc_art_hash = getattr(pc_track, "art_hash", None)
        mapping_art_hash = matched_entry.art_hash
        if pc_art_hash != mapping_art_hash:
            plan.to_update_artwork.append(SyncItem(
                action=SyncAction.UPDATE_ARTWORK,
                fingerprint=fingerprint,
                pc_track=pc_track,
                db_track_id=db_track_id,
                ipod_track=ipod_track,
                old_art_hash=mapping_art_hash,
                new_art_hash=pc_art_hash,
                description=f"Art {'removed' if not pc_art_hash else 'changed'}: {track_name}",
            ))
        elif pc_art_hash and (
            ipod_track.get("artwork_count", 0) == 0
            or ipod_track.get("artwork_id_ref", 0) == 0
        ):
            # PC has art and mapping agrees (hash matches) but iPod
            # doesn't actually have it — previous ArtworkDB write may
            # have failed.  Emit an artwork update so it gets retried.
            plan.to_update_artwork.append(SyncItem(
                action=SyncAction.UPDATE_ARTWORK,
                fingerprint=fingerprint,
                pc_track=pc_track,
                db_track_id=db_track_id,
                ipod_track=ipod_track,
                old_art_hash=None,
                new_art_hash=pc_art_hash,
                description=f"Art missing on iPod: {track_name}",
            ))

        # Play count: scrobble iPod deltas from Play Counts file.
        # iPod plays belong to the iPod, PC plays belong to the PC.
        # We never sync play counts between the two — we just scrobble
        # the iPod delta so the user's connected services stay up to date.
        #
        # Prefer the iTunesDB play_count_2 slot; fall back to the
        # Play Counts file-derived delta when present.
        ipod_play_delta = ipod_track.get("play_count_2", 0)
        if not ipod_play_delta:
            ipod_play_delta = ipod_track.get("recent_playcount", 0)
        ipod_skip_delta = ipod_track.get("recent_skipcount", 0)

        if ipod_play_delta > 0 or ipod_skip_delta > 0:
            parts = []
            if ipod_play_delta > 0:
                parts.append(f"+{ipod_play_delta} play{'s' if ipod_play_delta != 1 else ''}")
            if ipod_skip_delta > 0:
                parts.append(f"+{ipod_skip_delta} skip{'s' if ipod_skip_delta != 1 else ''}")
            desc = f"{', '.join(parts)}: {track_name}"

            plan.to_sync_playcount.append(SyncItem(
                action=SyncAction.SYNC_PLAYCOUNT,
                fingerprint=fingerprint,
                pc_track=pc_track,
                db_track_id=db_track_id,
                ipod_track=ipod_track,
                play_count_delta=ipod_play_delta,
                skip_count_delta=ipod_skip_delta,
                description=desc,
            ))

        # Rating: resolve conflicts using configured strategy
        ipod_rating = ipod_track.get("rating", 0)
        pc_rating = pc_track.rating or 0
        if ipod_rating == pc_rating or (ipod_rating <= 0 and pc_rating <= 0):
            return

        strategy = rating_strategy

        if strategy == "pc_wins":
            new_rating = pc_rating if pc_rating > 0 else ipod_rating
        elif strategy == "highest":
            new_rating = max(ipod_rating, pc_rating)
        elif strategy == "lowest":
            non_zero = [rating for rating in (ipod_rating, pc_rating) if rating > 0]
            new_rating = min(non_zero) if non_zero else 0
        elif strategy == "average":
            avg = (ipod_rating + pc_rating) / 2
            new_rating = round(avg / 20) * 20  # snap to nearest star step
            new_rating = max(0, min(100, new_rating))
        else:  # ipod_wins (default)
            new_rating = ipod_rating if ipod_rating > 0 else pc_rating

        plan.to_sync_rating.append(SyncItem(
            action=SyncAction.SYNC_RATING,
            fingerprint=fingerprint,
            pc_track=pc_track,
            db_track_id=db_track_id,
            ipod_track=ipod_track,
            ipod_rating=ipod_rating,
            pc_rating=pc_rating,
            new_rating=new_rating,
            rating_strategy=strategy,
            description=f"Rating: {track_name}",
        ))

    def _compare_metadata(self, pc_track: PCTrack, ipod_track: dict) -> dict[str, tuple[Any, Any]]:
        """Compare metadata between PC and iPod track.

        Returns: {field: (pc_value, ipod_value)} for fields that differ.
        """
        changes: dict[str, tuple[Any, Any]] = {}
        for pc_field, ipod_field in METADATA_FIELDS.items():
            pc_value = getattr(pc_track, pc_field, None)
            ipod_value = ipod_track.get(ipod_field)

            # Normalize None → ""
            if pc_value is None:
                pc_value = ""
            if ipod_value is None:
                ipod_value = ""

            # Normalize bool → int so flag fields don't display as "True"/"False"
            if isinstance(pc_value, bool):
                pc_value = int(pc_value)
            if isinstance(ipod_value, bool):
                ipod_value = int(ipod_value)

            # Treat "" and 0 as equivalent "empty" values
            if pc_value == "" and ipod_value == 0:
                continue
            if pc_value == 0 and ipod_value == "":
                continue

            # Missing/default PC metadata should not erase a better value that
            # already exists on the iPod.  This keeps a second sync from
            # replacing folder-derived names with scanner defaults.
            if self._metadata_has_value(ipod_value):
                if pc_value == "":
                    continue
                if self._is_pc_default_text(pc_field, pc_value):
                    continue

            # If PC is empty and iPod has the writer default for this field,
            # it's not a real change — the writer just filled in the default.
            if pc_field in _WRITER_DEFAULTS:
                writer_default = _WRITER_DEFAULTS[pc_field]
                pc_empty = pc_value in ("", 0, None)
                if pc_empty and ipod_value == writer_default:
                    continue

            # For fields like compilation: a falsy/absent PC value must not
            # strip a truthy iPod value.  The flag can only be promoted by an
            # explicit PC tag, never demoted by an absent one.
            if pc_field in _PC_ABSENT_PRESERVES_IPOD and not pc_value and ipod_value:
                continue

            if isinstance(pc_value, str) and isinstance(ipod_value, str):
                if pc_value.strip() != ipod_value.strip():
                    changes[pc_field] = (pc_value, ipod_value)
            elif pc_value != ipod_value:
                changes[pc_field] = (pc_value, ipod_value)

        # Video scanning reads the MP4 movie header without decoding media.
        # Repair legacy rows written with a zero duration, but do not compare
        # nonzero values because container timescale rounding can differ.
        pc_duration = int(pc_track.duration_ms or 0)
        ipod_duration = int(ipod_track.get("length") or 0)
        if pc_track.is_video and pc_duration > 0 and ipod_duration <= 0:
            changes["duration_ms"] = (pc_duration, ipod_duration)

        # Chapter timelines are iTunesDB-side metadata, not AAC/M4A-only file
        # metadata.  When the PC source exposes embedded chapters, sync them to
        # the DB for any matched audio file type; absent PC chapters do not
        # erase existing iPod-side chapter data.
        pc_chapter_data = self._chapter_data_from_pc_track(pc_track)
        if pc_chapter_data is not None:
            ipod_chapter_data = ipod_track.get("chapter_data")
            if (
                self._normalized_chapter_entries(pc_chapter_data)
                != self._normalized_chapter_entries(ipod_chapter_data)
            ):
                changes["chapter_data"] = (
                    pc_chapter_data,
                    ipod_chapter_data or {"chapters": []},
                )

        return changes

    def _source_file_changed(self, pc_track: PCTrack, mapping: TrackMapping) -> bool:
        """Check if the source file has changed since last sync.

        Uses size/mtime as a fast gate, then source content hashes when
        available.  MP4-family source files are special: tag/art edits can
        rewrite container metadata and change file size without changing the
        audio payload, so old mappings without a content hash do not treat MP4
        container churn as an audio-file replacement.
        """
        size_diff = abs(pc_track.size - mapping.source_size)
        mtime_changed = pc_track.mtime != mapping.source_mtime
        if size_diff == 0 and not mtime_changed:
            return False

        current_hash = None
        if mapping.source_hash:
            try:
                current_hash = source_content_hash(pc_track.path)
            except OSError:
                current_hash = None
            if current_hash:
                return current_hash != mapping.source_hash

        source_ext = (pc_track.extension or Path(pc_track.path).suffix).lower()
        if source_ext in _MP4_CONTAINER_EXTS:
            logger.debug(
                "Ignoring MP4-family container size/mtime change without stored source hash: %s",
                pc_track.filename,
            )
            return False

        # Significant size change (>10 KB or >1% of file size)
        size_pct = size_diff / max(mapping.source_size, 1)

        if size_diff > 10_240 or size_pct > 0.01:
            return True

        # mtime changed AND size changed (rules out metadata-only tag edits)
        if mtime_changed and size_diff > 0:
            return True

        return False
