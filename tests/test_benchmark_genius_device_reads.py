"""Keep the ADR-0274 benchmark read-only and its two modes distinct."""

from __future__ import annotations

from threading import Barrier, Lock
from typing import TYPE_CHECKING

import pytest
from scripts import benchmark_genius_device_reads as benchmark

from iOpenPod.app import genius_analysis
from iOpenPod.app.genius_audio import GeniusAudioProfile

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from storage import DevicePath, FilesystemSession, HostPath


def _profile(
    pcm: bytes, *, sample_rate_hz: int, checkpoint: Callable[[], None]
) -> GeniusAudioProfile:
    del sample_rate_hz
    checkpoint()
    return GeniusAudioProfile(2.0, None, (float(pcm[0]),) * 29, None)


class _Decoder:
    """Count concurrent device reads; optionally require two at once."""

    def __init__(self, together: Barrier | None = None) -> None:
        self._together = together
        self._lock = Lock()
        self._reading = 0
        self.most_at_once = 0

    def decode(
        self,
        source: HostPath | DevicePath,
        *,
        input_suffix: str,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes:
        del source, input_suffix, session
        checkpoint()
        with self._lock:
            self._reading += 1
            self.most_at_once = max(self.most_at_once, self._reading)
        try:
            if self._together is not None:
                self._together.wait(timeout=10)
        finally:
            with self._lock:
                self._reading -= 1
        return b"\x01\x00\x00\x00"


def _ipod(tmp_path: Path, count: int = 4) -> Path:
    music = tmp_path / "ipod" / "iPod_Control" / "Music" / "F00"
    music.mkdir(parents=True)
    for index in range(count):
        (music / f"T{index:03}.mp3").write_bytes(b"audio" * (index + 1))
    (music / "notes.txt").write_text("not music", encoding="utf-8")
    return tmp_path / "ipod"


def _contents(mount: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in mount.rglob("*") if path.is_file()}


def test_one_device_reader_matches_the_application_and_leaves_the_ipod_unchanged(
    tmp_path: Path,
) -> None:
    mount = _ipod(tmp_path)
    before = _contents(mount)
    decoder = _Decoder()

    result = benchmark.run(
        mount, tracks=4, seed=7, device_readers=1, decoder=decoder, profiler=_profile
    )

    assert (result.tracks, result.analyzed, result.unavailable) == (4, 4, 0)
    assert result.megabytes == pytest.approx(50 / 1_000_000)
    assert decoder.most_at_once == 1
    assert _contents(mount) == before


def test_two_device_readers_read_together_and_restore_the_application(
    tmp_path: Path,
) -> None:
    mount = _ipod(tmp_path)
    original = genius_analysis._holding
    decoder = _Decoder(Barrier(2))

    result = benchmark.run(
        mount, tracks=4, seed=7, device_readers=2, decoder=decoder, profiler=_profile
    )

    assert result.analyzed == 4
    assert decoder.most_at_once == 2
    assert genius_analysis._holding is original


def test_sample_is_repeatable_and_bounded_by_the_music_available(
    tmp_path: Path,
) -> None:
    mount = _ipod(tmp_path, count=6)

    first = benchmark.sample_music(mount, 3, seed=7)

    assert first == benchmark.sample_music(mount, 3, seed=7)
    assert len(set(first)) == 3
    assert all(path.suffix == ".mp3" for path in first)
    with pytest.raises(ValueError, match="Only 6 Music files"):
        benchmark.sample_music(mount, 7, seed=7)
