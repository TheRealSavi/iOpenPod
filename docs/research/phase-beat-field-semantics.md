# Phase beat-field semantics

Research date: 2026-10-31. Scope: Phase build 3168002, image SHA-256
`35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258`.
This investigation reads the native code and bundled assets and executes the
original ARM conversion. It does not run live rendering or judging, recreate the
iTunes producer, modify the game, or write an iPod.

## Findings

| Encoded field | Confirmed native role | Appropriate interpretation |
| --- | --- | --- |
| Beat timestamp | Locates beats, intervals, sections, candidate alignment, and output beat cues | Pulse timing |
| High nibble, currently `strength` | Decoded and retained; no reads observed during normal conversion; an optional diagnostic path reads it into a dead stack store | Unresolved producer measurement; not a demonstrated chart-density control |
| Low nibble, currently `accent` | Supplies native beat-power smoothing and relative section classification | Beat-associated power; the name `accent` understates and potentially misdescribes its confirmed role |

The follow-up audit supports treating the high nibble as **unused for gameplay
generation in this inspected retail build**, while preserving it as an unresolved
producer field. Its only identified diagnostic read has no observable consumer.
This is a bounded reverse-engineering conclusion about build 3168002, not a claim
about every Phase executable or the original iTunes analysis tool.

The existing low-field mapping to whole-mix energy is consistent with its native
consumer. Its precise producer formula, frequency weighting, amplitude-versus-
power convention, and normalization remain unproved. The high field should not
be advertised as a verified musical accent, confidence, or onset-strength input.

## Exact decoding and low-field consumer

The parser at `0x18009DC4` expands the high nibble as `high << 12` into the
decoded beat record at `+4`; it expands the low nibble as
`((low << 11) * 19660) >> 15` into `+8`. These are separate values, with different
fixed-point scaling. The first word is the time in milliseconds. See the
[parser export](../../.scratch/phase-windows/density-research/export1/18009dc4.c),
lines 80–87.

The analyzer at `0x18061FC8` explicitly copies beat `+8` into its power series
(line 41). It reads configuration strings including `ave_power_smoothing_range`,
`max_power_smoothing_range`, and `max_power_from_averages`, squares values and
takes a square root when computing the smoothed average (lines 119–131), then
compares against a threshold (lines 173–177).
[Native analyzer](../../.scratch/phase-windows/density-research/export2/18061fc8.c).

The threshold function `0x18062F90` sorts smoothed powers and computes an average
after applying `beat_power_split_clip_low` and `beat_power_split_clip_high`.
`0x18062A08` forms sections, optionally merges short sections using
`beat_power_split_min_duration`, and combines adjacent sections of the same
class. This is evidence for relative passage power, not an absolute "more notes"
knob. [Threshold](../../.scratch/phase-windows/density-research/export2/18062f90.c),
[section construction](../../.scratch/phase-windows/density-research/export2/18062a08.c).

## High-field tests

A memory-read watch was installed on the decoded beat array immediately before
the native beat-analyzer constructor, after parsing and before power analysis.
It remained active through the rest of converter construction, checkpoint creation,
selection, sweep and lane transformations, tap/annotation output, and markers.
The two fixtures were version-5 Poppies (400 beat records) and ocean eyes (138).

Neither run read decoded beat `+4`. The direct power-series read at PC
`0x18062014` read `+8` exactly once per beat. Other observed accesses included
beat timestamps and additional low-field reads. The receipt retains every
observed PC, field offset, access size, and count.
[Watch script](../../.scratch/phase-parameters-beat/trace_reads.py),
[read trace](../../.scratch/phase-parameters-beat/beat-read-trace.json).

A second experiment ran both fixtures at all four native difficulty indices,
changing only the encoded high nibble: original values, all zero, all fifteen,
`15 - original`, and a repeating 0–15 ramp. All five variants had identical full
sink output, phrase-selection summaries, and selected counts for each
track/difficulty combination: **40 conversions, 32 counterfactual comparisons**.
The exact comparison includes tap payloads, sweep/beat annotation payloads,
marker strings, callback order, and times, not just tap totals.
[Perturbation script](../../.scratch/phase-parameters-beat/perturb_high.py),
[results and output hashes](../../.scratch/phase-parameters-beat/high-field-perturbations.json).

These stages correspond to the game's loader state machine: `0x18068C0C` creates
the converter in state 3 and invokes the tested conversion functions in states
6 through 11. It then finalizes track storage in state 12. Native output emits
beat annotations using timestamps and constructed durations, with no observed
high-nibble propagation. [Loader](../../.scratch/phase-windows/density-research/export3/18068c0c.c),
lines 77–95 and 145–166;
[output](../../.scratch/phase-windows/density-research/export7/18056720.c).

The initial conclusion is **unused in these measured normal conversion paths**.
The follow-up below investigates retained-object ownership and the diagnostic
branch rather than treating those runs as a whole-program proof.

