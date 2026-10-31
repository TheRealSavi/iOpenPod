# Phase algorithm version 6 evaluation

Date: 2026-10-31. Decision:
[ADR-0221](../adr/0221-preserve-phase-spectral-lane-evidence.md).

## Change and evidence boundary

Version 6 separates normalized attack detection from encoded magnitude. The
shipped 80–300, 400–1500 and 2000–4500 Hz ranges measure linear spectral increases
for both mix and sources. A single mix-derived scale and whole-vector compression
preserve relative spectral balance through saturation, subject to five-bit
rounding. Detection, beat power and hook recognition retain their version-5
policies. This is a new producer policy informed by native consumers, not a
reconstruction of Apple's producer filters or quantizer.

Independent band calibration could previously make a weaker band win a lane;
independent clipping could make unequal evidence become `(31,31,31)`. Authored
tests now verify frequency gaps, linear gain, primary/alternative ordering,
quiet-band balance, and ratio preservation through saturation. Source detection
arrays remain distinct from linear magnitude arrays and immutable after capture.

## Paired music comparison

The five read-only recordings, hashes, clip offsets and model identity are those
in the [version-5 evaluation](phase-algorithm-v5.md). Version 6 reuses its exact
mono PCM, and reruns the same pinned separation model to measure new source
magnitudes. Existing detection/energy/chroma arrays match exactly for the four
90-second clips. Poppies is clipped to its declared duration on remeasurement;
its final separation block has small feature differences (last two seconds),
so that source-assisted comparison is not a strict single-variable experiment.
Full-mix candidate timestamps and all beat records compare exactly
equal to version 5 for every fixture. Source-assisted candidate counts remain
equal; some close source-only detections retain a different measured timestamp
as their merge priority now uses linear amplitude. Existing mix timings
remain anchored. Original recordings and user/device saves were not modified.

The unchanged build-3168002 ARM converter accepts all ten charts (with and without
source assistance) at all four difficulty indices: **40 conversions**. On Hard,
all ten outputs match the Windows translation's exact tap/annotation payloads,
callback order and marker strings. Game image and configuration identities are
unchanged from the version-5 evaluation. This exercises native chart generation,
not rendering, audio synchronization, hit judgment or physical gameplay.

Source-assisted Hard output:

| Recording | Candidates, both versions | v5 taps | v6 taps | v5 tied maxima | v6 tied maxima |
| --- | ---: | ---: | ---: | ---: | ---: |
| Poppies | 1252 | 315 | 312 | 227 | 63 |
| 505 | 697 | 168 | 166 | 100 | 39 |
| Clocks | 686 | 202 | 209 | 143 | 30 |
| The Red | 630 | 147 | 145 | 134 | 30 |
| ocean eyes | 473 | 145 | 145 | 139 | 36 |

All-31 triples change from 50/2/13/24/46 respectively to zero in these fixtures.
Ties are not universally wrong, and no tie-rate target or forced lane balancing
was used. Acoustic-only Hard taps change from 315/166/202/138/123 to
316/166/196/138/119. This revision preserves broadly similar density; it is not
intended to maximize the number of taps.

| Recording | v5 lane-mask counts (1 / 2 / 4) | v6 lane-mask counts (1 / 2 / 4) |
| --- | --- | --- |
| Poppies | 72 / 134 / 109 | 191 / 59 / 62 |
| 505 | 42 / 87 / 39 | 92 / 27 / 47 |
| Clocks | 47 / 76 / 79 | 119 / 82 / 8 |
| The Red | 42 / 47 / 58 | 77 / 36 / 32 |
| ocean eyes | 36 / 47 / 62 | 64 / 78 / 3 |

The new measurement often favors low frequencies and yields fewer bright-lane
notes on piano/vocal fixtures. Preserving measured spectral relationships does
not imply evenly distributed lanes. The native game still chooses alternatives
and repeat variation; these results require listening/play evaluation before
claiming more satisfying patterns.

Using the fixed version-5 inferred source labels and the same 60 ms match window,
foreground matches change from 293/165/180/102/56 to 288/161/184/100/54. Hook
matches change from 206/164/135/61/17 to 202/160/138/61/17. These are not
ground-truth instrument labels, and there is no consistent coverage improvement.
The demonstrated improvement is preservation of spectral amplitude relationships,
not a claim of better transcription or universally better play feel.

The longest Poppies tap-only gap increases from 7.431 to 8.000 seconds; The Red
decreases from 9.416 to 7.709 seconds. Tap-only gaps exclude native checkpoints
and sweeps and must not be called empty gameplay without inspecting annotations.

## Reproduction and regression checks

Private `.scratch/phase-v6/prepare.py` verifies recording hashes, measures sources,
and retains compact arrays and generated charts. `evaluate.py` reuses the
version-5 native adapters, and `compare.py` writes `comparison.json`, including
lane histograms, ties, inferred coverage and timestamp comparisons. All four
`results-v6-d*.json` files retain full native sink output. No copyrighted audio,
game binary or chart is committed.

```powershell
uv run python .scratch/phase-v6/prepare.py
uv run --with unicorn==2.1.4 python .scratch/phase-v6/evaluate.py 2
uv run python .scratch/phase-v6/compare.py
```

Authored regressions also cover held-tone suppression, accompaniment retention,
quiet-source calibration, timing, tempo changes, exact serial/parallel output,
recurring hooks, cancellation, silent stereo folds, codec limits, publication and
cache reuse. `librosa-phase-6` is part of the service identity; ordinary Save/Sync
regenerates prior-version charts, while device selection still defers analysis.

Repository validation: Ruff formatting/lint, Rumdl, lock validation and Mypy
pass. The full eight-worker test run reports 10,030 passed and 47 platform skips,
plus 24 collection errors (three unrelated updater modules repeated across eight
workers). Their unchanged `version_fixtures.patch_version(-1)` rejects the
repository's current `2.1.0` version because its patch component is zero. No
executed test failed; the complete suite therefore cannot be called green.
