# ADR-0228: Overlap Phase mix and source analysis

- Status: Accepted
- Date: 2026-11-02
- Extends: ADR-0226 and ADR-0227

Input prefetch overlaps input copies with analysis but does not fill the longer GPU gaps.
The measured workflow spends roughly 47–49 seconds per eight-song job on
whole-mix acoustic analysis after source analysis has finished. Those measurements
do not depend on the source Parts until the final chart-selection step.

## Decision

Separate whole-mix measurement from final combination with Phase Parts.
`measure_phase_mix` returns immutable compact evidence: beat/onset positions,
encoded beats, mix energy and spectral magnitudes. It retains no PCM or spectral
blocks. `finish_phase_analysis` validates Part alignment and applies the unchanged
chart selection. The existing `analyze_phase_pcm` interface performs both steps
for serial callers, including the existing silent/no-onset Parts-only behavior.

When a source provider reports CUDA capability, the Application Layer may run one
whole-mix measurement concurrently with source analysis of the same Track. Stereo
averaging and resampling complete before concurrency starts, limiting transient
conversion buffers. One background coordinator owns mix measurement and its two
existing DSP workers. Source analysis, source fallback/identity changes, application
checkpoints, final combination and encoding remain on the preparation caller.
There is no second decoded Track or additional model worker.

Overlap requires at least four available compute threads, respecting CPU affinity
where supported, and at most 256 MiB of decoded source PCM. The size limit bounds
the additional stereo-buffer lifetime; larger inputs use the serial path. For
the default 44.1 kHz stereo format this covers roughly 12 minutes 41 seconds.
CPU, MPS, unknown capability and smaller CPU allocations also remain serial.

## Live capability and failure behavior

Scheduling capability is distinct from cache identity. In-process Demucs reports
its selected backend. A managed runtime starts each preparation without overlap
capability. Only a successful live response with validated evidence can enable it,
so its first Track is serial. The existing protocol accepts an optional strictly
boolean `supports_mix_overlap` field; legacy responses mean false. Installation
receipts and opaque identity strings are not parsed as scheduling authority.

Backend selection can still change on the next Track or fall back during it.
A previously confirmed CUDA worker may therefore overlap CPU work for one Track
after an accelerator failure. Its returned false capability disables subsequent
overlap. Chart provenance continues to identify the backend that actually produced
the evidence. No runtime reinstall or new download is required.

The mix worker sees only a private stop signal, never the application callback.
The caller polls its completion/errors from source checkpoints and while waiting.
Mix failure remains a required-analysis error; it is not mistaken for an optional
model failure. Optional model failure can reuse the already-running mix work for
acoustic fallback. Cancellation or any other error signals stop and joins the
mix coordinator and its DSP workers before returning, preserving the primary
exception. A running native DSP operation may finish before observing stop.

All numerical operations, thresholds, sample rates, section sizes and musical
mapping remain unchanged. Algorithm/cache identity stays version 7. The
[measurement report](../research/phase-stage-overlap.md) records timing, memory,
original-game output comparisons and the limits of native validation.
