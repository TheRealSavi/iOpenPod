"""Application-level progress helpers for UI/background coordination."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class StageStats:
    """Timing statistics for a single progress stage."""

    stage: str
    start_time: float = 0.0
    end_time: float = 0.0
    total_items: int = 0
    completed_items: int = 0

    _ema_item_time: float | None = None
    _ema_alpha: float = 0.15
    _last_item_time: float = 0.0
    _items_processed: int = 0

    @property
    def elapsed(self) -> float:
        end = self.end_time if self.end_time else time.monotonic()
        return max(0.0, end - self.start_time)

    @property
    def avg_item_time(self) -> float:
        """Return a smoothed average duration per completed item."""

        if self._ema_item_time is None:
            if self.completed_items > 0 and self.elapsed > 0:
                return self.elapsed / self.completed_items
            return 0.0

        if self._items_processed < 20:
            fallback = self.elapsed / max(1, self.completed_items)
            blend_alpha = self._items_processed / 20.0
            return (
                blend_alpha * self._ema_item_time
                + (1 - blend_alpha) * fallback
            )
        return self._ema_item_time

    def update_ema(self, new_time: float) -> None:
        """Update the exponential moving average with a new sample."""

        if self._ema_item_time is None:
            self._ema_item_time = new_time
        else:
            self._ema_item_time = (
                self._ema_alpha * new_time
                + (1 - self._ema_alpha) * self._ema_item_time
            )
        self._items_processed += 1

    @property
    def remaining_seconds(self) -> float:
        remaining_items = max(0, self.total_items - self.completed_items)
        avg = self.avg_item_time
        if avg <= 0:
            return 0.0
        return remaining_items * avg


class ETATracker:
    """Track progress and compute a stable estimated time remaining."""

    def __init__(self) -> None:
        self._stages: dict[str, StageStats] = {}
        self._stage_order: list[str] = []
        self._current_stage: str | None = None
        self._global_start: float = 0.0

    def reset(self) -> None:
        """Clear all tracking data."""

        self._stages.clear()
        self._stage_order.clear()
        self._current_stage = None
        self._global_start = 0.0

    def start(self) -> None:
        """Mark the beginning of the whole operation."""

        self.reset()
        self._global_start = time.monotonic()

    @property
    def elapsed_total(self) -> float:
        """Total elapsed time since start()."""

        if not self._global_start:
            return 0.0
        return time.monotonic() - self._global_start

    def stage_start(self, stage: str, total: int) -> None:
        """Begin tracking a new stage with the given item count."""

        now = time.monotonic()
        stats = StageStats(stage=stage, start_time=now, total_items=total)
        stats._last_item_time = now
        self._stages[stage] = stats
        if stage not in self._stage_order:
            self._stage_order.append(stage)
        self._current_stage = stage

    def item_done(self, stage: str | None = None) -> None:
        """Record completion of one item in the given or current stage."""

        stage = stage or self._current_stage
        if not stage or stage not in self._stages:
            return

        stats = self._stages[stage]
        now = time.monotonic()
        delta = now - stats._last_item_time
        stats._last_item_time = now
        stats.update_ema(delta)
        stats.completed_items += 1

    def stage_end(self, stage: str) -> None:
        """Mark a stage as complete."""

        if stage in self._stages:
            self._stages[stage].end_time = time.monotonic()
            if self._current_stage == stage:
                self._current_stage = None

    def update(self, stage: str, current: int, total: int) -> None:
        """Update or create a stage from absolute current/total progress."""

        if stage not in self._stages:
            self.stage_start(stage, total)

        stats = self._stages[stage]
        stats.total_items = total

        gap = current - stats.completed_items
        if gap > 0:
            now = time.monotonic()
            total_delta = now - stats._last_item_time
            per_item = total_delta / gap
            for _ in range(gap):
                stats.update_ema(per_item)
                stats.completed_items += 1
            stats._last_item_time = now

    @property
    def current_stage_stats(self) -> StageStats | None:
        if self._current_stage and self._current_stage in self._stages:
            return self._stages[self._current_stage]
        return None

    def remaining_seconds(self) -> float:
        """Estimated seconds remaining for the current stage."""

        stats = self.current_stage_stats
        if stats is None:
            return 0.0
        return stats.remaining_seconds

    def format_eta(self) -> str:
        """Human-readable ETA string for the current stage."""

        return self._format_duration(self.remaining_seconds())

    def format_elapsed(self) -> str:
        """Human-readable elapsed time since start()."""

        return self._format_duration(self.elapsed_total, prefix="")

    def format_stage_progress(self, stage: str, current: int, total: int) -> str:
        """Format compact progress text such as `3 of 50 - ~1m remaining`."""

        parts = []
        if total > 0:
            parts.append(f"{current} of {total}")

        eta = self.format_eta()
        if eta:
            parts.append(eta)

        return " - ".join(parts) if parts else ""

    @staticmethod
    def _format_duration(seconds: float, prefix: str = "~") -> str:
        """Format seconds into a human-readable remaining-time string."""

        if seconds <= 0:
            return ""
        seconds = int(seconds)
        if seconds < 5:
            return ""

        if seconds < 60:
            return f"{prefix}{seconds}s remaining"
        if seconds < 3600:
            minutes, remaining_seconds = divmod(seconds, 60)
            if remaining_seconds == 0:
                return f"{prefix}{minutes}m remaining"
            return f"{prefix}{minutes}m {remaining_seconds}s remaining"

        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        if minutes == 0:
            return f"{prefix}{hours}h remaining"
        return f"{prefix}{hours}h {minutes}m remaining"
