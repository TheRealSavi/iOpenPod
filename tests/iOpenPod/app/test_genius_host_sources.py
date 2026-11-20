"""Correlated Host audio avoids device transport without weakening source checks."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock

import pytest
from tests.iOpenPod.app.test_genius_analysis import (
    _device,  # pyright: ignore[reportPrivateUsage]
    _profile,  # pyright: ignore[reportPrivateUsage]
    _with_device_tracks,  # pyright: ignore[reportPrivateUsage]
    _with_staged_tracks,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app import library_sync_helper
from iOpenPod.app.genius_analysis import (
    GeniusAnalysisService,
    GeniusAudioDecodeError,
    GeniusHostDependency,
)
from iOpenPod.app.genius_host_sources import GeniusHostSource
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    IPodTrackFingerprint,
    SyncDetails,
)
from iPodDB.library import FileDependency, LibrarySnapshot, PreparedLyrics
from storage import (
    AtomicHostFile,
    ConcurrentModificationError,
    DevicePath,
    FilesystemSession,
    HostPath,
)
from storage.host_input import LocalHostFile


def checkpoint() -> None:
    pass


def device(
    tmp_path: Path, count: int = 1
) -> tuple[Path, FilesystemSession, LibrarySnapshot]:
    root, _, session, snapshot = _device(tmp_path)
    snapshot = _with_device_tracks(root, snapshot, tuple(range(2, count + 1)))
    directory = root / "iPod_Control/Music/F00"
    directory.mkdir(parents=True)
    for track in snapshot.tracks:
        (directory / track.metadata.location).write_bytes(b"device audio")
    return (
        root,
        session,
        replace(
            snapshot,
            tracks=tuple(
                replace(
                    t,
                    metadata=replace(
                        t.metadata,
                        location=f"iPod_Control/Music/F00/{t.metadata.location}",
                    ),
                )
                for t in snapshot.tracks
            ),
        ),
    )


class Decoder:
    def __init__(
        self, *, fail_host: bool = False, action: Callable[[], None] = checkpoint
    ) -> None:
        self.calls: list[tuple[HostPath | DevicePath, str]] = []
        self.fail_host = fail_host
        self.action = action

    def decode(
        self,
        source: HostPath | DevicePath,
        *,
        input_suffix: str,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes:
        checkpoint()
        self.calls.append((source, input_suffix))
        self.action()
        if self.fail_host and isinstance(source, HostPath):
            raise GeniusAudioDecodeError("Optional Host decoder unavailable")
        return b"\x01\x00\x00\x00"


def correlation(
    session: FilesystemSession, snapshot: LibrarySnapshot, host: Path, index: int = 0
) -> GeniusHostSource:
    track = snapshot.tracks[index]
    assert track.ipod is not None
    path = DevicePath(track.metadata.location)
    device = session.file_identity(path)
    local = LocalHostFile.observe(HostPath(host))
    record = IPodTrackFingerprint(
        track.ipod.db_track_id,
        track.track_id,
        path,
        device.size,
        device.modified_ns,
        "1,2,3",
        SyncDetails(
            "2026-11-18",
            str(local.path),
            local.size_bytes,
            local.modified_ns,
            host.suffix.lstrip("."),
            "mp3",
            True,
        ),
    )
    return GeniusHostSource(record, local.path, local.size_bytes, local.modified_ns)


def write_helper(root: Path, sources: tuple[GeniusHostSource, ...]) -> None:
    path = root / str(LIBRARY_SYNC_HELPER_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        library_sync_helper._encode_helper(  # pyright: ignore[reportPrivateUsage]
            tuple(s.device for s in sources), (), "a" * 64, updated_at="2026-11-18"
        )
    )


@pytest.mark.parametrize("committed", (False, True))
def test_correlated_original_uses_host_extension_and_persistent_profile_cache(
    tmp_path: Path, committed: bool
) -> None:
    root, session, snapshot = device(tmp_path)
    host = tmp_path / "original.flac"
    host.write_bytes(b"original lossless audio")
    source = correlation(session, snapshot, host)
    if committed:
        write_helper(root, (source,))
    sources = () if committed else (source,)
    cache = AtomicHostFile(tmp_path / "profiles.json")
    decoder = Decoder()
    result = GeniusAnalysisService(cache, decoder, profiler=_profile).analyze(
        snapshot, session, host_sources=sources, checkpoint=checkpoint
    )
    assert decoder.calls == [(HostPath(host), ".flac")]
    assert not result.issues and tuple(result.profiles) == (1,)
    assert result.dependencies[0].path == DevicePath("iPod_Control/Music/F00/song.mp3")
    assert result.host_dependencies == (
        GeniusHostDependency(1, LocalHostFile.observe(HostPath(host))),
    )
    repeated = GeniusAnalysisService(cache, decoder, profiler=_profile).analyze(
        snapshot, session, host_sources=sources, checkpoint=checkpoint
    )
    assert repeated.profiles == result.profiles
    assert len(decoder.calls) == 1
    host.unlink()
    GeniusAnalysisService(cache, decoder, profiler=_profile).analyze(
        snapshot, session, host_sources=sources, checkpoint=checkpoint
    )
    assert decoder.calls[-1] == (DevicePath("iPod_Control/Music/F00/song.mp3"), ".mp3")


@pytest.mark.parametrize(
    "stale",
    (
        "host_size",
        "host_mtime",
        "device_size",
        "device_mtime",
        "persistent_id",
        "device_path",
        "stream",
        "corrupt",
        "missing",
        "extension",
    ),
)
def test_unusable_committed_correlations_fall_back_to_device(
    tmp_path: Path, stale: str
) -> None:
    root, session, snapshot = device(tmp_path)
    host = tmp_path / (
        "original.unsupported" if stale == "extension" else "original.flac"
    )
    host.write_bytes(b"original audio")
    source = correlation(session, snapshot, host)
    record = source.device
    assert record.sync is not None
    sync = record.sync
    if stale == "host_size":
        record = replace(
            record, sync=replace(sync, host_size_bytes=sync.host_size_bytes + 1)
        )
    elif stale == "host_mtime":
        record = replace(
            record, sync=replace(sync, host_modified_ns=sync.host_modified_ns - 1)
        )
    elif stale == "device_size":
        record = replace(record, size_bytes=record.size_bytes + 1)
    elif stale == "device_mtime":
        record = replace(record, modified_ns=record.modified_ns - 60_000_000_000)
    elif stale == "persistent_id":
        record = replace(record, database_track_id=999)
    elif stale == "device_path":
        record = replace(record, path=DevicePath("other.mp3"))
    elif stale == "stream":
        record = replace(record, sync=replace(sync, stream_selection_sha256="f" * 64))
    write_helper(root, (replace(source, device=record),))
    if stale == "corrupt":
        (root / str(LIBRARY_SYNC_HELPER_PATH)).write_bytes(b"invalid")
    if stale == "missing":
        host.unlink()
    decoder = Decoder()
    result = GeniusAnalysisService(decoder=decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=checkpoint
    )
    assert decoder.calls == [(DevicePath("iPod_Control/Music/F00/song.mp3"), ".mp3")]
    assert result.profiles and not result.host_dependencies


def test_host_decode_failure_retries_device_without_caching_wrong_source(
    tmp_path: Path,
) -> None:
    root, session, snapshot = device(tmp_path)
    host = tmp_path / "original.flac"
    host.write_bytes(b"audio")
    write_helper(root, (correlation(session, snapshot, host),))
    decoder = Decoder(fail_host=True)
    result = GeniusAnalysisService(decoder=decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=checkpoint
    )
    assert decoder.calls == [
        (HostPath(host), ".flac"),
        (DevicePath("iPod_Control/Music/F00/song.mp3"), ".mp3"),
    ]
    assert result.profiles and not result.issues and not result.host_dependencies


def test_prepared_replacement_takes_priority_over_previous_host_correlation(
    tmp_path: Path,
) -> None:
    root, session, snapshot = device(tmp_path)
    old = tmp_path / "old.flac"
    old.write_bytes(b"old audio")
    source = correlation(session, snapshot, old)
    write_helper(root, (source,))
    staged, media = _with_staged_tracks(tmp_path, snapshot, (2,))
    replacement = replace(media[0], media=replace(media[0].media, track_id=1))
    desired = replace(snapshot, tracks=(replace(staged.tracks[-1], track_id=1),))
    decoder = Decoder()
    result = GeniusAnalysisService(decoder=decoder, profiler=_profile).analyze(
        desired,
        session,
        media=(replacement,),
        host_sources=(source,),
        checkpoint=checkpoint,
    )
    assert decoder.calls == [(replacement.source, ".mp3")]
    assert result.prepared_profiles and not result.host_dependencies


def test_valid_device_profile_needs_no_host_lookup_or_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iOpenPod.app import genius_analysis

    _, session, snapshot = device(tmp_path)
    decoder = Decoder()
    service = GeniusAnalysisService(decoder=decoder, profiler=_profile)
    service.analyze(snapshot, session, checkpoint=checkpoint)

    def unexpected_lookup(*args: object, **kwargs: object) -> None:
        pytest.fail("Warm device profiles should not read the correlation helper")

    monkeypatch.setattr(genius_analysis, "committed_genius_sources", unexpected_lookup)
    result = service.analyze(snapshot, session, checkpoint=checkpoint)
    assert len(decoder.calls) == 1 and result.profiles


@pytest.mark.parametrize("correlated", (False, True))
def test_retagging_only_associates_profiles_of_the_device_encoding(
    tmp_path: Path, correlated: bool
) -> None:
    root, session, snapshot = device(tmp_path)
    if correlated:
        host = tmp_path / "original.flac"
        host.write_bytes(b"lossless audio")
        write_helper(root, (correlation(session, snapshot, host),))
    service = GeniusAnalysisService(decoder=Decoder(), profiler=_profile)
    result = service.analyze(snapshot, session, checkpoint=checkpoint)
    path = snapshot.tracks[0].metadata.location
    tagged = result.with_tagged_media(
        (PreparedLyrics(1, "lyrics", FileDependency(path, 128, "a" * 64)),)
    )
    assert bool(tagged.prepared_profiles) is not correlated
    assert tagged.host_dependencies == result.host_dependencies


@pytest.mark.parametrize(
    "when", ("during_host", "during_device", "after_host", "after_device")
)
def test_host_and_device_remain_dependencies_through_publication(
    tmp_path: Path, when: str
) -> None:
    root, session, snapshot = device(tmp_path)
    host = tmp_path / "original.flac"
    host.write_bytes(b"audio")
    write_helper(root, (correlation(session, snapshot, host),))
    target = host if when.endswith("host") else root / "iPod_Control/Music/F00/song.mp3"

    def mutate() -> None:
        target.write_bytes(b"changed audio")

    decoder = Decoder(action=mutate if when.startswith("during") else checkpoint)
    service = GeniusAnalysisService(decoder=decoder, profiler=_profile)
    if when.startswith("during"):
        with pytest.raises(ConcurrentModificationError):
            service.analyze(snapshot, session, checkpoint=checkpoint)
    else:
        result = service.analyze(snapshot, session, checkpoint=checkpoint)
        mutate()
        with pytest.raises(ConcurrentModificationError):
            result.validate_sources(session, checkpoint=checkpoint)


def test_correlated_host_audio_uses_all_six_workers(tmp_path: Path) -> None:
    root, session, snapshot = device(tmp_path, 6)
    sources: list[GeniusHostSource] = []
    for index in range(6):
        host = tmp_path / f"original-{index}.mp3"
        host.write_bytes(b"audio")
        sources.append(correlation(session, snapshot, host, index))
    write_helper(root, tuple(sources))
    started = Event()
    release = Event()
    lock = Lock()
    count = 0

    def hold() -> None:
        nonlocal count
        with lock:
            count += 1
            if count == 6:
                started.set()
        assert release.wait(5)

    decoder = Decoder(action=hold)
    service = GeniusAnalysisService(decoder=decoder, profiler=_profile, workers=6)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            service.analyze, snapshot, session, checkpoint=checkpoint
        )
        try:
            assert started.wait(5), "Host counterparts were limited by device admission"
        finally:
            release.set()
        result = future.result(timeout=5)
    assert len(result.profiles) == 6
    assert all(isinstance(path, HostPath) for path, _ in decoder.calls)
