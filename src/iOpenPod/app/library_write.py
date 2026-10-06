"""Immutable write-workflow messages, independent of controllers and Qt."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from iOpenPod.app.media.importing import LibraryMediaSource
    from iOpenPod.app.media.progress import MediaPreparationProgress
    from iOpenPod.app.models.device import ActiveIPod
    from iPodDB.library import (
        ArtworkAsset,
        ArtworkPixels,
        ArtworkRead,
        LibrarySnapshot,
        LibraryWritePlan,
        LibraryWriteResult,
        PreparedPhoto,
        WriteIssue,
        WriteResources,
    )


class PreparationCancelledError(Exception):
    """The caller stopped work at a checkpoint before publication."""


@dataclass(frozen=True, slots=True)
class RockboxMediaUpdate:
    """Retag one retained iPod media file without replacing its audio payload."""

    track_id: int
    artwork: ArtworkPixels | None
    preserve_artwork: bool = False
    artwork_read: ArtworkRead | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class LibraryPreparationRequest:
    """Capture desired state and its application source together exactly once.

    The coordinator binds this snapshot to the retained iPodDB source only after
    checking ``source``. Workspace revisions identify the edit being reviewed;
    they are not the iPodDB source revision or permission to save device files.
    """

    snapshot: LibrarySnapshot
    source: ActiveIPod
    workspace_generation: int
    workspace_revision: int
    delete_omissions: bool = field(default=False, kw_only=True)
    artwork: tuple[ArtworkAsset, ...] = field(default=(), kw_only=True)
    media: tuple[LibraryMediaSource, ...] = field(default=(), kw_only=True)
    replace_media: tuple[int, ...] = field(default=(), kw_only=True)
    rockbox_media: tuple[RockboxMediaUpdate, ...] = field(default=(), kw_only=True)
    rockbox_metadata: bool = field(default=False, kw_only=True)
    photos: tuple[PreparedPhoto, ...] = field(default=(), kw_only=True)
    replace_photos: tuple[int, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class WriteItemProgress:
    """One active item's display identity and activity; confers no file authority."""

    item_id: str
    name: str
    progress: MediaPreparationProgress


@dataclass(frozen=True, slots=True)
class WriteProgress:
    """An entered stage, not proof that the stage completed successfully.

    ``completed`` and ``total`` describe the current stage only. They are
    optional because validation and database phases do not always have a useful
    item count. ``current_item`` is a human-readable identity for the item
    most recently started or completed by the stage; it is deliberately not a
    permission-bearing path.

    ``active_items`` is the complete immutable snapshot of currently running Host
    preparations. It excludes waiting and finished items; measurements describe
    each item's current phase rather than readiness for publication.
    """

    phase: str
    message: str
    completed: int | None = None
    total: int | None = None
    current_item: str = ""
    unit: str = ""
    active_items: tuple[WriteItemProgress, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class WriteTraceEvent:
    phase: str
    message: str
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class LibraryFileChange:
    """Reviewable file effects; these descriptions confer no save authority."""

    path: str
    action: Literal["write", "remove"]
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LibraryReview:
    plan: LibraryWritePlan | None
    result: LibraryWriteResult
    resources: WriteResources | None = field(default=None, kw_only=True)
    file_changes: tuple[LibraryFileChange, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class LibrarySaveResult:
    issues: tuple[WriteIssue, ...]
    active: ActiveIPod | None = None
    recovery_path: str = ""


class LibraryPreparationService(Protocol):
    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibraryReview: ...

    def save_library(
        self,
        review: LibraryReview,
        expected: ActiveIPod,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
    ) -> LibrarySaveResult: ...
