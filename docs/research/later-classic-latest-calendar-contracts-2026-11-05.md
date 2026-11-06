# Later Classic latest-firmware calendar contracts

Research date: **2026-11-05, America/Detroit**. Targets are updater family **35 / RetailOS 2.0.4**
and updater family **38 / RetailOS 2.0.5**, independently retained and inspected.
They remain distinct targets. This report does not infer a product SKU, board
revision or capacity from the user's generation labels. Apple's
[update-catalog capture][catalog] supplies the separate latest-release evidence:
35 remains on 2.0.4 while 38 is on 2.0.5; the latter is not a general update for
family 35.

Both later images retain the verified Classic 2.0.1 calendar architecture:
software-corrected calendar reads; separate zone/DST metadata; raw playback date
words; and Smart date comparisons against a captured calendar day. Their saved
clock fields occupy the same Preferences offsets, but their version/extent pairs
differ. This justifies explicitly qualified read-only observations; it does not
justify treating any date as an exact historical UTC instant or blocking a
Library when that interpretation is uncertain.

The applicable product policy remains
[ADR-0240](../adr/0240-treat-calendar-dates-as-best-effort-metadata.md) and
[ADR-0241](../adr/0241-inspect-firmware-dst-rules-as-optional-evidence.md).

## Exact inputs, method and limits

| Target | Logical OSOS bytes | SHA-256 | Runtime map |
| --- | ---: | --- | --- |
| 35 / 2.0.4 | 10,597,864 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | [35 startup map][map35] |
| 38 / 2.0.5 | 10,632,448 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | [38 startup map][map38] |
| Comparison: 33 / 2.0.1 normalized OSOS | 10,513,984 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | [Pinned normalized map][map33] |

All addresses below are runtime ARM addresses. Family 35's initialized DRAM starts
at raw offset `0xaed8`, and family 38's at `0xaf98`, both mapped at `08000000`.
The 2.0.1 comparison uses its normalized image, not either later raw layout.

The new [guarded script][script] validates full image identities before reading
any selected span. Its [receipt][receipt] records 223 instruction listings,
126 relocation-normalized comparisons across 63 selected routines, 200 checked
call-target correspondences, resolved PC-relative literal words, exact body
hashes, script/map hashes, tool versions and bounded Host arithmetic examples.
The two later images are checked independently against 2.0.1. Differences in
Preferences, import and persistence code are exported separately rather than
forced through an equality claim. Reproduce from the firmware lab with UV into
a new directory:

```powershell
uv run scripts/check_later_classic_calendar_contracts.py --output-dir artifacts/later-classic-calendar-20261105-v5
```

The retained receipt used Python 3.12 and Capstone 5.0.6. Branch-displacement
normalization is a verification aid, **not** proof that arbitrary callees or
indirect observers are equivalent. Reported contracts also use inspected loads,
stores, constants and resolved direct calls. The evidence is static firmware
inspection plus bounded Host reconstruction: no ARM execution, physical-device
test, firmware installation, clock setting, Preferences writing or shared Ghidra
mutation occurred in this investigation. [Script][script], [receipt][receipt].

## Preferences: same clock coordinates, distinct native versions

| Contract | Family 35 / 2.0.4 | Family 38 / 2.0.5 |
| --- | --- | --- |
| Fresh Preferences version at file `+0` | `0x3e` | `0x3f` |
| Native file extent | `0xb8c` = 2,956 bytes | `0xb90` = 2,960 bytes |
| Native context → file origin | Context `+4` | Context `+4` |
| Saved DST State | File `+0xb6c`, u8 | File `+0xb6c`, u8 |
| Selected city | File `+0xb70`, little-endian u32 | File `+0xb70`, little-endian u32 |
| Clock correction day word | File `+0xb78`, raw little-endian 32 bits | Same |
| Clock correction seconds word | File `+0xb7c`, raw little-endian 32 bits | Same |
| Dirty byte, **native context only** | Context `+0xb90` | Context `+0xb94` |

The loader passes context `+4` to the file reader. Its destination therefore
differs by four from the native getter/setter coordinates: DST context `+0xb70`,
city `+0xb74`, correction words `+0xb7c/+0xb80`. The reader zeros its destination
and caps its file read at the target's extent. That is firmware load behavior,
not authorization for the Host to pad a short captured file and declare its
missing clock fields known. [35 loader/read][pref35], [38 loader/read][pref38],
[receipt labels `preferences_read` and `preferences_load`][receipt].

