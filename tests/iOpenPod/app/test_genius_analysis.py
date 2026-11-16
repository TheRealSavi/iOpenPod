"""Cached acoustic evidence remains optional, bounded, and source checked."""

from __future__ import annotations

import json
import shutil
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock, current_thread
from typing import TYPE_CHECKING

import pytest
from threadpoolctl import threadpool_info

from iOpenPod.app import genius_analysis, genius_analysis_cache
from iOpenPod.app.genius_analysis import (
    FFmpegGeniusPCMDecoder,
    GeniusAnalysisActivity,
    GeniusAnalysisProgress,
    GeniusAnalysisService,
    GeniusAudioDecodeError,
)
from iOpenPod.app.genius_analysis_cache import GeniusProfileCache
from iOpenPod.app.genius_audio import GeniusAudioProfile
from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.media.importing import LibraryMediaSource
from iPodDB.library import (
    AudioEncoding,
    FileDependency,
    IPodTrackDetails,
    LibrarySnapshot,
    MediaType,
    Track,
    TrackMetadata,
    prepared_audio,
)
from storage import (
    AccessMode,
    AtomicHostFile,
    ConcurrentModificationError,
    DevicePath,
    FilesystemSession,
    FilesystemSessionError,
    HostPath,
    Storage,
    StorageOperationError,
    capture_host_file,
)
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from collections.abc import Callable


def _checkpoint() -> None:
    pass


def _profile(
    pcm: bytes, *, sample_rate_hz: int, checkpoint: Callable[[], None]
) -> GeniusAudioProfile:
    assert sample_rate_hz == 22_050
    checkpoint()
    return GeniusAudioProfile(2.0, None, (float(pcm[0]),) * 29, None)


class _Decoder:
    def __init__(self, action: Callable[[], None] | None = None) -> None:
        self.sources: list[HostPath | DevicePath] = []
        self.action = action

    def decode(
        self,
        source: HostPath | DevicePath,
        *,
        input_suffix: str,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes:
        assert input_suffix == ".mp3"
        assert session.is_active
        checkpoint()
        self.sources.append(source)
        if self.action is not None:
            self.action()
        return b"\x01\x00\x00\x00"


def _device(
    tmp_path: Path,
) -> tuple[Path, VirtualStoragePlatform, FilesystemSession, LibrarySnapshot]:
    root = tmp_path / "device"
    root.mkdir(parents=True)
    (root / "song.mp3").write_bytes(b"original")
    platform = VirtualStoragePlatform()
    platform.add_volume(root, writable=False)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    session = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_ONLY
    )
    track = Track(
        1,
        "Song",
        "Artist",
        "Album",
        2_000,
        metadata=TrackMetadata(location="song.mp3"),
        ipod=IPodTrackDetails(db_track_id=100),
    )
    return root, platform, session, LibrarySnapshot((track,))


def test_device_cache_survives_reloads_and_preserves_source_checks(
    tmp_path: Path,
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    decoder = _Decoder()
    cache = AtomicHostFile(tmp_path / "profiles.json")
    service = GeniusAnalysisService(cache, decoder, profiler=_profile)
    first = service.analyze(snapshot, session, checkpoint=_checkpoint)
    revision = cache.revision()
    second = GeniusAnalysisService(cache, decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=_checkpoint
    )
    assert first == second
    assert first.issues == ()
    assert tuple(first.profiles) == (1,)
    assert len(first.dependencies) == 1
    assert decoder.sources == [DevicePath("song.mp3")]
    assert cache.revision() == revision
    (root / "song.mp3").write_bytes(b"changed after review")
    with pytest.raises(ConcurrentModificationError):
        second.validate_sources(session, checkpoint=_checkpoint)
    service.analyze(snapshot, session, checkpoint=_checkpoint)
    assert len(decoder.sources) == 2


def test_cache_reuse_never_crosses_device_identity(tmp_path: Path) -> None:
    root, platform, session, snapshot = _device(tmp_path)
    cache = AtomicHostFile(tmp_path / "profiles.json")
    decoder = _Decoder()
    service = GeniusAnalysisService(cache, decoder, profiler=_profile)
    service.analyze(snapshot, session, checkpoint=_checkpoint)
    session.close()
    platform.add_volume(root, device_id="different-device", writable=False)
    storage = Storage(platform)
    replacement = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_ONLY
    )
    service.analyze(snapshot, replacement, checkpoint=_checkpoint)
    assert len(decoder.sources) == 2


