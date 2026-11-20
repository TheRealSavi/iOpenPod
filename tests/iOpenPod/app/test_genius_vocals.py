"""Vocal occupancy uses aligned sources and bounded, distributed sampling."""

from pathlib import Path

import numpy as np
import pytest

from iOpenPod.app.genius_vocals import (
    ManagedGeniusVocals,
    _sample,  # pyright: ignore[reportPrivateUsage]
    installed_genius_vocals,
    vocal_fraction,
)
from iOpenPod.app.phase_parts import HOP, RATE, PhasePart, PhasePartKind
from iOpenPod.app.phase_runtime import ManagedPhaseSources


def _parts(vocal: float, fraction: float = 1.0) -> tuple[PhasePart, ...]:
    count = 1 + 12 * RATE // HOP
    rows: list[PhasePart] = []
    for kind in PhasePartKind:
        energy = np.zeros(count, dtype=np.float64)
        if kind is PhasePartKind.OTHER:
            energy[:] = 1
        if kind is PhasePartKind.VOCALS:
            energy[: round(count * fraction)] = vocal
        rows.append(
            PhasePart(
                kind,
                np.zeros((3, count)),
                energy,
                np.zeros((12, count)),
                np.zeros((3, count)),
            )
        )
    return tuple(rows)


def test_tiny_vocal_stem_leakage_is_not_singing() -> None:
    assert vocal_fraction(_parts(0.01), ((0, 12 * RATE),)) == 0
    assert vocal_fraction(_parts(0.8), ((0, 12 * RATE),)) == 1


def test_sparse_vocals_are_not_averaged_into_a_continuously_vocal_song() -> None:
    measured = vocal_fraction(_parts(0.8, 0.2), ((0, 12 * RATE),))
    assert 0.1 <= measured <= 0.2


def test_vocal_evidence_cannot_use_missing_or_misaligned_sources() -> None:
    with pytest.raises(ValueError, match="all six"):
        vocal_fraction(_parts(0.8)[:-1], ((0, 12 * RATE),))


def test_long_tracks_sample_across_the_recording_and_keep_memory_bounded() -> None:
    # One byte-valued second per second makes exact sample coverage inspectable.
    pcm = b"".join(bytes([i % 256]) * RATE * 4 for i in range(900))
    sampled, intervals = _sample(pcm)
    assert len(sampled) == 48 * RATE * 4
    assert len(intervals) == 6
    assert sampled[: RATE * 4] == pcm[: RATE * 4]
    assert sampled[-RATE * 4 :] == pcm[-RATE * 4 :]
    starts = [sampled[first * 4] for first, _ in intervals]
    assert len(set(starts)) == 6


def test_short_tracks_use_all_audio() -> None:
    pcm = bytes(12 * RATE * 4)
    assert _sample(pcm) == (pcm, ((0, 12 * RATE),))


def test_installed_provider_requires_checkpoint_in_shared_model_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = ManagedPhaseSources(tmp_path / "runtime-test", "receipt")

    def installed(_cls: type[ManagedPhaseSources]) -> ManagedPhaseSources:
        return sources

    monkeypatch.setattr(ManagedPhaseSources, "installed", classmethod(installed))
    assert installed_genius_vocals() is None
    checkpoint = tmp_path / "models/hub/checkpoints/5c90dfd2-34c22ccb.th"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"test-presence-only")
    provider = installed_genius_vocals()
    assert provider is not None
    assert provider.identity == "genius-vocals-v1:managed-v1:receipt"
    provider.close()


def test_vocal_cache_identity_does_not_change_with_worker_live_receipt(
    tmp_path: Path,
) -> None:
    class Sources(ManagedPhaseSources):
        live = "installed-receipt"

        @property
        def identity(self) -> str:
            return self.live

    sources = Sources(tmp_path, "unused")
    provider = ManagedGeniusVocals(sources)
    original = provider.identity
    sources.live = "live-worker-backend"
    assert provider.identity == original
