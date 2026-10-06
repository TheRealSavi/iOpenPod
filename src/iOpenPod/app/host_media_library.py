"""Scan user-owned Host folders into the common immutable Library contract."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from enum import StrEnum
from io import BytesIO
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import mutagen
from mutagen.flac import Picture
from PIL import Image, ImageOps

from iOpenPod.app.display_text import source_text
from iOpenPod.app.host_media_fingerprint import (
    FpcalcError,
    FpcalcFingerprinter,
    normalize_fpcalc_fingerprint,
)
from iOpenPod.app.host_media_folders import HostMediaFolder, HostMediaType
from iOpenPod.app.host_playlists import (
    MAX_PLAYLIST_BYTES,
    PLAYLIST_EXTENSIONS,
    parse_host_playlist,
)
from iOpenPod.app.media.content_type import classify_content_type
from iOpenPod.app.media.inspection import MediaInspectionError, MediaInspector
from iOpenPod.app.media.models import MediaTag
from iOpenPod.app.media.tags import (
    TAG_NAMES,
    apply_tag_values,
    inspection_tag_values,
    read_tag_values,
)
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.models.photos import PhotoImage, PhotoRequest
from iPodDB.library import (
    LibrarySnapshot,
    MediaType,
    Photo,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Playlist,
    PlaylistEntry,
    PlaylistKind,
    PlaylistSortOrder,
    Track,
    TrackMetadata,
)
from storage import AtomicHostFile, HostPath, StorageError
from storage.host_directory import HostEntryKind, LocalHostDirectory
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from typing import BinaryIO

logger = logging.getLogger(__name__)

_CACHE_VERSION = 10
_MAX_CACHE_BYTES = 64 * 1024 * 1024
_MAX_CACHE_ENTRIES = 250_000
_MAX_ARTWORK_BYTES = 64 * 1024 * 1024
_MAX_INSPECTION_WORKERS = 8

_AUDIO_EXTENSIONS = frozenset(
    {
        ".aac",
        ".aif",
        ".aiff",
        ".alac",
        ".flac",
        ".m4a",
        ".m4b",
        ".mp3",
        ".oga",
        ".ogg",
        ".opus",
        ".wav",
        ".wma",
        ".wv",
    }
)
_VIDEO_EXTENSIONS = frozenset(
    {
        ".avi",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".webm",
        ".wmv",
    }
)
_PHOTO_EXTENSIONS = frozenset(
    {
        ".bmp",
        ".gif",
        ".heic",
        ".heif",
        ".jpeg",
        ".jpg",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
    }
)
_CACHE_ENTRY_FIELDS = frozenset(
    {
        "kind",
        "metadata",
        "modified_ns",
        "path",
        "size_bytes",
        "warning",
    }
)
_TRACK_METADATA_FIELDS = frozenset(
    {
        "album",
        "album_artist",
        "artist",
        "bitrate_kbps",
        "disc_number",
        "genre",
        "length_ms",
        "sample_rate_hz",
        "title",
        "total_discs",
        "total_tracks",
        "track_number",
        "year",
        "media_type",
        "tag_values",
        "acoustic_fingerprint",
        "artwork_content_sha256",
        "artwork_kind",
        "artwork_modified_ns",
        "artwork_path",
        "artwork_size_bytes",
    }
)
_PHOTO_METADATA_FIELDS = frozenset({"content_sha256", "height", "width"})
_PLAYLIST_METADATA_FIELDS = frozenset({"references", "title"})
_FOLDER_ARTWORK_STEMS = (
    "cover",
    "front",
    "folder",
    "albumart",
    "album art",
    "album",
    "artwork",
)
_FOLDER_ARTWORK_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
)


class HostMediaFileKind(StrEnum):
    """One semantic kind found by a Host Media Library scan."""

    AUDIO = "audio"
    VIDEO = "video"
    PHOTO = "photo"
    PLAYLIST = "playlist"


class HostArtworkKind(StrEnum):
    """Where one lazily loaded Host cover was observed during the scan."""

    EMBEDDED = "embedded"
    FOLDER = "folder"


class HostMediaScanStage(StrEnum):
    DISCOVERING = "discovering"
    READING = "reading"
    EXTERNAL = "external"
    FINALIZING = "finalizing"
    COMPLETE = "complete"


class HostMediaScanError(RuntimeError):
    """A Host Media Library scan could not produce a coherent result."""


class HostMediaScanCancelledError(HostMediaScanError):
    """Cooperative cancellation reached a safe scan checkpoint."""


class HostMediaTreeChangedError(HostMediaScanError):
    """The selected Host Media Library changed during its scan."""


@dataclass(frozen=True, slots=True)
class HostMediaScanProgress:
    stage: HostMediaScanStage
    completed: int
    total: int
    message: str
    path: HostPath | None = None
    cache_hits: int = 0


@dataclass(frozen=True, slots=True)
class HostMediaCacheStats:
    reused: int = 0
    inspected: int = 0

    @property
    def total(self) -> int:
        return self.reused + self.inspected


@dataclass(frozen=True, slots=True)
class HostMediaScanIssue:
    path: HostPath
    detail: str


@dataclass(frozen=True, slots=True)
class PlaylistExternalReference:
    """A local playlist entry outside the selected Host scan scope."""

    target: HostPath
    playlists: tuple[HostPath, ...]
    available: bool
    detail: str = ""
    observation: LocalHostFile | None = None


@dataclass(frozen=True, slots=True)
class HostMediaSource:
    """Host access retained beside, never inside, the common Library Snapshot."""

    path: HostPath
    kind: HostMediaFileKind
    size_bytes: int
    modified_ns: int
    acoustic_fingerprint: str | None = None
    content_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class HostMediaArtworkSource:
    """Validated Host source for one opaque artwork identity."""

    artwork_id: int
    kind: HostArtworkKind
    path: HostPath
    size_bytes: int
    modified_ns: int
    content_sha256: str

    def __post_init__(self) -> None:
        if self.artwork_id <= 0:
            raise ValueError("A Host artwork source requires a positive identity")
        if self.size_bytes <= 0 or self.modified_ns < 0:
            raise ValueError("A Host artwork source requires observed file facts")
        if len(self.content_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_sha256
        ):
            raise ValueError("A Host artwork source requires a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class HostMediaLibrary:
    """One completed in-memory Host Media Library source projection."""

    snapshot: LibrarySnapshot
    sources: tuple[HostMediaSource, ...]
    issues: tuple[HostMediaScanIssue, ...]
    cache: HostMediaCacheStats
    artwork_sources: tuple[HostMediaArtworkSource, ...] = ()
    approved_external_files: tuple[LocalHostFile, ...] = ()
    incomplete_playlist_ids: tuple[int, ...] = ()
    # Retained scan evidence for targeted refresh, separate from Library authority.
    cached_records: tuple[_CachedRecord, ...] = field(
        default=(), repr=False, compare=False
    )
    rechecked_track_paths: frozenset[str] = field(
        default=frozenset(), repr=False, compare=False
    )

    @property
    def audio_count(self) -> int:
        return sum(
            any(
                kind in (MediaType.AUDIO, MediaType.PODCAST, MediaType.AUDIOBOOK)
                for kind in track.media_types
            )
            for track in self.snapshot.tracks
        )

    @property
    def video_count(self) -> int:
        return sum(
            any(
                kind
                in (
                    MediaType.VIDEO,
                    MediaType.AUDIO_VIDEO,
                    MediaType.VIDEO_PODCAST,
                    MediaType.MUSIC_VIDEO,
                    MediaType.TV_SHOW,
                )
                for kind in track.media_types
            )
            for track in self.snapshot.tracks
        )

    @property
    def photo_count(self) -> int:
        return 0 if self.snapshot.photos is None else len(self.snapshot.photos.photos)

    @property
    def playlist_count(self) -> int:
        return len(self.snapshot.playlists)


class HostMediaArtworkLoader:
    """Lazily decode artwork from a completed, immutable Host scan."""

    def __init__(self) -> None:
        self._sources: dict[int, HostMediaArtworkSource] = {}
        self._external_files: dict[str, LocalHostFile] = {}

    def replace_library(self, library: HostMediaLibrary | None) -> None:
        """Replace the complete source generation used by later lazy reads."""

        self._sources = (
            {}
            if library is None
            else {source.artwork_id: source for source in library.artwork_sources}
        )
        self._external_files = (
            {}
            if library is None
            else {
                _path_identity(source.path.path): source
                for source in library.approved_external_files
            }
        )

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        """Decode one current embedded or folder cover outside the GUI thread."""

        source = self._sources.get(request.artwork_id)
        if source is None:
            return None
        external = self._external_files.get(_path_identity(source.path.path))
        try:
            observed = external or LocalHostFile.observe(source.path)
            if (observed.size_bytes, observed.modified_ns) != (
                source.size_bytes,
                source.modified_ns,
            ):
                raise HostMediaTreeChangedError(
                    "The Host artwork source changed after the Library scan. "
                    "Run Sync again."
                )
            if source.kind is HostArtworkKind.EMBEDDED:
                with observed.open_read() as stream:
                    payload = _embedded_artwork(stream)
            else:
                payload = observed.read_bytes(
                    max_bytes=_MAX_ARTWORK_BYTES, checkpoint=lambda: None
                )
        except (OSError, StorageError) as error:
            raise HostMediaTreeChangedError(
                "The Host artwork source changed or is no longer safe to read. "
                "Run Sync again."
            ) from error
        if (
            payload is None
            or hashlib.sha256(payload).hexdigest() != source.content_sha256
        ):
            raise HostMediaTreeChangedError(
                "The Host artwork source no longer matches the Library scan. "
                "Run Sync again."
            )
        with Image.open(BytesIO(payload)) as opened:
            oriented = ImageOps.exif_transpose(opened)
            oriented.thumbnail(
                (request.target_px, request.target_px),
                Image.Resampling.LANCZOS,
            )
            pixels = oriented.convert("RGB")
            width, height = pixels.size
            rgb888 = pixels.tobytes()
        return ArtworkImage(
            cache_key=(
                f"host/{source.content_sha256}/{request.target_px}/{width}x{height}"
            ),
            artwork_id=request.artwork_id,
            format_id=1,
            width=width,
            height=height,
            rgb888=rgb888,
        )


class HostMediaPhotoLoader:
    """Read display-sized pixels from one completed Host Media Library scan.

    The common Photo records remain descriptive. This source adapter retains the
    observed Host-file facts and refuses to read a file after those facts change,
    so a stale in-memory scan cannot silently present replacement content.
    """

    def __init__(self) -> None:
        self._sources: dict[int, HostMediaSource] = {}

    def replace_library(self, library: HostMediaLibrary | None) -> None:
        """Replace the complete source generation used by later lazy reads."""

        self._sources.clear()
        if library is None or library.snapshot.photos is None:
            return
        sources_by_path = {
            _path_identity(source.path.path): source
            for source in library.sources
            if source.kind is HostMediaFileKind.PHOTO
        }
        for photo in library.snapshot.photos.photos:
            representation = next(
                (
                    item
                    for item in photo.representations
                    if item.kind is PhotoRepresentationKind.FULL_RESOLUTION
                ),
                None,
            )
            if representation is None:
                continue
            source = sources_by_path.get(
                _path_identity(Path(representation.relative_path))
            )
            if source is not None:
                self._sources[photo.photo_id] = source

    def load_photo(self, request: PhotoRequest) -> PhotoImage | None:
        """Decode one current Host image outside the GUI thread."""

        if request.format_id not in (None, 0):
            return None
        source = self._sources.get(request.photo_id)
        if source is None:
            return None
        try:
            observed = LocalHostFile.observe(source.path)
            if (observed.size_bytes, observed.modified_ns) != (
                source.size_bytes,
                source.modified_ns,
            ):
                raise HostMediaTreeChangedError(
                    "The Host Photo changed after the Library scan. Run Sync again."
                )
            with observed.open_read() as stream, Image.open(stream) as opened:
                oriented = ImageOps.exif_transpose(opened)
                oriented.thumbnail(
                    (request.target_px, request.target_px),
                    Image.Resampling.LANCZOS,
                )
                pixels = oriented.convert("RGB")
                width, height = pixels.size
                rgb888 = pixels.tobytes()
        except (OSError, StorageError) as error:
            raise HostMediaTreeChangedError(
                "The Host Photo changed or is no longer safe to read. Run Sync again."
            ) from error
        cache_identity = hashlib.sha256(
            (
                f"{_path_identity(source.path.path)}\0{source.size_bytes}\0"
                f"{source.modified_ns}\0{width}x{height}"
            ).encode()
        ).hexdigest()
        return PhotoImage(
            cache_key=f"host/{cache_identity}",
            photo_id=request.photo_id,
            format_id=0,
            width=width,
            height=height,
            rgb888=rgb888,
        )


@dataclass(frozen=True, slots=True)
class _Observation:
    path: HostPath
    kind: HostMediaFileKind
    size_bytes: int
    modified_ns: int
    file: LocalHostFile | None = field(default=None, compare=False, repr=False)

    @property
    def state(self) -> tuple[str, str, int, int]:
        return (
            _path_identity(self.path.path),
            self.kind.value,
            self.size_bytes,
            self.modified_ns,
        )


@dataclass(frozen=True, slots=True)
class _ArtworkReference:
    kind: HostArtworkKind
    path: HostPath
    size_bytes: int
    modified_ns: int
    content_sha256: str

    @property
    def artwork_id(self) -> int:
        return _stable_content_identity(self.content_sha256, "artwork")

    @property
    def source(self) -> HostMediaArtworkSource:
        return HostMediaArtworkSource(
            self.artwork_id,
            self.kind,
            self.path,
            self.size_bytes,
            self.modified_ns,
            self.content_sha256,
        )

    @property
    def state(self) -> tuple[str, str, int, int, str]:
        return (
            self.kind.value,
            _path_identity(self.path.path),
            self.size_bytes,
            self.modified_ns,
            self.content_sha256,
        )


@dataclass(frozen=True, slots=True)
class _CachedFileRecord:
    path: HostPath
    kind: HostMediaFileKind
    size_bytes: int
    modified_ns: int
    warning: str = ""

    @property
    def source(self) -> HostMediaSource:
        return HostMediaSource(
            self.path,
            self.kind,
            self.size_bytes,
            self.modified_ns,
        )

    def matches(
        self,
        observation: _Observation,
        folder_artwork: _ArtworkReference | None = None,
    ) -> bool:
        del folder_artwork
        return (
            _path_identity(self.path.path) == _path_identity(observation.path.path)
            and self.kind is observation.kind
            and self.size_bytes == observation.size_bytes
            and self.modified_ns == observation.modified_ns
        )


@dataclass(frozen=True, slots=True)
class _CachedTrackRecord(_CachedFileRecord):
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    genre: str = ""
    year: int = 0
    track_number: int = 0
    total_tracks: int = 0
    disc_number: int = 0
    total_discs: int = 0
    length_ms: int = 0
    bitrate_kbps: int = 0
    sample_rate_hz: int = 0
    acoustic_fingerprint: str = ""
    artwork_kind: HostArtworkKind | None = None
    artwork_path: HostPath | None = None
    artwork_size_bytes: int = 0
    artwork_modified_ns: int = 0
    artwork_content_sha256: str = ""
    media_type: MediaType | None = None
    tag_values: tuple[MediaTag, ...] = ()

    @property
    def artwork(self) -> _ArtworkReference | None:
        if (
            self.artwork_kind is None
            or self.artwork_path is None
            or not self.artwork_content_sha256
        ):
            return None
        return _ArtworkReference(
            self.artwork_kind,
            self.artwork_path,
            self.artwork_size_bytes,
            self.artwork_modified_ns,
            self.artwork_content_sha256,
        )

    @property
    def source(self) -> HostMediaSource:
        return HostMediaSource(
            self.path,
            self.kind,
            self.size_bytes,
            self.modified_ns,
            self.acoustic_fingerprint or None,
        )

    def matches(
        self,
        observation: _Observation,
        folder_artwork: _ArtworkReference | None = None,
    ) -> bool:
        del folder_artwork
        return bool(self.acoustic_fingerprint) and _CachedFileRecord.matches(
            self, observation
        )


@dataclass(frozen=True, slots=True)
class _CachedPhotoRecord(_CachedFileRecord):
    width: int = 0
    height: int = 0
    content_sha256: str = ""

    @property
    def source(self) -> HostMediaSource:
        return HostMediaSource(
            self.path,
            self.kind,
            self.size_bytes,
            self.modified_ns,
            content_sha256=self.content_sha256 or None,
        )

    def matches(
        self,
        observation: _Observation,
        folder_artwork: _ArtworkReference | None = None,
    ) -> bool:
        del folder_artwork
        return bool(self.content_sha256) and _CachedFileRecord.matches(
            self,
            observation,
        )


@dataclass(frozen=True, slots=True)
class _CachedPlaylistRecord(_CachedFileRecord):
    title: str = ""
    references: tuple[HostPath, ...] = ()


type _CachedRecord = _CachedTrackRecord | _CachedPhotoRecord | _CachedPlaylistRecord


@dataclass(frozen=True, slots=True)
class PendingHostMediaScan:
    """A stable first pass awaiting decisions about external playlist files."""

    records: tuple[_CachedRecord, ...]
    external_references: tuple[PlaylistExternalReference, ...]
    issues: tuple[HostMediaScanIssue, ...]
    cache: HostMediaCacheStats
    cached_records: tuple[_CachedRecord, ...]
    folder_artwork: tuple[_ArtworkReference, ...] = ()
    folders: tuple[HostMediaFolder, ...] = ()
    observations: tuple[_Observation, ...] = ()
    enumeration_issues: tuple[HostMediaScanIssue, ...] = ()
    files: tuple[HostPath, ...] = ()


class _MutagenReader(Protocol):
    def File(
        self,
        filething: BinaryIO | BytesIO,
        options: object = None,
        easy: bool = False,
    ) -> Any: ...


class _TagReader(Protocol):
    """The dictionary-like read surface exposed by Mutagen tag containers."""

    def get(self, key: str) -> object: ...


class _FrameReader(Protocol):
    """The ID3 frame lookup surface used for embedded artwork."""

    def getall(self, key: str) -> list[object]: ...


class _ArtworkPicture(Protocol):
    """The common Mutagen picture fields used by the scanner."""

    data: bytes
    type: object


class _AcousticFingerprinter(Protocol):
    def fingerprint(
        self,
        source: HostPath,
        *,
        checkpoint: CancellationCheck,
    ) -> str: ...


ProgressCallback = Callable[[HostMediaScanProgress], None]
CancellationCheck = Callable[[], None]


class HostMediaScanner:
    """Scan, cache, and project Host media without planning or executing Sync."""

    def __init__(
        self,
        cache_file: AtomicHostFile | None = None,
        fingerprinter: _AcousticFingerprinter | None = None,
        *,
        max_workers: int | None = None,
    ) -> None:
        resolved_workers = (
            min(_MAX_INSPECTION_WORKERS, max(1, os.cpu_count() or 1))
            if max_workers is None
            else max_workers
        )
        if not 1 <= resolved_workers <= _MAX_INSPECTION_WORKERS:
            raise ValueError(
                "Host media inspection workers must be between 1 and "
                f"{_MAX_INSPECTION_WORKERS}"
            )
        self._cache_file = cache_file
        self._fingerprinter = fingerprinter or FpcalcFingerprinter()
        self._max_workers = resolved_workers

    def scan(
        self,
        folders: tuple[HostMediaFolder, ...],
        *,
        checkpoint: CancellationCheck,
        progress: ProgressCallback | None = None,
        files: tuple[HostPath, ...] = (),
    ) -> PendingHostMediaScan:
        """Read the selected scope and stop before external playlist decisions."""

        _emit(
            progress,
            HostMediaScanStage.DISCOVERING,
            0,
            0,
            "Finding selected media…"
            if files
            else "Finding media in the selected folders…",
        )
        checkpoint()
        before, enumeration_issues = _enumerate(
            folders, files=files, checkpoint=checkpoint
        )
        cached, cached_artwork = self._load_cache()
        before_artwork = _folder_artwork_catalog(
            before, cached=cached_artwork, checkpoint=checkpoint
        )
        issues = list(enumeration_issues)
        total = len(before)
        records, inspection_issues, reused, inspected = _inspect_selected_files(
            before,
            cached,
            self._fingerprinter,
            folder_artwork=before_artwork,
            max_workers=self._max_workers,
            checkpoint=checkpoint,
            progress=progress,
        )
        issues.extend(inspection_issues)

        checkpoint()
        _emit(
            progress,
            HostMediaScanStage.FINALIZING,
            total,
            total,
            "Checking for files that changed during the scan…",
            cache_hits=reused,
        )
        after, final_issues = _enumerate(folders, files=files, checkpoint=checkpoint)
        after_artwork = _folder_artwork_catalog(
            after, cached=before_artwork, checkpoint=checkpoint
        )
        if _folder_artwork_states(before_artwork) != _folder_artwork_states(
            after_artwork
        ):
            records = _reconcile_folder_artwork(records, after_artwork)
        if tuple(item.state for item in before) != tuple(item.state for item in after):
            issues.append(
                _scan_issue(
                    folders,
                    source_text(
                        "The Host Media Library changed while it was scanned; the available files were kept for review. Sync will recheck source files before writing to the iPod."
                    ),
                    files=files,
                )
            )
        if enumeration_issues != final_issues:
            issues.append(
                _scan_issue(
                    folders,
                    source_text(
                        "The availability of one or more selected folders changed while they were scanned; unavailable files were omitted. Sync will recheck source files before writing to the iPod."
                    ),
                    files=files,
                )
            )

        scanned_paths = {_path_identity(record.path.path) for record in records}
        external_targets: dict[str, tuple[HostPath, list[HostPath]]] = {}
        for record in records:
            checkpoint()
            if not isinstance(record, _CachedPlaylistRecord):
                continue
            for reference in record.references:
                checkpoint()
                target_identity = _path_identity(reference.path)
                if target_identity in scanned_paths:
                    continue
                playlists = external_targets.setdefault(
                    target_identity,
                    (reference, []),
                )[1]
                if record.path not in playlists:
                    playlists.append(record.path)

        external: list[PlaylistExternalReference] = []
        for target, playlists in external_targets.values():
            checkpoint()
            external.append(_review_reference(target, tuple(playlists)))

        merged_cache = dict(cached)
        merged_cache.update(
            (_path_identity(record.path.path), record) for record in records
        )
        scanned_artwork_directories = {
            _path_identity(observation.path.path.parent)
            for observation in after
            if observation.kind in (HostMediaFileKind.AUDIO, HostMediaFileKind.VIDEO)
        }
        merged_artwork = {
            identity: artwork
            for identity, artwork in cached_artwork.items()
            if identity not in scanned_artwork_directories
        }
        merged_artwork.update(after_artwork)
        self._store_cache(merged_cache.values(), merged_artwork.values())
        return PendingHostMediaScan(
            records=tuple(records),
            external_references=tuple(external),
            issues=tuple(issues),
            cache=HostMediaCacheStats(reused, inspected),
            cached_records=tuple(merged_cache.values()),
            folder_artwork=tuple(merged_artwork.values()),
            folders=folders,
            observations=before,
            enumeration_issues=enumeration_issues,
            files=files,
        )

    def complete(
        self,
        pending: PendingHostMediaScan,
        accepted: frozenset[HostPath],
        *,
        checkpoint: CancellationCheck,
        progress: ProgressCallback | None = None,
    ) -> HostMediaLibrary:
        """Scan accepted external files and publish one common Library Snapshot."""

        offered = {
            _path_identity(reference.target.path): reference
            for reference in pending.external_references
        }
        accepted_by_identity = {_path_identity(path.path): path for path in accepted}
        if not set(accepted_by_identity).issubset(offered):
            raise ValueError(
                "Accepted files must come from the pending playlist review"
            )
        if any(not offered[identity].available for identity in accepted_by_identity):
            raise ValueError("Unavailable Playlist targets cannot be accepted")

        cached = {
            _path_identity(record.path.path): record
            for record in pending.cached_records
        }
        records = list(pending.records)
        issues = list(pending.issues)
        reused = pending.cache.reused
        inspected = pending.cache.inspected
        total = len(accepted_by_identity)
        approved_external_files: list[LocalHostFile] = []
        for index, (identity, path) in enumerate(
            sorted(accepted_by_identity.items()),
            start=1,
        ):
            checkpoint()
            reviewed = offered[identity].observation
            if reviewed is None:
                raise ValueError("Accepted files require a Storage observation")
            path = reviewed.path
            try:
                reviewed.validate()
            except (OSError, StorageError) as error:
                issues.append(
                    HostMediaScanIssue(
                        path,
                        source_text(
                            "The accepted playlist file could not be read: {error}",
                            error=str(error),
                        ),
                    )
                )
                continue
            observation = _Observation(
                path,
                HostMediaFileKind.AUDIO
                if path.path.suffix.casefold() in _AUDIO_EXTENSIONS
                else HostMediaFileKind.VIDEO,
                reviewed.size_bytes,
                reviewed.modified_ns,
            )
            previous = cached.get(identity)
            if previous is not None and previous.matches(observation, None):
                record = previous
                reused += 1
                label = source_text(
                    "Reusing external file {index} of {total}…",
                    index=f"{index:,}",
                    total=f"{total:,}",
                )
            else:
                try:
                    # Decoders receive a private Storage capture, never an untrusted
                    # path that can be retargeted after the user's decision.
                    with reviewed.capture(checkpoint=checkpoint) as snapshot:
                        record = _inspect_file(
                            replace(
                                observation,
                                path=snapshot,
                                file=LocalHostFile.observe(snapshot),
                            ),
                            self._fingerprinter,
                            folder_artwork=None,
                            checkpoint=checkpoint,
                        )
                        assert isinstance(record, _CachedTrackRecord)
                        record = replace(
                            record,
                            path=path,
                            artwork_path=path
                            if record.artwork_path is not None
                            else None,
                        )
                except (OSError, StorageError) as error:
                    issues.append(
                        HostMediaScanIssue(
                            path,
                            source_text(
                                "The accepted Playlist file could not be safely read: {error}",
                                error=str(error),
                            ),
                        )
                    )
                    continue
                inspected += 1
                label = source_text(
                    "Reading external file {index} of {total}…",
                    index=f"{index:,}",
                    total=f"{total:,}",
                )
            try:
                reviewed.validate()
            except (OSError, StorageError) as error:
                issues.append(
                    HostMediaScanIssue(
                        path,
                        source_text(
                            "The accepted Playlist file changed while it was scanned and was omitted: {error}",
                            error=str(error),
                        ),
                    )
                )
                continue
            records.append(record)
            cached[identity] = record
            approved_external_files.append(reviewed)
            if record.warning:
                issues.append(HostMediaScanIssue(record.path, record.warning))
            _emit(
                progress,
                HostMediaScanStage.EXTERNAL,
                index,
                total,
                label,
                path=path,
                cache_hits=reused,
            )

        checkpoint()
        if pending.external_references:
            after, final_issues = _enumerate(
                pending.folders, files=pending.files, checkpoint=checkpoint
            )
            if tuple(item.state for item in after) != tuple(
                item.state for item in pending.observations
            ):
                issues.append(
                    _scan_issue(
                        pending.folders,
                        source_text(
                            "The selected media changed during Playlist review; the original scan remains available. Sync will recheck source files before writing to the iPod."
                        ),
                        files=pending.files,
                    )
                )
            if final_issues != pending.enumeration_issues:
                issues.append(
                    _scan_issue(
                        pending.folders,
                        source_text(
                            "The availability of one or more selected folders changed during Playlist review; unavailable files were omitted."
                        ),
                        files=pending.files,
                    )
                )
        _emit(
            progress,
            HostMediaScanStage.FINALIZING,
            total,
            total,
            "Building the Host Media Library…",
            cache_hits=reused,
        )
        unique_records = _unique_records(records)
        result = _build_library(
            unique_records,
            tuple(issues),
            HostMediaCacheStats(reused, inspected),
        )
        result = replace(result, approved_external_files=tuple(approved_external_files))
        self._store_cache(cached.values(), pending.folder_artwork)
        _emit(
            progress,
            HostMediaScanStage.COMPLETE,
            result.cache.total,
            result.cache.total,
            "Host Media Library scan complete.",
            cache_hits=result.cache.reused,
        )
        return result

    def refresh_tracks(
        self,
        library: HostMediaLibrary,
        paths: frozenset[HostPath],
        *,
        checkpoint: CancellationCheck,
    ) -> HostMediaLibrary:
        """Reread Host tags when current iPod details disagree with cached tags."""

        if not paths:
            return library
        records = {
            _path_identity(record.path.path): record
            for record in library.cached_records
        }
        cached_records, folder_artwork = self._load_cache()
        refreshed_paths: set[str] = set()
        for path in sorted(paths, key=lambda item: _path_identity(item.path)):
            checkpoint()
            identity = _path_identity(path.path)
            record = records.get(identity)
            if not isinstance(record, _CachedTrackRecord):
                raise HostMediaScanError("The Host Track is no longer in the scan.")
            folder = folder_artwork.get(_path_identity(path.path.parent))
            if folder is None:
                folder = next(
                    (
                        _ArtworkReference(
                            HostArtworkKind.FOLDER,
                            source.path,
                            source.size_bytes,
                            source.modified_ns,
                            source.content_sha256,
                        )
                        for source in library.artwork_sources
                        if source.kind is HostArtworkKind.FOLDER
                        and _path_identity(source.path.path.parent)
                        == _path_identity(path.path.parent)
                    ),
                    None,
                )
            observation = _Observation(
                record.path, record.kind, record.size_bytes, record.modified_ns
            )
            try:
                refreshed = _inspect_track(observation, folder, checkpoint=checkpoint)
            except (OSError, StorageError, ValueError, mutagen.MutagenError) as error:
                raise HostMediaScanError(
                    "The Host Track could not be reread. Run Sync again."
                ) from error
            if refreshed.warning:
                raise HostMediaScanError(
                    "The Host Track details could not be verified. Run Sync again."
                )
            records[identity] = replace(
                refreshed,
                acoustic_fingerprint=record.acoustic_fingerprint,
            )
            refreshed_paths.add(identity)
        updated = _build_library(
            tuple(records.values()),
            library.issues,
            HostMediaCacheStats(
                max(0, library.cache.reused - len(refreshed_paths)),
                library.cache.inspected + len(refreshed_paths),
            ),
        )
        updated = replace(
            updated,
            approved_external_files=library.approved_external_files,
            rechecked_track_paths=(
                library.rechecked_track_paths | frozenset(refreshed_paths)
            ),
        )
        cached_records.update(records)
        self._store_cache(cached_records.values(), folder_artwork.values())
        return updated

    def _load_cache(
        self,
    ) -> tuple[dict[str, _CachedRecord], dict[str, _ArtworkReference]]:
        if self._cache_file is None:
            return {}, {}
        try:
            payload = self._cache_file.read_bytes()
            if payload is None or len(payload) > _MAX_CACHE_BYTES:
                return {}, {}
            records, artwork = _decode_cache(payload)
            return (
                {_path_identity(record.path.path): record for record in records},
                {
                    _path_identity(reference.path.path.parent): reference
                    for reference in artwork
                },
            )
        except (OSError, StorageError, ValueError, UnicodeError):
            return {}, {}

    def _store_cache(
        self,
        records: Iterable[_CachedRecord],
        folder_artwork: Iterable[_ArtworkReference],
    ) -> None:
        if self._cache_file is None:
            return
        ordered = tuple(
            sorted(
                _unique_records(records),
                key=lambda record: _path_identity(record.path.path),
            )
        )
        if len(ordered) > _MAX_CACHE_ENTRIES:
            ordered = ordered[-_MAX_CACHE_ENTRIES:]
        ordered_artwork = tuple(
            sorted(
                folder_artwork,
                key=lambda reference: _path_identity(reference.path.path),
            )
        )
        if len(ordered_artwork) > _MAX_CACHE_ENTRIES:
            ordered_artwork = ordered_artwork[-_MAX_CACHE_ENTRIES:]
        try:
            self._cache_file.replace_bytes(_encode_cache(ordered, ordered_artwork))
        except (OSError, StorageError, HostMediaScanError):
            logger.warning(
                "Host Media Scan cache could not be updated",
                exc_info=True,
            )


def _emit(
    callback: ProgressCallback | None,
    stage: HostMediaScanStage,
    completed: int,
    total: int,
    message: str,
    *,
    path: HostPath | None = None,
    cache_hits: int = 0,
) -> None:
    if callback is not None:
        callback(
            HostMediaScanProgress(
                stage,
                completed,
                total,
                message,
                path,
                cache_hits,
            )
        )


def _scan_issue(
    folders: tuple[HostMediaFolder, ...],
    detail: str,
    *,
    files: tuple[HostPath, ...] = (),
) -> HostMediaScanIssue:
    """Describe scan drift without making a best-effort scan unusable."""

    # The folder dialog normally guarantees at least one folder. Keep the helper
    # total for callers that construct a scanner directly in tests or integrations.
    path = folders[0].path if folders else files[0] if files else HostPath(Path.cwd())
    return HostMediaScanIssue(path, detail)


def _enumerate(
    folders: tuple[HostMediaFolder, ...],
    *,
    checkpoint: CancellationCheck,
    files: tuple[HostPath, ...] = (),
) -> tuple[tuple[_Observation, ...], tuple[HostMediaScanIssue, ...]]:
    observations: dict[str, _Observation] = {}
    issues: list[HostMediaScanIssue] = []
    for folder in folders:
        checkpoint()
        try:
            _walk_folder(
                LocalHostDirectory.observe(folder.path),
                folder,
                observations,
                issues,
                checkpoint=checkpoint,
            )
        except (OSError, StorageError) as error:
            issues.append(
                HostMediaScanIssue(
                    folder.path,
                    source_text(
                        "The selected folder could not be fully scanned: {error}",
                        error=str(error),
                    ),
                )
            )
    for path in files:
        checkpoint()
        kind = classify_host_media_file(Path(path.path))
        if kind is None:
            issues.append(
                HostMediaScanIssue(path, source_text("Unsupported media file."))
            )
            continue
        try:
            file = LocalHostFile.observe(path)
        except (OSError, StorageError) as error:
            issues.append(
                HostMediaScanIssue(
                    path,
                    source_text(
                        "Unavailable or unsafe file: {error}", error=str(error)
                    ),
                )
            )
            continue
        observations[_path_identity(path.path)] = _Observation(
            path, kind, file.size_bytes, file.modified_ns, file=file
        )
    return (
        tuple(sorted(observations.values(), key=lambda item: item.state)),
        tuple(issues),
    )


def _walk_folder(
    directory: LocalHostDirectory,
    folder: HostMediaFolder,
    observations: dict[str, _Observation],
    issues: list[HostMediaScanIssue],
    *,
    checkpoint: CancellationCheck,
) -> None:
    checkpoint()

    def report(path: HostPath, error: OSError | StorageError) -> None:
        issues.append(
            HostMediaScanIssue(
                path,
                source_text(
                    "Some folder contents were unavailable; scanning continued: {error}",
                    error=str(error),
                ),
            )
        )

    try:
        entries = directory.list_entries(checkpoint=checkpoint, on_issue=report)
    except (OSError, StorageError) as error:
        report(directory.path, error)
        return
    for entry in sorted(
        entries, key=lambda item: os.path.normcase(item.path.path.name)
    ):
        checkpoint()
        if entry.kind is HostEntryKind.DIRECTORY:
            if folder.recurse and entry.directory is not None:
                _walk_folder(
                    entry.directory,
                    folder,
                    observations,
                    issues,
                    checkpoint=checkpoint,
                )
            continue
        if entry.kind is not HostEntryKind.FILE:
            continue
        path = Path(entry.path.path)
        kind = _classify(path, folder.media_types)
        if kind is None:
            continue
        observations[_path_identity(path)] = _Observation(
            entry.path,
            kind,
            entry.size_bytes,
            entry.modified_ns,
            file=entry.file,
        )


def _classify(
    path: Path,
    allowed: frozenset[HostMediaType] | None = None,
) -> HostMediaFileKind | None:
    extension = path.suffix.casefold()
    choices = (
        (HostMediaType.AUDIO, HostMediaFileKind.AUDIO, _AUDIO_EXTENSIONS),
        (HostMediaType.VIDEO, HostMediaFileKind.VIDEO, _VIDEO_EXTENSIONS),
        (HostMediaType.PHOTOS, HostMediaFileKind.PHOTO, _PHOTO_EXTENSIONS),
        (HostMediaType.PLAYLISTS, HostMediaFileKind.PLAYLIST, PLAYLIST_EXTENSIONS),
    )
    for media_type, kind, extensions in choices:
        if extension in extensions and (allowed is None or media_type in allowed):
            return kind
    return None


def classify_host_media_file(path: Path) -> HostMediaFileKind | None:
    """Classify a selected filename using the scanner's supported extensions."""

    return _classify(path)


