# Phase parameter intent and native consumers

Research date: 2026-10-31. Scope: Phase build 3168002, SHA-256
`35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258`.
This follow-up traces the native consumers of the per-song fields and tests
specific interpretations. It changes documentation and private research probes,
not the production analyzer or game configuration.

## Most defensible interpretation

| Input | Meaning supported by evidence | Confidence and remaining uncertainty |
| --- | --- | --- |
| Transient timestamp | Time of a candidate musical attack | Exact parser and conversion behavior; original detector timing is unknown |
| Three five-bit transient magnitudes | Spectral-band strengths: their combined value supplies selection priority, and their ordering seeds primary and alternative lanes | Native consumers confirmed; original filter and quantizer are not recovered |
| Beat timestamp | Musical pulse position used for phrase grouping, candidate alignment, and beat cues | Native consumers confirmed; producer's beat-grid conventions remain uncertain |
| Low beat nibble, currently `accent` | Beat-associated power used for relative soft/normal section classification | Consumer confirmed; RMS is our chosen source measurement, not a recovered producer formula |
| High beat nibble, currently `strength` | A separate producer measurement retained by the parser | Unused for gameplay generation in the audited build; an optional diagnostic read discards it; original musical meaning unresolved |

The low/mid/high interpretation now has stronger evidence than naming alone:
the shipped analysis configuration explicitly lists three frequency subbands.
The claim that the three magnitudes influence lane choice is directly supported
by the native candidate constructor, lane-adjustment routine, and output writer.
Their influence is more specific than simply making an attack more likely to
survive selection. [Candidate constructor][candidate], [lane adjustment][lanes],
[tap output][output], [shipped configuration][config].

## Shipped analysis-band definitions

Both extracted `phase.json` and `conv_phase.json` contain an `analysis` block:

| Configuration key | Shipped value |
| --- | --- |
| `freq_FFT_size` | 256 |
| `freq_lower_band`, `freq_upper_band` | 80, 4500 |
| `freq_subbands` | `[80, 300]`, `[400, 1500]`, `[2000, 4500]` |
| `freq_mask_enable` | 1 |
| `trans_env_thresh_db` | -48 |
| `trans_eq` | 1, 1, 1 |

The strongest intended interpretation is three low-to-high frequency regions,
approximately **80–300 Hz, 400–1500 Hz, and 2000–4500 Hz**, in listed order.
The region boundaries have deliberate gaps; this is not a continuous division
of the entire spectrum. [Analysis configuration][analysis-config], lines 415–503;
[main configuration][config], `analysis` block.

These are shipped configuration values, not proof that the retail game executes
that producer. The inspected executable contains the consumer strings
`use_band_energies` and `minor_energy_multiplier`, but none of the searched ASCII
producer keys `freq_subbands`, `freq_FFT_size`, `trans_env_thresh_db`, or
`beats_env_thresh_db`. No producer function connecting these analysis settings to
the PHZ fields has been recovered. They may be development configuration retained
in the assets. Sample rate, filtering, windowing, channel combination, onset
measurement, and five-bit quantization remain unproved. [String-search receipt][results].

The current iOpenPod bands, below 250 Hz / 250–2000 Hz / above 2000 Hz, do not
match those shipped values. This is a documented producer-policy difference,
not a parser incompatibility. [Current analyzer](../../src/iOpenPod/app/phase_audio.py).

## Exact attack-magnitude behavior

The parser expands each five-bit field by shifting left 11, then stores their
sum. Thus the decoded values are linear fixed-point inputs to the consumer;
this does not prove how linear they were with respect to waveform amplitude.
[Parser][parser], lines 104–111.

The candidate constructor at `0x18030964` identifies the strongest band and the
strongest remaining band. Its five-word output contains time, score, primary
band index, alternative band index, and original transient index. When
`use_band_energies` is enabled, its pre-beat-amplification score is:

```text
strongest_band + minor_energy_multiplier * (sum_of_other_two_bands)
```

With that flag disabled it uses the stored sum. In the main shipped game
configuration, the flag is 1 and `minor_energy_multiplier` is 1, so the score is
the **sum of all three fields**, while their ranking still supplies lane
information. The strongest field alone is not the stock selection score.
[Constructor][candidate], [caller][selection], [main configuration][config].

A direct original-ARM probe checked **500 cases**: all triples from
`{0, 1, 7, 15, 31}`, with the flag disabled or enabled and the minor multiplier
set to 0, 0.5, or 1. Every case matched the score formula and selected a maximum
and maximum remaining band. Ties are deterministic: equal triples choose primary
index 2 and alternative index 0. [Probe][probe], [full results][results].

The lane routine at `0x18053CEC` can replace a repeated lane with the alternative,
using `shift_threshold` and `shift_max_interval`. The main configuration uses
2 and 1.5 seconds at all four difficulties. It also handles sweep/flurry-related
alternation. The output writer at `0x18056720` constructs a tap lane mask as
`1 << lane_index`. Thus band identity seeds lane identity, but does not force a
particular final button for every attack. [Lane routine][lanes],
[special-interval predicate][special], [output][output], [configuration][config].

## Native output experiments

A 60-second authored chart used identical timings, beats, and attack total, with
all six permutations of band strengths `(24, 12, 4)`. Every permutation produced
171 candidates after checkpoints and 128 emitted taps at **identical times**.
Their lane patterns changed with the band permutation: `(24,12,4)` emitted
86 mask-1 and 42 mask-2 taps; swapping its second and third bands instead emitted
86 mask-1 and 42 mask-4 taps. This verifies that the alternative band has a visible
output role even when selection and timing are unchanged. [Results][results].

