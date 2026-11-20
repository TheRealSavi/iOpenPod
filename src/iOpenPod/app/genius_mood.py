"""Conservative acoustic fits; no quotas or inferred emotional/lyrical labels."""

from __future__ import annotations

import math
from dataclasses import dataclass

from iOpenPod.app.genius_audio import GENIUS_AUDIO_FEATURE_COUNT, GeniusAudioProfile


@dataclass(frozen=True, slots=True)
class MoodFit:
    calm: float
    steady: float
    energetic: float


def _ramp(value: float, low: float, high: float) -> float:
    return min(1.0, max(0.0, (value - low) / (high - low)))


def mood_fit(profile: GeniusAudioProfile) -> MoodFit | None:
    """Require activity, rhythm and dynamics evidence, not just a plausible BPM.

    Curves are product heuristics in measured units, not trained probabilities.
    Tempo contributes only to an evidenced pulse, avoiding a hard 110/125 BPM
    boundary when the estimator hears a beat at half or double time.
    """
    character = profile.character
    if (
        character is None
        or profile.duration_seconds < 10
        or not math.isfinite(profile.duration_seconds)
        or len(profile.body) != GENIUS_AUDIO_FEATURE_COUNT
        or not all(math.isfinite(value) for value in profile.body)
        or character.active_fraction < 0.8
    ):
        return None
    tempo, centroid, variance = profile.body[:3]
    if centroid <= 200 or variance < 0 or tempo < 0:
        return None
    texture = (math.sqrt(variance) / centroid) ** 2
    activity = _ramp(character.spectral_activity, 25, 80)
    brightness = _ramp(centroid, 1200, 3200)
    noise = _ramp(character.spectral_flatness, 0.008, 0.06)
    pulse = _ramp(character.beat_strength, 0.15, 0.65)
    # Periodicity is not intensity: even gentle repeated guitar/piano notes can
    # produce a sharp autocorrelation peak. Require activity to support drive.
    drive = pulse * (0.65 + 0.35 * _ramp(tempo, 70, 155)) * (0.4 + 0.6 * activity)
    energy = max(
        0.5 * activity + 0.3 * drive + 0.2 * brightness,
        # Dense distorted music can have few distinct attacks. Require both
        # noisy texture and brightness rather than mistaking it for calm music.
        0.6 * noise + 0.4 * brightness,
    )
    calm = (
        0.45 * (1 - activity)
        + 0.2 * (1 - brightness)
        + 0.2 * (1 - drive)
        + 0.15 * (1 - noise)
    )
    # Centroid movement also describes changes in pitch/instrumentation. Let
    # dynamics lead, so ordinary melodic development does not veto calmness.
    steady = 0.3 * (1 - _ramp(texture, 0.06, 0.6)) + 0.7 * (
        1 - _ramp(character.dynamic_range_db, 6, 20)
    )
    return MoodFit(calm, steady, energy)


def focus_candidate(profile: GeniusAudioProfile) -> bool:
    """Cheap acoustic gate before optional vocal inference."""
    fit = mood_fit(profile)
    return (
        fit is not None
        and fit.calm >= 0.7
        and fit.steady >= 0.65
        and fit.energetic <= 0.35
    )


def mood_matches(key: str, profile: GeniusAudioProfile) -> bool:
    fit = mood_fit(profile)
    if fit is None:
        return False
    if key == "focus":
        return (
            focus_candidate(profile)
            and profile.vocals is not None
            and profile.vocals.vocal_fraction <= 0.15
        )
    if key == "energy":
        return fit.energetic >= 0.65 and fit.calm < 0.55
    if key == "relax":
        return fit.calm >= 0.65 and fit.energetic <= 0.4
    if key == "love":
        # The caller additionally requires an explicit title/album subject cue.
        return fit.calm >= 0.5 and fit.energetic <= 0.5
    return False