def _review_reference(
    path: HostPath, playlists: tuple[HostPath, ...]
) -> PlaylistExternalReference:
    if path.path.suffix.casefold() not in _AUDIO_EXTENSIONS | _VIDEO_EXTENSIONS:
        return PlaylistExternalReference(
            path,
            playlists,
            False,
            "Only supported audio and video files can be included; nested Playlists are not followed.",
        )
    try:
        observation = LocalHostFile.observe(path)
    except (OSError, StorageError) as error:
        return PlaylistExternalReference(
            path,
            playlists,
            False,
            source_text("Unavailable or unsafe file: {error}", error=str(error)),
        )
    return PlaylistExternalReference(path, playlists, True, observation=observation)


def _folder_artwork_catalog(
    observations: tuple[_Observation, ...],
    *,
    cached: dict[str, _ArtworkReference],
    checkpoint: CancellationCheck,
) -> dict[str, _ArtworkReference]:
    catalog: dict[str, _ArtworkReference] = {}
    directories = {
        _path_identity(observation.path.path.parent): observation
        for observation in observations
        if observation.kind in (HostMediaFileKind.AUDIO, HostMediaFileKind.VIDEO)
    }
    for identity, observation in directories.items():
        checkpoint()
        try:
            artwork = _folder_artwork_for(
                observation,
                cached=cached.get(identity),
                checkpoint=checkpoint,
            )
        except (OSError, StorageError):
            # Folder artwork is optional presentation data. Cloud placeholders,
            # evictions, and permission churn must not invalidate media discovery.
            artwork = None
        if artwork is not None:
            catalog[identity] = artwork
    return catalog


