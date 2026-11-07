"""Spectral balance must survive chart encoding because it seeds native lanes."""

import numpy as np
import pytest

from iOpenPod.app.phase_audio import analyze_phase_pcm
from iOpenPod.app.phase_hooks import direct_parts
from iOpenPod.app.phase_parts import FFT, RATE, measure_band_attacks, measure_part


def test_band_measurement_uses_shipped_ranges_and_preserves_linear_gain() -> None:
    frequencies = np.fft.rfftfreq(FFT, 1 / RATE)
    spectrum = np.zeros((len(frequencies), 3))
    # Deliberate gaps and outer frequencies must not enter encoded magnitudes.
    for hz in (40, 350, 1750, 6000):
        spectrum[np.argmin(abs(frequencies - hz)), 1] = 100
    assert not measure_band_attacks(spectrum).any()
    for hz, amplitude in ((150, 9), (800, 3), (3000, 1)):
        spectrum[np.argmin(abs(frequencies - hz)), 1:] = amplitude
    measured = measure_band_attacks(spectrum)
    np.testing.assert_allclose(measured[:, 1], np.array([9, 3, 1]) / FFT)
    assert not measured[:, 2].any()  # Held energy is not a new attack.
    np.testing.assert_allclose(measure_band_attacks(spectrum * 0.2), measured * 0.2)


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 0, 1), (1, 2, 0)])
def test_shared_quantization_preserves_primary_alternative_and_clipped_shape(
    order: tuple[int, int, int],
) -> None:
    count = 1200
    frames = tuple(range(20, 1100, 40))
    bands = np.zeros((3, count))
    shape = np.array([1.0, 0.3, 0.1])[list(order)]
    bands[:, list(frames)] = shape[:, None]
    bands[:, frames[-1]] *= 100  # Rare loud attack must not flatten all bands.
    events = direct_parts(
        (),
        beats=[],
        length_ms=15000,
        checkpoint=lambda: None,
        mix_bands=bands,
        mix_energy=np.ones(count),
        mix_onsets=frames,
    )
    assert len(events) == len(frames)
    for event in events:
        values = np.array([event.low, event.mid, event.high])
        assert tuple(np.argsort(values)) == tuple(np.argsort(shape))
        np.testing.assert_allclose(values / values.max(), shape, atol=1 / 31)


def test_quieter_band_does_not_get_its_own_maximum_gain() -> None:
    # Each region has an equally clear onset. Its real amplitude, not its
    # independently normalized novelty, must determine the primary band.
    t = np.arange(30 * RATE) / RATE
    signal = np.zeros(len(t))
    for start in np.arange(1, 29, 0.5):
        age = t - start
        shape = np.where(
            (age >= 0) & (age < 0.12), np.sin(np.pi * np.clip(age / 0.12, 0, 1)) ** 2, 0
        )
        signal += shape * sum(
            amplitude * np.sin(2 * np.pi * hz * t)
            for hz, amplitude in ((150, 0.6), (800, 0.2), (3000, 0.06))
        )
    pcm = signal.astype(np.float32)
    chart = analyze_phase_pcm(pcm.tobytes(), length_ms=30000)
    assert len(chart.transients) >= 45
    assert (
        sum(e.low > e.mid > e.high for e in chart.transients)
        >= len(chart.transients) * 0.95
    )
    # The source provider and mix use the same physical measurement units.
    _, _, _, source_magnitudes = measure_part(pcm)
    _, _, _, quiet_magnitudes = measure_part(pcm * 0.25)
    np.testing.assert_allclose(quiet_magnitudes, source_magnitudes * 0.25, atol=1e-9)
