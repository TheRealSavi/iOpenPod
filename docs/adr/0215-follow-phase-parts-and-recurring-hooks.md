# ADR-0215: Follow Phase Parts and recurring Hooks

- Status: Accepted
- Date: 2026-10-30
- Extends: ADR-0214
- Selection and magnitude policy superseded by: [ADR-0217](0217-preserve-phase-evidence-for-native-difficulty.md)
- Vocal/guitar preference superseded by: [ADR-0222](0222-anchor-phase-attacks-to-percussion.md)
- Provider failure policy superseded by: [ADR-0225](0225-install-optional-phase-analysis-with-safe-fallbacks.md)

Phase uses the existing optional Demucs/PyTorch stack to estimate vocals, guitar,
bass, drums, piano, and other sources. The pinned six-source checkpoint signature
`5c90dfd2` supplies explicit guitar evidence; the four-source model's `other`
output cannot justify that label. The model's estimates remain fallible.

The default application composition decodes stereo 44,100 Hz PCM when the provider
is available. Four-second cores with one-second context keep separated waveforms
and spectral intermediates bounded. Only compact Phase Part evidence survives
each block. No separated audio is persisted. Model weights use the provider's
Host cache and hash validation. Inference uses zero random shifts and checks
cancellation between blocks; an in-flight model load or inference must finish
before it can stop. GPU is preferred when available, otherwise CPU is supported.

Recurring six-note pitch/rhythm sequences become Phase Hooks. Matching tolerates
moderate tempo variation, rejects changed pitch ordering and steady single-pitch
pulses, and retains each occurrence's own attack times. Source selection balances
audibility, attack clarity, recurrence, continuity, and a modest vocal/guitar
preference. Another part can answer pauses. Final difficulty and lane behavior
remain owned by the native game.

Without the optional stack, Phase uses ADR-0214's acoustic analysis. Once a source
provider is selected, its errors stop preparation; an acoustic fallback must not
be cached under a successful model identity. Chart provenance now includes the
algorithm, model signature, provider/runtime versions, inference backend, and PCM
format. Installing the provider or changing that identity regenerates old charts.

This adds model cost and a first-use download while keeping the base application
dependency set unchanged. The existing `synesthesia-gpu` extra supplies the stack;
Phase does not depend on Synesthesia's controller or analysis implementation.
Synthetic tests cover source handoffs, hook recognition, leakage rejection, and
cache invalidation. Repeated real-model analysis and native parser acceptance
are recorded in [Phase audio analysis](../phase-audio-analysis.md). They do not
establish source separation accuracy against ground truth or physical play feel.

## 2026-10-31 correction: preserve supporting attacks

The original pause-only support rule can starve native difficulty selection:
an authored sustained vocal over active accompaniment reduced 64 candidates to
eight. Version 4 preserves eligible audible supporting attacks under held leads,
using 60% magnitudes and lead priority for the existing 120 ms collision gate.
Source/hook scoring still chooses the lead; final difficulty stays with Phase.
No support event is synthesized or shifted. The algorithm identity invalidates
older chart provenance on the next ordinary save.

This repairs the demonstrated suppression, without claiming the reported song
is solved. Native phrase selection on the local *Poppies* recording changes only
377 to 378 despite 570 to 705 input candidates. The
[native research](../research/phase-windows-recomp-feasibility.md) distinguishes
this evidence from complete gem conversion and physical gameplay acceptance.