def _folder_artwork_for(
    observation: _Observation,
    *,
    cached: _ArtworkReference | None = None,
    checkpoint: CancellationCheck,
) -> _ArtworkReference | None:
    if observation.kind not in (HostMediaFileKind.AUDIO, HostMediaFileKind.VIDEO):
        return None
    directory = observation.path.path.parent
    try:
        entries = LocalHostDirectory.observe(HostPath(directory)).list_entries(
            checkpoint=checkpoint
        )
        files = sorted(
            (entry for entry in entries if entry.kind is HostEntryKind.FILE),
            key=lambda entry: (entry.path.path.name.casefold(), entry.path.path.name),
        )
    except (OSError, StorageError):
        return None
    by_name = {entry.path.path.name.casefold(): entry for entry in files}
    for stem in _FOLDER_ARTWORK_STEMS:
        for extension in _FOLDER_ARTWORK_EXTENSIONS:
            checkpoint()
            entry = by_name.get(f"{stem}{extension}".casefold())
            if entry is None or entry.file is None:
                continue
            if not 0 < entry.size_bytes <= _MAX_ARTWORK_BYTES:
                continue
            if (
                cached is not None
                and _path_identity(cached.path.path) == _path_identity(entry.path.path)
                and cached.size_bytes == entry.size_bytes
                and cached.modified_ns == entry.modified_ns
            ):
                return cached
            digest = hashlib.sha256()
            try:
                with entry.file.open_read(checkpoint=checkpoint) as source:
                    while chunk := source.read(1024 * 1024):
                        checkpoint()
                        digest.update(chunk)
                    source.seek(0)
                    with Image.open(source) as image:
                        image.verify()
            except StorageError:
                # A folder cover is a convenience, not part of the Host media
                # catalog. Treat transient cloud-storage failures as no cover.
                return None
            except (OSError, SyntaxError, ValueError):
                continue
            return _ArtworkReference(
                HostArtworkKind.FOLDER,
                entry.path,
                entry.size_bytes,
                entry.modified_ns,
                digest.hexdigest(),
            )
    return None


