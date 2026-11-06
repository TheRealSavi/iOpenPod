# Clock adjustments and date comparisons in Classic 2.0.1

Research date: **2026-11-06**. This follow-up examines the clock-provider boundary,
the automatic/manual DST state machine, and comparison behavior that remains
outside the best-effort date conversion policy. It adds a bounded direct-branch
search, a 32-case automatic-DST reconstruction, and four current-Host comparison
discriminators. It does not repeat the playback-sidecar findings in the
[non-blocking dates report](nonblocking-ipod-dates-2026-11-05.md).

## Findings for iOpenPod

Saved clock correction, live offset metadata, selected city, and the automatic
DST predicate cache are distinct states. None establishes the historical timezone
of a retained date. The firmware's manual action also does not constitute a
durable automatic-DST disable setting. Model the observed states separately;
do not turn a saved byte into a historical offset or an inferred mode switch.
[Manual action][manual], [automatic refresh][automatic], [raw/bias getter][scalar]

The current Host Smart Playlist preview and the inspected firmware intentionally
use different relative-date predicates. The new discriminators make that
difference testable without changing the accepted non-blocking policy or claiming
firmware parity across generations. [Host preview][host-preview],
[native adapter][adapter], [discriminator results][discriminators]

## Evidence and scope

| Item | Identity |
| --- | --- |
| Firmware | Classic 120GB, RetailOS 2.0.1, updater family 33 |
| Normalized OSOS | 10,513,984 bytes |
| OSOS SHA-256 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| Pinned analysis baseline | osos-lab `d2c8e357d58591bdaa70bb6be9da191f489554a6` |
| Profile SHA-256 | `b668b37155bea4ea1b4d4de545a01a5c047a4609d532b4421d34ced78ab5317c` |
| Initialized regions inspected | `.dram`: runtime `0x08000000`, image `0xb65c`, length `0x9fad50`; `.iram`: runtime `0x22000000`, image `0x800`, length `0xae5c` |
| Host tools | UV 0.13.7; CPython 3.12.14 |
| iOpenPod comparison | HEAD `1a4444058c4934721e55e622d96f132648fc64c2` plus the working tree |

The [profile][profile] owns the firmware identity and map. Addresses below are
specific to this image. Function names are analyst annotations. Exact instruction
checks and Host reconstructions are identified separately; neither executes ARM
or establishes physical behavior. Other researchers own the DST-file format,
city resources, and cross-generation comparison. This report does not generalize
Classic 2.0.1 transition arithmetic to newer releases.

## The raw provider still has no proven absolute-time basis

The raw-calendar helper `0x080344c0` explicitly selects bank zero, reads it through
`0x082be0cc`, and returns the converted day and seconds pair. It does not add the
saved software bias. Its caller `0x0804d0f0` can return two distinct scalars:

```text
raw_calendar_scalar = raw_seconds + 86400 * (raw_day_number - 2440588)
bias_scalar         = bias_seconds + 86400 * bias_day_displacement
```

Both calculations retain 32-bit arithmetic. The first constant is an epoch
coordinate; it does not prove that the raw calendar is UTC. The helper also
checks raw-provider status before publishing the scalar. These particular
branches should not be described as a Host Unix-time synchronization API merely
because their epoch resembles Unix. [Raw pair ARM][raw-pair],
[scalar ARM `0x0804d128..0x0804d170`][scalar]

A fresh aligned ARM B/BL encoding search across the two initialized regions
found these direct branches:

| Destination | Matching branch addresses | Verified role |
| --- | --- | --- |
| `0x082be3c8` | `0x0804d584` | The adjusted setter passes selector **one**. |
| `0x083532ec` | `0x082be3e4` | Synchronized wrapper forwards selector and buffer. |
| `0x0804d4f0` | `0x08045ca8`, `0x0804bef4`, `0x080c0204` | Calendar edit, intermediate zone adjustment, scheduled alarm. |
| `0x080344c0` | `0x0804d114` | Raw scalar reader described above. |

The sole found call to the raw-bank writing wrapper is therefore the already
identified alarm route, not an identified initialization of the running calendar.
The setter's selector-zero path instead computes requested-minus-raw bias.
This narrows the searched direct-call surface; it does **not** exclude Thumb
instructions, indirect calls, computed peripheral writes, bootloader code,
other modules, or other firmware images. An encoding search can also encounter
data that resembles instructions; the listed hits were checked against exported
function bodies. [Branch-search results][discriminators],
[adjusted setter `0x0804d550..0x0804d5cc`][adjusted-set],
[raw-bank wrapper][raw-set-wrapper]

