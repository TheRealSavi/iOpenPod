# Phase algorithm version 5 evaluation

Date: 2026-10-31. Decision: [ADR-0217](../adr/0217-preserve-phase-evidence-for-native-difficulty.md).

## Method and scope

Read-only local recordings were decoded and separated once, retaining private
mono PCM and compact source evidence for controlled comparisons. Source identity
was `demucs-4.1.0-5c90dfd2-torch-2.14.0+cu130-cuda-shifts0`. Version-4 charts were
captured before editing the analyzer. Subsequent variants used the same decoded
audio and source features. No audio, stems, game executable, or complete chart
sequences are committed. No physical iPod was written during these experiments.

The unchanged build-3168002 ARM constructor and conversion stages execute with
the game's configuration, through tap/lane/sweep output. Runtime allocation,
crypto, symbol interning, and final storage callbacks use the bounded adapters
documented in the [native harness research](phase-windows-recomp-feasibility.md).
Hard is difficulty index 2. No game difficulty constants were changed.

Game image SHA-256:
`35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258`.
Configuration SHA-256:
`f2b1e7514b5f19b7fefd45ebf4cd9b4a3186e6af6d6d5dde412c7a790e4d399d`.
Windows probe SHA-256:
`6699a6cf328be3975ad2cb51bd085ca38767d54cb2285e45206431781c76ec63`.

## Iterations

1. A failing regression showed that adding an empty vocal estimate erased every
   full-mix attack. Retaining both acoustic families, reducing detection wait to
   about 60 ms, and calibrating source strengths against the mix fixed it. Poppies
   rose from 284 to 293 native Hard taps; 505 changed from 159 to 158. More input
   events alone did not establish success.
2. A constant-harmony fixture with much louder percussion still encoded the same
   beat-power value in both halves. Using full-mix RMS smoothed over about 250 ms
   fixed this regression. Poppies reached 316 taps, and native normal-energy
   phrase duration increased from about 54 to 104 seconds. This is an energy
   interpretation, not a rule forcing all passages into normal classification.
3. The old held-tone gate removed all eight isolated accompaniment attacks under
   a sustained melody in an authored test. Removing that gate alone failed the
   vibrato regression. Checking whether percussion itself falls below 5% of mix
   RMS instead preserved those drums and continued rejecting held-tone vibrato.
4. A neutral source-preference ablation and 15%, 35%, and 60% stem-only boosts
   showed that a stronger mix often masked the preference entirely. Higher boosts
   did not give consistent improvements across fixtures. The final 15% preference
   applies once to the shared attack when an eligible foreground source supports
   it. A regression verifies this behavior even when its stem is weaker than the
   mix. The native game remains free to select other candidates.
5. The final codec-capacity guard uses time-distributed buckets. A 30-minute
   authored case exceeding 20,000 attacks retains over 9,000 events from its
   quieter first half, while staying within the codec limit and preserving actual
   timestamps. A global strongest-event truncation would not guarantee this.

## Final native Hard output

Counts below use source-assisted analysis. The other recordings are 90-second
clips; Poppies is the complete 169.733-second recording. 505 starts at 120 seconds;
the remaining clips start at zero.

| Recording | v4 candidates | v5 candidates | v4 selected after checkpoints | v5 selected after checkpoints | v4 taps | v5 taps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Marcy Playground — Poppies | 705 | 1252 | 378 | 409 | 284 | 315 |
| Arctic Monkeys — 505 | 423 | 697 | 196 | 202 | 159 | 168 |
| Coldplay — Clocks | 404 | 686 | 243 | 248 | 202 | 202 |
| Chevelle — The Red | 346 | 630 | 173 | 190 | 133 | 147 |
| Billie Eilish — ocean eyes | 288 | 473 | 163 | 184 | 132 | 145 |

Final acoustic-only Hard tap counts are 315, 166, 202, 138, and 123 respectively.
All ten final charts complete all four native difficulty indices. On Hard, the
Windows translation matches ARM exactly for tap payloads, annotation payloads,
callback order, and marker strings. Rendering, audio synchronization, and judging
are outside this harness.

Tap-only gaps are not empty-gameplay measurements. For example, The Red's longest
final tap gap spans a checkpoint followed by native sweep annotations. The
preceding variant's Poppies gap similarly includes a checkpoint at 35.299 seconds
and a sweep interval beginning at 39.346 seconds. Sweep output must be inspected
alongside taps before treating a gap as starvation.

Foreground coverage is only a diagnostic, measured within 60 ms of the analyzer's
own inferred source attacks. Relative to neutral preference, the final policy
changes Poppies matches from 291 to 293 and ocean eyes from 55 to 56, with the
other three unchanged. It does not establish correct instrument identification.
Compared with v4, Poppies' inferred hook matches decrease from 210 to 206 even as
total foreground matches increase. The Red and ocean eyes also do not improve on
every coverage measure. These results justify retaining complete evidence and
modest preferences, not claiming accurate instrument transcription or universally
better play feel. Listening and physical play remain required for that claim.

## Reproduction receipts

Private scripts and results are in `.scratch/phase-v5/`: `prepare_corpus.py`
captures the v4 baseline (do not rerun against a newer analyzer), `generate.py`
generates named variants, `preferences.py` performs preference ablations,
`evaluate.py` runs native conversion and optional Windows comparison, and
`compare.py` reports inferred foreground/hook coverage. `manifest.json` stores
clip offsets and provider identity; JSON receipts retain the complete sink output.
These scripts depend on local game artifacts and are not application dependencies.

Example final verification, using the retained `preference5` fixture name:

```powershell
uv run --with unicorn==2.1.4 python .scratch/phase-v5/evaluate.py preference5 2 --windows
```

Source-file SHA-256 values identify the specific local editions, not just titles:

| Recording | SHA-256 |
| --- | --- |
| Poppies | `63cf0d7d476bbb6c3b8dcd3972bcec27a4536e6b3af96348e08774912d768e39` |
| 505 | `a138f550f52ba5f8cb5109f84bdf3cacd54d2d3f9bdb1302f728625f99c7e8cc` |
| Clocks | `c970b1131963a214d6ebdc28ef27cd92cf8178fda0dee38d9fcb164aeb05bc96` |
| The Red | `b84b999e8cc0c4e58348511a115b7396a41b4f26e0f98a05385ca40c2972dc3e` |
| ocean eyes | `3f286b8dc9d29835cea3349bf4ab245c4742f2bd1b65b8eb8ae5719af7387433` |
