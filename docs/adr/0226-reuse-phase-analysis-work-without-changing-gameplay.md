# ADR-0226: Reuse Phase analysis work without changing gameplay

- Status: Accepted
- Date: 2026-11-02
- Extends: ADR-0225

The user requested further performance experiments, evaluated through the
original Phase converter's output. Keep the version-7 gameplay mapping, model
weights, 344-frame source sections, 86-frame context and acoustic parameters.
Remove repeated feature work, overlap CUDA inference with the previous section's
CPU feature measurements, and retain the downloaded model for one preparation.
The [experiment report](../research/phase-speed-reuse-and-scheduling.md) records
timing scope, memory observations, original-game comparisons and limitations.

## Preparation lifetime

`ManagedPhaseSources.for_analysis()` creates a fresh owner of one lazy isolated
worker. `PhaseAnalysisService.for_analysis()` selects that owner for a preparation,
and `prepare_phase` closes it on every exit, including cache validation failures,
cancellation and device disconnection. A preparation that reuses every cached
chart starts no process. Standalone managed analysis still reaps its worker
after one request. Optional failure closes the worker before selecting acoustic
analysis for the rest of the preparation.

The retained worker receives sequential, size-bounded requests in a private Host
workspace. PCM and evidence use fixed local filenames; atomic request and response
publication and increasing integer sequence numbers prevent partial or stale
responses from being accepted. Validation retains ownership until all evidence
has been loaded. The worker receives no device path or Filesystem Session.

Storage's existing media-tool runner owns process execution, environment cleanup,
cancellation, diagnostics and reaping. Its optional stdin lifetime pipe remains
open without transmitting data. A nonblocking watcher terminates this private
worker on EOF without waiting for an analysis checkpoint if its parent crashes.
Other media tools keep
the existing closed-stdin behavior. Worker output is disposable Host data and
cannot commit device writes.

Each request has a one-hour deadline; the preparation process has a 24-hour
deadline. Stdout is bounded to 4 KiB and cumulative job diagnostics to 4 MiB.
These limits and protocol failures retain the measured acoustic fallback. The
existing single-request CLI and installation health protocol remain available.

## Bounded computation

Feature measurement computes only retained attack bands and reuses immutable
frequency/pitch masks and a single selected chroma power matrix. Dtypes, selected
row order, reductions and numerical thresholds remain unchanged.

CUDA analysis has one inference caller and at most one pending CPU feature block.
Only the caller publishes evidence or invokes application checkpoints. A failed
accelerator drains and discards pending work before restarting the complete Track
on CPU. Exceptions and cancellation join the feature worker. CPU and MPS retain
the serial path; acceleration failures still fall back as specified by ADR-0225.

The acoustic rolling-queue experiment remains outside the application defaults.
No dependency is added and no model download changes. The algorithm and cache
identity remain version 7 because the authored mapping and tested original-game
output are preserved. Native Windows packaging checks exercise standalone and
retained worker requests. Other platforms' native execution and physical iPod
gameplay remain separate acceptance tasks.