The older raw-origin ambiguity remains: adding a constant to raw time and
subtracting it from bias preserves the displayed calendar and adjusted alarm
intervals. There is still no new evidence authorizing UTC/local labeling of the
raw hardware calendar or historical correction of old Track dates.
[Hardware provenance analysis][hardware]

The saved-calendar holding cache reads counter register `0x3c7000b4` and expires
at an unsigned modular difference of 1,000,000. Rockbox's pinned S5L87xx header
independently identifies that address as Timer E's counter and names it
`USEC_TIMER`. This corroborates register identity and Rockbox's convention;
it does not verify RetailOS's timer configuration or physical rate. Keep the
firmware model threshold in ticks until its initialization is established.
[Counter ARM][counter], [cache reader][adjusted-read],
[Rockbox header][rockbox-timer]

## Automatic DST is an edge detector with separate samples

The refresh routine at `0x08164584` has a fresh-sample branch distinct from its
calendar interpolation branch. In the fresh branch, exact calls and stores are:

| Address | Operation |
| --- | --- |
| `0x081645ec` | First selected-city DST predicate call, result A. |
| `0x081645f8..0x08164608` | Read previous predicate byte C and calculate `bool(A) XOR C`. |
| `0x08164610` | Read the normalized calendar into the model. |
| `0x08164630` | Second selected-city DST predicate call, result B. |
| `0x08164640` | Store `bool(B)` to the predicate cache. |
| `0x08164644..0x08164654` | Skip adjustment unless the earlier XOR is nonzero and the city enables DST. |
| `0x0816466c..0x0816467c` | Third predicate call D; call the offset setter with DST `60` if D is nonzero, otherwise `0`. |

Literal `0x08164788` resolves the predicate cache to **`0x089a1f38`**. It is not
the live calendar's DST metadata byte, the selected-city model's separate byte,
or Preferences file `+0xb6c`. The 32-case reconstruction enumerates boolean
C/A/B/D and the enable flag. Its local transition is:

```python
cached_after = bool(second_predicate)
setter_dst_minutes = (
    60 * bool(third_predicate)
    if bool(first_predicate) != bool(cached_before) and city_enabled
    else None
)
```

For the normally maintained zero/one cache, this reproduces the guarded ARM
sequence. It is not a model of arbitrary corrupt cache bytes, predicate internals,
callback recursion, or timing between samples. [Automatic ARM][automatic],
[byte-checked callback results][callback-results], [32 cases][discriminators]

Two useful discriminators follow. If C=0, A=0 and B=1, this invocation changes
the cache to one without calling the setter. If C=0, A=1 and B=0, the earlier
edge still permits a call, and D controls its requested DST. These are possible
input combinations for the reconstructed routine, not claims that a physical
transition necessarily supplies them. An emulator must not collapse the three
predicate calls into one sample and then claim exact scheduling fidelity.
[Automatic ARM][automatic]

The manual action `0x081deeb0` reads live base/DST minutes, maps zero DST to 60
and any nonzero value to zero, and calls the same offset setter while retaining
the base offset. No automatic-mode flag is written in this body. Conversely,
the automatic branch tests a predicate edge, not a direct inequality between
live DST and the expected value. A stable predicate alone therefore does not
prove that the next refresh undoes a manual switch. The predicate itself reads
clock state, and callbacks can re-enter model code; physical persistence still
requires a controlled test. [Manual ARM `0x081deeb8..0x081deee0`][manual],
[automatic ARM][automatic]

## A settings write is more than editing saved fields

The offset setter `0x080ba8a0` computes its final calendar before updating
metadata. It then applies metadata mask `0x180`, invokes the zone callback,
applies its precomputed calendar through `0x08076e70`, and invokes the calendar
callback. The lower metadata setter can make an intermediate base-zone-only
calendar adjustment. Those intermediate and final writes must not be added as
two independent final displacements. [Offset setter][offset-set],
[metadata setter][metadata-set], [callback propagation][propagation]

Return values are also unsuitable as a single successful-transaction receipt:
the outer offset setter returns one; the compact-calendar adapter returns zero;
and the lower software setter can update its bias before checking provider
failure. The deferred collection walk clears its pending byte after invoking
member virtual methods without aggregating their success. The members remain
unresolved, so this is neither proof of database timestamp migration nor proof
that all observers leave timestamps untouched. [Adjusted setter][adjusted-set],
[calendar adapter][calendar-set], [collection walk][collection]

This reinforces the existing observation-only Preferences boundary. Adding a
typed DST file reader or a pure transition calculation does not make direct
Preferences edits equivalent to the device's city/DST setting operation.
[Preferences policy][adr196]

