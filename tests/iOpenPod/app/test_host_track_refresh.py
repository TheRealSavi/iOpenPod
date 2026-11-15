"""Targeted Host tag refresh overlaps reads and reports cancellable progress."""

import threading
import wave
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app import host_media_library as media
from iOpenPod.app.host_media_controller import HostMediaScanController
from iOpenPod.app.host_media_library import (
    HostMediaLibrary,
    HostMediaScanCancelledError,
    HostMediaScanError,
    HostMediaScanner,
    HostMediaScanProgress,
)
from storage import AtomicHostFile, HostPath


class _Fingerprinter:
    def fingerprint(self, source: HostPath, *, checkpoint: Callable[[], None]) -> str:
        return "1,2,3"


@pytest.fixture
def scanned(tmp_path: Path) -> tuple[HostMediaScanner, HostMediaLibrary]:
    paths: list[HostPath] = []
    for index in range(12):
        path = tmp_path / f"{index:02d}.wav"
        with wave.open(str(path), "wb") as stream:
            stream.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            stream.writeframes(bytes(1600))
        paths.append(HostPath(path))
    scanner = HostMediaScanner(
        AtomicHostFile(tmp_path / "cache.json"), _Fingerprinter(), max_workers=2
    )
    pending = scanner.scan((), files=tuple(paths), checkpoint=lambda: None)
    return scanner, scanner.complete(pending, frozenset(), checkpoint=lambda: None)


def test_refresh_reports_later_completions_while_first_read_is_blocked(
    scanned: tuple[HostMediaScanner, HostMediaLibrary], monkeypatch: pytest.MonkeyPatch
) -> None:
    scanner, library = scanned
    released = threading.Event()
    owner = threading.get_ident()
    lock = threading.Lock()
    active = maximum = 0
    events: list[HostMediaScanProgress] = []
    original = media._inspect_track  # pyright: ignore[reportPrivateUsage]
    # Make every completed read eligible for progress without wall-clock sleeps.
    ticks = iter(range(1000))
    monkeypatch.setattr(media, "perf_counter", lambda: float(next(ticks)))

    def inspect(
        observation: media._Observation,  # pyright: ignore[reportPrivateUsage]
        artwork: media._ArtworkReference | None,  # pyright: ignore[reportPrivateUsage]
        *,
        checkpoint: Callable[[], None],
    ) -> media._CachedTrackRecord:  # pyright: ignore[reportPrivateUsage]
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            if observation.path.path.name == "00.wav":
                assert released.wait(5), "A slow first read hid later progress"
            return original(observation, artwork, checkpoint=checkpoint)
        finally:
            with lock:
                active -= 1

    def progress(event: HostMediaScanProgress) -> None:
        assert threading.get_ident() == owner
        events.append(event)
        if event.path is not None and event.path.path.name == "05.wav":
            released.set()

    monkeypatch.setattr(media, "_inspect_track", inspect)
    updated = scanner.refresh_tracks(
        library,
        frozenset(source.path for source in library.sources),
        checkpoint=lambda: None,
        progress=progress,
    )
    assert maximum == 2 and active == 0
    assert released.is_set()
    assert [event.completed for event in events] == list(range(13))
    assert all(
        event.total == 12 and event.stage.value == "refreshing" for event in events
    )
    assert events[-1].path is not None
    assert updated.snapshot == library.snapshot
    assert updated.sources == library.sources
    assert len(updated.rechecked_track_paths) == 12


@pytest.mark.parametrize("interruption", ["cancel", "read-error", "progress-error"])
def test_refresh_interruptions_join_workers_without_publishing_partial_cache(
    scanned: tuple[HostMediaScanner, HostMediaLibrary],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    scanner, library = scanned
    before = (tmp_path / "cache.json").read_bytes()
    started = threading.Event()
    stopped = threading.Event()
    cancelled = threading.Event()
    called: list[str] = []
    original = media._inspect_track  # pyright: ignore[reportPrivateUsage]

    def checkpoint() -> None:
        if cancelled.is_set():
            raise HostMediaScanCancelledError("Cancelled refresh")

    def inspect(
        observation: media._Observation,  # pyright: ignore[reportPrivateUsage]
        artwork: media._ArtworkReference | None,  # pyright: ignore[reportPrivateUsage]
        *,
        checkpoint: Callable[[], None],
    ) -> media._CachedTrackRecord:  # pyright: ignore[reportPrivateUsage]
        name = observation.path.path.name
        called.append(name)
        if name == "00.wav":
            assert started.wait(5), "Refresh reads did not overlap"
            if interruption == "read-error":
                raise OSError("Unreadable Track")
            return original(observation, artwork, checkpoint=checkpoint)
        started.set()
        try:
            for _ in range(500):
                checkpoint()
                if stopped.wait(0.01):
                    break
            pytest.fail("Refresh did not interrupt the running read")
        finally:
            stopped.set()

    def progress(event: HostMediaScanProgress) -> None:
        if event.completed:
            if interruption == "progress-error":
                raise RuntimeError("Progress consumer failed")
            cancelled.set()

    monkeypatch.setattr(media, "_inspect_track", inspect)
    expected = RuntimeError if interruption == "progress-error" else HostMediaScanError
    with pytest.raises(expected):
        scanner.refresh_tracks(
            library,
            frozenset(source.path for source in library.sources),
            checkpoint=checkpoint,
            progress=progress,
        )
    assert stopped.is_set()
    assert sorted(called) == ["00.wav", "01.wav"]
    assert (tmp_path / "cache.json").read_bytes() == before
    assert not library.rechecked_track_paths


def test_refresh_coalesces_fast_progress_but_keeps_exact_endpoints(
    scanned: tuple[HostMediaScanner, HostMediaLibrary], monkeypatch: pytest.MonkeyPatch
) -> None:
    scanner, library = scanned
    monkeypatch.setattr(media, "perf_counter", lambda: 0.0)
    events: list[HostMediaScanProgress] = []
    scanner.refresh_tracks(
        library,
        frozenset(source.path for source in library.sources),
        checkpoint=lambda: None,
        progress=events.append,
    )
    assert [event.completed for event in events] == [0, 1, 12]
    assert all(event.total == 12 for event in events)


@pytest.mark.parametrize("cancel", [False, True])
def test_refresh_controller_delivers_progress_and_discards_cancelled_results(
    scanned: tuple[HostMediaScanner, HostMediaLibrary], cancel: bool
) -> None:
    scanner, library = scanned
    controller = HostMediaScanController(scanner)
    events: list[object] = []
    finished: list[object] = []
    controller.progressChanged.connect(events.append)
    controller.refreshFinished.connect(finished.append)
    try:
        assert controller.refresh_tracks(
            library, frozenset(source.path for source in library.sources)
        )
        assert controller._pool.waitForDone(5000)  # pyright: ignore[reportPrivateUsage]
        if cancel:
            controller.cancel()
        APPLICATION.processEvents()
        if cancel:
            assert events == finished == []
        else:
            assert len(finished) == 1 and events
            assert isinstance(events[-1], HostMediaScanProgress)
            assert events[-1].completed == events[-1].total == 12
    finally:
        controller.shutdown()
