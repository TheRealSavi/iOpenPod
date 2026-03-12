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
  2. Claimed-dbid filtering → prevents double-matching
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

from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum, auto
from pathlib import Path
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .pc_library import PCLibrary, PCTrack
from .audio_fingerprint import get_or_compute_fingerprint, is_fpcalc_available
from .mapping import MappingManager, MappingFile, TrackMapping
from .integrity import IntegrityReport

logger = logging.getLogger(__name__)


# ─── Enums & Data Classes ─────────────────────────────────────────────────────


class SyncAction(Enum):
    """Type of sync action needed."""

    ADD_TO_IPOD = auto()  # New track, copy to iPod
    REMOVE_FROM_IPOD = auto()  # Track not on PC, remove from iPod
    UPDATE_METADATA = auto()  # Metadata changed on PC, update iPod DB
    UPDATE_FILE = auto()  # Source file changed, re-copy/transcode
    UPDATE_ARTWORK = auto()  # Embedded art changed, re-extract
    SYNC_PLAYCOUNT = auto()  # iPod has new plays to scrobble
    SYNC_RATING = auto()  # Rating differs, last-write-wins
    NO_ACTION = auto()  # Track is in sync


@dataclass
class SyncItem:
    """A single item in the sync plan."""

    action: SyncAction
    fingerprint: Optional[str] = None

    # For ADD/UPDATE actions — the source PC track
    pc_track: Optional[PCTrack] = None

    # For REMOVE/matched actions — iPod-side info
    dbid: Optional[int] = None
    ipod_track: Optional[dict] = None

    # For UPDATE_METADATA: which fields changed  {field: (pc_val, ipod_val)}
    metadata_changes: dict = field(default_factory=dict)

    # For SYNC_PLAYCOUNT
    play_count_delta: int = 0       # iPod plays since last sync (from Play Counts file)
    skip_count_delta: int = 0       # iPod skips since last sync (from Play Counts file)

    # For SYNC_RATING — last-write-wins
    ipod_rating: int = 0  # 0-100 (stars × 20)
    pc_rating: int = 0  # 0-100 (stars × 20)
    new_rating: int = 0  # The winner
    rating_strategy: str = ""  # e.g. "ipod_wins", "pc_wins", "highest", etc.

    # For UPDATE_ARTWORK
    old_art_hash: Optional[str] = None
    new_art_hash: Optional[str] = None

    # Human-readable description
    description: str = ""


@dataclass
class StorageSummary:
    """iPod storage estimate for the sync plan."""

    bytes_to_add: int = 0
    bytes_to_remove: int = 0
    bytes_to_update: int = 0  # File updates (re-copy)

    @property
    def net_change(self) -> int:
        return self.bytes_to_add + self.bytes_to_update - self.bytes_to_remove

    def format(self) -> str:
        parts = []
        if self.bytes_to_add > 0:
            parts.append(f"+{_fmt_bytes(self.bytes_to_add)}")
        if self.bytes_to_remove > 0:
            parts.append(f"-{_fmt_bytes(self.bytes_to_remove)}")
        if self.bytes_to_update > 0:
            parts.append(f"~{_fmt_bytes(self.bytes_to_update)} re-sync")
        if parts:
            net = self.net_change
            sign = "+" if net >= 0 else "-"
            parts.append(f"(net {sign}{_fmt_bytes(abs(net))})")
        return " ".join(parts) if parts else "0 B"


