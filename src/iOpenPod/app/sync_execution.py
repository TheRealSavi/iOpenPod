"""Execute reviewed Sync intent through one verified Library/Storage transaction."""

from __future__ import annotations

import hashlib
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from threading import Event, Lock
from typing import TYPE_CHECKING
from uuid import uuid4

from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.host_media_fingerprint import FpcalcError, FpcalcFingerprinter
from iOpenPod.app.host_media_library import HostMediaFileKind
from iOpenPod.app.library_sync_helper import SyncDetails, SyncedImage, SyncedTrack
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    PreparationCancelledError,
    WriteItemProgress,
    WriteProgress,
)
from iOpenPod.app.media.importing import (
    ImportedSong,
    LibraryMediaSource,
    relocate_song,
)
from iOpenPod.app.media.music_paths import MusicPathAllocator
from iOpenPod.app.media.photo_sync import (
    MAX_PHOTO_SOURCE_BYTES,
    photo_library_with_asset,
    photo_still_from_stream,
    prepare_sync_photo,
)
from iOpenPod.app.media.progress import MediaPreparationPhase, MediaPreparationProgress
from iOpenPod.app.media.sync_artwork import capture_sync_artwork
from iOpenPod.app.media.transcoding import MediaTranscoder, TranscodeSettings
from iOpenPod.app.podcasts.media import download_episode, episode_track
from iOpenPod.app.podcasts.sync_artwork import prepare_podcast_covers
from iOpenPod.app.podcasts.sync_preparation import (
    history_after_podcast_sync,
    prepare_podcast_sync,
)
from iOpenPod.app.scrobbling.models import Account, ScrobbleError
from iOpenPod.app.services.device_coordinator import (
    SyncCleanupCompletedError,
    SyncRecoveryRequiredError,
    SyncRestoredCleanupPendingError,
)
from iOpenPod.app.sync_plan import (
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
    host_path_identity,
    prepare_sync_plan,
)
from iOpenPod.app.tag_normalizer import normalize_tags, tag_profile
from iOpenPod.app.track_playback_policy import (
    enforce_library_playback_policy,
    enforce_track_playback_policy,
)
from iPodDB.library import (
    ArtworkAsset,
    ArtworkPixels,
    AudioEncoding,
    FileDependency,
    IssueSeverity,
    MediaKind,
    MediaType,
    PhotoPixelFormat,
    PhotoThumbnailFormat,
    Playlist,
    PlaylistKind,
    PreparedPhoto,
    Track,
    WriteIssue,
    content_chunks,
    edit_track_metadata,
    playlist_entries,
    prepared_audio,
    prepared_video,
)
from storage import DeviceEntryKind, DevicePath, StorageError
from storage.content_workspace import StagedContent, content_workspace
from storage.host_input import LocalHostFile
from storage.media_processing import available_compute_threads

_PHOTO_MEMORY_BUDGET = 512 * 1024 * 1024

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from iOpenPod.app.host_media_library import HostMediaLibrary, HostMediaSource
    from iOpenPod.app.library_sync_helper import IPodMediaLibrary
    from iOpenPod.app.media.transcoding import PreparedTranscode
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.podcasts.models import PodcastEpisode
    from iOpenPod.app.podcasts.sync import (
        PodcastEpisodeAddition,
        PodcastSyncPlan,
        PodcastSyncRequest,
    )
    from iOpenPod.app.podcasts.sync_preparation import PreparedPodcastSync
    from iOpenPod.app.scrobbling.service import ScrobbleService
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from iOpenPod.app.sync_plan import SyncPlan
    from storage.media_processing import MediaTools


class SyncExecutionStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class SyncOptions:
    compute_sound_check: bool = False
    normalize_tags: bool = False
    rotate_tall_photos: bool = False
    fit_thumbnails: bool = False
    rockbox_metadata: bool = False
    scrobble: bool = True


@dataclass(frozen=True, slots=True)
class PlaylistSyncChange:
    name: str
    action: str
    added_count: int
    removed_count: int
    order_changed: bool


@dataclass(frozen=True, slots=True)
class SyncExecutionRequest:
    plan: SyncPlan
    host: HostMediaLibrary
    ipod: IPodMediaLibrary
    source: ActiveIPod
    workspace_generation: int
    workspace_revision: int
    settings: TranscodeSettings = field(default_factory=TranscodeSettings)
    options: SyncOptions = field(default_factory=SyncOptions)
    reconcile_playlists: bool = True
    podcasts: PodcastSyncRequest | None = None
    scrobble_accounts: tuple[Account, ...] = ()


@dataclass(frozen=True, slots=True)
class SyncExecutionResult:
    status: SyncExecutionStatus
    active: ActiveIPod | None = None
    completed: tuple[SyncPlanItem, ...] = ()
    issues: tuple[WriteIssue, ...] = ()
    recovery_path: str = ""
    helper: IPodMediaLibrary | None = None
    playlist_change_count: int = 0


@dataclass(slots=True)
class _PreparedTrack:
    item: SyncPlanItem
    song: ImportedSong
    provenance: SyncedTrack
    resources: ExitStack
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PreparedPhoto:
    item: SyncPlanItem
    asset: PreparedPhoto
    provenance: SyncedImage


@dataclass(frozen=True, slots=True)
class _PreparedPodcast:
    item: SyncPlanItem
    song: ImportedSong
    replaces_track_id: int | None = None
    subscription_id: str = ""
    acoustic_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class _PodcastArtworkRepair:
    item: SyncPlanItem
    pixels: ArtworkPixels


