# Phase speed and native output comparison

Date: 2026-11-02. Baseline: `librosa-phase-7` and the six-source checkpoint
`5c90dfd2`. Measurements use an Intel i9-13900KS and NVIDIA RTX 4070 on Windows.

## Method

Each generated chart is serialized to an encrypted Phase analysis file. The
unchanged original Phase build 3168002 ARM parser and gameplay converter consume
that file in the local emulator. Image SHA-256:
`35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258`.
These are original-game execution results, not a reimplementation's prediction
or a physical iPod playthrough. Research adapters provide the execution environment
and record callbacks; this does not exercise the rendering or judging loop.

The primary observations are emitted tap records, lane masks, annotations and
marker callbacks. Tap records are callback offset 12; payload field 1 is the
lane mask and field 2 is time in integer milliseconds. Sweep-related intervals
appear among offset-16 annotations, so tap counts do not count every game event.
Checkpoint markers are counted separately.

Within each song and difficulty, tap matching first maximizes the number of
one-to-one pairs within 35 ms inclusive, then minimizes total absolute timing
displacement. Lane is not used to choose matches. “Missing” and “added” mean
unmatched relative to the current algorithm, not mistakes against musical ground
truth. Timing percentiles describe matched pairs only; they exclude unmatched
taps. All four difficulty indices are executed separately. Pooling counts across
difficulties does not create independent song observations.

Full recordings and their hashes are listed in the
[version-7 evaluation](phase-algorithm-v7.md). The model experiment uses all five
listed songs (1,110.647 seconds total). Acoustic experiments use *inferno (edit)*
and *ghosts* in full (360.696 seconds total). No recordings or game binaries are
committed.

## Equivalent acoustic filter implementation

The acoustic analyzer's 31-bin median filters, reflected boundaries, power-2 soft masks and
margin 2 are retained. The implementation uses SciPy's specialized two-dimensional
median filter with explicit symmetric padding and cropping. It transposes the
frequency filter so both passes operate along contiguous rows, then restores the
original array layout before downstream measurements. SciPy was already shipped
through librosa; declaring it directly adds no new package or version to the
locked dependency closure.

Two alternating warm runs per implementation, in seconds:

| Full song | Original runs | Optimized runs | Mean original | Mean optimized | Time reduction |
| --- | --- | --- | ---: | ---: | ---: |
| inferno (edit) | 4.335, 4.355 | 3.705, 3.689 | 4.345 | 3.697 | 14.9% |
| ghosts | 7.278, 7.600 | 6.241, 6.263 | 7.439 | 6.252 | 16.0% |

These times cover acoustic analysis with PCM already decoded, excluding startup,
decoding and device writes. With two repetitions on one computer, these are
descriptive measurements, not a confidence interval or a cross-platform speed
guarantee. The actual production implementation was run through the original
game for both full songs at all four difficulties. All **5,832 callbacks match
exactly**: 2,233 tap records, 3,527 annotations, 64 markers (including 40
checkpoints), and eight metadata calls. Callback order, timestamps, complete
payloads, selected counts and phrase summaries match. The eight executions count
each difficulty independently. Full chart objects also compare exactly equal.

This implementation is adopted. The algorithm identity stays at version 7 because
the evidence and gameplay mapping are preserved. Tests compare exact values,
dtype and array layout against librosa for short blocks, both memory layouts,
silence, repeated values and random spectra, plus complete authored charts.

## Larger model sections: 344 to 496 frames

The model pads inference to its 7.8-second training segment. Retaining 496 frames
instead of 344, with the same 86-frame context on each side, reduces calls while
remaining below that segment limit. The measured peak Torch GPU allocation is
599,919,104 bytes for both settings; this is not total process memory or driver
reservation. The larger sections remain experimental.

Warm CUDA source-analysis timing, one accepted pair per full song, in seconds:

| Song | Current 344 frames | Candidate 496 frames |
| --- | ---: | ---: |
| softscars | 11.6967 | 10.6715 |
| inferno (edit) | 10.1063 | 7.3921 |
| dazies | 17.4318 | 13.8622 |
| ghosts | 15.0787 | 11.5979 |
| sulky baby | 16.9784 | 14.5366 |
| Total | 71.2919 | 58.0603 |

Total measured source-stage time falls **18.56%**. The last pair was repeated
after an unrelated test run overlapped its first measurement; both measurements
remain in the private results. This excludes imports, model loading, decoding,
acoustic fusion, encoding and device writes. It is not an end-to-end Sync speedup.
Software: Python 3.12.14, Demucs 4.1.0, Torch 2.14.0+cu130 (24 CPU threads),
librosa 0.11.0. GPU clocks were not fixed.