The fresh initializers explicitly store the versions above; the loaders also
contain version migration branches. Family 35 shares 2.0.1's file extent but
has a different version. Family 38 adds four bytes after the older extent. Size
alone cannot qualify any of these layouts. This pass does not assign a product
meaning to the new trailing bytes. [35 initializer][default35],
[38 initializer][default38], [loaders and framing assertions][receipt].

| Clock-field consumer | Family 35 | Family 38 |
| --- | --- | --- |
| Saved DST getter / setter | `0804a0d8` / `0805cc1c` | `0804a0f8` / `0805cc58` |
| Selected-city getter / setter | `0804a124` / `0805cc48` | `0804a144` / `0805cc84` |
| Mirror live correction into Preferences | `0805ae30` | `0805ae6c` |
| Restore Preferences then install correction | `0804d97c` | `0804d9a8` |
| File writer / dirty guard | `080635cc` / `080636cc` | `08063668` / `08063760` |

These functions are independently exported and hashed in the receipt. The
restore routes read context `+0xb7c/+0xb80` and call the live correction setter;
the mirror routes compare/store both words and mark Preferences dirty. The day
word is a day displacement, not a timezone-minute value. Its signed
interpretation and the seconds remainder must remain distinct from their raw
32-bit storage. [Preferences and correction listings][receipt].

Saved DST State is still not a strict zero/one enum. City selection supplies a
normalized predicate result, while the broader live-settings mirror can pass
the live zero/sixty minute value into the same byte setter. Getters return the
raw byte. Do not reject 60 or silently rewrite an unusual retained byte.
[35 live-settings mirror][mirror35], [38 live-settings mirror][mirror38],
[DST getters/setters][receipt].

The writers copy the target extent from context `+4`; both clear the native
dirty byte after their write call without testing its returned status. These are
observed persistence attempts, not verified recoverable transactions. No
Preferences write implementation is recommended for iOpenPod by this finding.
[35 writer][writer35], [38 writer][writer38].

## Live calendar and clock correction

| Operation | Family 35 | Family 38 |
| --- | --- | --- |
| Read adjusted calendar | `080592b4` | `080592f0` |
| Read calendar plus metadata | `080593cc` | `08059408` |
| Read normalized compact calendar | `08083b08` | `08083ba4` |
| Set adjusted calendar | `0806390c` | `080639a8` |
| Read / replace raw correction words | `0804b258` / `0805ce60` | `0804b284` / `0805cefc` |
| Correction-pair global | `089caa98` | `089d30e4` |
| Metadata field bridge | `0804b64c` | `0804b678` |
| Masked calendar/metadata setter | `0804b928` | `0804b954` |

For ordinary valid calendars, both images read the raw packed calendar, convert
it to a day/second pair, add the software correction and convert it back. Setting
bank zero computes requested minus raw calendar as the replacement correction;
it does not write the running RTC calendar on that path. On successful setting,
reads temporarily use the requested-calendar copy while the counter difference
is below the literal 1,000,000. This is a post-set holding cache, not a cache
refreshed by every read. Pair arithmetic still performs only one carry or borrow;
the raw words must not be presented as a general normalized timezone offset.
[35 adjusted reader][adjusted35], [38 adjusted reader][adjusted38],
[setters, pair converters and arithmetic][receipt],
[2.0.1 interpretation baseline][provider-baseline].

The metadata bridge sign-extends the base-zone byte and multiplies by 15 to
obtain minutes. A zero DST byte yields zero minutes; any nonzero byte yields 60.
Validity flags remain separate from the calendar components. The metadata
signature `0x72746356`, zone byte and DST byte continue through separate provider
storage rather than the Preferences file. The script checks the signature and
these direct call correspondences in both builds. [Metadata bridge and storage
listings][receipt], [settings baseline][settings-baseline].

