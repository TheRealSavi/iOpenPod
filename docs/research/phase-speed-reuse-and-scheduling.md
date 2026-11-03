# Phase feature reuse and scheduling experiments

Date: 2026-11-02. These experiments follow the
[first speed comparison](phase-speed-output-comparison.md). The reference already
includes the equivalent 31-bin HPSS filter. Musical thresholds, section sizes,
context, sample rates, FFT sizes and model weights are held fixed.

## Corpus and measurement

The user authorized testing music on the Active iPod at `D:\`. Eight full Tracks
were read into private Host fixtures through iOpenPod's configured FFmpeg and
FFprobe selection. Source hashes, durations, decoded PCM hashes and unchanged
source-file checks are retained in the private manifest. No music, separated
waveforms or original-game binaries are included in the repository.

| Track | Artist | Duration (seconds) |
| --- | --- | ---: |
| inferno (edit) | yeule | 139.920 |
| ghosts | yeule | 220.776 |
| Aerodynamic | Daft Punk | 207.533 |
| Backseat Freestyle | Kendrick Lamar | 212.536 |
| Never Meant | American Football | 268.333 |
| Male Fantasy | Billie Eilish | 194.887 |
| My Own Summer (Shove It) | Deftones | 215.480 |
| Godspeed | Frank Ocean | 177.920 |

Total duration is 1,637.385 seconds (27.28975 minutes), across seven artists.
This broadens the previous corpus but is not a representative music dataset.
Measurements use the same Windows i9-13900KS / RTX 4070 Host. CPU/GPU clocks and
other operating-system activity are not controlled. Heavy experiment jobs run
one at a time; correctness checks run separately from timing.

The primary compatibility check serializes each candidate chart and executes the
original Phase build-3168002 ARM parser and chart converter at all four difficulty
indices. It compares ordered complete tap payloads, annotations, marker records,
selected counts and phrase summaries. This is original conversion code in an
emulator with research adapters; rendering, judging and physical playback are
outside this test. Output differences describe changes from the reference,
not musical accuracy against hand-labelled ground truth.

## Original Phase output

Every independently generated baseline/candidate pair was executed at each
difficulty. These totals count one side of each comparison, not both copies:

| Path | Song/difficulty comparisons | Identical complete callbacks | Taps | Annotations | Markers | Metadata |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Acoustic feature changes | 32 | 25,681 | 9,890 | 15,479 | 280 | 32 |
| Experimental acoustic scheduler | 32 | 25,681 | 9,890 | 15,479 | 280 | 32 |
| CUDA overlap | 32 | 25,958 | 10,176 | 15,470 | 280 | 32 |
| Combined production features, overlap and retained worker | 32 | 25,958 | 10,176 | 15,470 | 280 | 32 |

Each row retains all 184 checkpoint markers exactly. There are zero missing or
added taps, changed lanes, changed tap timestamps, changed annotation fields or
changed callback ordering. Selected counts and phrase summaries also match.
The combined production comparison runs the actual managed worker and its request
protocol, then consumes the returned evidence through the application's chart
authoring and original-game converter. Full evidence arrays and chart objects
also compare exactly equal. These are overlapping experiments on the same songs,
not independent expansions of the musical sample size.

## Feature calculations

The attack measurement originally computes positive differences for all 1,025
FFT bins, although only 354 bins enter its three band reductions. Selecting each
band first removes unused arithmetic while preserving selected-bin order and
the existing reductions. The other change caches immutable frequency/pitch masks
and selects the chroma power matrix once instead of copying it 12 times.

Three alternating samples per song, with ten calls per timed sample, give these
means over 24 samples. Each call measures one source-sized music block; these
are feature timings, not complete Track or Sync timings.

| Variant | Mean feature time (ms) | Time reduction |
| --- | ---: | ---: |
| Reference | 27.081866 | — |
| Retained frequency bands only | 25.780930 | 4.8037% |
| Reused masks and chroma selection | 26.352165 | 2.6944% |
| Both changes | 25.065571 | 7.4452% |

An earlier single-call timing series is retained as diagnostic data. The repeated
series above is the primary measurement. Both show operating-system timing
variation; no cross-platform speed guarantee follows from these numbers.

For a source-sized block, peak traced allocations fall from 10,968,192 to
8,768,763 bytes. Within the attack calculation alone, they fall from 4,252,564 to
1,719,704 bytes. These are Python/NumPy allocations observed by `tracemalloc`,
not total process working set or GPU memory.

Across 24 full acoustic runs per variant, summed time is 182.264 seconds for the
reference and 185.086 seconds for the candidate: the candidate took 1.55% longer
in this series. A large mid-run timing shift is retained in the samples. This
experiment does not demonstrate a complete acoustic-analysis speedup.

## Acoustic worker scheduling

The candidate replaces two-block batch barriers with a rolling queue, keeping
the existing two-worker limit. The coordinator alone publishes disjoint output
slices and invokes application checkpoints.

Three alternating pairs per song give summed per-song means of 46.997777 seconds
for the reference and 46.413042 seconds for the candidate: 1.2442% less acoustic
stage time. Twelve of 24 individual pairs are faster. Candidate-minus-reference
differences have median −0.012271 seconds, mean −0.073092 seconds, sample standard
deviation 0.205427 seconds, and range −0.437657 to +0.269552 seconds.

A paired song-cluster bootstrap, retaining each song's three pairs, gives a 95%
percentile interval of 0.0769%–2.2952% time reduction (seed 20261102; 10,000
resamples). This describes resampling these selected songs on this Host. It does
not estimate performance on other hardware or a representative music population.

The rolling scheduler remains experimental. Only 12 of 24 pairs are faster, and
the inferno mean is 3.34% slower; the current application retains its existing
acoustic scheduler.

## CUDA inference and CPU feature overlap

The candidate keeps one model caller and one pending CPU feature block. While
the GPU processes the next unchanged 344-frame section, a single CPU worker
resamples and measures the preceding section. All 86-frame context, normalization
and feature operations are retained. CPU and MPS paths remain serial.

Three alternating pairs per song give summed per-song means of 104.1335 seconds
serial and 51.7662 seconds overlapped: **50.2887% less warm source-analysis time**.
Individual song reductions are 47.97%–53.13%. These measurements exclude imports,
model loading, decoding, full-mix acoustic fusion, encoding and device writes.

Peak Torch allocation stays at 599,919,104 bytes, and peak Torch reservation stays
at 788,529,152 bytes in every measured run. Mean sampled process working-set peaks
increase by about 3.79 MB; the largest observed samples increase from
1,645,072,384 to 1,663,004,672 bytes. Working set was sampled every 20 ms and is
not a hard upper bound. The queue adds at most one retained CPU feature block.

## Retaining the downloaded model for one preparation

A separate research worker runs the unchanged reference source algorithm with
either one interpreter/model per Track or one interpreter/model for all eight
Tracks. This isolates retention from the feature and overlap changes. Timings
include interpreter startup, library imports, model loading, private PCM reads
and evidence-file writes. They exclude decoding, full-mix acoustic fusion,
game-file encoding and device publication.

Two complete paired jobs were run in ABBA order:

| Pair | Separate workers (seconds) | Retained worker (seconds) | Time reduction |
| --- | ---: | ---: | ---: |
| 1: separate then retained | 103.726759 | 75.164601 | 27.5360% |
| 2: retained then separate | 126.031451 | 103.478639 | 17.8946% |
| Mean | 114.879105 | 89.321620 | 22.2473% |

All returned arrays match across the four jobs. Maximum child-process peak working
set is 1,553,588,224 bytes with separate workers and 1,558,605,824 bytes with
retention. The retained model occupies memory between Tracks until the preparation
closes. These two pairs provide descriptive measurements, not a confidence
interval. Their speed reduction must not be added to the isolated overlap result.

The actual combined production worker processed the eight Tracks successfully and
released its resources. Its timing is not used as a performance benchmark because
other validation ran concurrently. The resulting files supply the combined
original-game comparison above.

The first production integration attempt exposed a Windows startup hang: both
buffered and raw blocking stdin reads in the parent-lifetime watcher stalled
NumPy's native-module import. The bounded reproduction captured both thread
stacks. Nonblocking pipe polling fixes that loop; Python 3.12 supports nonblocking
Windows pipes through [os.set_blocking](https://docs.python.org/3.12/library/os.html#os.set_blocking).
Regression tests cover import while the pipe is open, normal
interpreter shutdown, EOF during idle/work, and watcher setup failure. Parent
loss ends the isolated worker without waiting for an analysis checkpoint.

Feature reuse, retained preparation workers and CUDA overlap are enabled. The
musical policy and cache algorithm identity remain version 7; no dependency or
model download is added.

## Implementation validation

The full Windows test run passes 10,471 tests, with 47 skips for platform-specific
semantics or unavailable private captures. Its one warning comes from the existing
large-photo dimension test. UV lock validation, Ruff formatting and lint, Mypy,
Rumdl and focused strict Pyright checks pass. Source and wheel builds succeed;
the new wheel's runtime files and resources match the source tree.

The full-suite run exposed two integration issues that were fixed before the
passing rerun: default media-tool cleanup now accesses stdin only when the optional
lifetime pipe was requested, and worker IPC retries transient Windows permission
failures for at most one second while continuing to check cancellation. Regression
tests cover successful retries, exhausted retries and cancellation; other file
errors still propagate. These fixes do not alter the analysis calculations.

The rebuilt Windows executable passes manifest and payload inspection. From a
separate working directory, its frozen runtime check exercises acoustic analysis,
one standalone downloaded-model request and two requests through a retained
worker. All pass using the installed private test runtime. Native macOS and Linux
execution were not performed in this experiment.

The unsigned Windows x64 MSIX also passes package integrity, identity, embedded
build/license checks and the extracted executable's runtime smoke test. The local
artifact is `dist/iOpenPod-2.1.0-Windows-x64-phase-reuse-review.msix`, with SHA-256
`af99cbd0b6af7d1db6f8a17f9856ea04df54510e24756501a0be625834b0a29f`.
Installed Store identity and Certification Kit checks require a signed package
and were not run here.

## Private reproduction material

Scripts, source snapshots, corpus provenance and individual samples are under
`.scratch/phase-speed-next/`. `parts-feature-repeat.json` and `parts-timings.json`
retain feature and full-acoustic measurements; `parts-summary.json` summarizes
them. `scheduler-timing.json` and `scheduler-summary.json` retain scheduler pairs
and the bootstrap definition. `overlap-timings.json` and `overlap-summary.json`
retain the model-stage runs and memory observations.
`worker-reuse-timings.json` retains isolated retention measurements;
`worker-summary.json` records array and combined original-game equality.
`parts-native.json`, `scheduler-native.json`, `overlap-native.json` and
`worker-native-results.json` retain the emitted records. All original-game runs
use image SHA-256
`35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258`.
