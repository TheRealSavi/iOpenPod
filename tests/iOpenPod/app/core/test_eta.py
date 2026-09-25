"""Deterministic workloads exercise ETA accuracy and lifecycle semantics."""

from __future__ import annotations

import math

import pytest

from iOpenPod.app.core.eta import EtaConfig, EtaEstimator, EtaState, ProgressEta


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float = 1.0) -> None:
        self.now += seconds


def _steady(
    *,
    rate: float = 100,
    seconds: int = 30,
    total: float = 10_000,
) -> tuple[Clock, EtaEstimator, float]:
    clock = Clock()
    estimator = EtaEstimator(total=total, clock=clock)
    completed = 0.0
    for _ in range(seconds):
        clock.advance()
        completed += rate
        estimator.update(completed, total=total)
    return clock, estimator, completed


def test_constant_throughput_is_accurate_and_range_contains_the_forecast() -> None:
    _clock, estimator, _completed = _steady()
    result = estimator.snapshot()
    assert result.state is EtaState.ESTIMATING
    assert result.rate_per_second == pytest.approx(100)
    assert result.remaining_seconds == pytest.approx(70)
    assert result.lower_seconds is not None and result.lower_seconds < 70
    assert result.upper_seconds is not None and result.upper_seconds > 70
    assert result.elapsed_seconds == 30


@pytest.mark.parametrize("interval", [0.01, 0.1, 0.5, 1.0, 3.0])
def test_constant_rate_is_independent_of_callback_frequency(interval: float) -> None:
    clock = Clock()
    estimator = EtaEstimator(total=100_000, clock=clock)
    for index in range(1, round(30 / interval) + 1):
        clock.now = index * interval
        estimator.update(clock.now * 100, total=100_000)
    result = estimator.snapshot()
    assert result.remaining_seconds == pytest.approx(970)


def test_irregular_and_duplicate_callbacks_do_not_invent_timing_samples() -> None:
    clock = Clock()
    estimator = EtaEstimator(total=10_000, clock=clock)
    for duration in (0, 0.01, 2, 0.02, 3, 0, 1, 0.1, 4):
        clock.advance(duration)
        result = estimator.update(clock.now * 100, total=10_000)
        assert estimator.update(clock.now * 100, total=10_000) == result
    assert result.rate_per_second == pytest.approx(100)


def test_startup_unknown_and_empty_work_are_distinct() -> None:
    clock = Clock()
    estimator = EtaEstimator(clock=clock)
    assert estimator.snapshot().state is EtaState.UNKNOWN_TOTAL
    assert estimator.update(0, total=100).state is EtaState.WARMING_UP
    clock.advance()
    assert estimator.update(10, total=100).remaining_seconds is None
    empty = EtaEstimator(total=0, clock=clock).snapshot()
    assert empty.state is EtaState.COMPLETE
    assert empty.remaining_seconds == 0


def test_first_counter_is_a_baseline_and_large_same_timestamp_bursts_need_time() -> (
    None
):
    clock = Clock()
    estimator = EtaEstimator(completed=900, total=10_000, clock=clock)
    assert estimator.update(5_000, total=10_000).remaining_seconds is None
    for _ in range(100):
        assert estimator.snapshot().remaining_seconds is None


def test_one_cache_burst_does_not_collapse_the_eta() -> None:
    clock, estimator, completed = _steady(total=1_000_000)
    clock.advance()
    result = estimator.update(completed + 10_000, total=1_000_000)
    assert result.rate_per_second is not None
    assert 90 < result.rate_per_second < 130
    assert result.remaining_seconds is not None and result.remaining_seconds > 7_000


@pytest.mark.parametrize("new_rate", [5.0, 1_000.0])
def test_sustained_slowdown_and_speedup_replace_obsolete_history(
    new_rate: float,
) -> None:
    clock, estimator, completed = _steady(total=1_000_000)
    for _ in range(6):
        clock.advance()
        completed += new_rate
        estimator.update(completed, total=1_000_000)
    result = estimator.snapshot()
    assert result.rate_per_second == pytest.approx(new_rate, rel=0.2)
    assert result.remaining_seconds == pytest.approx(
        (1_000_000 - completed) / new_rate, rel=0.2
    )


def test_variable_workload_widens_range() -> None:
    _clock, stable, _completed = _steady(seconds=60)
    clock = Clock()
    variable = EtaEstimator(total=10_000, clock=clock)
    completed = 0.0
    for index in range(60):
        clock.advance()
        completed += 50 if index % 2 else 150
        variable.update(completed, total=10_000)
    fixed, changing = stable.snapshot(), variable.snapshot()
    assert fixed.upper_seconds is not None and fixed.lower_seconds is not None
    assert changing.upper_seconds is not None and changing.lower_seconds is not None
    assert changing.upper_seconds / changing.lower_seconds > (
        fixed.upper_seconds / fixed.lower_seconds * 2
    )