def _folder_artwork_states(
    catalog: dict[str, _ArtworkReference],
) -> tuple[tuple[str, tuple[str, str, int, int, str]], ...]:
    return tuple(
        sorted((identity, artwork.state) for identity, artwork in catalog.items())
    )


def _reconcile_folder_artwork(
    records: list[_CachedRecord],
    folder_artwork: dict[str, _ArtworkReference],
) -> list[_CachedRecord]:
    """Keep optional folder covers aligned with the final best-effort view."""

    reconciled: list[_CachedRecord] = []
    for record in records:
        if not isinstance(record, _CachedTrackRecord):
            reconciled.append(record)
            continue
        current = folder_artwork.get(_path_identity(record.path.path.parent))
        reconciled.append(_track_with_folder_artwork(record, current))
    return reconciled


def _track_with_folder_artwork(
    record: _CachedTrackRecord,
    current: _ArtworkReference | None,
) -> _CachedTrackRecord:
    artwork = record.artwork
    if artwork is not None and artwork.kind is HostArtworkKind.EMBEDDED:
        return record
    return replace(
        record,
        artwork_kind=None if current is None else current.kind,
        artwork_path=None if current is None else current.path,
        artwork_size_bytes=0 if current is None else current.size_bytes,
        artwork_modified_ns=0 if current is None else current.modified_ns,
        artwork_content_sha256="" if current is None else current.content_sha256,
    )


