"""CUDA scheduling preserves evidence, bounded work, and Track cancellation."""

from __future__ import annotations

import sys
from contextlib import nullcontext
from dataclasses import dataclass, field
from threading import Event, Thread, get_ident
from threading import enumerate as enumerate_threads
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING

import librosa
import numpy as np
import pytest

from iOpenPod.app import phase_sources
from iOpenPod.app.phase_parts import HOP, PhasePart
from iOpenPod.app.phase_sources import DemucsPhaseSources

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray


class Tensor(np.ndarray[tuple[int, ...], np.dtype[np.float32]]):
    def cpu(self) -> Tensor:
        return self

    def numpy(self) -> NDArray[np.float32]:
        return np.asarray(self)


def ignore_inference(_device: str, _count: int) -> None:
    pass


def ignore_measurement() -> None:
    pass


def move_model(_device: str) -> None:
    pass


def from_numpy(array: NDArray[np.float32]) -> Tensor:
    return array.view(Tensor)


def resample(samples: NDArray[np.float32], **_kwargs: object) -> NDArray[np.float32]:
    return samples[..., ::2]


@dataclass
class SourceHarness:
    calls: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    on_inference: Callable[[str, int], None] = ignore_inference
    on_measurement: Callable[[], None] = ignore_measurement

    def apply_model(
        self, _model: object, waveform: Tensor, *, device: str, **_kwargs: object
    ) -> Tensor:
        self.calls.append((device, get_ident()))
        self.on_inference(device, sum(call[0] == device for call in self.calls))
        return np.repeat(waveform[:, None, :, :], 6, axis=1).view(Tensor)

    def measure(
        self, samples: NDArray[np.float32]
    ) -> tuple[
        NDArray[np.float64],
        NDArray[np.float64],
        NDArray[np.float64],
        NDArray[np.float64],
    ]:
        self.on_measurement()
        positions = np.minimum(
            np.arange(1 + len(samples) // HOP) * HOP, len(samples) - 1
        )
        energy = np.abs(samples[positions]).astype(np.float64)
        return (
            np.broadcast_to(energy, (3, len(energy))).copy(),
            energy,
            np.broadcast_to(energy, (12, len(energy))).copy(),
            np.broadcast_to(energy, (3, len(energy))).copy(),
        )

    def source(self, device: str) -> DemucsPhaseSources:
        source = DemucsPhaseSources()
        source._device = device  # pyright: ignore[reportPrivateUsage]
        source._model = SimpleNamespace(  # pyright: ignore[reportPrivateUsage]
            sources=["drums", "bass", "other", "vocals", "piano", "guitar"],
            samplerate=44_100,
            audio_channels=2,
            to=move_model,
        )
        return source


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> SourceHarness:
    state = SourceHarness()
    torch = ModuleType("torch")
    torch.__dict__.update(from_numpy=from_numpy, inference_mode=nullcontext)
    apply = ModuleType("demucs.apply")
    apply.__dict__["apply_model"] = state.apply_model
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "demucs.apply", apply)
    monkeypatch.setattr(phase_sources, "measure_part", state.measure)
    monkeypatch.setattr(librosa, "resample", resample)
    return state


@pytest.fixture
def pcm() -> bytes:
    # Four nonempty inference sections, with a short final section.
    mono = np.linspace(-0.5, 0.5, 44_100 * 13, dtype="<f4")
    return np.column_stack((mono, mono)).tobytes()


def run(
    source: DemucsPhaseSources,
    pcm: bytes,
    checkpoint: Callable[[], None] = lambda: None,
) -> tuple[PhasePart, ...]:
    return source.analyze(pcm, sample_rate=44_100, channels=2, checkpoint=checkpoint)


def assert_equal(before: tuple[PhasePart, ...], after: tuple[PhasePart, ...]) -> None:
    for a, b in zip(before, after, strict=True):
        assert a.kind == b.kind
        for name in ("bands", "energy", "chroma", "magnitudes"):
            np.testing.assert_array_equal(getattr(a, name), getattr(b, name))


def assert_joined() -> None:
    assert not any(
        thread.name.startswith("phase-features") for thread in enumerate_threads()
    )


