# ADR-0221: Preserve Phase spectral lane evidence

- Status: Accepted
- Date: 2026-10-31
- Supersedes: ADR-0217's encoded magnitude measurement and per-band calibration

Native Phase uses the sum of three attack fields for stock selection priority,
and their ordering for primary and alternative lanes. Independent band gains
can invert that ordering; independent clipping can flatten it into deterministic
ties. Detection novelty and encoded magnitude therefore become separate evidence.
We retain normalized log-mel detection and recurring Phase Hook recognition,
but measure linear spectral increases in the shipped 80–300, 400–1500 and
2000–4500 Hz regions for encoding. Mix and source measurements share units.

One mix-derived amplitude scale applies to all bands and sources. Compression
and saturation apply to the whole attack vector, preserving its ratios until
five-bit rounding. Quiet sources cannot become loud merely by having their own
normalizer. Full-mix attacks, modest foreground preference, native difficulty
ownership, whole-mix beat power, and the upper beat field's compatibility mapping
remain. The upper field is unused for gameplay in the audited build 3168002;
it is not a density control.

This adds compact magnitude arrays, without additional dependencies or waveform
retention. The shipped ranges and native consumers are evidence; the spectral
increase measurement and quantizer remain iOpenPod policy, not recovered iTunes
code. `librosa-phase-6` invalidates older analysis provenance on ordinary Save or
Sync. Device selection continues to defer analysis under ADR-0216. See
[parameter evidence](../research/phase-parameter-semantics.md) and
[version-6 evaluation](../research/phase-algorithm-v6.md).