def _inspect_selected_files(
    observations: tuple[_Observation, ...],
    cached: dict[str, _CachedRecord],
    fingerprinter: _AcousticFingerprinter,
    *,
    folder_artwork: dict[str, _ArtworkReference],
    max_workers: int,
    checkpoint: CancellationCheck,
    progress: ProgressCallback | None,
) -> tuple[
    list[_CachedRecord],
    list[HostMediaScanIssue],
    int,
    int,
]:
    """Inspect cache misses concurrently while publishing ordered progress."""

    records: list[_CachedRecord] = []
    issues: list[HostMediaScanIssue] = []
    reused = 0
    inspected = 0
    total = len(observations)
    batch_size = max_workers * 4
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="host-media-inspection",
    ) as executor:
        for batch_start in range(0, total, batch_size):
            batch = observations[batch_start : batch_start + batch_size]
            ready: dict[int, _CachedRecord] = {}
            pending: dict[int, Future[_CachedRecord]] = {}
            for offset, observation in enumerate(batch):
                checkpoint()
                index = batch_start + offset
                previous = cached.get(_path_identity(observation.path.path))
                fallback = folder_artwork.get(
                    _path_identity(observation.path.path.parent)
                )
                if previous is not None and previous.matches(observation, fallback):
                    ready[index] = (
                        _track_with_folder_artwork(previous, fallback)
                        if isinstance(previous, _CachedTrackRecord)
                        else previous
                    )
                    continue
                pending[index] = executor.submit(
                    _inspect_file,
                    observation,
                    fingerprinter,
                    folder_artwork=fallback,
                    checkpoint=checkpoint,
                )

            _emit(
                progress,
                HostMediaScanStage.READING,
                len(records),
                total,
                "Reading metadata and calculating matching fingerprints…",
                path=batch[0].path,
                cache_hits=reused,
            )
            # Publish finished work immediately, even when an earlier file is slow.
            by_future = {future: index for index, future in pending.items()}
            for index in chain(ready, (by_future[f] for f in as_completed(by_future))):
                checkpoint()
                observation = observations[index]
                future = pending.get(index)
                if future is None:
                    record = ready[index]
                    reused += 1
                    label = source_text(
                        "Reusing unchanged file {index} of {total}…",
                        index=f"{len(records) + 1:,}",
                        total=f"{total:,}",
                    )
                else:
                    record = future.result()
                    inspected += 1
                    label = source_text(
                        "Read file {index} of {total}…",
                        index=f"{len(records) + 1:,}",
                        total=f"{total:,}",
                    )
                records.append(record)
                if record.warning:
                    issues.append(HostMediaScanIssue(record.path, record.warning))
                _emit(
                    progress,
                    HostMediaScanStage.READING,
                    len(records),
                    total,
                    label,
                    path=observation.path,
                    cache_hits=reused,
                )
    records.sort(key=lambda record: _path_identity(record.path.path))
    issues.sort(key=lambda issue: _path_identity(issue.path.path))
    return records, issues, reused, inspected


def _inspect_file(
    observation: _Observation,
    fingerprinter: _AcousticFingerprinter,
    *,
    folder_artwork: _ArtworkReference | None = None,
    checkpoint: CancellationCheck,
) -> _CachedRecord:
    if observation.kind in (
        HostMediaFileKind.AUDIO,
        HostMediaFileKind.VIDEO,
    ):
        try:
            record = _inspect_track(observation, folder_artwork, checkpoint=checkpoint)
        except (
            HostMediaTreeChangedError,
            OSError,
            StorageError,
            ValueError,
            mutagen.MutagenError,
        ) as error:
            fallback = _fallback_record(
                observation,
                "Metadata could not be read; the file was retained with basic "
                f"facts: {error}",
                folder_artwork=folder_artwork,
            )
            assert isinstance(fallback, _CachedTrackRecord)
            record = fallback
        try:
            acoustic_fingerprint = fingerprinter.fingerprint(
                observation.path,
                checkpoint=checkpoint,
            )
        except FpcalcError as error:
            warning = _combine_warnings(
                record.warning,
                f"Acoustic fingerprint unavailable; this file can still be selected for Add: {error}",
            )
            return replace(record, warning=warning)
        return replace(record, acoustic_fingerprint=acoustic_fingerprint)
    try:
        if observation.kind is HostMediaFileKind.PHOTO:
            return _inspect_photo(observation, checkpoint=checkpoint)
        return _inspect_playlist(observation, checkpoint=checkpoint)
    except (
        HostMediaTreeChangedError,
        OSError,
        ValueError,
        StorageError,
        mutagen.MutagenError,
    ) as error:
        return _fallback_record(
            observation,
            f"Metadata could not be read; the file was retained with basic facts: {error}",
        )


def _combine_warnings(*values: str) -> str:
    return " ".join(value for value in values if value)


def _inspect_track(
    observation: _Observation,
    folder_artwork: _ArtworkReference | None,
    *,
    checkpoint: CancellationCheck,
) -> _CachedTrackRecord:
    try:
        with _observed_file(observation).open_read(checkpoint=checkpoint) as stream:
            record = _read_track(observation, folder_artwork, stream)
    except mutagen.MutagenError as error:
        fallback = _fallback_record(
            observation, str(error), folder_artwork=folder_artwork
        )
        assert isinstance(fallback, _CachedTrackRecord)
        record = fallback
    if (
        record.tag_values
        or record.length_ms
        or observation.kind is HostMediaFileKind.AUDIO
    ):
        return record
    # Containers without native tag support, including Matroska and AVI, use
    # the existing bounded, single-file FFprobe adapter instead.
    try:
        observed = MediaInspector().inspect(observation.path, checkpoint=checkpoint)
    except MediaInspectionError as error:
        return replace(
            record,
            warning=_combine_warnings(
                record.warning,
                f"Metadata inspection unavailable; basic file facts were retained: {error}",
            ),
        )
    values = inspection_tag_values(observed)
    tagged = apply_tag_values(
        Track(0, observation.path.path.stem, "", "", 0),
        values,
        suffix=observation.path.path.suffix,
        video=bool(observed.video_streams),
    )
    streams = observed.audio_streams or observed.video_streams
    preferred = next(
        (stream for stream in streams if stream.default), next(iter(streams), None)
    )
    duration = (
        preferred.duration_seconds if preferred else None
    ) or observed.duration_seconds
    bitrate = (
        (preferred.bitrate_bps if preferred else None) or observed.bitrate_bps or 0
    )
    return replace(
        record,
        warning="",
        tag_values=values,
        media_type=tagged.media_types[0],
        title=tagged.title,
        artist=tagged.artist,
        album=tagged.album,
        album_artist=tagged.album_artist,
        genre=tagged.genre,
        year=tagged.year,
        track_number=tagged.track_number,
        total_tracks=tagged.metadata.total_tracks,
        disc_number=tagged.metadata.disc_number,
        total_discs=tagged.metadata.total_discs,
        length_ms=round(duration * 1000) if duration is not None else 0,
        bitrate_kbps=round(bitrate / 1000),
        sample_rate_hz=(preferred.sample_rate_hz or 0) if preferred else 0,
    )