def test_only_uncached_tracks_are_queued_and_reported(tmp_path: Path) -> None:
    root, _, session, snapshot = _device(tmp_path)
    tracks = [snapshot.tracks[0]]
    for track_id in (2, 3):
        name = f"song-{track_id}.mp3"
        (root / name).write_bytes(b"audio")
        tracks.append(
            replace(
                tracks[0],
                track_id=track_id,
                metadata=TrackMetadata(location=name),
                ipod=IPodTrackDetails(db_track_id=100 + track_id),
            )
        )
    decoder = _Decoder()
    service = GeniusAnalysisService(decoder=decoder, profiler=_profile)
    service.analyze(
        replace(snapshot, tracks=(tracks[0], tracks[2])),
        session,
        checkpoint=_checkpoint,
    )
    decoder.sources.clear()
    progress: list[GeniusAnalysisProgress] = []
    snapshot = replace(snapshot, tracks=tuple(tracks))
    result = service.analyze(
        snapshot, session, checkpoint=_checkpoint, progress=progress.append
    )
    assert decoder.sources == [DevicePath("song-2.mp3")]
    assert [(event.completed, event.total) for event in progress] == [(0, 1), (1, 1)]
    assert progress[0].active == (GeniusAnalysisActivity(2, "Song"),)
    assert progress[-1].active == ()
    assert tuple(result.profiles) == (1, 2, 3)
    assert len(result.dependencies) == 3
    progress.clear()
    decoder.sources.clear()
    repeated = service.analyze(
        snapshot, session, checkpoint=_checkpoint, progress=progress.append
    )
    assert repeated == result
    assert progress == []
    assert decoder.sources == []


