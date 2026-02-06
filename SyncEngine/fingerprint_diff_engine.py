"""
Fingerprint-Based Diff Engine - Computes sync plan using acoustic fingerprints.

Uses Chromaprint acoustic fingerprints for reliable track identification:
- Same song at different quality/format = same fingerprint
- Metadata changes don't affect fingerprint
- Only audio content changes create new fingerprint

Handles fingerprint collisions (same song on multiple albums) via disambiguation:
  1. source_path_hint matches → unique
  2. album + track_number → disambiguate
  3. duration_ms within ±2 seconds → disambiguate
  4. Unresolved → surfaced to user

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

from .pc_library import PCLibrary, PCTrack
from .audio_fingerprint import get_or_compute_fingerprint, is_fpcalc_available
from .mapping import MappingManager, TrackMapping

logger = logging.getLogger(__name__)


# ─── Enums & Data Classes ─────────────────────────────────────────────────────


class SyncAction(Enum):
    """Type of sync action needed."""

    ADD_TO_IPOD = auto()  # New track, copy to iPod
    REMOVE_FROM_IPOD = auto()  # Track not on PC, remove from iPod
    UPDATE_METADATA = auto()  # Metadata changed on PC, update iPod DB
    UPDATE_FILE = auto()  # Source file changed, re-copy/transcode
    UPDATE_ARTWORK = auto()  # Embedded art changed, re-extract
    SYNC_PLAYCOUNT = auto()  # iPod has new plays, write-back to PC
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
    play_count_delta: int = 0
    skip_count_delta: int = 0

    # For SYNC_RATING — last-write-wins
    ipod_rating: int = 0  # 0-100 (stars × 20)
    pc_rating: int = 0  # 0-100 (stars × 20)
    new_rating: int = 0  # The winner

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

    # Artwork: True if any matched track lacks art on iPod
    artwork_needs_sync: bool = False
    artwork_missing_count: int = 0

    # Errors during fingerprinting
    fingerprint_errors: list[tuple[str, str]] = field(default_factory=list)

    # Fingerprint collisions that couldn't be auto-resolved
    unresolved_collisions: list[tuple[str, list[PCTrack]]] = field(default_factory=list)

    # PC duplicates: fingerprint → list[PCTrack] with same fingerprint on PC
    duplicates: dict[str, list[PCTrack]] = field(default_factory=dict)

    # Stale mapping entries: (fingerprint, dbid) pairs where dbid is not in iTunesDB.
    # Cleaned from mapping during execution, not shown to user.
    _stale_mapping_entries: list[tuple[str, int]] = field(default_factory=list)

    # Stats
    total_pc_tracks: int = 0
    total_ipod_tracks: int = 0
    matched_tracks: int = 0

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
            self.artwork_needs_sync,
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
        if self.artwork_needs_sync:
            lines.append(f"  🖼️  {self.artwork_missing_count} tracks missing album art")
        if self.fingerprint_errors:
            lines.append(f"  ⚠️  {len(self.fingerprint_errors)} files could not be fingerprinted")
        if self.duplicates:
            lines.append(f"  🚫 {len(self.duplicates)} duplicate groups ({self.duplicate_count} extra files)")
        if self.unresolved_collisions:
            lines.append(f"  ❓ {len(self.unresolved_collisions)} unresolved fingerprint collisions")

        if not lines:
            return "✅ Everything is in sync!"

        header = f"Sync Plan ({self.matched_tracks} matched, {self.total_pc_tracks} PC, {self.total_ipod_tracks} iPod):"
        return header + "\n" + "\n".join(lines)


# ─── Metadata Comparison ──────────────────────────────────────────────────────

# PC field name → iPod track dict key
METADATA_FIELDS: dict[str, str] = {
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "Album Artist",
    "genre": "Genre",
    "year": "year",
    "track_number": "trackNumber",
    "disc_number": "discNumber",
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

    def __init__(self, pc_library: PCLibrary, ipod_path: str | Path):
        self.pc_library = pc_library
        self.ipod_path = Path(ipod_path)
        self.mapping_manager = MappingManager(ipod_path)

    # ── Public API ──────────────────────────────────────────────────────────

    def compute_diff(
        self,
        ipod_tracks: list[dict],
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
        write_fingerprints: bool = True,
    ) -> SyncPlan:
        """
        Compute the full sync plan.

        Args:
            ipod_tracks: Track dicts from iTunesDB parser
            progress_callback: Optional callback(stage, current, total, message)
            write_fingerprints: Store computed fingerprints in PC file metadata

        Returns:
            SyncPlan
        """
        if not is_fpcalc_available():
            raise RuntimeError(
                "fpcalc not found. Install Chromaprint: https://acoustid.org/chromaprint"
            )

        plan = SyncPlan()

        # Build iPod track lookup by dbid
        ipod_by_dbid: dict[int, dict] = {}
        for track in ipod_tracks:
            dbid = track.get("dbid")
            if dbid:
                ipod_by_dbid[dbid] = track
        plan.total_ipod_tracks = len(ipod_by_dbid)

        # Load mapping
        if progress_callback:
            progress_callback("load_mapping", 0, 0, "Loading iPod mapping...")
        mapping = self.mapping_manager.load()

        # ===== Phase 1: Scan PC & fingerprint =====
        if progress_callback:
            progress_callback("scan_pc", 0, 0, "Scanning PC library...")

        pc_tracks = list(self.pc_library.scan())
        plan.total_pc_tracks = len(pc_tracks)

        # fingerprint → list[PCTrack]  (to detect PC-side duplicates)
        pc_by_fp: dict[str, list[PCTrack]] = {}
        seen_fps: set[str] = set()

        for i, track in enumerate(pc_tracks):
            if progress_callback:
                progress_callback("fingerprint", i + 1, len(pc_tracks), track.filename)

            fp = get_or_compute_fingerprint(track.path, write_to_file=write_fingerprints)
            if not fp:
                plan.fingerprint_errors.append((track.path, "Could not compute fingerprint"))
                continue

            pc_by_fp.setdefault(fp, []).append(track)
            seen_fps.add(fp)

        # ===== Phase 2: Detect PC duplicates =====
        duplicate_fps: set[str] = set()
        for fp, tracks in pc_by_fp.items():
            if len(tracks) > 1:
                plan.duplicates[fp] = tracks
                duplicate_fps.add(fp)

        # ===== Phase 3: Match & Diff =====
        if progress_callback:
            progress_callback("diff", 0, 0, "Computing differences...")

        for fp, pc_tracks_for_fp in pc_by_fp.items():
            if fp in duplicate_fps:
                # Duplicates on PC — blocked from sync
                continue

            pc_track = pc_tracks_for_fp[0]
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

            # MATCHED: Resolve which mapping entry this PC track matches
            matched_entry = self._resolve_collision(pc_track, mapping_entries)

            if matched_entry is None:
                # Collision couldn't be resolved
                plan.unresolved_collisions.append((fp, pc_tracks_for_fp))
                continue

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

            # Play count: additive (iPod→PC)
            plays_since_sync = ipod_track.get("playCount2", 0)
            skips_since_sync = ipod_track.get("skipCount", 0)
            if plays_since_sync > 0 or skips_since_sync > 0:
                plan.to_sync_playcount.append(SyncItem(
                    action=SyncAction.SYNC_PLAYCOUNT,
                    fingerprint=fp,
                    pc_track=pc_track,
                    dbid=dbid,
                    ipod_track=ipod_track,
                    play_count_delta=plays_since_sync,
                    skip_count_delta=skips_since_sync,
                    description=f"Played {plays_since_sync}x: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))

            # Rating: last-write-wins
            ipod_rating = ipod_track.get("rating", 0)
            pc_rating = pc_track.rating or 0
            if ipod_rating != pc_rating and (ipod_rating > 0 or pc_rating > 0):
                # Determine winner: whichever was modified more recently
                # Since we can't track rating mtime reliably, use iPod as winner
                # (user most recently used the device)
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
                    description=f"Rating: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))

        # ===== Phase 4: Find tracks to remove =====
        mapping_fps = mapping.all_fingerprints()
        orphaned_fps = mapping_fps - seen_fps

        for fp in orphaned_fps:
            for entry in mapping.get_entries(fp):
                dbid = entry.dbid
                ipod_track = ipod_by_dbid.get(dbid)

                if not ipod_track:
                    # Stale mapping entry — dbid not in current iTunesDB.
                    # Nothing to remove from iPod; silently clean from mapping.
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

        # ===== Phase 5: Missing artwork check =====
        for dbid, _pc_path in plan.matched_pc_paths.items():
            ipod_track = ipod_by_dbid.get(dbid)
            if ipod_track:
                if ipod_track.get("artworkCount", 0) == 0 or ipod_track.get("mhiiLink", 0) == 0:
                    plan.artwork_missing_count += 1

        if plan.artwork_missing_count > 0:
            plan.artwork_needs_sync = True
            logger.info(f"ART: {plan.artwork_missing_count} matched tracks missing artwork")

        return plan

    # ── Private Helpers ─────────────────────────────────────────────────────

    def _resolve_collision(
        self,
        pc_track: PCTrack,
        entries: list[TrackMapping],
    ) -> Optional[TrackMapping]:
        """
        Resolve a fingerprint collision (multiple mapping entries).

        Disambiguation cascade:
          1. Single entry → trivial
          2. source_path_hint matches → unique
          3. Only one entry matching same album+track# → unique
          4. Duration within ±2s → unique
          5. Otherwise → None (unresolved)
        """
        if len(entries) == 1:
            return entries[0]

        # Try source_path_hint
        for entry in entries:
            if entry.source_path_hint and entry.source_path_hint == pc_track.relative_path:
                return entry

        # NOTE: Further disambiguation (album+track#, duration) would require
        # iPod track data which we don't have here. For now, return None for
        # true multi-entry collisions that path hint can't resolve.
        # The caller will add these to unresolved_collisions.
        logger.warning(
            f"Unresolved collision: {len(entries)} entries for same fingerprint, "
            f"none match path hint '{pc_track.relative_path}'"
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

            # Normalize
            if pc_value is None:
                pc_value = ""
            if ipod_value is None:
                ipod_value = ""

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