def _observed_file(observation: _Observation) -> LocalHostFile:
    if observation.file is not None:
        return observation.file
    source = LocalHostFile.observe(observation.path)
    if (source.size_bytes, source.modified_ns) != (
        observation.size_bytes,
        observation.modified_ns,
    ):
        raise HostMediaTreeChangedError(
            "A Host file changed before inspection. Run Sync again."
        )
    return source


def _read_track(
    observation: _Observation,
    folder_artwork: _ArtworkReference | None,
    stream: BinaryIO,
) -> _CachedTrackRecord:
    parsed = cast("_MutagenReader", mutagen).File(stream, easy=False)
    tag_values = read_tag_values(getattr(parsed, "tags", None))
    tagged = apply_tag_values(
        Track(0, observation.path.path.stem, "", "", 0),
        tag_values,
        suffix=observation.path.path.suffix,
        video=observation.kind is HostMediaFileKind.VIDEO,
    )
    info = getattr(parsed, "info", None)
    length = _finite_number(getattr(info, "length", 0.0))
    bitrate = _nonnegative_int(getattr(info, "bitrate", 0))
    sample_rate = _nonnegative_int(getattr(info, "sample_rate", 0))
    artwork_payload = _parsed_embedded_artwork(parsed)
    artwork = (
        _ArtworkReference(
            HostArtworkKind.EMBEDDED,
            observation.path,
            observation.size_bytes,
            observation.modified_ns,
            hashlib.sha256(artwork_payload).hexdigest(),
        )
        if artwork_payload is not None
        else folder_artwork
    )
    return _CachedTrackRecord(
        path=observation.path,
        kind=observation.kind,
        size_bytes=observation.size_bytes,
        modified_ns=observation.modified_ns,
        title=tagged.title,
        artist=tagged.artist,
        album=tagged.album,
        album_artist=tagged.album_artist,
        genre=tagged.genre,
        year=tagged.year,
        track_number=tagged.track_number,
        total_tracks=tagged.metadata.total_tracks,
        disc_number=tagged.metadata.disc_number,
        total_discs=tagged.metadata.total_discs,
        length_ms=max(0, round(length * 1000)),
        bitrate_kbps=max(0, round(bitrate / 1000)),
        sample_rate_hz=sample_rate,
        media_type=tagged.media_types[0],
        tag_values=tag_values,
        artwork_kind=None if artwork is None else artwork.kind,
        artwork_path=None if artwork is None else artwork.path,
        artwork_size_bytes=0 if artwork is None else artwork.size_bytes,
        artwork_modified_ns=0 if artwork is None else artwork.modified_ns,
        artwork_content_sha256=("" if artwork is None else artwork.content_sha256),
    )


def _embedded_artwork(stream: BinaryIO) -> bytes | None:
    stream.seek(0)
    parsed = cast("_MutagenReader", mutagen).File(stream, easy=False)
    return _parsed_embedded_artwork(parsed)


def embedded_artwork_from_bytes(data: bytes) -> bytes | None:
    """Read an embedded image from captured bytes without filesystem access."""

    return _parsed_embedded_artwork(
        cast("_MutagenReader", mutagen).File(BytesIO(data), easy=False)
    )


def embedded_artwork_from_stream(stream: BinaryIO) -> bytes | None:
    """Read bounded image payloads without loading the enclosing media file."""
    return _embedded_artwork(stream)


def _parsed_embedded_artwork(parsed: Any) -> bytes | None:
    if parsed is None:
        return None
    candidates: list[tuple[bool, bytes]] = []
    pictures = getattr(parsed, "pictures", ())
    if isinstance(pictures, list):
        for picture in cast("list[object]", pictures):
            payload = getattr(picture, "data", None)
            if isinstance(payload, bytes) and 0 < len(payload) <= _MAX_ARTWORK_BYTES:
                candidates.append((getattr(picture, "type", 0) == 3, payload))

    tags = getattr(parsed, "tags", None)
    if tags is not None and hasattr(tags, "getall"):
        frame_reader = cast("_FrameReader", tags)
        for picture in frame_reader.getall("APIC"):
            payload = getattr(picture, "data", None)
            if isinstance(payload, bytes) and 0 < len(payload) <= _MAX_ARTWORK_BYTES:
                candidates.append((getattr(picture, "type", 0) == 3, payload))

    if tags is not None and hasattr(tags, "get"):
        tag_reader = cast("_TagReader", tags)
        covers = tag_reader.get("covr")
        if isinstance(covers, list):
            candidates.extend(
                (True, bytes(value))
                for value in cast("list[object]", covers)
                if isinstance(value, bytes | bytearray)
                and 0 < len(value) <= _MAX_ARTWORK_BYTES
            )
        for name in ("metadata_block_picture", "coverart"):
            values = tag_reader.get(name)
            if isinstance(values, str):
                artwork_values: list[object] = [values]
            elif isinstance(values, list):
                artwork_values = cast("list[object]", values)
            else:
                continue
            for value in artwork_values:
                if not isinstance(value, str):
                    continue
                try:
                    decoded = base64.b64decode(value, validate=True)
                    payload = (
                        cast(
                            "_ArtworkPicture",
                            Picture(decoded),  # type: ignore[no-untyped-call]
                        ).data
                        if name == "metadata_block_picture"
                        else decoded
                    )
                except (TypeError, ValueError, mutagen.MutagenError):
                    continue
                if 0 < len(payload) <= _MAX_ARTWORK_BYTES:
                    candidates.append((True, payload))
        for name in ("Cover Art (Front)", "Cover Art (Back)"):
            value = tag_reader.get(name)
            payload = getattr(value, "value", value)
            if isinstance(payload, bytes) and payload:
                separator = payload.find(b"\0")
                if separator >= 0:
                    payload = payload[separator + 1 :]
                if 0 < len(payload) <= _MAX_ARTWORK_BYTES:
                    candidates.append((name.endswith("(Front)"), payload))

    ordered = (
        *(payload for is_front, payload in candidates if is_front),
        *(payload for is_front, payload in candidates if not is_front),
    )
    for payload in ordered:
        try:
            with Image.open(BytesIO(payload)) as image:
                image.verify()
        except (OSError, SyntaxError, ValueError):
            continue
        return payload
    return None


def _inspect_photo(
    observation: _Observation,
    *,
    checkpoint: CancellationCheck,
) -> _CachedPhotoRecord:
    digest = hashlib.sha256()
    with _observed_file(observation).open_read(checkpoint=checkpoint) as source:
        while chunk := source.read(1024 * 1024):
            checkpoint()
            digest.update(chunk)
        source.seek(0)
        with Image.open(source) as image:
            width, height = image.size
    return _CachedPhotoRecord(
        path=observation.path,
        kind=observation.kind,
        size_bytes=observation.size_bytes,
        modified_ns=observation.modified_ns,
        width=max(0, int(width)),
        height=max(0, int(height)),
        content_sha256=digest.hexdigest(),
    )


def _inspect_playlist(
    observation: _Observation, *, checkpoint: CancellationCheck
) -> _CachedPlaylistRecord:
    source = _observed_file(observation)
    payload = source.read_bytes(max_bytes=MAX_PLAYLIST_BYTES, checkpoint=checkpoint)
    parsed = parse_host_playlist(payload, observation.path, checkpoint=checkpoint)
    return _CachedPlaylistRecord(
        path=observation.path,
        kind=observation.kind,
        size_bytes=observation.size_bytes,
        modified_ns=observation.modified_ns,
        title=parsed.title,
        references=parsed.references,
        warning=parsed.warning,
    )


def _fallback_record(
    observation: _Observation,
    warning: str,
    *,
    folder_artwork: _ArtworkReference | None = None,
) -> _CachedRecord:
    if observation.kind in (HostMediaFileKind.AUDIO, HostMediaFileKind.VIDEO):
        return _CachedTrackRecord(
            path=observation.path,
            kind=observation.kind,
            size_bytes=observation.size_bytes,
            modified_ns=observation.modified_ns,
            warning=warning,
            title=observation.path.path.stem,
            artwork_kind=(None if folder_artwork is None else folder_artwork.kind),
            artwork_path=(None if folder_artwork is None else folder_artwork.path),
            artwork_size_bytes=(
                0 if folder_artwork is None else folder_artwork.size_bytes
            ),
            artwork_modified_ns=(
                0 if folder_artwork is None else folder_artwork.modified_ns
            ),
            artwork_content_sha256=(
                "" if folder_artwork is None else folder_artwork.content_sha256
            ),
        )
    if observation.kind is HostMediaFileKind.PHOTO:
        return _CachedPhotoRecord(
            path=observation.path,
            kind=observation.kind,
            size_bytes=observation.size_bytes,
            modified_ns=observation.modified_ns,
            warning=warning,
        )
    return _CachedPlaylistRecord(
        path=observation.path,
        kind=observation.kind,
        size_bytes=observation.size_bytes,
        modified_ns=observation.modified_ns,
        warning=warning,
        title=observation.path.path.stem,
    )


