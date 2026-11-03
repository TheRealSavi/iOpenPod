# Phase whole-mix and source overlap

Date: 2026-11-02. This follows the
[input-prefetch experiment](phase-input-prefetch.md), which showed that device
reads were a small portion of warmed preparation time. Whole-mix acoustic work
still ran after source analysis, leaving the GPU unused by Phase during that
stage. This experiment overlaps those independent measurements for the same Track
and combines their evidence afterward.

The numerical algorithm remains unchanged. See
[ADR-0228](../adr/0228-overlap-phase-mix-and-source-analysis.md) for eligibility,
resource bounds, live capability, fallback and cleanup.

## Reproduction and scope

A deterministic service regression makes source analysis wait for whole-mix
measurement to start. It failed before the change because no mix worker started
until the source provider returned, then passed after integration. Further checks
cover application callbacks staying on the caller, immutable evidence, silence,
Part alignment, error precedence, cancellation/join, CPU/size/capability gates and
stereo conversion before concurrency.

Private scripts and source snapshots are under `.scratch/phase-stage-overlap/`.
The corpus is the same eight full songs, 27.29 minutes, from the authorized iPod
used in the previous reports. Local-PCM jobs replace only FFmpeg decoding with
previously verified stereo PCM. Both variants use the production managed runtime,
fresh preparation/model ownership, identical inputs and unchanged source analysis.
A separate read-only `D:\` preparation pair exercises configured media tools,
input prefetch and the full application path. No device publication occurs.

The host is Windows, i9-13900KS and RTX 4070. Existing desktop/browser GPU activity
and CPU/GPU clocks are uncontrolled; no user applications are stopped. Jobs run
serially in alternating baseline/candidate order. Timing comparisons are scoped
to this corpus and host, not a cross-platform performance guarantee.

The initial memory sampler saw the Windows venv launcher rather than its
interpreter grandchild. Timing and output checks remain valid, but the first two
local pairs have incomplete combined RSS/child CPU data and are excluded from
those comparisons. Corrected samples discover the complete owned process tree
and sum parent/worker RSS every 100 ms. Sampled RSS includes shared resident pages
and is neither a hard peak nor total system/GPU memory.

## Local timing results

Each job analyzes all eight songs, with the model retained within that job. Parent
imports are warmed; the first Track includes child startup/model loading. In every
candidate job, the first Track is serial and the remaining seven take the live
CUDA overlap path.

Local elapsed figures sum the eight `analyze()` calls. They exclude PCM file
reading/hashing, chart-file writes and final worker shutdown. The process CPU/RSS
sampler spans those surrounding operations too; its scope is broader than the
elapsed column.

| Pair | Serial (seconds) | Overlap (seconds) | Time reduction |
| --- | ---: | ---: | ---: |
| 1 | 103.124 | 64.973 | 36.9951% |
| 2 | 94.300 | 65.434 | 30.6112% |
| 3 | 94.298 | 65.479 | 30.5616% |
| Mean | 97.241 | 65.295 | 32.8519% |

The first baseline's first Track takes 20.792 seconds, compared with 12.177 and
12.254 seconds in later baseline jobs. That startup difference affects the pooled
mean. The latter two pairs still show reductions of 30.61% and 30.56%. These are
descriptive samples, not a confidence interval or a guaranteed speedup.

In the final local pair, source work takes about 6.3% longer and total mix/fusion
work about 20.9% longer under overlap, while wall time falls 30.56%. Parent process
CPU time increases from 91.875 to 148.359 core-seconds; child CPU time increases
from 1,025.516 to 1,060.438 core-seconds. The change overlaps work rather than
reducing the signal-processing calculations. Nested and overlapping stage totals
must not be added as separate wall-clock costs.

## Full preparation from the iPod

One baseline/candidate pair uses the real read-only `D:\` session, the configured
FFmpeg selection, and the same current compressed-input queue in both variants.
The parent process is shared across this pair. Preparation time includes all
eight decodes and analyses; the later dependency recheck and device publication
are outside the measurement.

| Measurement | Serial | Overlap |
| --- | ---: | ---: |
| Preparation | 96.488 s | 67.884 s |
| Fully cached preparation | 0.230 s | 0.224 s |
| Sampled summed process RSS peak | 2,499,305,472 bytes | 2,561,826,816 bytes |
| Parent CPU time | 91.516 core-seconds | 163.984 core-seconds |
| Child CPU time | 1,016.359 core-seconds | 1,075.797 core-seconds |

This pair reduces preparation time by **28.604 seconds (29.6452%)**. The sampled
RSS increase is 62,521,344 bytes, about 62.5 MB. The corrected local pair instead
samples 2,380,308,480 versus 2,317,365,248 bytes; allocator and sampling differences
mean neither result establishes a universal memory increase or decrease.

Both variants perform eight copy/hash captures, eight final preparation source
hashes and eight later dependency hashes. The baseline encounters colder input
reads: its captures total 4.996 seconds versus 0.123 seconds for the candidate.
Prefetch overlaps most of that work already; waits to receive captures total
0.305 versus 0.014 seconds. This remaining cache-order effect is part of the
observed integration result, not proof of a particular USB link speed.

The later dependency rechecks take about 0.056 seconds for either variant. Fully
cached preparation does no model or mix work and shows no meaningful scheduling
gain in this single pair. Source metadata remains unchanged and there are zero
device publications.

## Original Phase output

Actual returned encrypted files from the full preparation pair were consumed by
the original build-3168002 ARM parser and chart converter. Eight songs at all four
difficulty indices give 32 paired comparisons and 64 conversions. All **25,958
complete callbacks match**, counting one side of each comparison:

| Record kind | Identical records |
| --- | ---: |
| Taps | 10,176 |
| Annotations | 15,470 |
| Markers | 280 |
| Metadata | 32 |

Markers include 184 checkpoints. Tap counts by difficulty index 0–3 are 1,510,
1,924, 2,956 and 3,786. Missing/extra records, timestamp changes, lane changes,
payload changes and ordering changes are all zero. Original conversion code runs
under emulation with research adapters; rendering, judging and physical iPod
gameplay are outside this check. The image SHA-256 is
`35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258`.

All 56 supplemental body comparisons against the full baseline also match: 48
local-run files plus eight integrated candidate files. These are repeated outputs
for the same eight songs, not additional independent musical samples. Whole-file
hashes differ because newly authored files use randomized RSA OAEP envelopes.
The Phase Library index and cache provenance match, and each cache hash correctly
identifies its own complete file. These checks supplement the game-output test.

Raw results are retained in `local-summary.json`, `device-summary.json` and
`native-summary.json`, with individual timestamps, process samples and complete
native callbacks alongside them in the private experiment directory.

## Implementation validation

The full suite passes **10,551 tests**, with 47 skips for platform-specific
semantics or unavailable private captures and the existing large-photo warning.
UV lock validation, Ruff formatting/lint, Mypy, focused strict Pyright and Rumdl
checks pass. Independent review found no remaining scheduling or lifecycle issue.

Focused regressions cover the serial/split measurement contract, read-only reusable
evidence, silence and Part alignment, live CUDA capability and CPU fallback,
malformed/legacy worker metadata, actual overlap, caller-thread callbacks,
stereo conversion order, CPU/PCM limits, optional-model failure, mandatory mix
failure, cancellation and joined cleanup. Algorithm/cache version remains 7.

Source/wheel builds and wheel resource equality pass. The rebuilt Windows
executable passes manifest/payload inspection and its frozen acoustic runtime
check plus standalone and retained downloaded-worker requests. The unsigned MSIX
passes integrity, identity, embedded build/license checks and the extracted
executable's smoke test. The artifact is
`dist/iOpenPod-2.1.0-Windows-x64-phase-stage-overlap-review.msix`, SHA-256
`dd5b5f2169348410651c393d645702b233c9a9ff5713960a9f15a19de243455b`.
Signed Store installation/certification and native macOS/Linux execution were not
performed in this experiment.
