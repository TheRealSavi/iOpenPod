"""
Diff Engine - Computes the sync plan between PC library and iPod.

Uses pure fingerprint matching - no database needed.

Fingerprint = artist|album|title|duration_sec (normalized, lowercase)
- Same song at different quality = same fingerprint
- Size comparison determines quality changes

Flow:
1. Scan PC → Dict[fingerprint, PCTrack]
2. Scan iPod → Dict[fingerprint, iPodTrack]
3. Find PC duplicates → Block those fingerprints
4. PC-only (non-dupe) → ADD
5. iPod-only (fingerprint not on PC, including dupes) → REMOVE
6. Both exist (non-dupe), size differs >5% → QUALITY CHANGE
7. Both exist, check play counts
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum, auto

from .pc_library import PCLibrary, PCTrack


class SyncAction(Enum):
    """Type of sync action needed."""
    ADD_TO_IPOD = auto()        # New track, copy to iPod
    REMOVE_FROM_IPOD = auto()   # Track not on PC, remove from iPod
    SYNC_PLAYCOUNT = auto()     # iPod has new plays, sync to PC
    SYNC_RATING = auto()        # iPod rating differs from PC rating
    NO_ACTION = auto()          # Track is in sync


@dataclass
class QualityChange:
    """Represents a quality upgrade/downgrade between PC and iPod versions."""
    pc_track: PCTrack           # PC file
    ipod_track: dict            # Current iPod track
    size_diff: int              # Positive = upgrade (PC bigger), negative = downgrade

    @property
    def is_upgrade(self) -> bool:
        return self.size_diff > 0

    @property
    def direction(self) -> str:
        return "upgrade" if self.is_upgrade else "downgrade"


@dataclass
class SyncItem:
    """A single item in the sync plan."""
    action: SyncAction

    # For ADD actions
    pc_track: Optional[PCTrack] = None

    # For REMOVE/SYNC_PLAYCOUNT/SYNC_RATING actions (from iTunesDB)
    ipod_track: Optional[dict] = None

    # For SYNC_PLAYCOUNT
    play_count_delta: int = 0
    skip_count_delta: int = 0

    # For SYNC_RATING
    ipod_rating: int = 0       # Rating on iPod (0-100, stars × 20)
    pc_rating: int = 0         # Rating on PC (0-100, stars × 20)
    new_rating: int = 0        # Computed rating to apply (average if both non-zero)

    # Human-readable description
    description: str = ""


@dataclass
class SyncPlan:
    """Complete sync plan with all actions needed."""

    # Grouped actions
    to_add: list[SyncItem] = field(default_factory=list)
    to_remove: list[SyncItem] = field(default_factory=list)
    to_sync_playcount: list[SyncItem] = field(default_factory=list)
    to_sync_rating: list[SyncItem] = field(default_factory=list)

    # Quality changes (PC size differs significantly from iPod)
    quality_changes: list[QualityChange] = field(default_factory=list)

    # Duplicates on PC: fingerprint -> list of PCTrack with same fingerprint
    duplicates: dict[str, list[PCTrack]] = field(default_factory=dict)

    # Stats
    total_pc_tracks: int = 0
    total_ipod_tracks: int = 0
    matched_tracks: int = 0

    # Size estimates
    bytes_to_add: int = 0
    bytes_to_remove: int = 0

    @property
    def has_changes(self) -> bool:
        """Check if any sync actions are needed."""
        return any([
            self.to_add,
            self.to_remove,
            self.to_sync_playcount,
            self.to_sync_rating,
            self.quality_changes,
        ])

    @property
    def has_duplicates(self) -> bool:
        """Check if there are duplicate files that need resolution."""
        return bool(self.duplicates)

    @property
    def duplicate_count(self) -> int:
        """Total number of extra duplicate files (not counting the 'original')."""
        return sum(len(tracks) - 1 for tracks in self.duplicates.values())

    @property
    def summary(self) -> str:
        """Human-readable summary of the sync plan."""
        lines = []
        if self.to_add:
            lines.append(f"  📥 {len(self.to_add)} tracks to add ({self._format_bytes(self.bytes_to_add)})")
        if self.to_remove:
            lines.append(f"  🗑️  {len(self.to_remove)} tracks to remove ({self._format_bytes(self.bytes_to_remove)})")
        if self.quality_changes:
            upgrades = sum(1 for qc in self.quality_changes if qc.is_upgrade)
            downgrades = len(self.quality_changes) - upgrades
            if upgrades:
                lines.append(f"  ⬆️  {upgrades} quality upgrades")
            if downgrades:
                lines.append(f"  ⬇️  {downgrades} quality downgrades")
        if self.to_sync_playcount:
            lines.append(f"  🎵 {len(self.to_sync_playcount)} tracks with new play counts")
        if self.to_sync_rating:
            lines.append(f"  ⭐ {len(self.to_sync_rating)} tracks with rating changes")
        if self.duplicates:
            lines.append(f"  ⚠️  {len(self.duplicates)} duplicate groups ({self.duplicate_count} extra files)")

        if not lines:
            return "✅ Everything is in sync!"

        return "Sync Plan:\n" + "\n".join(lines)

    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes as human-readable string."""
        val = float(bytes_val)
        for unit in ["B", "KB", "MB", "GB"]:
            if val < 1024:
                return f"{val:.1f} {unit}"
            val /= 1024
        return f"{val:.1f} TB"


