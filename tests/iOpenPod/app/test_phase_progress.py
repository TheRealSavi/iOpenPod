"""Phase estimates use timed audio, while status follows the actual backend."""

from dataclasses import replace
from pathlib import Path
from threading import get_ident

import pytest
from tests.iOpenPod.app.core.test_eta import Clock
from tests.iOpenPod.app.phase_test_support import StubPhaseAnalysis
from tests.iOpenPod.app.services.test_phase_prefetch import device

from iOpenPod.app.core.eta import EtaState
from iOpenPod.app.phase_activity import PhaseActivity, PhaseStage
from iOpenPod.app.phase_progress import PhaseProgress, PhaseProgressReporter
from iOpenPod.app.services.phase import prepare_phase
from iPodDB.library import LibrarySnapshot, playlist_entries


def test_eta_weights_audio_duration_and_does_not_train_on_heartbeats() -> None:
    clock = Clock()
    events: list[PhaseProgress] = []
    reporter = PhaseProgressReporter(
        (30_000, 60_000, 90_000, 180_000), events.append, clock=clock
    )
    activity = PhaseActivity(PhaseStage.ACOUSTIC)
    reporter.emit("first", activity)
    initial = events[-1]
    assert initial.eta.state is EtaState.WARMING_UP
    for index, seconds in enumerate((3, 6, 9)):
        clock.advance(seconds)
        reporter.complete_track()
        reporter.emit(str(index), activity)
    assert events[-1].completed == 3
    assert events[-1].eta.remaining_seconds == pytest.approx(18)
    reporter.emit("2", activity)
    assert len(events) == 4  # Duplicate checkpoint costs no GUI event.
    clock.advance(1)
    reporter.emit("2", activity)
    assert events[-1].eta.completed == 180_000
    assert events[-1].eta.remaining_seconds == pytest.approx(18)
    clock.advance(120)
    reporter.emit("2", activity)
    stalled = events[-1]
    assert stalled.eta.state is EtaState.STALLED
    assert stalled.eta.remaining_seconds is None
    reporter.complete_track()
    reporter.emit("", PhaseActivity(PhaseStage.FINALIZING))
    assert events[-1].eta.state is EtaState.COMPLETE
    assert "Finishing analysis" in events[-1].message


def test_new_preparation_does_not_reuse_a_previous_eta() -> None:
    clock = Clock()
    events: list[PhaseProgress] = []
    first = PhaseProgressReporter((30_000,) * 6, events.append, clock=clock)
    for _ in range(3):
        clock.advance(3)
        first.complete_track()
    first.emit("track", PhaseActivity(PhaseStage.ACOUSTIC))
    estimated = events[-1]
    assert estimated.eta.state is EtaState.ESTIMATING
    second = PhaseProgressReporter((30_000,) * 6, events.append, clock=clock)
    second.emit("track", PhaseActivity(PhaseStage.ACOUSTIC))
    assert events[-1].eta.state is EtaState.WARMING_UP


@pytest.mark.parametrize(
    "backend,name,expected",
    [
        ("cuda", "RTX 4070", "RTX 4070 / CUDA"),
        ("mps", "", "GPU / MPS (Metal)"),
        ("cpu", "", "CPU"),
        ("", "", "Selecting hardware"),
    ],
)
def test_source_message_names_live_hardware(
    backend: str, name: str, expected: str
) -> None:
    events: list[PhaseProgress] = []
    reporter = PhaseProgressReporter((30_000,), events.append)
    reporter.emit("Song", PhaseActivity(PhaseStage.SOURCES, backend, name, True))
    assert expected in events[-1].message
    assert "Demucs htdemucs_6s" in events[-1].message
    assert "+ librosa · CPU" in events[-1].message
    reporter.emit("Song", PhaseActivity(PhaseStage.ACOUSTIC))
    assert "librosa · CPU" in events[-1].message
    assert "Demucs" not in events[-1].message
    assert "CUDA" not in events[-1].message


def test_preparation_reports_only_eligible_unique_tracks_on_caller(
    tmp_path: Path,
) -> None:
    storage, desired = device(tmp_path, 3)
    desired = replace(
        desired,
        tracks=(replace(desired.tracks[0], length_ms=10_000), *desired.tracks[1:]),
        playlists=(
            replace(desired.playlists[0], entries=playlist_entries((1, 2, 2, 3))),
        ),
    )
    events: list[PhaseProgress] = []
    threads: list[int] = []

    def report(value: PhaseProgress) -> None:
        threads.append(get_ident())
        events.append(value)

    with storage.open_session(storage.discover().volumes[0]) as session:
        prepare_phase(
            session,
            LibrarySnapshot(),
            desired,
            analyzer=StubPhaseAnalysis(),
            analysis_progress=report,
        )
    assert set(threads) == {get_ident()}
    assert all(event.total == 2 for event in events)
    assert {event.title for event in events} == {"", "2", "3"}
    assert events[-1].completed == 2
    assert events[-1].eta.total == 60_000
    assert events[-1].eta.state is EtaState.COMPLETE
    assert PhaseStage.VERIFYING in {event.activity.stage for event in events}