## Follow-up: ownership, teardown, and diagnostic reads

The read-only export covers all 3,680 functions identified in the Ghidra project,
with no decompilation failures. This is coverage of identified functions, not a
proof that every possible indirect target has been recovered.
[Static inventory](../../.scratch/phase-unused-audit/static-inventory.json).
The export gives the following ownership chain:

| Object or reference | Owner / creation | Destruction |
| --- | --- | --- |
| Converter | Loader `0x18068C0C` stores it at game-state `+0x1780` | Teardown `0x18068A5C` calls `0x18057228`, frees it, and clears that slot |
| Parsed PHZ | Converter constructor stores it at converter `+0x8C` | Converter destructor calls `0x1802AAC0`, then frees the object |
| Beat analyzer | Converter owns it at `+0x90`; analyzer borrows the parsed PHZ at `+0x20` | Converter destructor calls `0x18063338`, then frees the analyzer |
| Beat array | Parsed PHZ owns it at `+0x0C` | Parsed-object destructor frees the array directly |

Primary evidence: [loader](../../.scratch/phase-unused-audit/all/18068c0c.c),
[teardown assembly](../../.scratch/phase-unused-audit/all/18068a5c.asm.txt),
[converter destructor assembly](../../.scratch/phase-unused-audit/all/18057228.asm.txt),
[parsed destructor assembly](../../.scratch/phase-unused-audit/all/1802aac0.asm.txt),
[analyzer constructor](../../.scratch/phase-unused-audit/all/180632a8.c), and
[analyzer destructor](../../.scratch/phase-unused-audit/all/18063338.c).
The exported cross-references identify a single parser caller (the converter
constructor), a single converter-constructor caller (the loader), and a single
converter-destructor caller (the teardown).
[Reference inventory](../../.scratch/phase-unused-audit/all/references.tsv).

`0x1807170C` builds per-transient beat classifications from the parsed data and
analyzer. Its retained records contain a beat index, interval classification, and
section flag; this path does not retain the raw parsed or beat-array pointers.
[Classification builder](../../.scratch/phase-unused-audit/all/1807170c.c).

A native lifetime probe corroborates those owners after full conversion on both
fixtures. Scanning guest memory `0x02000000..0x02300000` and the mapped image
`0x18000000..0x18200000` finds exactly:

- Parsed-object pointer: converter `+0x8C` and analyzer `+0x20`.
- Beat-array pointer: parsed object `+0x0C` only.
- Analyzer pointer: converter `+0x90` only.
- No interior beat-array pointers in those scanned ranges.

The stack at `0x023F0000` is deliberately excluded because it contains obsolete
call arguments. These are searches for pointer-valued words, not a typed pointer
proof. Executing the native converter destructor then requests deallocation of
the transient array, beat array, parsed object, and analyzer without reading any
beat record. Free adapters record the requested addresses and do not model host
heap reuse. [Lifetime probe](../../.scratch/phase-parameters-beat/lifetime.py),
[pointer and free receipt](../../.scratch/phase-parameters-beat/lifetime.json).

There **is** a static high-field read that the initial normal-path watch did not
exercise. When `beats_report` is enabled, `0x180778F4` reads beat `+4` at
`0x18077A40` and writes it to `[SP+4]` at `0x18077A44`. It immediately reads beat
`+8` and overwrites the same stack slot at `0x18077A50`. No instruction reads the
first stack value in between. Ghidra's decompiled C removes these dead stores and
shows an empty reporting loop; the original assembly is necessary to see them.
[Diagnostic assembly](../../.scratch/phase-unused-audit/all/180778f4.asm.txt).

This prevents the literal claim that the high field is "never read." The observed
diagnostic stack store does not produce a gameplay value. The final high value
also remains briefly in caller-saved register R2, but its return path is closed:
the converter calls symbol interning for the nonempty literal `beatmatcher`.
With an existing intern table, the hash helper calls integer division, which
initializes R2 at `0x180026EC` before using it. With an empty table, the string
insertion path sets R2 from string length at `0x1802DCF8`. The intern-function
epilogue at `0x18049C14` also restores R2 from its own saved incoming R0, not from
the diagnostic value. The high value therefore does not become a later hidden
argument. [Constructor continuation](../../.scratch/phase-unused-audit/all/18056fb8.asm.txt),
[interning](../../.scratch/phase-unused-audit/all/18049b48.asm.txt),
[hash helper](../../.scratch/phase-unused-audit/all/180084ac.asm.txt),
[division](../../.scratch/phase-unused-audit/all/180026e0.asm.txt),
[string insertion](../../.scratch/phase-unused-audit/all/1802dce4.asm.txt).

