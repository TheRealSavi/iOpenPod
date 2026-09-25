"""Execute reviewed Sync intent through one verified Library/Storage transaction."""

from __future__ import annotations

import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

from iOpenPod.app.host_media_library import HostMediaFileKind
from iOpenPod.app.library_sync_helper import SyncDetails, SyncedImage, SyncedTrack
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    PreparationCancelledError,
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
    prepare_sync_photo,
)
from iOpenPod.app.media.sync_artwork import capture_sync_artwork
from iOpenPod.app.media.transcoding import MediaTranscoder, TranscodeSettings
from iOpenPod.app.services.device_coordinator import (
    SyncCleanupCompletedError,
    SyncRecoveryRequiredError,
)
from iOpenPod.app.sync_plan import (
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanMediaKind,
    host_path_identity,
    prepare_sync_plan,
)
from iOpenPod.app.tag_normalizer import normalize_tags, tag_profile
from iPodDB.library import (
    ArtworkAsset,
    AudioEncoding,
    FileDependency,
    IssueSeverity,
    MediaKind,
    PhotoPixelFormat,
    PhotoThumbnailFormat,
    Playlist,
    PlaylistKind,
    PreparedPhoto,
    Track,
    WriteIssue,
    edit_track_metadata,
    playlist_entries,
    prepared_audio,
    prepared_video,
)
from storage import DeviceEntryKind, DevicePath, StorageError
from storage.host_input import LocalHostFile
from storage.media_processing import available_compute_threads

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Event

    from iOpenPod.app.host_media_library import HostMediaLibrary, HostMediaSource
    from iOpenPod.app.library_sync_helper import IPodMediaLibrary
    from iOpenPod.app.media.transcoding import PreparedTranscode
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from iOpenPod.app.sync_plan import SyncPlan, SyncPlanItem
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


