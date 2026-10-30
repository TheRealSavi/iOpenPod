"""Bounded whole-song onset and pulse analysis for Phase gameplay charts."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, wait
from threading import Event
from typing import TYPE_CHECKING, cast

import numpy as np
from numpy.typing import NDArray

from iPodDB.games import PhaseBeat, PhaseChart, PhaseTransient

if TYPE_CHECKING:
    from collections.abc import Callable

PHASE_ANALYSIS_VERSION = "librosa-phase-1"
PHASE_SAMPLE_RATE = 22_050
_HOP = 256
_FFT = 2048
_BLOCK = 2048
_CONTEXT = 64
type _FloatArray = NDArray[np.float64]


def _member(module: object, name: str) -> object:
    return getattr(module, name)


def analyze_phase_pcm(
    pcm: bytes,
    *,
    length_ms: int,
    checkpoint: Callable[[], None] = lambda: None,
    max_workers: int = 2,
) -> PhaseChart:
    """Map spectral onsets and tracked beats into the game's packed magnitudes.

    The mapping is an iOpenPod design, not a recovered iTunes analysis algorithm.
    Time is Q16.16 seconds; the game performs its own integer-ms conversion.
    """
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
    if not np.isfinite(samples).all():
        raise ValueError("Phase PCM contains non-finite samples.")
    samples = samples[: round(length_ms * PHASE_SAMPLE_RATE / 1000)]
    if not samples.size or float(np.max(np.abs(samples))) < 1e-5:
        return PhaseChart()
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
    frame_count = 1 + samples.size // _HOP
    bands = np.zeros((3, frame_count), dtype=np.float64)
    energy = np.zeros(frame_count, dtype=np.float64)
    harmony = np.zeros(frame_count, dtype=np.float64)
    edges = librosa.mel_frequencies(n_mels=64, fmin=20, fmax=PHASE_SAMPLE_RATE / 2)
    masks = (edges < 250, (edges >= 250) & (edges < 2000), edges >= 2000)
    stopped = Event()

    def analyze_block(first: int) -> tuple[_FloatArray, _FloatArray, _FloatArray]:
        if stopped.is_set():
            raise RuntimeError("Phase analysis stopped")
        last = min(frame_count, first + _BLOCK)
        begin = max(0, first - _CONTEXT)
        end = min(frame_count, last + _CONTEXT)
        signal = samples[begin * _HOP : min(samples.size, end * _HOP)]
        magnitude = np.abs(librosa.stft(signal, n_fft=_FFT, hop_length=_HOP))
        harmonic, percussive = librosa.decompose.hpss(
            magnitude, kernel_size=31, margin=(2.0, 2.0)
        )
        if stopped.is_set():
            raise RuntimeError("Phase analysis stopped")
        # Percussive emphasis retains pitched attacks rather than erasing them.
        spectrum = (0.75 * percussive + 0.25 * magnitude) ** 2
        mel = librosa.feature.melspectrogram(
            S=spectrum,
            sr=PHASE_SAMPLE_RATE,
            n_fft=_FFT,
            hop_length=_HOP,
            n_mels=64,
            fmin=20,
        )
        log_mel = power_to_db(mel, ref=1.0, top_db=80.0)
        section = slice(first - begin, last - begin)
        block_energy = np.sqrt(np.mean(magnitude[:, section] ** 2, axis=0)) / _FFT
        block_harmony = np.sqrt(np.mean(harmonic[:, section] ** 2, axis=0)) / _FFT
        block_bands = np.zeros((3, last - first), dtype=np.float64)
        for index, mask in enumerate(masks):
            envelope = onset_strength(
                S=log_mel[mask],
                sr=PHASE_SAMPLE_RATE,
                hop_length=_HOP,
                n_fft=_FFT,
                center=False,
            )
            block_bands[index] = envelope[section]
        return (
            block_bands,
            block_energy.astype(np.float64),
            block_harmony.astype(np.float64),
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
                    block_bands, block_energy, block_harmony = future.result()
                    last = first + block_energy.size
                    bands[:, first:last] = block_bands
                    energy[first:last] = block_energy
                    harmony[first:last] = block_harmony
        finally:
            stopped.set()
    checkpoint()
    scales = np.asarray(
        [
            max(float(np.percentile(row[row > 1e-5], 95)), 1e-5)
            if np.any(row > 1e-5)
            else 1e-5
            for row in bands
        ],
        dtype=np.float64,
    )
    envelope = np.minimum(bands / scales[:, None], 2.0).mean(axis=0)
    active = energy > max(1e-5, float(np.max(energy)) * 0.01)
    envelope[~active] = 0
    if not np.any(envelope > 1e-5):
        return PhaseChart()
    onsets = onset_detect(
        onset_envelope=envelope,
        sr=PHASE_SAMPLE_RATE,
        hop_length=_HOP,
        units="frames",
        wait=round(0.12 * PHASE_SAMPLE_RATE / _HOP),
        delta=0.1,
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
    harmonic_scale = max(float(np.percentile(harmony[active], 95)), 1e-5)

    def timestamp(frame: int) -> int:
        return round(frame * _HOP * 65536 / PHASE_SAMPLE_RATE)

    def quantize(value: float, scale: float, maximum: int) -> int:
        return round(math.pow(min(max(value / scale, 0), 1), 0.65) * maximum)

    transients: list[PhaseTransient] = []
    beats: list[PhaseBeat] = []
    for frame in onsets.tolist():
        checkpoint()
        if (
            0 <= frame < frame_count
            and active[frame]
            and timestamp(frame) < length_ms * 65536 // 1000
        ):
            strengths = tuple(
                quantize(float(bands[i, frame]), float(scales[i]), 31) for i in range(3)
            )
            if any(strengths):
                transients.append(PhaseTransient(timestamp(frame), *strengths))
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
                    quantize(float(harmony[frame]), harmonic_scale, 15),
                )
            )
            previous_beat = timestamp(frame)
    return PhaseChart(tuple(transients), tuple(beats))
