"""Bounded whole-song onset and pulse analysis for Phase gameplay charts."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING, cast

import numpy as np
from numpy.typing import NDArray

from iPodDB.games import PhaseBeat, PhaseChart

from .phase_hooks import direct_parts
from .phase_hpss import separate_magnitude
from .phase_parts import measure_band_attacks

if TYPE_CHECKING:
    from collections.abc import Callable

    from .phase_parts import PhasePart

PHASE_ANALYSIS_VERSION = "librosa-phase-7"
PHASE_SAMPLE_RATE = 22_050
_HOP = 256
_FFT = 2048
_BLOCK = 2048
_CONTEXT = 64
type _FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class _MixMeasurements:
    magnitudes: _FloatArray
    energy: _FloatArray
    onsets: tuple[int, ...]
    percussive_onsets: tuple[int, ...]
    beat_positions: tuple[int, ...]
    beats: tuple[PhaseBeat, ...]


@dataclass(frozen=True, slots=True)
class PhaseMixEvidence:
    """Compact whole-mix evidence; no PCM or spectral blocks are retained."""

    length_ms: int
    frame_count: int
    measurements: _MixMeasurements | None = None


def _member(module: object, name: str) -> object:
    return getattr(module, name)


def analyze_phase_pcm(
    pcm: bytes,
    *,
    length_ms: int,
    checkpoint: Callable[[], None] = lambda: None,
    max_workers: int = 2,
    parts: tuple[PhasePart, ...] = (),
) -> PhaseChart:
    """Map spectral onsets and tracked beats into the game's packed magnitudes.

    The mapping is an iOpenPod design, not a recovered iTunes analysis algorithm.
    Time is Q16.16 seconds; the game performs its own integer-ms conversion.
    """
    evidence = measure_phase_mix(
        pcm, length_ms=length_ms, checkpoint=checkpoint, max_workers=max_workers
    )
    return finish_phase_analysis(evidence, parts=parts, checkpoint=checkpoint)


def measure_phase_mix(
    pcm: bytes,
    *,
    length_ms: int,
    checkpoint: Callable[[], None] = lambda: None,
    max_workers: int = 2,
) -> PhaseMixEvidence:
    """Measure whole-mix attacks and pulse independently of optional Parts."""
    import librosa

    checkpoint()
    if max_workers not in (1, 2):
        raise ValueError("Phase analysis supports one or two DSP workers.")
    if len(pcm) % 4 or len(pcm) > PHASE_SAMPLE_RATE * 1801 * 4:
        raise ValueError("Invalid or oversized Phase PCM input.")
    samples = np.frombuffer(pcm, dtype="<f4")
    if (
        not 30 <= length_ms // 1000 <= 1800
        or abs(samples.size / PHASE_SAMPLE_RATE - length_ms / 1000) > 3
    ):
        raise ValueError("Decoded Phase audio duration disagrees with the Track.")
    # Bound validation and silence-detection temporaries even for long Tracks.
    validation_block = PHASE_SAMPLE_RATE * 10
    for first in range(0, samples.size, validation_block):
        checkpoint()
        if not np.isfinite(samples[first : first + validation_block]).all():
            raise ValueError("Phase PCM contains non-finite samples.")
    samples = samples[: round(length_ms * PHASE_SAMPLE_RATE / 1000)]
    frame_count = 1 + samples.size // _HOP
    peak = max(
        (
            float(np.max(np.abs(samples[first : first + validation_block])))
            for first in range(0, samples.size, validation_block)
        ),
        default=0.0,
    )
    if peak < 1e-5:
        return PhaseMixEvidence(length_ms, frame_count)
    # librosa's lazy module exports have incomplete typing. Narrow its dynamic
    # array APIs here; all output shapes are checked by the following operations.
    onset_strength = cast(
        "Callable[..., _FloatArray]", _member(librosa.onset, "onset_strength")
    )
    onset_detect = cast(
        "Callable[..., NDArray[np.int64]]", _member(librosa.onset, "onset_detect")
    )
    beat_track = cast(
        "Callable[..., tuple[object, NDArray[np.int64]]]",
        _member(librosa.beat, "beat_track"),
    )
    power_to_db = cast("Callable[..., _FloatArray]", _member(librosa, "power_to_db"))
    bands = np.zeros((2, 3, frame_count), dtype=np.float64)
    energy = np.zeros(frame_count, dtype=np.float64)
    harmony = np.zeros(frame_count, dtype=np.float64)
    magnitudes = np.zeros((3, frame_count), dtype=np.float64)
    percussion_attacks = np.zeros(frame_count, dtype=np.float64)
    edges = librosa.mel_frequencies(n_mels=64, fmin=20, fmax=PHASE_SAMPLE_RATE / 2)
    masks = (edges < 250, (edges >= 250) & (edges < 2000), edges >= 2000)
    stopped = Event()

    def analyze_block(
        first: int,
    ) -> tuple[_FloatArray, _FloatArray, _FloatArray, _FloatArray, _FloatArray]:
        if stopped.is_set():
            raise RuntimeError("Phase analysis stopped")
        last = min(frame_count, first + _BLOCK)
        begin = max(0, first - _CONTEXT)
        end = min(frame_count, last + _CONTEXT)
        signal = samples[begin * _HOP : min(samples.size, end * _HOP)]
        magnitude = cast(
            "NDArray[np.float32]",
            np.abs(librosa.stft(signal, n_fft=_FFT, hop_length=_HOP)),
        )
        harmonic, percussive = separate_magnitude(magnitude)
        if stopped.is_set():
            raise RuntimeError("Phase analysis stopped")
        # Percussive emphasis retains pitched attacks rather than erasing them.
        section = slice(first - begin, last - begin)
        block_energy = np.sqrt(np.mean(magnitude[:, section] ** 2, axis=0)) / _FFT
        block_harmony = np.sqrt(np.mean(harmonic[:, section] ** 2, axis=0)) / _FFT
        # Flux normalization can amplify tiny vibrato or numerical changes in a
        # held tone. Require an actual change in harmonic shape or amplitude.
        lag = 4
        previous = np.pad(harmonic[:, :-lag], ((0, 0), (lag, 0)))
        norm = np.linalg.norm(harmonic, axis=0)
        old_norm = np.linalg.norm(previous, axis=0)
        similarity = np.sum(harmonic * previous, axis=0) / np.maximum(
            norm * old_norm, 1e-12
        )
        articulated = ((1 - similarity > 0.02) | (norm > old_norm * 1.08))[section]
        block_bands = np.zeros((2, 3, last - first), dtype=np.float64)
        for family, spectrum in enumerate(
            ((0.75 * percussive + 0.25 * magnitude) ** 2, harmonic**2)
        ):
            mel = librosa.feature.melspectrogram(
                S=spectrum,
                sr=PHASE_SAMPLE_RATE,
                n_fft=_FFT,
                hop_length=_HOP,
                n_mels=64,
                fmin=20,
            )
            log_mel = power_to_db(mel, ref=1.0, top_db=80.0)
            for index, mask in enumerate(masks):
                envelope = onset_strength(
                    S=log_mel[mask],
                    sr=PHASE_SAMPLE_RATE,
                    hop_length=_HOP,
                    n_fft=_FFT,
                    center=False,
                    max_size=3 if family else 1,
                )
                block_bands[family, index] = envelope[section]
        block_bands[1, :, ~articulated] = 0
        # A sustained melody may dominate total power while quieter drums are
        # still clearly audible. Suppress numerical/vibrato leakage only when
        # the percussive component itself is negligible.
        percussion = np.sqrt(np.mean(percussive[:, section] ** 2, axis=0)) / _FFT
        held = (~articulated) & (percussion < block_energy * 0.05)
        block_bands[0, :, held] = 0
        return (
            block_bands,
            block_energy.astype(np.float64),
            block_harmony.astype(np.float64),
            measure_band_attacks(magnitude)[:, section],
            measure_band_attacks(percussive)[:, section].sum(axis=0),
        )

    # Bound admission as well as worker count: never queue a whole song's
    # spectrograms. Only this coordinator publishes results or calls checkpoint.
    starts = tuple(range(0, frame_count, _BLOCK))
    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="phase-dsp"
    ) as workers:
        try:
            for offset in range(0, len(starts), max_workers):
                checkpoint()
                batch = starts[offset : offset + max_workers]
                futures = tuple(workers.submit(analyze_block, first) for first in batch)
                for first, future in zip(batch, futures, strict=True):
                    while not future.done():
                        checkpoint()
                        wait((future,), timeout=0.05)
                    checkpoint()
                    (
                        block_bands,
                        block_energy,
                        block_harmony,
                        block_magnitudes,
                        block_percussion,
                    ) = future.result()
                    last = first + block_energy.size
                    bands[:, :, first:last] = block_bands
                    energy[first:last] = block_energy
                    harmony[first:last] = block_harmony
                    magnitudes[:, first:last] = block_magnitudes
                    percussion_attacks[first:last] = block_percussion
        finally:
            stopped.set()
    checkpoint()
    scales = np.asarray(
        [
            max(float(np.percentile(row[row > 1e-5], 95)), 1e-5)
            if np.any(row > 1e-5)
            else 1e-5
            for row in bands.reshape(6, frame_count)
        ],
        dtype=np.float64,
    ).reshape(2, 3)
    envelopes = np.minimum(bands / scales[:, :, None], 2.0).mean(axis=1)
    active = energy > max(1e-5, float(np.max(energy)) * 0.01)
    envelopes[:, ~active] = 0
    # Reject amplified leakage from locally inaudible harmonic components.
    envelopes[1, harmony < np.maximum(1e-5, energy * 0.15)] = 0
    envelope = envelopes[0]
    if not np.any(envelope > 1e-5):
        return PhaseMixEvidence(length_ms, frame_count)
    onsets = tuple(
        onset_detect(
            onset_envelope=row,
            sr=PHASE_SAMPLE_RATE,
            hop_length=_HOP,
            units="frames",
            wait=round(0.06 * PHASE_SAMPLE_RATE / _HOP),
            delta=0.1,
        )
        for row in envelopes
    )
    checkpoint()
    beat_positions: list[int] = []
    # Local tempo estimation adapts across the song without allocating a
    # whole-track tempogram (hundreds of MiB on a 30-minute input).
    for first in range(0, frame_count, _BLOCK):
        checkpoint()
        last = min(frame_count, first + _BLOCK)
        begin, end = max(0, first - 256), min(frame_count, last + 256)
        _, local_beats = beat_track(
            onset_envelope=envelope[begin:end],
            sr=PHASE_SAMPLE_RATE,
            hop_length=_HOP,
            units="frames",
            trim=False,
        )
        beat_positions.extend(
            begin + frame
            for frame in local_beats.tolist()
            if first <= begin + frame < last
        )
    checkpoint()
    pulse_scale = max(float(np.percentile(envelope[envelope > 0], 95)), 1e-5)
    # The native game's low beat nibble drives relative passage power. Smooth
    # full-mix energy over 250 ms so a beat's exact position within an attack
    # cannot turn constant backing harmony into a false energy measurement.
    width = 2 * round(0.125 * PHASE_SAMPLE_RATE / _HOP) + 1
    power = np.sqrt(np.convolve(energy**2, np.ones(width) / width, mode="same"))
    power_scale = max(float(np.percentile(power[active], 95)), 1e-5)

    def timestamp(frame: int) -> int:
        return round(frame * _HOP * 65536 / PHASE_SAMPLE_RATE)

    def quantize(value: float, scale: float, maximum: int) -> int:
        return round(math.pow(min(max(value / scale, 0), 1), 0.65) * maximum)

    beats: list[PhaseBeat] = []
    previous_beat = -1
    for frame in beat_positions:
        checkpoint()
        if (
            0 <= frame < frame_count
            and active[frame]
            and timestamp(frame) < length_ms * 65536 // 1000
            and timestamp(frame) - previous_beat >= round(0.12 * 65536)
        ):
            beats.append(
                PhaseBeat(
                    timestamp(frame),
                    quantize(float(envelope[frame]), pulse_scale, 15),
                    quantize(float(power[frame]), power_scale, 15),
                )
            )
            previous_beat = timestamp(frame)
    mix_onsets = tuple(sorted({int(frame) for frames in onsets for frame in frames}))
    # The detection envelope includes pitched attacks. Only give acoustic
    # percussion priority when HPSS supplies at least half the measured
    # attack magnitude; normalized novelty alone is not that evidence.
    percussive_onsets = tuple(
        int(frame)
        for frame in onsets[0]
        if percussion_attacks[frame]
        >= max(float(magnitudes[:, frame].sum()) * 0.5, 1e-10)
    )
    magnitudes.flags.writeable = False
    energy.flags.writeable = False
    return PhaseMixEvidence(
        length_ms,
        frame_count,
        _MixMeasurements(
            magnitudes,
            energy,
            mix_onsets,
            percussive_onsets,
            tuple(beat_positions),
            tuple(beats),
        ),
    )


def finish_phase_analysis(
    evidence: PhaseMixEvidence,
    *,
    parts: tuple[PhasePart, ...] = (),
    checkpoint: Callable[[], None] = lambda: None,
) -> PhaseChart:
    """Combine independently measured mix and optional Part evidence in order."""
    checkpoint()
    if any(len(part.energy) != evidence.frame_count for part in parts):
        raise ValueError("Phase source evidence disagrees with decoded duration")
    measured = evidence.measurements
    if measured is None:
        return PhaseChart(
            direct_parts(
                parts, beats=[], length_ms=evidence.length_ms, checkpoint=checkpoint
            )
            if parts
            else ()
        )
    directed = direct_parts(
        parts,
        beats=list(measured.beat_positions),
        length_ms=evidence.length_ms,
        checkpoint=checkpoint,
        mix_bands=measured.magnitudes,
        mix_energy=measured.energy,
        mix_onsets=measured.onsets,
        percussive_onsets=measured.percussive_onsets,
    )
    return PhaseChart(directed, measured.beats)