class SyncExecutor:
    """Keep CPU work on the Host and publish sequentially over the USB 2.0 bus."""

    def __init__(
        self,
        coordinator: DeviceCoordinator,
        *,
        transcoder: MediaTranscoder | None = None,
        workers: int | None = None,
    ) -> None:
        self._coordinator = coordinator
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
            requested_playlists = (
                preview_playlist_sync(
                    request.plan, request.host, request.ipod, request.source
                )
                if request.reconcile_playlists
                else ()
            )
            if self._default_transcoder:
                track_jobs = sum(
                    item.media_kind is SyncPlanMediaKind.TRACK
                    and item.action in (SyncPlanAction.ADD, SyncPlanAction.UPDATE)
                    for item in request.plan.items
                )
                self._transcoder = MediaTranscoder(
                    threads_per_job=max(
                        1,
                        available_compute_threads()
                        // min(self._workers, track_jobs or 1),
                    )
                )
            tools = self._transcoder.preflight(checkpoint=checkpoint)
            with ExitStack() as resources:
                prepared, failures = self._prepare_tracks(
                    request, tools, resources, progress, checkpoint
                )
                issues.extend(failures)
                checkpoint()
                issues.extend(_capture_artwork(request, prepared, checkpoint))
                photos, photo_issues = self._prepare_photos(
                    request, progress, checkpoint
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
                                f"{result.item.name} changed during preparation "
                                "and was skipped. Rescan this source before retrying.",
                                detail=str(error),
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
                draft, completed, reconciled = _draft(
                    draft_request, prepared, issues, photos
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
                            f"{len(skipped_playlists)} reviewed Playlist change(s) could not "
                            "be applied. Resolve the reported source or Track problem, "
                            "then rescan and review the remaining Playlist changes.",
                            severity=IssueSeverity.WARNING,
                        )
                    )
                if not completed and not reconciled:
                    requested_changes = bool(
                        request.plan.change_count or requested_playlists
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
                review = self._coordinator.prepare_library(draft, progress, cancelled)
                issues.extend(review.result.issues)
                checkpoint()
                if review.result.prepared is None:
                    return SyncExecutionResult(
                        SyncExecutionStatus.FAILED, issues=tuple(issues)
                    )
                saved = self._coordinator.save_library(
                    review, request.source, progress, cancelled
                )
                issues.extend(saved.issues)
                if saved.active is None:
                    return self._failed_save(
                        request, saved.recovery_path, issues, cancelled
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
                    helper = self._coordinator.publish_sync_success(
                        saved.active,
                        request.ipod,
                        tuple(item.provenance for item in prepared),
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
                            detail=str(error),
                        )
                    )
                partial = (
                    len(completed) < request.plan.change_count
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
                                detail=str(error),
                            )
                        )
                    except Exception as error:
                        issues.append(
                            WriteIssue(
                                "sync.cleanup_pending",
                                "Sync succeeded, but recovery-file cleanup could not finish. "
                                "Keep the iPod connected and choose Retry Cleanup before unplugging.",
                                severity=IssueSeverity.WARNING,
                                detail=str(error),
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
                        str(error),
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
                            detail=str(error),
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
                        detail=str(error),
                    ),
                ),
            )

    def _failed_save(
        self,
        request: SyncExecutionRequest,
        recovery_path: str,
        issues: list[WriteIssue],
        cancelled: Event,
    ) -> SyncExecutionResult:
        if recovery_path:
            try:
                self._coordinator.recover_failed_sync(request.source, recovery_path)
            except SyncCleanupCompletedError as error:
                issues.append(
                    WriteIssue(
                        "sync.cleanup_flush_pending",
                        "The previous Library was restored and recovery files were removed, "
                        "but the final device flush could not be confirmed. Safely eject before unplugging.",
                        severity=IssueSeverity.WARNING,
                        detail=str(error),
                    )
                )
            except Exception as error:
                issues.append(
                    WriteIssue(
                        "sync.recovery_required",
                        "Sync was interrupted and its previous Library could not be restored. "
                        "Reconnect the same iPod and recover this transaction before further writes.",
                        detail=str(error),
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
        host = {
            host_path_identity(str(item.path)): item for item in request.host.sources
        }
        tracks = {item.track_id: item for item in request.ipod.tracks}
        images = {item.image_id: item for item in request.ipod.images}
        with self._coordinator.sync_session(request.source) as session:
            for item in request.plan.items:
                checkpoint()
                if item.action is SyncPlanAction.ATTENTION:
                    continue
                if (
                    item.host_path is not None
                    and item.action is SyncPlanAction.UNCHANGED
                ):
                    source = host[host_path_identity(item.host_path)]
                    _validate_host_source(source)
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
                            f"{item.name}: the iPod file changed after scanning. Rescan the iPod before Sync."
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

        def prepare(item: SyncPlanItem) -> _PreparedTrack:
            result = self._prepare_one(
                request,
                item,
                sources[host_path_identity(item.host_path or "")],
                tracks[host_path_identity(item.host_path or "")],
                tools,
                checkpoint,
            )
            # Register ownership inside the worker before the result is delivered.
            # Even a failed progress callback then closes every successful capture.
            # The executor joins workers before the outer ExitStack can close.
            with cleanup_lock:
                resources.callback(result.resources.close)
            return result

        # Independent preparation runs concurrently; publication uses the single
        # ordered Storage transaction, avoiding competing USB writers.
        with ThreadPoolExecutor(
            max_workers=min(self._workers, len(changes) or 1),
            thread_name_prefix="sync-media",
        ) as pool:
            futures = {pool.submit(prepare, item): item for item in changes}
            was_cancelled = False
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                except PreparationCancelledError:
                    was_cancelled = True
                except Exception as error:
                    issues.append(
                        WriteIssue(
                            "sync.item_failed",
                            f"{item.name} was skipped. Its existing iPod copy was kept. "
                            "Correct the source or encoder settings and retry.",
                            subject="track",
                            record_id=item.ipod_id,
                            detail=str(error),
                            artifact=item.host_path or "",
                        )
                    )
                else:
                    prepared.append(result)
                    issues.extend(
                        WriteIssue(
                            "sync.media_warning",
                            warning,
                            severity=IssueSeverity.WARNING,
                            artifact=item.host_path or "",
                        )
                        for warning in result.warnings
                    )
                progress(
                    WriteProgress(
                        "sync.prepare",
                        f"Prepared {len(prepared):,} of {len(changes):,} Tracks; {len(issues):,} messages.",
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
                            f"{result.item.name} was skipped because an unused four-character "
                            "media filename could not be reserved. Its existing iPod copy was kept. "
                            "Resolve the reported Music-folder problem, then rescan and retry.",
                            subject="track",
                            record_id=result.item.ipod_id,
                            detail=str(error),
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

    def _prepare_one(
        self,
        request: SyncExecutionRequest,
        item: SyncPlanItem,
        source: HostMediaSource,
        track: Track,
        tools: MediaTools,
        checkpoint: Callable[[], None],
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
            if not source.acoustic_fingerprint:
                raise ValueError(
                    "The Host Track has no verified acoustic fingerprint. Rescan it with fpcalc installed."
                )
            provenance = SyncedTrack(
                DevicePath(song.track.metadata.location),
                source.acoustic_fingerprint,
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
        retained_bytes = 0
        # Each photo has an independently bounded decoded image. Retaining at most
        # 512 MiB of verified output keeps large Photo libraries resumable in batches.
        for item in changes:
            checkpoint()
            source = sources[host_path_identity(item.host_path or "")]
            try:
                _validate_host_source(source)
                if (
                    retained_bytes
                    + source.size_bytes
                    + sum(fmt.row_bytes * fmt.height for fmt in formats)
                    > 512 * 1024 * 1024
                ):
                    raise ValueError(
                        "The Photo preparation batch reached its 512 MiB limit. Sync the remaining Photos in another batch."
                    )
                observed = LocalHostFile.observe(source.path)
                data = observed.read_bytes(
                    max_bytes=MAX_PHOTO_SOURCE_BYTES, checkpoint=checkpoint
                )
                digest = hashlib.sha256(data).hexdigest()
                if digest != source.content_sha256:
                    raise ValueError(
                        "The Photo changed after scanning. Rescan this source before retrying."
                    )
                identity = (
                    item.ipod_id if item.action is SyncPlanAction.UPDATE else next_id
                )
                assert identity is not None
                if item.action is SyncPlanAction.ADD:
                    next_id += 1
                unique = uuid4()
                path = f"Photos/Full Resolution/iOpenPod/{unique.hex}{source.path.path.suffix.casefold()}"
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
                retained_bytes += sum(len(file.data) for file in asset.files)
                prepared.append(
                    _PreparedPhoto(
                        item,
                        asset,
                        SyncedImage(
                            DevicePath(path),
                            digest,
                            SyncDetails(
                                datetime.now(UTC).isoformat(),
                                str(source.path),
                                source.size_bytes,
                                source.modified_ns,
                                source.path.path.suffix.lstrip("."),
                                source.path.path.suffix.lstrip("."),
                                False,
                            ),
                        ),
                    )
                )
            except PreparationCancelledError:
                raise
            except Exception as error:
                issues.append(
                    WriteIssue(
                        "sync.photo_failed",
                        f"{item.name} was skipped. Its existing Photo was preserved. "
                        "Correct the source or device format problem and retry.",
                        subject="photo",
                        record_id=item.ipod_id,
                        detail=str(error),
                        artifact=item.host_path or "",
                    )
                )
            progress(
                WriteProgress(
                    "sync.photos",
                    f"Prepared {len(prepared):,} of {len(changes):,} Photos…",
                )
            )
        return tuple(prepared), tuple(issues)


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
        track, LibraryMediaSource(output.source, output.inspection.fingerprint, media)
    )


def _draft(
    request: SyncExecutionRequest,
    prepared: list[_PreparedTrack],
    issues: list[WriteIssue],
    prepared_photos: tuple[_PreparedPhoto, ...] = (),
) -> tuple[LibraryPreparationRequest, tuple[SyncPlanItem, ...], bool]:
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
    completed: list[SyncPlanItem] = []
    removed_photos: set[int] = set()
    next_track_id = min((0, *tracks)) - 1
    for result in prepared:
        item, song = result.item, result.song
        cover_id = 0
        if song.artwork is not None:
            identity_key = id(song.artwork)
            if identity_key not in artwork_ids:
                artwork_ids[identity_key] = -len(artwork_ids) - 1
                artwork.append(ArtworkAsset(artwork_ids[identity_key], song.artwork))
            cover_id = artwork_ids[identity_key]
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
        elif item.action is SyncPlanAction.ATTENTION:
            issues.append(
                WriteIssue(
                    "sync.needs_attention",
                    f"{item.name} needs attention and was left unchanged. "
                    "Resolve missing or ambiguous matching evidence and rescan.",
                    severity=IssueSeverity.WARNING,
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
    draft = LibraryPreparationRequest(
        replace(
            original,
            tracks=_normalized_tracks(request, tuple(tracks.values()))
            if request.options.normalize_tags
            else tuple(tracks.values()),
            playlists=playlists,
            photos=photos,
        ),
        request.source,
        request.workspace_generation,
        request.workspace_revision,
        delete_omissions=any(
            item.action is SyncPlanAction.REMOVE for item in completed
        ),
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
    return draft, tuple(completed), reconciled


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
                    f"Playlist {host.name} was preserved because some source entries were excluded "
                    "or could not be read. Resolve its missing or declined references and rescan "
                    "before updating this Playlist.",
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
                    f"Playlist {host.name} was preserved because its name matches an ambiguous or managed Playlist. Rename the Host Playlist and retry.",
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
                    f"Playlist {host.name} was preserved because one of its selected Tracks failed. Retry those Tracks to update this Playlist.",
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
            f"The Host source {source.path.path.name} changed after scanning. Rescan before Sync."
        )


def _validate_playlist_sources(
    request: SyncExecutionRequest,
    issues: list[WriteIssue],
    checkpoint: Callable[[], None],
) -> bool:
    valid = True
    if request.reconcile_playlists:
        for source in request.host.sources:
            if source.kind is not HostMediaFileKind.PLAYLIST:
                continue
            checkpoint()
            try:
                _validate_host_source(source)
            except (OSError, ValueError, StorageError) as error:
                valid = False
                issues.append(
                    WriteIssue(
                        "sync.playlist_source_changed",
                        "A Host Playlist changed or became unavailable after Review. "
                        "Host Playlist reconciliation was skipped; rescan before retrying.",
                        severity=IssueSeverity.WARNING,
                        detail=str(error),
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
                    f"Artwork for {group[0].item.name} was skipped. "
                    "Media can still Sync; any existing iPod artwork was preserved.",
                    severity=IssueSeverity.WARNING,
                    detail=str(error),
                )
            )
        else:
            for track in group:
                track.song = replace(track.song, artwork=pixels)
    return tuple(issues)


__all__ = [
    "PlaylistSyncChange",
    "SyncExecutionRequest",
    "SyncExecutionResult",
    "SyncExecutionStatus",
    "SyncExecutor",
    "SyncOptions",
    "preview_playlist_sync",
]