class SyncExecutor:
    """Keep CPU work on the Host and publish sequentially over the USB 2.0 bus."""

    def __init__(
        self,
        coordinator: DeviceCoordinator,
        *,
        transcoder: MediaTranscoder | None = None,
        workers: int | None = None,
        scrobbler: ScrobbleService | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._scrobbler = scrobbler
        self._transcoder = transcoder or MediaTranscoder()
        self._default_transcoder = transcoder is None
        self._workers = (
            max(1, min(16, available_compute_threads())) if workers is None else workers
        )
        if self._workers < 1:
            raise ValueError("Sync needs at least one preparation worker.")

    def execute(
        self,
        request: SyncExecutionRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> SyncExecutionResult:
        issues: list[WriteIssue] = []
        committed_result: SyncExecutionResult | None = None

        def checkpoint() -> None:
            if cancelled.is_set():
                raise PreparationCancelledError

        try:
            checkpoint()
            progress(
                WriteProgress("sync.validate", "Validating the selected Sync Plan…")
            )
            _validate_plan(request)
            self._validate_sources(request, checkpoint)
            if request.options.scrobble and request.scrobble_accounts:
                progress(
                    WriteProgress("sync.scrobble", "Scrobbling pending iPod plays…")
                )
                try:
                    if self._scrobbler is None:
                        raise ScrobbleError("The scrobbling service is unavailable.")
                    scrobbles = self._scrobbler.run(
                        request.source,
                        request.scrobble_accounts,
                        cancelled,
                        lambda message: progress(
                            WriteProgress("sync.scrobble", message)
                        ),
                    )
                except (ScrobbleError, OSError, StorageError) as error:
                    return SyncExecutionResult(
                        SyncExecutionStatus.FAILED,
                        issues=(
                            WriteIssue(
                                "sync.scrobble_capture_failed",
                                "Pending plays could not be safely retained. Sync stopped before changing the iPod.",
                                detail=exception_text(error),
                            ),
                        ),
                    )
                progress(WriteProgress("sync.scrobble", scrobbles.summary))
                if scrobbles.notices:
                    issues.append(
                        WriteIssue(
                            "sync.scrobble_dates_adjusted",
                            scrobbles.summary,
                            severity=IssueSeverity.INFO,
                            detail="\n".join(scrobbles.notices),
                        )
                    )
                if scrobbles.issues or scrobbles.skipped:
                    issues.append(
                        WriteIssue(
                            "sync.scrobble_pending",
                            scrobbles.summary,
                            severity=IssueSeverity.WARNING,
                            detail="\n".join(scrobbles.issues),
                        )
                    )
                checkpoint()
            podcast_plan = None
            podcast_sync = None
            if request.podcasts is not None:
                progress(
                    WriteProgress(
                        "sync.podcasts",
                        "Refreshing Podcasts and preparing their Sync settings…",
                    )
                )
                podcast_sync = prepare_podcast_sync(
                    request.podcasts, request.source, self._coordinator, checkpoint
                )
                podcast_plan = podcast_sync.plan
                issues.extend(podcast_plan.issues)
                # Reviewed Host changes take precedence over automatic Podcast policy.
                affected = {
                    item.ipod_id
                    for item in request.plan.items
                    if item.media_kind is SyncPlanMediaKind.TRACK
                    and item.action
                    in (
                        SyncPlanAction.REMOVE,
                        SyncPlanAction.UPDATE,
                        SyncPlanAction.UNCHANGED,
                    )
                }
                podcast_plan = replace(
                    podcast_plan,
                    additions=tuple(
                        addition
                        for addition in podcast_plan.additions
                        if addition.replaces_track_id is None
                        or addition.replaces_track_id not in affected
                    ),
                    removals=tuple(
                        identity
                        for identity in podcast_plan.removals
                        if identity not in affected
                    ),
                )
            podcast_changes = (
                len(podcast_plan.additions)
                + len(podcast_plan.removals)
                + sum(
                    addition.replaces_track_id is not None
                    for addition in podcast_plan.additions
                )
                if podcast_plan is not None
                else 0
            )
            requested_playlists = (
                preview_playlist_sync(
                    request.plan, request.host, request.ipod, request.source
                )
                if request.reconcile_playlists
                else ()
            )
            track_jobs = sum(
                item.media_kind is SyncPlanMediaKind.TRACK
                and item.action in (SyncPlanAction.ADD, SyncPlanAction.UPDATE)
                for item in request.plan.items
            ) + (len(podcast_plan.additions) if podcast_plan is not None else 0)
            if self._default_transcoder:
                self._transcoder = MediaTranscoder(
                    threads_per_job=max(
                        1,
                        available_compute_threads()
                        // min(self._workers, track_jobs or 1),
                    )
                )
            with ExitStack() as resources:
                prepared: list[_PreparedTrack] = []
                podcast_tracks: list[_PreparedPodcast] = []
                if track_jobs:
                    progress(
                        WriteProgress(
                            "sync.tools",
                            "Checking tools needed to prepare the selected Tracks…",
                        )
                    )
                    try:
                        tools = self._transcoder.preflight(checkpoint=checkpoint)
                    except PreparationCancelledError:
                        raise
                    except (OSError, StorageError) as error:
                        issues.append(
                            WriteIssue(
                                "sync.tools_unavailable",
                                source_text(
                                    "{count} selected Tracks could not be prepared. Their existing iPod copies were kept; independent Photo and removal changes can continue.",
                                    count=f"{track_jobs:,}",
                                ),
                                detail=exception_text(error),
                            )
                        )
                    else:
                        prepared, failures = self._prepare_tracks(
                            request, tools, resources, progress, checkpoint
                        )
                        issues.extend(failures)
                        if podcast_plan is not None:
                            podcast_tracks, failures = self._prepare_podcasts(
                                request,
                                podcast_plan,
                                tools,
                                resources,
                                progress,
                                checkpoint,
                                tuple(
                                    item.song.track.metadata.location
                                    for item in prepared
                                ),
                            )
                            issues.extend(failures)
                checkpoint()
                issues.extend(_capture_artwork(request, prepared, checkpoint))
                podcast_artwork_repairs: tuple[_PodcastArtworkRepair, ...] = ()
                if podcast_sync is not None and podcast_plan is not None:
                    podcast_tracks, podcast_artwork_repairs, cover_issues = (
                        _capture_podcast_artwork(
                            request,
                            podcast_sync,
                            podcast_plan,
                            podcast_tracks,
                            progress,
                            checkpoint,
                        )
                    )
                    issues.extend(cover_issues)
                    podcast_changes += len(podcast_artwork_repairs)
                photos, photo_issues = self._prepare_photos(
                    request, progress, checkpoint, resources
                )
                issues.extend(photo_issues)
                stable: list[_PreparedTrack] = []
                stable_photos: list[_PreparedPhoto] = []
                sources = {
                    host_path_identity(str(source.path)): source
                    for source in request.host.sources
                }
                candidates: tuple[_PreparedTrack | _PreparedPhoto, ...] = (
                    *prepared,
                    *photos,
                )
                for result in candidates:
                    source = sources[host_path_identity(result.item.host_path or "")]
                    try:
                        _validate_host_source(source)
                    except (OSError, ValueError, StorageError) as error:
                        issues.append(
                            WriteIssue(
                                "sync.source_changed",
                                source_text(
                                    "{name} changed during preparation "
                                    "and was skipped. Rescan this source before retrying.",
                                    name=result.item.name,
                                ),
                                detail=exception_text(error),
                            )
                        )
                    else:
                        if isinstance(result, _PreparedTrack):
                            stable.append(result)
                        else:
                            stable_photos.append(result)
                prepared = stable
                photos = tuple(stable_photos)
                playlist_sources_valid = _validate_playlist_sources(
                    request, issues, checkpoint
                )
                draft_request = (
                    request
                    if playlist_sources_valid
                    else replace(request, reconcile_playlists=False)
                )
                draft, completed, library_changed = _draft(
                    draft_request,
                    prepared,
                    issues,
                    photos,
                    tuple(podcast_tracks),
                    podcast_plan.removals if podcast_plan is not None else (),
                    podcast_artwork_repairs,
                )
                playlist_changes = (
                    _playlist_changes(
                        _playlist_baseline(
                            request,
                            frozenset(
                                track.track_id for track in draft.snapshot.tracks
                            ),
                        ),
                        draft.snapshot.playlists,
                    )
                    if draft_request.reconcile_playlists
                    else ()
                )
                skipped_playlists = {
                    (change.name, change.action) for change in requested_playlists
                } - {(change.name, change.action) for change in playlist_changes}
                if skipped_playlists:
                    issues.append(
                        WriteIssue(
                            "sync.playlist_changes_skipped",
                            source_text(
                                "{count} reviewed Playlist change(s) could not "
                                "be applied. Resolve the reported source or Track problem, "
                                "then rescan and review the remaining Playlist changes.",
                                count=str(len(skipped_playlists)),
                            ),
                            severity=IssueSeverity.WARNING,
                        )
                    )
                if not completed and not library_changed:
                    requested_changes = bool(
                        request.plan.change_count
                        or requested_playlists
                        or podcast_changes
                        or any(
                            issue.severity is IssueSeverity.ERROR for issue in issues
                        )
                    )
                    return SyncExecutionResult(
                        SyncExecutionStatus.FAILED
                        if requested_changes
                        else SyncExecutionStatus.SUCCESS,
                        active=request.source if not requested_changes else None,
                        issues=tuple(issues),
                    )
                # A source edited during Host computation must never be published
                # against the older Review, even if its temporary result is valid.
                self._validate_sources(request, checkpoint)
                podcast_history = (
                    history_after_podcast_sync(
                        podcast_sync, podcast_plan, draft.snapshot
                    )
                    if podcast_sync is not None and podcast_plan is not None
                    else None
                )
                review = (
                    self._coordinator.prepare_library(
                        draft, progress, cancelled, podcast_state=podcast_history
                    )
                    if podcast_history is not None
                    else self._coordinator.prepare_library(draft, progress, cancelled)
                )
                issues.extend(review.result.issues)
                checkpoint()
                if review.result.prepared is None:
                    return SyncExecutionResult(
                        SyncExecutionStatus.FAILED, issues=tuple(issues)
                    )
                saved = self._coordinator.save_library(
                    review, request.source, progress, cancelled, retain_recovery=True
                )
                issues.extend(saved.issues)
                if saved.active is None:
                    return self._failed_save(
                        request, saved.recovery_path, issues, cancelled, progress
                    )
                if cancelled.is_set():
                    issues.append(
                        WriteIssue(
                            "sync.cancellation_after_publication",
                            "Cancellation arrived after publication began. Sync finished and "
                            "verified the selected changes to keep the iPod Library consistent.",
                            severity=IssueSeverity.WARNING,
                        )
                    )
                # Cancellation after publication cannot turn a verified commit into
                # failure. Finish its lightweight provenance update before returning.
                helper = None
                try:
                    progress(
                        WriteProgress(
                            "sync.helper", "Recording successful Sync details…"
                        )
                    )
                    if (
                        request.plan.change_count
                        or requested_playlists
                        or podcast_changes
                    ):
                        helper = self._coordinator.publish_sync_success(
                            saved.active,
                            request.ipod
                            if request.reconcile_playlists or request.plan.items
                            else None,
                            (
                                *(item.provenance for item in prepared),
                                *(
                                    SyncedTrack(
                                        DevicePath(item.song.track.metadata.location),
                                        item.acoustic_fingerprint,
                                    )
                                    for item in podcast_tracks
                                    if item.acoustic_fingerprint
                                ),
                            ),
                            tuple(item.provenance for item in photos),
                        )
                        issues.extend(
                            WriteIssue(
                                "sync.helper_warning",
                                item.detail,
                                severity=IssueSeverity.WARNING,
                            )
                            for item in helper.issues
                        )
                except Exception as error:
                    issues.append(
                        WriteIssue(
                            "sync.helper_failed",
                            "Library changes were saved, but Sync history could not be updated. "
                            "Keep the iPod connected and rescan before another Sync.",
                            severity=IssueSeverity.WARNING,
                            detail=exception_text(error),
                        )
                    )
                partial = (
                    len(completed) < request.plan.change_count + podcast_changes
                    or bool(skipped_playlists)
                    or any(issue.severity is IssueSeverity.ERROR for issue in issues)
                )
                recovery_path = saved.recovery_path
                if recovery_path:
                    try:
                        progress(
                            WriteProgress(
                                "sync.cleanup", "Cleaning verified Sync recovery files…"
                            )
                        )
                        self._coordinator.finalize_sync_success(
                            saved.active, recovery_path
                        )
                        recovery_path = ""
                    except SyncCleanupCompletedError as error:
                        recovery_path = ""
                        issues.append(
                            WriteIssue(
                                "sync.cleanup_flush_pending",
                                "Sync succeeded and recovery files were removed, but the final "
                                "device flush could not be confirmed. Safely eject before unplugging.",
                                severity=IssueSeverity.WARNING,
                                detail=exception_text(error),
                            )
                        )
                    except Exception as error:
                        issues.append(
                            WriteIssue(
                                "sync.cleanup_pending",
                                "Sync succeeded, but recovery-file cleanup could not finish. "
                                "Keep the iPod connected and choose Retry Cleanup before unplugging.",
                                severity=IssueSeverity.WARNING,
                                detail=exception_text(error),
                                artifact=recovery_path,
                            )
                        )
                committed_result = SyncExecutionResult(
                    SyncExecutionStatus.PARTIAL
                    if partial
                    else SyncExecutionStatus.SUCCESS,
                    saved.active,
                    completed,
                    tuple(issues),
                    recovery_path,
                    helper,
                    len(playlist_changes),
                )
                # Preserve this result if ExitStack cleanup raises after the return.
                return committed_result  # noqa: RET504
        except SyncRecoveryRequiredError as error:
            return SyncExecutionResult(
                SyncExecutionStatus.RECOVERY_REQUIRED,
                issues=(
                    *issues,
                    WriteIssue(
                        "sync.recovery_required",
                        exception_text(error),
                        artifact=error.recovery_path,
                    ),
                ),
                recovery_path=error.recovery_path,
            )
        except PreparationCancelledError:
            return SyncExecutionResult(
                SyncExecutionStatus.CANCELLED,
                issues=(
                    *issues,
                    WriteIssue(
                        "sync.cancelled",
                        "Sync was cancelled before publication. "
                        "Temporary Host files were removed; the iPod Library is unchanged.",
                        severity=IssueSeverity.WARNING,
                    ),
                ),
            )
        except Exception as error:
            if committed_result is not None:
                return replace(
                    committed_result,
                    issues=(
                        *committed_result.issues,
                        WriteIssue(
                            "sync.host_cleanup_pending",
                            "Sync succeeded, but temporary Host files could not all be removed. "
                            "Close applications using the reported temporary files before removing them.",
                            severity=IssueSeverity.WARNING,
                            detail=exception_text(error),
                        ),
                    ),
                )
            return SyncExecutionResult(
                SyncExecutionStatus.FAILED,
                issues=(
                    *issues,
                    WriteIssue(
                        "sync.failed",
                        "Sync could not continue. Correct the reported problem "
                        "and rescan before trying again.",
                        detail=exception_text(error),
                    ),
                ),
            )

    def _failed_save(
        self,
        request: SyncExecutionRequest,
        recovery_path: str,
        issues: list[WriteIssue],
        cancelled: Event,
        progress: Callable[[WriteProgress], None],
    ) -> SyncExecutionResult:
        if recovery_path:
            try:
                progress(
                    WriteProgress(
                        "save.recovery.inspect",
                        "Sync could not finish. Checking recovery files before restoring the previous Library…",
                    )
                )
                self._coordinator.recover_failed_sync(
                    request.source, recovery_path, progress
                )
            except SyncRestoredCleanupPendingError as error:
                issues.append(
                    WriteIssue(
                        "sync.restored_cleanup_pending",
                        "The previous Library was restored and verified. Recovery files could not all be removed; retry recovery to finish cleanup before another Sync.",
                        detail=exception_text(error),
                        artifact=recovery_path,
                    )
                )
                return SyncExecutionResult(
                    SyncExecutionStatus.RECOVERY_REQUIRED,
                    issues=tuple(issues),
                    recovery_path=recovery_path,
                )
            except SyncCleanupCompletedError as error:
                issues.append(
                    WriteIssue(
                        "sync.cleanup_flush_pending",
                        "The previous Library was restored and recovery files were removed, "
                        "but the final device flush could not be confirmed. Safely eject before unplugging.",
                        severity=IssueSeverity.WARNING,
                        detail=exception_text(error),
                    )
                )
            except Exception as error:
                issues.append(
                    WriteIssue(
                        "sync.recovery_required",
                        "Sync was interrupted and its previous Library could not be restored. "
                        "Reconnect the same iPod and recover this transaction before further writes.",
                        detail=exception_text(error),
                        artifact=recovery_path,
                    )
                )
                return SyncExecutionResult(
                    SyncExecutionStatus.RECOVERY_REQUIRED,
                    issues=tuple(issues),
                    recovery_path=recovery_path,
                )
            issues.append(
                WriteIssue(
                    "sync.restored",
                    "The previous Library was restored and staged device files were cleaned up.",
                    severity=IssueSeverity.WARNING,
                )
            )
        return SyncExecutionResult(
            SyncExecutionStatus.CANCELLED
            if cancelled.is_set()
            else SyncExecutionStatus.FAILED,
            issues=tuple(issues),
        )

    def _validate_sources(
        self, request: SyncExecutionRequest, checkpoint: Callable[[], None]
    ) -> None:
        tracks = {item.track_id: item for item in request.ipod.tracks}
        images = {item.image_id: item for item in request.ipod.images}
        with self._coordinator.sync_session(request.source) as session:
            for item in request.plan.items:
                checkpoint()
                if item.action is SyncPlanAction.ATTENTION:
                    continue
                if item.ipod_id is not None:
                    recorded = (
                        tracks[item.ipod_id]
                        if item.media_kind is SyncPlanMediaKind.TRACK
                        else images[item.ipod_id]
                    )
                    actual = session.stat(recorded.path)
                    if (
                        actual.kind is not DeviceEntryKind.FILE
                        or actual.size != recorded.size_bytes
                        or not session.modified_time_matches(
                            actual.modified_ns, recorded.modified_ns
                        )
                    ):
                        raise ValueError(
                            source_text(
                                "{name}: the iPod file changed after scanning. Rescan the iPod before Sync.",
                                name=item.name,
                            )
                        )

    def _prepare_tracks(
        self,
        request: SyncExecutionRequest,
        tools: MediaTools,
        resources: ExitStack,
        progress: Callable[[WriteProgress], None],
        checkpoint: Callable[[], None],
    ) -> tuple[list[_PreparedTrack], list[WriteIssue]]:
        sources = {
            host_path_identity(str(item.path)): item for item in request.host.sources
        }
        host_tracks = request.host.snapshot.tracks
        if request.options.normalize_tags:
            host_tracks = _normalized_tracks(request, host_tracks, checkpoint)
        tracks = {
            host_path_identity(track.metadata.location): track for track in host_tracks
        }
        changes = [
            item
            for item in request.plan.items
            if item.media_kind is SyncPlanMediaKind.TRACK
            and item.action in (SyncPlanAction.ADD, SyncPlanAction.UPDATE)
        ]
        prepared: list[_PreparedTrack] = []
        issues: list[WriteIssue] = []
        cleanup_lock = Lock()
        activity_lock = Lock()
        activity_updated = Event()
        active: dict[SyncPlanItem, MediaPreparationProgress] = {}
        activity_changed = False
        preparation_order = {item: index for index, item in enumerate(changes)}
        completed = 0

        def snapshot() -> tuple[WriteItemProgress, ...]:
            with activity_lock:
                return tuple(
                    WriteItemProgress(
                        host_path_identity(item.host_path or ""),
                        item.name,
                        active[item],
                    )
                    for item in sorted(active, key=preparation_order.__getitem__)
                )

        def report_activity(
            item: SyncPlanItem, update: MediaPreparationProgress
        ) -> None:
            nonlocal activity_changed
            # Coalesce samples from each worker so slow consumers cannot accumulate
            # an unbounded queue. Only the executor thread publishes GUI messages.
            with activity_lock:
                active[item] = update
                activity_changed = True
                activity_updated.set()

        progress(
            WriteProgress(
                "sync.prepare",
                source_text(
                    "Preparing {count} selected Tracks on the Host…",
                    count=f"{len(changes):,}",
                ),
                completed=0,
                total=len(changes),
                unit="Tracks",
            )
        )

        def prepare(item: SyncPlanItem) -> _PreparedTrack:
            nonlocal activity_changed
            report_activity(
                item,
                MediaPreparationProgress(
                    MediaPreparationPhase.READING, "Starting Host media preparation"
                ),
            )
            try:
                result = self._prepare_one(
                    request,
                    item,
                    sources[host_path_identity(item.host_path or "")],
                    tracks[host_path_identity(item.host_path or "")],
                    tools,
                    checkpoint,
                    lambda update: report_activity(item, update),
                )
                # Register ownership inside the worker before the result is delivered.
                # Even a failed progress callback then closes every successful capture.
                # The executor joins workers before the outer ExitStack can close.
                with cleanup_lock:
                    resources.callback(result.resources.close)
                return result
            finally:
                with activity_lock:
                    active.pop(item, None)
                    activity_changed = True
                    activity_updated.set()

        # Independent preparation runs concurrently; publication uses the single
        # ordered Storage transaction, avoiding competing USB writers.
        with ThreadPoolExecutor(
            max_workers=min(self._workers, len(changes) or 1),
            thread_name_prefix="sync-media",
        ) as pool:
            futures = {pool.submit(prepare, item): item for item in changes}
            was_cancelled = False

            def finished() -> Generator[Future[_PreparedTrack]]:
                nonlocal activity_changed
                pending = set(futures)
                while pending:
                    activity_updated.wait(timeout=0.1)
                    activity_updated.clear()
                    done, pending = wait(
                        pending, timeout=0, return_when=FIRST_COMPLETED
                    )
                    with activity_lock:
                        changed = activity_changed
                        activity_changed = False
                    if changed:
                        items = snapshot()
                        progress(
                            WriteProgress(
                                "sync.prepare",
                                "Preparing selected Tracks on the Host…",
                                completed=completed,
                                total=len(changes),
                                current_item=items[-1].name if items else "",
                                unit="Tracks",
                                active_items=items,
                            )
                        )
                    yield from done

            for future in finished():
                item = futures[future]
                try:
                    result = future.result()
                except PreparationCancelledError:
                    was_cancelled = True
                except Exception as error:
                    issues.append(
                        WriteIssue(
                            "sync.item_failed",
                            source_text(
                                "{name} was skipped. Its existing iPod copy was kept. "
                                "Correct the source or encoder settings and retry.",
                                name=item.name,
                            )
                            if item.ipod_id is not None
                            else source_text(
                                "{name} was skipped. No iPod copy was added. "
                                "Correct the source or encoder settings and retry.",
                                name=item.name,
                            ),
                            subject="track",
                            record_id=item.ipod_id,
                            detail=exception_text(error),
                            artifact=item.host_path or "",
                        )
                    )
                else:
                    prepared.append(result)
                    issues.extend(
                        WriteIssue(
                            "sync.media_warning",
                            warning,
                            severity=IssueSeverity.INFO
                            if warning.startswith(
                                (
                                    "Re-encoding a lossy",
                                    "Resampled ",
                                    "Downmixed ",
                                    "Reduced lossless",
                                )
                            )
                            else IssueSeverity.WARNING,
                            artifact=item.host_path or "",
                        )
                        for warning in result.warnings
                    )
                completed += 1
                progress(
                    WriteProgress(
                        "sync.prepare",
                        source_text(
                            "Processed {completed} of {total} Tracks; {ready} ready, {skipped} skipped.",
                            completed=f"{completed:,}",
                            total=f"{len(changes):,}",
                            ready=f"{len(prepared):,}",
                            skipped=f"{completed - len(prepared):,}",
                        ),
                        completed=completed,
                        total=len(changes),
                        current_item=item.name,
                        unit="Tracks",
                        active_items=snapshot(),
                    )
                )
            if was_cancelled:
                raise PreparationCancelledError
        order = {item: index for index, item in enumerate(request.plan.items)}
        prepared.sort(key=lambda result: order[result.item])
        if not prepared:
            return prepared, issues
        allocated: list[_PreparedTrack] = []
        # Reserve destinations serially: CPU workers must not compete for USB
        # metadata reads. Even replaced/removed paths stay reserved until commit.
        with self._coordinator.sync_session(request.source) as session:
            allocator = MusicPathAllocator(
                request.source.profile.capabilities.database.music_directory_count,
                (track.metadata.location for track in request.source.library.tracks),
                exists=session.exists,
            )
            for result in prepared:
                checkpoint()
                try:
                    extension = result.song.source.media.file.relative_path.rsplit(
                        ".", 1
                    )[-1]
                    location = allocator.allocate(extension, checkpoint=checkpoint)
                    song = relocate_song(result.song, location)
                except (OSError, ValueError, StorageError) as error:
                    issues.append(
                        WriteIssue(
                            "sync.filename_failed",
                            source_text(
                                "{name} was skipped because an unused four-character "
                                "media filename could not be reserved. Its existing iPod copy was kept. "
                                "Resolve the reported Music-folder problem, then rescan and retry.",
                                name=result.item.name,
                            ),
                            subject="track",
                            record_id=result.item.ipod_id,
                            detail=exception_text(error),
                            artifact=result.item.host_path or "",
                        )
                    )
                else:
                    allocated.append(
                        replace(
                            result,
                            song=song,
                            provenance=replace(
                                result.provenance, path=DevicePath(location)
                            ),
                        )
                    )
        return allocated, issues

    def _prepare_podcasts(
        self,
        request: SyncExecutionRequest,
        plan: PodcastSyncPlan,
        tools: MediaTools,
        resources: ExitStack,
        progress: Callable[[WriteProgress], None],
        checkpoint: Callable[[], None],
        reserved: tuple[str, ...],
    ) -> tuple[list[_PreparedPodcast], list[WriteIssue]]:
        prepared: list[_PreparedPodcast] = []
        issues: list[WriteIssue] = []
        with self._coordinator.sync_session(request.source) as session:
            allocator = MusicPathAllocator(
                request.source.profile.capabilities.database.music_directory_count,
                (
                    *(
                        track.metadata.location
                        for track in request.source.library.tracks
                    ),
                    *reserved,
                ),
                exists=session.exists,
            )
            for index, addition in enumerate(plan.additions):
                checkpoint()
                episode = addition.episode
                item = _podcast_add_item(addition)

                def downloaded(
                    size: int, total: int | None, episode: PodcastEpisode = episode
                ) -> None:
                    progress(
                        WriteProgress(
                            "sync.podcast_download",
                            source_text("Downloading {title}…", title=episode.title)
                            if episode.title
                            else source_text("Downloading Podcast Episode…"),
                            completed=size,
                            total=total,
                            current_item=episode.title,
                            unit="bytes",
                        )
                    )

                def activity(
                    update: MediaPreparationProgress,
                    episode: PodcastEpisode = episode,
                    index: int = index,
                ) -> None:
                    progress(
                        WriteProgress(
                            "sync.podcast_prepare",
                            "Preparing Podcast media for the iPod…",
                            completed=index,
                            total=len(plan.additions),
                            current_item=episode.title,
                            unit="episodes",
                            active_items=(
                                WriteItemProgress(
                                    episode.episode_id, episode.title, update
                                ),
                            ),
                        )
                    )

                progress(
                    WriteProgress(
                        "sync.podcast_download",
                        source_text("Downloading {title}…", title=episode.title)
                        if episode.title
                        else source_text("Downloading Podcast Episode…"),
                        completed=0,
                        current_item=episode.title,
                        unit="bytes",
                    )
                )
                try:
                    with ExitStack() as lifetime:
                        source = lifetime.enter_context(
                            download_episode(
                                addition, checkpoint=checkpoint, progress=downloaded
                            )
                        )
                        track = episode_track(addition)
                        output = lifetime.enter_context(
                            self._transcoder.prepare(
                                source,
                                request.source.profile,
                                request.settings,
                                checkpoint=checkpoint,
                                spoken_word=True,
                                tools=tools,
                                metadata=track,
                                rockbox_metadata=request.options.rockbox_metadata,
                                normalize_tags=request.options.normalize_tags,
                                compute_sound_check=request.options.compute_sound_check,
                                progress=activity,
                            )
                        )
                        # Media kind follows inspected output, never the enclosure suffix.
                        track = replace(
                            output.metadata or track,
                            media_types=(
                                MediaType.VIDEO_PODCAST
                                if output.inspection.video_streams
                                else MediaType.PODCAST,
                            ),
                        )
                        song = _song(request, track, replace(output, metadata=track))
                        extension = song.source.media.file.relative_path.rsplit(".", 1)[
                            -1
                        ]
                        location = allocator.allocate(extension, checkpoint=checkpoint)
                        song = relocate_song(song, location)
                        acoustic_fingerprint = ""
                        progress(
                            WriteProgress(
                                "sync.podcast_fingerprint",
                                "Fingerprinting Podcast media…",
                                completed=index,
                                total=len(plan.additions),
                                current_item=episode.title,
                                unit="episodes",
                            )
                        )
                        try:
                            # Pass-through captures have no extension. Use the
                            # verified output format, not the publisher's filename.
                            acoustic_fingerprint = FpcalcFingerprinter(
                                input_suffix=f".{extension}"
                            ).fingerprint(output.source, checkpoint=checkpoint)
                        except (
                            FpcalcError,
                            OSError,
                            StorageError,
                            ValueError,
                        ) as error:
                            issues.append(
                                WriteIssue(
                                    "sync.podcast_fingerprint_unavailable",
                                    source_text(
                                        "{title} could not be fingerprinted. The Episode can still be added, "
                                        "but its acoustic matching evidence is unavailable.",
                                        title=episode.title,
                                    )
                                    if episode.title
                                    else source_text(
                                        "Podcast Episode could not be fingerprinted. The Episode can still be added, "
                                        "but its acoustic matching evidence is unavailable."
                                    ),
                                    severity=IssueSeverity.WARNING,
                                    detail=exception_text(error),
                                    artifact=episode.enclosure_url,
                                )
                            )
                        resources.callback(lifetime.pop_all().close)
                        prepared.append(
                            _PreparedPodcast(
                                item,
                                song,
                                addition.replaces_track_id,
                                addition.subscription.subscription_id,
                                acoustic_fingerprint,
                            )
                        )
                        issues.extend(
                            WriteIssue(
                                "sync.podcast_media_warning",
                                warning,
                                severity=IssueSeverity.INFO,
                                artifact=episode.enclosure_url,
                            )
                            for warning in output.warnings
                        )
                except PreparationCancelledError:
                    raise
                except Exception as error:
                    issues.append(
                        WriteIssue(
                            "sync.podcast_failed",
                            _podcast_add_failure_message(
                                episode.title,
                                replacing=addition.replaces_track_id is not None,
                            ),
                            detail=exception_text(error),
                            artifact=episode.enclosure_url,
                        )
                    )
        return prepared, issues

    def _prepare_one(
        self,
        request: SyncExecutionRequest,
        item: SyncPlanItem,
        source: HostMediaSource,
        track: Track,
        tools: MediaTools,
        checkpoint: Callable[[], None],
        activity: Callable[[MediaPreparationProgress], None],
    ) -> _PreparedTrack:
        checkpoint()
        _validate_host_source(source)
        with ExitStack() as lifetime:
            result = lifetime.enter_context(
                self._transcoder.prepare(
                    source.path,
                    request.source.profile,
                    request.settings,
                    checkpoint=checkpoint,
                    spoken_word=track.media_kind
                    in (MediaKind.PODCAST, MediaKind.AUDIOBOOK),
                    tools=tools,
                    metadata=track,
                    rockbox_metadata=request.options.rockbox_metadata,
                    normalize_tags=request.options.normalize_tags,
                    compute_sound_check=request.options.compute_sound_check,
                    progress=activity,
                )
            )
            if (
                result.original_fingerprint.size,
                result.original_fingerprint.modified_ns,
            ) != (source.size_bytes, source.modified_ns):
                raise ValueError(
                    "The Host file changed since its scan. Rescan before retrying."
                )
            song = _song(request, track, result)
            provenance = SyncedTrack(
                DevicePath(song.track.metadata.location),
                source.acoustic_fingerprint or "",
                SyncDetails(
                    datetime.now(UTC).isoformat(),
                    str(source.path),
                    source.size_bytes,
                    source.modified_ns,
                    source.path.path.suffix.lstrip(".").casefold(),
                    result.encoding.value,
                    result.was_transcoded,
                ),
            )
            return _PreparedTrack(
                item, song, provenance, lifetime.pop_all(), result.warnings
            )

    def _prepare_photos(
        self,
        request: SyncExecutionRequest,
        progress: Callable[[WriteProgress], None],
        checkpoint: Callable[[], None],
        resources: ExitStack,
    ) -> tuple[tuple[_PreparedPhoto, ...], tuple[WriteIssue, ...]]:
        changes = tuple(
            item
            for item in request.plan.items
            if item.media_kind is SyncPlanMediaKind.PHOTO
            and item.action in (SyncPlanAction.ADD, SyncPlanAction.UPDATE)
        )
        if not changes:
            return (), ()
        sources = {
            host_path_identity(str(source.path)): source
            for source in request.host.sources
        }
        library = request.source.library.photos
        originals = (
            {}
            if library is None
            else {photo.photo_id: photo for photo in library.photos}
        )
        used_ids = set(originals)
        if library is not None:
            used_ids.update(album.album_id for album in library.albums)
        next_id = max((100, *used_ids)) + 1
        formats = tuple(
            PhotoThumbnailFormat(
                item.format_id,
                item.width,
                item.height,
                item.row_bytes,
                PhotoPixelFormat(item.pixel_format.value),
            )
            for item in request.source.profile.capabilities.artwork.photo_formats
        )
        prepared: list[_PreparedPhoto] = []
        issues: list[WriteIssue] = []
        staging = resources.enter_context(
            content_workspace(memory_budget=_PHOTO_MEMORY_BUDGET, checkpoint=checkpoint)
        )
        progress(
            WriteProgress(
                "sync.photos",
                source_text(
                    "Preparing {count} selected Photos on the Host…",
                    count=f"{len(changes):,}",
                ),
                completed=0,
                total=len(changes),
                unit="Photos",
            )
        )
        # Decode one bounded image at a time; aggregate output can overflow to disk.
        for completed, item in enumerate(changes, 1):
            checkpoint()
            source = sources[host_path_identity(item.host_path or "")]
            try:
                _validate_host_source(source)
                progress(
                    WriteProgress(
                        "sync.photos",
                        "Reading and preparing this Photo…",
                        completed=completed - 1,
                        total=len(changes),
                        current_item=item.name,
                        unit="Photos",
                    )
                )
                observed = LocalHostFile.observe(source.path)
                converted = source.size_bytes > MAX_PHOTO_SOURCE_BYTES
                suffix = source.path.path.suffix.casefold()
                if converted:
                    with observed.open_read(checkpoint=checkpoint) as stream:
                        hasher = hashlib.sha256()
                        while chunk := stream.read(1024 * 1024):
                            hasher.update(chunk)
                        digest = hasher.hexdigest()
                        stream.seek(0)
                        data = photo_still_from_stream(stream)
                    suffix = ".png"
                else:
                    data = observed.read_bytes(
                        max_bytes=MAX_PHOTO_SOURCE_BYTES, checkpoint=checkpoint
                    )
                    digest = hashlib.sha256(data).hexdigest()
                if digest != source.content_sha256:
                    raise ValueError(
                        source_text(
                            "The Photo changed after scanning. Rescan this source before retrying."
                        )
                    )
                identity = (
                    item.ipod_id if item.action is SyncPlanAction.UPDATE else next_id
                )
                assert identity is not None
                if item.action is SyncPlanAction.ADD:
                    next_id += 1
                unique = uuid4()
                path = f"Photos/Full Resolution/iOpenPod/{unique.hex}{suffix}"
                asset = prepare_sync_photo(
                    data,
                    photo_id=identity,
                    original_relative_path=path,
                    thumbnail_shard=max(1, unique.int & 0xFFFFFFFF),
                    formats=formats,
                    rotate_tall_photos=request.options.rotate_tall_photos,
                    fit_thumbnails=request.options.fit_thumbnails,
                    original=originals.get(identity),
                )
                # Check the retained album shape before this item can enter the batch.
                photo_library_with_asset(library, asset)
                asset = replace(
                    asset,
                    files=tuple(
                        replace(
                            file, data=staging.store_chunks(content_chunks(file.data))
                        )
                        for file in asset.files
                    ),
                )
                if any(isinstance(file.data, StagedContent) for file in asset.files):
                    issues.append(
                        WriteIssue(
                            "sync.photo_disk_staging",
                            source_text(
                                'Photo "{path}" was prepared using temporary disk space because the memory budget was reached.',
                                path=str(source.path),
                            ),
                            severity=IssueSeverity.WARNING,
                            artifact=str(source.path),
                        )
                    )
                prepared.append(
                    _PreparedPhoto(
                        item,
                        asset,
                        SyncedImage(
                            DevicePath(path),
                            hashlib.sha256(data).hexdigest(),
                            SyncDetails(
                                datetime.now(UTC).isoformat(),
                                str(source.path),
                                source.size_bytes,
                                source.modified_ns,
                                source.path.path.suffix.lstrip("."),
                                suffix.lstrip("."),
                                converted,
                                host_content_sha256=digest,
                            ),
                        ),
                    )
                )
                if converted:
                    issues.append(
                        WriteIssue(
                            "sync.photo_converted",
                            "Prepared a still PNG from the first image frame for the iPod Photo viewer. The Host original is unchanged.",
                            severity=IssueSeverity.INFO,
                            artifact=str(source.path),
                        )
                    )
            except PreparationCancelledError:
                raise
            except Exception as error:
                issues.append(
                    WriteIssue(
                        "sync.photo_failed",
                        source_text(
                            "{name} was skipped. Its existing Photo was preserved. "
                            "Correct the source or device format problem and retry.",
                            name=item.name,
                        )
                        if item.ipod_id is not None
                        else source_text(
                            "{name} was skipped. No Photo was added. "
                            "Correct the source or device format problem and retry.",
                            name=item.name,
                        ),
                        subject="photo",
                        record_id=item.ipod_id,
                        detail=exception_text(error),
                        artifact=item.host_path or "",
                    )
                )
            progress(
                WriteProgress(
                    "sync.photos",
                    source_text(
                        "Processed {completed} of {total} Photos; {messages} messages.",
                        completed=f"{completed:,}",
                        total=f"{len(changes):,}",
                        messages=f"{len(issues):,}",
                    ),
                    completed=completed,
                    total=len(changes),
                    current_item=item.name,
                    unit="Photos",
                )
            )
        return tuple(prepared), tuple(issues)


def _podcast_add_failure_message(title: str, *, replacing: bool) -> str:
    if replacing:
        if title:
            return source_text(
                "{title} could not be added. The Episode awaiting replacement was kept. "
                "Refresh the Podcast and retry.",
                title=title,
            )
        return source_text(
            "Podcast Episode could not be added. The Episode awaiting replacement was kept. "
            "Refresh the Podcast and retry."
        )
    if title:
        return source_text(
            "{title} could not be added. Refresh the Podcast and retry.", title=title
        )
    return source_text(
        "Podcast Episode could not be added. Refresh the Podcast and retry."
    )


def _validate_plan(request: SyncExecutionRequest) -> None:
    comparison = prepare_sync_plan(request.host, request.ipod, request.source.library)
    allowed = set(comparison.items)
    allowed.update(
        replace(
            item,
            action=SyncPlanAction.REMOVE,
            basis=SyncPlanBasis.USER_DESELECTED,
            host_size_changed=False,
            host_modified_changed=False,
        )
        for item in comparison.items
        if item.ipod_id is not None
        and item.host_path is not None
        and item.action is not SyncPlanAction.ATTENTION
    )
    # Selection permits an explicit one-way Add when content matching is absent.
    allowed.update(
        replace(item, action=SyncPlanAction.ADD, basis=SyncPlanBasis.HOST_ONLY)
        for item in comparison.items
        if item.action is SyncPlanAction.ATTENTION
        and item.basis is SyncPlanBasis.MISSING_IDENTITY
        and item.media_kind is SyncPlanMediaKind.TRACK
        and item.host_path is not None
        and item.ipod_id is None
    )
    hosts: set[str] = set()
    devices: set[tuple[SyncPlanMediaKind, int]] = set()
    for item in request.plan.items:
        if item not in allowed:
            raise ValueError(
                "The selected Sync Plan no longer matches its scanned sources. Review a fresh plan."
            )
        if item.host_path is not None:
            key = host_path_identity(item.host_path)
            if key in hosts:
                raise ValueError("The selected Sync Plan repeats a Host source.")
            hosts.add(key)
        if item.ipod_id is not None:
            identity = (item.media_kind, item.ipod_id)
            if identity in devices:
                raise ValueError("The selected Sync Plan repeats an iPod identity.")
            devices.add(identity)


def _song(
    request: SyncExecutionRequest, host: Track, output: PreparedTranscode
) -> ImportedSong:
    host = output.metadata or host
    audio = next(iter(output.inspection.audio_streams), None)
    motion = next(iter(output.inspection.video_streams), None)
    extension, description = (
        {
            AudioEncoding.MP3: ("mp3", "MPEG audio file"),
            AudioEncoding.AAC: ("m4a", "AAC audio file"),
            AudioEncoding.ALAC: ("m4a", "Apple Lossless audio file"),
            AudioEncoding.WAV: ("wav", "WAV audio file"),
            AudioEncoding.AIFF: ("aiff", "AIFF audio file"),
        }[output.encoding]
        if isinstance(output.encoding, AudioEncoding)
        else ("m4v", "MPEG-4 video file")
    )
    location = MusicPathAllocator(
        request.source.profile.capabilities.database.music_directory_count
    ).allocate(extension)
    duration = (
        (motion.duration_seconds if motion is not None else None)
        or (audio.duration_seconds if audio is not None else None)
        or output.inspection.duration_seconds
    )
    if not duration or (audio is not None and not audio.sample_rate_hz):
        raise ValueError("Prepared media has no verified duration or sample rate.")
    if audio is None and motion is None:
        raise ValueError("Prepared media has no verified audio or motion-video stream.")
    track = replace(
        host,
        track_id=0,
        artwork_id=0,
        ipod=None,
        length_ms=max(1, round(duration * 1000)),
        size_bytes=output.inspection.fingerprint.size,
        bitrate_kbps=round(
            (
                output.inspection.bitrate_bps
                or (audio.bitrate_bps if audio is not None else None)
                or (motion.bitrate_bps if motion is not None else None)
                or 0
            )
            / 1000
        ),
        metadata=replace(
            host.metadata,
            location=location,
            file_format=description,
            sample_rate_hz=(audio.sample_rate_hz or 0) if audio is not None else 0,
            variable_bitrate=(
                host.metadata.variable_bitrate
                if output.variable_bitrate is None
                else output.variable_bitrate
            ),
            pregap=0 if output.was_transcoded else host.metadata.pregap,
            sample_count=0 if output.was_transcoded else host.metadata.sample_count,
            postgap=0 if output.was_transcoded else host.metadata.postgap,
            gapless=False if output.was_transcoded else host.metadata.gapless,
            normalization_gain_db=(
                output.normalization_gain_db
                if request.options.compute_sound_check
                and output.normalization_gain_db is not None
                else host.metadata.normalization_gain_db
            ),
            date_added=int(datetime.now(UTC).timestamp()),
            artwork_count=0,
            has_lyrics=False,
        ),
    )
    track = enforce_track_playback_policy(track)
    dependency = FileDependency(
        location, track.size_bytes, output.inspection.fingerprint.sha256
    )
    media = (
        prepared_audio(0, dependency, output.encoding)
        if isinstance(output.encoding, AudioEncoding)
        else prepared_video(
            0, dependency, has_audio=bool(output.inspection.audio_streams)
        )
    )
    return ImportedSong(
        track,
        LibraryMediaSource(
            output.source,
            output.inspection.fingerprint,
            media,
            display_path=host.metadata.location,
        ),
    )


def _draft(
    request: SyncExecutionRequest,
    prepared: list[_PreparedTrack],
    issues: list[WriteIssue],
    prepared_photos: tuple[_PreparedPhoto, ...] = (),
    prepared_podcasts: tuple[_PreparedPodcast, ...] = (),
    podcast_removals: tuple[int, ...] = (),
    podcast_artwork_repairs: tuple[_PodcastArtworkRepair, ...] = (),
) -> tuple[LibraryPreparationRequest, tuple[SyncPlanItem, ...], bool]:
    """Build desired state, completed actions, and whether implicit changes exist."""
    original = request.source.library
    tracks = {track.track_id: track for track in original.tracks}
    mapping = _retained_playlist_mapping(request)
    host_tracks = {
        host_path_identity(track.metadata.location): track.track_id
        for track in request.host.snapshot.tracks
    }
    replaced: list[int] = []
    media: list[LibraryMediaSource] = []
    artwork: list[ArtworkAsset] = []
    artwork_ids: dict[int, int] = {}

    def cover_identity(pixels: ArtworkPixels | None) -> int:
        if pixels is None:
            return 0
        identity = id(pixels)
        if identity not in artwork_ids:
            artwork_ids[identity] = -len(artwork_ids) - 1
            artwork.append(ArtworkAsset(artwork_ids[identity], pixels))
        return artwork_ids[identity]

    completed: list[SyncPlanItem] = []
    removed_photos: set[int] = set()
    next_track_id = min((0, *tracks)) - 1
    for result in prepared:
        item, song = result.item, result.song
        cover_id = cover_identity(song.artwork)
        if item.action is SyncPlanAction.UPDATE:
            assert item.ipod_id is not None
            identity = item.ipod_id
            old = tracks[identity]
            track = replace(
                song.track,
                track_id=identity,
                ipod=old.ipod,
                rating=old.rating,
                play_count=old.play_count,
                artwork_id=cover_id or old.artwork_id,
                metadata=replace(
                    song.track.metadata,
                    date_added=old.metadata.date_added,
                    last_played=old.metadata.last_played,
                    skip_count=old.metadata.skip_count,
                    last_skipped=old.metadata.last_skipped,
                    bookmark_time_ms=old.metadata.bookmark_time_ms,
                    artwork_count=old.metadata.artwork_count,
                    has_lyrics=old.metadata.has_lyrics,
                    normalization_gain_db=(
                        song.track.metadata.normalization_gain_db
                        if request.options.compute_sound_check
                        and song.track.metadata.normalization_gain_db is not None
                        else old.metadata.normalization_gain_db
                    ),
                ),
            )
            replaced.append(identity)
        else:
            identity = next_track_id
            next_track_id -= 1
            track = replace(song.track, track_id=identity, artwork_id=cover_id)
        tracks[identity] = track
        media.append(
            replace(song.source, media=replace(song.source.media, track_id=identity))
        )
        mapping[host_tracks[host_path_identity(item.host_path or "")]] = identity
        completed.append(item)
    podcast_removed = set(podcast_removals)
    for podcast in prepared_podcasts:
        identity = next_track_id
        next_track_id -= 1
        song = podcast.song
        tracks[identity] = replace(
            song.track, track_id=identity, artwork_id=cover_identity(song.artwork)
        )
        media.append(
            replace(song.source, media=replace(song.source.media, track_id=identity))
        )
        if podcast.replaces_track_id is not None:
            podcast_removed.add(podcast.replaces_track_id)
        completed.append(podcast.item)
    for identity in podcast_removed:
        track = tracks.pop(identity)
        completed.append(
            SyncPlanItem(
                SyncPlanAction.REMOVE,
                SyncPlanMediaKind.TRACK,
                SyncPlanBasis.IPOD_ONLY,
                track.title or "Podcast Episode",
                detail="Podcast Sync settings",
                ipod_path=track.metadata.location,
                ipod_id=identity,
            )
        )
    for item in request.plan.items:
        if (
            item.action is SyncPlanAction.UNCHANGED
            and item.media_kind is SyncPlanMediaKind.TRACK
        ):
            assert item.host_path is not None and item.ipod_id is not None
            mapping[host_tracks[host_path_identity(item.host_path)]] = item.ipod_id
        elif item.action is SyncPlanAction.REMOVE:
            assert item.ipod_id is not None
            if item.media_kind is SyncPlanMediaKind.TRACK:
                tracks.pop(item.ipod_id)
            else:
                removed_photos.add(item.ipod_id)
            completed.append(item)
    unresolved = tuple(
        item for item in request.plan.items if item.action is SyncPlanAction.ATTENTION
    )
    for repair in podcast_artwork_repairs:
        repair_identity = repair.item.ipod_id
        repair_track = (
            tracks.get(repair_identity) if repair_identity is not None else None
        )
        if repair_track is not None and repair_track.artwork_id == 0:
            tracks[repair_track.track_id] = replace(
                repair_track, artwork_id=cover_identity(repair.pixels)
            )
            completed.append(repair.item)
    if unresolved:
        issues.append(
            WriteIssue(
                "sync.needs_attention",
                source_text(
                    "{count} unmatched items were left unchanged. Their matching details remain available in Review.",
                    count=f"{len(unresolved):,}",
                ),
                severity=IssueSeverity.INFO,
            )
        )
    playlists, reconciled = _playlists(request, mapping, frozenset(tracks), issues)
    photos = original.photos
    removed_tracks = {track.track_id for track in original.tracks} - tracks.keys()
    for prepared_photo in prepared_photos:
        photos = photo_library_with_asset(photos, prepared_photo.asset)
        completed.append(prepared_photo.item)
    if photos is not None:
        photos = replace(
            photos,
            photos=tuple(
                photo for photo in photos.photos if photo.photo_id not in removed_photos
            ),
            albums=tuple(
                replace(
                    album,
                    photo_ids=tuple(
                        identity
                        for identity in album.photo_ids
                        if identity not in removed_photos
                    ),
                    music_track_id=album.music_track_id
                    if album.music_track_id not in removed_tracks
                    else None,
                    play_music=album.play_music
                    and album.music_track_id not in removed_tracks,
                )
                for album in photos.albums
            ),
        )
    desired = replace(
        original,
        tracks=_normalized_tracks(request, tuple(tracks.values()))
        if request.options.normalize_tags
        else tuple(tracks.values()),
        playlists=playlists,
        photos=photos,
    )
    normalized = enforce_library_playback_policy(desired)
    draft = LibraryPreparationRequest(
        normalized,
        request.source,
        request.workspace_generation,
        request.workspace_revision,
        delete_omissions=bool(podcast_removed)
        or any(item.action is SyncPlanAction.REMOVE for item in completed),
        media=tuple(media),
        artwork=tuple(artwork),
        replace_media=tuple(replaced),
        photos=tuple(item.asset for item in prepared_photos),
        replace_photos=tuple(
            item.asset.photo.photo_id
            for item in prepared_photos
            if item.item.action is SyncPlanAction.UPDATE
        ),
    )
    return draft, tuple(completed), reconciled or normalized != desired


def _podcast_add_item(addition: PodcastEpisodeAddition) -> SyncPlanItem:
    return SyncPlanItem(
        SyncPlanAction.ADD,
        SyncPlanMediaKind.TRACK,
        SyncPlanBasis.HOST_ONLY,
        addition.episode.title or "Podcast Episode",
        detail=addition.subscription.title,
        host_path=addition.episode.enclosure_url,
    )


def _normalized_tracks(
    request: SyncExecutionRequest,
    tracks: tuple[Track, ...],
    checkpoint: Callable[[], None] | None = None,
) -> tuple[Track, ...]:
    profile = request.source.profile
    suggestion = normalize_tags(
        tracks,
        tag_profile(
            profile.family,
            profile.generation,
            uses_sqlite=profile.capabilities.database.uses_sqlite_database,
        ),
        checkpoint=checkpoint,
    )
    updates = {update.track_id: update.edits for update in suggestion.updates}
    return tuple(
        edit_track_metadata(track, updates[track.track_id])
        if track.track_id in updates
        else track
        for track in tracks
    )


def _retained_playlist_mapping(request: SyncExecutionRequest) -> dict[int, int]:
    """Retain correlations when Review excludes an Update of an existing copy."""
    host_tracks = {
        host_path_identity(track.metadata.location): track.track_id
        for track in request.host.snapshot.tracks
    }
    included_paths = {
        host_path_identity(item.host_path)
        for item in request.plan.items
        if item.host_path is not None
    }
    mapping: dict[int, int] = {}
    for item in prepare_sync_plan(
        request.host, request.ipod, request.source.library
    ).items:
        if (
            item.host_path is not None
            and item.ipod_id is not None
            and item.media_kind is SyncPlanMediaKind.TRACK
            and item.action in (SyncPlanAction.UPDATE, SyncPlanAction.UNCHANGED)
            and host_path_identity(item.host_path) not in included_paths
        ):
            mapping[host_tracks[host_path_identity(item.host_path)]] = item.ipod_id
    for item in request.plan.items:
        if (
            item.action is SyncPlanAction.UNCHANGED
            and item.media_kind is SyncPlanMediaKind.TRACK
            and item.host_path is not None
            and item.ipod_id is not None
        ):
            mapping[host_tracks[host_path_identity(item.host_path)]] = item.ipod_id
    return mapping


def preview_playlist_sync(
    plan: SyncPlan,
    host: HostMediaLibrary,
    ipod: IPodMediaLibrary,
    source: ActiveIPod,
) -> tuple[PlaylistSyncChange, ...]:
    """Describe Host reconciliation using the same pure rules as execution.

    Incoming selected Tracks receive hypothetical draft identities. Failed Tracks
    can later prevent a reviewed change; execution reports those skipped changes.
    Removing a Track always removes its references and is already reviewed as a
    media removal, so that automatic cleanup is excluded from this preview.
    """
    request = SyncExecutionRequest(plan, host, ipod, source, 0, 0)
    mapping = _retained_playlist_mapping(request)
    host_tracks = {
        host_path_identity(track.metadata.location): track.track_id
        for track in host.snapshot.tracks
    }
    retained_ids = {track.track_id for track in source.library.tracks}
    next_track_id = min((0, *retained_ids)) - 1
    for item in plan.items:
        if item.media_kind is not SyncPlanMediaKind.TRACK:
            continue
        if item.action is SyncPlanAction.REMOVE:
            assert item.ipod_id is not None
            retained_ids.discard(item.ipod_id)
        elif item.action in (SyncPlanAction.ADD, SyncPlanAction.UPDATE):
            assert item.host_path is not None
            identity = item.ipod_id
            if item.action is SyncPlanAction.ADD:
                identity = next_track_id
                next_track_id -= 1
                retained_ids.add(identity)
            assert identity is not None
            mapping[host_tracks[host_path_identity(item.host_path)]] = identity
    retained = frozenset(retained_ids)
    playlists, _ = _playlists(request, mapping, retained, [])
    return _playlist_changes(_playlist_baseline(request, retained), playlists)


def _playlist_changes(
    before: tuple[Playlist, ...], after: tuple[Playlist, ...]
) -> tuple[PlaylistSyncChange, ...]:
    by_id = {playlist.playlist_id: playlist for playlist in before}
    changes: list[PlaylistSyncChange] = []
    for playlist in after:
        previous = by_id.get(playlist.playlist_id)
        if previous is not None and previous.track_ids == playlist.track_ids:
            continue
        original = () if previous is None else previous.track_ids
        old_counts, new_counts = Counter(original), Counter(playlist.track_ids)
        common = old_counts & new_counts

        def retained_order(
            identities: tuple[int, ...], counts: Counter[int]
        ) -> tuple[int, ...]:
            remaining = counts.copy()
            result: list[int] = []
            for identity in identities:
                if remaining[identity]:
                    remaining[identity] -= 1
                    result.append(identity)
            return tuple(result)

        changes.append(
            PlaylistSyncChange(
                playlist.name,
                "create" if previous is None else "update",
                sum((new_counts - old_counts).values()),
                sum((old_counts - new_counts).values()),
                retained_order(original, common)
                != retained_order(playlist.track_ids, common),
            )
        )
    return tuple(changes)


def _playlist_baseline(
    request: SyncExecutionRequest, retained_ids: frozenset[int]
) -> tuple[Playlist, ...]:
    removed_ids = {
        track.track_id for track in request.source.library.tracks
    } - retained_ids
    return tuple(
        replace(
            playlist,
            entries=tuple(
                entry for entry in playlist.entries if entry.track_id not in removed_ids
            ),
        )
        for playlist in request.source.library.playlists
    )


def _playlists(
    request: SyncExecutionRequest,
    mapping: dict[int, int],
    retained_ids: frozenset[int],
    issues: list[WriteIssue],
) -> tuple[tuple[Playlist, ...], bool]:
    """Reconcile unambiguous regular playlists, preserving failed memberships."""

    original = request.source.library.playlists
    playlists = {
        playlist.playlist_id: playlist
        for playlist in _playlist_baseline(request, retained_ids)
    }
    if not request.reconcile_playlists:
        result = tuple(playlists.values())
        return result, result != original
    hosts = request.host.snapshot.playlists
    host_names = Counter(playlist.name.casefold() for playlist in hosts)
    ipod_names = Counter(
        playlist.name.casefold() for playlist in original if playlist.parent_id is None
    )
    by_name = {
        playlist.name.casefold(): playlist
        for playlist in original
        if playlist.parent_id is None
    }
    host_tracks = {
        host_path_identity(track.metadata.location): track.track_id
        for track in request.host.snapshot.tracks
    }
    selected = {
        host_tracks[host_path_identity(item.host_path)]
        for item in request.plan.items
        if item.media_kind is SyncPlanMediaKind.TRACK
        and item.host_path is not None
        and item.action
        in (SyncPlanAction.ADD, SyncPlanAction.UPDATE, SyncPlanAction.UNCHANGED)
    }
    next_playlist_id = min((0, *playlists)) - 1
    incomplete = frozenset(request.host.incomplete_playlist_ids)
    for host in hosts:
        if host.kind is not PlaylistKind.PLAYLIST or host.parent_id is not None:
            continue
        if host.playlist_id in incomplete:
            issues.append(
                WriteIssue(
                    "sync.playlist_incomplete",
                    source_text(
                        "Playlist {name} was preserved because some source entries were excluded "
                        "or could not be read. Resolve its missing or declined references and rescan "
                        "before updating this Playlist.",
                        name=host.name,
                    ),
                    severity=IssueSeverity.WARNING,
                )
            )
            continue
        desired = tuple(
            mapping[identity] for identity in host.track_ids if identity in mapping
        )
        if not desired and host.entries:
            continue
        name = host.name.casefold()
        existing = by_name.get(name)
        if (
            host_names[name] != 1
            or ipod_names[name] > 1
            or (
                existing is not None
                and (
                    existing.kind is not PlaylistKind.PLAYLIST
                    or existing.system_managed
                )
            )
        ):
            issues.append(
                WriteIssue(
                    "sync.playlist_ambiguous",
                    source_text(
                        "Playlist {name} was preserved because its name matches an ambiguous or managed Playlist. Rename the Host Playlist and retry.",
                        name=host.name,
                    ),
                    severity=IssueSeverity.WARNING,
                )
            )
            continue
        if any(
            identity in selected and identity not in mapping
            for identity in host.track_ids
        ):
            issues.append(
                WriteIssue(
                    "sync.playlist_incomplete",
                    source_text(
                        "Playlist {name} was preserved because one of its selected Tracks failed. Retry those Tracks to update this Playlist.",
                        name=host.name,
                    ),
                    severity=IssueSeverity.WARNING,
                )
            )
            continue
        if existing is None:
            identity = next_playlist_id
            next_playlist_id -= 1
            playlists[identity] = Playlist(
                identity, host.name, entries=playlist_entries(desired)
            )
        else:
            current = playlists[existing.playlist_id]
            playlists[existing.playlist_id] = replace(
                current, entries=playlist_entries(desired, current.entries)
            )
    result = tuple(playlists.values())
    return result, result != original


def _validate_host_source(source: HostMediaSource) -> None:
    observed = LocalHostFile.observe(source.path)
    if (observed.size_bytes, observed.modified_ns) != (
        source.size_bytes,
        source.modified_ns,
    ):
        raise ValueError(
            source_text(
                "The Host source {name} changed after scanning. Rescan before Sync.",
                name=source.path.path.name,
            )
        )


def _validate_playlist_sources(
    request: SyncExecutionRequest,
    issues: list[WriteIssue],
    checkpoint: Callable[[], None],
) -> bool:
    valid = True
    if request.reconcile_playlists:
        retained_paths = {
            host_path_identity(item.host_path)
            for item in request.plan.items
            if item.host_path is not None and item.action is SyncPlanAction.UNCHANGED
        }
        for source in request.host.sources:
            if (
                source.kind is not HostMediaFileKind.PLAYLIST
                and host_path_identity(str(source.path)) not in retained_paths
            ):
                continue
            checkpoint()
            try:
                _validate_host_source(source)
            except (OSError, ValueError, StorageError) as error:
                valid = False
                issues.append(
                    WriteIssue(
                        "sync.playlist_source_changed",
                        "A Host Playlist or one of its retained sources changed or became unavailable after Review. "
                        "Host Playlist reconciliation was skipped; rescan before retrying.",
                        severity=IssueSeverity.WARNING,
                        detail=exception_text(error),
                    )
                )
    return valid


def _capture_artwork(
    request: SyncExecutionRequest,
    tracks: list[_PreparedTrack],
    checkpoint: Callable[[], None],
) -> tuple[WriteIssue, ...]:
    formats = request.source.profile.capabilities.artwork.cover_formats
    if not formats:
        return ()
    target_px = max(max(item.width, item.height) for item in formats)
    sources = {item.artwork_id: item for item in request.host.artwork_sources}
    by_path = {
        host_path_identity(track.metadata.location): track
        for track in request.host.snapshot.tracks
    }
    groups: dict[int, list[_PreparedTrack]] = {}
    for track in tracks:
        host_track = by_path[host_path_identity(track.item.host_path or "")]
        if host_track.artwork_id:
            groups.setdefault(host_track.artwork_id, []).append(track)
    issues: list[WriteIssue] = []
    for identity, group in groups.items():
        checkpoint()
        try:
            source = sources.get(identity)
            if source is None:
                raise ValueError(
                    "The scanned artwork source is missing. Rescan this album."
                )
            pixels = capture_sync_artwork(source, target_px, checkpoint=checkpoint)
        except PreparationCancelledError:
            raise
        except Exception as error:
            issues.append(
                WriteIssue(
                    "sync.artwork_skipped",
                    source_text(
                        "Artwork for {name} was skipped. "
                        "Media can still Sync; any existing iPod artwork was preserved.",
                        name=group[0].item.name,
                    ),
                    severity=IssueSeverity.WARNING,
                    detail=exception_text(error),
                )
            )
        else:
            for track in group:
                track.song = replace(track.song, artwork=pixels)
    return tuple(issues)


def _capture_podcast_artwork(
    request: SyncExecutionRequest,
    podcast_sync: PreparedPodcastSync,
    plan: PodcastSyncPlan,
    prepared: list[_PreparedPodcast],
    progress: Callable[[WriteProgress], None],
    checkpoint: Callable[[], None],
) -> tuple[
    list[_PreparedPodcast], tuple[_PodcastArtworkRepair, ...], tuple[WriteIssue, ...]
]:
    formats = request.source.profile.capabilities.artwork.cover_formats
    if not formats:
        return prepared, (), ()
    incoming = {podcast.subscription_id for podcast in prepared}
    shows = {
        addition.subscription.subscription_id: addition.subscription
        for addition in plan.additions
        if addition.subscription.subscription_id in incoming
    }
    unavailable = (
        {
            item.ipod_id
            for item in request.plan.items
            if item.media_kind is SyncPlanMediaKind.TRACK
            and item.action in (SyncPlanAction.REMOVE, SyncPlanAction.UPDATE)
        }
        | set(plan.removals)
        | {
            podcast.replaces_track_id
            for podcast in prepared
            if podcast.replaces_track_id is not None
        }
    )
    retained = {track.track_id: track for track in request.source.library.tracks}
    repairs: dict[int, str] = {}
    refreshed = frozenset(podcast_sync.refreshed_subscription_ids)
    for subscription in podcast_sync.state.snapshot.subscriptions:
        if subscription.subscription_id not in refreshed:
            continue
        for episode in subscription.episodes:
            identity = episode.track_id
            if identity is None or identity in unavailable:
                continue
            track = retained.get(identity)
            if track is not None and track.artwork_id == 0:
                repairs[identity] = subscription.subscription_id
                shows[subscription.subscription_id] = subscription
    result = prepare_podcast_covers(
        tuple(shows.values()),
        max(max(item.width, item.height) for item in formats),
        checkpoint=checkpoint,
        progress=progress,
    )
    covers = {cover.subscription_id: cover.pixels for cover in result.covers}
    incoming_covers = [
        replace(
            podcast, song=replace(podcast.song, artwork=covers[podcast.subscription_id])
        )
        if podcast.subscription_id in covers
        else podcast
        for podcast in prepared
    ]
    retained_covers = tuple(
        _PodcastArtworkRepair(
            SyncPlanItem(
                SyncPlanAction.UPDATE,
                SyncPlanMediaKind.TRACK,
                SyncPlanBasis.HOST_FACTS_CHANGED,
                retained[identity].title or "Podcast Episode",
                detail="Podcast artwork",
                host_path=shows[subscription_id].artwork_url,
                ipod_path=retained[identity].metadata.location,
                ipod_id=identity,
            ),
            covers[subscription_id],
        )
        for identity, subscription_id in repairs.items()
        if subscription_id in covers
    )
    return incoming_covers, retained_covers, result.issues


__all__ = [
    "PlaylistSyncChange",
    "SyncExecutionRequest",
    "SyncExecutionResult",
    "SyncExecutionStatus",
    "SyncExecutor",
    "SyncOptions",
    "preview_playlist_sync",
]
