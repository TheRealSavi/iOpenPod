"""Always-available complete-song spectral and musical analysis."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol, cast

import librosa
import numpy as np
from numpy.typing import NDArray

from ._rhythm import analyze_rhythm
from ._signals import (
    FloatArray,
    align,
    calibrated_band_levels_dbfs,
    cosine_change,
    dbfs_unit,
    frame_crest_db,
    positive_distribution,
    robust_unit,
    scalar_signal,
    smooth,
    vector_signal,
)
from ._structure import analyze_structure
from .models import (
    AnalysisIssue,
    AnalysisIssueSeverity,
    AnalysisProgress,
    AnalysisRequest,
    AnalysisStage,
    AnalysisTimeline,
    AudioMetadata,
    EnergyAnalysis,
    EventKind,
    HarmonyAnalysis,
    LayerAnalysis,
    MusicalEvent,
    Provenance,
    RhythmAnalysis,
    SignalValidity,
    SourceAnalysis,
    SourceKind,
    SpatialAnalysis,
    SpectrumAnalysis,
    StructureAnalysis,
    TimbreAnalysis,
    TimeGrid,
    TrackAnalysis,
    VectorSample,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .audio import DecodedAudio

IntArray = NDArray[np.int32]


class _ArrayReduction(Protocol):
    def __call__(
        self,
        values: FloatArray,
        *,
        axis: int | None = None,
    ) -> FloatArray | np.float32: ...


class _DecibelTransform(Protocol):
    def __call__(
        self,
        values: FloatArray,
        *,
        ref: _ArrayReduction,
    ) -> FloatArray: ...


class _OnsetStrength(Protocol):
    def __call__(
        self,
        *,
        S: FloatArray,  # noqa: N803 - librosa's public keyword is uppercase.
        sr: float,
        hop_length: int,
        aggregate: _ArrayReduction | None = None,
        center: bool = True,
    ) -> FloatArray: ...


class _OnsetStrengthMulti(Protocol):
    def __call__(
        self,
        *,
        S: FloatArray,  # noqa: N803 - librosa's public keyword is uppercase.
        sr: float,
        hop_length: int,
        channels: Sequence[int],
        aggregate: _ArrayReduction,
        center: bool = True,
    ) -> FloatArray: ...


def _library_member(namespace: object, name: str) -> object:
    return getattr(namespace, name)


_ARRAY_MAX = cast("_ArrayReduction", np.max)
_ARRAY_MEDIAN = cast("_ArrayReduction", np.median)
_POWER_TO_DB = cast("_DecibelTransform", _library_member(librosa, "power_to_db"))
_AMPLITUDE_TO_DB = cast(
    "_DecibelTransform", _library_member(librosa, "amplitude_to_db")
)
_ONSET_STRENGTH = cast(
    "_OnsetStrength", _library_member(librosa.onset, "onset_strength")
)
_ONSET_STRENGTH_MULTI = cast(
    "_OnsetStrengthMulti",
    _library_member(librosa.onset, "onset_strength_multi"),
)

_PROVENANCE = Provenance(
    "iOpenPod music analysis core",
    "2",
    "calibrated STFT, HPSS, onset, pulse, harmony, timbre, and recurrence analysis",
)
_BAND_NAMES = (
    "sub-bass",
    "bass",
    "low-mid",
    "mid",
    "upper-mid",
    "presence",
    "brilliance",
)
_BAND_EDGES_HZ = (20.0, 60.0, 250.0, 500.0, 2_000.0, 4_000.0, 8_000.0)
_PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


class DeterministicMusicAnalyzer:
    """Extract a truthful analysis result without optional model dependencies."""

    def analyze(
        self,
        audio: DecodedAudio,
        request: AnalysisRequest,
        *,
        title: str,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> TrackAnalysis:
        sample_rate = audio.sample_rate_hz
        hop_size = max(256, round(sample_rate / 50.0))
        frame_size = 2048 if sample_rate <= 32_000 else 4096
        stereo = audio.samples
        if len(stereo) < frame_size:
            padding = frame_size - len(stereo)
            stereo = np.pad(stereo, ((0, padding), (0, 0)))
        checkpoint()
        progress(
            AnalysisProgress(
                0.12,
                AnalysisStage.SPECTRUM,
                "Measuring calibrated energy and frequency balance",
            )
        )
        left_spectrum = librosa.stft(
            stereo[:, 0],
            n_fft=frame_size,
            hop_length=hop_size,
            window="hann",
            center=False,
        )
        left_power = np.abs(left_spectrum).astype(np.float32) ** 2
        del left_spectrum
        right_spectrum = librosa.stft(
            stereo[:, 1],
            n_fft=frame_size,
            hop_length=hop_size,
            window="hann",
            center=False,
        )
        power = (left_power + np.abs(right_spectrum).astype(np.float32) ** 2) * 0.5
        del left_power, right_spectrum
        magnitude = np.sqrt(power).astype(np.float32)
        frame_count = int(magnitude.shape[1])
        frame_rate = sample_rate / hop_size
        grid = TimeGrid(
            frame_count,
            frame_size / (2.0 * sample_rate),
            hop_size / sample_rate,
        )
        frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=frame_size).astype(
            np.float32
        )
        left_frames = librosa.util.frame(
            stereo[:, 0], frame_length=frame_size, hop_length=hop_size
        ).T
        right_frames = librosa.util.frame(
            stereo[:, 1], frame_length=frame_size, hop_length=hop_size
        ).T
        rms = align(
            np.sqrt(
                0.5
                * (
                    np.mean(left_frames * left_frames, axis=1)
                    + np.mean(right_frames * right_frames, axis=1)
                )
            ),
            frame_count,
        )
        loudness_dbfs = (20.0 * np.log10(np.maximum(rms, 1e-7))).astype(np.float32)
        acoustic_confidence = dbfs_unit(loudness_dbfs, floor=-82.0, ceiling=-42.0)
        relative_energy = _relative_energy(
            loudness_dbfs,
            acoustic_confidence,
            max(1, round(frame_rate * 0.4)),
        )
        crest_db = frame_crest_db(stereo, frame_size, hop_size, frame_count)
        band_levels = calibrated_band_levels_dbfs(
            power, frequencies, frame_size, _BAND_EDGES_HZ
        )
        band_power = np.power(10.0, band_levels / 10.0).astype(np.float32)
        band_distribution = positive_distribution(band_power)
        band_amplitude = np.power(10.0, band_levels / 20.0).astype(np.float32)
        band_flux = (
            np.maximum(
                0.0,
                np.diff(band_amplitude, axis=0, prepend=band_amplitude[:1]),
            )
            * frame_rate
        ).astype(np.float32)

        harmonic, percussive = librosa.decompose.hpss(
            magnitude,
            kernel_size=(31, 31),
            margin=(1.7, 4.2),
            power=2.0,
        )
        harmonic_power = np.mean(harmonic * harmonic, axis=0)
        percussive_power = np.mean(percussive * percussive, axis=0)
        family_total = harmonic_power + percussive_power + 1e-8
        harmonicity = np.clip(harmonic_power / family_total, 0.0, 1.0).astype(
            np.float32
        )
        percussiveness = np.clip(percussive_power / family_total, 0.0, 1.0).astype(
            np.float32
        )
        flatness = align(librosa.feature.spectral_flatness(S=magnitude)[0], frame_count)
        centroid_hz = align(
            librosa.feature.spectral_centroid(S=magnitude, sr=sample_rate)[0],
            frame_count,
        )
        bandwidth_hz = align(
            librosa.feature.spectral_bandwidth(S=magnitude, sr=sample_rate)[0],
            frame_count,
        )
        rolloff_hz = align(
            librosa.feature.spectral_rolloff(
                S=magnitude, sr=sample_rate, roll_percent=0.90
            )[0],
            frame_count,
        )
        contrast_matrix = align(
            librosa.feature.spectral_contrast(S=magnitude, sr=sample_rate, n_bands=6),
            frame_count,
        ).T
        contrast = np.clip(np.mean(contrast_matrix, axis=1) / 50.0, 0.0, 1.0).astype(
            np.float32
        )

        checkpoint()
        progress(
            AnalysisProgress(
                0.31,
                AnalysisStage.RHYTHM,
                "Finding transients, pulse, beats, downbeats, and tempo",
            )
        )
        mel_power = librosa.feature.melspectrogram(
            S=power,
            sr=sample_rate,
            n_mels=64,
            fmin=24.0,
            fmax=sample_rate / 2.0,
        ).astype(np.float32)
        mel_db = _POWER_TO_DB(mel_power, ref=_ARRAY_MAX).astype(np.float32)
        onset_bands = align(
            _ONSET_STRENGTH_MULTI(
                S=mel_db,
                sr=sample_rate,
                hop_length=hop_size,
                channels=[0, 12, 28, 48, 64],
                aggregate=_ARRAY_MEDIAN,
                center=False,
            ),
            frame_count,
        )
        percussive_db = _AMPLITUDE_TO_DB(percussive, ref=_ARRAY_MAX)
        percussive_onset = align(
            _ONSET_STRENGTH(
                S=percussive_db,
                sr=sample_rate,
                hop_length=hop_size,
                aggregate=_ARRAY_MEDIAN,
                center=False,
            ),
            frame_count,
        )
        band_onset = 1.0 - np.exp(-np.maximum(onset_bands, 0.0) / 1.5)
        broadband_onset = np.mean(onset_bands, axis=0)
        combined_onset = 0.55 * broadband_onset + 0.45 * np.minimum(
            percussive_onset, broadband_onset * 4.0
        )
        onset = (1.0 - np.exp(-np.maximum(combined_onset, 0.0) / 1.5)).astype(
            np.float32
        )
        rhythm = analyze_rhythm(
            onset,
            band_onset[0],
            sample_rate=sample_rate,
            hop_size=hop_size,
            grid=grid,
            duration_seconds=audio.duration_seconds,
        )

        checkpoint()
        progress(
            AnalysisProgress(
                0.50,
                AnalysisStage.MUSICAL_CONTEXT,
                "Measuring timbre, harmony, pitch, and stereo space",
            )
        )
        if float(np.max(acoustic_confidence)) < 0.02:
            chroma = np.full((frame_count, 12), 1.0 / 12.0, dtype=np.float32)
        else:
            chroma = align(
                librosa.feature.chroma_stft(S=power, sr=sample_rate, n_chroma=12),
                frame_count,
            ).T
            chroma = positive_distribution(chroma)
        chroma_entropy = -np.sum(chroma * np.log(np.maximum(chroma, 1e-8)), axis=1)
        tonal_focus = np.clip(1.0 - chroma_entropy / math.log(12.0), 0.0, 1.0)
        harmony_confidence = np.clip(
            acoustic_confidence * (0.45 + 0.55 * (1.0 - flatness)), 0.0, 0.98
        ).astype(np.float32)
        coherence = np.clip(0.58 * tonal_focus + 0.42 * harmonicity, 0.0, 1.0).astype(
            np.float32
        )
        coherence = np.where(acoustic_confidence > 0.02, coherence, 0.5).astype(
            np.float32
        )
        harmonic_change = cosine_change(chroma, max(1, round(frame_rate * 0.5)))
        pitch_midi, pitch_confidence = _predominant_pitch(
            harmonic,
            frequencies,
            loudness_dbfs,
            flatness,
            harmonicity,
        )
        pan, width, correlation, spatial_confidence, spatial_validity = _spatial(
            stereo,
            frame_size,
            hop_size,
            frame_count,
            loudness_dbfs,
        )
        mfcc = align(librosa.feature.mfcc(S=mel_db, n_mfcc=20), frame_count).T
        timbre_descriptors = np.column_stack(
            (band_distribution, mfcc[:, 1:13], contrast_matrix, chroma)
        ).astype(np.float32)
        timbre_change = _descriptor_change(timbre_descriptors, frame_rate)

        checkpoint()
        progress(
            AnalysisProgress(
                0.67,
                AnalysisStage.STRUCTURE,
                "Discovering Sections and recurring musical material",
            )
        )
        brightness = np.clip(centroid_hz / (sample_rate / 2.0), 0.0, 1.0).astype(
            np.float32
        )
        structure_descriptors = np.column_stack(
            (
                mfcc[:, 1:13],
                contrast_matrix,
                chroma,
                band_distribution,
                relative_energy,
                flatness,
                harmonicity,
                percussiveness,
            )
        ).astype(np.float32)
        structure = analyze_structure(
            structure_descriptors,
            grid=grid,
            duration_seconds=audio.duration_seconds,
            audibility=acoustic_confidence,
            relative_energy=relative_energy,
            brightness=brightness,
            harmonicity=harmonicity,
            percussiveness=percussiveness,
        )
        audible = acoustic_confidence
        bass_register = np.clip(
            audible * (band_distribution[:, 0] + band_distribution[:, 1]),
            0.0,
            1.0,
        ).astype(np.float32)
        harmonic_layer = (audible * harmonicity).astype(np.float32)
        percussive_layer = (audible * percussiveness).astype(np.float32)
        noise_layer = (audible * flatness).astype(np.float32)
        events = tuple(
            sorted(
                (
                    *_onset_events(
                        onset,
                        band_flux,
                        grid,
                        audio.duration_seconds,
                    ),
                    *rhythm.events,
                    *structure.events,
                ),
                key=lambda event: (event.seconds, event.kind, event.event_id),
            )
        )
        timeline = AnalysisTimeline(
            grid=grid,
            window_seconds=frame_size / sample_rate,
            energy=EnergyAnalysis(
                scalar_signal(
                    grid,
                    loudness_dbfs,
                    confidence=acoustic_confidence,
                    unit="dBFS",
                ),
                scalar_signal(
                    grid,
                    relative_energy,
                    confidence=acoustic_confidence,
                    unit="relative",
                ),
                scalar_signal(
                    grid, crest_db, confidence=acoustic_confidence, unit="dB"
                ),
            ),
            rhythm=RhythmAnalysis(
                scalar_signal(
                    grid,
                    rhythm.onset,
                    confidence=acoustic_confidence,
                    unit="normalized",
                ),
                scalar_signal(
                    grid,
                    rhythm.pulse,
                    confidence=rhythm.confidence,
                    unit="normalized",
                ),
                scalar_signal(
                    grid,
                    rhythm.beat_phase,
                    confidence=rhythm.confidence,
                    unit="cycle",
                    circular=True,
                ),
                scalar_signal(
                    grid,
                    rhythm.tempo_bpm,
                    confidence=rhythm.confidence,
                    unit="bpm",
                ),
            ),
            spectrum=SpectrumAnalysis(
                vector_signal(
                    grid,
                    band_levels,
                    _BAND_NAMES,
                    confidence=acoustic_confidence,
                    unit="dBFS",
                ),
                vector_signal(
                    grid,
                    band_distribution,
                    _BAND_NAMES,
                    confidence=acoustic_confidence,
                    unit="power share",
                    distribution=True,
                ),
                vector_signal(
                    grid,
                    band_flux,
                    _BAND_NAMES,
                    confidence=acoustic_confidence,
                    unit="full-scale amplitude per second",
                ),
                scalar_signal(
                    grid,
                    centroid_hz,
                    confidence=acoustic_confidence,
                    unit="Hz",
                ),
                scalar_signal(
                    grid,
                    bandwidth_hz,
                    confidence=acoustic_confidence,
                    unit="Hz",
                ),
                scalar_signal(
                    grid,
                    rolloff_hz,
                    confidence=acoustic_confidence,
                    unit="Hz",
                ),
            ),
            timbre=TimbreAnalysis(
                scalar_signal(
                    grid,
                    flatness,
                    confidence=acoustic_confidence,
                    unit="ratio",
                ),
                scalar_signal(
                    grid,
                    contrast,
                    confidence=acoustic_confidence,
                    unit="normalized",
                ),
                scalar_signal(
                    grid,
                    timbre_change,
                    confidence=acoustic_confidence,
                    unit="normalized",
                ),
            ),
            harmony=HarmonyAnalysis(
                vector_signal(
                    grid,
                    chroma,
                    _PITCH_CLASSES,
                    confidence=harmony_confidence,
                    unit="probability",
                    distribution=True,
                ),
                scalar_signal(
                    grid,
                    coherence,
                    confidence=harmony_confidence,
                    unit="normalized",
                ),
                scalar_signal(
                    grid,
                    harmonic_change,
                    confidence=harmony_confidence,
                    unit="normalized",
                ),
                scalar_signal(
                    grid,
                    pitch_midi,
                    confidence=pitch_confidence,
                    unit="MIDI note",
                ),
            ),
            spatial=SpatialAnalysis(
                scalar_signal(
                    grid,
                    pan,
                    confidence=spatial_confidence,
                    unit="signed",
                    validity=spatial_validity,
                ),
                scalar_signal(
                    grid,
                    width,
                    confidence=spatial_confidence,
                    unit="normalized",
                    validity=spatial_validity,
                ),
                scalar_signal(
                    grid,
                    correlation,
                    confidence=spatial_confidence,
                    unit="signed",
                    validity=spatial_validity,
                ),
            ),
            layers=LayerAnalysis(
                scalar_signal(
                    grid,
                    bass_register,
                    confidence=acoustic_confidence,
                    unit="activity",
                ),
                scalar_signal(
                    grid,
                    harmonic_layer,
                    confidence=acoustic_confidence,
                    unit="activity",
                ),
                scalar_signal(
                    grid,
                    percussive_layer,
                    confidence=acoustic_confidence,
                    unit="activity",
                ),
                scalar_signal(
                    grid,
                    noise_layer,
                    confidence=acoustic_confidence,
                    unit="activity",
                ),
            ),
            structure=StructureAnalysis(
                scalar_signal(
                    grid, structure.novelty, confidence=0.88, unit="normalized"
                ),
                scalar_signal(
                    grid,
                    structure.section_progress,
                    confidence=0.95,
                    unit="section fraction",
                ),
            ),
        )
        sources = _acoustic_sources(
            grid,
            harmonic,
            percussive,
            frequencies,
            loudness_dbfs,
            acoustic_confidence,
        )
        issues: tuple[AnalysisIssue, ...] = ()
        if spatial_validity is SignalValidity.LIMITED:
            issues = (
                AnalysisIssue(
                    "music-analysis.false-stereo",
                    AnalysisIssueSeverity.DEGRADED,
                    "The decoded channels are effectively identical; spatial evidence is limited.",
                    _PROVENANCE.provider,
                ),
            )
        checkpoint()
        progress(
            AnalysisProgress(
                0.82,
                AnalysisStage.SOURCES,
                "Deterministic source-family evidence is ready",
            )
        )
        return TrackAnalysis(
            metadata=AudioMetadata(
                request.title or title,
                audio.duration_seconds,
                sample_rate,
                2,
            ),
            timeline=timeline,
            sections=structure.sections,
            events=events,
            sources=sources,
            issues=issues,
            provenance=(_PROVENANCE,),
        )


def _descriptor_change(descriptors: FloatArray, frame_rate: float) -> FloatArray:
    centered = descriptors - np.median(descriptors, axis=0, keepdims=True)
    scaled = centered / (np.std(centered, axis=0, keepdims=True) + 1e-5)
    normalized = scaled / (np.linalg.norm(scaled, axis=1, keepdims=True) + 1e-8)
    change = cosine_change(normalized, max(1, round(frame_rate * 0.5)))
    return smooth(robust_unit(change), max(1, round(frame_rate * 0.12)))


def _relative_energy(
    loudness_dbfs: FloatArray,
    acoustic_confidence: FloatArray,
    smoothing_radius: int,
) -> FloatArray:
    if float(np.max(acoustic_confidence)) < 0.02:
        return np.zeros_like(loudness_dbfs)
    levels = smooth(loudness_dbfs, smoothing_radius)
    low = float(np.percentile(levels, 8.0))
    high = float(np.percentile(levels, 97.0))
    if high - low < 0.25:
        return np.full_like(levels, 0.5)
    result: FloatArray = np.clip((levels - low) / (high - low), 0.0, 1.0).astype(
        np.float32
    )
    return result


def _predominant_pitch(
    harmonic: FloatArray,
    frequencies: FloatArray,
    loudness_dbfs: FloatArray,
    flatness: FloatArray,
    harmonicity: FloatArray,
) -> tuple[FloatArray, FloatArray]:
    mask = (frequencies >= 45.0) & (frequencies <= 2_000.0)
    candidates = harmonic[mask]
    candidate_frequencies = frequencies[mask]
    peak_indices = np.argmax(candidates, axis=0)
    peak_hz = candidate_frequencies[peak_indices].astype(np.float32)
    pitch = (69.0 + 12.0 * np.log2(np.maximum(peak_hz, 1e-5) / 440.0)).astype(
        np.float32
    )
    peak = np.max(candidates, axis=0)
    concentration = peak / (np.sum(candidates, axis=0) + 1e-8)
    audible = dbfs_unit(loudness_dbfs, floor=-76.0, ceiling=-38.0)
    confidence = np.clip(
        audible
        * harmonicity
        * (0.45 * (1.0 - flatness) + 0.55 * np.clip(concentration * 4.0, 0.0, 1.0)),
        0.0,
        1.0,
    ).astype(np.float32)
    return pitch, confidence


def _spatial(
    stereo: FloatArray,
    frame_size: int,
    hop_size: int,
    frame_count: int,
    loudness_dbfs: FloatArray,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, SignalValidity]:
    left = librosa.util.frame(
        stereo[:, 0], frame_length=frame_size, hop_length=hop_size
    ).T
    right = librosa.util.frame(
        stereo[:, 1], frame_length=frame_size, hop_length=hop_size
    ).T
    left_energy = np.mean(left * left, axis=1) + 1e-10
    right_energy = np.mean(right * right, axis=1) + 1e-10
    pan = align(
        (right_energy - left_energy) / (right_energy + left_energy), frame_count
    )
    side = np.mean((left - right) ** 2, axis=1)
    middle = np.mean((left + right) ** 2, axis=1) + 1e-10
    width = np.clip(align(np.sqrt(side / middle), frame_count) / 2.0, 0.0, 1.0)
    numerator = np.mean(left * right, axis=1)
    correlation = align(numerator / np.sqrt(left_energy * right_energy), frame_count)
    difference = float(np.mean(np.abs(stereo[:, 0] - stereo[:, 1])))
    scale = float(np.sqrt(np.mean(stereo * stereo)))
    false_stereo = difference / max(scale, 1e-8) < 1e-4
    confidence = (
        np.zeros(frame_count, dtype=np.float32)
        if false_stereo
        else 0.96 * dbfs_unit(loudness_dbfs, floor=-78.0, ceiling=-42.0)
    )
    validity = SignalValidity.LIMITED if false_stereo else SignalValidity.VALID
    return (
        np.clip(pan, -1.0, 1.0).astype(np.float32),
        width.astype(np.float32),
        np.clip(correlation, -1.0, 1.0).astype(np.float32),
        confidence.astype(np.float32),
        validity,
    )


def _onset_events(
    onset: FloatArray,
    band_flux: FloatArray,
    grid: TimeGrid,
    duration_seconds: float,
) -> tuple[MusicalEvent, ...]:
    frame_rate = 1.0 / grid.step_seconds
    frames: IntArray = np.asarray(
        librosa.util.peak_pick(
            onset,
            pre_max=max(1, round(frame_rate * 0.05)),
            post_max=max(1, round(frame_rate * 0.05)),
            pre_avg=max(1, round(frame_rate * 0.16)),
            post_avg=max(1, round(frame_rate * 0.16)),
            delta=0.10,
            wait=max(1, round(frame_rate * 0.045)),
            sparse=True,
        ),
        dtype=np.int32,
    )
    result: list[MusicalEvent] = []
    for index, frame in enumerate(frames):
        seconds = grid.time_at(int(frame))
        if seconds > duration_seconds:
            continue
        weights = np.maximum(band_flux[frame], 0.0)
        total = float(np.sum(weights))
        if total <= 1e-8:
            continue
        profile = tuple(float(value) for value in weights / total)
        result.append(
            MusicalEvent(
                event_id=f"onset-{index}-{int(frame)}",
                kind=EventKind.ONSET,
                seconds=seconds,
                strength=float(np.clip(onset[frame], 0.0, 1.0)),
                confidence=float(np.clip(0.48 + 0.48 * onset[frame], 0.0, 0.96)),
                bands=VectorSample(
                    profile,
                    _BAND_NAMES,
                    0.90,
                    "power share",
                    SignalValidity.VALID,
                ),
            )
        )
    return tuple(result)


def _acoustic_sources(
    grid: TimeGrid,
    harmonic: FloatArray,
    percussive: FloatArray,
    frequencies: FloatArray,
    mix_loudness_dbfs: FloatArray,
    acoustic_confidence: FloatArray,
) -> tuple[SourceAnalysis, ...]:
    harmonic_power = np.mean(harmonic * harmonic, axis=0)
    percussive_power = np.mean(percussive * percussive, axis=0)
    total = harmonic_power + percussive_power + 1e-8
    sources: list[SourceAnalysis] = []
    unavailable = np.zeros(grid.frame_count, dtype=np.float32)
    for source_id, kind, label, spectrum, power in (
        ("harmonic", SourceKind.HARMONIC, "Harmonic family", harmonic, harmonic_power),
        (
            "percussive",
            SourceKind.PERCUSSIVE,
            "Percussive family",
            percussive,
            percussive_power,
        ),
    ):
        presence = np.clip(power / total, 0.0, 1.0).astype(np.float32)
        loudness = (
            mix_loudness_dbfs + 10.0 * np.log10(np.maximum(presence, 1e-7))
        ).astype(np.float32)
        onset = robust_unit(np.maximum(0.0, np.diff(power, prepend=power[:1])))
        centroid = (
            np.sum(spectrum * frequencies[:, None], axis=0)
            / (np.sum(spectrum, axis=0) + 1e-8)
        ).astype(np.float32)
        confidence = np.clip(acoustic_confidence * 0.78, 0.0, 0.88)
        sources.append(
            SourceAnalysis(
                source_id,
                kind,
                label,
                float(np.mean(confidence)),
                scalar_signal(
                    grid, presence, confidence=confidence, unit="power share"
                ),
                scalar_signal(grid, loudness, confidence=confidence, unit="dBFS"),
                scalar_signal(grid, onset, confidence=confidence, unit="normalized"),
                scalar_signal(grid, centroid, confidence=confidence, unit="Hz"),
                scalar_signal(
                    grid,
                    unavailable,
                    confidence=0.0,
                    unit="signed",
                    validity=SignalValidity.UNAVAILABLE,
                ),
                scalar_signal(
                    grid,
                    unavailable,
                    confidence=0.0,
                    unit="normalized",
                    validity=SignalValidity.UNAVAILABLE,
                ),
                _PROVENANCE,
            )
        )
    return tuple(sources)


__all__ = ["DeterministicMusicAnalyzer"]
