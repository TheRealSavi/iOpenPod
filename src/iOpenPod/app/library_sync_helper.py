"""Scan Active-iPod media and persist its non-authoritative Sync correlation index."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, cast

from iOpenPod.app.host_media_fingerprint import (
    FpcalcError,
    FpcalcFingerprinter,
    FpcalcUnavailableError,
    normalize_fpcalc_fingerprint,
)
from iPodDB.library import PhotoRepresentationKind
from storage import (
    DeviceEntry,
    DeviceEntryKind,
    DevicePath,
    FileFingerprint,
    HostPath,
    StorageError,
)
from storage.device_capture import capture_device_file

if TYPE_CHECKING:
    from pathlib import Path

    from iPodDB.library import LibrarySnapshot, Photo, Track
    from storage import FilesystemSession


LIBRARY_SYNC_HELPER_PATH = DevicePath("iPod_Control/iOpenPod/library-sync-helper.json")
_IPOD_CONTROL_PATH = DevicePath("iPod_Control")
_PHOTOS_PATH = DevicePath("Photos")
_FORMAT_VERSION = 3
_MAX_HELPER_BYTES = 64 * 1024 * 1024
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

    def __post_init__(self) -> None:
        if not self.last_synced_at.strip():
            raise ValueError("Sync Details require a last-synced timestamp")
        if self.host_size_bytes < 0 or self.host_modified_ns < 0:
            raise ValueError("Sync Details require non-negative Host file facts")
        if self.host_content_sha256:
            _require_sha256(self.host_content_sha256, "Host content fingerprint")


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
        if self.size_bytes < 0 or self.modified_ns < 0:
            raise ValueError("An iPod Track fingerprint needs non-negative file facts")
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
        if self.size_bytes < 0 or self.modified_ns < 0:
            raise ValueError("An iPod image fingerprint needs non-negative file facts")
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


@dataclass(frozen=True, slots=True)
class SyncedTrack:
    """Successful Host provenance for one committed, verified device location."""

    path: DevicePath
    acoustic_fingerprint: str
    sync: SyncDetails


@dataclass(frozen=True, slots=True)
class SyncedImage:
    """Successful Host provenance for one committed full-resolution Photo."""

    path: DevicePath
    content_sha256: str
    sync: SyncDetails


def publish_sync_helper(
    session: FilesystemSession,
    library: LibrarySnapshot,
    previous: IPodMediaLibrary,
    synced: tuple[SyncedTrack, ...],
    synced_images: tuple[SyncedImage, ...] = (),
    *,
    library_sha256: str,
) -> IPodMediaLibrary:
    """Publish matching evidence only after the caller's Library commit succeeds.

    Never decode files over the USB bus again: committed locations supply their
    verified file facts, while the Host scan supplies acoustic matching evidence.
    A changed or malformed helper is preserved for recovery rather than overwritten.
    """

    loaded, issue = _load_helper(session)
    if issue is not None or not loaded.writable:
        raise LibrarySyncHelperError(
            "The existing Sync helper is invalid and was preserved. Recover or "
            "explicitly replace it before the next Sync."
        )
    if loaded.revision != previous.helper_revision:
        raise LibrarySyncHelperError(
            "The Sync helper changed after Review. Rescan the iPod before retrying."
        )
    updated = {str(item.path).casefold(): item for item in synced}
    retained = {item.track_id: item for item in previous.tracks}
    tracks: list[IPodTrackFingerprint] = []
    for track in library.tracks:
        path = _track_path(track)
        new = updated.get(str(path).casefold())
        old = retained.get(track.track_id)
        if new is None and old is None:
            continue
        entry = _regular_file(session, path)
        if new is not None:
            tracks.append(
                IPodTrackFingerprint(
                    _database_track_id(track),
                    track.track_id,
                    path,
                    entry.size,
                    entry.modified_ns,
                    new.acoustic_fingerprint,
                    new.sync,
                )
            )
        elif old is not None and _matches(session, old, path, entry):
            tracks.append(replace(old, database_track_id=_database_track_id(track)))
    old_images = {item.image_id: item for item in previous.images}
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
            path = _photo_path(photo)
            if _matches(session, prior, path, _regular_file(session, path)):
                images.append(prior)
    revision = _save_helper(
        session, tuple(tracks), tuple(images), library_sha256, loaded
    )
    flush = session.flush()
    issues = (
        ()
        if flush.complete
        else (
            IPodMediaScanIssue(
                "Sync helper",
                "The helper was verified, but complete device flushing "
                "could not be confirmed. Safely eject before unplugging. "
                + flush.detail,
            ),
        )
    )
    return IPodMediaLibrary(
        tuple(tracks),
        tuple(images),
        issues,
        IPodMediaCacheStats(reused=len(tracks) + len(images)),
        revision,
        True,
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
class _LoadedHelper:
    tracks: tuple[IPodTrackFingerprint, ...] = ()
    images: tuple[IPodImageFingerprint, ...] = ()
    library_sha256: str = ""
    updated_at: str = ""
    revision: FileFingerprint | None = None
    writable: bool = True


class IPodMediaScanner:
    """Fingerprint only device media absent from a valid, matching helper entry."""

    def __init__(
        self,
        fingerprinter: _AcousticFingerprinter | None = None,
        *,
        temporary_directory: Path | None = None,
    ) -> None:
        self._fingerprinter = fingerprinter or FpcalcFingerprinter()
        self._temporary_directory = temporary_directory

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
        _emit(progress, IPodMediaScanStage.LOADING, 0, 0, "Reading Sync helper…")
        loaded, load_issue = _load_helper(session)
        issues = [load_issue] if load_issue is not None else []
        cached_tracks = {_track_key(item): item for item in loaded.tracks}
        cached_images = {item.image_id: item for item in loaded.images}

        tracks: list[IPodTrackFingerprint] = []
        images: list[IPodImageFingerprint] = []
        reused = 0
        fingerprinted = 0
        copied_fingerprints: dict[tuple[str, int, int], str] = {}
        image_fingerprints: dict[tuple[str, int, int], str] = {}
        fingerprinting_unavailable = False

        for index, track in enumerate(library.tracks, start=1):
            checkpoint()
            track_path: DevicePath | None = None
            try:
                track_path = _track_path(track)
                entry = _regular_file(session, track_path)
                track_previous = cached_tracks.get(_track_key_for_track(track))
                if track_previous is not None and _matches(
                    session, track_previous, track_path, entry
                ):
                    track_record = replace(
                        track_previous,
                        track_id=track.track_id,
                        database_track_id=_database_track_id(track),
                    )
                    reused += 1
                    label = f"Reusing iPod Track {index:,} of {len(library.tracks):,}…"
                else:
                    identity = (str(track_path), entry.size, entry.modified_ns)
                    acoustic = copied_fingerprints.get(identity)
                    if acoustic is None:
                        if fingerprinting_unavailable:
                            continue
                        acoustic = self._fingerprint_track(
                            session,
                            track_path,
                            checkpoint,
                        )
                        copied_fingerprints[identity] = acoustic
                    sync = (
                        track_previous.sync
                        if track_previous is not None
                        and track_previous.acoustic_fingerprint == acoustic
                        else None
                    )
                    track_record = IPodTrackFingerprint(
                        database_track_id=_database_track_id(track),
                        track_id=track.track_id,
                        path=track_path,
                        size_bytes=entry.size,
                        modified_ns=entry.modified_ns,
                        acoustic_fingerprint=acoustic,
                        sync=sync,
                    )
                    fingerprinted += 1
                    label = f"Fingerprinting iPod Track {index:,} of {len(library.tracks):,}…"
                tracks.append(track_record)
                current = session.stat(track_path)
                if current.size != entry.size or not session.modified_time_matches(
                    current.modified_ns,
                    entry.modified_ns,
                ):
                    tracks.pop()
                    raise ValueError(
                        "the media file changed while it was fingerprinted"
                    )
            except FpcalcUnavailableError as error:
                fingerprinting_unavailable = True
                issues.append(
                    IPodMediaScanIssue(
                        "Acoustic matching",
                        f"Acoustic matching is unavailable; existing Sync Details and independent items remain usable. {error}",
                    )
                )
                label = "Continuing without acoustic matching…"
            except (FpcalcError, OSError, StorageError, ValueError) as error:
                issues.append(
                    IPodMediaScanIssue(
                        f"Track {track.track_id}",
                        str(error),
                    )
                )
                label = f"Could not fingerprint iPod Track {index:,} of {len(library.tracks):,}."
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
                    label = f"Reusing iPod image {index:,} of {len(photos):,}…"
                else:
                    identity = (str(image_path), entry.size, entry.modified_ns)
                    digest = image_fingerprints.get(identity)
                    if digest is None:
                        digest = session.fingerprint(image_path).sha256
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
                    fingerprinted += 1
                    label = f"Fingerprinting iPod image {index:,} of {len(photos):,}…"
                images.append(image_record)
                current = session.stat(image_path)
                if current.size != entry.size or not session.modified_time_matches(
                    current.modified_ns,
                    entry.modified_ns,
                ):
                    images.pop()
                    raise ValueError(
                        "the image file changed while it was fingerprinted"
                    )
            except (OSError, StorageError, ValueError) as error:
                issues.append(IPodMediaScanIssue(f"Image {photo.photo_id}", str(error)))
                label = (
                    f"Could not fingerprint iPod image {index:,} of {len(photos):,}."
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
            helper_revision = _save_helper(
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
                        "The helper was verified, but the operating system did not "
                        f"confirm a complete device flush: {flush.detail}",
                    )
                )
        elif persist and not loaded.writable:
            issues.append(
                IPodMediaScanIssue(
                    "Sync helper",
                    "The existing helper is invalid and was left unchanged; its "
                    "Sync history must be recovered or explicitly replaced.",
                )
            )
        elif not persist and report_read_only:
            issues.append(
                IPodMediaScanIssue(
                    "Sync helper",
                    "The iPod is not safely writable, so newly calculated "
                    "fingerprints were not persisted.",
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
        )

    def _fingerprint_track(
        self,
        session: FilesystemSession,
        path: DevicePath,
        checkpoint: CancellationCheck,
    ) -> str:
        with capture_device_file(
            session,
            path,
            checkpoint=checkpoint,
            temporary_directory=(
                HostPath(self._temporary_directory)
                if self._temporary_directory is not None
                else None
            ),
        ) as captured:
            return self._fingerprinter.fingerprint(captured, checkpoint=checkpoint)


def _load_helper(
    session: FilesystemSession,
) -> tuple[_LoadedHelper, IPodMediaScanIssue | None]:
    if not session.exists(LIBRARY_SYNC_HELPER_PATH):
        return _LoadedHelper(), None
    entry = session.stat(LIBRARY_SYNC_HELPER_PATH)
    if entry.kind is not DeviceEntryKind.FILE or entry.size > _MAX_HELPER_BYTES:
        return (
            _LoadedHelper(writable=False),
            IPodMediaScanIssue(
                "Sync helper",
                "The existing helper is not a bounded regular file.",
            ),
        )
    source = session.read_snapshot(
        LIBRARY_SYNC_HELPER_PATH,
        max_bytes=_MAX_HELPER_BYTES,
    )
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
                "Sync helper", f"The existing helper is invalid: {error}"
            ),
        )
    return replace(loaded, revision=source.fingerprint), None


def _save_helper(
    session: FilesystemSession,
    tracks: tuple[IPodTrackFingerprint, ...],
    images: tuple[IPodImageFingerprint, ...],
    library_sha256: str,
    loaded: _LoadedHelper,
) -> FileFingerprint:
    unchanged = (
        tracks == loaded.tracks
        and images == loaded.images
        and library_sha256 == loaded.library_sha256
        and loaded.revision is not None
    )
    if unchanged:
        assert loaded.revision is not None
        return loaded.revision
    payload = _encode_helper(
        tracks,
        images,
        library_sha256,
        updated_at=datetime.now(UTC).isoformat(),
    )
    result = session.atomic_write(
        LIBRARY_SYNC_HELPER_PATH,
        payload,
        expected=loaded.revision,
        create_parents=True,
    )
    return result.fingerprint


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


def _encode_helper(
    tracks: tuple[IPodTrackFingerprint, ...],
    images: tuple[IPodImageFingerprint, ...],
    library_sha256: str,
    *,
    updated_at: str,
) -> bytes:
    if len(tracks) + len(images) > _MAX_RECORDS:
        raise LibrarySyncHelperError("The Sync helper contains too many records")
    records = {
        "tracks": [_track_document(item) for item in tracks],
        "images": [_image_document(item) for item in images],
    }
    document = {
        "version": _FORMAT_VERSION,
        "updated_at": updated_at,
        "library_sha256": library_sha256,
        **records,
        "catalog_sha256": hashlib.sha256(_canonical_json(records)).hexdigest(),
    }
    payload = _canonical_json(document)
    if len(payload) > _MAX_HELPER_BYTES:
        raise LibrarySyncHelperError("The Sync helper exceeds 64 MiB")
    return payload


def _decode_helper(payload: bytes) -> _LoadedHelper:
    raw: object = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs)
    document = _object(raw, "Sync helper")
    expected = {
        "version",
        "updated_at",
        "library_sha256",
        "tracks",
        "images",
        "catalog_sha256",
    }
    if set(document) != expected or document["version"] not in (1, 2, _FORMAT_VERSION):
        raise ValueError("Sync helper fields or version are unsupported")
    tracks_raw = _array(document["tracks"], "tracks")
    images_raw = _array(document["images"], "images")
    if len(tracks_raw) + len(images_raw) > _MAX_RECORDS:
        raise ValueError("Sync helper contains too many records")
    records = {"tracks": tracks_raw, "images": images_raw}
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
    return _LoadedHelper(
        tracks,
        images,
        library_sha256,
        _text(document["updated_at"], "updated_at"),
    )


def _track_document(value: IPodTrackFingerprint) -> dict[str, object]:
    return {
        "database_track_id": str(value.database_track_id),
        "track_id": value.track_id,
        "path": str(value.path),
        "size_bytes": value.size_bytes,
        "modified_ns": value.modified_ns,
        "acoustic_fingerprint": value.acoustic_fingerprint,
        "sync": _sync_document(value.sync),
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
        modified_ns=_nonnegative_integer(row["modified_ns"], "modified_ns"),
        acoustic_fingerprint=normalize_fpcalc_fingerprint(acoustic) if acoustic else "",
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
        modified_ns=_nonnegative_integer(row["modified_ns"], "modified_ns"),
        content_sha256=_text(row["content_sha256"], "content_sha256"),
        sync=_sync_from_document(row["sync"]),
    )


def _sync_from_document(value: object) -> SyncDetails | None:
    if value is None:
        return None
    row = _exact_object(
        value,
        "Sync details",
        {
            "last_synced_at",
            "host_path_hint",
            "host_size_bytes",
            "host_modified_ns",
            "source_format",
            "ipod_format",
            "was_transcoded",
            *(
                {"host_content_sha256"}
                if isinstance(value, dict) and "host_content_sha256" in value
                else set()
            ),
        },
    )
    was_transcoded = row["was_transcoded"]
    if not isinstance(was_transcoded, bool):
        raise ValueError("was_transcoded must be a boolean")
    return SyncDetails(
        last_synced_at=_text(row["last_synced_at"], "last_synced_at"),
        host_path_hint=_text(row["host_path_hint"], "host_path_hint"),
        host_size_bytes=_nonnegative_integer(row["host_size_bytes"], "host_size_bytes"),
        host_modified_ns=_nonnegative_integer(
            row["host_modified_ns"], "host_modified_ns"
        ),
        source_format=_text(row["source_format"], "source_format"),
        ipod_format=_text(row["ipod_format"], "ipod_format"),
        was_transcoded=was_transcoded,
        host_content_sha256=_text(
            row.get("host_content_sha256", ""), "host_content_sha256"
        ),
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
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