@dataclass
class SyncPlan:
    """Complete sync plan with all actions needed."""

    # Grouped action lists
    to_add: list[SyncItem] = field(default_factory=list)
    to_remove: list[SyncItem] = field(default_factory=list)
    to_update_metadata: list[SyncItem] = field(default_factory=list)
    to_update_file: list[SyncItem] = field(default_factory=list)
    to_update_artwork: list[SyncItem] = field(default_factory=list)
    to_sync_playcount: list[SyncItem] = field(default_factory=list)
    to_sync_rating: list[SyncItem] = field(default_factory=list)

    # PC file paths for ALL matched tracks (dbid → absolute PC path)
    # Used by artwork writer to extract embedded art for *every* track
    matched_pc_paths: dict[int, str] = field(default_factory=dict)

    # Errors during fingerprinting
    fingerprint_errors: list[tuple[str, str]] = field(default_factory=list)

    # Fingerprint collisions that couldn't be auto-resolved
    unresolved_collisions: list[tuple[str, list[PCTrack]]] = field(default_factory=list)

    # PC duplicates: display_key → list[PCTrack] with same song AND same album
    # True duplicates only — same fingerprint + same album.
    # Same song on different albums is NOT a duplicate (greatest hits case).
    duplicates: dict[str, list[PCTrack]] = field(default_factory=dict)

    # Stale mapping entries: (fingerprint, dbid) pairs where dbid is not in iTunesDB.
    # Cleaned from mapping during execution, not shown to user.
    _stale_mapping_entries: list[tuple[str, int]] = field(default_factory=list)

    # Mapping file loaded during compute_diff — carried through to executor
    # so we don't load it twice.
    mapping: MappingFile | None = None

    # Integrity report from pre-flight check (None if not run)
    integrity_report: IntegrityReport | None = None

    # Stats
    total_pc_tracks: int = 0
    total_ipod_tracks: int = 0
    matched_tracks: int = 0

    # Playlist changes (populated by GUI before showing plan)
    playlists_to_add: list[dict] = field(default_factory=list)
    playlists_to_edit: list[dict] = field(default_factory=list)
    playlists_to_remove: list[dict] = field(default_factory=list)

    # Storage
    storage: StorageSummary = field(default_factory=StorageSummary)

    @property
    def has_changes(self) -> bool:
        return any([
            self.to_add,
            self.to_remove,
            self.to_update_metadata,
            self.to_update_file,
            self.to_update_artwork,
            self.to_sync_playcount,
            self.to_sync_rating,
            self.playlists_to_add,
            self.playlists_to_edit,
            self.playlists_to_remove,
        ])

    @property
    def has_duplicates(self) -> bool:
        return bool(self.duplicates)

    @property
    def duplicate_count(self) -> int:
        return sum(len(t) - 1 for t in self.duplicates.values())

    @property
    def summary(self) -> str:
        lines = []
        if self.to_add:
            lines.append(f"  📥 {len(self.to_add)} tracks to add ({_fmt_bytes(self.storage.bytes_to_add)})")
        if self.to_remove:
            lines.append(f"  🗑️  {len(self.to_remove)} tracks to remove ({_fmt_bytes(self.storage.bytes_to_remove)})")
        if self.to_update_file:
            lines.append(f"  🔄 {len(self.to_update_file)} tracks to re-sync ({_fmt_bytes(self.storage.bytes_to_update)})")
        if self.to_update_metadata:
            lines.append(f"  📝 {len(self.to_update_metadata)} tracks with metadata updates")
        if self.to_update_artwork:
            lines.append(f"  🎨 {len(self.to_update_artwork)} tracks with artwork updates")
        if self.to_sync_playcount:
            lines.append(f"  🎵 {len(self.to_sync_playcount)} tracks with new play counts")
        if self.to_sync_rating:
            lines.append(f"  ⭐ {len(self.to_sync_rating)} tracks with rating changes")
        if self.fingerprint_errors:
            lines.append(f"  ⚠️  {len(self.fingerprint_errors)} files could not be fingerprinted")
        if self.playlists_to_add:
            lines.append(f"  🎶 {len(self.playlists_to_add)} playlists to add")
        if self.playlists_to_edit:
            lines.append(f"  📝 {len(self.playlists_to_edit)} playlists to update")
        if self.playlists_to_remove:
            lines.append(f"  🗑️  {len(self.playlists_to_remove)} playlists to remove")
        if self.duplicates:
            lines.append(f"  ⚠️  {len(self.duplicates)} duplicate groups ({self.duplicate_count} extra files skipped)")
        if self.unresolved_collisions:
            lines.append(f"  ❓ {len(self.unresolved_collisions)} unresolved fingerprint collisions")

        # Show integrity fixes at the top if any were found
        integrity_lines = []
        if self.integrity_report and not self.integrity_report.is_clean:
            ir = self.integrity_report
            if ir.missing_files:
                integrity_lines.append(f"  🔧 {len(ir.missing_files)} DB tracks had missing files (cleaned)")
            if ir.stale_mappings:
                integrity_lines.append(f"  🔧 {len(ir.stale_mappings)} stale mapping entries (cleaned)")
            if ir.orphan_files:
                integrity_lines.append(f"  🔧 {len(ir.orphan_files)} orphan files removed from iPod")

        if not lines and not integrity_lines:
            return "✅ Everything is in sync!"

        header = f"Sync Plan ({self.matched_tracks} matched, {self.total_pc_tracks} PC, {self.total_ipod_tracks} iPod):"
        all_lines = integrity_lines + lines
        return header + "\n" + "\n".join(all_lines)


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


# ─── Engine ────────────────────────────────────────────────────────────────────


