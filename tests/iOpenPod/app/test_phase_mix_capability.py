"""Mix scheduling uses successful live evidence, never installation identity."""

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from iOpenPod.app.phase_parts import PhasePart, PhasePartKind
from iOpenPod.app.phase_runtime import ManagedPhaseSources
from iOpenPod.app.phase_sources import DemucsPhaseSources, PhaseOverlapSources
from iOpenPod.app.phase_worker_session import PhaseWorkerSession
from iOpenPod.assets.phase_runtime import worker


def test_custom_source_without_capability_remains_compatible_and_serial() -> None:
    class CustomSource:
        @property
        def identity(self) -> str:
            return "custom-model-cuda-shifts0"

        def analyze(
            self,
            pcm: bytes,
            *,
            sample_rate: int,
            channels: int,
            checkpoint: Callable[[], None],
        ) -> tuple[PhasePart, ...]:
            return ()

    assert not isinstance(CustomSource(), PhaseOverlapSources)
    assert isinstance(DemucsPhaseSources(), PhaseOverlapSources)


@pytest.mark.parametrize("supported", [False, True])
def test_worker_response_reports_the_successful_sources_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, supported: bool
) -> None:
    (tmp_path / "audio.f32").write_bytes(bytes(8))
    requested = False

    class CompletedError(Exception):
        pass

    def take_request(_path: Path) -> bytes:
        nonlocal requested
        if requested:
            raise CompletedError
        requested = True
        return json.dumps(
            {"protocol": 2, "sequence": 1, "rate": 44100, "channels": 2}
        ).encode()

    def analyze(*_args: object, **_kwargs: object) -> tuple[PhasePart, ...]:
        return ()

    monkeypatch.setattr(worker, "_take_request", take_request)
    monkeypatch.setattr(DemucsPhaseSources, "analyze", analyze)
    monkeypatch.setattr(
        DemucsPhaseSources, "identity", property(lambda _source: "live-model")
    )
    monkeypatch.setattr(
        DemucsPhaseSources,
        "supports_mix_overlap",
        property(lambda _source: supported),
    )
    with pytest.raises(CompletedError):
        worker._serve(tmp_path)  # pyright: ignore[reportPrivateUsage]
    response = json.loads((tmp_path / "response.json").read_text())
    assert response == {
        "protocol": 2,
        "sequence": 1,
        "identity": "live-model",
        "supports_mix_overlap": supported,
    }


def evidence(path: Path, *, valid: bool = True) -> None:
    count = 1 + 22_050 // 256
    arrays = {
        f"{kind.value}_{field}": np.zeros(shape)
        for kind in PhasePartKind
        for field, shape in (
            ("bands", (3, count)),
            ("energy", (count if valid else count + 1,)),
            ("chroma", (12, count)),
            ("magnitudes", (3, count)),
        )
    }
    np.savez(path, allow_pickle=False, **arrays)


def test_managed_capability_requires_valid_live_evidence_and_resets_per_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "parts.npz"
    evidence(output)
    capability = False

    def request(
        _session: PhaseWorkerSession, _pcm: bytes, **_kwargs: object
    ) -> tuple[Path, str]:
        return output, "same-model-identity"

    monkeypatch.setattr(PhaseWorkerSession, "request", request)
    monkeypatch.setattr(
        PhaseWorkerSession,
        "last_supports_mix_overlap",
        property(lambda _session: capability),
    )
    installed = ManagedPhaseSources(tmp_path, "installation-model-cuda-shifts0")
    source = installed.for_analysis()
    assert isinstance(source, PhaseOverlapSources)
    assert not installed.supports_mix_overlap and not source.supports_mix_overlap
    try:
        for capability in (True, False, True):
            parts = source.analyze(
                bytes(44_100 * 2 * 4),
                sample_rate=44_100,
                channels=2,
                checkpoint=lambda: None,
            )
            assert len(parts) == 6
            assert source.supports_mix_overlap is capability
            assert source.identity == "managed-v1:same-model-identity"
        next_preparation = source.for_analysis()
        assert not next_preparation.supports_mix_overlap
    finally:
        source.close()
    assert not source.supports_mix_overlap


@pytest.mark.parametrize("failure", ["evidence", "checkpoint"])
def test_failed_managed_validation_does_not_enable_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    output = tmp_path / "parts.npz"
    evidence(output, valid=failure != "evidence")
    responded = False
    cancelled = InterruptedError("cancelled after worker response")

    def request(
        _session: PhaseWorkerSession, _pcm: bytes, **_kwargs: object
    ) -> tuple[Path, str]:
        nonlocal responded
        responded = True
        return output, "actual-cuda"

    def checkpoint() -> None:
        if failure == "checkpoint" and responded:
            raise cancelled

    monkeypatch.setattr(PhaseWorkerSession, "request", request)
    monkeypatch.setattr(
        PhaseWorkerSession, "last_supports_mix_overlap", property(lambda _session: True)
    )
    source = ManagedPhaseSources(tmp_path, "installation-cuda").for_analysis()
    with pytest.raises((ValueError, InterruptedError)) as caught:
        source.analyze(
            bytes(44_100 * 2 * 4),
            sample_rate=44_100,
            channels=2,
            checkpoint=checkpoint,
        )
    if failure == "checkpoint":
        assert caught.value is cancelled
    assert not source.supports_mix_overlap
    assert source.identity == "managed-v1:installation-cuda"
