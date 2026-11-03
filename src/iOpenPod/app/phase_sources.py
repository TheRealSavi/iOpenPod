"""Bounded six-source inference; separated waveforms never leave memory."""

from __future__ import annotations

import importlib
import importlib.util
import logging
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import suppress
from copy import copy
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import numpy as np

from .phase_activity import PhaseActivity, PhaseStage
from .phase_parts import HOP, RATE, PhasePart, PhasePartKind, measure_part

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray


type _PartMeasurements = tuple[
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
]


@dataclass(frozen=True, slots=True)
class _PendingBlock:
    first: int
    last: int
    begin: int
    future: Future[tuple[_PartMeasurements, ...]]


def _measure_block(raw: NDArray[np.float32]) -> tuple[_PartMeasurements, ...]:
    """CPU-only, bounded work; no model, callbacks, or shared output arrays."""
    librosa: Any = importlib.import_module("librosa")
    mono = librosa.resample(raw, orig_sr=44_100, target_sr=RATE)
    return tuple(measure_part(mono[index]) for index in range(6))


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


@runtime_checkable
class PhaseOverlapSources(PhaseSourceAnalyzer, Protocol):
    """Optional scheduling capability; independent from chart cache identity."""

    @property
    def supports_mix_overlap(self) -> bool: ...


class DemucsPhaseSources:
    """Use the pinned six-source model with deterministic, bounded inference."""

    def __init__(self) -> None:
        self._model: Any = None
        self._device: str | None = None
        self._activity = PhaseActivity(PhaseStage.LOADING)

    @property
    def activity(self) -> PhaseActivity:
        return self._activity

    def _inference_device(self) -> str:
        if self._device is None:
            torch: Any = importlib.import_module("torch")
            self._device = "cpu"
            for name, backend in (
                ("cuda", getattr(torch, "cuda", None)),
                ("mps", getattr(getattr(torch, "backends", None), "mps", None)),
            ):
                try:
                    if backend is not None and backend.is_available():
                        self._device = name
                        break
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Phase could not inspect %s; trying another backend",
                        name,
                        exc_info=True,
                    )
        return self._device

    def for_analysis(self) -> DemucsPhaseSources:
        updated = copy(self)
        updated._device = None
        updated._activity = PhaseActivity(PhaseStage.LOADING)
        return updated

    @property
    def supports_mix_overlap(self) -> bool:
        """Keep CPU and shared-memory MPS inference on the serial path."""
        return self._inference_device() == "cuda"

    @staticmethod
    def available() -> bool:
        try:
            return all(
                importlib.util.find_spec(name) is not None
                for name in ("demucs", "torch")
            )
        except (ImportError, ValueError):
            return False

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
        if not samples.size:
            raise ValueError("Invalid Phase separation PCM samples")
        # Validate in ten-second blocks rather than allocating a whole-Track
        # boolean array (about 150 MiB for the maximum stereo input).
        for first_sample in range(0, len(samples), sample_rate * 10):
            checkpoint()
            if not np.isfinite(
                samples[first_sample : first_sample + sample_rate * 10]
            ).all():
                raise ValueError("Invalid Phase separation PCM samples")
        torch: Any = importlib.import_module("torch")
        apply: Any = importlib.import_module("demucs.apply")
        device = self._inference_device()
        device_name = ""
        if device == "cuda":
            # Display metadata must never disable otherwise usable analysis.
            with suppress(Exception):
                device_name = str(torch.cuda.get_device_properties().name)[:160]
        self._activity = PhaseActivity(PhaseStage.LOADING, device, device_name)
        checkpoint()
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
        self._activity = PhaseActivity(PhaseStage.SOURCES, device, device_name)
        checkpoint()
        count = 1 + round(len(samples) * RATE / sample_rate) // HOP
        bands = np.zeros((6, 3, count), dtype=np.float64)
        energy = np.zeros((6, count), dtype=np.float64)
        chroma = np.zeros((6, 12, count), dtype=np.float64)
        magnitudes = np.zeros((6, 3, count), dtype=np.float64)
        # Four-second cores plus context stay below the model's training segment
        # limit. Only compact evidence is retained for the complete song.
        core, context = 344, 86
        ratio = sample_rate // RATE
        # CUDA inference overlaps one CPU feature block; other backends stay serial.
        executor = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="phase-features")
            if device == "cuda"
            else None
        )
        pending: _PendingBlock | None = None

        def commit_pending() -> None:
            nonlocal pending
            if pending is None:
                return
            block = pending
            pending = None
            while not block.future.done():
                checkpoint()
                wait((block.future,), timeout=0.05)
            measurements = block.future.result()
            section = slice(block.first - block.begin, block.last - block.begin)
            for index, (b, e, c, m) in enumerate(measurements):
                checkpoint()
                bands[index, :, block.first : block.last] = b[:, section]
                energy[index, block.first : block.last] = e[section]
                chroma[index, :, block.first : block.last] = c[:, section]
                magnitudes[index, :, block.first : block.last] = m[:, section]

        try:
            for first in range(0, count, core):
                checkpoint()
                last = min(count, first + core)
                begin, end = max(0, first - context), min(count, last + context)
                block = samples[
                    begin * HOP * ratio : min(len(samples), end * HOP * ratio)
                ]
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
                separated: Any = None
                try:
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
                except Exception:
                    if device == "cpu":
                        raise
                    logging.getLogger(__name__).warning(
                        "Phase %s inference failed; restarting the Track on CPU",
                        device,
                        exc_info=True,
                    )
                    checkpoint()
                    self._device = "cpu"
                if self._device == "cpu" and device != "cpu":
                    # Running CPU work cannot be cancelled: drain it before CPU retry.
                    if executor is not None:
                        executor.shutdown(wait=True, cancel_futures=True)
                        executor = None
                        pending = None
                    # Leave the exception handler before retrying: its traceback can
                    # retain failed accelerator tensors until the CPU run finishes.
                    try:
                        model.to("cpu")
                        cache = getattr(torch, device, None)
                        if cache is not None:
                            cache.empty_cache()
                    except Exception:
                        logging.getLogger(__name__).debug(
                            "Phase accelerator cleanup failed",
                            exc_info=True,
                        )
                    del bands, energy, chroma, magnitudes, waveform, reference
                    # Retry the complete Track: one chart must have one backend's
                    # evidence, including when a later accelerator block fails.
                    return self.analyze(
                        pcm,
                        sample_rate=sample_rate,
                        channels=channels,
                        checkpoint=checkpoint,
                    )
                checkpoint()
                # Mean removal is intentional for attack evidence (DC is not a note).
                raw = np.asarray(separated.mean(1).numpy(), dtype=np.float32)
                if raw.shape != (6, waveform.shape[-1]) or not np.isfinite(raw).all():
                    raise ValueError("Invalid Phase separated waveform")
                if executor is None:
                    mono = librosa.resample(raw, orig_sr=44_100, target_sr=RATE)
                    section = slice(first - begin, last - begin)
                    for index in range(6):
                        checkpoint()
                        b, e, c, m = measure_part(mono[index])
                        bands[index, :, first:last] = b[:, section]
                        energy[index, first:last] = e[section]
                        chroma[index, :, first:last] = c[:, section]
                        magnitudes[index, :, first:last] = m[:, section]
                else:
                    commit_pending()
                    pending = _PendingBlock(
                        first, last, begin, executor.submit(_measure_block, raw)
                    )
            commit_pending()
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
        return tuple(
            PhasePart(kind, bands[i], energy[i], chroma[i], magnitudes[i])
            for i, kind in enumerate(kinds)
        )