The lower bank readers still request seven bytes at register `0x59` for selector
zero or `0x60` for selector one. The writers retain the running/alarm distinction
and separate triplets. These addresses agree with the previously corroborated
PCF5063x running-calendar/alarm register roles. This establishes continuity of
the inspected transport and calendar handling, **not** that the raw running
calendar is UTC or local time. No physical transport binding or battery-retention
experiment was repeated for either later target.
[35 bank reader][bank35], [38 bank reader][bank38],
[bank writers and transport listings][receipt],
[primary-source hardware baseline][hardware-baseline].

## City selection, manual DST and automatic DST

| Operation | Family 35 | Family 38 |
| --- | --- | --- |
| Apply zone/DST minute change | `080d1510` | `080d15bc` |
| Select city and save current state | `08164884` | `08165048` |
| Manual DST toggle | `081f919c` | `081fa190` |
| Calendar model poll with automatic DST | `0817c66c` | `0817cf2c` |
| Annual active predicate | `080f4fc8` | `080f5080` |
| City-to-base-offset lookup | `080f4e18` | `080f4ed0` |

Both high-level setters calculate the same final change before applying it:

```text
calendar_after = calendar_before
               + 60 * (new_zone + new_DST - old_zone - old_DST)
               modulo 2^32
```

The manual action keeps the current base zone and changes zero DST minutes to
60, or nonzero to zero. The automatic model route compares the newly calculated
annual predicate with its cached predicate, checks the selected city's enabled
row and applies the same setter when a change is detected. It is therefore not
correct to describe either latest later Classic build as manual-DST-only. Exact
poll timing, sleep behavior and observer ordering remain outside this static
proof. [35 setter][zone35], [38 setter][zone38],
[35 automatic route][auto35], [38 automatic route][auto38],
[manual actions and city selection][receipt].

The annual-rule format, two-byte opaque custom-file prefix and corrected
week/February arithmetic were independently established in the
[earlier later-family DST investigation][dst-report]. Both later profiles use
selector 4 for the fourth week and 5 for last; these are distinct from 2.0.1's
selector 4 for last. Their 205 compiled city records retain the same numeric IDs,
selection groups and offset codes as 2.0.1, while resource IDs differ. Current
fixed offset, current DST, annual rule and historical geographical timezone are
still different evidence. [DST and city-table receipt][dst-receipt].

## Callback propagation does not establish a date migration

The exact later registration paths install two callbacks:

| Callback stage | Family 35 | Family 38 |
| --- | --- | --- |
| Registration routine | `0817d4bc` | `0817dd7c` |
| Zone metadata callback | `080bc3c8` | `080bc46c` |
| Calendar callback | `0809c5a8` | `0809c65c` |
| Set deferred-refresh byte at owner `+0x70` | `0812544c` | `08125644` |
| Deferred collection walk | `0812525c` | `08125454` |

The zone callback runs after metadata application but before the outer setter's
precomputed final calendar write; the calendar callback runs after that write.
Both refresh a model through a virtual method and mark deferred work. The later
collection walks still clear owner `+0x70` after traversal, but now invoke each
member's virtual slot **`+0x180`**, compared with **`+0x17c`** in 2.0.1. That is
a real observed contract difference, not an address relocation. It prevents
claiming that every indirect consumer is already understood merely because the
clock setters match. [Registration and callback listings][receipt],
[35 collection walk][walk35], [38 collection walk][walk38],
[2.0.1 callback baseline][callback-baseline].

The inspected direct clock/model stores do not establish a loop rebasing old
Track or Playlist timestamps. Indirect event recipients and collection-member
implementations remain unresolved separately for each later target. Likewise,
marking deferred work is not proof that Smart membership was recalculated or
successfully persisted. No complete old-date migration, or complete absence of
one elsewhere, is claimed here.

## Playback date domain and persistence

| Operation | Family 35 | Family 38 |
| --- | --- | --- |
| Record play / record skip | `0826501c` / `08265098` | `08266880` / `082668fc` |
| Compact calendar → Mac seconds | `0809fe94` | `0809ff40` |
| Compact calendar → 1970-relative seconds | `08088d60` | `08088dfc` |
| Direct calendar → Mac-seconds clock sample | `08050198` | `080501c0` |
| Positional Play Counts reader | `080a9d9c` | `080a9e48` |
| Positional Play Counts writer | `080b3ccc` | `080b3d70` |
| Track import span | `0808a3ec` | `0808a488` |

