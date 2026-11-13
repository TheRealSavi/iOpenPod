"""Arrange a salient musical phrase as a short native monophonic Alarm Tone.

Whole-song recurrence proposes phrases. Harmonic salience and a continuity-
constrained pitch path transcribe each proposal; no loudest-bin or first-seven-
seconds shortcut is used. This is an arrangement, not a lossless transcription.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast

import numpy as np
from numpy.typing import NDArray

from iOpenPod.app.display_text import source_text
from iOpenPod.app.synesthesia.audio import FFmpegDecoder
from iPodDB.alarms import AlarmToneNote
from iPodDB.library import MediaKind, Track

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.playback.backend import PlaybackSourceProvider
    from storage.media_processing import MediaToolFinder

FloatArray = NDArray[np.float32]
_RATE = 22050
_HOP = 256
_SECONDS = 7.0
_MAX_SOURCE_BYTES = 512 * 1024 * 1024


def _median[T: np.generic](
    values: NDArray[T], size: int | tuple[int, int]
) -> NDArray[T]:
    median = cast(
        "Callable[..., NDArray[T]]", import_module("scipy.ndimage").median_filter
    )
    return median(values, size=size, mode="nearest")


@dataclass(frozen=True, slots=True)
class ToneArrangement:
    notes: tuple[AlarmToneNote, ...]
    source_start_seconds: float
    source_end_seconds: float

    @property
    def duration_ms(self) -> int:
        return sum(note.duration_ms for note in self.notes)


def can_convert_track(track: Track) -> bool:
    return (
        track.track_id > 0
        and track.media_kind is MediaKind.MUSIC
        and bool(track.metadata.location)
        and 1000 <= track.length_ms <= 15 * 60 * 1000
    )


def convert_track_to_tone(
    track: Track,
    provider: PlaybackSourceProvider,
    *,
    checkpoint: Callable[[], None],
    report: Callable[[str], None],
    find_tool: MediaToolFinder | None = None,
) -> ToneArrangement:
    """Capture through the connection-bound source; derive only ephemeral Host data."""
    if not can_convert_track(track):
        raise ValueError("Choose a saved music track between 1 second and 15 minutes.")
    checkpoint()
    report(source_text("Reading the track…"))
    source = provider.open_playback_source(track)
    if not 0 < source.byte_count <= _MAX_SOURCE_BYTES:
        raise ValueError("This track is too large for tone conversion.")
    suffix = Path(source.file_name).suffix
    if not suffix or len(suffix) > 12 or not suffix[1:].isalnum():
        suffix = ".media"
    with TemporaryDirectory(prefix="iopenpod-tone-") as directory:
        path = Path(directory) / ("source" + suffix)
        with path.open("wb") as output:
            offset = 0
            while offset < source.byte_count:
                checkpoint()
                count = min(1024 * 1024, source.byte_count - offset)
                payload = source.read_at(offset, count)
                if not payload or len(payload) > count:
                    raise ValueError("The track changed while it was being read.")
                output.write(payload)
                offset += len(payload)
        report(source_text("Listening for a melodic phrase…"))
        decoded = FFmpegDecoder(sample_rate_hz=_RATE, find_tool=find_tool).decode(
            path, checkpoint=checkpoint, progress=lambda _value: checkpoint()
        )
        # Avoid cancelling a centered lead by summing phase-inverted stereo.
        mono = np.mean(decoded.samples, axis=1, dtype=np.float32)
        if float(np.mean(mono * mono)) < float(np.mean(decoded.samples**2)) * 0.05:
            mono = decoded.samples[:, 0].copy()
        return arrange_melody(mono, checkpoint=checkpoint, report=report)


def _proposals(
    audio: FloatArray, checkpoint: Callable[[], None]
) -> list[tuple[float, float]]:
    import librosa

    # A half-second chroma overview bounds the recurrence matrix even at the
    # 15-minute decode limit. Pitch refinement separately suppresses percussion.
    spectrum = np.abs(librosa.stft(audio, n_fft=2048, hop_length=2048))
    checkpoint()
    chroma = librosa.feature.chroma_stft(
        S=spectrum**2, sr=_RATE, n_fft=2048, hop_length=2048
    )
    group = 5
    count = chroma.shape[1] // group
    if count < 2:
        return [(0.0, 0.0)]
    features = chroma[:, : count * group].reshape(12, count, group).mean(axis=2)
    features /= np.maximum(np.linalg.norm(features, axis=0, keepdims=True), 1e-7)
    energy = (
        np.sqrt(np.mean(spectrum[:, : count * group] ** 2, axis=0))
        .reshape(count, group)
        .mean(axis=1)
    )
    energy /= max(float(np.quantile(energy, 0.9)), 1e-7)
    width = min(count, max(1, round(_SECONDS * _RATE / (2048 * group))))
    starts = count - width + 1
    frame_similarity = features.T @ features
    similarity = np.zeros((starts, starts), dtype=np.float32)
    # Match ordered phrases, so equal chord histograms in a different order do
    # not count as repeated melody sections.
    for offset in range(width):
        checkpoint()
        similarity += (
            frame_similarity[offset : offset + starts, offset : offset + starts] / width
        )
    separation = round(12 * _RATE / (2048 * group))
    positions = np.arange(starts, dtype=np.int32)
    similarity[np.abs(positions[:, None] - positions[None, :]) < separation] = 0
    recurrence = np.mean(
        np.partition(similarity, -min(5, starts), axis=1)[:, -min(5, starts) :], axis=1
    )
    checkpoint()
    step = 2048 * group / _RATE
    # Flat sustained intros do not earn the same salience as changing phrases.
    motion = np.r_[0.0, np.linalg.norm(np.diff(features, axis=1), axis=0)]
    window = np.ones(width) / width
    activity = np.convolve(np.minimum(motion, 1), window, mode="valid")
    audibility = np.convolve(np.minimum(energy, 1), window, mode="valid")
    score = (recurrence * 0.65 + activity * 0.35) * audibility
    ranked: list[tuple[float, float]] = []
    duration = len(audio) / _RATE
    onset = np.maximum(np.diff(spectrum, axis=1, prepend=spectrum[:, :1]), 0).sum(
        axis=0
    )
    for raw in np.argsort(score)[::-1]:
        start = min(float(raw) * step, max(0.0, duration - _SECONDS))
        frame = round(start * _RATE / 2048)
        lo, hi = max(0, frame - 3), min(len(onset), frame + 4)
        aligned = (lo + int(np.argmax(onset[lo:hi]))) * 2048 / _RATE
        start = min(aligned, max(0.0, duration - _SECONDS))
        if all(abs(start - previous) >= _SECONDS * 0.8 for previous, _ in ranked):
            ranked.append((start, float(score[raw])))
        if len(ranked) == 6:
            break
    return ranked or [(0.0, 0.0)]


def _pitch_path(
    audio: FloatArray, checkpoint: Callable[[], None]
) -> tuple[NDArray[np.int32], FloatArray, FloatArray]:
    import librosa

    spectrum = np.abs(librosa.stft(audio, n_fft=4096, hop_length=_HOP)).astype(
        np.float32
    )
    # Frequency-local whitening prevents bass loudness and spectral envelopes
    # from defining the melody. Time/frequency HPSS suppresses percussive attacks.
    harmonic, _ = librosa.decompose.hpss(spectrum, kernel_size=(17, 17), margin=(2, 2))
    # Attenuate evidence that persists throughout the phrase (held bass/chords).
    # A retained floor keeps sustained melodic notes from disappearing outright.
    background = np.quantile(harmonic, 0.35, axis=1, keepdims=True)
    harmonic = np.maximum(harmonic - background * 0.95, harmonic * 0.06).astype(
        np.float32
    )
    floor = _median(harmonic, (31, 1))
    whitened = harmonic / np.maximum(
        floor, np.max(harmonic, axis=0, keepdims=True) * 0.02 + 1e-8
    )
    whitened = np.sqrt(np.minimum(whitened, 30))
    midi = np.arange(48, 89)
    frequencies = 440 * 2 ** ((midi - 69) / 12)
    bins = frequencies * 4096 / _RATE
    salience = np.zeros((len(midi), spectrum.shape[1]), dtype=np.float32)
    odd_support = np.zeros_like(salience)
    for harmonic_number in range(1, 7):
        checkpoint()
        # Local peak integration tolerates vibrato and tuning without changing
        # the semitone output grid. Higher partials supply missing-F0 evidence.
        targets = bins * harmonic_number
        radius = np.maximum(1, np.rint(targets * 0.018)).astype(int)
        values = np.zeros_like(salience)
        for row, (center, spread) in enumerate(zip(targets, radius, strict=True)):
            lo, hi = (
                max(0, round(center) - int(spread)),
                min(len(whitened), round(center) + int(spread) + 1),
            )
            if lo < hi:
                values[row] = np.max(whitened[lo:hi], axis=0)
        if harmonic_number % 2:
            odd_support = np.maximum(odd_support, values)
        salience += values * 0.8 ** (harmonic_number - 1)
    salience *= 0.5 + 0.5 * odd_support / np.maximum(
        np.max(odd_support, axis=0, keepdims=True), 1e-7
    )
    # A lower octave supported only by even partials is not a new fundamental.
    # Odd partials preserve the correct pitch when the fundamental is absent.
    salience = np.maximum(salience, 0)
    energy = np.sqrt(np.mean(spectrum**2, axis=0))
    active = energy > max(float(np.max(energy)) * 0.045, 1e-5)
    flatness = np.exp(np.mean(np.log(spectrum + 1e-8), axis=0)) / np.maximum(
        np.mean(spectrum, axis=0), 1e-8
    )
    active &= flatness < 0.55
    peak = np.max(salience, axis=0)
    relative = salience / np.maximum(peak, 1e-7)
    # Suppress the low register gradually, not with an octave-changing post-pass.
    relative[:7] *= np.linspace(0.65, 0.95, 7, dtype=np.float32)[:, None]
    emissions = np.vstack((relative, np.where(active, 0.12, 1.2)))
    emissions[:-1, ~active] = 0
    distance = np.abs(midi[:, None] - midi[None, :])
    penalty = np.minimum(distance, 12) * 0.045 + (distance != 0) * 0.1
    transition = np.full((len(midi) + 1, len(midi) + 1), -0.16, dtype=np.float32)
    transition[:-1, :-1] = -penalty
    transition[-1, -1] = 0
    scores = emissions[:, 0]
    back = np.zeros(emissions.shape, dtype=np.int32)
    for frame in range(1, emissions.shape[1]):
        if frame % 64 == 0:
            checkpoint()
        candidates = scores[:, None] + transition
        back[:, frame] = np.argmax(candidates, axis=0)
        scores = emissions[:, frame] + np.max(candidates, axis=0)
    path = np.zeros(emissions.shape[1], dtype=np.int32)
    path[-1] = int(np.argmax(scores))
    for frame in range(len(path) - 1, 0, -1):
        path[frame - 1] = back[path[frame], frame]
    confidence = relative[np.minimum(path, len(midi) - 1), np.arange(len(path))]
    pitches = np.where(path == len(midi), 0, path + midi[0]).astype(np.int32)
    pitches = _median(pitches, 5)
    flux = np.maximum(np.diff(spectrum, axis=1, prepend=spectrum[:, :1]), 0).sum(axis=0)
    return pitches, confidence.astype(np.float32), flux.astype(np.float32)


def _notes(
    pitches: NDArray[np.int32], flux: FloatArray, duration: float
) -> tuple[AlarmToneNote, ...]:
    find_peaks = cast(
        "Callable[..., tuple[NDArray[np.intp], dict[str, NDArray[np.float64]]]]",
        import_module("scipy.signal").find_peaks,
    )

    # Split repeated pitches at strong attacks as well as pitch transitions.
    peaks, _ = find_peaks(
        flux,
        distance=round(0.12 * _RATE / _HOP),
        prominence=max(float(np.max(flux)) * 0.22, 1e-5),
    )
    boundaries = sorted(
        {
            0,
            len(pitches),
            *(int(i) for i in np.flatnonzero(np.diff(pitches)) + 1),
            *(int(i) for i in peaks if 0.08 <= i * _HOP / _RATE <= duration - 0.08),
        }
    )
    segments: list[tuple[int, int, int]] = []
    for start, end in pairwise(boundaries):
        pitch = int(np.median(pitches[start:end]))
        if segments and (end - start) * _HOP / _RATE < 0.07:
            previous = segments.pop()
            segments.append((previous[0], end, previous[2]))
        else:
            segments.append((start, end, pitch))
    while segments and segments[0][2] == 0:
        segments.pop(0)
    while segments and segments[-1][2] == 0:
        segments.pop()
    result: list[AlarmToneNote] = []
    for start, end, pitch in segments:
        start_ms = round(min(start * _HOP / _RATE, duration) * 1000)
        end_ms = round(min(end * _HOP / _RATE, duration) * 1000)
        if end_ms <= start_ms:
            continue
        frequency = round(440 * 2 ** ((pitch - 69) / 12)) if pitch else 0
        result.append(AlarmToneNote(frequency, end_ms - start_ms))
    return tuple(result)


def arrange_melody(
    audio: FloatArray, *, checkpoint: Callable[[], None], report: Callable[[str], None]
) -> ToneArrangement:
    """Analyze finite 22.05 kHz mono PCM; select and transcribe one short phrase."""
    if (
        audio.ndim != 1
        or not _RATE <= len(audio) <= 15 * 60 * _RATE
        or not np.all(np.isfinite(audio))
    ):
        raise ValueError(
            "Tone analysis needs finite mono audio between 1 second and 15 minutes."
        )
    if float(np.max(np.abs(audio))) < 1e-5:
        raise ValueError("No audible melody was found in this track.")
    checkpoint()
    proposals = _proposals(audio, checkpoint)
    best: tuple[float, ToneArrangement] | None = None
    for start, recurrence in proposals:
        checkpoint()
        report(source_text("Turning the melody into notes…"))
        segment = audio[round(start * _RATE) : round((start + _SECONDS) * _RATE)]
        pitches, confidence, flux = _pitch_path(segment, checkpoint)
        notes = _notes(pitches, flux, len(segment) / _RATE)
        voiced = pitches > 0
        distinct = len({int(pitch) for pitch in pitches[voiced]})
        if not notes or distinct < 2 or np.mean(voiced) < 0.3:
            continue
        changes = np.abs(np.diff(pitches[voiced]))
        score = (
            float(np.mean(confidence[voiced]))
            + recurrence * 0.65
            + min(distinct, 8) * 0.035
            - float(np.mean(changes > 7)) * 0.6
        )
        result = ToneArrangement(notes, start, start + len(segment) / _RATE)
        if best is None or score > best[0]:
            best = score, result
    if best is None:
        raise ValueError(
            "A clear melodic phrase could not be found. Try another track."
        )
    checkpoint()
    return best[1]
