"""Bounded, source-checked acoustic analysis for native Genius preparation."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from copy import copy
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from threading import Event, Lock
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from threadpoolctl import threadpool_limits

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
    FileIdentity,
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
    available_compute_threads,
    find_media_tool,
    run_media_tool,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from iOpenPod.app.media.importing import LibraryMediaSource
    from iPodDB.library import LibrarySnapshot, PreparedLyrics, Track
    from storage import FileFingerprint, FilesystemSession


GENIUS_SAMPLE_RATE_HZ = 22_050
MAX_GENIUS_AUDIO_SECONDS = 15 * 60
_MAX_PCM_BYTES = GENIUS_SAMPLE_RATE_HZ * MAX_GENIUS_AUDIO_SECONDS * 4
# Removable devices keep ADR-0183's bound; staged Host captures are local files.
_MAX_DEVICE_ANALYSIS_WORKERS = 2
_MAX_ANALYSIS_WORKERS = 6


def _default_analysis_workers() -> int:
    """Use about one worker per physical core, within ADR-0271's memory bound."""
    return max(
        _MAX_DEVICE_ANALYSIS_WORKERS,
        min(_MAX_ANALYSIS_WORKERS, available_compute_threads() // 2),
    )


# Each profile's matrices are small. Measured BLAS threading slowed profiling even
# for one worker, and concurrent workers oversubscribed the CPU (ADR-0272).
_MATHS_THREADS_PER_WORKER = 1


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
        maximum_duration_seconds: int = MAX_GENIUS_AUDIO_SECONDS,
        sample_rate_hz: int = GENIUS_SAMPLE_RATE_HZ,
        channels: int = 1,
    ) -> None:
        if not 0 < maximum_duration_seconds <= 1801:
            raise ValueError("Invalid acoustic decode duration limit")
        if sample_rate_hz not in (22_050, 44_100) or channels not in (1, 2):
            raise ValueError("Unsupported acoustic PCM format")
        self._sample_rate_hz = sample_rate_hz
        self._channels = channels
        self._max_pcm_bytes = sample_rate_hz * maximum_duration_seconds * channels * 4
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
            str(self._channels),
            "-ar",
            str(self._sample_rate_hz),
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
                    max_output_bytes=self._max_pcm_bytes,
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
                    max_output_bytes=self._max_pcm_bytes,
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
    active: tuple[GeniusAnalysisActivity, ...] = ()


@dataclass(frozen=True, slots=True)
class GeniusAnalysisDependency:
    """Cheap device-file identity, never a substitute for write authorization."""

    path: DevicePath
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class GeniusPreparedProfile:
    """Analyzed Host content awaiting verified publication at its device path."""

    path: DevicePath
    size: int
    sha256: str
    profile: GeniusAudioProfile


@dataclass(frozen=True, slots=True)
class GeniusAnalysisResult:
    profiles: Mapping[int, GeniusAudioProfile]
    issues: tuple[GeniusAnalysisIssue, ...] = ()
    dependencies: tuple[GeniusAnalysisDependency, ...] = ()
    prepared_profiles: tuple[GeniusPreparedProfile, ...] = ()

    def with_tagged_media(
        self, tagged: tuple[PreparedLyrics, ...]
    ) -> GeniusAnalysisResult:
        """Carry profiles through captured tag-only rewrites of analyzed audio.

        The ordinary tag writer supplies the final content evidence. Association
        still waits for Storage to verify those exact bytes during publication.
        """
        prepared = {item.path: item for item in self.prepared_profiles}
        for item in tagged:
            profile = self.profiles.get(item.track_id)
            if profile is not None:
                path = DevicePath(item.file.relative_path)
                prepared[path] = GeniusPreparedProfile(
                    path, item.file.size, item.file.sha256, profile
                )
        return replace(self, prepared_profiles=tuple(prepared.values()))

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


class _AdmissionQueue:
    """Library-ordered waiting analysis with a separate bound for device reads.

    Host and device sources wait in separate Library-ordered queues. The earliest
    admissible head is admitted next, so a device Track waiting for a read slot
    does not hold back later staged Host captures.
    """

    def __init__(self, pending: list[tuple[Track, _Source]]) -> None:
        self._device: deque[tuple[int, Track, _Source]] = deque()
        self._host: deque[tuple[int, Track, _Source]] = deque()
        for index, (track, source) in enumerate(pending):
            queue = self._device if isinstance(source.path, DevicePath) else self._host
            queue.append((index, track, source))
        self._device_running = 0

    def __bool__(self) -> bool:
        return bool(self._device or self._host)

    def admit(self) -> tuple[Track, _Source, bool] | None:
        heads = [
            queue
            for queue, open_ in (
                (self._device, self._device_running < _MAX_DEVICE_ANALYSIS_WORKERS),
                (self._host, True),
            )
            if queue and open_
        ]
        if not heads:
            return None
        queue = min(heads, key=lambda waiting: waiting[0][0])
        _, track, source = queue.popleft()
        on_device = queue is self._device
        self._device_running += on_device
        return track, source, on_device

    def release(self, *, on_device: bool) -> None:
        self._device_running -= on_device

    def clear(self) -> None:
        self._device.clear()
        self._host.clear()