The native watch was then moved earlier, to the first instruction after the
parser returns, covering the reporter as well as all later conversion. Seven
original bundled inputs were tested on Hard; `fff` was additionally tested at the
other three difficulty indices. Each case ran with reporting disabled/enabled
and high field zero/fifteen: **40 additional conversions**. All four variants
produce identical complete output for each input/difficulty. With reporting off,
there are zero high-field reads; with reporting on, the only high-field read is
`0x18077A40`, exactly once per beat. This independently confirms the diagnostic
read is executed and that the initial watch was not silently skipping an active
gameplay consumer. [Earlier watch](../../.scratch/phase-unused-audit/watch_early.py),
[receipt](../../.scratch/phase-unused-audit/early-watch.json).

Four authored cases with one, two, three, or irregularly spaced beats add
**16 conversions** on Hard, again crossing reporting disabled/enabled with high
field zero/fifteen. All four variants of each case produce identical full output;
the only upper-field reads are the diagnostic reads when reporting is enabled.
Together with the initial 40 runs, this makes 96 complete conversions across the
two investigations. [Edge-case probe](../../.scratch/phase-unused-audit/watch_edge_cases.py),
[receipt](../../.scratch/phase-unused-audit/edge-watch.json).

The ownership audit finds no retained raw-beat pointer handed to track-output
storage and no identified live-rendering use. The diagnostic path is a dead
read/store, the gameplay path does not consume the value, and teardown frees its
array without inspecting elements. These observations justify calling the field
unused for gameplay in the audited build. They do not assign a historical
producer meaning to it or prove that another build or development analyzer uses
it identically. The high field should be preserved for format compatibility,
without claiming that its values improve chart selection.

## Original bundled files

The high nibble is not just zero padding in shipped producer data. Every one of
the seven bundled charts contains all values 1 through 15 and no zeros. Low
nibbles vary separately and can be zero. High/low Pearson correlations are only
0.105–0.496, so the two fields cannot be treated as interchangeable encodings of
one measurement. This describes the bundled charts; it does not establish the
distribution of arbitrary iTunes-generated charts.

| Bundled chart | Beat count | High values | Low values | High/low correlation |
| --- | ---: | --- | --- | ---: |
| aaa | 514 | 1–15 | 0–7 | 0.270 |
| bbb | 485 | 1–15 | 0–8 | 0.460 |
| ccc | 521 | 1–15 | 0–13 | 0.247 |
| ddd | 532 | 1–15 | 0–10 | 0.477 |
| eee | 547 | 1–15 | 0–15 | 0.322 |
| fff | 258 | 1–15 | 0–9 | 0.496 |
| ggg | 375 | 1–15 | 0–15 | 0.105 |

The script parses the preserved decrypted bundled payloads without rewriting
them. Per-file SHA-256 identities and complete histograms are in the receipt.
[Extraction](../../.scratch/phase-parameters-beat/bundled_fields.py),
[bundled distributions](../../.scratch/phase-parameters-beat/bundled-fields.json).

## Producer-intent clues and limits

The bundled `conv_phase.json` contains an `analysis` section with
`beats_env_thresh_db = -6`, `beats_res_pole_magnitude = 0.996490478515625`, and
`generateBeatCues = 1`, alongside separate tempo, time-grid, transient, and
frequency-analysis controls. This suggests a beat extractor with its own envelope
and resonator processing, rather than simply storing the instantaneous transient
envelope. However, no traced producer code connects those controls to either
nibble. They may be retained development configuration. Assigning the high nibble
to resonator confidence, or claiming that the low nibble is exactly RMS, would
go beyond this evidence.
[Bundled analysis configuration](../../../ipod-firmware-lab/artifacts/phase-assets/config/gen/conv_phase.json),
lines 405–517.

Practical implication: prioritize faithful beat timing and a meaningful relative
power contour. Preserve the high field in the format, but do not tune it expecting
denser taps based on the current evidence. Further identification needs producer
code or original charts paired with their exact audio and controlled signal
comparisons. No production mapping was changed by this investigation.

## Reproduction

From the iOpenPod root, using the private local game assets and existing harness:

```powershell
uv run --with unicorn==2.1.4 python .scratch/phase-parameters-beat/trace_reads.py
uv run --with unicorn==2.1.4 python .scratch/phase-parameters-beat/perturb_high.py
uv run python .scratch/phase-parameters-beat/bundled_fields.py
uv run --with unicorn==2.1.4 python .scratch/phase-unused-audit/watch_early.py
uv run --with unicorn==2.1.4 python .scratch/phase-unused-audit/watch_edge_cases.py
uv run --with unicorn==2.1.4 python .scratch/phase-parameters-beat/lifetime.py
uv run python .scratch/phase-unused-audit/audit_inventory.py
```

The harness uses explicit allocation, crypto, symbol, and output-storage adapters,
as described in the [native conversion research](phase-windows-recomp-feasibility.md).
