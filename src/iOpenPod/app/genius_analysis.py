"""Bounded, source-checked acoustic analysis for native Genius preparation."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from dataclasses import dataclass
from pathlib import PurePosixPath
from threading import Event, Lock
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from iOpenPod.app.genius_analysis_cache import GeniusProfileCache
from iOpenPod.app.genius_audio import (
    GENIUS_AUDIO_PROFILE_VERSION,
    GeniusAudioProfile,
    profile_genius_pcm,
)
from iPodDB.library import MediaKind, is_video_track
from storage import (
    AtomicHostFile,
    ConcurrentModificationError,
    DevicePath,
    FilePreconditionError,
    FilesystemSessionError,
    HostPath,
    SessionInvalidatedError,
    StorageError,
)
from storage.host_input import LocalHostFile
from storage.media_processing import (
    MediaToolError,
    MediaToolFinder,
    find_media_tool,
    run_media_tool,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from iOpenPod.app.media.importing import LibraryMediaSource
    from iPodDB.library import LibrarySnapshot, Track
    from storage import FileIdentity, FilesystemSession


GENIUS_SAMPLE_RATE_HZ = 22_050
MAX_GENIUS_AUDIO_SECONDS = 15 * 60
_MAX_PCM_BYTES = GENIUS_SAMPLE_RATE_HZ * MAX_GENIUS_AUDIO_SECONDS * 4
_MAX_ANALYSIS_WORKERS = 2
# Explicit single-file demuxers prevent a disguised playlist from following
# external references. MOV external data references remain disabled by default.
_INPUT_FORMATS = {
    ".aac": "aac",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".alac": "mov",
    ".flac": "flac",
    ".m4a": "mov",
    ".mp3": "mp3",
    ".oga": "ogg",
    ".ogg": "ogg",
    ".opus": "ogg",
    ".wav": "wav",
    ".wma": "asf",
    ".wv": "wv",
}


class GeniusAudioDecodeError(RuntimeError):
    """Optional acoustic analysis could not decode one source within its bounds."""


class GeniusPCMDecoder(Protocol):
    def decode(
        self,
        source: HostPath | DevicePath,
        *,
        input_suffix: str,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes: ...


class GeniusProfiler(Protocol):
    def __call__(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        checkpoint: Callable[[], None],
    ) -> GeniusAudioProfile: ...


class FFmpegGeniusPCMDecoder:
    """Decode one pinned input to bounded mono PCM through Storage's runner."""

    def __init__(
        self,
        *,
        find_tool: MediaToolFinder | None = None,
    ) -> None:
        self._find_tool = find_tool or find_media_tool
        self._lookup_done = False
        self._executable: HostPath | None = None
        self._lookup_lock = Lock()

    def for_analysis(self) -> FFmpegGeniusPCMDecoder:
        """Resolve lazily once this run; the next run retries missing tools."""
        decoder = copy(self)
        decoder._lookup_done = False
        decoder._executable = None
        return decoder

    def decode(
        self,
        source: HostPath | DevicePath,
        *,
        input_suffix: str,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes:
        checkpoint()
        input_format = _INPUT_FORMATS.get(input_suffix.casefold())
        if input_format is None:
            raise GeniusAudioDecodeError("No safe decoder for this audio extension")
        with self._lookup_lock:
            if not self._lookup_done:
                self._executable = self._find_tool("ffmpeg")
                self._lookup_done = True
        executable = self._executable
        if executable is None:
            raise GeniusAudioDecodeError("FFmpeg is unavailable for acoustic analysis")
        arguments = (
            "-nostdin",
            "-hide_banner",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            input_format,
            "-i",
        )
        suffix = (
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            str(GENIUS_SAMPLE_RATE_HZ),
            "-f",
            "f32le",
            "pipe:1",
        )
        try:
            if isinstance(source, DevicePath):
                output = session.read_with_tool(
                    source,
                    executable,
                    arguments,
                    arguments_after_input=suffix,
                    checkpoint=checkpoint,
                    timeout_seconds=300,
                    max_output_bytes=_MAX_PCM_BYTES,
                    max_stderr_bytes=65_536,
                    low_priority=True,
                )
            else:
                output = run_media_tool(
                    executable,
                    arguments,
                    input_file=source,
                    arguments_after_input=suffix,
                    checkpoint=checkpoint,
                    timeout_seconds=300,
                    max_output_bytes=_MAX_PCM_BYTES,
                    max_stderr_bytes=65_536,
                    low_priority=True,
                )
        except MediaToolError as error:
            raise GeniusAudioDecodeError(str(error)) from error
        checkpoint()
        return output.stdout


@dataclass(frozen=True, slots=True)
class GeniusAnalysisIssue:
    track_id: int | None
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class GeniusAnalysisActivity:
    """Display identity for one admitted music Track."""

    track_id: int
    title: str


@dataclass(frozen=True, slots=True)
class GeniusAnalysisProgress:
    completed: int
    total: int
    track_id: int
    title: str
    cached: bool = False
    active: tuple[GeniusAnalysisActivity, ...] = ()


@dataclass(frozen=True, slots=True)
class GeniusAnalysisDependency:
    """Cheap device-file identity, never a substitute for write authorization."""

    path: DevicePath
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class GeniusAnalysisResult:
    profiles: Mapping[int, GeniusAudioProfile]
    issues: tuple[GeniusAnalysisIssue, ...] = ()
    dependencies: tuple[GeniusAnalysisDependency, ...] = ()

    def validate_sources(
        self, session: FilesystemSession, *, checkpoint: Callable[[], None]
    ) -> None:
        checkpoint = _session_checkpoint(session, checkpoint)
        for dependency in self.dependencies:
            checkpoint()
            _validate_device(session, dependency)
        checkpoint()


@dataclass(frozen=True, slots=True)
class _Source:
    path: HostPath | DevicePath
    key: str
    host: LocalHostFile | None = None
    dependency: GeniusAnalysisDependency | None = None

    def validate(self, session: FilesystemSession) -> None:
        if self.host is not None:
            try:
                self.host.validate()
            except (OSError, StorageError) as error:
                raise ConcurrentModificationError(
                    "The Genius Host audio source changed during analysis"
                ) from error
        if self.dependency is not None:
            _validate_device(session, self.dependency)


@dataclass(frozen=True, slots=True)
class _AnalyzedTrack:
    source: _Source
    profile: GeniusAudioProfile
    cached: bool


class GeniusAnalysisService:
    """Profile at most two music sources concurrently and retain successful work."""

    def __init__(
        self,
        cache_file: AtomicHostFile | None = None,
        decoder: GeniusPCMDecoder | None = None,
        *,
        profiler: GeniusProfiler | None = None,
    ) -> None:
        self._cache = GeniusProfileCache(cache_file)
        self._cache_lock = Lock()
        self._decoder = decoder or FFmpegGeniusPCMDecoder()
        self._profiler = profiler or profile_genius_pcm

    def analyze(
        self,
        snapshot: LibrarySnapshot,
        session: FilesystemSession,
        *,
        media: tuple[LibraryMediaSource, ...] = (),
        checkpoint: Callable[[], None],
        progress: Callable[[GeniusAnalysisProgress], None] | None = None,
    ) -> GeniusAnalysisResult:
        checkpoint = _session_checkpoint(session, checkpoint)
        checkpoint()
        decoder = (
            self._decoder.for_analysis()
            if isinstance(self._decoder, FFmpegGeniusPCMDecoder)
            else self._decoder
        )
        supplied = {source.media.track_id: source for source in media}
        if len(supplied) != len(media):
            raise ValueError("Genius analysis media must have unique Track IDs")
        issues: list[GeniusAnalysisIssue] = []
        profiles: dict[int, GeniusAudioProfile] = {}
        dependencies: dict[DevicePath, GeniusAnalysisDependency] = {}
        try:
            self._cache.load(checkpoint)
        except (
            FilesystemSessionError,
            ConcurrentModificationError,
            FilePreconditionError,
        ):
            raise
        except (OSError, StorageError, ValueError) as error:
            issues.append(GeniusAnalysisIssue(None, "genius.cache_read", str(error)))
        cache_writable = True

        def save(*, force: bool = False) -> None:
            nonlocal cache_writable
            if cache_writable:
                try:
                    self._cache.save(checkpoint, force=force)
                except (
                    FilesystemSessionError,
                    ConcurrentModificationError,
                    FilePreconditionError,
                ):
                    raise
                except (OSError, StorageError, ValueError) as error:
                    cache_writable = False
                    issues.append(
                        GeniusAnalysisIssue(None, "genius.cache_write", str(error))
                    )

        tracks = tuple(
            track
            for track in snapshot.tracks
            if track.media_kind is MediaKind.MUSIC
            and not track.metadata.podcast
            and not is_video_track(track)
        )
        stopped = Event()

        def worker_checkpoint() -> None:
            if stopped.is_set():
                checkpoint()
                raise PreparationStoppedError
            checkpoint()

        try:
            with ThreadPoolExecutor(max_workers=_MAX_ANALYSIS_WORKERS) as workers:
                for first in range(0, len(tracks), _MAX_ANALYSIS_WORKERS):
                    checkpoint()
                    batch = tracks[first : first + _MAX_ANALYSIS_WORKERS]
                    futures = tuple(
                        workers.submit(
                            self._analyze_track,
                            track,
                            supplied.get(track.track_id),
                            session,
                            decoder,
                            worker_checkpoint,
                        )
                        for track in batch
                    )
                    if progress is not None:
                        try:
                            progress(
                                GeniusAnalysisProgress(
                                    first,
                                    len(tracks),
                                    batch[0].track_id,
                                    batch[0].title,
                                    active=tuple(
                                        GeniusAnalysisActivity(
                                            track.track_id, track.title
                                        )
                                        for track in batch
                                    ),
                                ),
                            )
                        except BaseException:
                            stopped.set()
                            raise
                    for index, (track, future) in enumerate(
                        zip(batch, futures, strict=True), first
                    ):
                        try:
                            outcome = future.result()
                            checkpoint()
                            if isinstance(outcome, GeniusAnalysisIssue):
                                issues.append(outcome)
                                cached = False
                            else:
                                if not outcome.cached:
                                    with self._cache_lock:
                                        self._cache.remember(
                                            outcome.source.key, outcome.profile
                                        )
                                profiles[track.track_id] = outcome.profile
                                if outcome.source.dependency is not None:
                                    dependencies[outcome.source.dependency.path] = (
                                        outcome.source.dependency
                                    )
                                cached = outcome.cached
                                with self._cache_lock:
                                    save()
                            if progress is not None:
                                progress(
                                    GeniusAnalysisProgress(
                                        index + 1,
                                        len(tracks),
                                        track.track_id,
                                        track.title,
                                        cached,
                                        tuple(
                                            GeniusAnalysisActivity(
                                                pending.track_id, pending.title
                                            )
                                            for pending in batch[index - first + 1 :]
                                        ),
                                    )
                                )
                        except BaseException:
                            stopped.set()
                            raise
        finally:
            # Successful earlier work survives a failed source. Cancellation is
            # still propagated; checkpointed cache writes never mask it.
            save(force=True)
        result = GeniusAnalysisResult(
            MappingProxyType(profiles), tuple(issues), tuple(dependencies.values())
        )
        result.validate_sources(session, checkpoint=checkpoint)
        return result

    def _analyze_track(
        self,
        track: Track,
        supplied: LibraryMediaSource | None,
        session: FilesystemSession,
        decoder: GeniusPCMDecoder,
        checkpoint: Callable[[], None],
    ) -> _AnalyzedTrack | GeniusAnalysisIssue:
        try:
            source = _source(track, supplied, session, checkpoint)
            with self._cache_lock:
                profile = self._cache.get(source.key)
            cached = profile is not None
            try:
                if profile is None:
                    if track.length_ms > MAX_GENIUS_AUDIO_SECONDS * 1000:
                        raise GeniusAudioDecodeError(
                            "Track exceeds the 15-minute acoustic analysis limit"
                        )
                    pcm = decoder.decode(
                        source.path,
                        input_suffix=PurePosixPath(track.metadata.location).suffix,
                        session=session,
                        checkpoint=checkpoint,
                    )
                    if len(pcm) > _MAX_PCM_BYTES:
                        raise GeniusAudioDecodeError(
                            "Decoded audio exceeds its byte limit"
                        )
                    profile = self._profiler(
                        pcm, sample_rate_hz=GENIUS_SAMPLE_RATE_HZ, checkpoint=checkpoint
                    )
                    del pcm
            finally:
                source.validate(session)
                checkpoint()
            return _AnalyzedTrack(source, profile, cached)
        except (
            FilesystemSessionError,
            ConcurrentModificationError,
            FilePreconditionError,
            PreparationStoppedError,
        ):
            raise
        except (GeniusAudioDecodeError, OSError, StorageError, ValueError) as error:
            return GeniusAnalysisIssue(
                track.track_id, "genius.audio_unavailable", str(error)
            )


class PreparationStoppedError(RuntimeError):
    """A peer failed, so unfinished optional analysis must stop."""


def _source(
    track: Track,
    supplied: LibraryMediaSource | None,
    session: FilesystemSession,
    checkpoint: Callable[[], None],
) -> _Source:
    if supplied is not None:
        try:
            observed = LocalHostFile.observe(supplied.source)
            fingerprint = supplied.fingerprint
            if observed.size_bytes != fingerprint.size:
                raise ConcurrentModificationError(
                    "The prepared Genius Host audio changed size"
                )
            digest = hashlib.sha256()
            with observed.open_read(
                checkpoint=checkpoint, max_bytes=fingerprint.size
            ) as stream:
                while chunk := stream.read(1024 * 1024):
                    checkpoint()
                    digest.update(chunk)
            if digest.hexdigest() != fingerprint.sha256:
                raise ConcurrentModificationError(
                    "The prepared Genius Host audio changed content"
                )
        except (
            FilesystemSessionError,
            ConcurrentModificationError,
            FilePreconditionError,
        ):
            raise
        except (OSError, StorageError) as error:
            raise ConcurrentModificationError(
                "The prepared Genius Host audio is no longer available"
            ) from error
        # The prepared content fingerprint allows equal verified Host copies to
        # reuse one profile. It may describe the original input rather than the
        # capture's inode or timestamps; pin the capture's own observed identity.
        key = _key(("host", fingerprint.size, fingerprint.sha256))
        return _Source(supplied.source, key, host=observed)
    path = DevicePath(track.metadata.location)
    identity = session.file_identity(path)
    mounted = session.mounted_volume
    key = _key(
        (
            "device",
            mounted.physical_device.id.value,
            mounted.volume.id.value,
            track.ipod.db_track_id if track.ipod is not None else track.track_id,
            str(path),
            identity.size,
            identity.modified_ns,
            identity.device,
            identity.inode,
        )
    )
    return _Source(path, key, dependency=GeniusAnalysisDependency(path, identity))


def _key(values: tuple[object, ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            (GENIUS_AUDIO_PROFILE_VERSION, GENIUS_SAMPLE_RATE_HZ, values),
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    ).hexdigest()


def _validate_device(
    session: FilesystemSession, dependency: GeniusAnalysisDependency
) -> None:
    try:
        current = session.file_identity(dependency.path)
    except FilesystemSessionError:
        raise
    except (OSError, StorageError) as error:
        raise ConcurrentModificationError(
            "The Genius device audio source changed during preparation"
        ) from error
    if current != dependency.identity:
        raise ConcurrentModificationError(
            "The Genius device audio source changed during preparation"
        )


def _session_checkpoint(
    session: FilesystemSession, checkpoint: Callable[[], None]
) -> Callable[[], None]:
    def checked() -> None:
        checkpoint()
        if not session.is_active:
            raise SessionInvalidatedError(
                "The Filesystem Session ended during Genius acoustic analysis"
            )

    return checked