## There are two different comparison contracts

The scheduled-calendar comparator `0x0806b73c` orders unsigned keys constructed
from year and an already derived day index, then hour/minute/second. It does not
read month, day, zone, DST, or validity flags for its comparison. Consequently a
model of this function must receive a consistent derived day index or expose
that raw field; silently recomputing it changes behavior for inconsistent input.
The scheduling selector chooses the first minimum among active entries 0..4,
without comparing that minimum to the current time. It selects the earliest
active calendar, not necessarily the next future alarm. [Comparator][calendar-compare],
[scheduled selection][schedule-select], [hardware analysis][hardware]

Smart date rules instead zero-extend the Track's native u32 word and compare it
against signed-64-bit calculated operands. Bound multiplication and addition
wrap modulo 2^64. There is no special missing-zero test in the inspected leaf
path, and reversed bounds are not repaired by the native comparator. Its
adapter changes action bit `0x200` to inclusive range `0x100`; relative sentinel
operands select cached local-calendar midnight and 23:59:59. These are arithmetic
contracts, not a conversion to unambiguous UTC events. [Adapter][adapter],
[comparator][numeric-compare], [Smart model][smart-model]

For a concrete current-Host discriminator, take native operands
`(sentinel, -1, 86400)` and `(sentinel, 0, 1)`, action `0x200`, and a sampled
calendar of **2026-03-08 12:00**. The firmware reconstruction produces inclusive
bounds **2026-03-07 00:00:00** through **2026-03-08 23:59:59**. The current writer's
equivalent `(-86400, 1)` lower displacement has the same product. Interpreting
the fixture through the explicitly supplied New York rules gives these results:

| Track calendar label | Classic reconstructed match | Current rolling Host match |
| --- | --- | --- |
| March 7 00:00 | Yes | No |
| March 7 10:00 | Yes | No |
| March 9 00:00 | No | Yes |
| March 8 23:59:59 | Yes | Yes |

This is a statement about explicit operand bytes, not an inferred Apple UI label
for “one day.” The bounds contain 172,800 local-calendar second labels; their
New York elapsed interpretation spans 47 hours through the spring transition.
The firmware itself never consults these Host timezone rules. The fixture used
the installed timezone file with SHA-256
`d7f2206b3a45989fc9ad63d558922532fa7352280d5f87176bf1db79cb1d1fa9`;
the authoritative observed hash is retained in the discriminator artifact.
[Fixture results][discriminators], [current writer][host-smart-writer],
[current preview][host-preview]

## Concrete support gaps and safe next steps

1. Keep a qualified firmware clock observation separate from Device Time Context:
   raw saved bias words, raw saved DST byte, full selected-city identity, and
   format/firmware provenance. Expose uncertainty rather than manufacturing an
   absolute raw-clock basis. The existing Classic profile already provides these
   saved fields; it does not capture live provider state or the predicate cache.
   [Preferences definitions][host-preferences], [Host resolver][host-resolver]
2. Add pure, explicitly qualified models for offset-change arithmetic and the
   local automatic-DST state transition if needed for diagnostics or fixtures.
   Preserve native word widths, the three-sample distinction, and intermediate
   notification ordering. Do not use these models to initiate device writes.
3. Keep a firmware date-rule evaluator or fixture oracle distinct from the
   rolling Host preview. Changing actual membership is a separate behavioral
   decision because [ADR-0196][adr196] deliberately retained rolling evaluation.
   A qualified implementation needs raw date words, native operands, one captured
   calendar-day context, and handling of unsupported rules without date blockers.
4. Do not infer chronology from date order, treat the bias as an extra timezone
   correction, rewrite existing dates after a city change, or disable load/save
   when any clock observation is missing. These remain Host policy limits under
   [ADR-0240][adr240], not shortcomings that a more detailed model can resolve.

The Host source comparison is pinned by SHA-256:
`smart_playlist_preview.py` =
`91717528581508799fa6477b2f6dfee70ed35f730aa1fd46ee320a324967f7cd`,
Preferences definitions =
`6dfb439f209509b11be82772cfccc316c60e850ad63afba57a75d5c681bc8e37`,
and the application time resolver =
`2c1c6849de391cab26b870db32af8324d696b9a2cc476ae68d3fbdce64e763cc`.
Subsequent working-tree changes may supersede these observations.

## Validation and remaining limits