class DiffEngine:
    """
    Computes sync differences between PC library and iPod using fingerprint matching.

    No database required - just compares two sets of fingerprints.

    Usage:
        engine = DiffEngine(pc_library)
        plan = engine.compute_diff(ipod_tracks)
        print(plan.summary)
    """

    def __init__(self, pc_library: PCLibrary):
        self.pc_library = pc_library

    def _make_fingerprint(self, artist: str, album: str, title: str, duration_ms: int) -> str:
        """Create normalized fingerprint from metadata."""
        artist = (artist or "").lower().strip()
        album = (album or "").lower().strip()
        title = (title or "").lower().strip()
        duration_sec = duration_ms // 1000
        return f"{artist}|{album}|{title}|{duration_sec}"

    def _make_pc_fingerprint(self, track: PCTrack) -> str:
        """Create fingerprint for a PC track."""
        return self._make_fingerprint(
            track.artist or "",
            track.album or "",
            track.title or "",
            track.duration_ms
        )

    def _make_ipod_fingerprint(self, track: dict) -> str:
        """Create fingerprint for an iPod track."""
        return self._make_fingerprint(
            track.get("Artist", ""),
            track.get("Album", ""),
            track.get("Title", ""),
            track.get("length", 0)
        )

    def _sizes_differ_significantly(self, size1: int, size2: int, tolerance_pct: float = 0.05) -> bool:
        """Check if two file sizes differ by more than tolerance (default 5%)."""
        if size1 <= 0 or size2 <= 0:
            return False
        diff = abs(size1 - size2)
        avg = (size1 + size2) / 2
        return diff / avg > tolerance_pct

    def compute_diff(
        self,
        ipod_tracks: list[dict],
        progress_callback=None,
    ) -> SyncPlan:
        """
        Compute the sync plan by comparing PC and iPod fingerprints.

        Args:
            ipod_tracks: List of track dicts from iTunesDB parser
            progress_callback: Optional callback(stage, current, total, message)

        Returns:
            SyncPlan with all sync actions needed
        """
        plan = SyncPlan()

        # ===== Step 1: Scan both libraries and build fingerprint indexes =====
        if progress_callback:
            progress_callback("scan", 0, 0, "Scanning PC library...")

        # Build PC fingerprint index
        pc_by_fingerprint: dict[str, list[PCTrack]] = {}
        pc_tracks = list(self.pc_library.scan())
        plan.total_pc_tracks = len(pc_tracks)

        for i, track in enumerate(pc_tracks):
            if progress_callback:
                progress_callback("scan_pc", i + 1, len(pc_tracks), track.filename)
            fp = self._make_pc_fingerprint(track)
            if fp not in pc_by_fingerprint:
                pc_by_fingerprint[fp] = []
            pc_by_fingerprint[fp].append(track)

        # Build iPod fingerprint index
        if progress_callback:
            progress_callback("scan", 0, 0, "Scanning iPod library...")

        ipod_by_fingerprint: dict[str, dict] = {}
        for track in ipod_tracks:
            fp = self._make_ipod_fingerprint(track)
            ipod_by_fingerprint[fp] = track

        plan.total_ipod_tracks = len(ipod_by_fingerprint)

        # ===== Step 2: Find PC duplicates =====
        if progress_callback:
            progress_callback("duplicates", 0, 0, "Checking for duplicates...")

        duplicate_fingerprints: set[str] = set()
        for fp, tracks in pc_by_fingerprint.items():
            if len(tracks) > 1:
                plan.duplicates[fp] = tracks
                duplicate_fingerprints.add(fp)

        # ===== Step 3: PC-only fingerprints (non-duplicate) → ADD =====
        if progress_callback:
            progress_callback("diff", 0, 0, "Computing differences...")

        for fp, tracks in pc_by_fingerprint.items():
            # Skip duplicates - they're blocked
            if fp in duplicate_fingerprints:
                continue

            pc_track = tracks[0]  # Only one track (non-duplicate)

            if fp not in ipod_by_fingerprint:
                # PC has it, iPod doesn't → ADD
                plan.to_add.append(SyncItem(
                    action=SyncAction.ADD_TO_IPOD,
                    pc_track=pc_track,
                    description=f"New: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                ))
                plan.bytes_to_add += pc_track.size
            else:
                # Both have it → MATCHED
                plan.matched_tracks += 1
                ipod_track = ipod_by_fingerprint[fp]

                # Check for quality difference
                ipod_size = ipod_track.get("size", 0)
                if self._sizes_differ_significantly(pc_track.size, ipod_size):
                    plan.quality_changes.append(QualityChange(
                        pc_track=pc_track,
                        ipod_track=ipod_track,
                        size_diff=pc_track.size - ipod_size,
                    ))

                # Check for play count changes
                plays_since_sync = ipod_track.get("playCount2", 0)
                if plays_since_sync > 0:
                    plan.to_sync_playcount.append(SyncItem(
                        action=SyncAction.SYNC_PLAYCOUNT,
                        pc_track=pc_track,
                        ipod_track=ipod_track,
                        play_count_delta=plays_since_sync,
                        description=f"Played {plays_since_sync}x: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                    ))

                # Check for rating changes
                ipod_rating = ipod_track.get("rating", 0)  # 0-100 (stars × 20)
                pc_rating = pc_track.rating or 0  # 0-100 (stars × 20)
                if ipod_rating != pc_rating:
                    # Compute new rating: average if both non-zero, else use whichever is set
                    if ipod_rating > 0 and pc_rating > 0:
                        # Round to nearest 20 (star boundary)
                        avg = (ipod_rating + pc_rating) / 2
                        new_rating = round(avg / 20) * 20
                    else:
                        new_rating = ipod_rating or pc_rating

                    plan.to_sync_rating.append(SyncItem(
                        action=SyncAction.SYNC_RATING,
                        pc_track=pc_track,
                        ipod_track=ipod_track,
                        ipod_rating=ipod_rating,
                        pc_rating=pc_rating,
                        new_rating=new_rating,
                        description=f"Rating changed: {pc_track.artist or 'Unknown'} - {pc_track.title or pc_track.filename}",
                    ))

        # ===== Step 4: iPod-only fingerprints → REMOVE =====
        # But NOT if PC has duplicates of that fingerprint (frozen)
        pc_fingerprints_exist = set(pc_by_fingerprint.keys())

        for fp, ipod_track in ipod_by_fingerprint.items():
            if fp not in pc_fingerprints_exist:
                # iPod has it, PC doesn't → REMOVE
                plan.to_remove.append(SyncItem(
                    action=SyncAction.REMOVE_FROM_IPOD,
                    ipod_track=ipod_track,
                    description=f"Not on PC: {ipod_track.get('Artist', 'Unknown')} - {ipod_track.get('Title', 'Unknown')}",
                ))
                plan.bytes_to_remove += ipod_track.get("size", 0)
            # else: fingerprint exists on PC (maybe as duplicate) - don't remove

        return plan