def test_silence_ages_then_withdraws_eta_and_progress_can_recover() -> None:
    clock, estimator, completed = _steady()
    original = estimator.snapshot()
    clock.advance(7)
    stale = estimator.snapshot()
    assert (
        original.remaining_seconds is not None and stale.remaining_seconds is not None
    )
    assert stale.remaining_seconds > original.remaining_seconds
    assert stale.upper_seconds is not None and original.upper_seconds is not None
    assert stale.upper_seconds > original.upper_seconds
    # Heartbeats are not progress and must not keep stale estimates alive.
    clock.advance(9)
    assert estimator.update(completed, total=10_000).state is EtaState.STALLED
    assert estimator.snapshot().remaining_seconds is None
    for _ in range(10):
        clock.advance()
        completed += 100
        estimator.update(completed, total=10_000)
    assert estimator.snapshot().state is EtaState.ESTIMATING


def test_stall_detection_respects_observed_sparse_item_cadence() -> None:
    clock = Clock()
    estimator = EtaEstimator(total=100, clock=clock)
    for completed in range(1, 5):
        clock.advance(20)
        estimator.update(completed, total=100)
    clock.advance(25)
    assert estimator.snapshot().state is EtaState.ESTIMATING
    clock.advance(36)
    assert estimator.snapshot().state is EtaState.STALLED


def test_pauses_exclude_wait_time_including_a_partial_sample() -> None:
    clock, estimator, completed = _steady()
    clock.advance(0.25)
    estimator.update(completed + 25, total=10_000)
    paused = estimator.pause()
    clock.advance(3_600)
    assert estimator.pause() == paused
    assert paused.state is EtaState.PAUSED
    assert estimator.snapshot() == paused
    with pytest.raises(ValueError, match="Resume"):
        estimator.update(completed + 50, total=10_000)
    estimator.resume()
    clock.advance(0.75)
    result = estimator.update(completed + 100, total=10_000)
    assert result.rate_per_second == pytest.approx(100)
    assert result.elapsed_seconds == 31


def test_total_changes_keep_rate_evidence_and_never_count_down_without_work() -> None:
    clock, estimator, completed = _steady()
    original = estimator.snapshot()
    bigger = estimator.update(completed, total=20_000)
    assert bigger.remaining_seconds == pytest.approx(170)
    assert bigger.rate_per_second == original.rate_per_second
    assert estimator.update(completed, total=None).state is EtaState.UNKNOWN_TOTAL
    assert estimator.update(completed, total=10_000) == original
    clock.advance(0.5)
    assert estimator.snapshot().remaining_seconds == original.remaining_seconds
    assert estimator.update(completed, total=completed).remaining_seconds == 0
    assert estimator.update(completed, total=10_000).state is EtaState.ESTIMATING


@pytest.mark.parametrize(
    ("completed", "total"),
    [
        (-1, 100),
        (1, 0),
        (math.nan, 100),
        (math.inf, None),
        (1, math.inf),
        (1, math.nan),
    ],
)
def test_invalid_observations_do_not_poison_estimator(
    completed: float,
    total: float | None,
) -> None:
    _clock, estimator, _completed = _steady()
    before = estimator.snapshot()
    with pytest.raises(ValueError):
        estimator.update(completed, total=total)
    assert estimator.snapshot() == before


def test_counter_regression_and_invalid_clocks_are_rejected() -> None:
    clock, estimator, completed = _steady()
    with pytest.raises(ValueError, match="decrease"):
        estimator.update(completed - 1, total=10_000)
    for invalid in (29, math.inf, math.nan):
        clock.now = invalid
        with pytest.raises(ValueError, match="clock"):
            estimator.snapshot()
    clock.now = 31
    assert estimator.update(completed + 100, total=10_000).state is EtaState.ESTIMATING


@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan])
def test_timing_configuration_requires_positive_finite_values(value: float) -> None:
    with pytest.raises(ValueError):
        EtaConfig(half_life_seconds=value)


def test_very_large_byte_counters_and_tiny_weighted_work_stay_finite() -> None:
    for unit in (1e15, 1e-100):
        _clock, estimator, _completed = _steady(rate=unit, total=unit * 100)
        estimate = estimator.snapshot()
        assert estimate.remaining_seconds == pytest.approx(70)
        assert estimate.upper_seconds is not None and math.isfinite(
            estimate.upper_seconds
        )


@pytest.mark.parametrize("change", ["phase", "unit", "counter", "operation"])
def test_stage_adapter_discards_incompatible_history(change: str) -> None:
    clock = Clock()
    eta = ProgressEta(clock=clock)
    assert eta.snapshot() is None
    for completed in range(6):
        eta.update("copy", completed * 100, 10_000, unit="bytes")
        clock.advance()
    before = eta.snapshot()
    assert before is not None and before.state is EtaState.ESTIMATING
    if change == "operation":
        eta.reset()
        assert eta.snapshot() is None
    result = eta.update(
        "verify" if change == "phase" else "copy",
        0 if change == "counter" else 500,
        10_000,
        unit="items" if change == "unit" else "bytes",
    )
    assert result.state is EtaState.WARMING_UP
    assert result.remaining_seconds is None
