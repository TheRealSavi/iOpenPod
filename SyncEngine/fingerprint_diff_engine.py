"""
Fingerprint-Based Diff Engine - Computes sync plan using acoustic fingerprints.

Uses Chromaprint acoustic fingerprints for reliable track identification:
- Same song at different quality/format = same fingerprint
- Metadata changes don't affect fingerprint
- Only audio content changes create new fingerprint

Flow:
1. Scan PC library → compute/read fingerprints for all tracks
2. Load iPod mapping file → fingerprint → dbid relationships
3. For each PC track:
   - Fingerprint in mapping → MATCHED (check for metadata/file changes)
   - Fingerprint not in mapping → ADD
4. For each mapping entry not seen → REMOVE

Fallback to signature matching for edge cases (initial sync of existing libraries).
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


class SyncAction(Enum):
    """Type of sync action needed."""

    ADD_TO_IPOD = auto()  # New track, copy to iPod
    REMOVE_FROM_IPOD = auto()  # Track not on PC, remove from iPod
    UPDATE_METADATA = auto()  # Metadata changed on PC, update iPod
    UPDATE_FILE = auto()  # Source file changed, re-sync to iPod
    SYNC_PLAYCOUNT = auto()  # iPod has new plays, sync to PC
    SYNC_RATING = auto()  # Rating differs, sync
    NO_ACTION = auto()  # Track is in sync


@dataclass
class SyncItem:
    """A single item in the sync plan."""

    action: SyncAction
    fingerprint: Optional[str] = None

    # For ADD/UPDATE actions
    pc_track: Optional[PCTrack] = None

    # For REMOVE/matched actions (from iTunesDB via mapping)
    dbid: Optional[int] = None
    ipod_track: Optional[dict] = None

    # For UPDATE_METADATA: which fields changed
    metadata_changes: dict = field(default_factory=dict)

    # For SYNC_PLAYCOUNT
    play_count_delta: int = 0
    skip_count_delta: int = 0

    # For SYNC_RATING
    ipod_rating: int = 0
    pc_rating: int = 0
    new_rating: int = 0

    # Human-readable description
    description: str = ""


@dataclass
class SyncPlan:
    """Complete sync plan with all actions needed."""

    # Grouped actions
    to_add: list[SyncItem] = field(default_factory=list)
    to_remove: list[SyncItem] = field(default_factory=list)
    to_update_metadata: list[SyncItem] = field(default_factory=list)
    to_update_file: list[SyncItem] = field(default_factory=list)
    to_sync_playcount: list[SyncItem] = field(default_factory=list)
    to_sync_rating: list[SyncItem] = field(default_factory=list)

    # PC file paths for ALL matched tracks (dbid → absolute PC path)
    # Used by artwork writer to extract embedded art for every track, not just changed ones
    matched_pc_paths: dict[int, str] = field(default_factory=dict)

    # Artwork sync: True if any matched iPod track is missing artwork
    artwork_needs_sync: bool = False
    artwork_missing_count: int = 0

    # Errors during fingerprinting
    fingerprint_errors: list[tuple[str, str]] = field(default_factory=list)  # (path, error)

    # Stats
    total_pc_tracks: int = 0
    total_ipod_tracks: int = 0
    matched_tracks: int = 0

    # Size estimates
    bytes_to_add: int = 0
    bytes_to_remove: int = 0
    bytes_to_update: int = 0

    @property
    def has_changes(self) -> bool:
        """Check if any sync actions are needed."""
        return any(
            [
                self.to_add,
                self.to_remove,
                self.to_update_metadata,
                self.to_update_file,
                self.to_sync_playcount,
                self.to_sync_rating,
                self.artwork_needs_sync,
            ]
        )

    @property
    def summary(self) -> str:
        """Human-readable summary of the sync plan."""
        lines = []

        if self.to_add:
            lines.append(f"  📥 {len(self.to_add)} tracks to add ({self._format_bytes(self.bytes_to_add)})")
        if self.to_remove:
            lines.append(f"  🗑️  {len(self.to_remove)} tracks to remove ({self._format_bytes(self.bytes_to_remove)})")
        if self.to_update_file:
            lines.append(f"  🔄 {len(self.to_update_file)} tracks to re-sync ({self._format_bytes(self.bytes_to_update)})")
        if self.to_update_metadata:
            lines.append(f"  📝 {len(self.to_update_metadata)} tracks with metadata updates")
        if self.to_sync_playcount:
            lines.append(f"  🎵 {len(self.to_sync_playcount)} tracks with new play counts")
        if self.to_sync_rating:
            lines.append(f"  ⭐ {len(self.to_sync_rating)} tracks with rating changes")
        if self.artwork_needs_sync:
            lines.append(f"  🎨 {self.artwork_missing_count} tracks missing album art")
        if self.fingerprint_errors:
            lines.append(f"  ⚠️  {len(self.fingerprint_errors)} files could not be fingerprinted")

        if not lines:
            return "✅ Everything is in sync!"

        header = f"Sync Plan ({self.matched_tracks} matched, {self.total_pc_tracks} PC, {self.total_ipod_tracks} iPod):"
        return header + "\n" + "\n".join(lines)

    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes as human-readable string."""
        val = float(bytes_val)
        for unit in ["B", "KB", "MB", "GB"]:
            if val < 1024:
                return f"{val:.1f} {unit}"
            val /= 1024
        return f"{val:.1f} TB"