Fresh runs passed the provider model's 2,416 unique instruction bytes, 100 BCD
and 404 calendar roundtrips, seven bias cases, and six cache cases; the callback
check's 14 bodies, two raw stubs, and 19 literal/table guards; and the Smart
model's 4,756 unique instruction bytes plus calendar, bound, action, cache, and
width fixtures. The additional discriminator run checked five more exported
listings totaling 504 bytes, the predicate-cache pointer, 32 local state cases,
four Host/native comparison cases, and the stated direct-branch search. These
groups overlap and must not be added as distinct firmware coverage.

Re-run the existing guarded checks from the firmware lab with fresh output paths:

```powershell
uv run python -B scripts/check_clock_provider_model.py --output artifacts/clock-adjustments-20261106-provider.json
uv run python -B scripts/check_timezone_change_propagation.py --output artifacts/clock-adjustments-20261106-callbacks.json
uv run python -B scripts/check_smart_time_rules.py --output artifacts/clock-adjustments-20261106-smart.json
```

Each result records source hashes and scope. The initial discriminator attempt
found no `tzdata` package in the standard-library-only lab environment and stopped
before writing output. The successful run opened the existing iOpenPod timezone
data file read-only with `ZoneInfo.from_file`; it installed no dependency and
changed no lab source. [Provider result][provider-results],
[callback result][callback-results], [Smart result][smart-results],
[additional results][discriminators]

No physical iPod, firmware settings, shared Ghidra metadata, or application code
was changed. Raw clock initialization, exact timer frequency in RetailOS,
notification recipients, callback reentrancy, alarm delivery, historical device
settings, and other firmware generations remain unverified here. These limits
prevent claiming clock synchronization support or exact recovery of historical
UTC timestamps.

[profile]: ../../../ipod-firmware-lab/vendor/osos-lab/ghidra/profiles/classic6g-reva-2.0.1.json
[manual]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-lower-writes/081deeb0-FUN_081deeb0.asm.txt
[automatic]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-callback-model/08164584-FUN_08164584.asm.txt
[raw-pair]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-provider/080344c0-FUN_080344c0.asm.txt
[scalar]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-lower-writes/0804d0f0-FUN_0804d0f0.asm.txt
[adjusted-set]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-provider/0804d4f0-FUN_0804d4f0.asm.txt
[raw-set-wrapper]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-lower-writes/082be3c8-FUN_082be3c8.asm.txt
[hardware]: ../../../ipod-firmware-lab/notes/itunesdb/hardware-clock-provenance.md
[counter]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-lower-writes/22001edc-FUN_000026dc.asm.txt
[adjusted-read]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-provider/08042ad4-FUN_08042ad4.asm.txt
[rockbox-timer]: https://github.com/Rockbox/rockbox/blob/2476968a206e5cdf80fde7887c48cd41512c3276/firmware/export/s5l87xx.h#L779
[offset-set]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-settings/080ba8a0-FUN_080ba8a0.asm.txt
[metadata-set]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-settings/0804be2c-FUN_0804be2c.asm.txt
[calendar-set]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-settings/08076e70-FUN_08076e70.asm.txt
[propagation]: ../../../ipod-firmware-lab/notes/itunesdb/timezone-change-propagation.md
[collection]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-dirty-refresh/0810e0cc-FUN_0810e0cc.asm.txt
[calendar-compare]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-settings-sources/0806b73c-FUN_0806b73c.asm.txt
[schedule-select]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-settings-sources/080a8db0-FUN_080a8db0.asm.txt
[adapter]: ../../../ipod-firmware-lab/artifacts/itunesdb201-rule-helper-exploration/0808949c-Exploratory_0808949c.asm.txt
[numeric-compare]: ../../../ipod-firmware-lab/artifacts/itunesdb201-rule-operator-exploration/08023928-Exploratory_08023928.asm.txt
[smart-model]: ../../../ipod-firmware-lab/scripts/check_smart_time_rules.py
[provider-results]: ../../../ipod-firmware-lab/artifacts/clock-adjustments-20261106-provider.json
[callback-results]: ../../../ipod-firmware-lab/artifacts/clock-adjustments-20261106-callbacks.json
[smart-results]: ../../../ipod-firmware-lab/artifacts/clock-adjustments-20261106-smart.json
[discriminators]: ../../../ipod-firmware-lab/artifacts/clock-adjustments-20261106-discriminators.json
[host-preview]: ../../src/iOpenPod/app/smart_playlist_preview.py
[host-smart-writer]: ../../src/iPodDB/library/_smart_writing.py
[host-preferences]: ../../src/iPodDB/preferences/definitions.py
[host-resolver]: ../../src/iOpenPod/app/services/device_time.py
[adr196]: ../adr/0196-adopt-firmware-clock-and-date-evidence.md
[adr240]: ../adr/0240-treat-calendar-dates-as-best-effort-metadata.md