Both event kinds call the normalized compact-calendar getter and pass **zero**
as the Mac wrapper's current-offset-correction flag. The wrapper adds
2,082,844,800 to its Gregorian 1970-relative result; the underlying constants
are −719163 days and 86400 seconds per day. For admitted ordinary calendars this
produces the same 1904-relative calendar representation as the direct clock
sample. It is not a historical IANA conversion. The supplied calendar already
contains the software correction; adding Saved DST State or clock correction
again in the Host would double-apply evidence. [35 event writer][play35],
[38 event writer][play38], [wrappers, epoch assertions and skip writers][receipt].

After their receiver-validity gate, play writes Track `+0x98` and increments
`+0x90/+0x94`; skip writes Track `+0xa8` and increments `+0xa0/+0xa4`. Neither
compares the new date with the previous one. A backward calendar therefore does
not prevent accepted counters increasing while the raw date decreases. The
positional writer emits those date words unchanged beside counter deltas, and
the reader replaces them directly from row `+4/+0x18`, including zero and older
words. This independently extends the raw-date preservation rationale to both
later targets. It does not claim a complete successful playback or file flush.
[35/38 event and Play Counts listings][receipt],
[38 positional reader][counts38].

The inspected import spans still copy MHIT `+0x20` to Track `+0x6c`, `+0x58` to
`+0x98`, and `+0xa0` to `+0xa8` without a local timezone conversion. MHIT `+0x68`
is passed to the Track constructor: a nonzero word is retained; zero asks for the
current calendar sample. The MHIT buffer starts at stack `+0x238` in both spans.
These are the specifically traced ordinary Track dates; this report does not
generalize every date-shaped field or filesystem timestamp to that domain.
[35 import][import35], [38 import][import38],
[constructor and direct clock listings][receipt].

## Smart date consumers retain the captured-day model

| Operation | Family 35 | Family 38 |
| --- | --- | --- |
| Track rule leaf | `08060168` | `0806020c` |
| Numeric/date adapter | `0809ffb0` | `080a005c` |
| Lazy day-boundary capture | `080cc3a0` | `080cc444` |
| Bound arithmetic | `08059aa8` | `08059ae4` |
| Numeric comparison | `0803a29c` | `0803a29c` |

The later Track leaves zero-extend the relevant 32-bit modification, added,
last-played and last-skipped words. The adapter recognizes the full 64-bit
sentinel `0x2dae2dae2dae2dae` independently in lower and upper bases and lazily
captures the device calendar's day endpoints. One context stores start
00:00:00 and inclusive end 23:59:59 from the **same** calendar sample and reuses
them after its ready byte is set. It does not obtain a fresh current second for
every Track. [35 adapter][smart35], [38 adapter][smart38],
[day-cache and leaf listings][receipt], [2.0.1 Smart baseline][smart-baseline].

Bound arithmetic remains `base + multiplier * scale` modulo 2^64. There is no
local day/week/month unit enum or month-length calculation in that helper. The
adapter changes action bit `0x200` into inclusive-range `0x100` before the signed
64-bit comparator. Unsupported, malformed or out-of-range Host date intent must
therefore still follow ADR-0240's deterministic approximation/preservation
policy, rather than creating a workflow error. These native comparisons do not
silently replace the Host's documented Smart-preview policy.
[Adapters][smart35], [38 adapter][smart38], [bound/comparator listings][receipt].

The bounded receipt checks Gregorian epoch constants; offset moves of +3600,
−3600, +34200 and u32 wrap; zero/high-bit/backward raw playback words; and
day-versus-second relative bounds. These are explicitly Host arithmetic
reconstructions tied to verified instructions, not hardware or ARM-emulator
results. [Script][script], [receipt][receipt].

## Support implications and remaining questions

For family 35, typed read-only Preferences observations may require updater 35,
RetailOS 2.0.4, extent `0xb8c` and version `0x3e`. For family 38, require updater
38, RetailOS 2.0.5, extent `0xb90` and version `0x3f`. Device identity and captured
file framing are separate checks. Unknown, contradictory, missing or incomplete
evidence remains opaque or unavailable; it must not prevent Library operations.
The separately qualified later DST profiles remain useful regardless of whether
Preferences is readable. No new write or historical-time guarantee follows.