# Metadata fields to compare between PC and iPod
METADATA_FIELDS = {
    # PC field → iPod field
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "AlbumArtist",
    "genre": "Genre",
    "year": "year",  # From mhit parser
    "track_number": "trackNumber",
    "disc_number": "discNumber",
}


class FingerprintDiffEngine:
    """
    Computes sync differences using acoustic fingerprints.

    Usage:
        engine = FingerprintDiffEngine(pc_library, ipod_path)
        plan = engine.compute_diff(ipod_tracks)
        print(plan.summary)
    """

    def __init__(self, pc_library: PCLibrary, ipod_path: str | Path):
        """
        Initialize diff engine.

        Args:
            pc_library: PCLibrary instance for scanning PC music
            ipod_path: Root path of mounted iPod
        """
        self.pc_library = pc_library
        self.ipod_path = Path(ipod_path)
        self.mapping_manager = MappingManager(ipod_path)

    def _compare_metadata(self, pc_track: PCTrack, ipod_track: dict) -> dict:
        """
        Compare metadata between PC and iPod track.

        Returns:
            Dict of {field: (pc_value, ipod_value)} for fields that differ
        """
        changes = {}

        for pc_field, ipod_field in METADATA_FIELDS.items():
            pc_value = getattr(pc_track, pc_field, None)
            ipod_value = ipod_track.get(ipod_field)

            # Normalize for comparison
            if pc_value is None:
                pc_value = ""
            if ipod_value is None:
                ipod_value = ""

            # String comparison (case-insensitive for text fields)
            if isinstance(pc_value, str) and isinstance(ipod_value, str):
                if pc_value.lower().strip() != ipod_value.lower().strip():
                    changes[pc_field] = (pc_value, ipod_value)
            elif pc_value != ipod_value:
                changes[pc_field] = (pc_value, ipod_value)

        return changes

    def _source_file_changed(self, pc_track: PCTrack, mapping: TrackMapping) -> bool:
        """
        Check if the source file has changed since last sync.

        Uses size and mtime comparison. Note: metadata edits may change mtime
        but not size significantly, so we check both.
        """
        # Significant size change (>1% or >10KB)
        size_diff = abs(pc_track.size - mapping.source_size)
        size_pct = size_diff / max(mapping.source_size, 1)

        if size_diff > 10240 and size_pct > 0.01:
            return True

        # mtime changed AND size changed (rules out metadata-only edits)
        if pc_track.mtime != mapping.source_mtime and size_diff > 0:
            return True

        return False

    def compute_diff(
        self,
        ipod_tracks: list[dict],
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
        write_fingerprints: bool = True,
    ) -> SyncPlan:
        """
        Compute the sync plan by comparing PC fingerprints with iPod mapping.

        Args:
            ipod_tracks: List of track dicts from iTunesDB parser
            progress_callback: Optional callback(stage, current, total, message)
            write_fingerprints: If True, store computed fingerprints in PC files

        Returns:
            SyncPlan with all sync actions needed
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

        # Load existing mapping
        if progress_callback:
            progress_callback("load_mapping", 0, 0, "Loading iPod mapping...")

        mapping = self.mapping_manager.load()

        # ===== Step 1: Scan PC and compute fingerprints =====
        if progress_callback:
            progress_callback("scan_pc", 0, 0, "Scanning PC library...")

        pc_tracks = list(self.pc_library.scan())
        plan.total_pc_tracks = len(pc_tracks)

        # Fingerprint → PCTrack mapping (built during scan)
        pc_by_fingerprint: dict[str, PCTrack] = {}
        seen_fingerprints: set[str] = set()

        for i, track in enumerate(pc_tracks):
            if progress_callback:
                progress_callback("fingerprint", i + 1, len(pc_tracks), track.filename)

            # Get or compute fingerprint
            fingerprint = get_or_compute_fingerprint(
                track.path,
                write_to_file=write_fingerprints,
            )

            if not fingerprint:
                plan.fingerprint_errors.append((track.path, "Could not compute fingerprint"))
                continue

            # Handle duplicate fingerprints on PC (same audio, different files)
            if fingerprint in pc_by_fingerprint:
                # Skip duplicate - first one wins
                logger.warning(
                    f"Duplicate fingerprint: {track.path} matches {pc_by_fingerprint[fingerprint].path}"
                )
                continue

            pc_by_fingerprint[fingerprint] = track
            seen_fingerprints.add(fingerprint)

        # ===== Step 2: Compare with mapping =====
        if progress_callback:
            progress_callback("diff", 0, 0, "Computing differences...")

        for fingerprint, pc_track in pc_by_fingerprint.items():
            existing_mapping = mapping.get_track(fingerprint)

            if existing_mapping is None:
                # NEW TRACK: Not in mapping → Add to iPod
                plan.to_add.append(
                    SyncItem(
                        action=SyncAction.ADD_TO_IPOD,
                        fingerprint=fingerprint,
                        pc_track=pc_track,
                        description=f"New: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                    )
                )
                plan.bytes_to_add += pc_track.size
            else:
                # MATCHED: In mapping → Check for changes
                plan.matched_tracks += 1
                dbid = existing_mapping.dbid
                ipod_track = ipod_by_dbid.get(dbid)

                # Always record PC path for artwork extraction
                if dbid and pc_track.path:
                    plan.matched_pc_paths[dbid] = str(pc_track.path)

                if ipod_track is None:
                    # Mapping exists but track missing from iTunesDB (corrupted state)
                    # Treat as new track
                    logger.warning(f"Mapping for {fingerprint} points to missing dbid {dbid}")
                    plan.to_add.append(
                        SyncItem(
                            action=SyncAction.ADD_TO_IPOD,
                            fingerprint=fingerprint,
                            pc_track=pc_track,
                            description=f"Re-add (mapping stale): {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                        )
                    )
                    plan.bytes_to_add += pc_track.size
                    continue

                # Check if source file changed (quality upgrade/downgrade)
                if self._source_file_changed(pc_track, existing_mapping):
                    plan.to_update_file.append(
                        SyncItem(
                            action=SyncAction.UPDATE_FILE,
                            fingerprint=fingerprint,
                            pc_track=pc_track,
                            dbid=dbid,
                            ipod_track=ipod_track,
                            description=f"File changed: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                        )
                    )
                    plan.bytes_to_update += pc_track.size

                # Check for metadata changes
                metadata_changes = self._compare_metadata(pc_track, ipod_track)
                if metadata_changes:
                    plan.to_update_metadata.append(
                        SyncItem(
                            action=SyncAction.UPDATE_METADATA,
                            fingerprint=fingerprint,
                            pc_track=pc_track,
                            dbid=dbid,
                            ipod_track=ipod_track,
                            metadata_changes=metadata_changes,
                            description=f"Metadata: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename} ({', '.join(metadata_changes.keys())})",
                        )
                    )

                # Check for play count changes (iPod → PC sync)
                plays_since_sync = ipod_track.get("playCount2", 0)
                if plays_since_sync > 0:
                    plan.to_sync_playcount.append(
                        SyncItem(
                            action=SyncAction.SYNC_PLAYCOUNT,
                            fingerprint=fingerprint,
                            pc_track=pc_track,
                            dbid=dbid,
                            ipod_track=ipod_track,
                            play_count_delta=plays_since_sync,
                            description=f"Played {plays_since_sync}x: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                        )
                    )

                # Check for rating changes
                ipod_rating = ipod_track.get("rating", 0)
                pc_rating = pc_track.rating or 0
                if ipod_rating != pc_rating:
                    # Use higher rating, or average if both non-zero
                    if ipod_rating > 0 and pc_rating > 0:
                        avg = (ipod_rating + pc_rating) / 2
                        new_rating = round(avg / 20) * 20
                    else:
                        new_rating = max(ipod_rating, pc_rating)

                    plan.to_sync_rating.append(
                        SyncItem(
                            action=SyncAction.SYNC_RATING,
                            fingerprint=fingerprint,
                            pc_track=pc_track,
                            dbid=dbid,
                            ipod_track=ipod_track,
                            ipod_rating=ipod_rating,
                            pc_rating=pc_rating,
                            new_rating=new_rating,
                            description=f"Rating: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                        )
                    )

        # ===== Step 3: Find tracks to remove (in mapping but not on PC) =====
        mapping_fingerprints = mapping.all_fingerprints()
        orphaned_fingerprints = mapping_fingerprints - seen_fingerprints

        for fingerprint in orphaned_fingerprints:
            track_mapping = mapping.get_track(fingerprint)
            if track_mapping:
                dbid = track_mapping.dbid
                ipod_track = ipod_by_dbid.get(dbid)

                plan.to_remove.append(
                    SyncItem(
                        action=SyncAction.REMOVE_FROM_IPOD,
                        fingerprint=fingerprint,
                        dbid=dbid,
                        ipod_track=ipod_track,
                        description=f"Removed from PC: {ipod_track.get('Artist', 'Unknown') if ipod_track else 'Unknown'} - {ipod_track.get('Title', 'Unknown') if ipod_track else 'Unknown'}",
                    )
                )
                if ipod_track:
                    plan.bytes_to_remove += ipod_track.get("size", 0)

        # ===== Step 4: Check for missing artwork =====
        # If any matched iPod track is missing artwork, flag for sync.
        # The artwork writer will extract art from PC files during database write.
        for dbid, pc_path in plan.matched_pc_paths.items():
            ipod_track = ipod_by_dbid.get(dbid)
            if ipod_track:
                artwork_count = ipod_track.get("artworkCount", 0)
                mhii_link = ipod_track.get("mhiiLink", 0)
                if artwork_count == 0 or mhii_link == 0:
                    plan.artwork_missing_count += 1

        if plan.artwork_missing_count > 0:
            plan.artwork_needs_sync = True
            logger.info(f"ART: {plan.artwork_missing_count} matched tracks missing artwork on iPod")

        return plan
