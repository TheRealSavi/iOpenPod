"""Count finite Sync work while retaining nested activity and interruption semantics."""

from __future__ import annotations

from dataclasses import replace
from time import monotonic
from typing import TYPE_CHECKING

from iOpenPod.app.library_write import WriteProgress

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator


class CountedProgress:
    """Publish processed items, including handled skips, through WriteProgress.

    The loop must resume normally before an item counts as completed. Exceptions,
    cancellation and early exits do not manufacture completion. Nested activity
    keeps the enclosing phase's counts and may describe the current sub-operation.
    """

    def __init__(
        self,
        progress: Callable[[WriteProgress], None],
        phase: str,
        message: str,
        *,
        unit: str,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._progress = progress
        self._current = WriteProgress(phase, message, completed=0, unit=unit)
        self._clock = clock
        self._last_reported: float | None = None

    def _publish(self, update: WriteProgress, *, force: bool = False) -> None:
        now = self._clock()
        if force or self._last_reported is None or now - self._last_reported >= 0.1:
            self._progress(update)
            self._last_reported = now

    def items[T](self, items: Collection[T], name: Callable[[T], str]) -> Iterator[T]:
        total = len(items)
        for index, item in enumerate(items):
            self._current = replace(
                self._current, completed=index, total=total, current_item=name(item)
            )
            self._publish(self._current, force=index == 0)
            yield item
            self._current = replace(self._current, completed=index + 1)
            self._publish(self._current, force=index + 1 == total)

    def report(self, update: WriteProgress) -> None:
        """Retain known counters when a nested operation reports only activity."""
        self._publish(
            replace(
                update,
                phase=self._current.phase,
                completed=self._current.completed,
                total=self._current.total,
                unit=self._current.unit,
                current_item=update.current_item or self._current.current_item,
            )
        )