class FingerprintDiffEngine:
    """
    Computes sync differences using acoustic fingerprints.

    Usage:
        engine = FingerprintDiffEngine(pc_library, ipod_path)
        plan = engine.compute_diff(ipod_tracks)
        print(plan.summary)
    """

    def __init__(self, pc_library: PCLibrary, ipod_path: str | Path,
                 supports_video: bool = True, supports_podcast: bool = True):
        self.pc_library = pc_library
        self.ipod_path = Path(ipod_path)
        self.supports_video = supports_video
        self.supports_podcast = supports_podcast
        self.mapping_manager = MappingManager(ipod_path)

    # ── Public API ──────────────────────────────────────────────────────────

    def compute_diff(
        self,
        ipod_tracks: list[dict],
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
        write_fingerprints: bool = True,
        is_cancelled: Optional[Callable[[], bool]] = None,
        *,
        track_edits: Optional[dict[int, dict[str, tuple]]] = None,
        sync_workers: int = 0,
        rating_strategy: str = "ipod_wins",
    ) -> SyncPlan:
        """
        Compute the full sync plan.

        Args:
            ipod_tracks: Track dicts from iTunesDB parser
            progress_callback: Optional callback(stage, current, total, message)
            write_fingerprints: Store computed fingerprints in PC file metadata
            is_cancelled: Optional callable returning True when the caller
                          wants to abort early.  Checked between stages.
            track_edits: Pending GUI track edits: dbid → {field: (original, new)}.
                         When provided, in-memory track dicts are reverted to
                         originals before comparison, then edits are overlaid.
            sync_workers: Number of parallel fingerprint workers (0 = auto).
            rating_strategy: Conflict resolution for ratings: ipod_wins,
                             pc_wins, highest, lowest, average.

        Returns:
            SyncPlan
        """
        if not is_fpcalc_available():
            raise RuntimeError(
                "fpcalc not found. Install Chromaprint: https://acoustid.org/chromaprint"
            )

        plan = SyncPlan()

        # Load mapping
        if progress_callback:
            progress_callback("load_mapping", 0, 0, "Loading iPod mapping...")
        mapping = self.mapping_manager.load()

        # ===== Pre-flight: Integrity check =====
        # Validate consistency between filesystem, iTunesDB, and mapping.
        # This mutates ipod_tracks (removes entries with missing files)
        # and mapping (removes stale dbids), and deletes orphan files.
        from .integrity import check_integrity
        if progress_callback:
            progress_callback("integrity", 0, 0, "Checking iPod integrity…")
        integrity_report = check_integrity(
            self.ipod_path,
            ipod_tracks,
            mapping,
            delete_orphans=True,
            progress_callback=progress_callback,
            is_cancelled=is_cancelled,
        )
        if is_cancelled and is_cancelled():
            return plan
        if not integrity_report.is_clean:
            logger.info(integrity_report.summary)
            # Save cleaned mapping immediately so stale entries don't persist
            if integrity_report.stale_mappings:
                self.mapping_manager.save(mapping)

        plan.integrity_report = integrity_report

        # Tracks whose files are missing must be explicitly removed from the
        # iPod database.  The integrity check pulled them out of ipod_tracks
        # (so the diff engine won't try to match them), but the executor
        # re-reads the full iTunesDB from disk — so without a REMOVE action
        # they'd be written straight back.
        for ghost_track in integrity_report.missing_files:
            ghost_dbid = ghost_track.get("db_id")
            plan.to_remove.append(SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                fingerprint=None,
                dbid=ghost_dbid,
                ipod_track=ghost_track,
                description=(
                    f"File missing on iPod: "
                    f"{ghost_track.get('Artist', 'Unknown')} - "
                    f"{ghost_track.get('Title', 'Unknown')}"
                ),
            ))
            plan.storage.bytes_to_remove += ghost_track.get("size", 0)

        # Rebuild dbid lookup in case integrity check removed some tracks
        ipod_by_dbid = {}
        for track in ipod_tracks:
            dbid = track.get("db_id")
            if dbid:
                ipod_by_dbid[dbid] = track
        plan.total_ipod_tracks = len(ipod_by_dbid)

        # ── Revert GUI edits so ipod_tracks reflect the true iPod state ──
        # update_track_flags() modifies the in-memory dicts for instant UI
        # feedback, but we need the originals for accurate PC-vs-iPod comparison.
        # Edits are stored as {dbid: {key: (original, new)}} — revert to originals.
        gui_edits = track_edits or {}

        if gui_edits:
            for dbid, field_edits in gui_edits.items():
                ipod_track = ipod_by_dbid.get(dbid)
                if ipod_track is None:
                    continue
                for edit_key, (orig_val, _new_val) in field_edits.items():
                    ipod_track[edit_key] = orig_val
            logger.info("Reverted GUI edits on %d tracks for accurate diff", len(gui_edits))

        # ===== Phase 1: Scan PC & fingerprint =====
        if is_cancelled and is_cancelled():
            return plan

        if progress_callback:
            progress_callback("scan_pc", 0, 0, "Scanning PC library...")

        pc_tracks = list(self.pc_library.scan(include_video=self.supports_video))

        # Filter out podcast tracks when the device doesn't support podcasts.
        # This mirrors the include_video filter: no point syncing content the
        # iPod can't categorise.
        if not self.supports_podcast:
            pc_tracks = [t for t in pc_tracks if not t.is_podcast]

        plan.total_pc_tracks = len(pc_tracks)

        # fingerprint → list[PCTrack]  (to detect PC-side duplicates)
        pc_by_fp: dict[str, list[PCTrack]] = {}
        seen_fps: set[str] = set()

        # Parallel fingerprinting — fpcalc is a subprocess so threading
        # scales well.  Respect the user's sync_workers setting.
        import os
        _sw = sync_workers
        fp_workers = min(_sw or (os.cpu_count() or 4), 8)

        completed = 0
        completed_lock = threading.Lock()
        total = len(pc_tracks)

        def _fingerprint_one(track: PCTrack) -> tuple[PCTrack, Optional[str]]:
            fp = get_or_compute_fingerprint(track.path, write_to_file=write_fingerprints)
            return (track, fp)

        logger.info(f"Fingerprinting {total} tracks with {fp_workers} workers")

        with ThreadPoolExecutor(max_workers=fp_workers) as pool:
            futures = {pool.submit(_fingerprint_one, t): t for t in pc_tracks}

            for future in as_completed(futures):
                if is_cancelled and is_cancelled():
                    # Cancel remaining futures and bail out
                    for f in futures:
                        f.cancel()
                    return plan

                with completed_lock:
                    completed += 1
                    current = completed

                track, fp = future.result()

                if progress_callback:
                    progress_callback("fingerprint", current, total, track.filename)

                if not fp:
                    plan.fingerprint_errors.append((track.path, "Could not compute fingerprint"))
                    continue

                pc_by_fp.setdefault(fp, []).append(track)
                seen_fps.add(fp)

        # ===== Phase 2: Group by identity (fingerprint + album) =====
        # Same fingerprint + same album = true duplicate (pick one, report rest)
        # Same fingerprint + different album = independent tracks (greatest hits)

        # (fp, album_key) → list[PCTrack]
        identity_groups: dict[tuple[str, str], list[PCTrack]] = {}
        for fp, tracks in pc_by_fp.items():
            by_album: dict[str, list[PCTrack]] = {}
            for t in tracks:
                album_key = (t.album or "").strip().lower()
                by_album.setdefault(album_key, []).append(t)

            for album_key, album_tracks in by_album.items():
                identity_groups[(fp, album_key)] = album_tracks
                if len(album_tracks) > 1:
                    # True duplicates: same song, same album, multiple files
                    display_key = f"{album_tracks[0].artist or 'Unknown'}|{album_tracks[0].album or 'Unknown'}|{album_tracks[0].title or 'Unknown'}"
                    plan.duplicates[display_key] = album_tracks

        # ===== Phase 3: Match & Diff =====
        if is_cancelled and is_cancelled():
            return plan

        if progress_callback:
            progress_callback("diff", 0, 0, "Computing differences...")

        # For fingerprints with multiple album groups, we need to track which
        # mapping entries have already been claimed so each PC track gets its own.
        claimed_dbids: set[int] = set()

        for (fp, _album_key), pc_tracks_for_group in identity_groups.items():
            # Pick representative track (first one from this album group)
            pc_track = pc_tracks_for_group[0]
            mapping_entries = mapping.get_entries(fp)

            if not mapping_entries:
                # NEW TRACK: Not in mapping → Add
                plan.to_add.append(SyncItem(
                    action=SyncAction.ADD_TO_IPOD,
                    fingerprint=fp,
                    pc_track=pc_track,
                    description=f"New: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))
                plan.storage.bytes_to_add += pc_track.size
                continue

            # Filter out mapping entries already claimed by another album group
            available_entries = [e for e in mapping_entries if e.dbid not in claimed_dbids]

            if not available_entries:
                # All mapping entries for this fingerprint are claimed by other
                # album groups → this is a new album variant (greatest hits case)
                plan.to_add.append(SyncItem(
                    action=SyncAction.ADD_TO_IPOD,
                    fingerprint=fp,
                    pc_track=pc_track,
                    description=f"New (album variant): {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename} [{pc_track.album or 'Unknown'}]",
                ))
                plan.storage.bytes_to_add += pc_track.size
                continue

            # MATCHED: Resolve which mapping entry this PC track matches
            matched_entry = self._resolve_collision(pc_track, available_entries, ipod_by_dbid)

            if matched_entry is None:
                # Collision couldn't be resolved
                plan.unresolved_collisions.append((fp, pc_tracks_for_group))
                continue

            claimed_dbids.add(matched_entry.dbid)

            dbid = matched_entry.dbid
            ipod_track = ipod_by_dbid.get(dbid)

            if ipod_track is None:
                # Mapping exists but track missing from iTunesDB (stale mapping)
                logger.warning(f"Mapping for {fp} points to missing dbid {dbid}")
                plan.to_add.append(SyncItem(
                    action=SyncAction.ADD_TO_IPOD,
                    fingerprint=fp,
                    pc_track=pc_track,
                    description=f"Re-add (stale mapping): {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))
                plan.storage.bytes_to_add += pc_track.size
                continue

            plan.matched_tracks += 1

            # Record PC path for artwork extraction (all matched tracks)
            plan.matched_pc_paths[dbid] = str(pc_track.path)

            # ── Change detection ──

            # File change: size+mtime gate
            if self._source_file_changed(pc_track, matched_entry):
                plan.to_update_file.append(SyncItem(
                    action=SyncAction.UPDATE_FILE,
                    fingerprint=fp,
                    pc_track=pc_track,
                    dbid=dbid,
                    ipod_track=ipod_track,
                    description=f"File changed: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))
                plan.storage.bytes_to_update += pc_track.size

            # Metadata change
            metadata_changes = self._compare_metadata(pc_track, ipod_track)
            if metadata_changes:
                plan.to_update_metadata.append(SyncItem(
                    action=SyncAction.UPDATE_METADATA,
                    fingerprint=fp,
                    pc_track=pc_track,
                    dbid=dbid,
                    ipod_track=ipod_track,
                    metadata_changes=metadata_changes,
                    description=f"Metadata: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename} ({', '.join(metadata_changes.keys())})",
                ))

            # Artwork change: compare art_hash (covers add, change, AND removal)
            pc_art_hash = getattr(pc_track, "art_hash", None)
            mapping_art_hash = matched_entry.art_hash
            if pc_art_hash != mapping_art_hash:
                plan.to_update_artwork.append(SyncItem(
                    action=SyncAction.UPDATE_ARTWORK,
                    fingerprint=fp,
                    pc_track=pc_track,
                    dbid=dbid,
                    ipod_track=ipod_track,
                    old_art_hash=mapping_art_hash,
                    new_art_hash=pc_art_hash,
                    description=f"Art {'removed' if not pc_art_hash else 'changed'}: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))
            elif pc_art_hash and (ipod_track.get("artwork_count", 0) == 0 or ipod_track.get("artwork_id_ref", 0) == 0):
                # PC has art and mapping agrees (hash matches) but iPod
                # doesn't actually have it — previous ArtworkDB write may
                # have failed.  Emit an artwork update so it gets retried.
                plan.to_update_artwork.append(SyncItem(
                    action=SyncAction.UPDATE_ARTWORK,
                    fingerprint=fp,
                    pc_track=pc_track,
                    dbid=dbid,
                    ipod_track=ipod_track,
                    old_art_hash=None,
                    new_art_hash=pc_art_hash,
                    description=f"Art missing on iPod: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))

            # Play count: scrobble iPod deltas from Play Counts file.
            # iPod plays belong to the iPod, PC plays belong to the PC.
            # We never sync play counts between the two — we just scrobble
            # the iPod delta so the user's ListenBrainz stays up to date.
            #
            ipod_play_delta = ipod_track.get("recent_playcount", 0)
            ipod_skip_delta = ipod_track.get("recent_skipcount", 0)

            if ipod_play_delta > 0 or ipod_skip_delta > 0:
                parts = []
                if ipod_play_delta > 0:
                    parts.append(f"+{ipod_play_delta} play{'s' if ipod_play_delta != 1 else ''}")
                if ipod_skip_delta > 0:
                    parts.append(f"+{ipod_skip_delta} skip{'s' if ipod_skip_delta != 1 else ''}")
                track_name = f"{pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}"
                desc = f"{', '.join(parts)}: {track_name}"

                plan.to_sync_playcount.append(SyncItem(
                    action=SyncAction.SYNC_PLAYCOUNT,
                    fingerprint=fp,
                    pc_track=pc_track,
                    dbid=dbid,
                    ipod_track=ipod_track,
                    play_count_delta=ipod_play_delta,
                    skip_count_delta=ipod_skip_delta,
                    description=desc,
                ))

            # Rating: resolve conflicts using configured strategy
            ipod_rating = ipod_track.get("rating", 0)
            pc_rating = pc_track.rating or 0
            if ipod_rating != pc_rating and (ipod_rating > 0 or pc_rating > 0):
                strategy = rating_strategy

                if strategy == "pc_wins":
                    new_rating = pc_rating if pc_rating > 0 else ipod_rating
                elif strategy == "highest":
                    new_rating = max(ipod_rating, pc_rating)
                elif strategy == "lowest":
                    non_zero = [r for r in (ipod_rating, pc_rating) if r > 0]
                    new_rating = min(non_zero) if non_zero else 0
                elif strategy == "average":
                    avg = (ipod_rating + pc_rating) / 2
                    new_rating = round(avg / 20) * 20  # snap to nearest star step
                    new_rating = max(0, min(100, new_rating))
                else:  # ipod_wins (default)
                    new_rating = ipod_rating if ipod_rating > 0 else pc_rating

                plan.to_sync_rating.append(SyncItem(
                    action=SyncAction.SYNC_RATING,
                    fingerprint=fp,
                    pc_track=pc_track,
                    dbid=dbid,
                    ipod_track=ipod_track,
                    ipod_rating=ipod_rating,
                    pc_rating=pc_rating,
                    new_rating=new_rating,
                    rating_strategy=strategy,
                    description=f"Rating: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))

        # ===== Phase 4: Find tracks to remove =====
        if is_cancelled and is_cancelled():
            return plan

        # 4a: Fingerprints entirely absent from PC → all entries are removals
        mapping_fps = mapping.all_fingerprints()
        orphaned_fps = mapping_fps - seen_fps

        for fp in orphaned_fps:
            for entry in mapping.get_entries(fp):
                dbid = entry.dbid
                ipod_track = ipod_by_dbid.get(dbid)

                if not ipod_track:
                    plan._stale_mapping_entries.append((fp, dbid))
                    continue

                plan.to_remove.append(SyncItem(
                    action=SyncAction.REMOVE_FROM_IPOD,
                    fingerprint=fp,
                    dbid=dbid,
                    ipod_track=ipod_track,
                    description=(
                        f"Removed from PC: "
                        f"{ipod_track.get('Artist', 'Unknown')} - "
                        f"{ipod_track.get('Title', 'Unknown')}"
                    ),
                ))
                plan.storage.bytes_to_remove += ipod_track.get("size", 0)

        # 4b: Fingerprints still on PC but with unclaimed mapping entries.
        # These are album variants that were deleted (e.g., removed from
        # Greatest Hits but kept on original album).
        for fp in seen_fps & mapping_fps:
            for entry in mapping.get_entries(fp):
                if entry.dbid in claimed_dbids:
                    continue
                dbid = entry.dbid
                ipod_track = ipod_by_dbid.get(dbid)

                if not ipod_track:
                    plan._stale_mapping_entries.append((fp, dbid))
                    continue

                plan.to_remove.append(SyncItem(
                    action=SyncAction.REMOVE_FROM_IPOD,
                    fingerprint=fp,
                    dbid=dbid,
                    ipod_track=ipod_track,
                    description=(
                        f"Album variant removed: "
                        f"{ipod_track.get('Artist', 'Unknown')} - "
                        f"{ipod_track.get('Title', 'Unknown')} "
                        f"[{ipod_track.get('Album', '')}]"
                    ),
                ))
                plan.storage.bytes_to_remove += ipod_track.get("size", 0)

        # 4c: Unmapped iPod tracks — tracks in iTunesDB that have NO mapping
        # entry at all (e.g., put there by iTunes, not by iOpenPod).
        # These are invisible to 4a/4b which only iterate mapping entries.
        # Collect all dbids already accounted for by matches or removals.
        accounted_dbids = claimed_dbids.copy()
        for item in plan.to_remove:
            if item.dbid:
                accounted_dbids.add(item.dbid)
        for fp, dbid in plan._stale_mapping_entries:
            accounted_dbids.add(dbid)

        for dbid, ipod_track in ipod_by_dbid.items():
            if dbid in accounted_dbids:
                continue
            # This track exists in iTunesDB but has no mapping entry and
            # was not matched to any PC track → it should be removed.
            plan.to_remove.append(SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                fingerprint=None,
                dbid=dbid,
                ipod_track=ipod_track,
                description=(
                    f"Not in PC library: "
                    f"{ipod_track.get('Artist', 'Unknown')} - "
                    f"{ipod_track.get('Title', 'Unknown')}"
                ),
            ))
            plan.storage.bytes_to_remove += ipod_track.get("size", 0)

        # ===== Phase 5: GUI edits overlay ==============================
        # The user may have changed rating, compilation, flags, volume,
        # start/stop times etc. via the iOpenPod GUI.  These pending edits
        # are stored as (original, new) tuples in iTunesDBCache._track_edits.
        #
        # IMPORTANT: update_track_flags() modifies the in-memory track dicts
        # for instant UI feedback, so the ipod_tracks we received already
        # contain the GUI values.  We reverted them to originals at the top
        # of compute_diff (before Phase 3) so the PC-vs-iPod comparison ran
        # against the true iPod state.  Now we overlay the edits.
        #
        # Edits are compared against the true iPod values (originals):
        #  - rating edits → SYNC_RATING (always wins, bypasses strategy)
        #  - METADATA_FIELDS edits → override / supplement the PC diff
        #  - iPod-only flags → emitted as UPDATE_METADATA directly
        #
        # If the same track already has a PC-driven UPDATE_METADATA item
        # from Phase 3, the GUI edit is merged into that item (GUI wins
        # for any overlapping field).

        if gui_edits:
            # Reverse lookup: iPod dict key → PC field name (for METADATA_FIELDS)
            _ipod_key_to_pc = {v: k for k, v in METADATA_FIELDS.items()}

            # Index existing UPDATE_METADATA items by dbid for merge
            meta_by_dbid: dict[int, SyncItem] = {}
            for item in plan.to_update_metadata:
                if item.dbid:
                    meta_by_dbid[item.dbid] = item

            # Index existing SYNC_RATING items by dbid to replace them
            rating_by_dbid: dict[int, int] = {}
            for idx, item in enumerate(plan.to_sync_rating):
                if item.dbid:
                    rating_by_dbid[item.dbid] = idx

            for dbid, field_edits in gui_edits.items():
                ipod_track = ipod_by_dbid.get(dbid)
                if ipod_track is None:
                    continue  # track no longer on iPod

                track_name = (
                    f"{ipod_track.get('Artist', 'Unknown')} - "
                    f"{ipod_track.get('Title', 'Unknown')}"
                )

                for edit_key, (orig_val, new_val) in field_edits.items():
                    # orig_val is the true iPod value (before GUI edit)
                    if orig_val == new_val:
                        continue  # no actual change

                    # ── Rating ──
                    if edit_key == "rating":
                        if dbid in rating_by_dbid:
                            # Replace existing rating item — GUI always wins
                            idx = rating_by_dbid[dbid]
                            plan.to_sync_rating[idx].new_rating = new_val
                            plan.to_sync_rating[idx].pc_rating = new_val
                            plan.to_sync_rating[idx].description = (
                                f"Rating (edited in iOpenPod): {track_name}"
                            )
                        else:
                            plan.to_sync_rating.append(SyncItem(
                                action=SyncAction.SYNC_RATING,
                                dbid=dbid,
                                ipod_track=ipod_track,
                                ipod_rating=orig_val if orig_val else 0,
                                pc_rating=new_val,
                                new_rating=new_val,
                                description=f"Rating (edited in iOpenPod): {track_name}",
                            ))
                        continue

                    # ── Metadata field or iPod-only flag ──
                    # Use the PC field name if available, otherwise the
                    # raw track-dict key (for iPod-only fields).
                    pc_field = _ipod_key_to_pc.get(edit_key, edit_key)

                    if dbid in meta_by_dbid:
                        # Merge into existing UPDATE_METADATA item
                        meta_by_dbid[dbid].metadata_changes[pc_field] = (
                            new_val, orig_val
                        )
                        # Update description
                        fields_str = ", ".join(
                            meta_by_dbid[dbid].metadata_changes.keys()
                        )
                        meta_by_dbid[dbid].description = (
                            f"Metadata: {track_name} ({fields_str})"
                        )
                    else:
                        new_item = SyncItem(
                            action=SyncAction.UPDATE_METADATA,
                            dbid=dbid,
                            ipod_track=ipod_track,
                            metadata_changes={pc_field: (new_val, orig_val)},
                            description=f"Metadata (edited in iOpenPod): {track_name} ({pc_field})",
                        )
                        plan.to_update_metadata.append(new_item)
                        meta_by_dbid[dbid] = new_item

            logger.info("GUI edit overlay: processed %d edited tracks", len(gui_edits))

        # ── Restore GUI edits on in-memory track dicts ──────────────────
        # Phase 3 ran against the true iPod values; now put the GUI values
        # back so the UI still shows what the user set.
        if gui_edits:
            for dbid, field_edits in gui_edits.items():
                ipod_track = ipod_by_dbid.get(dbid)
                if ipod_track is None:
                    continue
                for edit_key, (_orig_val, new_val) in field_edits.items():
                    ipod_track[edit_key] = new_val

        # Attach the mapping so the executor can reuse it instead of
        # loading from disk a second time.
        plan.mapping = mapping

        return plan

    # ── Private Helpers ─────────────────────────────────────────────────────

    def _resolve_collision(
        self,
        pc_track: PCTrack,
        entries: list[TrackMapping],
        ipod_by_dbid: Optional[dict] = None,
    ) -> Optional[TrackMapping]:
        """
        Resolve a fingerprint collision (multiple mapping entries).

        Disambiguation cascade:
          1. Single entry → trivial
          2. source_path_hint matches → unique
          3. Album name matches exactly one entry → unique
          4. Album + track number matches → unique
          5. Otherwise → None (unresolved)
        """
        if len(entries) == 1:
            return entries[0]

        # Try source_path_hint
        for entry in entries:
            if entry.source_path_hint and entry.source_path_hint == pc_track.relative_path:
                return entry

        # Try album-based disambiguation using iPod track data
        if ipod_by_dbid:
            pc_album = (pc_track.album or "").strip().lower()
            pc_track_num = pc_track.track_number or 0

            # Step 3: Match by album name
            album_matches = []
            for entry in entries:
                ipod_track = ipod_by_dbid.get(entry.dbid)
                if ipod_track:
                    ipod_album = (ipod_track.get("Album", "") or "").strip().lower()
                    if ipod_album == pc_album:
                        album_matches.append(entry)

            if len(album_matches) == 1:
                return album_matches[0]

            # Step 4: Narrow further by track number if album matched multiple
            if len(album_matches) > 1 and pc_track_num > 0:
                tn_matches = []
                for entry in album_matches:
                    ipod_track = ipod_by_dbid.get(entry.dbid)
                    if ipod_track and ipod_track.get("track_number", 0) == pc_track_num:
                        tn_matches.append(entry)
                if len(tn_matches) == 1:
                    return tn_matches[0]

        logger.warning(
            f"Unresolved collision: {len(entries)} entries for same fingerprint, "
            f"could not disambiguate for '{pc_track.relative_path}'"
        )
        return None

    def _compare_metadata(self, pc_track: PCTrack, ipod_track: dict) -> dict:
        """Compare metadata between PC and iPod track.

        Returns: {field: (pc_value, ipod_value)} for fields that differ.
        """
        changes = {}
        for pc_field, ipod_field in METADATA_FIELDS.items():
            pc_value = getattr(pc_track, pc_field, None)
            ipod_value = ipod_track.get(ipod_field)

            # Normalize None → ""
            if pc_value is None:
                pc_value = ""
            if ipod_value is None:
                ipod_value = ""

            # Treat "" and 0 as equivalent "empty" values
            if pc_value == "" and ipod_value == 0:
                continue
            if pc_value == 0 and ipod_value == "":
                continue

            # If PC is empty and iPod has the writer default for this field,
            # it's not a real change — the writer just filled in the default.
            if pc_field in _WRITER_DEFAULTS:
                writer_default = _WRITER_DEFAULTS[pc_field]
                pc_empty = pc_value in ("", 0, None)
                if pc_empty and ipod_value == writer_default:
                    continue

            if isinstance(pc_value, str) and isinstance(ipod_value, str):
                if pc_value.strip() != ipod_value.strip():
                    changes[pc_field] = (pc_value, ipod_value)
            elif pc_value != ipod_value:
                changes[pc_field] = (pc_value, ipod_value)

        return changes

    def _source_file_changed(self, pc_track: PCTrack, mapping: TrackMapping) -> bool:
        """Check if the source file has changed since last sync.

        Uses size+mtime as a fast gate.
        """
        # Significant size change (>1% or >10 KB)
        size_diff = abs(pc_track.size - mapping.source_size)
        size_pct = size_diff / max(mapping.source_size, 1)

        if size_diff > 10_240 and size_pct > 0.01:
            return True

        # mtime changed AND size changed (rules out metadata-only tag edits)
        if pc_track.mtime != mapping.source_mtime and size_diff > 0:
            return True

        return False


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _fmt_bytes(val: int) -> str:
    """Format bytes as human-readable string."""
    v = float(abs(val))
    for unit in ["B", "KB", "MB", "GB"]:
        if v < 1024:
            return f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} TB"
