"""Source boundary validation does not require models or network access."""

import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from iOpenPod.app.phase_sources import DemucsPhaseSources


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
