"""Time cold Genius analysis of device Tracks with one or two device readers.

Measures ADR-0274 in isolation. A fixed, seeded sample of the Music files on a
mounted iPod is analyzed with the real decoder and profiler and no profile cache.
``--device-readers 1`` is the application's behavior; ``--device-readers 2``
removes the single device read so both in-flight device Tracks read at once.

The iPod is opened through a read-only Filesystem Session; nothing is written to
it. Compare runs of the same sample, alternating the two modes, for example::

    uv run python -m scripts.benchmark_genius_device_reads MOUNT --device-readers 2
    uv run python -m scripts.benchmark_genius_device_reads MOUNT --device-readers 1

Where the Host cannot evict files from its page cache, reconnect the iPod before
each run so every read is cold.
"""

from __future__ import annotations

import argparse
import os
import random
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from iOpenPod.app import genius_analysis
from iOpenPod.app.genius_analysis import GeniusAnalysisService
from iPodDB.library import IPodTrackDetails, LibrarySnapshot, Track, TrackMetadata
from storage import AccessMode, Storage
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence
    from threading import Lock

    from iOpenPod.app.genius_analysis import GeniusPCMDecoder, GeniusProfiler

_MUSIC_SUFFIXES = frozenset({".m4a", ".mp3"})
_MEGABYTE = 1_000_000


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    tracks: int
    megabytes: float
    seconds: float
    analyzed: int
    unavailable: int
    device_readers: int
    evicted: bool

    @property
    def megabytes_per_second(self) -> float:
        return self.megabytes / self.seconds if self.seconds else 0.0


def sample_music(mount: Path, count: int, seed: int) -> tuple[Path, ...]:
    """Return a repeatable sample of the iPod's Music files in path order."""
    music = mount / "iPod_Control" / "Music"
    files = sorted(
        path
        for path in music.rglob("*")
        if path.is_file() and path.suffix.casefold() in _MUSIC_SUFFIXES
    )
    if count > len(files):
        raise ValueError(f"Only {len(files)} Music files are available")
    return tuple(sorted(random.Random(seed).sample(files, count)))


def evict_from_page_cache(paths: Sequence[Path]) -> bool:
    """Ask the Host to drop cached pages; report whether it is supported."""
    advise = getattr(os, "posix_fadvise", None)
    dont_need = getattr(os, "POSIX_FADV_DONTNEED", None)
    if advise is None or dont_need is None:
        return False
    for path in paths:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            advise(descriptor, 0, 0, dont_need)
        finally:
            os.close(descriptor)
    return True


@contextmanager
def _unserialized_device_read(
    lock: Lock, checkpoint: Callable[[], None]
) -> Generator[None]:
    """Stand in for the device read slot without taking it."""
    del lock
    checkpoint()
    yield


@contextmanager
def _device_readers(count: int) -> Generator[None]:
    """Run with the application's single device read, or with it removed."""
    if count == 1:
        yield
        return
    original = genius_analysis._holding
    genius_analysis._holding = _unserialized_device_read
    try:
        yield
    finally:
        genius_analysis._holding = original


def run(
    mount: Path,
    *,
    tracks: int,
    seed: int,
    device_readers: int,
    decoder: GeniusPCMDecoder | None = None,
    profiler: GeniusProfiler | None = None,
) -> BenchmarkResult:
    if device_readers not in (1, 2):
        raise ValueError("Device readers must be 1 or 2")
    mount = mount.resolve(strict=True)
    sample = sample_music(mount, tracks, seed)
    megabytes = sum(path.stat().st_size for path in sample) / _MEGABYTE
    evicted = evict_from_page_cache(sample)
    snapshot = LibrarySnapshot(
        tuple(
            Track(
                index,
                path.stem,
                "Artist",
                "Album",
                200_000,
                metadata=TrackMetadata(location=path.relative_to(mount).as_posix()),
                ipod=IPodTrackDetails(db_track_id=1_000 + index),
            )
            for index, path in enumerate(sample, start=1)
        )
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(mount, writable=False)
    with tempfile.TemporaryDirectory() as locks:
        storage = Storage(platform, writer_lock_directory=Path(locks))
        session = storage.open_session(
            storage.discover().volumes[0], access=AccessMode.READ_ONLY
        )
        service = GeniusAnalysisService(decoder=decoder, profiler=profiler)
        with _device_readers(device_readers):
            started = time.perf_counter()
            result = service.analyze(snapshot, session, checkpoint=lambda: None)
            seconds = time.perf_counter() - started
    return BenchmarkResult(
        tracks=tracks,
        megabytes=megabytes,
        seconds=seconds,
        analyzed=len(result.profiles),
        unavailable=len(result.issues),
        device_readers=device_readers,
        evicted=evicted,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mount", type=Path, help="mount point of the iPod")
    parser.add_argument("--tracks", type=int, default=128)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device-readers", type=int, choices=(1, 2), default=1)
    arguments = parser.parse_args(argv)
    result = run(
        arguments.mount,
        tracks=arguments.tracks,
        seed=arguments.seed,
        device_readers=arguments.device_readers,
    )
    print(
        f"device_readers={result.device_readers} tracks={result.tracks} "
        f"megabytes={result.megabytes:.0f} seconds={result.seconds:.1f} "
        f"megabytes_per_second={result.megabytes_per_second:.2f} "
        f"analyzed={result.analyzed} unavailable={result.unavailable} "
        f"page_cache_evicted={result.evicted}"
    )
    if not result.evicted:
        print("Page cache was not evicted; reconnect the iPod before each run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
