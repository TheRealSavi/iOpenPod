"""Scan Active-iPod media and persist its non-authoritative Sync correlation index."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, closing
from dataclasses import dataclass, field, replace
from enum import StrEnum
from itertools import chain
from threading import Event
from typing import TYPE_CHECKING, Protocol, cast

from whenever import Instant

from iOpenPod.app.display_text import source_text
from iOpenPod.app.host_media_fingerprint import (
    FpcalcError,
    FpcalcFingerprinter,
    FpcalcNoAudioError,
    FpcalcUnavailableError,
    normalize_fpcalc_fingerprint,
)
from iOpenPod.app.ipod_analysis_cache import (
    IPodAnalysisCache,
    IPodAnalysisRecord,
    ipod_analysis_cache_identity,
)
from iOpenPod.app.media.fingerprint_codec import decode_fingerprint, encode_fingerprint
from iOpenPod.app.media.ratings import whole_star_rating
from iOpenPod.app.playlist_sync import PlaylistAssociation, playlist_sync_target
from iOpenPod.app.sync_track_details import track_tag_sha256
from iPodDB.library import PhotoRepresentationKind
from storage import (
    ConcurrentModificationError,
    DeviceEntry,
    DeviceEntryKind,
    DevicePath,
    FileContent,
    FileFingerprint,
    FilesystemSessionError,
    HostPath,
    StorageError,
    StorageOperationError,
    TransactionWrite,
)
from storage.device_capture import capture_device_file

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from iPodDB.library import LibrarySnapshot, Photo, Track
    from storage import AtomicHostFile, FilesystemSession, StorageTransaction


LIBRARY_SYNC_HELPER_PATH = DevicePath("iPod_Control/iOpenPod/library-sync-helper.json")
RATING_SYNC_PATH = DevicePath("iPod_Control/iOpenPod/rating-sync.json")
_IPOD_CONTROL_PATH = DevicePath("iPod_Control")
_PHOTOS_PATH = DevicePath("Photos")
_FORMAT_VERSION = 7
_MAX_RECORDS = 250_000


class LibrarySyncHelperError(RuntimeError):
    """The iPod media scan could not produce a trustworthy correlation index."""


class LibrarySyncHelperCancelledError(LibrarySyncHelperError):
    """Cooperative cancellation reached a safe device-scan checkpoint."""


class IPodMediaScanStage(StrEnum):
    LOADING = "loading"
    TRACKS = "tracks"
    IMAGES = "images"
    SAVING = "saving"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class IPodMediaScanProgress:
    stage: IPodMediaScanStage
    completed: int
    total: int
    message: str
    path: DevicePath | None = None
    reused: int = 0


@dataclass(frozen=True, slots=True)
class PendingRatingWrite:
    """Reviewed Host rating and the target to write after the iPod commits it."""

    host_rating: int
    target_rating: int

    def __post_init__(self) -> None:
        _validate_rating(self.host_rating)
        _validate_rating(self.target_rating)

    @property
    def host_target(self) -> int:
        return whole_star_rating(self.target_rating)

    def matches(self, host_rating: int, ipod_rating: int) -> bool:
        return ipod_rating == self.target_rating and host_rating in (
            self.host_rating,
            self.host_target,
        )


def _validate_rating(rating: int) -> None:
    if type(rating) is not int or not 0 <= rating <= 100:
        raise ValueError("Sync rating baselines must use the 0-100 scale")


@dataclass(frozen=True, slots=True)
class SyncDetails:
    """Host-source facts captured only after one successful Sync commit."""

    last_synced_at: str
    host_path_hint: str
    host_size_bytes: int
    host_modified_ns: int
    source_format: str
    ipod_format: str
    was_transcoded: bool
    host_content_sha256: str = ""
    host_artwork_sha256: str | None = None
    ipod_artwork_id: int | None = None
    ipod_tag_sha256: str | None = None
    ipod_baseline_pending: bool = False
    host_tag_sha256: str | None = None
    file_tag_policy: str | None = None
    stream_selection_sha256: str | None = None
    host_rating: int | None = None
    ipod_rating: int | None = None
    pending_rating: PendingRatingWrite | None = None

    def __post_init__(self) -> None:
        for rating in (self.host_rating, self.ipod_rating):
            if rating is not None:
                _validate_rating(rating)
        if not self.last_synced_at.strip():
            raise ValueError("Sync Details require a last-synced timestamp")
        if self.host_size_bytes < 0:
            raise ValueError("Sync Details require a non-negative Host file size")
        if self.host_content_sha256:
            _require_sha256(self.host_content_sha256, "Host content fingerprint")
        if self.host_artwork_sha256:
            _require_sha256(self.host_artwork_sha256, "Host artwork fingerprint")
        if self.ipod_artwork_id is not None and self.ipod_artwork_id < 0:
            raise ValueError("The iPod artwork identity must not be negative")
        if self.ipod_tag_sha256 is not None:
            _require_sha256(self.ipod_tag_sha256, "iPod Track tag fingerprint")
        if self.host_tag_sha256 is not None:
            _require_sha256(self.host_tag_sha256, "Host Track tag fingerprint")
        if self.stream_selection_sha256 is not None:
            _require_sha256(
                self.stream_selection_sha256, "Media Stream Selection fingerprint"
            )


@dataclass(frozen=True, slots=True)
class IPodTrackFingerprint:
    database_track_id: int
    track_id: int
    path: DevicePath
    size_bytes: int
    modified_ns: int
    acoustic_fingerprint: str
    sync: SyncDetails | None = None

    def __post_init__(self) -> None:
        if self.database_track_id < 0 or self.track_id <= 0:
            raise ValueError("An iPod Track fingerprint needs valid Track identities")
        if self.size_bytes < 0:
            raise ValueError("An iPod Track fingerprint needs a non-negative file size")
        if self.acoustic_fingerprint:
            normalize_fpcalc_fingerprint(self.acoustic_fingerprint)
        elif self.sync is None:
            raise ValueError(
                "A Track without an acoustic fingerprint needs committed Sync Details"
            )


@dataclass(frozen=True, slots=True)
class IPodImageFingerprint:
    image_id: int
    path: DevicePath
    size_bytes: int
    modified_ns: int
    content_sha256: str
    sync: SyncDetails | None = None

    def __post_init__(self) -> None:
        if self.image_id <= 0:
            raise ValueError("An iPod image fingerprint needs a positive image ID")
        if self.size_bytes < 0:
            raise ValueError("An iPod image fingerprint needs a non-negative file size")
        _require_sha256(self.content_sha256, "image fingerprint")


@dataclass(frozen=True, slots=True)
class IPodMediaScanIssue:
    subject: str
    detail: str


@dataclass(frozen=True, slots=True)
class IPodMediaCacheStats:
    reused: int = 0
    fingerprinted: int = 0

    @property
    def total(self) -> int:
        return self.reused + self.fingerprinted


@dataclass(frozen=True, slots=True)
class IPodMediaLibrary:
    """Device-side matching evidence retained outside the common Library Snapshot."""

    tracks: tuple[IPodTrackFingerprint, ...]
    images: tuple[IPodImageFingerprint, ...]
    issues: tuple[IPodMediaScanIssue, ...]
    cache: IPodMediaCacheStats
    helper_revision: FileFingerprint | None
    persisted: bool
    playlist_associations: tuple[PlaylistAssociation, ...] = ()
    rating_revision: FileFingerprint | None = None
    ratings_available: bool = True


@dataclass(frozen=True, slots=True)
class SyncedTrack:
    """Matching evidence and optional Host provenance for a committed location."""

    path: DevicePath
    acoustic_fingerprint: str
    sync: SyncDetails | None = None
    track_id: int | None = None
    refresh_metadata_baseline: bool = True


@dataclass(frozen=True, slots=True)
class SyncedImage:
    """Successful Host provenance for one committed full-resolution Photo."""

    path: DevicePath
    content_sha256: str
    sync: SyncDetails


def retain_retagged_sync_details(
    session: FilesystemSession,
    transaction: StorageTransaction,
    original: LibrarySnapshot,
    updated: LibrarySnapshot,
    track_ids: tuple[int, ...],
    *,
    library_sha256: str,
) -> StorageTransaction:
    """Carry established associations through verified retained-file tag edits.

    The caller supplies only retained-file retag identities, never replacements.
    Captured write preconditions must still match the helper's old identity and
    file facts. Publish refreshed facts with the media in the same recoverable
    transaction; Host Sync baselines and acoustic evidence remain untouched.
    """
    before = {track.track_id: track for track in original.tracks}
    after = {track.track_id: track for track in updated.tracks}
    writes = {write.path: write for write in transaction.writes}
    eligible: dict[tuple[str, int], tuple[Track, TransactionWrite]] = {}
    for identity in track_ids:
        prior, current = before.get(identity), after.get(identity)
        if (
            prior is None
            or current is None
            or _track_key_for_track(prior) != _track_key_for_track(current)
            or prior.metadata.location != current.metadata.location
        ):
            continue
        write = writes.get(_track_path(prior))
        if write is not None and write.expected is not None:
            eligible[_track_key_for_track(prior)] = (current, write)
    if not eligible:
        return transaction
    loaded, issue = _load_helper(session)
    if issue is not None or not loaded.writable:
        raise LibrarySyncHelperError(
            "The existing Sync helper is invalid and was preserved. Recover it "
            "before saving media tag edits."
        )
    if loaded.revision is None:
        return transaction
    # FAT represents modification times in two-second increments. Storage verifies
    # this timestamp along with content, including after interrupted-write recovery.
    modified_ns = (
        Instant.now().timestamp(unit="nanosecond") // 2_000_000_000 * 2_000_000_000
    )
    refreshed: set[DevicePath] = set()
    tracks: list[IPodTrackFingerprint] = []
    for record in loaded.tracks:
        candidate = eligible.get(_track_key(record))
        if candidate is not None and record.sync is not None:
            track, write = candidate
            expected = write.expected
            assert expected is not None
            if (
                record.path == write.path
                and record.size_bytes == expected.size
                and session.modified_time_matches(
                    record.modified_ns, expected.modified_ns
                )
            ):
                record = replace(
                    record,
                    track_id=track.track_id,
                    size_bytes=write.content.size,
                    modified_ns=modified_ns,
                )
                refreshed.add(write.path)
        tracks.append(record)
    if not refreshed:
        return transaction
    # A save can retag retained Tracks and remove others together. Keep helper
    # pruning in this same transaction so later publication cannot invalidate
    # the helper fingerprint needed for recovery or durability verification.
    retained_keys = {_track_key_for_track(track) for track in updated.tracks}
    tracks = [record for record in tracks if _track_key(record) in retained_keys]
    payload = _encode_helper(
        tuple(tracks),
        loaded.images,
        library_sha256,
        updated_at=Instant.now().to_fixed_offset().format_iso(unit="microsecond"),
        playlists=loaded.playlists,
        include_inline_ratings=loaded.inline_ratings,
    )
    return replace(
        transaction,
        writes=(
            *(
                replace(write, modified_ns=modified_ns)
                if write.path in refreshed
                else write
                for write in transaction.writes
            ),
            TransactionWrite(
                LIBRARY_SYNC_HELPER_PATH,
                payload,
                FileContent(len(payload), hashlib.sha256(payload).hexdigest()),
                loaded.revision,
            ),
        ),
    )


def read_sync_history(
    session: FilesystemSession, library: LibrarySnapshot
) -> IPodMediaLibrary:
    """Read established, still-valid associations without analyzing audio.

    Library refresh has no Host comparison. It can still carry existing Sync
    Details through its own metadata updates using the normal publication path.
    """
    loaded, issue = _load_helper(session)
    if issue is not None or not loaded.writable:
        raise LibrarySyncHelperError("The existing Sync helper is invalid.")
    retained = {_track_key(record): record for record in loaded.tracks}
    tracks: list[IPodTrackFingerprint] = []
    for track in library.tracks:
        record = retained.get(_track_key_for_track(track))
        if record is None:
            continue
        path = _track_path(track)
        if _matches(session, record, path, _regular_file(session, path)):
            tracks.append(replace(record, track_id=track.track_id))
    return IPodMediaLibrary(
        tuple(tracks),
        loaded.images,
        (loaded.rating_issue,) if loaded.rating_issue is not None else (),
        IPodMediaCacheStats(),
        loaded.revision,
        loaded.revision is not None,
        loaded.playlists,
        loaded.ratings.revision,
        loaded.rating_issue is None,
    )


def publish_sync_helper(
    session: FilesystemSession,
    library: LibrarySnapshot,
    previous: IPodMediaLibrary | None,
    synced: tuple[SyncedTrack, ...],
    synced_images: tuple[SyncedImage, ...] = (),
    *,
    library_sha256: str,
    playlists: tuple[PlaylistAssociation, ...] = (),
) -> IPodMediaLibrary:
    """Publish matching evidence only after the caller's Library commit succeeds.

    Never decode files over the USB bus again: committed locations supply their
    verified file facts, while incoming media supplies acoustic matching evidence.
    Without a preceding iPod Media Scan, merge the currently stored valid helper
    against committed Library identities and file facts. A scanned helper must still
    match its captured revision. Malformed helpers are always preserved.
    """

    loaded, issue = _load_helper(session)
    if issue is not None or not loaded.writable:
        raise LibrarySyncHelperError(
            "The existing Sync helper is invalid and was preserved. Recover or "
            "explicitly replace it before the next Sync."
        )
    if previous is not None and loaded.revision != previous.helper_revision:
        raise LibrarySyncHelperError(
            "The Sync helper changed after Review. Rescan the iPod before retrying."
        )
    if previous is not None and loaded.ratings.revision != previous.rating_revision:
        raise LibrarySyncHelperError(
            "Rating Sync state changed after Review. Rescan before retrying."
        )
    updated = {
        str(item.path).casefold(): item for item in synced if item.track_id is None
    }
    updated_ids = {item.track_id: item for item in synced if item.track_id is not None}
    successful: tuple[SyncedTrack | SyncedImage, ...] = (*synced, *synced_images)
    claimed_host_paths = {
        os.path.normcase(os.path.abspath(item.sync.host_path_hint))
        for item in successful
        if item.sync is not None and item.sync.host_path_hint.strip()
    }

    def retained_sync(sync: SyncDetails | None) -> SyncDetails | None:
        # A successful explicit match can supersede another copy's old path claim.
        # Retain its historical facts and acoustic evidence, but stop claiming the
        # Host file now associated with a different committed Library identity.
        if (
            sync is not None
            and sync.host_path_hint.strip()
            and (
                os.path.normcase(os.path.abspath(sync.host_path_hint))
                in claimed_host_paths
            )
        ):
            return replace(sync, host_path_hint="")
        return sync

    retained = {
        ("track", item.track_id) if previous is not None else _track_key(item): item
        for item in (loaded.tracks if previous is None else previous.tracks)
    }
    tracks: list[IPodTrackFingerprint] = []
    issues = [loaded.rating_issue] if loaded.rating_issue is not None else []
    for track in library.tracks:
        try:
            path = _track_path(track)
        except ValueError as error:
            issues.append(IPodMediaScanIssue(f"Track {track.track_id}", str(error)))
            continue
        new = updated_ids.get(track.track_id) or updated.get(str(path).casefold())
        if new is not None and str(new.path).casefold() != str(path).casefold():
            raise LibrarySyncHelperError(
                "A committed Sync association no longer matches its iPod file."
            )
        old = retained.get(
            ("track", track.track_id)
            if previous is not None
            else _track_key_for_track(track)
        )
        if new is None and old is None:
            continue
        try:
            entry = _regular_file(session, path)
        except FilesystemSessionError:
            raise
        except (OSError, StorageError, ValueError) as error:
            if new is not None or previous is not None:
                raise
            issues.append(
                IPodMediaScanIssue(
                    f"Track {track.track_id}",
                    source_text(
                        "Retained Sync helper evidence was omitted because its media file could not be checked: {error}",
                        error=str(error),
                    ),
                )
            )
            continue
        if new is not None:
            tracks.append(
                IPodTrackFingerprint(
                    _database_track_id(track),
                    track.track_id,
                    path,
                    entry.size,
                    entry.modified_ns,
                    new.acoustic_fingerprint,
                    replace(
                        new.sync,
                        ipod_artwork_id=track.artwork_id,
                        ipod_tag_sha256=track_tag_sha256(track),
                        ipod_baseline_pending=False,
                    )
                    if new.sync is not None and new.refresh_metadata_baseline
                    else new.sync,
                )
            )
        elif old is not None and _matches(session, old, path, entry):
            tracks.append(
                replace(
                    old,
                    track_id=track.track_id,
                    database_track_id=_database_track_id(track),
                    sync=retained_sync(old.sync),
                )
            )
    old_images = {
        item.image_id: item
        for item in (loaded.images if previous is None else previous.images)
    }
    new_images = {str(item.path).casefold(): item for item in synced_images}
    images: list[IPodImageFingerprint] = []
    for photo in () if library.photos is None else library.photos.photos:
        prior = old_images.get(photo.photo_id)
        paths = tuple(
            representation.relative_path
            for representation in photo.representations
            if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
        )
        new_image = next(
            (
                new_images[path.casefold()]
                for path in paths
                if path.casefold() in new_images
            ),
            None,
        )
        if new_image is not None:
            entry = _regular_file(session, new_image.path)
            images.append(
                IPodImageFingerprint(
                    photo.photo_id,
                    new_image.path,
                    entry.size,
                    entry.modified_ns,
                    new_image.content_sha256,
                    new_image.sync,
                )
            )
            continue
        if prior is not None:
            try:
                path = _photo_path(photo)
                if _matches(session, prior, path, _regular_file(session, path)):
                    images.append(replace(prior, sync=retained_sync(prior.sync)))
            except FilesystemSessionError:
                raise
            except (OSError, StorageError, ValueError) as error:
                if previous is not None:
                    raise
                issues.append(
                    IPodMediaScanIssue(
                        f"Image {photo.photo_id}",
                        source_text(
                            "Retained Sync helper evidence was omitted because its media file could not be checked: {error}",
                            error=str(error),
                        ),
                    )
                )
    valid_targets = {
        item.playlist_id for item in library.playlists if playlist_sync_target(item)
    }
    if any(item.ipod_playlist_id not in valid_targets for item in playlists):
        raise LibrarySyncHelperError(
            "A successful Playlist match is absent from the committed Library"
        )
    _validate_playlist_associations(playlists)
    host_claims = {item.host_playlist_id for item in playlists}
    target_claims = {item.ipod_playlist_id for item in playlists}
    retained_playlists = tuple(
        item
        for item in loaded.playlists
        if item.ipod_playlist_id in valid_targets
        and item.host_playlist_id not in host_claims
        and item.ipod_playlist_id not in target_claims
    )
    associations = (*retained_playlists, *playlists)
    revision, rating_revision = _save_helper(
        session,
        tuple(tracks),
        tuple(images),
        library_sha256,
        loaded,
        playlists=associations,
    )
    flush = session.flush()
    if not flush.complete:
        issues.append(
            IPodMediaScanIssue(
                "Sync helper",
                source_text(
                    "The helper was verified, but complete device flushing "
                    "could not be confirmed. Safely eject before unplugging. {detail}",
                    detail=flush.detail,
                ),
            )
        )
    return IPodMediaLibrary(
        tuple(tracks),
        tuple(images),
        tuple(issues),
        IPodMediaCacheStats(reused=len(tracks) + len(images)),
        revision,
        True,
        associations,
        rating_revision,
        loaded.rating_issue is None,
    )


class _AcousticFingerprinter(Protocol):
    def fingerprint(
        self,
        source: HostPath,
        *,
        checkpoint: Callable[[], None],
    ) -> str: ...


ProgressCallback = Callable[[IPodMediaScanProgress], None]
CancellationCheck = Callable[[], None]


@dataclass(frozen=True, slots=True)
class _RatingRecord:
    host_path: str
    host_rating: int
    ipod_rating: int
    pending: PendingRatingWrite | None


@dataclass(frozen=True, slots=True)
class _RatingCatalog:
    records: dict[tuple[str, int], _RatingRecord] = field(default_factory=dict)
    revision: FileFingerprint | None = None


@dataclass(frozen=True, slots=True)
class _LoadedHelper:
    tracks: tuple[IPodTrackFingerprint, ...] = ()
    images: tuple[IPodImageFingerprint, ...] = ()
    library_sha256: str = ""
    updated_at: str = ""
    version: int = _FORMAT_VERSION
    revision: FileFingerprint | None = None
    writable: bool = True
    playlists: tuple[PlaylistAssociation, ...] = ()
    ratings: _RatingCatalog = field(default_factory=_RatingCatalog)
    rating_issue: IPodMediaScanIssue | None = None
    inline_ratings: bool = False


@dataclass(frozen=True, slots=True)
class _TrackOutcome:
    index: int
    track: Track
    path: DevicePath | None
    record: IPodTrackFingerprint | None = None
    error: Exception | None = None
    reused: bool = False


@dataclass(frozen=True, slots=True)
class _PendingTrack:
    index: int
    track: Track
    path: DevicePath
    entry: DeviceEntry
    previous: IPodTrackFingerprint | None
    capture: ExitStack
    future: Future[str]


class IPodMediaScanner:
    """Fingerprint only device media absent from a valid, matching helper entry."""

    def __init__(
        self,
        fingerprinter: _AcousticFingerprinter | None = None,
        *,
        temporary_directory: Path | None = None,
        analysis_cache_file: Callable[[str], AtomicHostFile] | None = None,
    ) -> None:
        self._fingerprinter = fingerprinter or FpcalcFingerprinter()
        self._temporary_directory = temporary_directory
        self._analysis_cache_file = analysis_cache_file
        self._analysis_cache: tuple[str, IPodAnalysisCache] | None = None

    def scan(
        self,
        session: FilesystemSession,
        library: LibrarySnapshot,
        *,
        library_sha256: str,
        persist: bool,
        checkpoint: CancellationCheck,
        progress: ProgressCallback | None = None,
        validate_source: CancellationCheck | None = None,
        report_read_only: bool = True,
    ) -> IPodMediaLibrary:
        """Scan one stable Library Snapshot and optionally publish its helper."""

        _require_sha256(library_sha256, "Library fingerprint")
        checkpoint()
        issues: list[IPodMediaScanIssue] = []
        cache: IPodAnalysisCache | None = None
        cache_writable = True
        if self._analysis_cache_file is not None:
            identity = ipod_analysis_cache_identity(session)
            try:
                if self._analysis_cache is None or self._analysis_cache[0] != identity:
                    self._analysis_cache = (
                        identity,
                        IPodAnalysisCache(
                            self._analysis_cache_file(identity), identity
                        ),
                    )
                cache = self._analysis_cache[1]
                cache.load()
            except (OSError, StorageError, ValueError, FpcalcError) as error:
                issues.append(
                    IPodMediaScanIssue("Host iPod analysis cache", str(error))
                )

        def save_cache(*, force: bool = False) -> None:
            nonlocal cache_writable
            if cache is not None and cache_writable:
                try:
                    cache.save(force=force)
                except (OSError, StorageError, ValueError, FpcalcError) as error:
                    cache_writable = False
                    issues.append(
                        IPodMediaScanIssue("Host iPod analysis cache", str(error))
                    )

        def remember(record: IPodAnalysisRecord) -> None:
            if cache is not None:
                cache.remember(record)
                save_cache()

        try:
            result = self._scan(
                session,
                library,
                library_sha256=library_sha256,
                persist=persist,
                checkpoint=checkpoint,
                progress=progress,
                validate_source=validate_source,
                report_read_only=report_read_only,
                analysis_cache=cache,
                remember=remember,
            )
        finally:
            # Only independently completed, revalidated file analysis was remembered.
            # Cancellation/disconnect must not lose earlier valid work or write an iPod.
            save_cache(force=True)
        return replace(result, issues=(*result.issues, *issues))

    def _scan(
        self,
        session: FilesystemSession,
        library: LibrarySnapshot,
        *,
        library_sha256: str,
        persist: bool,
        checkpoint: CancellationCheck,
        progress: ProgressCallback | None,
        validate_source: CancellationCheck | None,
        report_read_only: bool,
        analysis_cache: IPodAnalysisCache | None,
        remember: Callable[[IPodAnalysisRecord], None],
    ) -> IPodMediaLibrary:

        _require_sha256(library_sha256, "Library fingerprint")
        checkpoint()
        _emit(progress, IPodMediaScanStage.LOADING, 0, 0, "Reading Sync helper…")
        loaded, load_issue = _load_helper_for_scan(session, checkpoint)
        issues = [
            issue for issue in (load_issue, loaded.rating_issue) if issue is not None
        ]
        cached_tracks = {_track_key(item): item for item in loaded.tracks}
        cached_images = {item.image_id: item for item in loaded.images}

        tracks: list[IPodTrackFingerprint] = []
        images: list[IPodImageFingerprint] = []
        reused = 0
        fingerprinted = 0
        image_fingerprints: dict[tuple[str, int, int], str] = {}

        with closing(
            self._track_outcomes(
                session, library, cached_tracks, analysis_cache, checkpoint, remember
            )
        ) as outcomes:
            for outcome in outcomes:
                index, track, track_path = outcome.index, outcome.track, outcome.path
                error = outcome.error
                if error is None:
                    track_record = outcome.record
                    assert track_record is not None
                    # v5 only changes acoustic encoding. v4 already has semantic baselines.
                    if loaded.version < 4 and track_record.sync is not None:
                        track_record = replace(
                            track_record,
                            sync=replace(track_record.sync, ipod_baseline_pending=True),
                        )
                    tracks.append(track_record)
                    if track_record.acoustic_fingerprint:
                        kind, track_identity = _track_key(track_record)
                        remember(
                            IPodAnalysisRecord(
                                kind,
                                track_identity,
                                track_record.path,
                                track_record.size_bytes,
                                track_record.modified_ns,
                                track_record.acoustic_fingerprint,
                            )
                        )
                    reused += int(outcome.reused)
                    fingerprinted += int(not outcome.reused)
                    label = source_text(
                        "Reusing iPod Track {index} of {total}…"
                        if outcome.reused
                        else "Fingerprinting iPod Track {index} of {total}…",
                        index=f"{index:,}",
                        total=f"{len(library.tracks):,}",
                    )
                elif isinstance(error, FpcalcUnavailableError):
                    issues.append(
                        IPodMediaScanIssue(
                            "Acoustic matching",
                            source_text(
                                "Acoustic matching is unavailable; existing Sync Details and independent items remain usable. {error}",
                                error=str(error),
                            ),
                        )
                    )
                    label = source_text("Continuing without acoustic matching…")
                else:
                    if isinstance(error, FpcalcNoAudioError):
                        reused += int(outcome.reused)
                        fingerprinted += int(not outcome.reused)
                    issues.append(
                        IPodMediaScanIssue(f"Track {track.track_id}", str(error))
                    )
                    label = source_text(
                        "Could not fingerprint iPod Track {index} of {total}.",
                        index=f"{index:,}",
                        total=f"{len(library.tracks):,}",
                    )
                _emit(
                    progress,
                    IPodMediaScanStage.TRACKS,
                    index,
                    len(library.tracks),
                    label,
                    path=track_path,
                    reused=reused,
                )

        photos = () if library.photos is None else library.photos.photos
        for index, photo in enumerate(photos, start=1):
            checkpoint()
            image_path: DevicePath | None = None
            try:
                image_path = _photo_path(photo)
                entry = _regular_file(session, image_path)
                image_previous = cached_images.get(photo.photo_id)
                if image_previous is not None and _matches(
                    session, image_previous, image_path, entry
                ):
                    image_record = image_previous
                    reused += 1
                    label = source_text(
                        "Reusing iPod image {index} of {total}…",
                        index=f"{index:,}",
                        total=f"{len(photos):,}",
                    )
                else:
                    identity = (str(image_path), entry.size, entry.modified_ns)
                    digest = image_fingerprints.get(identity)
                    cached = (
                        analysis_cache.get("image", photo.photo_id, image_path)
                        if analysis_cache is not None
                        else None
                    )
                    if (
                        digest is None
                        and cached is not None
                        and _analysis_matches(session, cached, entry)
                    ):
                        digest = cached.fingerprint
                    did_read = digest is None
                    if digest is None:
                        digest = session.fingerprint(image_path).sha256
                        _verify_file_unchanged(session, image_path, entry)
                        image_fingerprints[identity] = digest
                    sync = (
                        image_previous.sync
                        if image_previous is not None
                        and image_previous.content_sha256 == digest
                        else None
                    )
                    image_record = IPodImageFingerprint(
                        image_id=photo.photo_id,
                        path=image_path,
                        size_bytes=entry.size,
                        modified_ns=entry.modified_ns,
                        content_sha256=digest,
                        sync=sync,
                    )
                    fingerprinted += int(did_read)
                    reused += int(not did_read)
                    label = source_text(
                        "Fingerprinting iPod image {index} of {total}…",
                        index=f"{index:,}",
                        total=f"{len(photos):,}",
                    )
                images.append(image_record)
                remember(
                    IPodAnalysisRecord(
                        "image",
                        image_record.image_id,
                        image_record.path,
                        image_record.size_bytes,
                        image_record.modified_ns,
                        image_record.content_sha256,
                    )
                )
            except FilesystemSessionError:
                raise
            except (OSError, StorageError, ValueError) as error:
                if not session.is_active:
                    raise
                issues.append(IPodMediaScanIssue(f"Image {photo.photo_id}", str(error)))
                label = source_text(
                    "Could not fingerprint iPod image {index} of {total}.",
                    index=f"{index:,}",
                    total=f"{len(photos):,}",
                )
            _emit(
                progress,
                IPodMediaScanStage.IMAGES,
                index,
                len(photos),
                label,
                path=image_path,
                reused=reused,
            )

        checkpoint()
        helper_revision = loaded.revision
        rating_revision = loaded.ratings.revision
        persisted = False
        if persist and loaded.writable:
            if validate_source is not None:
                validate_source()
            _emit(
                progress,
                IPodMediaScanStage.SAVING,
                0,
                0,
                "Saving Sync helper…",
                reused=reused,
            )
            helper_revision, rating_revision = _save_helper(
                session,
                tuple(tracks),
                tuple(images),
                library_sha256,
                loaded,
            )
            flush = session.flush()
            persisted = True
            if not flush.complete:
                issues.append(
                    IPodMediaScanIssue(
                        "Sync helper",
                        source_text(
                            "The helper was verified, but the operating system did not confirm a complete device flush: {detail}",
                            detail=str(flush.detail),
                        ),
                    )
                )
        elif persist and not loaded.writable:
            issues.append(
                IPodMediaScanIssue(
                    "Sync helper",
                    "The existing helper could not be safely read and was left unchanged; its "
                    "Sync history must be recovered or explicitly replaced.",
                )
            )
        elif not persist and report_read_only:
            issues.append(
                IPodMediaScanIssue(
                    "Sync helper",
                    "The iPod is not safely writable, so newly calculated "
                    "fingerprints were not persisted to the iPod.",
                )
            )

        _emit(
            progress,
            IPodMediaScanStage.COMPLETE,
            len(library.tracks) + len(photos),
            len(library.tracks)
            + (0 if library.photos is None else len(library.photos.photos)),
            "iPod media scan complete.",
            reused=reused,
        )
        return IPodMediaLibrary(
            tuple(tracks),
            tuple(images),
            tuple(issues),
            IPodMediaCacheStats(reused, fingerprinted),
            helper_revision,
            persisted,
            loaded.playlists,
            rating_revision,
            loaded.rating_issue is None,
        )

    def _track_outcomes(
        self,
        session: FilesystemSession,
        library: LibrarySnapshot,
        committed: dict[tuple[str, int], IPodTrackFingerprint],
        cache: IPodAnalysisCache | None,
        checkpoint: CancellationCheck,
        remember: Callable[[IPodAnalysisRecord], None],
    ) -> Generator[_TrackOutcome]:
        """Read native decoder inputs directly; retain capture fallback for adapters."""
        pending: _PendingTrack | None = None
        stopped = Event()
        fingerprints: dict[tuple[DevicePath, int, int], str] = {}
        no_audio: set[tuple[DevicePath, int, int]] = set()
        unavailable = False
        fingerprinter = self._fingerprinter
        prepared_fingerprinter = False
        executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ipod-fingerprint"
        )

        def decode_checkpoint() -> None:
            if stopped.is_set():
                raise LibrarySyncHelperCancelledError
            checkpoint()

        def finish(item: _PendingTrack) -> _TrackOutcome:
            nonlocal unavailable
            try:
                try:
                    acoustic = item.future.result()
                except FpcalcNoAudioError as error:
                    _verify_file_unchanged(session, item.path, item.entry)
                    kind, identity = _track_key_for_track(item.track)
                    remember(
                        IPodAnalysisRecord(
                            kind,
                            identity,
                            item.path,
                            item.entry.size,
                            item.entry.modified_ns,
                            "",
                            no_audio=True,
                        )
                    )
                    no_audio.add((item.path, item.entry.size, item.entry.modified_ns))
                    return _TrackOutcome(item.index, item.track, item.path, error=error)
                _verify_file_unchanged(session, item.path, item.entry)
                record = _analyzed_track(
                    item.track, item.path, item.entry, acoustic, item.previous
                )
                fingerprints[(item.path, item.entry.size, item.entry.modified_ns)] = (
                    acoustic
                )
                return _TrackOutcome(item.index, item.track, item.path, record)
            except FilesystemSessionError:
                raise
            except (FpcalcError, OSError, StorageError, ValueError) as error:
                if not session.is_active:
                    raise
                unavailable = unavailable or isinstance(error, FpcalcUnavailableError)
                return _TrackOutcome(item.index, item.track, item.path, error=error)
            finally:
                item.capture.close()

        try:
            for index, track in enumerate(library.tracks, start=1):
                checkpoint()
                path: DevicePath | None = None
                try:
                    path = _track_path(track)
                    key = _track_key_for_track(track)
                    previous: IPodTrackFingerprint | None = committed.get(key)
                    while True:
                        checkpoint()
                        entry = _regular_file(session, path)
                        matches_committed = previous is not None and _matches(
                            session, previous, path, entry
                        )
                        acoustic = fingerprints.get(
                            (path, entry.size, entry.modified_ns)
                        )
                        without_audio = (
                            path,
                            entry.size,
                            entry.modified_ns,
                        ) in no_audio
                        cached = cache.get(*key, path) if cache is not None else None
                        if (
                            acoustic is None
                            and cached is not None
                            and _analysis_matches(session, cached, entry)
                        ):
                            if cached.no_audio:
                                without_audio = True
                            else:
                                acoustic = cached.fingerprint
                        same_pending_file = pending is not None and (
                            pending.path,
                            pending.entry.size,
                            pending.entry.modified_ns,
                        ) == (path, entry.size, entry.modified_ns)
                        if pending is not None and (
                            matches_committed
                            or acoustic is not None
                            or without_audio
                            or same_pending_file
                            or isinstance(fingerprinter, FpcalcFingerprinter)
                        ):
                            item, pending = pending, None
                            yield finish(item)
                            # Waiting for the preceding decode may take minutes.
                            # Reobserve before cache reuse or a native device read.
                            continue
                        break
                    if matches_committed:
                        assert previous is not None
                        yield _TrackOutcome(
                            index,
                            track,
                            path,
                            replace(
                                previous,
                                track_id=track.track_id,
                                database_track_id=_database_track_id(track),
                            ),
                            reused=True,
                        )
                        continue
                    if without_audio:
                        yield _TrackOutcome(
                            index, track, path, error=FpcalcNoAudioError(), reused=True
                        )
                        continue
                    if acoustic is not None:
                        yield _TrackOutcome(
                            index,
                            track,
                            path,
                            _analyzed_track(
                                track,
                                path,
                                entry,
                                acoustic,
                                previous,
                            ),
                            reused=True,
                        )
                        continue
                    if unavailable:
                        continue
                    if not prepared_fingerprinter:
                        if isinstance(fingerprinter, FpcalcFingerprinter):
                            fingerprinter = fingerprinter.for_scan()
                        prepared_fingerprinter = True
                    if isinstance(fingerprinter, FpcalcFingerprinter):
                        # The preceding native read completed before the current
                        # observation, so only one decoder accesses this device.
                        future = executor.submit(
                            fingerprinter.fingerprint_device,
                            session,
                            path,
                            checkpoint=decode_checkpoint,
                        )
                        pending = _PendingTrack(
                            index, track, path, entry, previous, ExitStack(), future
                        )
                        continue
                    with ExitStack() as capture:
                        captured = capture.enter_context(
                            capture_device_file(
                                session,
                                path,
                                checkpoint=checkpoint,
                                temporary_directory=(
                                    HostPath(self._temporary_directory)
                                    if self._temporary_directory is not None
                                    else None
                                ),
                            )
                        )
                        # There are at most two captures: one decoding and one copying.
                        if pending is not None:
                            item, pending = pending, None
                            yield finish(item)
                        if unavailable:
                            continue
                        checkpoint()
                        future = executor.submit(
                            fingerprinter.fingerprint,
                            captured,
                            checkpoint=decode_checkpoint,
                        )
                        pending = _PendingTrack(
                            index,
                            track,
                            path,
                            entry,
                            previous,
                            capture.pop_all(),
                            future,
                        )
                except FilesystemSessionError:
                    raise
                except (FpcalcError, OSError, StorageError, ValueError) as error:
                    if not session.is_active:
                        raise
                    if pending is not None:
                        item, pending = pending, None
                        yield finish(item)
                    unavailable = unavailable or isinstance(
                        error, FpcalcUnavailableError
                    )
                    yield _TrackOutcome(index, track, path, error=error)
            if pending is not None:
                item, pending = pending, None
                yield finish(item)
        finally:
            try:
                if pending is not None and pending.future.done():
                    # A cancellation during the next copy must retain the previous
                    # completed decode, provided its device file can still be checked.
                    item, pending = pending, None
                    try:
                        outcome = finish(item)
                        if (
                            outcome.record is not None
                            and outcome.record.acoustic_fingerprint
                        ):
                            record = outcome.record
                            kind, identity = _track_key(record)
                            remember(
                                IPodAnalysisRecord(
                                    kind,
                                    identity,
                                    record.path,
                                    record.size_bytes,
                                    record.modified_ns,
                                    record.acoustic_fingerprint,
                                )
                            )
                    except (StorageError, LibrarySyncHelperCancelledError):
                        # Optional retention cannot replace the interruption that
                        # caused cleanup when the Volume is no longer available.
                        pass
            finally:
                stopped.set()
                try:
                    executor.shutdown(wait=True, cancel_futures=True)
                finally:
                    if pending is not None:
                        pending.capture.close()


def _load_helper_for_scan(
    session: FilesystemSession, checkpoint: CancellationCheck
) -> tuple[_LoadedHelper, IPodMediaScanIssue | None]:
    """Recover optional scan evidence without relaxing publication preconditions."""
    for attempt in range(2):
        checkpoint()
        try:
            return _load_helper(session)
        except FilesystemSessionError:
            raise
        except (OSError, StorageError) as error:
            if not session.is_active:
                raise
            if attempt == 0 and isinstance(
                error, (OSError, StorageOperationError, ConcurrentModificationError)
            ):
                # Retry the complete observation: a previous existence/stat result
                # may belong to a helper that was replaced during the read.
                continue
            return (
                _LoadedHelper(writable=False),
                IPodMediaScanIssue(
                    "Sync helper",
                    source_text(
                        "The existing helper could not be read and was left unchanged; "
                        "media analysis will continue without its cached Sync history: {error}",
                        error=str(error),
                    ),
                ),
            )
    raise AssertionError("The bounded helper read must return or raise")


def _load_helper(
    session: FilesystemSession,
) -> tuple[_LoadedHelper, IPodMediaScanIssue | None]:
    if not session.exists(LIBRARY_SYNC_HELPER_PATH):
        return _attach_ratings(session, _LoadedHelper()), None
    entry = session.stat(LIBRARY_SYNC_HELPER_PATH)
    if entry.kind is not DeviceEntryKind.FILE:
        return (
            _LoadedHelper(writable=False),
            IPodMediaScanIssue(
                "Sync helper",
                "The existing helper is not a regular file.",
            ),
        )
    source = session.read_snapshot(LIBRARY_SYNC_HELPER_PATH)
    try:
        loaded = _decode_helper(source.data)
    except (
        KeyError,
        TypeError,
        ValueError,
        FpcalcError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        return (
            _LoadedHelper(revision=source.fingerprint, writable=False),
            IPodMediaScanIssue(
                "Sync helper",
                source_text(
                    "The existing helper is invalid: {error}", error=str(error)
                ),
            ),
        )
    return _attach_ratings(session, replace(loaded, revision=source.fingerprint)), None


def _rating_records(
    tracks: tuple[IPodTrackFingerprint, ...],
) -> dict[tuple[str, int], _RatingRecord]:
    return {
        _track_key(track): _RatingRecord(
            sync.host_path_hint, sync.host_rating, sync.ipod_rating, sync.pending_rating
        )
        for track in tracks
        if (sync := track.sync) is not None
        and sync.host_path_hint
        and sync.host_rating is not None
        and sync.ipod_rating is not None
    }


def _attach_ratings(session: FilesystemSession, loaded: _LoadedHelper) -> _LoadedHelper:
    try:
        catalog = _load_rating_catalog(session)
    except FilesystemSessionError:
        raise
    except (OSError, StorageError, ValueError) as error:
        return replace(
            loaded,
            rating_issue=IPodMediaScanIssue(
                "Rating Sync state",
                source_text(
                    "Rating Sync state could not be read and was left unchanged: {error}",
                    error=str(error),
                ),
            ),
        )

    def attach(track: IPodTrackFingerprint) -> IPodTrackFingerprint:
        sync = track.sync
        record = catalog.records.get(_track_key(track))
        if (
            sync is None
            or record is None
            or not sync.host_path_hint
            or os.path.normcase(record.host_path)
            != os.path.normcase(sync.host_path_hint)
        ):
            return track
        return replace(
            track,
            sync=replace(
                sync,
                host_rating=record.host_rating,
                ipod_rating=record.ipod_rating,
                pending_rating=record.pending,
            ),
        )

    return replace(loaded, tracks=tuple(map(attach, loaded.tracks)), ratings=catalog)


def _load_rating_catalog(session: FilesystemSession) -> _RatingCatalog:
    if not session.exists(RATING_SYNC_PATH):
        return _RatingCatalog()
    snapshot = session.read_snapshot(RATING_SYNC_PATH)
    try:
        raw: object = json.loads(
            snapshot.data.decode("utf-8"), object_pairs_hook=_pairs
        )
    except RecursionError as error:
        raise ValueError("Rating Sync state is nested too deeply") from error
    document = _exact_object(raw, "Rating Sync state", {"version", "records", "sha256"})
    if _nonnegative_integer(document["version"], "version") != 1:
        raise ValueError("Rating Sync state version is unsupported")
    rows = _array(document["records"], "Rating Sync records")
    if len(rows) > _MAX_RECORDS:
        raise ValueError("Rating Sync state contains too many records")
    if hashlib.sha256(_canonical_json(rows)).hexdigest() != document["sha256"]:
        raise ValueError("Rating Sync state checksum does not match")
    records: dict[tuple[str, int], _RatingRecord] = {}
    for raw_row in rows:
        row = _exact_object(
            raw_row,
            "Rating Sync record",
            {"kind", "id", "host_path", "host_rating", "ipod_rating", "pending"},
        )
        kind = _text(row["kind"], "Track identity kind")
        identity = _decimal_identifier(row["id"], "Track identity")
        host_path = _text(row["host_path"], "Host path")
        if kind not in {"database", "track"} or not identity or not host_path:
            raise ValueError("Rating Sync record has an invalid Track or Host identity")
        key = (kind, identity)
        if key in records:
            raise ValueError("Rating Sync state contains duplicate Track identities")
        host_rating = _nonnegative_integer(row["host_rating"], "Host rating")
        ipod_rating = _nonnegative_integer(row["ipod_rating"], "iPod rating")
        _validate_rating(host_rating)
        _validate_rating(ipod_rating)
        pending = None
        if row["pending"] is not None:
            intent = _exact_object(row["pending"], "Pending rating", {"host", "target"})
            pending = PendingRatingWrite(
                _nonnegative_integer(intent["host"], "Pending Host rating"),
                _nonnegative_integer(intent["target"], "Pending target rating"),
            )
        records[key] = _RatingRecord(host_path, host_rating, ipod_rating, pending)
    return _RatingCatalog(records, snapshot.fingerprint)


def _save_rating_catalog(
    session: FilesystemSession,
    records: dict[tuple[str, int], _RatingRecord],
    previous: _RatingCatalog,
) -> FileFingerprint | None:
    if records == previous.records:
        return previous.revision
    if len(records) > _MAX_RECORDS:
        raise LibrarySyncHelperError("Rating Sync state contains too many records")
    rows = [
        {
            "kind": kind,
            "id": str(identity),
            "host_path": record.host_path,
            "host_rating": record.host_rating,
            "ipod_rating": record.ipod_rating,
            "pending": (
                {
                    "host": record.pending.host_rating,
                    "target": record.pending.target_rating,
                }
                if record.pending is not None
                else None
            ),
        }
        for (kind, identity), record in sorted(records.items())
    ]
    payload = _canonical_json(
        {
            "version": 1,
            "records": rows,
            "sha256": hashlib.sha256(_canonical_json(rows)).hexdigest(),
        }
    )
    return session.atomic_write(
        RATING_SYNC_PATH, payload, expected=previous.revision, create_parents=True
    ).fingerprint


def stage_rating_writes(
    session: FilesystemSession,
    reviewed: IPodMediaLibrary,
    pending: dict[int, PendingRatingWrite],
) -> IPodMediaLibrary:
    """Save retry intent before the corresponding iPod ratings can commit."""
    catalog = _load_rating_catalog(session)
    if catalog.revision != reviewed.rating_revision or (
        session.fingerprint(LIBRARY_SYNC_HELPER_PATH) != reviewed.helper_revision
    ):
        raise LibrarySyncHelperError(
            "Rating Sync state changed after Review. Rescan before retrying."
        )
    tracks = tuple(
        replace(track, sync=replace(track.sync, pending_rating=intent))
        if track.sync is not None
        and (intent := pending.get(track.track_id)) is not None
        else track
        for track in reviewed.tracks
    )
    updates = _rating_records(
        tuple(track for track in tracks if track.track_id in pending)
    )
    revision = _save_rating_catalog(session, catalog.records | updates, catalog)
    return replace(reviewed, tracks=tracks, rating_revision=revision)


def _save_helper(
    session: FilesystemSession,
    tracks: tuple[IPodTrackFingerprint, ...],
    images: tuple[IPodImageFingerprint, ...],
    library_sha256: str,
    loaded: _LoadedHelper,
    *,
    playlists: tuple[PlaylistAssociation, ...] | None = None,
) -> tuple[FileFingerprint, FileFingerprint | None]:
    rating_revision = loaded.ratings.revision
    if playlists is None:
        playlists = loaded.playlists
    unchanged = (
        tracks == loaded.tracks
        and playlists == loaded.playlists
        and images == loaded.images
        and library_sha256 == loaded.library_sha256
        and loaded.version == _FORMAT_VERSION
        and (not loaded.inline_ratings or loaded.rating_issue is not None)
        and loaded.revision is not None
    )
    if unchanged:
        assert loaded.revision is not None
        return loaded.revision, rating_revision
    if loaded.inline_ratings and loaded.rating_issue is None:
        # Preserve preview baselines before removing them from the v7 document.
        rating_revision = _save_rating_catalog(
            session,
            loaded.ratings.records | _rating_records(loaded.tracks),
            loaded.ratings,
        )
    payload = _encode_helper(
        tracks,
        images,
        library_sha256,
        updated_at=Instant.now().to_fixed_offset().format_iso(unit="microsecond"),
        playlists=playlists,
        include_inline_ratings=loaded.inline_ratings
        and loaded.rating_issue is not None,
    )
    result = session.atomic_write(
        LIBRARY_SYNC_HELPER_PATH,
        payload,
        expected=loaded.revision,
        create_parents=True,
    )
    if loaded.rating_issue is None:
        # Pending Host work must survive a failed update of the v7 helper.
        rating_revision = _save_rating_catalog(
            session,
            _rating_records(tracks),
            replace(loaded.ratings, revision=rating_revision),
        )
    return result.fingerprint, rating_revision


def _track_path(track: Track) -> DevicePath:
    location = track.metadata.location.strip()
    if not location:
        raise ValueError("the iTunesDB Track has no media location")
    path = DevicePath(location)
    if not path.is_relative_to(_IPOD_CONTROL_PATH):
        raise ValueError("the iTunesDB Track location is outside iPod_Control")
    return path


def _photo_path(photo: Photo) -> DevicePath:
    candidates = tuple(
        representation
        for representation in photo.representations
        if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
        and representation.relative_path
    )
    if not candidates:
        raise ValueError("the Photo has no full-resolution file to fingerprint")
    representation = candidates[0]
    path = DevicePath(representation.relative_path)
    if not path.is_relative_to(_PHOTOS_PATH):
        raise ValueError("the Photo's full-resolution file is outside Photos")
    return path


def _regular_file(session: FilesystemSession, path: DevicePath) -> DeviceEntry:
    entry = session.stat(path)
    if entry.kind is not DeviceEntryKind.FILE:
        raise ValueError("the Library location is not a regular file")
    return entry


def _database_track_id(track: Track) -> int:
    return 0 if track.ipod is None else max(0, track.ipod.db_track_id)


def _track_key(track: IPodTrackFingerprint) -> tuple[str, int]:
    return (
        ("database", track.database_track_id)
        if track.database_track_id > 0
        else ("track", track.track_id)
    )


def _track_key_for_track(track: Track) -> tuple[str, int]:
    database_track_id = _database_track_id(track)
    return (
        ("database", database_track_id)
        if database_track_id > 0
        else ("track", track.track_id)
    )


def _matches(
    session: FilesystemSession,
    record: IPodTrackFingerprint | IPodImageFingerprint,
    path: DevicePath,
    entry: DeviceEntry,
) -> bool:
    return (
        record.path == path
        and record.size_bytes == entry.size
        and session.modified_time_matches(entry.modified_ns, record.modified_ns)
    )


def _analysis_matches(
    session: FilesystemSession, record: IPodAnalysisRecord, entry: DeviceEntry
) -> bool:
    return record.size_bytes == entry.size and session.modified_time_matches(
        entry.modified_ns, record.modified_ns
    )


def _verify_file_unchanged(
    session: FilesystemSession, path: DevicePath, entry: DeviceEntry
) -> None:
    current = _regular_file(session, path)
    if current.size != entry.size or not session.modified_time_matches(
        current.modified_ns, entry.modified_ns
    ):
        raise ValueError("the media file changed while it was fingerprinted")


def _analyzed_track(
    track: Track,
    path: DevicePath,
    entry: DeviceEntry,
    acoustic: str,
    previous: IPodTrackFingerprint | None,
) -> IPodTrackFingerprint:
    return IPodTrackFingerprint(
        _database_track_id(track),
        track.track_id,
        path,
        entry.size,
        entry.modified_ns,
        acoustic,
        previous.sync
        if previous is not None and previous.acoustic_fingerprint == acoustic
        else None,
    )


def _encode_helper(
    tracks: tuple[IPodTrackFingerprint, ...],
    images: tuple[IPodImageFingerprint, ...],
    library_sha256: str,
    *,
    updated_at: str,
    playlists: tuple[PlaylistAssociation, ...] = (),
    include_inline_ratings: bool = False,
) -> bytes:
    _validate_playlist_associations(playlists)
    if len(tracks) + len(images) + len(playlists) > _MAX_RECORDS:
        raise LibrarySyncHelperError("The Sync helper contains too many records")
    records = {
        "tracks": [
            _track_document(item, include_inline_ratings=include_inline_ratings)
            for item in tracks
        ],
        "images": [_image_document(item) for item in images],
        "playlists": [
            {
                "host_playlist_id": str(item.host_playlist_id),
                "ipod_playlist_id": str(item.ipod_playlist_id),
            }
            for item in playlists
        ],
    }
    document = {
        "version": _FORMAT_VERSION,
        "updated_at": updated_at,
        "library_sha256": library_sha256,
        **records,
        "catalog_sha256": hashlib.sha256(_canonical_json(records)).hexdigest(),
    }
    return _canonical_json(document)


def _decode_helper(payload: bytes) -> _LoadedHelper:
    try:
        raw: object = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs)
    except RecursionError as error:
        raise ValueError("The Sync helper is nested too deeply") from error
    document = _object(raw, "Sync helper")
    expected = {
        "version",
        "updated_at",
        "library_sha256",
        "tracks",
        "images",
        "catalog_sha256",
    }
    version = _nonnegative_integer(document.get("version"), "version")
    if version >= 7:
        expected.add("playlists")
    if set(document) != expected or version not in (
        1,
        2,
        3,
        4,
        5,
        6,
        _FORMAT_VERSION,
    ):
        raise ValueError("Sync helper fields or version are unsupported")
    tracks_raw = _array(document["tracks"], "tracks")
    images_raw = _array(document["images"], "images")
    playlists_raw = _array(document["playlists"], "playlists") if version >= 7 else []
    if len(tracks_raw) + len(images_raw) + len(playlists_raw) > _MAX_RECORDS:
        raise ValueError("Sync helper contains too many records")
    records = {"tracks": tracks_raw, "images": images_raw}
    if version >= 7:
        records["playlists"] = playlists_raw
    catalog_sha256 = _text(document["catalog_sha256"], "catalog_sha256")
    _require_sha256(catalog_sha256, "catalog checksum")
    if hashlib.sha256(_canonical_json(records)).hexdigest() != catalog_sha256:
        raise ValueError("Sync helper checksum does not match")
    library_sha256 = _text(document["library_sha256"], "library_sha256")
    _require_sha256(library_sha256, "Library fingerprint")
    tracks = tuple(_track_from_document(item) for item in tracks_raw)
    images = tuple(_image_from_document(item) for item in images_raw)
    if len({_track_key(item) for item in tracks}) != len(tracks):
        raise ValueError("Sync helper contains duplicate Track identities")
    if len({item.image_id for item in images}) != len(images):
        raise ValueError("Sync helper contains duplicate image identities")
    playlists = tuple(_playlist_from_document(item) for item in playlists_raw)
    _validate_playlist_associations(playlists)
    return _LoadedHelper(
        tracks,
        images,
        library_sha256,
        _text(document["updated_at"], "updated_at"),
        version,
        playlists=playlists,
        inline_ratings=any(
            isinstance(row, dict)
            and isinstance(sync := cast("dict[str, object]", row).get("sync"), dict)
            and ("host_rating" in sync or "ipod_rating" in sync)
            for row in chain(tracks_raw, images_raw)
        ),
    )


def _playlist_from_document(value: object) -> PlaylistAssociation:
    document = _exact_object(
        value, "Playlist match", {"host_playlist_id", "ipod_playlist_id"}
    )
    return PlaylistAssociation(
        _decimal_identifier(document["host_playlist_id"], "Host Playlist identity"),
        _decimal_identifier(document["ipod_playlist_id"], "iPod Playlist identity"),
    )


def _validate_playlist_associations(values: tuple[PlaylistAssociation, ...]) -> None:
    if any(item.host_playlist_id <= 0 or item.ipod_playlist_id <= 0 for item in values):
        raise ValueError("Playlist matches require positive identities")
    if len({item.host_playlist_id for item in values}) != len(values) or len(
        {item.ipod_playlist_id for item in values}
    ) != len(values):
        raise ValueError("Playlist matches must be one-to-one")


def _track_document(
    value: IPodTrackFingerprint, *, include_inline_ratings: bool
) -> dict[str, object]:
    sync = _sync_document(value.sync)
    if include_inline_ratings and sync is not None and value.sync is not None:
        sync.update(
            host_rating=value.sync.host_rating, ipod_rating=value.sync.ipod_rating
        )
    return {
        "database_track_id": str(value.database_track_id),
        "track_id": value.track_id,
        "path": str(value.path),
        "size_bytes": value.size_bytes,
        "modified_ns": value.modified_ns,
        "acoustic_fingerprint": encode_fingerprint(value.acoustic_fingerprint),
        "sync": sync,
    }


def _image_document(value: IPodImageFingerprint) -> dict[str, object]:
    return {
        "image_id": value.image_id,
        "path": str(value.path),
        "size_bytes": value.size_bytes,
        "modified_ns": value.modified_ns,
        "content_sha256": value.content_sha256,
        "sync": _sync_document(value.sync),
    }


def _sync_document(value: SyncDetails | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "last_synced_at": value.last_synced_at,
        "host_path_hint": value.host_path_hint,
        "host_size_bytes": value.host_size_bytes,
        "host_modified_ns": value.host_modified_ns,
        "source_format": value.source_format,
        "ipod_format": value.ipod_format,
        "was_transcoded": value.was_transcoded,
        "host_content_sha256": value.host_content_sha256,
        "host_artwork_sha256": value.host_artwork_sha256,
        "ipod_artwork_id": value.ipod_artwork_id,
        "ipod_tag_sha256": value.ipod_tag_sha256,
        "ipod_baseline_pending": value.ipod_baseline_pending,
        "host_tag_sha256": value.host_tag_sha256,
        "file_tag_policy": value.file_tag_policy,
        "stream_selection_sha256": value.stream_selection_sha256,
    }


def _track_from_document(value: object) -> IPodTrackFingerprint:
    row = _exact_object(
        value,
        "Track record",
        {
            "database_track_id",
            "track_id",
            "path",
            "size_bytes",
            "modified_ns",
            "acoustic_fingerprint",
            "sync",
        },
    )
    database_track_id = _decimal_identifier(
        row["database_track_id"], "database_track_id"
    )
    acoustic = _text(row["acoustic_fingerprint"], "acoustic_fingerprint")
    return IPodTrackFingerprint(
        database_track_id=database_track_id,
        track_id=_positive_integer(row["track_id"], "track_id"),
        path=DevicePath(_text(row["path"], "path")),
        size_bytes=_nonnegative_integer(row["size_bytes"], "size_bytes"),
        modified_ns=_signed_integer(row["modified_ns"], "modified_ns"),
        acoustic_fingerprint=decode_fingerprint(acoustic),
        sync=_sync_from_document(row["sync"]),
    )


def _image_from_document(value: object) -> IPodImageFingerprint:
    row = _exact_object(
        value,
        "image record",
        {
            "image_id",
            "path",
            "size_bytes",
            "modified_ns",
            "content_sha256",
            "sync",
        },
    )
    return IPodImageFingerprint(
        image_id=_positive_integer(row["image_id"], "image_id"),
        path=DevicePath(_text(row["path"], "path")),
        size_bytes=_nonnegative_integer(row["size_bytes"], "size_bytes"),
        modified_ns=_signed_integer(row["modified_ns"], "modified_ns"),
        content_sha256=_text(row["content_sha256"], "content_sha256"),
        sync=_sync_from_document(row["sync"]),
    )


def _sync_from_document(value: object) -> SyncDetails | None:
    if value is None:
        return None
    required = {
        "last_synced_at",
        "host_path_hint",
        "host_size_bytes",
        "host_modified_ns",
        "source_format",
        "ipod_format",
        "was_transcoded",
    }
    optional = {
        "host_content_sha256",
        "host_artwork_sha256",
        "ipod_artwork_id",
        "ipod_tag_sha256",
        "ipod_baseline_pending",
        "host_payload_sha256",  # Ignored field from an earlier v4 development build.
        "host_tag_sha256",
        "file_tag_policy",
        "stream_selection_sha256",
        "host_rating",
        "ipod_rating",
    }
    row = _object(value, "Sync details")
    if not required <= row.keys() or row.keys() - required - optional:
        raise ValueError("Sync details fields are invalid")
    was_transcoded = row["was_transcoded"]
    if not isinstance(was_transcoded, bool):
        raise ValueError("was_transcoded must be a boolean")
    baseline_pending = row.get("ipod_baseline_pending", False)
    if not isinstance(baseline_pending, bool):
        raise ValueError("ipod_baseline_pending must be a boolean")
    return SyncDetails(
        last_synced_at=_text(row["last_synced_at"], "last_synced_at"),
        host_path_hint=_text(row["host_path_hint"], "host_path_hint"),
        host_size_bytes=_nonnegative_integer(row["host_size_bytes"], "host_size_bytes"),
        host_modified_ns=_signed_integer(row["host_modified_ns"], "host_modified_ns"),
        source_format=_text(row["source_format"], "source_format"),
        ipod_format=_text(row["ipod_format"], "ipod_format"),
        was_transcoded=was_transcoded,
        host_content_sha256=_text(
            row.get("host_content_sha256", ""), "host_content_sha256"
        ),
        host_artwork_sha256=(
            None
            if row.get("host_artwork_sha256") is None
            else _text(row["host_artwork_sha256"], "host_artwork_sha256")
        ),
        ipod_artwork_id=(
            None
            if row.get("ipod_artwork_id") is None
            else _nonnegative_integer(row["ipod_artwork_id"], "ipod_artwork_id")
        ),
        ipod_tag_sha256=(
            None
            if row.get("ipod_tag_sha256") is None
            else _text(row["ipod_tag_sha256"], "ipod_tag_sha256")
        ),
        ipod_baseline_pending=baseline_pending,
        file_tag_policy=(
            None
            if row.get("file_tag_policy") is None
            else _text(row["file_tag_policy"], "file_tag_policy")
        ),
        host_rating=None
        if row.get("host_rating") is None
        else _nonnegative_integer(row["host_rating"], "host_rating"),
        ipod_rating=None
        if row.get("ipod_rating") is None
        else _nonnegative_integer(row["ipod_rating"], "ipod_rating"),
        stream_selection_sha256=(
            None
            if row.get("stream_selection_sha256") is None
            else _text(row["stream_selection_sha256"], "stream_selection_sha256")
        ),
        host_tag_sha256=(
            None
            if row.get("host_tag_sha256") is None
            else _text(row["host_tag_sha256"], "host_tag_sha256")
        ),
    )


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except RecursionError as error:
        raise ValueError("The Sync helper is nested too deeply") from error


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate Sync helper field: {key}")
        result[key] = value
    return result


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    mapping = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in mapping):
        raise ValueError(f"{label} must be an object")
    return cast("dict[str, object]", mapping)


def _exact_object(
    value: object,
    label: str,
    fields: set[str],
) -> dict[str, object]:
    result = _object(value, label)
    if set(result) != fields:
        raise ValueError(f"{label} fields are invalid")
    return result


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return cast("list[object]", value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    integer = _signed_integer(value, label)
    if integer < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return integer


def _signed_integer(value: object, label: str) -> int:
    """Filesystem timestamps may predate the Unix epoch; preserve their facts."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _nonnegative_integer(value, label)
    if result == 0:
        raise ValueError(f"{label} must be positive")
    return result


def _decimal_identifier(value: object, label: str) -> int:
    text = _text(value, label)
    if not text or not text.isascii() or not text.isdigit():
        raise ValueError(f"{label} must be decimal text")
    return int(text)


def _require_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _emit(
    progress: ProgressCallback | None,
    stage: IPodMediaScanStage,
    completed: int,
    total: int,
    message: str,
    *,
    path: DevicePath | None = None,
    reused: int = 0,
) -> None:
    if progress is not None:
        progress(
            IPodMediaScanProgress(
                stage,
                completed,
                total,
                message,
                path,
                reused,
            )
        )


__all__ = [
    "LIBRARY_SYNC_HELPER_PATH",
    "IPodImageFingerprint",
    "IPodMediaCacheStats",
    "IPodMediaLibrary",
    "IPodMediaScanIssue",
    "IPodMediaScanProgress",
    "IPodMediaScanStage",
    "IPodMediaScanner",
    "IPodTrackFingerprint",
    "LibrarySyncHelperCancelledError",
    "LibrarySyncHelperError",
    "SyncDetails",
]
