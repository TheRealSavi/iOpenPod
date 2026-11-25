"""Time cold Genius analysis of device Tracks with one or two device readers.

Measures ADR-0274 in isolation. A fixed, seeded sample of the Music files on a
mounted iPod is analyzed with the real decoder and profiler and no profile cache.
``--device-readers 1`` is the application's behavior; ``--device-readers 2``
removes the single device read so both in-flight device Tracks read at once.

The iPod is opened through a read-only Filesystem Session; nothing is written to
it. Compare runs of the same sample, alternating the two modes, for example::

    uv run python -m scripts.benchmark_genius_device_reads MOUNT --device-readers 2
    uv run python -m scripts.benchmark_genius_device_reads MOUNT --device-readers 1

The script requests page cache eviction where supported. Reconnect the iPod
before each run if you need to start with a cold Host page cache.
"""

from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from iOpenPod.app.genius_analysis import GeniusAnalysisService
from iPodDB.library import IPodTrackDetails, LibrarySnapshot, Track, TrackMetadata
from storage import AccessMode, DeviceEntryKind, DevicePath, Storage, StorageError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from iOpenPod.app.genius_analysis import GeniusPCMDecoder, GeniusProfiler
    from storage import DeviceEntry, FilesystemSession

_MUSIC_DIRECTORY = DevicePath("iPod_Control/Music")
_MUSIC_SUFFIXES = frozenset({".m4a", ".mp3"})
_MEGABYTE = 1_000_000


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    tracks: int
    sample_megabytes: float
    seconds: float
    analyzed: int
    unavailable: int
    device_readers: int
    cache_eviction_requested: bool

    @property
    def sample_megabytes_per_second(self) -> float:
        return self.sample_megabytes / self.seconds


def sample_music(
    session: FilesystemSession, count: int, seed: int
) -> tuple[DeviceEntry, ...]:
    """Return a repeatable sample of the iPod's Music files in path order."""
    if count < 1:
        raise ValueError("Track count must be positive")
    directories = [_MUSIC_DIRECTORY]
    files: list[DeviceEntry] = []
    while directories:
        for entry in session.list_directory(directories.pop()):
            if entry.kind is DeviceEntryKind.DIRECTORY:
                directories.append(entry.path)
            elif (
                entry.kind is DeviceEntryKind.FILE
                and PurePosixPath(entry.path.name).suffix.casefold() in _MUSIC_SUFFIXES
            ):
                files.append(entry)
    files.sort(key=lambda entry: entry.path.parts)
    if count > len(files):
        raise ValueError(f"Only {len(files)} Music files are available")
    selected = random.Random(seed).sample(files, count)
    return tuple(sorted(selected, key=lambda entry: entry.path.parts))


def run(
    session: FilesystemSession,
    *,
    tracks: int,
    seed: int,
    device_readers: int,
    decoder: GeniusPCMDecoder | None = None,
    profiler: GeniusProfiler | None = None,
) -> BenchmarkResult:
    if device_readers not in (1, 2):
        raise ValueError("Device readers must be 1 or 2")
    sample = sample_music(session, tracks, seed)
    sample_megabytes = sum(entry.size for entry in sample) / _MEGABYTE
    cache_eviction_requested = True
    for entry in sample:
        if not session.request_page_cache_eviction(entry.path):
            cache_eviction_requested = False
    snapshot = LibrarySnapshot(
        tuple(
            Track(
                index,
                PurePosixPath(entry.path.name).stem,
                "Artist",
                "Album",
                200_000,
                metadata=TrackMetadata(location=str(entry.path)),
                ipod=IPodTrackDetails(db_track_id=1_000 + index),
            )
            for index, entry in enumerate(sample, start=1)
        )
    )
    service = GeniusAnalysisService(
        decoder=decoder,
        profiler=profiler,
        workers=6,
        serialize_device_reads=device_readers == 1,
    )
    started = time.perf_counter()
    result = service.analyze(
        snapshot, session, checkpoint=lambda: None, use_committed_host_sources=False
    )
    seconds = time.perf_counter() - started
    if not result.profiles:
        detail = result.issues[0].detail if result.issues else "No profiles returned"
        raise ValueError(f"No Tracks analyzed: {detail}")
    return BenchmarkResult(
        tracks=tracks,
        sample_megabytes=sample_megabytes,
        seconds=seconds,
        analyzed=len(result.profiles),
        unavailable=len(result.issues),
        device_readers=device_readers,
        cache_eviction_requested=cache_eviction_requested,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mount", type=Path, help="mount point of the iPod")
    parser.add_argument("--tracks", type=int, default=128)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device-readers", type=int, choices=(1, 2), default=1)
    arguments = parser.parse_args(argv)
    storage = Storage()
    try:
        volume = storage.inspect(arguments.mount.absolute())
        with storage.open_session(volume, access=AccessMode.READ_ONLY) as session:
            result = run(
                session,
                tracks=arguments.tracks,
                seed=arguments.seed,
                device_readers=arguments.device_readers,
            )
    except (OSError, StorageError, ValueError) as error:
        parser.exit(1, f"Benchmark failed: {error}\n")
    print(
        f"device_readers={result.device_readers} tracks={result.tracks} "
        f"sample_megabytes={result.sample_megabytes:.2f} seconds={result.seconds:.1f} "
        f"sample_megabytes_per_second={result.sample_megabytes_per_second:.2f} "
        f"analyzed={result.analyzed} unavailable={result.unavailable} "
        f"page_cache_eviction_requested={result.cache_eviction_requested}"
    )
    if not result.cache_eviction_requested:
        print(
            "Reconnect the iPod before each run to start with a cold Host page cache."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