class GeniusAnalysisService:
    """Profile music sources concurrently and retain successful work.

    At most ``workers`` sources are analyzed at once, of which at most two read
    from the device. Admission follows Library order; outcomes are recorded as
    they complete, so one slow Track never idles the remaining workers.
    """

    def __init__(
        self,
        cache_file: AtomicHostFile | None = None,
        decoder: GeniusPCMDecoder | None = None,
        *,
        profiler: GeniusProfiler | None = None,
        workers: int | None = None,
    ) -> None:
        if workers is not None and not (
            _MAX_DEVICE_ANALYSIS_WORKERS <= workers <= _MAX_ANALYSIS_WORKERS
        ):
            raise ValueError("Genius analysis workers must be between 2 and 6")
        self._cache = GeniusProfileCache(cache_file)
        self._cache_lock = Lock()
        self._decoder = decoder or FFmpegGeniusPCMDecoder()
        self._profiler = profiler or profile_genius_pcm
        self._workers = workers or _default_analysis_workers()

    def analyze(
        self,
        snapshot: LibrarySnapshot,
        session: FilesystemSession,
        *,
        media: tuple[LibraryMediaSource, ...] = (),
        checkpoint: Callable[[], None],
        progress: Callable[[GeniusAnalysisProgress], None] | None = None,
        skip_requested: Callable[[], bool] | None = None,
    ) -> GeniusAnalysisResult:
        checkpoint = _session_checkpoint(session, checkpoint)
        should_skip = skip_requested or (lambda: False)
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
        try:
            with self._cache_lock:
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
                    with self._cache_lock:
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
        outcomes: dict[int, _AnalyzedTrack | GeniusAnalysisIssue] = {}
        pending: list[tuple[Track, _Source]] = []

        def worker_checkpoint() -> None:
            checkpoint()
            if stopped.is_set():
                raise PreparationStoppedError
            if should_skip():
                raise _AnalysisSkippedError

        try:
            # Resolve cache hits before admitting work. Cached Tracks still get
            # source checks, but never appear as active acoustic analysis.
            for track in tracks:
                checkpoint()
                if should_skip():
                    break
                try:
                    resolved = self._resolve_track(
                        track, supplied.get(track.track_id), session, worker_checkpoint
                    )
                except _AnalysisSkippedError:
                    break
                if isinstance(resolved, _Source):
                    pending.append((track, resolved))
                else:
                    outcomes[track.track_id] = resolved
            waiting = _AdmissionQueue(pending)
            # Insertion order is admission order, which progress reports as active.
            running: dict[
                Future[_AnalyzedTrack | GeniusAnalysisIssue], tuple[Track, bool]
            ] = {}
            completed = 0

            def report(track: Track | None, starting: tuple[Track, ...] = ()) -> None:
                active = (*(item for item, _ in running.values()), *starting)
                current = track or active[0]
                if progress is not None:
                    progress(
                        GeniusAnalysisProgress(
                            completed,
                            len(pending),
                            current.track_id,
                            current.title,
                            tuple(
                                GeniusAnalysisActivity(item.track_id, item.title)
                                for item in active
                            ),
                        )
                    )

            # The limit is process-wide; restore it only after every worker stops.
            with (
                threadpool_limits(
                    limits=_MATHS_THREADS_PER_WORKER,
                    user_api="blas",
                ),
                ThreadPoolExecutor(max_workers=self._workers) as workers,
            ):
                try:
                    while waiting or running:
                        checkpoint()
                        admitted: list[tuple[Track, _Source, bool]] = []
                        while (
                            len(running) + len(admitted) < self._workers
                            and not should_skip()
                        ):
                            admission = waiting.admit()
                            if admission is None:
                                break
                            admitted.append(admission)
                        if admitted:
                            # Report before starting, so a skip requested in
                            # response stops these Tracks before they are read.
                            report(None, tuple(track for track, _, _ in admitted))
                        for track, source, on_device in admitted:
                            if should_skip():
                                waiting.release(on_device=on_device)
                                continue
                            future = workers.submit(
                                self._analyze_track,
                                track,
                                source,
                                session,
                                decoder,
                                worker_checkpoint,
                            )
                            running[future] = (track, on_device)
                        if should_skip():
                            waiting.clear()
                        if not running:
                            break
                        done, _ = wait(running, return_when=FIRST_COMPLETED)
                        for future in [item for item in running if item in done]:
                            track, on_device = running.pop(future)
                            waiting.release(on_device=on_device)
                            try:
                                outcome = future.result()
                            except _AnalysisSkippedError:
                                continue
                            checkpoint()
                            outcomes[track.track_id] = outcome
                            if isinstance(outcome, _AnalyzedTrack):
                                with self._cache_lock:
                                    self._cache.remember(
                                        outcome.source.key, outcome.profile
                                    )
                                save()
                            completed += 1
                            report(track)
                except BaseException:
                    stopped.set()
                    raise
        finally:
            # Successful earlier work survives a failed source. Cancellation is
            # still propagated; checkpointed cache writes never mask it.
            save(force=True)
        profiles: dict[int, GeniusAudioProfile] = {}
        dependencies: dict[DevicePath, GeniusAnalysisDependency] = {}
        prepared_profiles: list[GeniusPreparedProfile] = []
        for track in tracks:
            checkpoint()
            resolved_outcome = outcomes.get(track.track_id)
            if resolved_outcome is None:
                continue
            if isinstance(resolved_outcome, GeniusAnalysisIssue):
                issues.append(resolved_outcome)
                continue
            profiles[track.track_id] = resolved_outcome.profile
            if resolved_outcome.source.dependency is not None:
                dependencies[resolved_outcome.source.dependency.path] = (
                    resolved_outcome.source.dependency
                )
            incoming = supplied.get(track.track_id)
            if incoming is not None:
                prepared_profiles.append(
                    GeniusPreparedProfile(
                        DevicePath(incoming.media.file.relative_path),
                        incoming.fingerprint.size,
                        incoming.fingerprint.sha256,
                        resolved_outcome.profile,
                    )
                )
        result = GeniusAnalysisResult(
            MappingProxyType(profiles),
            tuple(issues),
            tuple(dependencies.values()),
            tuple(prepared_profiles),
        )
        result.validate_sources(session, checkpoint=checkpoint)
        return result

    def remember_committed(
        self,
        result: GeniusAnalysisResult,
        snapshot: LibrarySnapshot,
        session: FilesystemSession,
        fingerprints: Mapping[DevicePath, FileFingerprint | None],
    ) -> None:
        """Associate profiles only with matching, Storage-verified output bytes.

        Use the committed fingerprint's identity, never a fresh observation that
        might already describe different content. The next lookup rechecks it.
        """
        prepared = {str(item.path): item for item in result.prepared_profiles}
        if not prepared:
            return
        checkpoint = _session_checkpoint(session, lambda: None)
        for track in snapshot.tracks:
            checkpoint()
            item = prepared.get(track.metadata.location)
            if item is None:
                continue
            path = item.path
            fingerprint = fingerprints.get(path)
            if fingerprint is None or (item.size, item.sha256) != (
                fingerprint.size,
                fingerprint.sha256,
            ):
                continue
            identity = FileIdentity(
                fingerprint.size,
                fingerprint.modified_ns,
                fingerprint.device,
                fingerprint.inode,
            )
            with self._cache_lock:
                self._cache.remember(
                    _device_key(track, path, session, identity), item.profile
                )
        with self._cache_lock:
            self._cache.save(checkpoint, force=True)

    def _resolve_track(
        self,
        track: Track,
        supplied: LibraryMediaSource | None,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> _Source | _AnalyzedTrack | GeniusAnalysisIssue:
        try:
            source = _source(track, supplied, session, checkpoint)
            with self._cache_lock:
                profile = self._cache.get(source.key)
            if profile is None:
                return source
            source.validate(session)
            checkpoint()
            return _AnalyzedTrack(source, profile)
        except (
            FilesystemSessionError,
            ConcurrentModificationError,
            FilePreconditionError,
        ):
            raise
        except (OSError, StorageError, ValueError) as error:
            return GeniusAnalysisIssue(
                track.track_id, "genius.audio_unavailable", str(error)
            )

    def _analyze_track(
        self,
        track: Track,
        source: _Source,
        session: FilesystemSession,
        decoder: GeniusPCMDecoder,
        checkpoint: Callable[[], None],
    ) -> _AnalyzedTrack | GeniusAnalysisIssue:
        try:
            try:
                checkpoint()
                source.validate(session)
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
                    raise GeniusAudioDecodeError("Decoded audio exceeds its byte limit")
                profile = self._profiler(
                    pcm, sample_rate_hz=GENIUS_SAMPLE_RATE_HZ, checkpoint=checkpoint
                )
                del pcm
            finally:
                source.validate(session)
                checkpoint()
            return _AnalyzedTrack(source, profile)
        except (
            FilesystemSessionError,
            ConcurrentModificationError,
            FilePreconditionError,
            PreparationStoppedError,
            _AnalysisSkippedError,
        ):
            raise
        except (GeniusAudioDecodeError, OSError, StorageError, ValueError) as error:
            return GeniusAnalysisIssue(
                track.track_id, "genius.audio_unavailable", str(error)
            )


class PreparationStoppedError(RuntimeError):
    """A peer failed, so unfinished optional analysis must stop."""


class _AnalysisSkippedError(RuntimeError):
    """The user skipped unfinished acoustic analysis for this Sync."""


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
    return _Source(
        path,
        _device_key(track, path, session, identity),
        dependency=GeniusAnalysisDependency(path, identity),
    )


def _device_key(
    track: Track,
    path: DevicePath,
    session: FilesystemSession,
    identity: FileIdentity,
) -> str:
    mounted = session.mounted_volume
    return _key(
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
