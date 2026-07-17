"""Public sync boundary DTOs shared by app-core and sync services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from iopenpod.device.storage_safety import allocated_size

from .mapping import MappingFile

if TYPE_CHECKING:
    from .integrity import IntegrityReport
    from .pc_library import PCTrack
    from .photos import PhotoSyncPlan
    from .transcoder import TranscodePlan


def _fmt_bytes(val: int) -> str:
    """Format bytes as human-readable string."""
    v = float(abs(val))
    for unit in ["B", "KB", "MB", "GB"]:
        if v < 1024:
            return f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} TB"


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


# Minimum free space (bytes) that should remain on the iPod after ordinary
# file copies. Sync-until-full lowers this to the database-write reserve.
SYNC_DISK_RESERVE_BYTES = 4 * 1024 * 1024

# Minimum free space required before attempting to write the database.
SYNC_DB_WRITE_RESERVE_BYTES = 1 * 1024 * 1024

# Estimated overhead for database files and their temporary write payloads.
SYNC_DB_OVERHEAD_BYTES = 10 * 1024 * 1024

# Reserve used by the explicit "sync until full" policy.
SYNC_UNTIL_FULL_RESERVE_BYTES = SYNC_DB_WRITE_RESERVE_BYTES


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
    fingerprint: str | None = None
    pc_track: PCTrack | None = None
    estimated_size: int | None = None
    transcode_plan: TranscodePlan | None = None
    db_track_id: int | None = None
    ipod_track: dict | None = None
    metadata_changes: dict = field(default_factory=dict)
    play_count_delta: int = 0
    skip_count_delta: int = 0
    ipod_rating: int = 0
    pc_rating: int = 0
    new_rating: int = 0
    rating_strategy: str = ""
    old_art_hash: str | None = None
    new_art_hash: str | None = None
    description: str = ""
    conversion_group_id: str | None = None
    conversion_group_add_count: int = 0
    defer_removal_until_after_add: bool = False
    conversion_source_fingerprints: tuple[str, ...] = ()
    conversion_source_path_hints: tuple[str, ...] = ()
    conversion_source_metadata: tuple[dict, ...] = ()
    mapping_source_metadata: dict | None = None
    aggregate_kind: str | None = None
    aggregate_contains_fingerprints: tuple[str, ...] = ()
    aggregate_contains_sources: tuple[dict, ...] = ()
    aggregate_rebuild_pc_tracks: tuple[PCTrack, ...] = ()
    aggregate_removed_fingerprint: str | None = None

    def __init__(
        self,
        action: SyncAction,
        fingerprint: str | None = None,
        pc_track: PCTrack | None = None,
        estimated_size: int | None = None,
        transcode_plan: TranscodePlan | None = None,
        db_track_id: int | None = None,
        ipod_track: dict | None = None,
        metadata_changes: dict | None = None,
        play_count_delta: int = 0,
        skip_count_delta: int = 0,
        ipod_rating: int = 0,
        pc_rating: int = 0,
        new_rating: int = 0,
        rating_strategy: str = "",
        old_art_hash: str | None = None,
        new_art_hash: str | None = None,
        description: str = "",
        conversion_group_id: str | None = None,
        conversion_group_add_count: int = 0,
        defer_removal_until_after_add: bool = False,
        conversion_source_fingerprints: tuple[str, ...] = (),
        conversion_source_path_hints: tuple[str, ...] = (),
        conversion_source_metadata: tuple[dict, ...] = (),
        mapping_source_metadata: dict | None = None,
        aggregate_kind: str | None = None,
        aggregate_contains_fingerprints: tuple[str, ...] = (),
        aggregate_contains_sources: tuple[dict, ...] = (),
        aggregate_rebuild_pc_tracks: tuple[PCTrack, ...] = (),
        aggregate_removed_fingerprint: str | None = None,
    ) -> None:
        self.action = action
        self.fingerprint = fingerprint
        self.pc_track = pc_track
        self.estimated_size = estimated_size
        self.transcode_plan = transcode_plan
        self.db_track_id = db_track_id
        self.ipod_track = ipod_track
        self.metadata_changes = metadata_changes or {}
        self.play_count_delta = play_count_delta
        self.skip_count_delta = skip_count_delta
        self.ipod_rating = ipod_rating
        self.pc_rating = pc_rating
        self.new_rating = new_rating
        self.rating_strategy = rating_strategy
        self.old_art_hash = old_art_hash
        self.new_art_hash = new_art_hash
        self.description = description
        self.conversion_group_id = conversion_group_id
        self.conversion_group_add_count = conversion_group_add_count
        self.defer_removal_until_after_add = defer_removal_until_after_add
        self.conversion_source_fingerprints = conversion_source_fingerprints
        self.conversion_source_path_hints = conversion_source_path_hints
        self.conversion_source_metadata = conversion_source_metadata
        self.mapping_source_metadata = mapping_source_metadata
        self.aggregate_kind = aggregate_kind
        self.aggregate_contains_fingerprints = aggregate_contains_fingerprints
        self.aggregate_contains_sources = aggregate_contains_sources
        self.aggregate_rebuild_pc_tracks = aggregate_rebuild_pc_tracks
        self.aggregate_removed_fingerprint = aggregate_removed_fingerprint

    def __post_init__(self) -> None:
        if self.metadata_changes is None:
            self.metadata_changes = {}

    @property
    def has_pc_source(self) -> bool:
        """True when this item has a source track available on the PC."""

        return self.pc_track is not None and bool(getattr(self.pc_track, "path", ""))

    @property
    def source_path(self) -> str:
        """Absolute or library-relative PC source path, when available."""

        return str(getattr(self.pc_track, "path", "") or "") if self.pc_track else ""

    @property
    def source_relative_path(self) -> str:
        """Stable library-relative source hint, when available."""

        if self.pc_track is None:
            return ""
        return str(getattr(self.pc_track, "relative_path", "") or "")

    @property
    def ipod_location(self) -> str:
        """iPod database location path for removal/update items."""

        if not self.ipod_track:
            return ""
        return str(
            self.ipod_track.get("Location")
            or self.ipod_track.get("location")
            or ""
        )

    @property
    def display_label(self) -> str:
        """Best short label for progress/errors."""

        if self.description:
            return self.description
        if self.pc_track is not None:
            return str(
                getattr(self.pc_track, "title", None)
                or getattr(self.pc_track, "filename", None)
                or getattr(self.pc_track, "path", "")
                or "track"
            )
        if self.ipod_track:
            return str(
                self.ipod_track.get("Title")
                or self.ipod_track.get("title")
                or self.ipod_location
                or "track"
            )
        return "track"

    @property
    def planned_add_size(self) -> int:
        """Estimated bytes that this item will write to the device."""

        if self.estimated_size is not None:
            return _coerce_nonnegative_int(self.estimated_size)
        if self.pc_track is not None:
            return _coerce_nonnegative_int(getattr(self.pc_track, "size", 0))
        return 0

    @property
    def planned_remove_size(self) -> int:
        """Estimated bytes removed from the device for this item."""

        if not self.ipod_track:
            return 0
        return _coerce_nonnegative_int(self.ipod_track.get("size", 0))

    @property
    def planned_update_growth(self) -> int:
        """Positive byte growth when replacing an existing file."""

        return max(0, self.planned_add_size - self.planned_remove_size)

    @property
    def conversion_group_key(self) -> str:
        return str(self.conversion_group_id or "")

    @property
    def conversion_group_expected_count(self) -> int:
        return _coerce_nonnegative_int(self.conversion_group_add_count)

    @property
    def is_deferred_removal(self) -> bool:
        return bool(self.defer_removal_until_after_add)

    @property
    def is_deferred_replacement_removal(self) -> bool:
        return bool(self.defer_removal_until_after_add and self.conversion_group_id)

    @property
    def is_chaptered_aggregate_rebuild(self) -> bool:
        return (
            self.aggregate_kind == "chaptered_album"
            and bool(self.aggregate_rebuild_pc_tracks)
            and bool(self.db_track_id)
        )


@dataclass
class StorageSummary:
    """iPod storage estimate for the sync plan."""

    bytes_to_add: int = 0
    bytes_to_remove: int = 0
    bytes_to_update: int = 0

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

    to_add: list[SyncItem] = field(default_factory=list)
    to_remove: list[SyncItem] = field(default_factory=list)
    to_update_metadata: list[SyncItem] = field(default_factory=list)
    to_update_file: list[SyncItem] = field(default_factory=list)
    to_update_artwork: list[SyncItem] = field(default_factory=list)
    to_sync_playcount: list[SyncItem] = field(default_factory=list)
    to_sync_rating: list[SyncItem] = field(default_factory=list)
    matched_pc_paths: dict[int, str] = field(default_factory=dict)
    fingerprint_errors: list[tuple[str, str]] = field(default_factory=list)
    unresolved_collisions: list[tuple[str, list[PCTrack]]] = field(default_factory=list)
    duplicates: dict[str, list[PCTrack]] = field(default_factory=dict)
    _stale_mapping_entries: list[tuple[str, int]] = field(default_factory=list)
    _integrity_removals: list[SyncItem] = field(default_factory=list)
    _mapping_requires_persistence: bool = False
    _refreshed_podcast_feeds: list[Any] | None = None
    mapping: MappingFile | None = None
    integrity_report: IntegrityReport | None = None
    total_pc_tracks: int = 0
    total_ipod_tracks: int = 0
    matched_tracks: int = 0
    playlists_to_add: list[dict] = field(default_factory=list)
    playlists_to_edit: list[dict] = field(default_factory=list)
    playlists_to_remove: list[dict] = field(default_factory=list)
    storage: StorageSummary = field(default_factory=StorageSummary)
    photo_plan: PhotoSyncPlan | None = None
    removals_pre_checked: bool = False

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
            self._integrity_removals,
            self.has_integrity_housekeeping,
            self._refreshed_podcast_feeds,
            self.playlists_to_add,
            self.playlists_to_edit,
            self.playlists_to_remove,
            self.photo_plan and self.photo_plan.has_changes,
        ])

    @property
    def has_integrity_housekeeping(self) -> bool:
        """Whether execution has non-database integrity cleanup to perform."""
        report = self.integrity_report
        return bool(
            self._mapping_requires_persistence
            or (report and getattr(report, "orphan_files", ()))
        )

    @property
    def integrity_change_count(self) -> int:
        """Number of automatic integrity actions represented by this plan."""
        report = self.integrity_report
        if report is None:
            return len(self._integrity_removals)
        return (
            len(getattr(report, "missing_files", ()))
            + len(getattr(report, "stale_mappings", ()))
            + len(getattr(report, "orphan_files", ()))
            + int(bool(getattr(report, "mapping_rebuild_required", False)))
        )

    @property
    def has_duplicates(self) -> bool:
        return bool(self.duplicates)

    @property
    def duplicate_count(self) -> int:
        return sum(len(t) - 1 for t in self.duplicates.values())

    @property
    def summary(self) -> str:
        track_add_bytes = sum(item.planned_add_size for item in self.to_add)
        track_remove_bytes = sum(item.planned_remove_size for item in self.to_remove)
        track_update_bytes = sum(item.planned_add_size for item in self.to_update_file)

        lines = []
        if self.to_add:
            lines.append(f"  📥 {len(self.to_add)} tracks to add ({_fmt_bytes(track_add_bytes)})")
        if self.to_remove:
            lines.append(f"  🗑️  {len(self.to_remove)} tracks to remove ({_fmt_bytes(track_remove_bytes)})")
        if self.to_update_file:
            lines.append(f"  🔄 {len(self.to_update_file)} tracks to re-sync ({_fmt_bytes(track_update_bytes)})")
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
        if self.photo_plan:
            if self.photo_plan.photos_to_add:
                lines.append(f"  🖼️  {len(self.photo_plan.photos_to_add)} photos to add")
            if self.photo_plan.photos_to_remove:
                lines.append(f"  🗑️  {len(self.photo_plan.photos_to_remove)} photos to remove")
            if self.photo_plan.albums_to_add:
                lines.append(f"  📚 {len(self.photo_plan.albums_to_add)} photo albums to add")
            if self.photo_plan.albums_to_remove:
                lines.append(f"  🗂️  {len(self.photo_plan.albums_to_remove)} photo albums to remove")
        if self.duplicates:
            lines.append(f"  ⚠️  {len(self.duplicates)} duplicate groups ({self.duplicate_count} extra files skipped)")
        if self.unresolved_collisions:
            lines.append(f"  ❓ {len(self.unresolved_collisions)} unresolved fingerprint collisions")

        integrity_lines = []
        if self.integrity_report and not self.integrity_report.is_clean:
            ir = self.integrity_report
            if ir.missing_files:
                integrity_lines.append(
                    f"  🔧 {len(ir.missing_files)} DB tracks with missing files will be removed"
                )
            if ir.stale_mappings:
                integrity_lines.append(
                    f"  🔧 {len(ir.stale_mappings)} stale mapping entries will be cleaned"
                )
            if ir.orphan_files:
                integrity_lines.append(
                    f"  🔧 {len(ir.orphan_files)} orphan files will be removed from iPod"
                )
            if getattr(ir, "mapping_rebuild_required", False):
                integrity_lines.append(
                    "  🔧 The corrupt iOpenPod mapping will be backed up and rebuilt"
                )

        if not lines and not integrity_lines:
            return "✅ Everything is in sync!"

        header = (
            f"Sync Plan ({self.matched_tracks} matched, "
            f"{self.total_pc_tracks} PC, {self.total_ipod_tracks} iPod):"
        )
        all_lines = integrity_lines + lines
        return header + "\n" + "\n".join(all_lines)


def sync_plan_required_free_bytes(
    plan: Any,
    *,
    db_overhead_bytes: int = SYNC_DB_OVERHEAD_BYTES,
    allocation_unit_size: int | None = None,
) -> int:
    """Estimate free bytes needed before starting an executable sync plan."""

    storage = getattr(plan, "storage", None)
    bytes_to_add = _coerce_nonnegative_int(getattr(storage, "bytes_to_add", 0))
    bytes_to_remove = _coerce_nonnegative_int(
        getattr(storage, "bytes_to_remove", 0)
    )

    if allocation_unit_size:
        add_items = tuple(getattr(plan, "to_add", ()) or ())
        logical_track_add = sum(
            _coerce_nonnegative_int(getattr(item, "planned_add_size", 0))
            for item in add_items
        )
        allocated_track_add = sum(
            allocated_size(
                _coerce_nonnegative_int(getattr(item, "planned_add_size", 0)),
                allocation_unit_size,
            )
            for item in add_items
        )
        unitemized_add = max(0, bytes_to_add - logical_track_add)
        bytes_to_add = allocated_track_add + allocated_size(
            unitemized_add,
            allocation_unit_size,
        )

    update_growth = 0
    for item in getattr(plan, "to_update_file", ()) or ():
        if allocation_unit_size:
            new_size = allocated_size(
                _coerce_nonnegative_int(getattr(item, "planned_add_size", 0)),
                allocation_unit_size,
            )
            old_size = allocated_size(
                _coerce_nonnegative_int(getattr(item, "planned_remove_size", 0)),
                allocation_unit_size,
            )
            update_growth += max(0, new_size - old_size)
        else:
            update_growth += _coerce_nonnegative_int(
                getattr(item, "planned_update_growth", 0)
            )

    deferred_remove_bytes = 0
    for item in getattr(plan, "to_remove", ()) or ():
        if bool(getattr(item, "is_deferred_removal", False)):
            deferred_remove_bytes += _coerce_nonnegative_int(
                getattr(item, "planned_remove_size", 0)
            )

    removable_credit = max(0, bytes_to_remove - deferred_remove_bytes)
    return max(
        0,
        bytes_to_add
        - removable_credit
        + update_growth
        + allocated_size(
            _coerce_nonnegative_int(db_overhead_bytes),
            allocation_unit_size,
        ),
    )


@dataclass
class SyncProgress:
    """Progress info for sync callbacks."""

    stage: str
    current: int
    total: int
    current_item: SyncItem | None = None
    message: str = ""
    worker_lines: list[str] | None = None
    size_progress: float | None = None


@dataclass
class SyncOutcome:
    """Result of a sync operation."""

    success: bool
    tracks_added: int = 0
    tracks_removed: int = 0
    tracks_updated_metadata: int = 0
    tracks_updated_file: int = 0
    playcounts_synced: int = 0
    ratings_synced: int = 0
    photos_added: int = 0
    photos_removed: int = 0
    photos_updated: int = 0
    photo_albums_added: int = 0
    photo_albums_removed: int = 0
    sound_check_computed: int = 0
    scrobbles_submitted: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    partial_save: bool = False

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
            lines.append(
                f"  Updated metadata for {self.tracks_updated_metadata} tracks"
            )
        if self.tracks_updated_file:
            lines.append(f"  Re-synced {self.tracks_updated_file} tracks")
        if self.playcounts_synced:
            lines.append(f"  Synced play counts for {self.playcounts_synced} tracks")
        if self.ratings_synced:
            lines.append(f"  Synced ratings for {self.ratings_synced} tracks")
        if self.photos_added:
            lines.append(f"  Added {self.photos_added} photos")
        if self.photos_removed:
            lines.append(f"  Removed {self.photos_removed} photos")
        if self.photos_updated:
            lines.append(f"  Updated {self.photos_updated} device photo views")
        if self.photo_albums_added:
            lines.append(f"  Added {self.photo_albums_added} photo albums")
        if self.photo_albums_removed:
            lines.append(f"  Removed {self.photo_albums_removed} photo albums")
        if self.sound_check_computed:
            lines.append(
                f"  Computed Sound Check for {self.sound_check_computed} tracks"
            )
        if self.scrobbles_submitted:
            lines.append(f"  Scrobbled {self.scrobbles_submitted} plays")
        if self.errors:
            lines.append(f"  {len(self.errors)} errors occurred")

        if not lines:
            return "No changes made."

        if self.partial_save:
            status = "Sync stopped early - partial results saved"
        elif self.success:
            status = "Sync completed"
        else:
            status = "Sync completed with errors"
        return f"{status}:\n" + "\n".join(lines)


@dataclass(frozen=True)
class SyncRequest:
    """Typed execution request passed into the sync executor boundary."""

    plan: SyncPlan
    mapping: MappingFile
    progress_callback: Callable[[SyncProgress], None] | None = None
    dry_run: bool = False
    is_cancelled: Callable[[], bool] | None = None
    write_back_to_pc: bool = False
    on_sync_complete: Callable[[], None] | None = None
    compute_sound_check: bool = False
    scrobble_on_sync: bool = False
    listenbrainz_token: str = ""
    listenbrainz_username: str = ""
    is_scrobble_cancelled: Callable[[], bool] | None = None
    on_cancel_with_partial: Callable[[int, int], bool] | None = None
    sync_until_full: bool = False
    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""
    lastfm_session_key: str = ""
    lastfm_username: str = ""
