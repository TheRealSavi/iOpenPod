"""Immediate, presentation-only field motion while Track Analysis is pending."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .persistent_world import FieldForcing


@dataclass(frozen=True, slots=True)
class PreviewFieldModel:
    """Generate modest motion without reading or claiming Musical Evidence."""

    seed: int

    def sample(self, seconds: float) -> FieldForcing:
        phase = max(0.0, seconds)
        hue = ((self.seed % 997) / 997.0 + 0.012 * math.sin(phase * 0.13)) % 1.0
        swell = 0.5 + 0.5 * math.sin(phase * 0.43 + self.seed % 17)
        drift = math.sin(phase * 0.19 + self.seed % 11)
        return FieldForcing(
            activity=0.21 + 0.10 * swell,
            low_frequency_mass=0.12 + 0.08 * swell,
            fine_excitation=0.09 + 0.05 * (1.0 - swell),
            harmonic_coherence=0.58,
            palette_hue=hue,
            palette_spread=0.40,
            brightness=0.32 + 0.08 * swell,
            stereo_width=0.28,
            lateral_bias=0.12 * drift,
            harmonic_layer=0.18,
            section_energy=0.24,
        )


def blend_forcing(
    preview: FieldForcing,
    analyzed: FieldForcing,
    amount: float,
) -> FieldForcing:
    """Blend continuous controls; admit real events only after the handoff."""

    amount = min(1.0, max(0.0, amount))

    def mix(first: float, second: float) -> float:
        return first + (second - first) * amount

    hue_delta = (analyzed.palette_hue - preview.palette_hue + 0.5) % 1.0 - 0.5
    return FieldForcing(
        activity=mix(preview.activity, analyzed.activity),
        low_frequency_mass=mix(preview.low_frequency_mass, analyzed.low_frequency_mass),
        fine_excitation=mix(preview.fine_excitation, analyzed.fine_excitation),
        harmonic_coherence=mix(preview.harmonic_coherence, analyzed.harmonic_coherence),
        palette_hue=(preview.palette_hue + hue_delta * amount) % 1.0,
        palette_spread=mix(preview.palette_spread, analyzed.palette_spread),
        brightness=mix(preview.brightness, analyzed.brightness),
        spectral_flux=mix(preview.spectral_flux, analyzed.spectral_flux),
        timbral_noise=mix(preview.timbral_noise, analyzed.timbral_noise),
        stereo_width=mix(preview.stereo_width, analyzed.stereo_width),
        lateral_bias=mix(preview.lateral_bias, analyzed.lateral_bias),
        rhythmic_pulse=mix(preview.rhythmic_pulse, analyzed.rhythmic_pulse),
        beat_phase=analyzed.beat_phase,
        harmonic_layer=mix(preview.harmonic_layer, analyzed.harmonic_layer),
        percussive_layer=mix(preview.percussive_layer, analyzed.percussive_layer),
        vocal_layer=mix(preview.vocal_layer, analyzed.vocal_layer),
        bass_layer=mix(preview.bass_layer, analyzed.bass_layer),
        section_novelty=mix(preview.section_novelty, analyzed.section_novelty),
        section_progress=analyzed.section_progress,
        section_identity=analyzed.section_identity,
        section_energy=mix(preview.section_energy, analyzed.section_energy),
        impulses=analyzed.impulses if amount >= 1.0 else (),
    )


__all__ = ["PreviewFieldModel", "blend_forcing"]
