"""Whole-mix and optional source overlap has explicit ownership and fallbacks."""

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Event, get_ident

import librosa
import numpy as np
import pytest
from numpy.typing import NDArray

from iOpenPod.app import phase_analysis
from iOpenPod.app.phase_analysis import PhaseAnalysisService
from iOpenPod.app.phase_audio import PhaseMixEvidence
from iOpenPod.app.phase_parts import PhasePart, PhasePartKind
from iPodDB.games import PhaseChart
from storage import FilesystemSession, HostPath, Storage
from storage.testing import VirtualStoragePlatform


@pytest.fixture
def session(tmp_path: Path) -> Iterator[FilesystemSession]:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(storage.discover().volumes[0]) as result:
        yield result


class Decoder:
    def decode(self, *_args: object, **_kwargs: object) -> bytes:
        return bytes(30 * 22_050 * 4)


class Provider:
    identity = "test-cuda"
    supports_mix_overlap = True

    def __init__(self, action: Callable[[Callable[[], None]], None]) -> None:
        self.action = action
        self.calls: list[int] = []
        self.formats: list[tuple[int, int]] = []
        count = 1 + 30 * 22_050 // 256
        self.parts = (
            PhasePart(
                PhasePartKind.GUITAR,
                np.zeros((3, count)),
                np.zeros(count),
                np.zeros((12, count)),
                np.zeros((3, count)),
            ),
        )

    def analyze(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        checkpoint: Callable[[], None],
    ) -> tuple[PhasePart, ...]:
        self.calls.append(get_ident())
        self.formats.append((sample_rate, channels))
        assert len(pcm) == 30 * sample_rate * channels * 4
        self.action(checkpoint)
        return self.parts


def run(
    service: PhaseAnalysisService,
    session: FilesystemSession,
    checkpoint: Callable[[], None] = lambda: None,
) -> bytes:
    return service.analyze(
        HostPath(Path.cwd() / "unused.wav"),
        input_suffix=".wav",
        length_ms=30_000,
        session=session,
        checkpoint=checkpoint,
    )


