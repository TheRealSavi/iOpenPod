# Acoustic Phase parameter audit

Date: 2026-11-02. Algorithm: `librosa-phase-7`, with no source-separation model.
Native target: Phase build 3168002, image SHA-256
`35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258`.

## Scope and result

The acoustic path already follows the confirmed native parameter roles. This
audit found no parameter-mapping defect and does not change musical policy or
invalidate existing charts. It adds executable fallback/wire-format regressions
and clarifies the legacy `PhaseBeat` field names in the codec.

This does not establish a complete reconstruction of Apple's analysis producer.
Its original filters, quantizer, beat-grid conventions, and upper beat field's
musical meaning remain unresolved. The native consumer roles below are supported
by the existing [parameter investigation](phase-parameter-semantics.md) and
[beat-field audit](phase-beat-field-semantics.md).

| Evidence | Acoustic implementation | Confirmed native role |
| --- | --- | --- |
| Attack times | Measured musical attacks encoded in Q16.16 seconds; no snapping to inferred beats | Candidate timing |
| Three attack magnitudes | Linear spectral increases in 80–300, 400–1500 and 2000–4500 Hz; one shared scale and ratio-preserving quantization | Combined stock selection score; ordering seeds primary and alternative lanes |
| Beat times | Independently tracked musical pulse | Phrase grouping, beat alignment, amplification and cues |
| Low beat nibble (`accent`) | Smoothed whole-mix energy with a shared relative scale | Relative section power and difficulty-dependent selection/spacing |
| High beat nibble (`strength`) | Retained compatibility mapping from onset evidence | Unused for gameplay generation in the audited build; producer meaning unknown |

Detection novelty remains separate from encoded spectral magnitude. Neither
independent band normalization nor instrument labels determine lane strength.
Both the direct acoustic path and optional-provider fallback call the same DSP
and codec; the fallback is not a regular or placeholder chart.

## Native counterfactual checks

A deterministic authored 30-second fixture combines a constant 440 Hz tone with
quiet then louder percussion. Its float32 mono PCM SHA-256 is
`68843a6d800e72c3032d135ad558d9abca36827056b2cd2f93bf3bf116671f90`.
The analyzer produced **79 attack records and 60 beat records**. All variants were
encoded with the application's PHZ codec, then parsed and converted by the
unchanged original ARM game code in the existing bounded research harness.
No device, original recording, game code, or configuration was modified.

Six variants at each of four difficulty indices give **24 complete conversions**:

| Variant | Observation at all four difficulties |
| --- | --- |
| Unchanged acoustic output | Accepted; emitted taps at every difficulty |
| Upper beat nibble all zero | Identical complete output to the unchanged chart |
| Upper beat nibble all fifteen | Identical complete output to the unchanged chart |
| Rotate low/mid/high attack fields, retaining their sum | Tap times/counts unchanged; lane sequences changed |
| Set lower beat nibble to eight throughout | Complete output changed; tap counts changed at difficulty indices 0 and 1 |
| Move pulse records 125 ms later, keeping attack times unchanged | Complete output and tap times changed |

Complete-output comparisons include callback order, tap/annotation payloads,
markers, selected counts and phrase summaries; they are not just count checks.

| Native difficulty index | Acoustic taps | Flat lower-field power taps | Shifted-pulse taps |
| ---: | ---: | ---: | ---: |
| 0 | 31 | 24 | 31 |
| 1 | 41 | 35 | 40 |
| 2 | 48 | 48 | 48 |
| 3 | 48 | 48 | 48 |

At indices 2 and 3, flattened lower-field power still changes complete output
despite unchanged tap counts. These results reinforce that the low field is
relative section evidence, not a universal monotonic note-count control. The
unused upper field is not a replacement for either pulse timing or section power.

## Regression coverage and limits

An optional-provider failure now has a regression using real authored PCM and
the complete acoustic DSP. An independently decrypted test-key envelope must
contain exactly the reference acoustic attack times, all three spectral fields,
beat times, upper nibbles and lower nibbles. This catches placeholder substitution,
lost spectral information, swapped beat fields, or altered timing in fallback.
Another signal test checks that reducing the audible recording by a uniform
factor of four leaves the relative chart unchanged. Existing tests cover band
gaps, ordering under saturation, dynamics, percussion timing, silence, tempo
changes, cancellation and codec bounds.

Reproduction uses the existing private lab image and harness:

```powershell
uv run --with unicorn==2.1.4 python .scratch/phase-acoustic-audit/audit.py
uv run pytest tests/iOpenPod/app/test_phase_audio.py tests/iOpenPod/app/test_phase_evidence.py tests/iOpenPod/app/test_phase_spectral.py tests/iOpenPod/app/test_phase_fallback.py tests/iPodDB/games/test_phase.py
```

The private script and full native receipts remain under
`.scratch/phase-acoustic-audit/`. Unicorn is a research-only runner, not an
application dependency. This confirms field use in the inspected converter;
physical gameplay, perceived musical quality and other game builds remain
separate acceptance work.
