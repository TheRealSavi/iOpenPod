"""Bounded six-source inference; separated waveforms never leave memory."""

from __future__ import annotations

import importlib
import importlib.util
from importlib.metadata import version
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from .phase_parts import HOP, RATE, PhasePart, PhasePartKind, measure_part

if TYPE_CHECKING:
    from collections.abc import Callable


class PhaseSourceAnalyzer(Protocol):
    @property
    def identity(self) -> str: ...

    def analyze(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        checkpoint: Callable[[], None],
    ) -> tuple[PhasePart, ...]: ...


class DemucsPhaseSources:
    """Use the pinned six-source model with deterministic, bounded inference."""

    def __init__(self) -> None:
        self._model: Any = None
        self._device: str | None = None

    def _inference_device(self) -> str:
        if self._device is None:
            torch: Any = importlib.import_module("torch")
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        return self._device

    @staticmethod
    def available() -> bool:
        return all(
            importlib.util.find_spec(name) is not None for name in ("demucs", "torch")
        )

    @property
    def identity(self) -> str:
        # The checkpoint signature identifies htdemucs_6s independently of model
        # aliases. Provider/runtime changes must invalidate cached charts too.
        return f"demucs-{version('demucs')}-5c90dfd2-torch-{version('torch')}-{self._inference_device()}-shifts0"

    def analyze(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        checkpoint: Callable[[], None],
    ) -> tuple[PhasePart, ...]:
        import librosa

        checkpoint()
        if sample_rate not in (RATE, 44_100) or channels not in (1, 2):
            raise ValueError("Unsupported Phase separation PCM format")
        if len(pcm) % (4 * channels) or len(pcm) > 1801 * sample_rate * channels * 4:
            raise ValueError("Invalid Phase separation PCM size")
        samples = np.frombuffer(pcm, dtype="<f4").reshape(-1, channels)
        if not samples.size or not np.isfinite(samples).all():
            raise ValueError("Invalid Phase separation PCM samples")
        torch: Any = importlib.import_module("torch")
        apply: Any = importlib.import_module("demucs.apply")
        if self._model is None:
            repository: Any = importlib.import_module("demucs.repo")
            # This is a checkpoint signature, not a Hub model alias. Resolve it
            # directly, retaining Torch's cached-file reuse and hash validation.
            self._model = repository.RemoteRepo(
                {
                    "5c90dfd2": "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th",
                }
            ).get_model("5c90dfd2")
            self._model.eval()
        checkpoint()
        model = self._model
        kinds = tuple(PhasePartKind(name) for name in model.sources)
        if set(kinds) != set(PhasePartKind) or len(kinds) != 6:
            raise ValueError("Phase requires all six distinct Demucs sources")
        if model.samplerate != 44_100 or model.audio_channels != 2:
            raise ValueError("Unexpected Phase separation model format")
        device = self._inference_device()
        count = 1 + round(len(samples) * RATE / sample_rate) // HOP
        bands = np.zeros((6, 3, count), dtype=np.float64)
        energy = np.zeros((6, count), dtype=np.float64)
        chroma = np.zeros((6, 12, count), dtype=np.float64)
        magnitudes = np.zeros((6, 3, count), dtype=np.float64)
        # Four-second cores plus context stay below the model's training segment
        # limit. Only compact evidence is retained for the complete song.
        core, context = 344, 86
        ratio = sample_rate // RATE
        for first in range(0, count, core):
            checkpoint()
            last = min(count, first + core)
            begin, end = max(0, first - context), min(count, last + context)
            block = samples[begin * HOP * ratio : min(len(samples), end * HOP * ratio)]
            if not block.size:
                continue
            waveform = torch.from_numpy(block.T.copy())
            if channels == 1:
                waveform = waveform.repeat(2, 1)
            if sample_rate != 44_100:
                # librosa resampling avoids depending on a matching torchaudio ABI.
                waveform = torch.from_numpy(
                    librosa.resample(
                        waveform.numpy(),
                        orig_sr=sample_rate,
                        target_sr=44_100,
                    )
                )
            reference = waveform.mean(0)
            deviation = float(reference.std())
            if deviation < 1e-7:
                continue
            mean = reference.mean()
            with torch.inference_mode():
                separated = (
                    apply.apply_model(
                        model,
                        ((waveform - mean) / deviation)[None],
                        shifts=0,
                        split=False,
                        device=device,
                        num_workers=0,
                    )[0].cpu()
                    * deviation
                )
            checkpoint()
            # Mean removal is intentional for attack evidence (DC is not a note).
            raw = np.asarray(separated.mean(1).numpy(), dtype=np.float32)
            if raw.shape != (6, waveform.shape[-1]) or not np.isfinite(raw).all():
                raise ValueError("Invalid Phase separated waveform")
            mono = librosa.resample(raw, orig_sr=44_100, target_sr=RATE)
            section = slice(first - begin, last - begin)
            for index in range(6):
                checkpoint()
                b, e, c, m = measure_part(mono[index])
                bands[index, :, first:last] = b[:, section]
                energy[index, first:last] = e[section]
                chroma[index, :, first:last] = c[:, section]
                magnitudes[index, :, first:last] = m[:, section]
        return tuple(
            PhasePart(kind, bands[i], energy[i], chroma[i], magnitudes[i])
            for i, kind in enumerate(kinds)
        )
