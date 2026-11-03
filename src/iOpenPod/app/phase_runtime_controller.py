"""Run optional Phase installation off the GUI thread, only on explicit request."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.phase_runtime import ManagedPhaseSources
from iOpenPod.app.phase_runtime_install import (
    host_runtime_target,
    install_phase_runtime,
)
from storage import StorageError

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Outcome:
    message: str
    details: str = ""


class _SetupCancelledError(Exception):
    pass


class _Signals(QObject):
    progress = Signal(object)
    finished = Signal(object)


class _Install(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = _Signals()
        self.cancelled = Event()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise _SetupCancelledError

        try:
            install_phase_runtime(
                checkpoint=checkpoint,
                progress=self.signals.progress.emit,
            )
        except _SetupCancelledError:
            self.signals.finished.emit(
                _Outcome(
                    source_text("Setup cancelled. Acoustic analysis remains available.")
                )
            )
        except Exception as error:
            _LOG.exception("Optional Phase analysis setup failed")
            self.signals.finished.emit(
                _Outcome(
                    source_text(
                        "Setup could not finish. Acoustic analysis remains available."
                    ),
                    exception_text(error),
                )
            )
        else:
            self.signals.finished.emit(
                _Outcome(
                    source_text(
                        "Instrument analysis is ready for the next Phase save or Sync."
                    )
                )
            )


class PhaseRuntimeController(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.busy = False
        self.cancelling = False
        self.installed = False
        self.can_install = False
        self.message: str = ""
        self.details: str = ""
        self.availability: str = source_text(
            "Acoustic analysis is included. Optional instrument analysis can be installed here."
        )
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job: _Install | None = None

    def refresh(self) -> None:
        """Read setup eligibility and the receipt without importing optional libraries."""
        if self.busy:
            return
        try:
            host_runtime_target()
        except ValueError:
            self.can_install = False
        else:
            self.can_install = True
        try:
            self.installed = ManagedPhaseSources.installed() is not None
        except (OSError, ValueError, StorageError):
            _LOG.warning(
                "Could not read the optional Phase runtime receipt", exc_info=True
            )
            self.installed = False
            self.availability = source_text(
                "The previous instrument analysis setup needs attention. Acoustic analysis remains available."
            )
        else:
            self.availability = (
                source_text(
                    "Instrument analysis is installed. Acoustic analysis remains available as a fallback."
                )
                if self.installed
                else source_text(
                    "Acoustic analysis is included. Optional instrument analysis can be installed here."
                )
            )
        if not self.can_install:
            self.availability = source_text(
                "Instrument analysis setup is unavailable on this system. Acoustic analysis remains available."
            )
        self.changed.emit()

    @Slot()
    def install(self) -> None:
        if self.busy:
            return
        self.refresh()
        if not self.can_install:
            return
        self.busy = True
        self.cancelling = False
        self.details = ""
        self.message = source_text("Preparing optional analysis setup…")
        self._job = _Install()
        self._job.signals.progress.connect(self._progress)
        self._job.signals.finished.connect(self._finished)
        self.changed.emit()
        self._pool.start(self._job)

    @Slot(object)
    def _progress(self, message: object) -> None:
        assert isinstance(message, str)
        if self.cancelling:
            return
        self.message = message
        self.changed.emit()

    @Slot(object)
    def _finished(self, outcome: object) -> None:
        assert isinstance(outcome, _Outcome)
        self.message = outcome.message
        self.details = outcome.details
        self.busy = False
        self.cancelling = False
        self._job = None
        self.refresh()

    @Slot()
    def cancel(self) -> None:
        if self._job is not None and not self.cancelling:
            self.cancelling = True
            self._job.cancelled.set()
            self.message = source_text("Cancelling setup…")
            self.changed.emit()

    def shutdown(self) -> None:
        self.cancel()
        self._pool.waitForDone()
