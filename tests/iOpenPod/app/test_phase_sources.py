"""Source boundary validation does not require models or network access."""

import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from numpy.typing import NDArray

from iOpenPod.app import phase_sources
from iOpenPod.app.phase_activity import PhaseActivity, PhaseStage
from iOpenPod.app.phase_sources import DemucsPhaseSources


def fake_version(_distribution_name: str) -> str:
    return "test"


@pytest.mark.parametrize(
    "pcm,rate,channels",
    [
        (b"", 22050, 1),
        (b"bad", 44100, 2),
        (np.array([np.nan], dtype="<f4").tobytes(), 22050, 1),
        (bytes(16), 48000, 2),
        (bytes(16), 22050, 3),
    ],
)
def test_invalid_separation_input_is_rejected_before_loading_a_model(
    pcm: bytes, rate: int, channels: int
) -> None:
    with pytest.raises(ValueError, match="Phase separation"):
        DemucsPhaseSources().analyze(
            pcm, sample_rate=rate, channels=channels, checkpoint=lambda: None
        )


def test_cancelled_separation_does_not_load_a_model() -> None:
    def cancel() -> None:
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        DemucsPhaseSources().analyze(
            bytes(16), sample_rate=22050, channels=1, checkpoint=cancel
        )


def test_late_invalid_samples_are_rejected_before_loading_a_model() -> None:
    samples = np.zeros(22_050 * 11, dtype="<f4")
    samples[-1] = np.nan
    with pytest.raises(ValueError, match="PCM samples"):
        DemucsPhaseSources().analyze(
            samples.tobytes(), sample_rate=22_050, channels=1, checkpoint=lambda: None
        )


def test_long_input_validation_can_be_cancelled_between_blocks() -> None:
    calls = 0

    def cancel_after_first_block() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("cancelled during validation")

    with pytest.raises(RuntimeError, match="cancelled during validation"):
        DemucsPhaseSources().analyze(
            bytes(22_050 * 11 * 4),
            sample_rate=22_050,
            channels=1,
            checkpoint=cancel_after_first_block,
        )


def test_pinned_checkpoint_bypasses_hugging_face_alias_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def alias_lookup(name: str) -> None:
        raise AssertionError("Pinned checkpoint entered Hugging Face alias lookup")

    class Repository:
        def __init__(self, urls: dict[str, str]) -> None:
            calls.append(("urls", urls))

        def get_model(self, signature: str) -> object:
            calls.append(("signature", signature))
            return SimpleNamespace(eval=lambda: None, sources=[])

    for name, attributes in (
        ("torch", {}),
        ("demucs.apply", {}),
        ("demucs.pretrained", {"get_model": alias_lookup}),
        ("demucs.repo", {"RemoteRepo": Repository}),
    ):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    with pytest.raises(ValueError, match="six distinct"):
        DemucsPhaseSources().analyze(
            bytes(16), sample_rate=22050, channels=1, checkpoint=lambda: None
        )
    assert calls == [
        (
            "urls",
            {
                "5c90dfd2": "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th"
            },
        ),
        ("signature", "5c90dfd2"),
    ]


@pytest.mark.parametrize(
    "cuda,mps,expected",
    [(True, True, "cuda"), (False, True, "mps"), (False, False, "cpu")],
)
def test_backend_selection_uses_available_acceleration(
    monkeypatch: pytest.MonkeyPatch, cuda: bool, mps: bool, expected: str
) -> None:
    torch = ModuleType("torch")
    torch.__dict__.update(
        cuda=SimpleNamespace(is_available=lambda: cuda),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(phase_sources, "version", fake_version)
    source = DemucsPhaseSources()
    assert f"-{expected}-shifts0" in source.identity
    assert source.supports_mix_overlap is (expected == "cuda")


@pytest.mark.parametrize("accelerator", ["cuda", "mps"])
def test_failed_acceleration_restarts_on_cpu(
    monkeypatch: pytest.MonkeyPatch, accelerator: str
) -> None:
    class Tensor(np.ndarray):
        def cpu(self) -> "Tensor":
            return self

        def numpy(self) -> np.ndarray:
            return np.asarray(self)

    devices: list[str] = []

    def apply_model(
        _model: object, waveform: Tensor, *, device: str, **_kwargs: object
    ) -> Tensor:
        devices.append(device)
        if device != "cpu":
            raise RuntimeError("Accelerator ran out of memory")
        assert sys.exception() is None, "CPU retry retained the accelerator traceback"
        return np.repeat(waveform[:, None, :, :], 6, axis=1).view(Tensor)

    def from_numpy(array: NDArray[np.float32]) -> Tensor:
        return array.view(Tensor)

    def move_model(_device: str) -> None:
        return None

    torch = ModuleType("torch")
    torch.__dict__.update(
        from_numpy=from_numpy, inference_mode=nullcontext, Tensor=Tensor
    )
    apply = ModuleType("demucs.apply")
    apply.__dict__["apply_model"] = apply_model
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "demucs.apply", apply)
    monkeypatch.setattr(phase_sources, "version", fake_version)
    source = DemucsPhaseSources()
    source._device = accelerator  # pyright: ignore[reportPrivateUsage]
    source._model = SimpleNamespace(  # pyright: ignore[reportPrivateUsage]
        sources=["drums", "bass", "other", "vocals", "piano", "guitar"],
        samplerate=44_100,
        audio_channels=2,
        to=move_model,
    )
    times = np.arange(44_100, dtype=np.float32) / 44_100
    mono = np.sin(times * (2 * np.pi * 440)).astype("<f4") * 0.1
    pcm = np.column_stack((mono, mono)).astype("<f4").tobytes()
    activities: list[PhaseActivity] = []
    parts = source.analyze(
        pcm,
        sample_rate=44_100,
        channels=2,
        checkpoint=lambda: activities.append(source.activity),
    )
    assert len(parts) == 6
    assert devices == [accelerator, "cpu"]
    assert "-cpu-shifts0" in source.identity
    assert not source.supports_mix_overlap
    assert any(
        a.stage is PhaseStage.SOURCES and a.backend == accelerator for a in activities
    )
    assert activities[-1].backend == "cpu"
