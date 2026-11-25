"""Keep the ADR-0274 benchmark read-only and its two modes distinct."""

from __future__ import annotations

from threading import Barrier, Lock
from typing import TYPE_CHECKING

import pytest
from scripts import benchmark_genius_device_reads as benchmark

from iOpenPod.app import genius_analysis
from iOpenPod.app.genius_audio import GeniusAudioProfile
from storage import DevicePath, Storage
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from storage import FilesystemSession, HostPath


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
        assert isinstance(source, DevicePath)
        assert input_suffix == ".mp3"
        checkpoint()
        with self._lock:
            self._reading += 1
            self.most_at_once = max(self.most_at_once, self._reading)
        try:
            if self._together is not None:
                self._together.wait(timeout=10)
            assert session.read(source).startswith(b"audio")
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


def _storage(mount: Path) -> Storage:
    platform = VirtualStoragePlatform()
    platform.add_volume(mount, writable=False)
    return Storage(platform)


def test_one_device_reader_matches_the_application_and_leaves_the_ipod_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mount = _ipod(tmp_path)
    before = _contents(mount)
    decoder = _Decoder()

    def unexpected_host_lookup(*args: object, **kwargs: object) -> None:
        pytest.fail("Device benchmark must not look up committed Host counterparts")

    monkeypatch.setattr(
        genius_analysis, "committed_genius_sources", unexpected_host_lookup
    )
    storage = _storage(mount)
    with storage.open_session(storage.inspect(mount)) as session:
        result = benchmark.run(
            session,
            tracks=4,
            seed=7,
            device_readers=1,
            decoder=decoder,
            profiler=_profile,
        )

    assert (result.tracks, result.analyzed, result.unavailable) == (4, 4, 0)
    assert result.sample_megabytes == pytest.approx(50 / 1_000_000)
    assert decoder.most_at_once == 1
    assert _contents(mount) == before


def test_two_device_readers_read_together(tmp_path: Path) -> None:
    mount = _ipod(tmp_path)
    decoder = _Decoder(Barrier(2))

    storage = _storage(mount)
    with storage.open_session(storage.inspect(mount)) as session:
        result = benchmark.run(
            session,
            tracks=4,
            seed=7,
            device_readers=2,
            decoder=decoder,
            profiler=_profile,
        )

    assert result.analyzed == 4
    assert decoder.most_at_once == 2


def test_sample_is_repeatable_and_bounded_by_the_music_available(
    tmp_path: Path,
) -> None:
    mount = _ipod(tmp_path, count=6)

    storage = _storage(mount)
    with storage.open_session(storage.inspect(mount)) as session:
        first = benchmark.sample_music(session, 3, seed=7)

        assert first == benchmark.sample_music(session, 3, seed=7)
        assert len({entry.path for entry in first}) == 3
        assert all(entry.path.name.endswith(".mp3") for entry in first)
        with pytest.raises(ValueError, match="Only 6 Music files"):
            benchmark.sample_music(session, 7, seed=7)
        with pytest.raises(ValueError, match="Track count must be positive"):
            benchmark.sample_music(session, 0, seed=7)


def test_sample_ignores_linked_music(tmp_path: Path) -> None:
    mount = _ipod(tmp_path, count=1)
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"outside the iPod")
    try:
        (mount / "iPod_Control" / "Music" / "linked.mp3").symlink_to(outside)
    except OSError as error:
        pytest.skip(f"Host cannot create symlinks: {error}")

    storage = _storage(mount)
    with storage.open_session(storage.inspect(mount)) as session:
        sample = benchmark.sample_music(session, 1, seed=7)
        assert sample[0].path == DevicePath("iPod_Control/Music/F00/T000.mp3")
        with pytest.raises(ValueError, match="Only 1 Music files"):
            benchmark.sample_music(session, 2, seed=7)


def test_cli_fails_when_no_sampled_track_can_be_analyzed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mount = _ipod(tmp_path, count=1)
    monkeypatch.setattr(benchmark, "Storage", lambda: _storage(mount))

    with pytest.raises(SystemExit) as exit_info:
        benchmark.main([str(mount), "--tracks", "1"])

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "No Tracks analyzed" in captured.err
    assert captured.out == ""
