"""Finite progress stays bounded and cannot turn interrupted work into completion."""

import pytest

from iOpenPod.app.library_write import PreparationCancelledError, WriteProgress
from iOpenPod.app.sync_progress import CountedProgress


def test_large_fast_stage_publishes_bounded_updates_and_exact_final_count() -> None:
    events: list[WriteProgress] = []
    stage = CountedProgress(
        events.append, "sync.metadata", "Preparing…", unit="Tracks", clock=lambda: 0
    )
    assert len(list(stage.items(range(20_000), str))) == 20_000
    assert [(event.completed, event.total) for event in events] == [
        (0, 20_000),
        (20_000, 20_000),
    ]


def test_nested_activity_retains_the_enclosing_counts_and_phase() -> None:
    events: list[WriteProgress] = []
    now = 0.0
    stage = CountedProgress(
        events.append,
        "sync.podcast_artwork.covers",
        "Preparing…",
        unit="episodes",
        clock=lambda: now,
    )
    for name in stage.items(("First", "Second"), str):
        now += 1
        stage.report(
            WriteProgress(
                "sync.podcast_artwork", "Downloading cover…", current_item=name
            )
        )
    nested = [event for event in events if event.message == "Downloading cover…"]
    assert [(event.completed, event.total) for event in nested] == [(0, 2), (1, 2)]
    assert all(
        event.phase == "sync.podcast_artwork.covers" and event.unit == "episodes"
        for event in nested
    )
    assert events[-1].completed == 2


@pytest.mark.parametrize("stop", ["cancel", "error", "break"])
def test_interrupted_item_never_claims_completion(stop: str) -> None:
    events: list[WriteProgress] = []
    stage = CountedProgress(
        events.append, "sync.metadata", "Preparing…", unit="Tracks", clock=lambda: 0
    )

    def run() -> None:
        for _ in stage.items(("First", "Second"), str):
            if stop == "cancel":
                raise PreparationCancelledError
            if stop == "error":
                raise OSError("source lost")
            break

    if stop == "break":
        run()
    else:
        with pytest.raises(PreparationCancelledError if stop == "cancel" else OSError):
            run()
    assert [(event.completed, event.total) for event in events] == [(0, 2)]


def test_empty_stage_does_not_replace_the_current_activity() -> None:
    events: list[WriteProgress] = []
    stage = CountedProgress(events.append, "sync.metadata", "Preparing…", unit="Tracks")
    assert list(stage.items((), str)) == []
    assert not events