def _build_library(
    records: tuple[_CachedRecord, ...],
    issues: tuple[HostMediaScanIssue, ...],
    cache: HostMediaCacheStats,
) -> HostMediaLibrary:
    tracks: list[Track] = []
    photos: list[Photo] = []
    artwork_sources: dict[int, HostMediaArtworkSource] = {}
    track_by_path: dict[str, int] = {}
    for record in records:
        if isinstance(record, _CachedTrackRecord):
            identity = _stable_identity(record.path.path, "track")
            artwork = record.artwork
            artwork_id = 0 if artwork is None else artwork.artwork_id
            if artwork is not None:
                artwork_sources.setdefault(artwork_id, artwork.source)
            track_by_path[_path_identity(record.path.path)] = identity
            tracks.append(
                apply_tag_values(
                    Track(
                        track_id=identity,
                        title=record.title or record.path.path.stem,
                        artist=record.artist,
                        album=record.album,
                        length_ms=record.length_ms,
                        genre=record.genre,
                        year=record.year,
                        track_number=record.track_number,
                        size_bytes=record.size_bytes,
                        bitrate_kbps=record.bitrate_kbps,
                        artwork_id=artwork_id,
                        media_types=(
                            record.media_type
                            or classify_content_type(
                                record.path.path.suffix,
                                {},
                                video=record.kind is HostMediaFileKind.VIDEO,
                            ),
                        ),
                        album_artist=record.album_artist,
                        metadata=TrackMetadata(
                            file_format=record.path.path.suffix.casefold().lstrip("."),
                            last_modified=record.modified_ns // 1_000_000_000,
                            total_tracks=record.total_tracks,
                            sample_rate_hz=record.sample_rate_hz,
                            disc_number=record.disc_number,
                            total_discs=record.total_discs,
                            location=os.fspath(record.path),
                        ),
                    ),
                    record.tag_values,
                    suffix=record.path.path.suffix,
                    video=record.media_type
                    in (
                        MediaType.VIDEO,
                        MediaType.AUDIO_VIDEO,
                        MediaType.VIDEO_PODCAST,
                        MediaType.MUSIC_VIDEO,
                        MediaType.TV_SHOW,
                    )
                    or (
                        record.media_type is None
                        and record.kind is HostMediaFileKind.VIDEO
                    ),
                )
            )
        elif isinstance(record, _CachedPhotoRecord):
            photos.append(
                Photo(
                    photo_id=_stable_identity(record.path.path, "photo"),
                    source_size_bytes=record.size_bytes,
                    representations=(
                        PhotoRepresentation(
                            kind=PhotoRepresentationKind.FULL_RESOLUTION,
                            format_id=0,
                            relative_path=os.fspath(record.path),
                            offset=0,
                            size_bytes=record.size_bytes,
                            width=record.width,
                            height=record.height,
                        ),
                    ),
                )
            )

    playlists: list[Playlist] = []
    incomplete_playlists: set[int] = set()
    for record in records:
        if not isinstance(record, _CachedPlaylistRecord):
            continue
        playlist_id = _stable_identity(record.path.path, "playlist")
        if record.warning:
            incomplete_playlists.add(playlist_id)
        playlist_entries: list[PlaylistEntry] = []
        for source_position, reference in enumerate(record.references):
            track_id = track_by_path.get(_path_identity(reference.path))
            if track_id is None:
                incomplete_playlists.add(playlist_id)
                continue
            playlist_entries.append(
                PlaylistEntry(
                    entry_id=_entry_identity(
                        record.path.path,
                        source_position,
                        reference.path,
                    ),
                    track_id=track_id,
                    position=len(playlist_entries),
                )
            )
        entries = tuple(playlist_entries)
        playlists.append(
            Playlist(
                playlist_id=playlist_id,
                name=record.title or record.path.path.stem,
                kind=PlaylistKind.PLAYLIST,
                entries=entries,
                sort_order=PlaylistSortOrder.MANUAL,
            )
        )

    snapshot = LibrarySnapshot(
        tracks=tuple(tracks),
        playlists=tuple(playlists),
        photos=PhotoLibrary(photos=tuple(photos)) if photos else None,
    )
    return HostMediaLibrary(
        snapshot=snapshot,
        sources=tuple(record.source for record in records),
        issues=issues,
        cache=cache,
        artwork_sources=tuple(artwork_sources.values()),
        incomplete_playlist_ids=tuple(sorted(incomplete_playlists)),
        cached_records=records,
    )


def _encode_cache(
    records: tuple[_CachedRecord, ...],
    folder_artwork: tuple[_ArtworkReference, ...],
) -> bytes:
    entries = [_record_document(record) for record in records]
    catalog = _canonical_json(entries)
    artwork_entries = [
        {
            "path": os.fspath(reference.path),
            "size_bytes": reference.size_bytes,
            "modified_ns": reference.modified_ns,
            "content_sha256": reference.content_sha256,
        }
        for reference in folder_artwork
    ]
    document = {
        "version": _CACHE_VERSION,
        "entries": entries,
        "catalog_sha256": hashlib.sha256(catalog).hexdigest(),
        "folder_artwork": artwork_entries,
        "folder_artwork_sha256": hashlib.sha256(
            _canonical_json(artwork_entries)
        ).hexdigest(),
    }
    encoded = _canonical_json(document)
    if len(encoded) > _MAX_CACHE_BYTES:
        raise HostMediaScanError("The Host Media Library cache exceeds 64 MiB")
    return encoded


def _decode_cache(
    payload: bytes,
) -> tuple[tuple[_CachedRecord, ...], tuple[_ArtworkReference, ...]]:
    raw: object = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs)
    document = _object(raw, "cache")
    version = _integer(document.get("version"), "version")
    if version == 9:
        expected = {"version", "entries", "catalog_sha256"}
    elif version == _CACHE_VERSION:
        expected = {
            "version",
            "entries",
            "catalog_sha256",
            "folder_artwork",
            "folder_artwork_sha256",
        }
    else:
        raise ValueError("Host media cache version is unsupported")
    if set(document) != expected:
        raise ValueError("Host media cache fields are invalid")
    entries = _array(document["entries"], "entries")
    if len(entries) > _MAX_CACHE_ENTRIES:
        raise ValueError("Host media cache contains too many entries")
    digest = _text(document["catalog_sha256"], "catalog_sha256")
    if (
        len(digest) != 64
        or hashlib.sha256(_canonical_json(entries)).hexdigest() != digest
    ):
        raise ValueError("Host media cache checksum does not match")
    records = tuple(_record_from_document(entry) for entry in entries)
    if version == 9:
        return records, _folder_artwork_from_records(records)
    artwork_entries = _array(document["folder_artwork"], "folder_artwork")
    if len(artwork_entries) > _MAX_CACHE_ENTRIES:
        raise ValueError("Host media cache contains too many folder covers")
    artwork_digest = _text(document["folder_artwork_sha256"], "folder_artwork_sha256")
    if (
        len(artwork_digest) != 64
        or hashlib.sha256(_canonical_json(artwork_entries)).hexdigest()
        != artwork_digest
    ):
        raise ValueError("Host media folder artwork checksum does not match")
    artwork: list[_ArtworkReference] = []
    for entry in artwork_entries:
        row = _object(entry, "folder artwork")
        if set(row) != {
            "path",
            "size_bytes",
            "modified_ns",
            "content_sha256",
        }:
            raise ValueError("Host media folder artwork fields are invalid")
        path = Path(_text(row["path"], "path"))
        if not path.is_absolute():
            raise ValueError("Host media folder artwork paths must be absolute")
        size_bytes = _integer(row["size_bytes"], "size_bytes")
        modified_ns = _integer(row["modified_ns"], "modified_ns")
        if not 0 < size_bytes <= _MAX_ARTWORK_BYTES or modified_ns < 0:
            raise ValueError("Host media folder artwork file facts are invalid")
        artwork.append(
            _ArtworkReference(
                HostArtworkKind.FOLDER,
                HostPath(path),
                size_bytes,
                modified_ns,
                _sha256(row["content_sha256"], "content_sha256"),
            )
        )
    return records, tuple(artwork)


def _folder_artwork_from_records(
    records: tuple[_CachedRecord, ...],
) -> tuple[_ArtworkReference, ...]:
    """Recover v9 folder-cover facts embedded in cached Track records."""

    references: dict[str, _ArtworkReference] = {}
    conflicts: set[str] = set()
    for record in records:
        if not isinstance(record, _CachedTrackRecord):
            continue
        artwork = record.artwork
        if artwork is None or artwork.kind is not HostArtworkKind.FOLDER:
            continue
        identity = _path_identity(record.path.path.parent)
        previous = references.get(identity)
        if previous is not None and previous != artwork:
            conflicts.add(identity)
        elif identity not in conflicts:
            references[identity] = artwork
    return tuple(
        reference
        for identity, reference in references.items()
        if identity not in conflicts
    )