@pytest.mark.parametrize("publication", ["matching", "missing", "different", "changed"])
def test_prepared_profile_reuse_requires_matching_committed_content(
    tmp_path: Path, publication: str
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    host = tmp_path / "replacement.mp3"
    host.write_bytes(b"replacement")
    with capture_host_file(HostPath(host), checkpoint=_checkpoint) as captured:
        fingerprint = captured.fingerprint
    source = LibraryMediaSource(
        HostPath(host),
        fingerprint,
        prepared_audio(
            1,
            FileDependency("song.mp3", fingerprint.size, fingerprint.sha256),
            AudioEncoding.MP3,
        ),
    )
    cache = AtomicHostFile(tmp_path / "profiles.json")
    decoder = _Decoder()
    service = GeniusAnalysisService(cache, decoder, profiler=_profile)
    result = service.analyze(snapshot, session, media=(source,), checkpoint=_checkpoint)
    (root / "song.mp3").write_bytes(
        b"other audio" if publication == "different" else b"replacement"
    )
    committed = session.fingerprint(DevicePath("song.mp3"))
    if publication == "changed":
        (root / "song.mp3").write_bytes(b"changed after commit")
    # Publication can assign the persistent identity after Host analysis.
    snapshot = replace(
        snapshot,
        tracks=(
            replace(
                snapshot.tracks[0], track_id=7, ipod=IPodTrackDetails(db_track_id=777)
            ),
        ),
    )
    service.remember_committed(
        result,
        snapshot,
        session,
        {} if publication == "missing" else {DevicePath("song.mp3"): committed},
    )
    repeated = GeniusAnalysisService(cache, decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=_checkpoint
    )
    assert tuple(repeated.profiles) == (7,)
    assert len(decoder.sources) == (1 if publication == "matching" else 2)
    assert len(repeated.dependencies) == 1


def test_new_and_replaced_tracks_use_prepared_host_sources(tmp_path: Path) -> None:
    root, _, session, snapshot = _device(tmp_path)
    host = tmp_path / "replacement.mp3"
    host.write_bytes(b"replacement")
    with capture_host_file(HostPath(host), checkpoint=_checkpoint) as captured:
        fingerprint = captured.fingerprint
    source = LibraryMediaSource(
        HostPath(host),
        fingerprint,
        prepared_audio(
            1,
            FileDependency("song.mp3", fingerprint.size, fingerprint.sha256),
            AudioEncoding.MP3,
        ),
    )
    decoder = _Decoder()
    result = GeniusAnalysisService(decoder=decoder, profiler=_profile).analyze(
        snapshot, session, media=(source,), checkpoint=_checkpoint
    )
    assert decoder.sources == [HostPath(host)]
    assert result.dependencies == ()
    assert result.issues == ()
    assert (root / "song.mp3").read_bytes() == b"original"
    host.write_bytes(b"changed prepared file")
    with pytest.raises(ConcurrentModificationError):
        GeniusAnalysisService(decoder=decoder, profiler=_profile).analyze(
            snapshot, session, media=(source,), checkpoint=_checkpoint
        )


def test_prepared_capture_accepts_original_fingerprint_but_rejects_content_change(
    tmp_path: Path,
) -> None:
    _, _, session, snapshot = _device(tmp_path)
    host = tmp_path / "original.mp3"
    host.write_bytes(b"original prepared media")
    decoder = _Decoder()
    with capture_host_file(HostPath(host), checkpoint=_checkpoint) as captured:
        fingerprint = captured.fingerprint
        source = LibraryMediaSource(
            captured.snapshot,
            fingerprint,
            prepared_audio(
                1,
                FileDependency("song.mp3", fingerprint.size, fingerprint.sha256),
                AudioEncoding.MP3,
            ),
        )
        service = GeniusAnalysisService(decoder=decoder, profiler=_profile)
        result = service.analyze(
            snapshot, session, media=(source,), checkpoint=_checkpoint
        )
        assert result.issues == ()
        assert tuple(result.profiles) == (1,)
        assert decoder.sources == [captured.snapshot]
        Path(captured.snapshot).write_bytes(b"changed prepared media!")
        assert Path(captured.snapshot).stat().st_size == fingerprint.size
        with pytest.raises(ConcurrentModificationError, match="content"):
            service.analyze(snapshot, session, media=(source,), checkpoint=_checkpoint)


@pytest.mark.parametrize("failure", ["decode", "cancel", "disconnect", "mutate"])
def test_only_optional_decode_failure_can_be_downgraded(
    tmp_path: Path, failure: str
) -> None:
    root, _, session, snapshot = _device(tmp_path)

    def action() -> None:
        if failure == "decode":
            raise GeniusAudioDecodeError("Bad audio")
        if failure == "cancel":
            raise PreparationCancelledError
        if failure == "disconnect":
            session.invalidate("Disconnected while analyzing")
        else:
            (root / "song.mp3").write_bytes(b"unexpected replacement")

    decoder = _Decoder(action)
    service = GeniusAnalysisService(decoder=decoder, profiler=_profile)
    if failure == "decode":
        for _ in range(2):
            result = service.analyze(snapshot, session, checkpoint=_checkpoint)
            assert not result.profiles
            assert result.issues[0].code == "genius.audio_unavailable"
        assert len(decoder.sources) == 2
    else:
        error = {
            "cancel": PreparationCancelledError,
            "disconnect": FilesystemSessionError,
            "mutate": ConcurrentModificationError,
        }[failure]
        with pytest.raises(error):
            service.analyze(snapshot, session, checkpoint=_checkpoint)


def test_corrupt_cache_is_a_miss_and_successful_profiles_repair_it(
    tmp_path: Path,
) -> None:
    _, _, session, snapshot = _device(tmp_path)
    file = AtomicHostFile(tmp_path / "cache.json")
    file.replace_bytes(b"broken cache")
    decoder = _Decoder()
    service = GeniusAnalysisService(file, decoder, profiler=_profile)
    result = service.analyze(snapshot, session, checkpoint=_checkpoint)
    assert result.profiles
    assert result.issues[0].code == "genius.cache_read"
    repeated = GeniusAnalysisService(file, decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=_checkpoint
    )
    assert not repeated.issues
    assert len(decoder.sources) == 1


def test_only_final_eligible_music_is_analyzed(tmp_path: Path) -> None:
    root, _, session, snapshot = _device(tmp_path)
    (root / "long.mp3").write_bytes(b"long song")
    track = snapshot.tracks[0]
    snapshot = replace(
        snapshot,
        tracks=(
            track,
            replace(track, track_id=2, media_types=(MediaType.AUDIOBOOK,)),
            replace(track, track_id=3, media_types=(MediaType.VIDEO,)),
            replace(track, track_id=4, metadata=replace(track.metadata, podcast=True)),
            replace(
                track,
                track_id=5,
                length_ms=901_000,
                metadata=TrackMetadata(location="long.mp3"),
            ),
        ),
    )
    decoder = _Decoder()
    result = GeniusAnalysisService(decoder=decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=_checkpoint
    )
    assert tuple(result.profiles) == (1,)
    assert len(decoder.sources) == 1
    assert result.issues[0].track_id == 5


def _with_device_tracks(
    root: Path, snapshot: LibrarySnapshot, track_ids: tuple[int, ...]
) -> LibrarySnapshot:
    tracks = list(snapshot.tracks)
    for track_id in track_ids:
        name = f"song-{track_id}.mp3"
        (root / name).write_bytes(b"audio")
        tracks.append(
            replace(
                snapshot.tracks[0],
                track_id=track_id,
                metadata=TrackMetadata(location=name),
                ipod=IPodTrackDetails(db_track_id=100 + track_id),
            )
        )
    return replace(snapshot, tracks=tuple(tracks))


def _with_staged_tracks(
    tmp_path: Path, snapshot: LibrarySnapshot, track_ids: tuple[int, ...]
) -> tuple[LibrarySnapshot, tuple[LibraryMediaSource, ...]]:
    tracks = list(snapshot.tracks)
    sources: list[LibraryMediaSource] = []
    for track_id in track_ids:
        location = f"new-{track_id}.mp3"
        host = tmp_path / f"staged-{track_id}.mp3"
        host.write_bytes(f"staged {track_id}".encode())
        with capture_host_file(HostPath(host), checkpoint=_checkpoint) as captured:
            fingerprint = captured.fingerprint
        sources.append(
            LibraryMediaSource(
                HostPath(host),
                fingerprint,
                prepared_audio(
                    track_id,
                    FileDependency(location, fingerprint.size, fingerprint.sha256),
                    AudioEncoding.MP3,
                ),
            )
        )
        tracks.append(
            replace(
                snapshot.tracks[0],
                track_id=track_id,
                metadata=TrackMetadata(location=location),
                ipod=IPodTrackDetails(db_track_id=100 + track_id),
            )
        )
    return replace(snapshot, tracks=tuple(tracks)), tuple(sources)


class _GatedDecoder:
    """Hold every decode until released while recording concurrent sources."""

    def __init__(self, target: int) -> None:
        self.target = target
        self.reached = Event()
        self.release = Event()
        self.lock = Lock()
        self.active: list[HostPath | DevicePath] = []
        self.calls: list[HostPath | DevicePath] = []
        self.peak = 0
        self.peak_device = 0

    def decode(
        self,
        source: HostPath | DevicePath,
        *,
        input_suffix: str,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes:
        assert input_suffix == ".mp3"
        assert session.is_active
        with self.lock:
            self.calls.append(source)
            self.active.append(source)
            self.peak = max(self.peak, len(self.active))
            self.peak_device = max(
                self.peak_device,
                sum(isinstance(item, DevicePath) for item in self.active),
            )
            if len(self.active) == self.target:
                self.reached.set()
        try:
            assert self.release.wait(5)
            checkpoint()
            return b"\x01\x00\x00\x00"
        finally:
            with self.lock:
                self.active.remove(source)


def test_device_reads_stay_bounded_with_spare_workers_and_report_progress(
    tmp_path: Path,
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    snapshot = _with_device_tracks(root, snapshot, (2, 3))
    decoder = _GatedDecoder(target=2)
    progress: list[tuple[int, int]] = []
    active_snapshots: list[tuple[GeniusAnalysisActivity, ...]] = []
    progress_threads: set[object] = set()
    reported = Event()

    def on_progress(value: GeniusAnalysisProgress) -> None:
        progress_threads.add(current_thread())
        progress.append((value.completed, value.total))
        active_snapshots.append(value.active)
        reported.set()

    service = GeniusAnalysisService(decoder=decoder, profiler=_profile, workers=4)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            service.analyze,
            snapshot,
            session,
            checkpoint=_checkpoint,
            progress=on_progress,
        )
        try:
            assert decoder.reached.wait(5)
            assert reported.wait(5)
            # The third device read cannot start until a device slot is released.
            assert len(decoder.calls) == 2
            assert active_snapshots[0] == (
                GeniusAnalysisActivity(1, "Song"),
                GeniusAnalysisActivity(2, "Song"),
            )
        finally:
            decoder.release.set()
        result = future.result(timeout=10)
    assert decoder.peak == 2
    assert len(decoder.calls) == 3
    assert tuple(result.profiles) == (1, 2, 3)
    assert progress[0] == (0, 3)
    assert progress[-1] == (3, 3)
    completed = [value for value, _ in progress]
    assert completed == sorted(completed)
    assert all(len(active) <= 2 for active in active_snapshots)
    assert active_snapshots[-1] == ()
    assert len(progress_threads) == 1


def test_staged_host_sources_use_every_worker(tmp_path: Path) -> None:
    _, _, session, snapshot = _device(tmp_path)
    snapshot, media = _with_staged_tracks(tmp_path, snapshot, (2, 3, 4, 5))
    snapshot = replace(snapshot, tracks=snapshot.tracks[1:])
    decoder = _GatedDecoder(target=4)
    service = GeniusAnalysisService(decoder=decoder, profiler=_profile, workers=4)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            service.analyze, snapshot, session, media=media, checkpoint=_checkpoint
        )
        try:
            assert decoder.reached.wait(5)
        finally:
            decoder.release.set()
        result = future.result(timeout=10)
    assert decoder.peak == 4
    assert decoder.peak_device == 0
    assert tuple(result.profiles) == (2, 3, 4, 5)


def test_waiting_device_reads_do_not_hold_back_later_staged_sources(
    tmp_path: Path,
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    snapshot = _with_device_tracks(root, snapshot, (2, 3))
    snapshot, media = _with_staged_tracks(tmp_path, snapshot, (4, 5))
    decoder = _GatedDecoder(target=4)
    service = GeniusAnalysisService(decoder=decoder, profiler=_profile, workers=4)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            service.analyze, snapshot, session, media=media, checkpoint=_checkpoint
        )
        try:
            assert decoder.reached.wait(5)
            with decoder.lock:
                active = set(decoder.active)
        finally:
            decoder.release.set()
        result = future.result(timeout=10)
    assert active == {
        DevicePath("song.mp3"),
        DevicePath("song-2.mp3"),
        HostPath(tmp_path / "staged-4.mp3"),
        HostPath(tmp_path / "staged-5.mp3"),
    }
    assert decoder.peak_device == 2
    assert tuple(result.profiles) == (1, 2, 3, 4, 5)


def test_slow_track_does_not_hold_back_later_admission(tmp_path: Path) -> None:
    root, _, session, snapshot = _device(tmp_path)
    snapshot = _with_device_tracks(root, snapshot, (2, 3))
    third_started = Event()

    class SlowFirstDecoder(_Decoder):
        def decode(
            self,
            source: HostPath | DevicePath,
            *,
            input_suffix: str,
            session: FilesystemSession,
            checkpoint: Callable[[], None],
        ) -> bytes:
            if source == DevicePath("song-3.mp3"):
                third_started.set()
            elif source == DevicePath("song.mp3"):
                # A pairwise batch would never start Track 3 while this waits.
                assert third_started.wait(5)
            return super().decode(
                source,
                input_suffix=input_suffix,
                session=session,
                checkpoint=checkpoint,
            )

    result = GeniusAnalysisService(
        decoder=SlowFirstDecoder(), profiler=_profile, workers=2
    ).analyze(snapshot, session, checkpoint=_checkpoint)
    assert third_started.is_set()
    assert tuple(result.profiles) == (1, 2, 3)


@pytest.mark.parametrize("workers", [0, 1, 7])
def test_worker_count_is_bounded(workers: int) -> None:
    with pytest.raises(ValueError, match="between 2 and 6"):
        GeniusAnalysisService(workers=workers)


@pytest.mark.parametrize(("threads", "expected"), [(1, 2), (4, 2), (8, 4), (16, 6)])
def test_default_workers_follow_physical_cores_within_bounds(
    monkeypatch: pytest.MonkeyPatch, threads: int, expected: int
) -> None:
    monkeypatch.setattr(genius_analysis, "available_compute_threads", lambda: threads)
    assert genius_analysis._default_analysis_workers() == expected  # pyright: ignore[reportPrivateUsage]


def _blas_threads() -> int:
    return min(
        pool["num_threads"] for pool in threadpool_info() if pool["user_api"] == "blas"
    )


def test_blas_threads_are_limited_during_analysis_and_then_restored(
    tmp_path: Path,
) -> None:
    import numpy as np

    np.dot(np.ones((2, 2)), np.ones((2, 2)))  # Load NumPy's BLAS before inspecting it.
    before = _blas_threads()
    root, _, session, snapshot = _device(tmp_path)
    snapshot = _with_device_tracks(root, snapshot, (2, 3))
    observed: list[int] = []

    def profile(
        pcm: bytes, *, sample_rate_hz: int, checkpoint: Callable[[], None]
    ) -> GeniusAudioProfile:
        observed.append(_blas_threads())
        return _profile(pcm, sample_rate_hz=sample_rate_hz, checkpoint=checkpoint)

    GeniusAnalysisService(decoder=_Decoder(), profiler=profile, workers=2).analyze(
        snapshot, session, checkpoint=_checkpoint
    )
    assert observed == [1] * 3
    assert _blas_threads() == before


def test_skip_requested_from_admission_progress_starts_no_reads(
    tmp_path: Path,
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    snapshot = _with_device_tracks(root, snapshot, (2,))
    snapshot, media = _with_staged_tracks(tmp_path, snapshot, (3,))
    skip = Event()
    decoding = Event()

    class SignallingDecoder(_Decoder):
        def decode(
            self,
            source: HostPath | DevicePath,
            *,
            input_suffix: str,
            session: FilesystemSession,
            checkpoint: Callable[[], None],
        ) -> bytes:
            decoding.set()
            return super().decode(
                source,
                input_suffix=input_suffix,
                session=session,
                checkpoint=checkpoint,
            )

    def progress(value: GeniusAnalysisProgress) -> None:
        assert value.completed == 0
        assert len(value.active) == 3
        # Admitted Tracks must not start before their progress is reported.
        assert not decoding.wait(0.3)
        skip.set()

    decoder = SignallingDecoder()
    result = GeniusAnalysisService(
        decoder=decoder, profiler=_profile, workers=4
    ).analyze(
        snapshot,
        session,
        media=media,
        checkpoint=_checkpoint,
        progress=progress,
        skip_requested=skip.is_set,
    )
    assert decoder.sources == []
    assert dict(result.profiles) == {}
    assert not result.issues


def test_skip_stops_active_and_waiting_work_and_keeps_completed_profiles(
    tmp_path: Path,
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    tracks = [snapshot.tracks[0]]
    for track_id in (2, 3):
        name = f"song-{track_id}.mp3"
        (root / name).write_bytes(b"audio")
        tracks.append(
            replace(
                tracks[0],
                track_id=track_id,
                metadata=TrackMetadata(location=name),
                ipod=IPodTrackDetails(db_track_id=100 + track_id),
            )
        )
    snapshot = replace(snapshot, tracks=tuple(tracks))
    skip = Event()
    peer_started = Event()
    peer_stopped = Event()

    class SkippableDecoder(_Decoder):
        def decode(
            self,
            source: HostPath | DevicePath,
            *,
            input_suffix: str,
            session: FilesystemSession,
            checkpoint: Callable[[], None],
        ) -> bytes:
            self.sources.append(source)
            if source == DevicePath("song.mp3"):
                assert peer_started.wait(5)
                return b"\x01\x00\x00\x00"
            peer_started.set()
            try:
                assert skip.wait(5)
                checkpoint()
                pytest.fail("Skipped audio decoding should stop at its checkpoint")
            finally:
                peer_stopped.set()

    decoder = SkippableDecoder()
    cache = AtomicHostFile(tmp_path / "profiles.json")

    def progress(value: GeniusAnalysisProgress) -> None:
        if value.completed == 1:
            skip.set()

    result = GeniusAnalysisService(cache, decoder, profiler=_profile).analyze(
        snapshot,
        session,
        checkpoint=_checkpoint,
        progress=progress,
        skip_requested=skip.is_set,
    )
    assert peer_stopped.is_set()
    assert tuple(result.profiles) == (1,)
    assert not result.issues
    assert set(decoder.sources) == {
        DevicePath("song.mp3"),
        DevicePath("song-2.mp3"),
    }
    retry_decoder = _Decoder()
    retried = GeniusAnalysisService(cache, retry_decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=_checkpoint
    )
    assert tuple(retried.profiles) == (1, 2, 3)
    assert set(retry_decoder.sources) == {
        DevicePath("song-2.mp3"),
        DevicePath("song-3.mp3"),
    }


@pytest.mark.parametrize("failure", ["cancel", "source_change"])
def test_skip_does_not_hide_cancellation_or_changed_sources(
    tmp_path: Path, failure: str
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    skip = Event()
    cancelled = Event()

    def action() -> None:
        skip.set()
        if failure == "cancel":
            cancelled.set()
        else:
            (root / "song.mp3").write_bytes(b"changed source")

    def checkpoint() -> None:
        if cancelled.is_set():
            raise PreparationCancelledError

    with pytest.raises(
        PreparationCancelledError
        if failure == "cancel"
        else ConcurrentModificationError
    ):
        GeniusAnalysisService(decoder=_Decoder(action), profiler=_profile).analyze(
            snapshot, session, checkpoint=checkpoint, skip_requested=skip.is_set
        )


def test_concurrent_source_change_stops_peer_and_rejects_profiles(
    tmp_path: Path,
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    (root / "second.mp3").write_bytes(b"second")
    snapshot = replace(
        snapshot,
        tracks=(
            *snapshot.tracks,
            replace(
                snapshot.tracks[0],
                track_id=2,
                metadata=TrackMetadata(location="second.mp3"),
                ipod=IPodTrackDetails(db_track_id=102),
            ),
        ),
    )
    peer_started = Event()
    peer_stopped = Event()

    class ChangingDecoder:
        def decode(
            self,
            source: HostPath | DevicePath,
            *,
            input_suffix: str,
            session: FilesystemSession,
            checkpoint: Callable[[], None],
        ) -> bytes:
            assert input_suffix == ".mp3"
            if source == DevicePath("song.mp3"):
                assert peer_started.wait(5)
                (root / "song.mp3").write_bytes(b"changed")
                return b"\x01\x00\x00\x00"
            peer_started.set()
            try:
                while True:
                    checkpoint()
                    if peer_stopped.wait(0.01):
                        raise AssertionError("Peer ran after analysis returned")
            finally:
                peer_stopped.set()

    service = GeniusAnalysisService(decoder=ChangingDecoder(), profiler=_profile)
    with pytest.raises(ConcurrentModificationError):
        service.analyze(snapshot, session, checkpoint=_checkpoint)
    assert peer_stopped.is_set()


@pytest.mark.parametrize(
    "mutation", ["checksum", "version", "shape", "nan", "duplicate"]
)
def test_cache_rejects_invalid_profiles(tmp_path: Path, mutation: str) -> None:
    file = AtomicHostFile(tmp_path / "cache.json")
    cache = GeniusProfileCache(file)
    cache.remember("a" * 64, GeniusAudioProfile(2, None, (0.0,) * 29, None))
    cache.save(_checkpoint, force=True)
    payload = file.read_bytes()
    assert payload is not None
    document = json.loads(payload)
    if mutation == "checksum":
        document["sha256"] = "0" * 64
    elif mutation == "version":
        document["analysis_version"] += 1
    else:
        if mutation == "shape":
            document["records"][0][3].pop()
        elif mutation == "nan":
            document["records"][0][3][0] = float("nan")
        else:
            document["records"] *= 2
        import hashlib

        document["sha256"] = hashlib.sha256(
            json.dumps(
                document["records"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    file.replace_bytes(json.dumps(document).encode())
    with pytest.raises(ValueError):
        GeniusProfileCache(file).load(_checkpoint)


def test_cache_bounds_records_and_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = AtomicHostFile(tmp_path / "cache.json")
    monkeypatch.setattr(genius_analysis_cache, "_MAX_RECORDS", 2)
    cache = GeniusProfileCache(file)
    profile = GeniusAudioProfile(2, None, (0.0,) * 29, None)
    for character in "abc":
        cache.remember(character * 64, profile)
    cache.save(_checkpoint, force=True)
    restored = GeniusProfileCache(file)
    restored.load(_checkpoint)
    assert restored.get("a" * 64) is None
    assert restored.get("b" * 64) == profile
    monkeypatch.setattr(genius_analysis_cache, "_MAX_BYTES", 128)
    with pytest.raises(StorageOperationError, match="read size limit"):
        GeniusProfileCache(file).load(_checkpoint)


def test_cache_byte_budget_evicts_old_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_analysis_cache, "_MAX_BYTES", 1500)
    file = AtomicHostFile(tmp_path / "cache.json")
    cache = GeniusProfileCache(file)
    profile = GeniusAudioProfile(2, None, (0.0,) * 29, None)
    for character in "abc":
        cache.remember(character * 64, profile)
    cache.save(_checkpoint, force=True)
    payload = file.read_bytes()
    assert payload is not None and len(payload) <= 1500
    restored = GeniusProfileCache(file)
    restored.load(_checkpoint)
    assert restored.get("a" * 64) is None
    assert restored.get("c" * 64) == profile


def test_missing_ffmpeg_is_looked_up_once_per_run_and_retried_later(
    tmp_path: Path,
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    (root / "second.mp3").write_bytes(b"second")
    snapshot = replace(
        snapshot,
        tracks=(
            *snapshot.tracks,
            replace(
                snapshot.tracks[0],
                track_id=2,
                metadata=TrackMetadata(location="second.mp3"),
            ),
        ),
    )
    lookups: list[str] = []

    def missing(name: str) -> None:
        lookups.append(name)

    service = GeniusAnalysisService(decoder=FFmpegGeniusPCMDecoder(find_tool=missing))
    for count in (1, 2):
        result = service.analyze(snapshot, session, checkpoint=_checkpoint)
        assert not result.profiles
        assert len(result.issues) == 2
        assert lookups == ["ffmpeg"] * count


def test_noop_cache_lookup_still_checks_cancellation(tmp_path: Path) -> None:
    _, _, session, snapshot = _device(tmp_path)
    service = GeniusAnalysisService(decoder=_Decoder(), profiler=_profile)
    service.analyze(snapshot, session, checkpoint=_checkpoint)

    def cancelled() -> None:
        raise PreparationCancelledError

    with pytest.raises(PreparationCancelledError):
        service.analyze(snapshot, session, checkpoint=cancelled)


def test_ffmpeg_decodes_pinned_device_audio_with_bounded_output(tmp_path: Path) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpeg is not installed")
    root, _, session, _ = _device(tmp_path)
    with wave.open(str(root / "source.wav"), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22_050)
        output.writeframes(b"\x00\x00" * 22_050)
    decoder = FFmpegGeniusPCMDecoder(find_tool=lambda _: HostPath(Path(executable)))
    pcm = decoder.decode(
        DevicePath("source.wav"),
        input_suffix=".wav",
        session=session,
        checkpoint=_checkpoint,
    )
    assert len(pcm) == 22_050 * 4
    assert not any(pcm)
