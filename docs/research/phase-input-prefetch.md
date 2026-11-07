# Phase input prefetch measurements

Date: 2026-11-02. This experiment tests overlapping device reads with Phase
analysis. The analysis algorithm, model, parameters and cache identity are
unchanged from the [previous experiments](phase-speed-reuse-and-scheduling.md).

## Reproduction and implementation

An integration regression uses a virtual device and the real `prepare_phase`
workflow. Analysis of the first Track waits for capture of the next Track to
start, while that next capture waits for the first analysis to start. The serial
implementation failed with “The next device input was not copied during current
analysis.” The queue passes without waiting for all captures before analysis.

The prior path performs two complete content hashes around decoding directly
from the iPod. The new path obtains the first hash during a verified Host capture,
decodes that copy and retains the final full device hash. One reader can capture
the current song and five upcoming songs, within 256 MiB of retained compressed
content. It never queues decoded PCM. Source checks and transaction preconditions
remain required. See [ADR-0227](../adr/0227-prefetch-bounded-phase-audio-inputs.md)
for resource bounds, serial fallbacks and lifecycle ownership.

## Measurement scope

The private harness and pre-change service snapshot are retained under
`.scratch/phase-prefetch/`. It uses the same eight full songs on the authorized
Active iPod at `D:\` as the previous report. The host is Windows with an
i9-13900KS and RTX 4070. It opens a real read-only Storage session and keeps Phase
index/cache changes in an in-memory test overlay; it does not publish to the iPod.

Baseline and candidate preparation are alternated, with a separate cache-hit
preparation after each. Timelines distinguish full source hashes, captures,
decoding, source analysis, acoustic analysis and chart encoding. The operating
system's file cache is not flushed, CPU/GPU clocks are uncontrolled, and existing
desktop/browser applications use the GPU. These measurements cannot establish
cold USB throughput or predict a speedup on other hardware.

Each uncached preparation starts a fresh managed model worker; parent imports were warmed
before timing. The timed candidate precedes the final adjustment to allow only
five waiting captures while an incoming Host Track is analyzed. These timed jobs
contain only device Tracks and consume the first capture immediately. A separate
current-code integration pass checks the final implementation; its elapsed time
is excluded because other validation ran concurrently.

## Timing results

Three alternating pairs analyze all eight songs, totaling 1,637.385 seconds of
music and 75,273,017 compressed source bytes per job. Times cover `prepare_phase`,
including reader/model lifetime, but exclude the separately traced subsequent
dependency recheck, publication and transaction verification.

| Pair | Baseline (seconds) | Prefetch (seconds) | Time reduction |
| --- | ---: | ---: | ---: |
| 1 | 126.120 | 117.014 | 7.2199% |
| 2 | 112.690 | 119.444 | −5.9928% |
| 3 | 111.280 | 109.209 | 1.8614% |
| Mean | 116.697 | 115.222 | 1.2636% |

The mean difference is 1.4746 seconds. These samples do not demonstrate a reliable
overall throughput improvement. The first baseline spends 5.0595 seconds on
preparation audio hashes; subsequent baselines spend 0.1153 and 0.1136 seconds.
The candidate's final hashes take about 0.057–0.059 seconds per job. Operating
system caching strongly affects the comparison, and background GPU load was
29–32% before measurement. No user process was stopped.

The eight candidate copy-and-hash operations total 0.1171, 0.1289 and 0.1325 seconds
per job, mostly overlapped with analysis. Total waits to receive captures are
12.9, 12.8 and 12.2 milliseconds, including the first capture. Gaps between
successive analysis calls total 4.774, 0.113 and 0.111 seconds in the baseline,
versus 0.076, 0.134 and 0.073 seconds with prefetch. Model analysis still occupies
roughly 59–69 seconds and acoustic chart generation 47–49 seconds per job.
Nested and overlapping stage times must not be added as independent costs.

| Logical operation per eight-song analysis job | Baseline | Prefetch |
| --- | ---: | ---: |
| Preparation full device fingerprints | 16 | 8 |
| Device-to-Host copies, including SHA-256 | 0 | 8 |
| Direct-device FFmpeg decodes | 8 | 0 |
| Host-file FFmpeg decodes | 0 | 8 |
| Later dependency fingerprints | 8 | 8 |

The later dependency check adds about 0.054–0.061 seconds outside these preparation
timings. These are logical read counts, not measured physical USB transfers.

Fully cached preparations do no decoding or analysis. Their baseline times are
0.1174, 0.1115 and 0.1582 seconds, versus 0.5550, 0.2846 and 0.2098 seconds with
prefetch. The means are 0.1290 and 0.3498 seconds: **0.2208 seconds more** across
eight songs. Those runs retain the same number of full device-content reads and
add 75,273,017 bytes of temporary Host writes. This is a measured cost of the
current cache-validation path.

## Original Phase output

The actual encrypted files from the prequeue baseline and final production pass
were consumed by the original build-3168002 ARM parser and chart converter at all
four difficulties. Thirty-two paired song/difficulty comparisons execute 64
conversions. All **25,958 complete callbacks match**, counting one side:

| Record kind | Identical records |
| --- | ---: |
| Taps | 10,176 |
| Annotations | 15,470 |
| Markers | 280 |
| Metadata | 32 |

The markers include 184 checkpoints. There are zero timing, lane, payload or
ordering changes. This runs original conversion code under emulation; rendering,
judging and physical gameplay are not exercised. The game image is the same
SHA-256 recorded in the previous experiment report.

All 56 chart bodies from six paired jobs and the final production job match.
Whole-file hashes differ because each newly authored file has a randomized RSA
OAEP envelope. Index bytes and analyzer/source provenance match, and each cache's
chart hash correctly refers to its own file. This supplemental file comparison
does not replace the original-game output check.

Raw records are in `paired-results.json`, `paired-events.json`, `summary.json`,
`native-outputs.json` and `native-summary.json` under the private experiment
directory. Sources were used read-only; no results were published to the iPod.

## Regression coverage

Focused checks cover overlap, first-song startup, Playlist order, exact analyzer
output, current-plus-five admission, aggregate byte backpressure, oversized-file
fallback, full-Host-disk/quota fallback during staging and copying, and propagation
of other errors. Cancellation, analysis failure, source changes, disconnection,
caller-thread callbacks and Host-only preparation are also covered. Fingerprint
cancellation tests preserve complete successful hashes and the original callback
exception on cancellation before, during and after a read.

Cleanup fault injection verifies that secondary deletion errors do not replace
the original cancellation or analysis failure, accounting is released, and the
reader joins before workspace teardown. A cleanup failure after otherwise
successful analysis still stops preparation. The final focused run passes all
59 relevant application and Storage tests, including raw and Storage-wrapped
capacity errors during workspace creation.

The prefetch-only full rerun passes **10,512 tests**, with 47 platform/private-data
skips and the existing large-photo warning. An initial run had one three-second
asynchronous picker timeout; the entire picker file then passed all 23 tests and
the full rerun passed with package jobs stopped. UV lock validation, Ruff, Mypy,
focused strict Pyright and Rumdl checks pass.

Source and wheel builds, wheel resource equality, Windows manifest/payload checks,
and the frozen acoustic/model runtime check pass. The unsigned MSIX also passes
integrity, identity, embedded build/license checks and its extracted executable's
smoke test. The prefetch-only artifact is
`dist/iOpenPod-2.1.0-Windows-x64-phase-prefetch-final-review.msix`, SHA-256
`ae8407f98fcae4b5dc136781e80dd13e53fdc260a6e992b2e7da1c6843319e32`.
Signed Store installation/certification and native macOS/Linux execution were not
performed here.