@pytest.mark.parametrize("device", ["cpu", "mps", "cuda"])
def test_backends_preserve_evidence_and_caller_owned_checkpoints(
    harness: SourceHarness, pcm: bytes, device: str
) -> None:
    before = run(harness.source("cpu"), pcm)
    caller = get_ident()
    feature_threads: set[int] = set()
    harness.on_measurement = lambda: feature_threads.add(get_ident())

    def checkpoint() -> None:
        assert get_ident() == caller

    after = run(harness.source(device), pcm, checkpoint)
    assert_equal(before, after)
    assert all(thread == caller for _device, thread in harness.calls)
    assert (caller not in feature_threads) == (device == "cuda")
    assert_joined()


def test_overlap_bounds_admission_while_feature_block_is_busy(
    harness: SourceHarness, pcm: bytes
) -> None:
    started, release, second, third = Event(), Event(), Event(), Event()
    failures: list[BaseException] = []

    def measure() -> None:
        started.set()
        assert release.wait(5)

    def inference(_device: str, count: int) -> None:
        if count == 2:
            assert started.wait(5)
            second.set()
        if count == 3:
            third.set()

    harness.on_measurement = measure
    harness.on_inference = inference

    def analyze() -> None:
        try:
            run(harness.source("cuda"), pcm)
        except BaseException as exc:
            failures.append(exc)

    caller = Thread(target=analyze)
    caller.start()
    try:
        assert second.wait(5), "CPU features did not overlap the second GPU call"
        assert not third.wait(0.05), (
            "More blocks were admitted while features were pending"
        )
    finally:
        release.set()
        caller.join(5)
    assert not caller.is_alive()
    assert not failures
    assert third.is_set()
    assert_joined()


def test_cancellation_is_checked_while_waiting_for_features(
    harness: SourceHarness, pcm: bytes
) -> None:
    started, release = Event(), Event()
    checks_after_second_inference = 0

    def measure() -> None:
        started.set()
        assert release.wait(5)

    def inference(_device: str, count: int) -> None:
        if count == 2:
            assert started.wait(5)

    def checkpoint() -> None:
        nonlocal checks_after_second_inference
        if len(harness.calls) == 2:
            checks_after_second_inference += 1
            # Skip the ordinary post-inference checkpoint, then cancel in the wait loop.
            if checks_after_second_inference == 2:
                release.set()
                raise RuntimeError("cancel while awaiting features")

    harness.on_measurement = measure
    harness.on_inference = inference
    try:
        with pytest.raises(RuntimeError, match="cancel while awaiting features"):
            run(harness.source("cuda"), pcm, checkpoint)
    finally:
        release.set()
    assert len(harness.calls) == 2
    assert_joined()


def test_late_cuda_failure_drains_features_before_complete_cpu_retry(
    harness: SourceHarness, pcm: bytes
) -> None:
    expected = run(harness.source("cpu"), pcm)
    cpu_calls = len(harness.calls)
    harness.calls.clear()

    def inference(device: str, count: int) -> None:
        if device == "cuda" and count == 3:
            raise RuntimeError("injected late CUDA failure")
        if device == "cpu":
            assert_joined()
            assert sys.exception() is None

    harness.on_inference = inference
    source = harness.source("cuda")
    actual = run(source, pcm)
    assert_equal(expected, actual)
    assert [device for device, _thread in harness.calls] == ["cuda"] * 3 + [
        "cpu"
    ] * cpu_calls
    assert source._device == "cpu"  # pyright: ignore[reportPrivateUsage]
    assert_joined()


@pytest.mark.parametrize("error_type", [ValueError, TimeoutError])
def test_feature_errors_propagate_and_join_the_worker(
    harness: SourceHarness, pcm: bytes, error_type: type[Exception]
) -> None:
    def fail() -> None:
        raise error_type("source feature failure")

    harness.on_measurement = fail
    with pytest.raises(error_type, match="source feature failure"):
        run(harness.source("cuda"), pcm)
    assert all(device == "cuda" for device, _thread in harness.calls)
    assert_joined()
