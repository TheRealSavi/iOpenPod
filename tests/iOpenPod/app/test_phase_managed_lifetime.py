"""Preparation ownership releases workers on success, fallback and bad results."""

import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from iOpenPod.app.phase_analysis import PhaseAnalysisService
from iOpenPod.app.phase_parts import PhasePartKind
from iOpenPod.app.phase_runtime import ManagedPhaseSources
from iOpenPod.app.phase_worker_session import PhaseWorkerSession


@pytest.mark.parametrize("invalid", ["missing", "archive", "duration", "nonfinite"])
def test_invalid_evidence_closes_the_worker_before_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    closed: list[object] = []

    def request(_session: object, _pcm: bytes, **_kwargs: object) -> tuple[Path, str]:
        path = tmp_path / "parts.npz"
        if invalid == "archive":
            path.write_bytes(b"invalid archive")
        elif invalid != "missing":
            count = 87 if invalid != "duration" else 88
            arrays = {
                f"{kind.value}_{field}": np.zeros(shape)
                for kind in PhasePartKind
                for field, shape in (
                    ("bands", (3, count)),
                    ("energy", (count,)),
                    ("chroma", (12, count)),
                    ("magnitudes", (3, count)),
                )
            }
            if invalid == "nonfinite":
                arrays["drums_energy"][0] = np.nan
            np.savez(path, allow_pickle=False, **arrays)
        return path, "test-cpu"

    monkeypatch.setattr(PhaseWorkerSession, "request", request)

    def close(session: object) -> None:
        closed.append(session)

    monkeypatch.setattr(PhaseWorkerSession, "close", close)
    source = ManagedPhaseSources(tmp_path, "test")
    with pytest.raises((ValueError, OSError, zipfile.BadZipFile)):
        source.analyze(
            bytes(44_100 * 2 * 4),
            sample_rate=44_100,
            channels=2,
            checkpoint=lambda: None,
        )
    assert len(closed) == 1
    source.close()
    assert len(closed) == 1


def test_explicit_managed_source_is_owned_by_each_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[ManagedPhaseSources] = []

    def close(source: ManagedPhaseSources) -> None:
        closed.append(source)

    monkeypatch.setattr(ManagedPhaseSources, "close", close)
    original = ManagedPhaseSources(tmp_path, "test-cpu")
    service = PhaseAnalysisService(source_analyzer=original)
    first, second = service.for_analysis(), service.for_analysis()
    first.close()
    second.close()
    assert len(closed) == 2
    assert closed[0] is not closed[1]
    assert all(source is not original for source in closed)
    assert all(source.identity == original.identity for source in closed)


def test_managed_identity_failure_closes_worker_before_discarding_source(
    tmp_path: Path,
) -> None:
    closed: list[bool] = []

    class BrokenIdentity(ManagedPhaseSources):
        @property
        def identity(self) -> str:
            raise RuntimeError("worker unavailable")

        def close(self) -> None:
            closed.append(True)

    service = PhaseAnalysisService(source_analyzer=BrokenIdentity(tmp_path, "test"))
    assert ":acoustic:" in service.identity
    assert closed == [True]


def test_managed_request_is_cancelled_before_starting_next_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launched: list[bytes] = []

    def request(
        _session: object,
        pcm: bytes,
        *,
        checkpoint: Callable[[], None],
        **_kwargs: object,
    ) -> tuple[Path, str]:
        launched.append(pcm)
        checkpoint()
        raise AssertionError("cancelled request reached the worker")

    monkeypatch.setattr(PhaseWorkerSession, "request", request)

    def cancel() -> None:
        raise InterruptedError("cancelled")

    source = ManagedPhaseSources(tmp_path, "test")
    with pytest.raises(InterruptedError, match="cancelled"):
        source.analyze(bytes(8), sample_rate=44100, channels=2, checkpoint=cancel)
    assert not launched


@pytest.mark.parametrize("retain", [False, True])
def test_only_preparation_owners_reuse_the_worker_between_tracks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retain: bool
) -> None:
    requested: list[object] = []
    closed: list[object] = []
    count = 1 + 22_050 // 256
    path = tmp_path / "parts.npz"
    np.savez(
        path,
        allow_pickle=False,
        **{
            f"{kind.value}_{field}": np.zeros(shape)
            for kind in PhasePartKind
            for field, shape in (
                ("bands", (3, count)),
                ("energy", (count,)),
                ("chroma", (12, count)),
                ("magnitudes", (3, count)),
            )
        },
    )

    def request(session: object, _pcm: bytes, **_kwargs: object) -> tuple[Path, str]:
        requested.append(session)
        return path, "test-cpu"

    def close(session: object) -> None:
        closed.append(session)

    monkeypatch.setattr(PhaseWorkerSession, "request", request)
    monkeypatch.setattr(PhaseWorkerSession, "close", close)
    source = ManagedPhaseSources(tmp_path, "test-cpu")
    if retain:
        source = source.for_analysis()
    for _ in range(2):
        source.analyze(
            bytes(22_050 * 4), sample_rate=22_050, channels=1, checkpoint=lambda: None
        )
    if retain:
        assert requested[0] is requested[1] and not closed
    else:
        assert requested[0] is not requested[1] and closed == requested
    source.close()
    assert len(closed) == (1 if retain else 2)
