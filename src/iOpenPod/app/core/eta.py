"""Bounded, unit-independent estimates for one measurable stage of work.

Only cumulative work and a monotonic clock enter this module. No Qt, filesystem,
device, or operation policy belongs here. See docs/eta.md for the model and limits.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_HISTORY_SIZE = 31
_LOG_TWO = math.log(2.0)


class EtaState(StrEnum):
    UNKNOWN_TOTAL = "unknown_total"
    WARMING_UP = "warming_up"
    ESTIMATING = "estimating"
    STALLED = "stalled"
    PAUSED = "paused"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class EtaConfig:
    """Timing policy in seconds, independent of progress callback frequency."""

    sample_seconds: float = 0.5
    warmup_seconds: float = 2.0
    half_life_seconds: float = 6.0
    stall_seconds: float = 15.0

    def __post_init__(self) -> None:
        for value in (
            self.sample_seconds,
            self.warmup_seconds,
            self.half_life_seconds,
            self.stall_seconds,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("ETA timing settings must be finite and positive")
        if self.stall_seconds < self.sample_seconds:
            raise ValueError("The stall threshold must cover at least one sample")


@dataclass(frozen=True, slots=True)
class EtaEstimate:
    """Immutable stage estimate; the range is a heuristic, not a probability CI.

    Missing seconds mean unavailable, never zero. Zero means the supplied work
    total has been reached, not that the surrounding operation committed safely.
    Elapsed time excludes explicit pauses. Rate uses the caller's units/second.
    """

    state: EtaState
    completed: float
    total: float | None
    elapsed_seconds: float
    rate_per_second: float | None = None
    remaining_seconds: float | None = None
    lower_seconds: float | None = None
    upper_seconds: float | None = None


_DEFAULT_CONFIG = EtaConfig()


class EtaEstimator:
    """Estimate remaining work using robust, adaptive throughput smoothing.

    Call ``update`` with cumulative progress in ONE unit (bytes, items, weighted
    work). Totals may change or be unknown. Progress must not decrease; construct
    a new estimator for retries, different stages, or different units. The first
    completed value is a baseline, never retroactively credited as timed work.

    ``snapshot`` ages the estimate without inventing progress. Poll it when no
    callbacks arrive. Instances belong to one thread; publish immutable estimates
    across threads. Inject a clock for deterministic simulations.
    """

    def __init__(
        self,
        *,
        completed: float = 0,
        total: float | None = None,
        config: EtaConfig = _DEFAULT_CONFIG,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        _validate_work(completed, total)
        self._clock = clock
        self._config = config
        now = clock()
        if not math.isfinite(now):
            raise ValueError("The ETA clock must be finite")
        self._last_clock = now
        self._start = now
        self._bucket_time = now
        self._bucket_completed = completed
        self._completed = completed
        self._total = total
        self._last_progress = now
        self._paused_at: float | None = None
        self._rates: deque[float] = deque(maxlen=_HISTORY_SIZE)
        self._durations: deque[float] = deque(maxlen=_HISTORY_SIZE)
        self._log_rate: float | None = None
        self._variance = 0.0
        self._samples = 0
        self._observed_seconds = 0.0

    def update(self, completed: float, *, total: float | None) -> EtaEstimate:
        """Observe absolute work; duplicate timestamps/counters are safe.

        Explicit ``total=None`` means discovery is still unbounded. Invalid input
        is rejected before altering the learned model. Paused work must resume
        before accepting another progress observation.
        """

        _validate_work(completed, total)
        if completed < self._completed:
            raise ValueError("Cumulative ETA progress must not decrease")
        if self._paused_at is not None:
            raise ValueError("Resume the ETA estimator before reporting progress")
        now = self._now()
        if completed > self._completed:
            self._last_progress = now
        self._completed = completed
        self._total = total
        duration = now - self._bucket_time
        work = completed - self._bucket_completed
        if duration >= self._config.sample_seconds and work > 0:
            self._learn(math.log(work) - math.log(duration), duration)
            self._bucket_time = now
            self._bucket_completed = completed
        return self._estimate(now)

    def snapshot(self) -> EtaEstimate:
        """Read current evidence, accounting for silence without training on it."""

        return self._estimate(self._now())

    def pause(self) -> EtaEstimate:
        """Exclude intentional waiting, such as a user review, from throughput."""

        now = self._now()
        if self._paused_at is None:
            self._paused_at = now
        return self._estimate(now)

    def resume(self) -> EtaEstimate:
        now = self._now()
        if self._paused_at is not None:
            delay = now - self._paused_at
            self._start += delay
            self._bucket_time += delay
            self._last_progress += delay
            self._paused_at = None
        return self._estimate(now)

    def _now(self) -> float:
        now = self._clock()
        if not math.isfinite(now) or now < self._last_clock:
            raise ValueError("The ETA clock must be finite and monotonic")
        self._last_clock = now
        return now

    def _learn(self, observed: float, duration: float) -> None:
        previous = self._log_rate
        if previous is None:
            self._log_rate = observed
        else:
            center = median(self._rates)
            spread = 1.4826 * median(abs(rate - center) for rate in self._rates)
            # A single cache hit / scheduling burst cannot dominate the model.
            limit = max(_LOG_TWO, 3.0 * spread)
            recent = (*tuple(self._rates)[-2:], observed)
            shifted = len(self._rates) >= 3 and (
                all(rate > previous + _LOG_TWO for rate in recent)
                or all(rate < previous - _LOG_TWO for rate in recent)
            )
            if shifted:
                # Three sustained observations indicate a new throughput regime.
                # Retire the obsolete history so subsequent samples stay there.
                self._log_rate = median(recent)
                self._rates.clear()
                self._durations.clear()
                self._variance = max(self._variance, (observed - previous) ** 2)
            else:
                bounded = max(center - limit, min(center + limit, observed))
                alpha = -math.expm1(
                    -_LOG_TWO * duration / self._config.half_life_seconds
                )
                self._log_rate = previous + alpha * (bounded - previous)
                # Preserve variability even when the central estimate clips a burst.
                residual = min(abs(observed - previous), math.log(100.0))
                self._variance = (1 - alpha) * (self._variance + alpha * residual**2)
        self._rates.append(observed)
        self._durations.append(duration)
        self._samples += 1
        self._observed_seconds += duration

    def _estimate(self, now: float) -> EtaEstimate:
        active_now = self._paused_at if self._paused_at is not None else now
        elapsed = active_now - self._start
        idle = active_now - self._last_progress
        cadence = median(self._durations) if self._durations else 0.0
        stall_after = max(self._config.stall_seconds, 3.0 * cadence)
        if self._paused_at is not None:
            state = EtaState.PAUSED
        elif self._total is not None and self._completed == self._total:
            return EtaEstimate(
                EtaState.COMPLETE,
                self._completed,
                self._total,
                elapsed,
                remaining_seconds=0.0,
                lower_seconds=0.0,
                upper_seconds=0.0,
            )
        elif idle >= stall_after:
            state = EtaState.STALLED
        elif self._total is None:
            state = EtaState.UNKNOWN_TOTAL
        elif (
            self._log_rate is None
            or self._samples < 3
            or self._observed_seconds < self._config.warmup_seconds
        ):
            state = EtaState.WARMING_UP
        else:
            state = EtaState.ESTIMATING
        if state is not EtaState.ESTIMATING:
            return EtaEstimate(state, self._completed, self._total, elapsed)

        assert self._log_rate is not None and self._total is not None
        # Normal callback cadence is free; longer silence lowers the effective
        # rate. Never count down to zero while the completed counter is stationary.
        stale = max(0.0, idle - max(1.0, 1.5 * cadence)) / stall_after
        log_rate = self._log_rate - 2.0 * stale
        log_remaining = math.log(self._total - self._completed) - log_rate
        # A predictive spread, not a shrinking standard error: future work can
        # remain variable even after many samples. Startup uncertainty decays.
        spread = (
            1.645 * math.sqrt(self._variance) + 1.0 / math.sqrt(self._samples) + stale
        )
        rate = _exp_finite(log_rate)
        remaining = _exp_finite(log_remaining)
        lower = _exp_finite(log_remaining - spread)
        upper = _exp_finite(log_remaining + spread)
        if any(value is None for value in (rate, remaining, lower, upper)):
            return EtaEstimate(
                EtaState.WARMING_UP, self._completed, self._total, elapsed
            )
        return EtaEstimate(
            state,
            self._completed,
            self._total,
            elapsed,
            rate,
            remaining,
            lower,
            upper,
        )


class ProgressEta:
    """Adapt stage-labelled counters to independent estimators with bounded state.

    A stage/unit change or counter restart discards old timing. Changing only the
    total preserves it. Call reset between operations, including retries whose
    first counter might equal the last operation's counter.
    """

    def __init__(
        self,
        *,
        config: EtaConfig = _DEFAULT_CONFIG,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._clock = clock
        self._estimator: EtaEstimator | None = None
        self._key: tuple[str, str] | None = None
        self._completed: float = 0

    def reset(self) -> None:
        self._estimator = None
        self._key = None
        self._completed = 0

    def update(
        self,
        phase: str,
        completed: float,
        total: float | None,
        *,
        unit: str = "items",
    ) -> EtaEstimate:
        _validate_work(completed, total)
        key = (phase, unit)
        if self._estimator is None or key != self._key or completed < self._completed:
            self._estimator = EtaEstimator(
                completed=completed,
                total=total,
                config=self._config,
                clock=self._clock,
            )
        estimate = self._estimator.update(completed, total=total)
        self._key = key
        self._completed = completed
        return estimate

    def snapshot(self) -> EtaEstimate | None:
        return self._estimator.snapshot() if self._estimator is not None else None


def _validate_work(completed: float, total: float | None) -> None:
    if not math.isfinite(completed) or completed < 0:
        raise ValueError("Completed ETA work must be finite and non-negative")
    if total is not None and (not math.isfinite(total) or total < completed):
        raise ValueError("ETA total must be finite and at least completed work")


def _exp_finite(value: float) -> float | None:
    try:
        result = math.exp(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) and result > 0 else None


__all__ = ["EtaConfig", "EtaEstimate", "EtaEstimator", "EtaState", "ProgressEta"]
