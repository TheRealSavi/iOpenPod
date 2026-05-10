"""Public sync boundary DTOs shared by app-core and sync services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .fingerprint_diff_engine import SyncItem, SyncPlan
from .mapping import MappingFile


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
    user_playlists: tuple[dict, ...] = ()
    on_sync_complete: Callable[[], None] | None = None
    compute_sound_check: bool = False
    scrobble_on_sync: bool = False
    listenbrainz_token: str = ""
    listenbrainz_username: str = ""
    is_scrobble_cancelled: Callable[[], bool] | None = None
    on_cancel_with_partial: Callable[[int, int], bool] | None = None