| Remaining question | Family 35 / 2.0.4 status | Family 38 / 2.0.5 status |
| --- | --- | --- |
| Meaning of custom DST's two-byte prefix | Loader reads it; no value check or semantic use established | Independently same limit |
| Raw RTC UTC/local-time basis | Running/alarm roles and correction path verified; time basis unproved | Independently same limit |
| Clock-change event recipients and deferred collection members | Direct callback/flag chain verified; member slot `+0x180` unresolved | Independently verified slot `+0x180`; recipients unresolved |
| Numeric city `0x26` geography | Compiled offset −300 conflicts with libgpod's Manchester/London mapping; localized Apple string unresolved | Same conflict independently verified |
| Hardware/SKU binding | Exact updater/release is known; no newly observed physical transport binding or board experiment | Same distinct limitation; do not collapse into family 35 |
| Historical timezone or fold identity | No history/fold information added by these calendar, DST, Preferences or playback fields | Independently same absence in inspected fields |
| Malformed calendar, provider failures, scheduling and persistence | Selected local behavior known; complete operational recovery untested | Independently same operational limit |

These remaining questions do not justify blocking date handling. They define
what optional diagnostics can honestly say and where later read-only research or
explicitly authorized physical validation would add evidence. The verified
shared behavior already supports the same best-effort Library policy across
these two latest firmware targets without inventing clock history.

[script]: ../../../ipod-firmware-lab/scripts/check_later_classic_calendar_contracts.py
[catalog]: ../../../ipod-firmware-lab/artifacts/latest-classic-catalog-20261105-v1/targets-v2.json
[receipt]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/receipt.json
[map35]: ../../../ipod-firmware-lab/Classic35FW/evidence/runtime-map.json
[map38]: ../../../ipod-firmware-lab/Classic38FW/evidence/runtime-map.json
[map33]: ../../../ipod-firmware-lab/vendor/osos-lab/ghidra/profiles/classic6g-reva-2.0.1.json
[dst-report]: firmware-dst-data-and-city-identity-2026-11-06.md
[dst-receipt]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/report.json
[provider-baseline]: ../../../ipod-firmware-lab/notes/itunesdb/clock-provider-and-adjustment.md
[settings-baseline]: ../../../ipod-firmware-lab/notes/itunesdb/timezone-and-dst-settings.md
[hardware-baseline]: ../../../ipod-firmware-lab/notes/itunesdb/hardware-clock-provenance.md
[callback-baseline]: ../../../ipod-firmware-lab/notes/itunesdb/timezone-change-propagation.md
[smart-baseline]: ../../../ipod-firmware-lab/notes/itunesdb/smart-time-rules.md
[pref35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-080587d8-preferences_load.asm.txt
[pref38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-080587f4-preferences_load.asm.txt
[default35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-080b30f8-preferences_default.asm.txt
[default38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-080b31a4-preferences_default.asm.txt
[writer35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-080635cc-preferences_writer.asm.txt
[writer38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-08063668-preferences_writer.asm.txt
[mirror35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-08167300-mirror_live_settings.asm.txt
[mirror38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-08167b08-mirror_live_settings.asm.txt
[adjusted35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-080592b4-read_adjusted_calendar.asm.txt
[adjusted38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-080592f0-read_adjusted_calendar.asm.txt
[bank35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-083627c0-rtc_read_bank.asm.txt
[bank38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-083640cc-rtc_read_bank.asm.txt
[zone35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-080d1510-apply_zone_dst_minutes.asm.txt
[zone38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-080d15bc-apply_zone_dst_minutes.asm.txt
[auto35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-0817c66c-automatic_dst_poll.asm.txt
[auto38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-0817cf2c-automatic_dst_poll.asm.txt
[walk35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-0812525c-deferred_collection.asm.txt
[walk38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-08125454-deferred_collection.asm.txt
[play35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-0826501c-record_play.asm.txt
[play38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-08266880-record_play.asm.txt
[counts38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-080a9e48-play_counts_read.asm.txt
[import35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-0808a3ec-track_import_span.asm.txt
[import38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-0808a488-track_import_span.asm.txt
[smart35]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/35-0809ffb0-smart_adapter.asm.txt
[smart38]: ../../../ipod-firmware-lab/artifacts/later-classic-calendar-20261105-v4/38-080a005c-smart_adapter.asm.txt