Original Phase tap output, pooled over the five full songs:

| Difficulty index | Current taps | Candidate taps | Matched within 35 ms | Missing | Added | Exact timestamps among matches | Changed lanes among matches | Identical full tap records |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1,069 | 1,067 | 930 | 139 | 137 | 912 | 99 | 822 |
| 1 | 1,360 | 1,357 | 1,149 | 211 | 208 | 1,120 | 123 | 1,011 |
| 2 (Hard) | 2,065 | 2,075 | 1,762 | 303 | 313 | 1,686 | 209 | 1,516 |
| 3 | 2,396 | 2,415 | 1,992 | 404 | 423 | 1,900 | 248 | 1,698 |

For matched pairs, median and 95th-percentile absolute timing displacement are
0 ms at every difficulty. Maximum displacement is 35/23/35/35 ms respectively.
Those percentiles must be read together with the missing/added counts: for
example, Hard excludes 303 current taps and 313 candidate taps from the paired
timing distribution. The full tap-record comparison includes all emitted payload
fields, rather than just time and lane.

Hard matching-window sensitivity (no duplicate tap timestamps in either output):

| Allowed displacement | Matched | Missing | Added | Matched lane changes |
| ---: | ---: | ---: | ---: | ---: |
| 0 ms | 1,686 | 379 | 389 | 170 |
| 12 ms | 1,745 | 320 | 330 | 199 |
| 35 ms | 1,762 | 303 | 313 | 209 |
| 60 ms | 1,787 | 278 | 288 | 220 |

The original game also changes five of its 32 checkpoint times, identically at
each difficulty: softscars 140,384→139,384 ms; inferno 67,514→71,514 ms;
ghosts 35,644→36,644 ms and 146,579→143,579 ms; sulky baby
202,459→203,459 ms. Intro, intro-over and song-over markers remain identical.
All 2,419 type-4 timed annotations remain identical at each difficulty.

On Hard, type-0 annotations retain 15 exact payloads out of 43; type 1 retains
10 out of 17; type-2 sweep-related intervals retain 98 out of 208. Counts remain
43/17/208 respectively, but counts alone conceal changes in position or duration.
Matching annotation starts within 35 ms yields 18/10/102 pairs respectively.

## Smaller acoustic median kernels

Reducing the kernel from 31 to 21 or 17 leaves the original Phase consumer
unchanged. Over the same two full songs, the mean acoustic analysis time falls
from 4.499 to 3.525/3.103 seconds for *inferno (edit)*, and from 7.426 to
5.895/5.076 seconds for *ghosts*. These were two alternating runs per setting,
separate from the equivalent-filter experiment above. Summing the per-song means
gives 21.00% less acoustic analysis time for kernel 21 and 31.42% for kernel 17,
relative to the original implementation, before the equivalent-filter optimization.

Actual original-game output on Hard, pooled over those two songs:

| Setting | Current taps | Candidate taps | Matched within 35 ms | Missing | Added | Exact timestamps among matches | Changed lanes among matches | Identical full tap records |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Kernel 21 | 654 | 643 | 459 | 195 | 184 | 396 | 82 | 331 |
| Kernel 17 | 654 | 651 | 461 | 193 | 190 | 388 | 96 | 316 |

For both, matched absolute timing displacement has median 0 ms, 95th percentile
12 ms, and maximum 35 ms. Across all four difficulties, kernel 21 matches
1,621 of 2,233 current taps (612 missing, 587 added); kernel 17 matches 1,589
(644 missing, 631 added). These settings remain experimental.

Hard matching sensitivity for kernel 21 is 396/440/459/474 matched taps at
0/12/35/60 ms; kernel 17 yields 388/445/461/478. Across all difficulties,
type-2 sweep-related annotations change from 233 to 237 for either kernel;
71 complete records remain identical with kernel 21, and 40 with kernel 17.

## Reproduction

Private scripts, timings, original-game callbacks and individual matched pairs
are under `.scratch/phase-speed-tradeoffs/`. Acoustic results are in
`acoustic-game-results.json` and `acoustic-aggregate.json`; model results are in
`model-full-native.json` and `model-full-exact-stats.json`. The scripts reuse the
existing original-ARM harness in `.scratch/phase-v5/evaluate.py`.
`model-final-summary.json` includes accepted and original timing samples, all
annotation and marker statistics, matching-window sensitivity, and per-track
changes. `acoustic-production-all-results.json` retains the eight exact-output
checks of the production helper.

Only the equivalent filter implementation is enabled in the application. Model
section length and acoustic kernel-size experiments do not change the defaults.
None of these comparisons measures correctness against hand-labelled notes or
physical gameplay preferences.
