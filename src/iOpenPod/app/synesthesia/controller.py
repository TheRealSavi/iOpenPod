"""Qt-facing analysis for the current and next Playback Entries."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from iOpenPod.app.playback.backend import PlaybackSourceError

from .models import AnalysisProgress, AnalysisRequest, AnalysisStage, TrackAnalysis

if TYPE_CHECKING:
    from iOpenPod.app.models.playback_models import PlaybackEntry
    from iOpenPod.app.playback.backend import PlaybackSourceProvider
    from iPodDB.library import Track

    from .backend import MusicAnalysisBackend

_COPY_CHUNK_BYTES = 1024 * 1024


class AnalysisCancelledError(RuntimeError):
    """Raised at an analyzer checkpoint after the user cancels its Job."""


class _AnalysisSignals(QObject):
    progress = Signal(int, object)
    succeeded = Signal(int, object)
    failed = Signal(int, object)
    finished = Signal(int)


class _AnalysisWork(QRunnable):
    def __init__(
        self,
        token: int,
        backend: MusicAnalysisBackend,
        source_provider: PlaybackSourceProvider,
        track: Track,
        request: AnalysisRequest,
    ) -> None:
        super().__init__()
        self.token = token
        self.backend = backend
        self.source_provider = source_provider
        self.track = track
        self.request = request
        self.cancelled = threading.Event()
        self.signals = _AnalysisSignals()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise AnalysisCancelledError("Music analysis was cancelled")

        try:
            checkpoint()
            source = self.source_provider.open_playback_source(self.track)
            if source.byte_count <= 0:
                raise PlaybackSourceError(
                    "The current Track does not reference readable media."
                )
            self.signals.progress.emit(
                self.token,
                AnalysisProgress(
                    0.0,
                    AnalysisStage.DECODE,
                    "Preparing the current Track for analysis",
                ),
            )
            with TemporaryDirectory(prefix="iopenpod-synesthesia-") as directory:
                materialized = Path(directory) / (
                    "source" + _safe_media_suffix(source.file_name)
                )
                with materialized.open("wb") as output:
                    offset = 0
                    while offset < source.byte_count:
                        checkpoint()
                        requested = min(
                            _COPY_CHUNK_BYTES,
                            source.byte_count - offset,
                        )
                        payload = source.read_at(offset, requested)
                        if not payload or len(payload) > requested:
                            raise PlaybackSourceError(
                                "The current Track changed while its media was being read."
                            )
                        output.write(payload)
                        offset += len(payload)
                checkpoint()
                result = self.backend.analyze(
                    materialized,
                    self.request,
                    checkpoint=checkpoint,
                    progress=lambda value: self.signals.progress.emit(
                        self.token, value
                    ),
                )
                checkpoint()
        except Exception as error:
            self.signals.failed.emit(self.token, error)
        else:
            self.signals.succeeded.emit(self.token, result)
        finally:
            self.signals.finished.emit(self.token)


@dataclass(slots=True)
class _PreparedAnalysis:
    entry: PlaybackEntry
    request: AnalysisRequest
    token: int | None
    analysis: TrackAnalysis | None = None


class SynesthesiaController(QObject):
    """Analyze a requested Track without owning or changing audio playback."""

    analysisChanged = Signal(object)
    progressChanged = Signal(object)
    busyChanged = Signal(bool)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(
        self,
        backend: MusicAnalysisBackend,
        source_provider: PlaybackSourceProvider,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend
        self._source_provider = source_provider
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._jobs: dict[int, _AnalysisWork] = {}
        self._token = 0
        self._active_token: int | None = None
        self._analysis: TrackAnalysis | None = None
        self._prepared: _PreparedAnalysis | None = None
        self._track: Track | None = None
        self._busy = False
        self._closed = False

    @property
    def analysis(self) -> TrackAnalysis | None:
        return self._analysis

    @property
    def track(self) -> Track | None:
        return self._track

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def prepared_entry_id(self) -> int | None:
        """Return the next occurrence with a completed in-memory analysis."""

        prepared = self._prepared
        return (
            prepared.entry.entry_id
            if prepared is not None and prepared.analysis is not None
            else None
        )

    def analyze(
        self,
        track: Track,
        request: AnalysisRequest | None = None,
        *,
        entry_id: int | None = None,
    ) -> bool:
        """Analyze the current occurrence, promoting matching preparation."""

        if self._closed:
            return False
        request = request or AnalysisRequest(title=track.title.strip() or None)
        prepared = self._prepared
        if prepared is not None and (
            prepared.entry.entry_id != entry_id
            or prepared.entry.track != track
            or prepared.request != request
        ):
            prepared = None
        self._discard_jobs(keep_token=prepared.token if prepared else None)
        self._prepared = None
        self._active_token = None
        self._track = track
        self._analysis = None
        self.analysisChanged.emit(None)
        if prepared is not None and prepared.analysis is not None:
            self._analysis = prepared.analysis
            self._set_busy(False)
            self.analysisChanged.emit(self._analysis)
            return True
        if prepared is not None and prepared.token in self._jobs:
            self._active_token = prepared.token
            self._set_busy(True)
            return True
        work = self._create_work(track, request)
        self._active_token = work.token
        self._set_busy(True)
        self._pool.start(work)
        return True

    def prepare_next(self, entry: PlaybackEntry | None) -> None:
        """Quietly prepare one upcoming occurrence behind current analysis."""

        if self._closed:
            return
        if self._prepared is not None and self._prepared.entry == entry:
            return
        self._discard_prepared()
        if entry is None or self._track is None:
            return
        request = AnalysisRequest(title=entry.track.title.strip() or None)
        work = self._create_work(entry.track, request)
        self._prepared = _PreparedAnalysis(entry, request, work.token)
        self._pool.start(work)

    def _create_work(self, track: Track, request: AnalysisRequest) -> _AnalysisWork:
        self._token += 1
        token = self._token
        work = _AnalysisWork(
            token,
            self._backend,
            self._source_provider,
            track,
            request,
        )
        work.signals.progress.connect(self._analysis_progress)
        work.signals.succeeded.connect(self._analysis_succeeded)
        work.signals.failed.connect(self._analysis_failed)
        work.signals.finished.connect(self._analysis_finished)
        self._jobs[token] = work
        return work

    @Slot()
    def cancel(self) -> None:
        self._discard_prepared()
        if self._active_token is None:
            return
        job = self._jobs.get(self._active_token)
        if job is not None:
            job.cancelled.set()

    @Slot()
    def clear(self) -> None:
        """Invalidate current analysis while any obsolete worker winds down."""

        if self._closed:
            return
        self._discard_jobs()
        self._prepared = None
        self._token += 1
        self._active_token = None
        self._track = None
        self._analysis = None
        self.analysisChanged.emit(None)
        self._set_busy(False)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._discard_jobs()
        self._prepared = None
        self._pool.waitForDone()
        self._active_token = None
        self._track = None
        self._analysis = None
        self._busy = False

    @Slot(int, object)
    def _analysis_progress(self, token: int, value: object) -> None:
        if token == self._active_token and isinstance(value, AnalysisProgress):
            self.progressChanged.emit(value)

    @Slot(int, object)
    def _analysis_succeeded(self, token: int, value: object) -> None:
        if not isinstance(value, TrackAnalysis):
            return
        if self._prepared is not None and token == self._prepared.token:
            self._prepared.analysis = value
            return
        if token != self._active_token:
            return
        self._analysis = value
        self.analysisChanged.emit(value)

    @Slot(int, object)
    def _analysis_failed(self, token: int, value: object) -> None:
        if token != self._active_token:
            return
        if isinstance(value, AnalysisCancelledError):
            self.cancelled.emit()
            return
        error = value if isinstance(value, Exception) else RuntimeError(str(value))
        self.failed.emit(str(error) or type(error).__name__)

    @Slot(int)
    def _analysis_finished(self, token: int) -> None:
        self._jobs.pop(token, None)
        if self._prepared is not None and token == self._prepared.token:
            self._prepared.token = None
        if token != self._active_token:
            return
        self._active_token = None
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        if busy == self._busy:
            return
        self._busy = busy
        self.busyChanged.emit(busy)

    def _discard_prepared(self) -> None:
        prepared = self._prepared
        self._prepared = None
        if prepared is not None and prepared.token is not None:
            job = self._jobs.pop(prepared.token, None)
            if job is not None:
                job.cancelled.set()

    def _discard_jobs(self, *, keep_token: int | None = None) -> None:
        """Cancel running work and remove obsolete work that has not started."""

        for token, job in tuple(self._jobs.items()):
            if token != keep_token:
                job.cancelled.set()
                del self._jobs[token]
        # The promoted worker may still be queued behind a cancelled worker.
        # Clearing the pool here would silently delete that prepared Job.
        if keep_token is None:
            self._pool.clear()


def _safe_media_suffix(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if (
        not suffix
        or len(suffix) > 12
        or any(not (character.isalnum() or character == ".") for character in suffix)
    ):
        return ".audio"
    return suffix


__all__ = ["AnalysisCancelledError", "SynesthesiaController"]