def test_mix_measurement_runs_while_provider_is_active_on_the_caller(
    session: FilesystemSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mix_started, provider_started = Event(), Event()
    caller = get_ident()
    mix_threads: list[int] = []
    evidence = PhaseMixEvidence(30_000, 1 + 30 * 22_050 // 256)

    def source(checkpoint: Callable[[], None]) -> None:
        provider_started.set()
        assert mix_started.wait(3), "Whole-mix work did not overlap source analysis"
        checkpoint()

    provider = Provider(source)

    def measure(_pcm: bytes, **_kwargs: object) -> PhaseMixEvidence:
        mix_threads.append(get_ident())
        mix_started.set()
        assert provider_started.wait(3)
        return evidence

    def finish(
        observed: PhaseMixEvidence,
        *,
        parts: tuple[PhasePart, ...],
        checkpoint: Callable[[], None],
    ) -> PhaseChart:
        assert observed is evidence and parts is provider.parts
        assert get_ident() == caller
        checkpoint()
        return PhaseChart()

    monkeypatch.setattr(phase_analysis, "measure_phase_mix", measure, raising=False)
    monkeypatch.setattr(phase_analysis, "finish_phase_analysis", finish, raising=False)
    monkeypatch.setattr(
        phase_analysis, "available_compute_threads", lambda: 8, raising=False
    )
    result = run(
        PhaseAnalysisService(decoder=Decoder(), source_analyzer=provider), session
    )
    assert result.startswith(b"pha\x02")
    assert provider.calls == [caller]
    assert len(mix_threads) == 1 and mix_threads[0] != caller


class Mix:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.started = Event()
        self.exited = Event()
        self.threads: list[int] = []
        self.finished: list[tuple[PhasePart, ...]] = []
        self.serial: list[tuple[PhasePart, ...]] = []
        self.evidence = PhaseMixEvidence(30_000, 1 + 30 * 22_050 // 256)
        self.action: Callable[[Callable[[], None]], None] = lambda check: check()
        monkeypatch.setattr(phase_analysis, "measure_phase_mix", self.measure)
        monkeypatch.setattr(phase_analysis, "finish_phase_analysis", self.finish)
        monkeypatch.setattr(phase_analysis, "analyze_phase_pcm", self.analyze_serial)
        monkeypatch.setattr(phase_analysis, "available_compute_threads", lambda: 8)

    def measure(
        self,
        _pcm: bytes,
        *,
        checkpoint: Callable[[], None],
        **_kwargs: object,
    ) -> PhaseMixEvidence:
        self.threads.append(get_ident())
        self.started.set()
        try:
            self.action(checkpoint)
            return self.evidence
        finally:
            self.exited.set()

    def finish(
        self,
        evidence: PhaseMixEvidence,
        *,
        parts: tuple[PhasePart, ...],
        checkpoint: Callable[[], None],
    ) -> PhaseChart:
        assert evidence is self.evidence and self.exited.is_set()
        checkpoint()
        self.finished.append(parts)
        return PhaseChart()

    def analyze_serial(
        self,
        _pcm: bytes,
        *,
        parts: tuple[PhasePart, ...],
        checkpoint: Callable[[], None],
        **_kwargs: object,
    ) -> PhaseChart:
        checkpoint()
        self.serial.append(parts)
        return PhaseChart()


@pytest.mark.parametrize(
    "error", [ValueError("invalid mix"), MemoryError("DSP memory")]
)
def test_mix_failure_propagates_without_optional_fallback(
    session: FilesystemSession, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    mix = Mix(monkeypatch)
    source_started = Event()

    def measure(_checkpoint: Callable[[], None]) -> None:
        assert source_started.wait(3)
        raise error

    def source(checkpoint: Callable[[], None]) -> None:
        source_started.set()
        assert mix.exited.wait(3)
        checkpoint()

    mix.action = measure
    provider = Provider(source)
    service = PhaseAnalysisService(decoder=Decoder(), source_analyzer=provider)
    with pytest.raises(type(error)) as caught:
        run(service, session)
    assert caught.value is error
    assert mix.exited.is_set()
    assert not mix.finished and not mix.serial
    assert "test-cuda" in service.identity


def test_user_cancellation_preserves_identity_and_joins_background_measurement(
    session: FilesystemSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mix = Mix(monkeypatch)
    cancel, worker_stopped = Event(), Event()
    cancellation = RuntimeError("Active iPod disconnected")
    callback_threads: list[int] = []

    def measure(checkpoint: Callable[[], None]) -> None:
        deadline = time.monotonic() + 3
        try:
            while time.monotonic() < deadline:
                checkpoint()
                time.sleep(0.001)
        except Exception:
            worker_stopped.set()
            raise
        pytest.fail("Background measurement did not receive its stop signal")

    def source(checkpoint: Callable[[], None]) -> None:
        assert mix.started.wait(3)
        cancel.set()
        checkpoint()

    def checkpoint() -> None:
        callback_threads.append(get_ident())
        if cancel.is_set():
            raise cancellation

    mix.action = measure
    provider = Provider(source)
    service = PhaseAnalysisService(decoder=Decoder(), source_analyzer=provider)
    with pytest.raises(RuntimeError) as caught:
        run(service, session, checkpoint)
    assert caught.value is cancellation
    assert worker_stopped.is_set() and mix.exited.is_set()
    assert set(callback_threads) == {get_ident()}
    assert provider.calls == [get_ident()]
    assert not mix.finished and not mix.serial
    assert "test-cuda" in service.identity


def test_cancellation_while_waiting_for_mix_after_provider_returns_joins_worker(
    session: FilesystemSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mix = Mix(monkeypatch)
    provider_returned, worker_stopped = Event(), Event()
    cancellation = InterruptedError("Cancelled while finishing whole-mix work")

    def measure(checkpoint: Callable[[], None]) -> None:
        deadline = time.monotonic() + 3
        try:
            while time.monotonic() < deadline:
                checkpoint()
                time.sleep(0.001)
        except Exception:
            worker_stopped.set()
            raise
        pytest.fail("Background measurement did not receive its stop signal")

    def source(_checkpoint: Callable[[], None]) -> None:
        assert mix.started.wait(3)
        provider_returned.set()

    def checkpoint() -> None:
        if provider_returned.is_set():
            raise cancellation

    mix.action = measure
    provider = Provider(source)
    service = PhaseAnalysisService(decoder=Decoder(), source_analyzer=provider)
    with pytest.raises(InterruptedError) as caught:
        run(service, session, checkpoint)
    assert caught.value is cancellation
    assert worker_stopped.is_set() and mix.exited.is_set()
    assert not mix.finished and not mix.serial


@pytest.mark.parametrize(
    "error", [RuntimeError("model failed"), MemoryError("model memory")]
)
def test_optional_provider_failure_keeps_mix_and_falls_back_for_later_tracks(
    session: FilesystemSession, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    mix = Mix(monkeypatch)
    provider_failed = Event()

    def measure(checkpoint: Callable[[], None]) -> None:
        assert provider_failed.wait(3)
        checkpoint()

    def source(_checkpoint: Callable[[], None]) -> None:
        assert mix.started.wait(3)
        provider_failed.set()
        raise error

    mix.action = measure
    provider = Provider(source)
    service = PhaseAnalysisService(decoder=Decoder(), source_analyzer=provider)
    assert run(service, session).startswith(b"pha\x02")
    assert mix.exited.is_set() and mix.finished == [()]
    assert len(mix.threads) == 1 and not mix.serial
    assert ":acoustic:" in service.identity
    assert run(service, session).startswith(b"pha\x02")
    assert provider.calls == [get_ident()]
    assert len(mix.threads) == 1 and mix.serial == [()]


@pytest.mark.parametrize("gate", ["cpu", "memory", "capability"])
def test_resource_or_capability_gate_keeps_analysis_serial(
    session: FilesystemSession, monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    mix = Mix(monkeypatch)

    def source(checkpoint: Callable[[], None]) -> None:
        assert not mix.started.is_set()
        checkpoint()

    provider = Provider(source)
    if gate == "cpu":
        monkeypatch.setattr(phase_analysis, "available_compute_threads", lambda: 3)
    elif gate == "memory":
        monkeypatch.setattr(phase_analysis, "_OVERLAP_PCM_LIMIT", 30 * 22_050 * 4 - 1)
    else:
        provider.supports_mix_overlap = False
    service = PhaseAnalysisService(decoder=Decoder(), source_analyzer=provider)
    assert run(service, session).startswith(b"pha\x02")
    assert provider.calls == [get_ident()]
    assert not mix.threads and not mix.finished
    assert mix.serial == [provider.parts]


def test_minimum_cpu_and_pcm_limit_boundaries_allow_overlap(
    session: FilesystemSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mix = Mix(monkeypatch)
    monkeypatch.setattr(phase_analysis, "available_compute_threads", lambda: 4)
    monkeypatch.setattr(phase_analysis, "_OVERLAP_PCM_LIMIT", 30 * 22_050 * 4)

    def source(checkpoint: Callable[[], None]) -> None:
        assert mix.started.wait(3)
        checkpoint()

    provider = Provider(source)
    service = PhaseAnalysisService(decoder=Decoder(), source_analyzer=provider)
    assert run(service, session).startswith(b"pha\x02")
    assert mix.finished == [provider.parts] and not mix.serial
    assert len(mix.threads) == 1 and mix.threads[0] != get_ident()


def test_provider_cpu_retry_disables_overlap_on_the_next_track(
    session: FilesystemSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mix = Mix(monkeypatch)

    def source(checkpoint: Callable[[], None]) -> None:
        if len(provider.calls) == 1:
            assert mix.started.wait(3)
            provider.supports_mix_overlap = False
        checkpoint()

    provider = Provider(source)
    service = PhaseAnalysisService(decoder=Decoder(), source_analyzer=provider)
    assert run(service, session).startswith(b"pha\x02")
    assert run(service, session).startswith(b"pha\x02")
    assert provider.calls == [get_ident(), get_ident()]
    assert len(mix.threads) == 1
    assert mix.finished == [provider.parts] and mix.serial == [provider.parts]


def test_stereo_conversion_finishes_before_concurrent_stages_begin(
    session: FilesystemSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mix = Mix(monkeypatch)
    resampled = Event()
    caller = get_ident()
    samples = np.empty((30 * 44_100, 2), dtype="<f4")
    samples[:, 0] = 0.25
    samples[:, 1] = 0.75
    stereo = samples.tobytes()

    class StereoDecoder:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def decode(self, *_args: object, **_kwargs: object) -> bytes:
            return stereo

    def source(checkpoint: Callable[[], None]) -> None:
        assert resampled.is_set()
        assert mix.started.wait(3)
        checkpoint()

    provider = Provider(source)

    def resample(
        audio: NDArray[np.float32], *, orig_sr: int, target_sr: int
    ) -> NDArray[np.float32]:
        assert get_ident() == caller
        assert not mix.started.is_set() and not provider.calls
        assert (orig_sr, target_sr) == (44_100, 22_050)
        assert audio.ndim == 1 and np.all(audio == 0.5)
        resampled.set()
        return audio[::2]

    def measure(
        pcm: bytes, *, checkpoint: Callable[[], None], **kwargs: object
    ) -> PhaseMixEvidence:
        assert resampled.is_set()
        assert len(pcm) == 30 * 22_050 * 4
        assert np.all(np.frombuffer(pcm, dtype="<f4") == 0.5)
        return mix.measure(pcm, checkpoint=checkpoint, **kwargs)

    monkeypatch.setattr(phase_analysis, "FFmpegGeniusPCMDecoder", StereoDecoder)
    monkeypatch.setattr(librosa, "resample", resample)
    monkeypatch.setattr(phase_analysis, "measure_phase_mix", measure)
    service = PhaseAnalysisService(source_analyzer=provider)
    assert run(service, session).startswith(b"pha\x02")
    assert provider.formats == [(44_100, 2)]
    assert mix.finished == [provider.parts] and not mix.serial
