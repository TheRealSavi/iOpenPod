"""Reusable ETA presentation for cumulative, stage-scoped progress."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QLabel, QWidget

from iOpenPod.app.core.eta import ProgressEta
from iOpenPod.GUI.presentation.eta import eta_text

if TYPE_CHECKING:
    from collections.abc import Callable


class EtaLabel(QLabel):
    """Own GUI-thread timing; operation lifecycles explicitly reset this label."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._eta = ProgressEta(clock=clock)
        self._timer = QTimer(self)
        self._timer.setInterval(1_000)
        self._timer.timeout.connect(self.refresh)
        self.setWordWrap(True)

    def set_progress(
        self,
        phase: str,
        completed: float,
        total: float | None,
        *,
        unit: str = "items",
    ) -> None:
        self._eta.update(phase, completed, total, unit=unit)
        self.refresh()
        if not self._timer.isActive():
            self._timer.start()

    def reset(self) -> None:
        """Stop refresh and discard evidence on success, failure, cancel or retry."""

        self._timer.stop()
        self._eta.reset()
        self.clear()

    def refresh(self) -> None:
        estimate = self._eta.snapshot()
        self.setText(eta_text(estimate) if estimate is not None else "")

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.refresh()
        super().changeEvent(event)
