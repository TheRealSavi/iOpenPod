"""Caller-owned Phase timing and translatable activity descriptions."""

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from iOpenPod.app.core.eta import EtaEstimate, EtaEstimator
from iOpenPod.app.display_text import source_text
from iOpenPod.app.phase_activity import PhaseActivity, PhaseStage


@dataclass(frozen=True, slots=True)
class PhaseProgress:
    completed: int
    total: int
    title: str
    activity: PhaseActivity
    eta: EtaEstimate

    @property
    def message(self) -> str:
        activity = self.activity
        labels = {
            PhaseStage.CAPTURING: source_text("Reading and checking audio"),
            PhaseStage.DECODING: source_text("Decoding audio with FFmpeg · CPU"),
            PhaseStage.LOADING: source_text("Loading Demucs htdemucs_6s"),
            PhaseStage.SOURCES: source_text("Demucs htdemucs_6s"),
            PhaseStage.ACOUSTIC: source_text("Acoustic analysis · librosa · CPU"),
            PhaseStage.COMBINING: source_text("Combining musical evidence · CPU"),
            PhaseStage.ENCODING: source_text("Building gameplay analysis · CPU"),
            PhaseStage.VERIFYING: source_text("Verifying audio"),
            PhaseStage.REUSING: source_text("Reusing verified analysis"),
            PhaseStage.FINALIZING: source_text("Finishing analysis"),
        }
        detail = labels[activity.stage]
        if activity.stage in (PhaseStage.LOADING, PhaseStage.SOURCES):
            backend = {
                "cuda": "CUDA",
                "mps": "GPU / MPS (Metal)",
                "cpu": "CPU",
            }.get(activity.backend, source_text("Selecting hardware"))
            if activity.device_name:
                backend = f"{activity.device_name} / {backend}"
            detail = source_text(
                "{method} · {hardware}", method=detail, hardware=backend
            )
            if activity.parallel_mix:
                detail = source_text("{method} + librosa · CPU", method=detail)
        return source_text(
            "Phase · {detail} · {completed}/{total} tracks",
            detail=detail,
            completed=str(self.completed),
            total=str(self.total),
        )


class PhaseProgressReporter:
    """Time completed audio duration, never synthetic within-song percentages."""

    def __init__(
        self,
        durations_ms: tuple[int, ...],
        report: Callable[[PhaseProgress], None],
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._durations = durations_ms
        self._report = report
        self._clock = clock
        self._total_ms = sum(durations_ms)
        self._eta = EtaEstimator(total=self._total_ms, clock=clock)
        self._completed = 0
        self._audio_ms = 0
        self._last: tuple[int, str, PhaseActivity] | None = None
        self._last_time = float("-inf")

    def emit(self, title: str, activity: PhaseActivity) -> None:
        now = self._clock()
        key = (self._completed, title, activity)
        if key == self._last and now - self._last_time < 1:
            return
        self._last, self._last_time = key, now
        self._report(
            PhaseProgress(
                self._completed,
                len(self._durations),
                title,
                activity,
                self._eta.snapshot(),
            )
        )

    def complete_track(self) -> None:
        self._audio_ms += self._durations[self._completed]
        self._completed += 1
        self._eta.update(self._audio_ms, total=self._total_ms)