def _record_document(record: _CachedRecord) -> dict[str, object]:
    if isinstance(record, _CachedTrackRecord):
        if record.kind not in (HostMediaFileKind.AUDIO, HostMediaFileKind.VIDEO):
            raise HostMediaScanError("A cached Track needs an audio or video kind")
        metadata: dict[str, object] = {
            "title": record.title,
            "artist": record.artist,
            "album": record.album,
            "album_artist": record.album_artist,
            "genre": record.genre,
            "media_type": record.media_type.value
            if record.media_type is not None
            else "",
            "tag_values": [
                {"name": tag.name, "value": tag.value} for tag in record.tag_values
            ],
            "year": record.year,
            "track_number": record.track_number,
            "total_tracks": record.total_tracks,
            "disc_number": record.disc_number,
            "total_discs": record.total_discs,
            "length_ms": record.length_ms,
            "bitrate_kbps": record.bitrate_kbps,
            "sample_rate_hz": record.sample_rate_hz,
            "acoustic_fingerprint": record.acoustic_fingerprint,
            "artwork_kind": (
                "" if record.artwork_kind is None else record.artwork_kind.value
            ),
            "artwork_path": (
                "" if record.artwork_path is None else os.fspath(record.artwork_path)
            ),
            "artwork_size_bytes": record.artwork_size_bytes,
            "artwork_modified_ns": record.artwork_modified_ns,
            "artwork_content_sha256": record.artwork_content_sha256,
        }
    elif isinstance(record, _CachedPhotoRecord):
        if record.kind is not HostMediaFileKind.PHOTO:
            raise HostMediaScanError("A cached Photo needs a photo kind")
        metadata = {
            "width": record.width,
            "height": record.height,
            "content_sha256": record.content_sha256,
        }
    else:
        if record.kind is not HostMediaFileKind.PLAYLIST:
            raise HostMediaScanError("A cached Playlist needs a playlist kind")
        metadata = {
            "title": record.title,
            "references": [os.fspath(path) for path in record.references],
        }
    return {
        "path": os.fspath(record.path),
        "kind": record.kind.value,
        "size_bytes": record.size_bytes,
        "modified_ns": record.modified_ns,
        "warning": record.warning,
        "metadata": metadata,
    }


def _record_from_document(value: object) -> _CachedRecord:
    row = _object(value, "cache entry")
    if frozenset(row) != _CACHE_ENTRY_FIELDS:
        raise ValueError("Host media cache entry fields are invalid")
    path = Path(_text(row["path"], "path"))
    if not path.is_absolute():
        raise ValueError("Host media cache paths must be absolute")
    host_path = HostPath(path)
    kind = HostMediaFileKind(_text(row["kind"], "kind"))
    size_bytes = _integer(row["size_bytes"], "size_bytes")
    modified_ns = _integer(row["modified_ns"], "modified_ns")
    warning = _text(row["warning"], "warning")
    metadata = _object(row["metadata"], "metadata")
    if kind in (HostMediaFileKind.AUDIO, HostMediaFileKind.VIDEO):
        # Ignore the unused digest emitted by an earlier v10 development build.
        if frozenset(metadata) - {"payload_sha256"} != _TRACK_METADATA_FIELDS:
            raise ValueError("Cached Track metadata fields are invalid")
        acoustic_fingerprint = _text(
            metadata["acoustic_fingerprint"],
            "acoustic_fingerprint",
        )
        if acoustic_fingerprint:
            try:
                acoustic_fingerprint = normalize_fpcalc_fingerprint(
                    acoustic_fingerprint
                )
            except FpcalcError as error:
                raise ValueError("Cached Acoustic Fingerprint is invalid") from error
        artwork_kind_value = _text(metadata["artwork_kind"], "artwork_kind")
        artwork_path_value = _text(metadata["artwork_path"], "artwork_path")
        artwork_digest_value = _text(
            metadata["artwork_content_sha256"],
            "artwork_content_sha256",
        )
        artwork_kind = (
            None if not artwork_kind_value else HostArtworkKind(artwork_kind_value)
        )
        artwork_path = (
            None if not artwork_path_value else HostPath(Path(artwork_path_value))
        )
        if (artwork_kind is None) != (artwork_path is None) or (
            artwork_kind is None
        ) != (not artwork_digest_value):
            raise ValueError("Cached Host artwork fields are inconsistent")
        if artwork_path is not None and not artwork_path.path.is_absolute():
            raise ValueError("Cached Host artwork paths must be absolute")
        artwork_digest = (
            ""
            if not artwork_digest_value
            else _sha256(artwork_digest_value, "artwork_content_sha256")
        )
        return _CachedTrackRecord(
            path=host_path,
            kind=kind,
            size_bytes=size_bytes,
            modified_ns=modified_ns,
            warning=warning,
            tag_values=_cached_tag_values(metadata["tag_values"]),
            title=_text(metadata["title"], "title"),
            artist=_text(metadata["artist"], "artist"),
            album=_text(metadata["album"], "album"),
            album_artist=_text(metadata["album_artist"], "album_artist"),
            genre=_text(metadata["genre"], "genre"),
            media_type=MediaType(_text(metadata["media_type"], "media_type"))
            if metadata["media_type"]
            else None,
            year=_integer(metadata["year"], "year"),
            track_number=_integer(metadata["track_number"], "track_number"),
            total_tracks=_integer(metadata["total_tracks"], "total_tracks"),
            disc_number=_integer(metadata["disc_number"], "disc_number"),
            total_discs=_integer(metadata["total_discs"], "total_discs"),
            length_ms=_integer(metadata["length_ms"], "length_ms"),
            bitrate_kbps=_integer(metadata["bitrate_kbps"], "bitrate_kbps"),
            sample_rate_hz=_integer(
                metadata["sample_rate_hz"],
                "sample_rate_hz",
            ),
            acoustic_fingerprint=acoustic_fingerprint,
            artwork_kind=artwork_kind,
            artwork_path=artwork_path,
            artwork_size_bytes=_integer(
                metadata["artwork_size_bytes"],
                "artwork_size_bytes",
            ),
            artwork_modified_ns=_integer(
                metadata["artwork_modified_ns"],
                "artwork_modified_ns",
            ),
            artwork_content_sha256=artwork_digest,
        )
    if kind is HostMediaFileKind.PHOTO:
        if frozenset(metadata) != _PHOTO_METADATA_FIELDS:
            raise ValueError("Cached Photo metadata fields are invalid")
        return _CachedPhotoRecord(
            path=host_path,
            kind=kind,
            size_bytes=size_bytes,
            modified_ns=modified_ns,
            warning=warning,
            width=_integer(metadata["width"], "width"),
            height=_integer(metadata["height"], "height"),
            content_sha256=_sha256(
                metadata["content_sha256"],
                "content_sha256",
            ),
        )
    if frozenset(metadata) != _PLAYLIST_METADATA_FIELDS:
        raise ValueError("Cached Playlist metadata fields are invalid")
    raw_references = _array(metadata["references"], "references")
    references = tuple(
        HostPath(reference_path)
        for item in raw_references
        if (reference_path := Path(_text(item, "reference"))).is_absolute()
    )
    if len(references) != len(raw_references):
        raise ValueError("Host media cache reference paths must be absolute")
    return _CachedPlaylistRecord(
        path=host_path,
        kind=kind,
        size_bytes=size_bytes,
        modified_ns=modified_ns,
        warning=warning,
        title=_text(metadata["title"], "title"),
        references=references,
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
            raise ValueError(f"Duplicate Host media cache field: {key}")
        result[key] = value
    return result


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object for {label}")
    raw = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in raw):
        raise ValueError(f"Expected text keys for {label}")
    return cast("dict[str, object]", raw)


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"Expected an array for {label}")
    return cast("list[object]", value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) > 65_536:
        raise ValueError(f"Expected bounded text for {label}")
    return value


def _sha256(value: object, label: str) -> str:
    result = _text(value, label)
    if len(result) != 64 or any(
        character not in "0123456789abcdef" for character in result
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return result


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Expected a non-negative integer for {label}")
    return value


def _cached_tag_values(value: object) -> tuple[MediaTag, ...]:
    values: list[MediaTag] = []
    seen: set[str] = set()
    for entry in _array(value, "tag_values"):
        row = _object(entry, "tag")
        if set(row) != {"name", "value"}:
            raise ValueError("Cached tag fields are invalid")
        name = _text(row["name"], "tag name")
        if name not in TAG_NAMES or name in seen:
            raise ValueError("Cached tag name is unknown or duplicated")
        seen.add(name)
        values.append(MediaTag(name, _text(row["value"], "tag value")))
    return tuple(values)


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value) if math.isfinite(value) and value >= 0 else 0.0


def _nonnegative_int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _stable_identity(path: os.PathLike[str], namespace: str) -> int:
    digest = hashlib.blake2b(
        f"iopenpod.host.{namespace}.v1\0{_path_identity(path)}".encode(),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


def _stable_content_identity(content_sha256: str, namespace: str) -> int:
    digest = hashlib.blake2b(
        f"iopenpod.host.{namespace}.v1\0{content_sha256}".encode(),
        digest_size=8,
    ).digest()
    identity = int.from_bytes(digest, "big") & ((1 << 63) - 1)
    return identity or 1


def _entry_identity(
    playlist: os.PathLike[str], index: int, target: os.PathLike[str]
) -> str:
    return hashlib.sha256(
        f"iopenpod.host.playlist-entry.v1\0{_path_identity(playlist)}\0{index}\0{_path_identity(target)}".encode()
    ).hexdigest()


def _unique_records(records: Iterable[_CachedRecord]) -> tuple[_CachedRecord, ...]:
    values: dict[str, _CachedRecord] = {}
    for record in records:
        values[_path_identity(record.path.path)] = record
    return tuple(
        sorted(values.values(), key=lambda record: _path_identity(record.path.path))
    )


def _path_identity(path: os.PathLike[str]) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


__all__ = [
    "HostArtworkKind",
    "HostMediaArtworkLoader",
    "HostMediaArtworkSource",
    "HostMediaCacheStats",
    "HostMediaFileKind",
    "HostMediaLibrary",
    "HostMediaPhotoLoader",
    "HostMediaScanCancelledError",
    "HostMediaScanError",
    "HostMediaScanIssue",
    "HostMediaScanProgress",
    "HostMediaScanStage",
    "HostMediaScanner",
    "HostMediaSource",
    "HostMediaTreeChangedError",
    "PendingHostMediaScan",
    "PlaylistExternalReference",
    "classify_host_media_file",
    "embedded_artwork_from_bytes",
]
