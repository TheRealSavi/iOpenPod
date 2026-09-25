"""Analysis-only Synesthesia controller contracts."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from time import monotonic, sleep
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QThreadPool
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.models.playback_models import PlaybackEntry
from iOpenPod.app.synesthesia import (
    AnalysisRequest,
    SynesthesiaController,
)
from iPodDB.library import Track

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.playback.backend import PlaybackSource
    from iOpenPod.app.synesthesia import AnalysisProgress, TrackAnalysis


@dataclass(frozen=True, slots=True)
class _MemorySource:
    payload: bytes
    file_name: str

    @property
    def byte_count(self) -> int:
        return len(self.payload)

    def read_at(self, offset: int, length: int) -> bytes:
        return self.payload[offset : offset + length]


class _SourceProvider:
    def __init__(self, payloads: dict[int, bytes]) -> None:
        self._payloads = payloads
        self.opened: list[Track] = []

    def open_playback_source(self, track: Track) -> PlaybackSource:
        self.opened.append(track)
        return _MemorySource(self._payloads[track.track_id], "iPod Track.M4A")


@dataclass(frozen=True, slots=True)
class _TruncatedSource:
    payload: bytes
    advertised_byte_count: int
    file_name: str = "truncated.flac"

    @property
    def byte_count(self) -> int:
        return self.advertised_byte_count

    def read_at(self, offset: int, length: int) -> bytes:
        return self.payload[offset : offset + length]


class _TruncatedSourceProvider:
    def open_playback_source(self, track: Track) -> PlaybackSource:
        del track
        return _TruncatedSource(b"short", advertised_byte_count=10)


class _RecordingBackend:
    def __init__(
        self,
        result: TrackAnalysis,
        *,
        blocked: bool = False,
        blocked_payloads: frozenset[bytes] = frozenset(),
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._blocked = blocked
        self._blocked_payloads = blocked_payloads
        self._error = error
        self.entered = threading.Event()
        self.release = threading.Event()
        self.paths: list[Path] = []
        self.payloads: list[bytes] = []
        self.requests: list[AnalysisRequest | None] = []

    def analyze(
        self,
        source: Path,
        request: AnalysisRequest | None = None,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> TrackAnalysis:
        del progress
        self.paths.append(source)
        self.payloads.append(source.read_bytes())
        self.requests.append(request)
        self.entered.set()
        if self._blocked or self.payloads[-1] in self._blocked_payloads:
            while not self.release.wait(0.01):
                checkpoint()
        checkpoint()
        if self._error is not None:
            raise self._error
        return self._result


def _track(track_id: int) -> Track:
    return Track(
        track_id=track_id,
        title=f"Track {track_id}",
        artist="Artist",
        album="Album",
        length_ms=180_000,
    )


def _wait_for(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 5
    while not predicate():
        APPLICATION.processEvents()
        if monotonic() >= deadline:
            raise AssertionError("Timed out waiting for Synesthesia analysis")
        sleep(0.01)
    APPLICATION.processEvents()


def test_controller_analyzes_an_identity_bound_copy_and_removes_it(
    synthetic_analysis: TrackAnalysis,
) -> None:
    track = _track(1)
    encoded = b"encoded audio bytes"
    provider = _SourceProvider({track.track_id: encoded})
    backend = _RecordingBackend(synthetic_analysis)
    controller = SynesthesiaController(backend, provider, APPLICATION)

    try:
        assert controller.analyze(track)
        _wait_for(lambda: not controller.busy)

        assert provider.opened == [track]
        assert backend.payloads == [encoded]
        assert backend.paths[0].suffix == ".m4a"
        assert not backend.paths[0].exists()
        assert backend.requests[0] == AnalysisRequest(title=track.title)
        assert controller.track == track
        assert controller.analysis == synthetic_analysis
        assert not hasattr(controller, "play")
        assert not hasattr(controller, "seek")
    finally:
        controller.shutdown()


def test_replacement_job_ignores_the_obsolete_result_and_cleans_both_copies(
    synthetic_analysis: TrackAnalysis,
) -> None:
    first = _track(1)
    second = _track(2)
    provider = _SourceProvider({1: b"first", 2: b"second"})
    backend = _RecordingBackend(synthetic_analysis, blocked=True)
    controller = SynesthesiaController(backend, provider, APPLICATION)
    published: list[object] = []
    controller.analysisChanged.connect(published.append)

    try:
        assert controller.analyze(first)
        assert backend.entered.wait(5)
        assert controller.analyze(second)
        backend.release.set()
        _wait_for(lambda: not controller.busy)

        assert provider.opened == [first, second]
        assert backend.payloads == [b"first", b"second"]
        assert published == [None, None, synthetic_analysis]
        assert controller.track == second
        assert controller.analysis == synthetic_analysis
        assert all(not path.exists() for path in backend.paths)
    finally:
        backend.release.set()
        controller.shutdown()


def test_latest_replacement_discards_an_intermediate_job_that_has_not_started(
    synthetic_analysis: TrackAnalysis,
) -> None:
    first = _track(1)
    intermediate = _track(2)
    latest = _track(3)
    provider = _SourceProvider({1: b"first", 2: b"intermediate", 3: b"latest"})
    backend = _RecordingBackend(synthetic_analysis, blocked=True)
    controller = SynesthesiaController(backend, provider, APPLICATION)

    try:
        assert controller.analyze(first)
        assert backend.entered.wait(5)
        assert controller.analyze(intermediate)
        assert controller.analyze(latest)
        backend.release.set()
        _wait_for(lambda: not controller.busy)

        assert provider.opened == [first, latest]
        assert backend.payloads == [b"first", b"latest"]
        assert controller.track == latest
        assert controller.analysis == synthetic_analysis
        assert all(not path.exists() for path in backend.paths)
    finally:
        backend.release.set()
        controller.shutdown()


def test_analysis_failure_is_reported_after_the_materialized_copy_is_removed(
    synthetic_analysis: TrackAnalysis,
) -> None:
    track = _track(1)
    provider = _SourceProvider({track.track_id: b"encoded audio bytes"})
    backend = _RecordingBackend(
        synthetic_analysis,
        error=RuntimeError("analysis failed"),
    )
    controller = SynesthesiaController(backend, provider, APPLICATION)
    failures: list[str] = []
    controller.failed.connect(failures.append)

    try:
        assert controller.analyze(track)
        _wait_for(lambda: not controller.busy)

        assert failures == ["analysis failed"]
        assert controller.analysis is None
        assert backend.paths
        assert all(not path.exists() for path in backend.paths)
    finally:
        controller.shutdown()


def test_invalidated_source_read_fails_without_leaving_a_temporary_copy(
    synthetic_analysis: TrackAnalysis,
) -> None:
    temporary_roots_before = set(Path(gettempdir()).glob("iopenpod-synesthesia-*"))
    backend = _RecordingBackend(synthetic_analysis)
    controller = SynesthesiaController(
        backend,
        _TruncatedSourceProvider(),
        APPLICATION,
    )
    failures: list[str] = []
    controller.failed.connect(failures.append)

    try:
        assert controller.analyze(_track(1))
        _wait_for(lambda: not controller.busy)

        assert failures == ["The current Track changed while its media was being read."]
        assert backend.paths == []
        assert set(Path(gettempdir()).glob("iopenpod-synesthesia-*")) == (
            temporary_roots_before
        )
    finally:
        controller.shutdown()


def test_shutdown_cooperatively_stops_analysis_and_removes_its_copy(
    synthetic_analysis: TrackAnalysis,
) -> None:
    track = _track(1)
    provider = _SourceProvider({track.track_id: b"encoded audio bytes"})
    backend = _RecordingBackend(synthetic_analysis, blocked=True)
    controller = SynesthesiaController(backend, provider, APPLICATION)

    assert controller.analyze(track)
    assert backend.entered.wait(5)

    controller.shutdown()

    assert backend.paths
    assert all(not path.exists() for path in backend.paths)
    assert not controller.busy


def test_completed_preparation_is_quiet_and_promoted_without_reanalysis(
    synthetic_analysis: TrackAnalysis,
) -> None:
    first, second = _track(1), _track(2)
    next_entry = PlaybackEntry(2, second)
    provider = _SourceProvider({1: b"first", 2: b"second"})
    backend = _RecordingBackend(synthetic_analysis)
    controller = SynesthesiaController(backend, provider, APPLICATION)
    published: list[object] = []
    progress: list[object] = []
    busy: list[bool] = []
    controller.analysisChanged.connect(published.append)
    controller.progressChanged.connect(progress.append)
    controller.busyChanged.connect(busy.append)

    try:
        assert controller.analyze(first, entry_id=1)
        _wait_for(lambda: not controller.busy)
        progress.clear()
        busy.clear()
        published.clear()

        controller.prepare_next(next_entry)
        _wait_for(lambda: controller.prepared_entry_id == 2)
        controller.prepare_next(next_entry)
        assert provider.opened == [first, second]
        assert controller.track == first
        assert controller.analysis is synthetic_analysis
        assert published == progress == busy == []
        assert all(not path.exists() for path in backend.paths)

        assert controller.analyze(second, entry_id=2)
        assert controller.analysis is synthetic_analysis
        assert controller.track == second
        assert not controller.busy
        assert controller.prepared_entry_id is None
        assert published == [None, synthetic_analysis]
        assert provider.opened == [first, second]
    finally:
        controller.shutdown()


@pytest.mark.parametrize("still_analyzing_current", (False, True))
def test_prepared_job_can_be_promoted_while_running_or_queued(
    synthetic_analysis: TrackAnalysis,
    still_analyzing_current: bool,
) -> None:
    first, second = _track(1), _track(2)
    provider = _SourceProvider({1: b"first", 2: b"second"})
    backend = _RecordingBackend(
        synthetic_analysis,
        blocked_payloads=frozenset(
            (b"first", b"second") if still_analyzing_current else (b"second",)
        ),
    )
    controller = SynesthesiaController(backend, provider, APPLICATION)
    published: list[object] = []
    controller.analysisChanged.connect(published.append)

    try:
        assert controller.analyze(first, entry_id=1)
        assert backend.entered.wait(5)
        if not still_analyzing_current:
            _wait_for(lambda: not controller.busy)
        controller.prepare_next(PlaybackEntry(2, second))
        if still_analyzing_current:
            assert backend.payloads == [b"first"]
        else:
            _wait_for(lambda: backend.payloads == [b"first", b"second"])
            assert not controller.busy

        published.clear()
        assert controller.analyze(second, entry_id=2)
        assert controller.busy
        backend.release.set()
        _wait_for(lambda: not controller.busy)

        assert provider.opened == [first, second]
        assert backend.payloads == [b"first", b"second"]
        assert published == [None, synthetic_analysis]
        assert controller.track == second
        assert all(not path.exists() for path in backend.paths)
    finally:
        backend.release.set()
        controller.shutdown()


def test_queue_replacement_cancels_preparation_and_retains_only_the_new_target(
    synthetic_analysis: TrackAnalysis,
) -> None:
    first, obsolete, latest = _track(1), _track(2), _track(3)
    provider = _SourceProvider({1: b"first", 2: b"obsolete", 3: b"latest"})
    backend = _RecordingBackend(
        synthetic_analysis, blocked_payloads=frozenset((b"obsolete",))
    )
    controller = SynesthesiaController(backend, provider, APPLICATION)
    published: list[object] = []
    controller.analysisChanged.connect(published.append)

    try:
        assert controller.analyze(first, entry_id=1)
        _wait_for(lambda: not controller.busy)
        published.clear()
        controller.prepare_next(PlaybackEntry(2, obsolete))
        _wait_for(lambda: len(backend.paths) == 2)
        controller.prepare_next(PlaybackEntry(3, latest))
        _wait_for(lambda: controller.prepared_entry_id == 3)

        assert published == []
        assert controller.analysis is synthetic_analysis
        assert provider.opened == [first, obsolete, latest]
        assert all(not path.exists() for path in backend.paths)
        controller.prepare_next(None)
        assert controller.prepared_entry_id is None
        assert controller.analyze(latest, entry_id=3)
        _wait_for(lambda: not controller.busy)
        assert provider.opened == [first, obsolete, latest, latest]
    finally:
        backend.release.set()
        controller.shutdown()


def test_preparation_for_another_occurrence_is_not_reused(
    synthetic_analysis: TrackAnalysis,
) -> None:
    first, second = _track(1), _track(2)
    provider = _SourceProvider({1: b"first", 2: b"second"})
    backend = _RecordingBackend(synthetic_analysis)
    controller = SynesthesiaController(backend, provider, APPLICATION)

    try:
        assert controller.analyze(first, entry_id=1)
        controller.prepare_next(PlaybackEntry(2, second))
        _wait_for(lambda: controller.prepared_entry_id == 2)
        assert controller.analyze(second, entry_id=3)
        _wait_for(lambda: not controller.busy)
        assert provider.opened == [first, second, second]
    finally:
        controller.shutdown()


def test_preparation_failure_stays_quiet_and_retries_when_it_becomes_current(
    synthetic_analysis: TrackAnalysis,
) -> None:
    provider = _SourceProvider({1: b"first", 2: b"second"})
    backend = _RecordingBackend(synthetic_analysis, error=RuntimeError("bad audio"))
    controller = SynesthesiaController(backend, provider, APPLICATION)
    failures: list[str] = []
    progress: list[object] = []
    controller.failed.connect(failures.append)
    controller.progressChanged.connect(progress.append)
    entry = PlaybackEntry(2, _track(2))

    try:
        assert controller.analyze(_track(1), entry_id=1)
        _wait_for(lambda: not controller.busy)
        assert failures == ["bad audio"]
        failures.clear()
        progress.clear()
        controller.prepare_next(entry)
        pool = controller.findChild(QThreadPool)
        assert pool is not None
        assert pool.waitForDone(5_000)
        APPLICATION.processEvents()

        assert failures == progress == []
        assert controller.prepared_entry_id is None
        controller.prepare_next(entry)
        assert pool.waitForDone(5_000)
        APPLICATION.processEvents()
        assert backend.payloads == [b"first", b"second"]

        assert controller.analyze(entry.track, entry_id=entry.entry_id)
        _wait_for(lambda: not controller.busy)
        assert backend.payloads == [b"first", b"second", b"second"]
        assert failures == ["bad audio"]
        assert all(not path.exists() for path in backend.paths)
    finally:
        controller.shutdown()


def test_stale_preparation_completion_cannot_publish_after_clear(
    synthetic_analysis: TrackAnalysis,
) -> None:
    provider = _SourceProvider({1: b"first", 2: b"second"})
    backend = _RecordingBackend(synthetic_analysis)
    controller = SynesthesiaController(backend, provider, APPLICATION)
    published: list[object] = []
    controller.analysisChanged.connect(published.append)

    try:
        assert controller.analyze(_track(1), entry_id=1)
        _wait_for(lambda: not controller.busy)
        controller.prepare_next(PlaybackEntry(2, _track(2)))
        pool = controller.findChild(QThreadPool)
        assert pool is not None
        # Completion is queued for the GUI thread but has not been delivered.
        assert pool.waitForDone(5_000)
        published.clear()
        controller.clear()
        APPLICATION.processEvents()

        assert published == [None]
        assert controller.analysis is None
        assert controller.prepared_entry_id is None
        assert all(not path.exists() for path in backend.paths)
    finally:
        controller.shutdown()


@pytest.mark.parametrize("shutdown", (False, True))
def test_leaving_cancels_preparation_and_removes_its_copy(
    synthetic_analysis: TrackAnalysis, shutdown: bool
) -> None:
    provider = _SourceProvider({1: b"first", 2: b"second"})
    backend = _RecordingBackend(
        synthetic_analysis, blocked_payloads=frozenset((b"second",))
    )
    controller = SynesthesiaController(backend, provider, APPLICATION)

    try:
        # There must be an active current analysis before preparation can start.
        controller.prepare_next(PlaybackEntry(2, _track(2)))
        assert provider.opened == []
        assert controller.analyze(_track(1), entry_id=1)
        _wait_for(lambda: not controller.busy)
        controller.prepare_next(PlaybackEntry(2, _track(2)))
        _wait_for(lambda: len(backend.paths) == 2)
        if shutdown:
            controller.shutdown()
        else:
            controller.clear()
        _wait_for(lambda: all(not path.exists() for path in backend.paths))

        assert controller.track is None
        assert controller.analysis is None
        assert controller.prepared_entry_id is None
        assert not controller.busy
    finally:
        backend.release.set()
        controller.shutdown()