The source-assisted version-5 Poppies chart gives the same distinction:

| Input | Selected after checkpoints | Taps | Mask 1 | Mask 2 | Mask 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original | 409 | 315 | 72 | 134 | 109 |
| Cyclic permutation of the three fields | 409 | 315 | 118 | 77 | 120 |
| Three fields replaced by their rounded mean | 409 | 315 | 103 | 0 | 212 |

The cyclic permutation preserves every emitted tap timestamp. Equalizing fields
also keeps the counts in this fixture, but rounding can change the sum slightly;
it is not a perfectly controlled score-preserving operation. Its collapsed lane
distribution is consistent with the constructor's tie behavior. A dense chart
can therefore still lose musical pattern variety through poor spectral encoding.
[Probe and receipts][results].

Clipping and independent band normalization deserve separate evaluation because
they can alter band order and create ties. Version-5 Poppies has 227 tied maxima
among 1252 input events, including 50 `(31,31,31)` events. This alone does not prove
a defect: original bundled files vary substantially, from 25 ties among 510 events
in `fff` to 247 among 1236 in `ccc`. There is no justified universal tie-rate
target. [iOpenPod statistics][stats], [bundled statistics][bundled].

## Beat fields and timing

The [beat-field investigation](phase-beat-field-semantics.md) documents direct
memory-read tracing and **40 complete native conversions** across two tracks,
four difficulties, and five upper-nibble variants. The upper field was not read
in the measured paths and all corresponding outputs matched exactly. All seven
original bundled charts nevertheless contain varying, nonzero upper values.
It is genuine producer data whose original meaning is unresolved, not known
padding. The follow-up ownership and teardown audit supports treating it as
unused for gameplay generation in this build. An optional diagnostic path does
read it, but immediately discards the value. Another 56 conversions, including
reporting enabled and short or irregular beat streams, produced identical output
when the upper value changed. The linked investigation records the assembly
evidence and the limits of this conclusion.

The lower field feeds relative power smoothing, a trimmed-average threshold, and
section merging. The resulting class changes difficulty-specific density and
spacing. Whole-mix RMS is consistent with this role, but its precise frequency
weighting, time window, and normalization cannot be recovered from the consumer
alone. Naming it simply `accent` can obscure this behavior.

Beat timestamps are also important independently of both values. Native phrase
grouping uses `beats_per_phrase` and `phrase_max_duration`; candidate alignment
selects beat/offbeat/no-beat amplification. With stock Hard configuration, a
class-1 on-beat amplifier of 4 means a score multiplier of 5, because the native
operation uses `1 + amplifier`. Offbeat 0 means multiplier 1, not deletion.
A modest foreground preference cannot be assumed to outweigh that rhythmic
priority. [Phrase grouping][phrases], [amplification][amplify],
[amplifier lookup][lookup], [configuration][config].

## Implications for the next analyzer experiment

Preserve the distinction between attack timing, spectral shape, and phrase
power. Evaluate the shipped subbands as a candidate mapping and measure changes
in band ordering, ties, lane sequences, and retained musical attacks alongside
counts. Avoid independently normalizing bands merely to balance lane counts:
the native game already performs lane variation using primary and alternative
spectral evidence. Source estimates should identify musical attacks without
arbitrarily relabeling their spectral bands as instrument lanes.

Keep the upper beat field encoded, but do not tune it as a density control on
the present evidence. Preserve relative dynamics in the lower field rather than
flattening it to maximum. The appropriate next acceptance step is a controlled
audio-to-chart comparison using the original bands, not declaring the entire
original analysis algorithm reconstructed. No production behavior was changed
by this research.

## Reproduction

```powershell
uv run --with unicorn==2.1.4 python .scratch/phase-parameters/probe_transients.py
uv run python .scratch/phase-parameters/inspect_chart_bands.py
```

The private probe executes original ARM code with the existing bounded crypto,
allocation, symbol, and output-storage adapters. It does not run rendering,
audio playback, or judgment. The image hash is verified by the underlying native
harness. Original assets and detailed chart output remain private.

[parser]: ../../.scratch/phase-windows/density-research/export1/18009dc4.c
[candidate]: ../../.scratch/phase-windows/density-research/export2/18030964.c
[selection]: ../../.scratch/phase-windows/density-research/export3/18053580.c
[lanes]: ../../.scratch/phase-windows/density-research/export6/18053cec.c
[special]: ../../.scratch/phase-windows/density-research/export6/18053c18.c
[output]: ../../.scratch/phase-windows/density-research/export6/18056720.c
[phrases]: ../../.scratch/phase-windows/density-research/export2/18061e2c.c
[amplify]: ../../.scratch/phase-windows/density-research/export3/18055798.c
[lookup]: ../../.scratch/phase-windows/density-research/export1/18078fdc.c
[config]: ../../../ipod-firmware-lab/artifacts/phase-assets/config/gen/phase.json
[analysis-config]: ../../../ipod-firmware-lab/artifacts/phase-assets/config/gen/conv_phase.json
[probe]: ../../.scratch/phase-parameters/probe_transients.py
[results]: ../../.scratch/phase-parameters/transient-results.json
[stats]: ../../.scratch/phase-parameters/band-statistics.json
[bundled]: ../../.scratch/phase-parameters-beat/bundled-fields.json
