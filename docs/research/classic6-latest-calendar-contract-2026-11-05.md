# Classic 6 latest-firmware calendar contract

Research date: **2026-11-05, America/Detroit**. The target is updater family
**24**, RetailOS **1.1.2**. Apple's captured update catalog and the retained
package manifest establish that release as the latest offered for this target;
the separate [identity investigation](classic-latest-firmware-targets-2026-11-05.md)
owns that qualification. This report investigates the actual family-24 image,
using Classic 120GB 2.0.1 only as a separately verified comparison.

## Application findings

Classic 6 can receive an explicit Preferences profile with **2,952-byte extent,
version `0x3c`, full unsigned 32-bit city ID at `0xb70`, Saved DST State byte at
`0xb6c`, signed day correction at `0xb78`, and seconds correction at `0xb7c`**.
The field coordinates match 2.0.1, but the extent and format version differ.
Do not require the 2.0.1 extent/version to inspect this target. [Reader][read],
[writer][write], [defaults][defaults], [field setters][city-set], [bias][bias]

The same best-effort Library date policy remains appropriate. Playback writes
calendar-encoded dates, the sidecar preserves raw words, and neither carries a
historical timezone or repeated-hour discriminator. The firmware table also
contradicts the legacy London mapping for city `0x26`: it resolves to **−300
minutes**, just as on 2.0.1. Retain the existing conservative unresolved-city
policy for this target. [Playback][play], [sidecar][counts-read], [city table][receipt]

Family 24 does **not** have a verified `Device/dst` consumer or an established
equivalent of the 2.0.1 automatic-transition route. The inspected family-24
city-selection path uses a retained DST byte, and its clock-refresh routine
does not perform the later automatic predicate calls. Keep the optional file
opaque for this target; that is an evidence boundary, not a claim that no such
consumer exists anywhere in the firmware. [Selection][selection],
[refresh][refresh], [bounded searches][receipt]

## Exact evidence and reproduction

| Item | Identity |
| --- | --- |
| Apple package | `Classic24FW/originals/iPod_24.1.1.2.ipsw` |
| Package SHA-256 | `e753abfb11aaeaa6fd1d7257e87f4e53b6b5d923b1de0e4c9c63c30e0dac9d1a` |
| Firmware member | `Firmware-24.9.1.2` |
| Logical plaintext OSOS | 9,924,476 bytes |
| OSOS SHA-256 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` |
| DRAM mapping | Image offset `0xae48`, runtime `0x08000000`, length 9,877,164 |
| Startup copy-table offset | `0x472c` |
| Runtime-map SHA-256 | `271b568f9b144f97b2a1cc76c1fef28790ac8577e5c0520780860e6f147abdd0` |
| Classic 33 comparison image | Normalized 2.0.1, SHA-256 `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`, DRAM image offset `0xb65c` |
| Pinned osos-lab baseline | `d2c8e357d58591bdaa70bb6be9da191f489554a6` |
| Tools used | UV, CPython 3.12.14, Capstone 5.0.6 |

Primary identities are the [extraction receipt][extraction] and independently
recovered [runtime map][map]. The logical family-24 body is not interchangeable
with a header-padded or normalized image. Function names below are analyst
descriptions, not recovered Apple symbols.

The new [verification script][script] pins both firmware hashes, verifies the
family-24 map and explicit field/constant instructions, compares 39 corresponding
instruction bodies, disassembles 14 additional spans, checks all 205 city rows
and 31 offset rows, and runs five bounded offset-adjustment algebra cases. It
retains both sides' decoded branch targets and literal values, validates 41
known call correspondences, and checks 30 explicit instruction/literal guards. The
[version-4 receipt][receipt] records every body hash and its exact extent.

```powershell
uv run scripts/check_classic24_calendar_contract.py --output-dir artifacts/classic24-calendar-contract-recheck
```

Run from the firmware lab with a **new** output directory. The script refuses
existing output directories and unexpected firmware. Its recorded SHA-256 is
`3ef36b5cb8ffca09da66fe90de5f00c13efe6962a170acc2e351e8c7db033569`.
It masks only relative branch operands and PC-relative literal displacement for
the instruction-shape comparison; equality by itself is not a proof of called
function semantics. The paths described below were also inspected through their
resolved targets. One constructor instruction differs beyond relocation:
the embedded default-extension pointer uses store `+0x914` in family 24 versus
`+0x918` in 33. The verifier records that exact instruction difference while
separately checking the date branches; it does not suppress it with a mask.
This is static evidence plus Host arithmetic reconstruction,
**not ARM emulation or physical acceptance**. No device was accessed or changed.

## Preferences: extent, coordinates, and retained state

`0x080833f0` reads at most `0xb88` bytes. Its caller at `0x08040e68` passes
`context + 4`, so native context offsets must be reduced by four to obtain file
offsets. Migration `0x08040e58` compares the format word against `0x3c` and
installs that value while upgrading older data. The default initializer
`0x080991cc` clears a `0xb88`-byte buffer and explicitly stores `0x3c` at its
offset zero. The writer `0x0804bf2c` allocates, copies from `context + 4`, and
writes exactly `0xb88` bytes. These are independent read/default/write witnesses,
not an inferred length from a single retained Preferences file. [Migration][migration],
[read][read], [write][write], [defaults][defaults]

| Observation | File coordinate | Family-24 instruction evidence |
| --- | --- | --- |
| Format version | `+0x000`, u32 | `0x08099218..0x0809921c` writes `0x3c` |
| Saved DST State | `+0xb6c`, byte | Getter `0x080323f0`; setter `0x080450dc` uses `LDRB/STRB` at context `+0xb70` |
| Selected city | `+0xb70`, u32 | Getter `0x0803243c`; setter `0x08045108` uses full `LDR/STR` at context `+0xb74` |
| Clock day correction | `+0xb78`, 32-bit displacement | Boot `0x08035ce8`, persist `0x0804348c..0x080434a0` |
| Clock seconds correction | `+0xb7c`, u32 | Boot `0x08035cec`, persist `0x08043494..0x080434ac` |

The default initializer separately clears these four clock/city fields at
`0x080992f8..0x08099308`. Boot loads the bias pair and calls `0x08045320`;
that routine installs the pair at `0x08911c14`. The getter `0x08033570` reads
the same pair, and Preferences persistence copies it back only when changed.
The signed day interpretation belongs to the existing software-correction model,
not a new signed city interpretation. [Defaults][defaults], [boot][boot],
[bias getter][bias-get], [bias setter][bias-set], [persistence][bias]

A full city word matters even though the built-in city keys are halfwords:
`0x080d9f48` compares the full caller value with each zero-extended table key.
Narrowing an arbitrary saved word to 16 bits could turn an unknown observation
into a falsely recognized city. The same reasoning forbids interpreting the
Saved DST State byte as a historical UTC correction. [City lookup][city-offset]

## City and offset tables

The city table at `0x0837d9c4` contains 205 twenty-byte records. Their layout is
`<IIHHHHHH`: two resource words, a group halfword, city ID at `+0x0a`, two
additional halfwords, offset code at `+0x10`, and a final halfword. The lookup
`0x080d9f48` resolves the code through `0x080d9d90`, which searches **31**
four-byte `<hH` rows at `0x0837d948`. Either unresolved lookup returns
`0x7fffffff`. The initializer copies 4,100 city bytes into its allocated table;
that path is not a DST-rule-file loader. [Lookup][city-offset], [offset lookup][offset],
[initializer][city-init]

| Table | SHA-256 |
| --- | --- |
| City records, 4,100 bytes | `91178a58e45ceffff6ddd5ee28c7c07c5cc79cf37ef70a7abdab8ce6a012395a` |
| Offset rows, 124 bytes | `1be1baef9f7ff339619aa7841a59f210ed92298cae4043dbaee9652b2a40300e` |

All city IDs 1 through 205 occur once in both 24 and 33. Each corresponding
resource word in 33 is 39 greater than its family-24 value; group and ID agree.
Ten cities have changes in the two additional halfwords, so the entire remaining
record must not be described as identical. The receipt lists these differences
without inventing meanings for those halfwords. [Table comparison][receipt]

Only city `0x32` differs in **resolved minutes**: family 24 has −240 and family
33 has −270. Family 24 lacks the later −270 offset row, but **does** contain
the unusual code 115 for +390 minutes. Do not copy the later 32-row index
assignment into this build. [Table comparison][receipt]

| City ID | Family-24 minutes | Interpretation boundary |
| --- | ---: | --- |
| `0x26` | −300 | Contradicts the legacy Manchester/London mapping; withhold that zone inference. |
| `0x18` | −360 | Consistent with the existing San José interpretation. |
| `0x36` | −240 | Consistent with the existing San Juan interpretation. |
| `0x41` | −180 | Consistent with the existing Rio interpretation. |
| `0x95` | +240 | Consistent with the existing Victoria interpretation. |

These names are existing libgpod-derived mappings corroborated by offsets, not
newly decoded Apple localized resource names. The investigation did not resolve
the underlying localized string resources. Fixed firmware offsets are also not
historical or current IANA timezone rules. [Existing identity analysis](firmware-dst-data-and-city-identity-2026-11-06.md),
[raw rows][receipt]

## Retained/manual DST versus an unproven automatic route

The city model initializer `0x080f82dc` starts byte `model + 4` at zero. Its
city updater `0x080f81b0` refreshes city, offset and resource data without
recomputing that byte. Selection `0x0814656c` persists the model's city and
byte, converts a nonzero byte to 60 minutes, and calls offset setter
`0x080b75b8`. Live reconciliation `0x081488e0` copies current live DST into
the model byte; it may also reconcile the selected city against the live base
offset. This is concrete retained-state behavior. [Model][model],
[model initializer][model-init], [selection][selection], [reconciliation][reconcile]

Manual action `0x081d3328` reads current metadata, toggles DST between 0 and
60, and calls that same setter. The setter adjusts the sampled calendar by:

```text
new = old + 60 * (new_zone + new_dst - old_zone - old_dst) modulo 2^32
```

Its metadata update uses mask `0x180`, then it sets the precomputed calendar.
Synthetic checks include both one-hour directions, a −300/DST60 to +330/DST0
change of +34,200 seconds, and both u32 wrap boundaries. They reconstruct the
inspected arithmetic; they do not test the UI or persistence on hardware.
[Manual action][manual], [setter][zone-set], [results][receipt]

The complete inspected refresh body `0x0815cd24..0x0815ce98` samples or
interpolates the calendar and publishes notifications. It lacks 2.0.1's automatic
predicate/setter sequence. An aligned direct ARM branch scan across initialized
DRAM found exactly two branches to `0x080b75b8`: selection at `0x081465d0`
and manual action at `0x081d3358`. This is bounded static call evidence;
indirect calls, Thumb code, computed paths and other possible calendar setters
are outside that scan. [Refresh][refresh], [scan receipt][receipt]

Exact null-terminated `dst`, backslash-path and slash-path searches in ASCII
and UTF-16LE found no matches. Together with the inspected routes, this explains
why no family-24 DST-file profile is qualified. It does **not** prove whole-program
absence of automatic DST, an alternate file path, encoded names or an independent
mechanism. Do not apply 2.0.1's table defects or later selector rules to this
image without its own consumer. [Search results][receipt]

## Clock provider, playback dates, and Smart comparisons

The normalized getter `0x0806afe4` calls the field bridge `0x0803390c`, which
uses the 2002-01-01 fallback when calendar validity is absent. Live metadata
still has signed quarter-hour units and a separate nonzero DST byte exposed as
60 minutes. The adjusted getter `0x080418f4` adds the software bias; adjusted
setter `0x0804c26c` uses requested-minus-raw for the running clock and subtracts
bias before programming bank one. This preserves the conceptual separation
between raw provider, corrected Firmware Calendar and metadata. [Normalized getter][normalized],
[field bridge][field], [adjusted read][adjusted-read], [adjusted write][adjusted-set]

The lower wrapper `0x08295294` reaches bank reader `0x08327540`: selector zero
reads seven bytes beginning at register `0x59`, selector one at `0x60`, and other
selectors return nine. Writer `0x08295590` reaches `0x0832762c`, with the same
running/alarm register sequences as the separately investigated 2.0.1 provider.
These bodies and resolved targets were inspected, not merely relocated by a
guessed address difference. The matching register roles do not establish that
the raw clock contains UTC; arbitrary raw origin plus compensating bias still
explains the adjusted calendar. [Raw wrapper][raw-read], [bank reader][bank-read],
[bank writer][bank-write], [2.0.1 hardware evidence][hardware]

| Date contract | Family-24 evidence | Result |
| --- | --- | --- |
| Last-played event | `0x08233f5c`, calendar read `0x0806afe4`, converter `0x08086c48` with argument zero | Calendar-to-Mac seconds, without subtracting zone/DST; stored at Track `+0x98`. |
| Last-skipped event | `0x08233fd8`, same converter and argument | Same calendar domain, stored at Track `+0xa8`. |
| Play Counts load | `0x0809058c`; copies at `0x08090670..74` and `0x080906a8..ac` | Sidecar words copied directly, with no timezone/fold validation. |
| Play Counts save | `0x08099cb0`; copies at `0x08099e74..78` and `0x08099e9c..a0` | Retains raw event words, with no UTC reconstruction. |
| Ordinary MHIT date import | `0x080716c4`; dataflow detailed below | Modification, last-played and last-skipped words copied; date-added has a zero fallback. |
| Smart date Track leaves | `0x08048530` | Same four date selectors and zero-extended u32 values as 2.0.1; zero has no special missing-date check on this route. |
| Smart relative-day context | `0x080b2410` | Lazily captures one Firmware Calendar value; caches inclusive 00:00:00 and 23:59:59 bounds. |
| Smart adapter/bounds | `0x08086d64`, `0x080420e8` | Sentinel `0x2dae2dae2dae2dae`; base + displacement × scale modulo 2^64. |
| Smart comparison | `0x08022abc` | Signed 64-bit numeric comparisons; date adapter converts relative action to inclusive range. |

Evidence: [play][play], [skip][skip], [Mac conversion][mac],
[sidecar read][counts-read], [sidecar write][counts-write], [Track leaf][leaf],
[day context][day], [adapter][adapter], [bound arithmetic][bound],
[comparison][compare]. These event, sidecar and Smart instruction bodies passed
the paired audit; the separately differing import span has explicit dataflow
guards. Calendar, Gregorian leap/ordinal and day composition/decomposition
helpers were also paired and their target chain inspected. The Mac converter's
epoch difference literal is `0x7c25b080`, or 2,082,844,800 seconds.

This strengthens the existing raw-preservation and non-blocking conversion
policy. It does not change ADR-0196's Host rolling-period Smart preview into a
firmware calendar-day preview. It also does not generalize every date-shaped
field or filesystem timestamp to that domain.
[Comparison scope](clock-adjustments-and-date-comparisons-2026-11-06.md)

### Ordinary Track import and date-added construction

The actual importer starts at `0x080716c4`, following unrelated literal words.
At `0x08071830`, it places the MHIT buffer at **stack `+0x234`**, four bytes
earlier than the 2.0.1 and later-family layouts. `0x08071838` requests a
`0x1b4`-byte header. The magic check at `0x08071864..0x08071870` resolves
literal `0x7469686d` at `0x08072630`, the little-endian `mhit` tag. The optional
endian-normalization call and header-size handling occur before the following
field accesses. These coordinates were traced directly in this build; subtracting
a presumed common code relocation would have selected the wrong entry point.
[Import listing][import], [field/call guards][receipt]

| Source date word | Stack slot | Family-24 dataflow |
| --- | --- | --- |
| MHIT `+0x20`, modification | `+0x254` | `0x080718d4` loads; `0x080718dc` stores Track `+0x6c`. |
| MHIT `+0x58`, last played | `+0x28c` | `0x0807199c` loads; `0x080719a0` stores Track `+0x98`. |
| MHIT `+0xa0`, last skipped | `+0x2d4` | `0x080719b4` loads; `0x080719b8` stores Track `+0xa8`. |
| MHIT `+0x68`, added | `+0x29c` | `0x080718ac` loads R3; `0x080718b8` calls constructor `0x0803c258`. |

No timezone arithmetic intervenes in the three raw-copy assignments. In the
constructor, `0x0803c270` retains the added argument in R6. Its zero test at
`0x0803c2a8` makes `0x0803c2b0` store a **nonzero word unchanged** at Track
`+0x58`. Zero instead calls `0x080383f0(&track.date_added)` at `0x0803c2bc`,
the already verified current Firmware Calendar-to-Mac-seconds function. This is
a runtime record fallback, not evidence that the original database bytes are
rewritten. These four contracts match the independently traced ordinary-date
scope of families 33, 35 and 38. [Constructor][constructor], [clock sample][clock-mac],
[import][import]

The release/publication-labeled word at MHIT `+0x8c` has a separately bounded
observation. `0x08071e0c` reads stack `+0x2c0`; zero skips the assignment.
Nonzero calls the extension-ensure helper `0x08019ca0`, reloads the same raw
word at `0x08071e20`, loads the extension pointer at `0x08071e24`, and stores
the word at extension `+0x18` at `0x08071e28`. The helper and these exact
instructions are retained in the new receipt. This establishes **raw copying
only**: it supplies no independent UTC provenance, publication-date timezone
rule, or historical conversion. Other date-shaped import fields, ArtworkDB,
and complete database publication remain outside this bounded follow-up.
[Import][import], [extension helper][extension], [guards][receipt]

## Remaining questions for Classic 6 / 1.1.2

| Question | What is established | What remains open |
| --- | --- | --- |
| Preferences | Extent/version, full city width, Saved DST State and bias coordinates; boot/persist routes | Physical save/reboot behavior and unusual/truncated historical file variants are not acceptance-tested. |
| Automatic DST / custom file | Retained/manual behavior in the inspected city and refresh routes; no qualified `dst` consumer | Whole-program automatic behavior, alternate consumers, transition scheduling and sleep/wake behavior. |
| Clock basis | Raw bank/register selection and software correction match the inspected 2.0.1 design | Absolute raw-clock origin, Host synchronization provenance and power-loss continuity. |
| City geography | All IDs/offsets compared; `0x26` conflict and `0x32` difference identified | Localized resource decoding, exact geographic identity for unresolved rows, historical user-selected cities. |
| Playback, ordinary import and Smart dates | Event writes, raw sidecar copies, four ordinary MHIT date contracts, raw release-word copy, principal Smart date path and its helper chain | Physical transition behavior; other date-shaped fields and complete database publication not retraced here. |
| Exact past UTC | A civil calendar word and current observations survive | Fold choice, past manual clock edits, travel, drift and previous settings cannot be recovered from these fields alone. |

None of these remaining questions should block Library loading, reconciliation,
saving or Sync. The safe support increment is explicit family/version qualification
for known observations, preservation of raw and Unknown Data, and documented
best-effort conversion. Physical testing is a future evidence improvement, not
a prerequisite for that authorized support.

[extraction]: ../../../ipod-firmware-lab/Classic24FW/evidence/extraction.json
[map]: ../../../ipod-firmware-lab/Classic24FW/evidence/runtime-map.json
[script]: ../../../ipod-firmware-lab/scripts/check_classic24_calendar_contract.py
[receipt]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/receipt.json
[read]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/preferences_read.asm.txt
[write]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/preferences_write.asm.txt
[defaults]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/preferences_defaults.asm.txt
[migration]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/preferences_migrate_span.asm.txt
[city-set]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/city_set.asm.txt
[bias]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/persist_bias.asm.txt
[boot]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/boot_bias_span.asm.txt
[bias-get]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/bias_get.asm.txt
[bias-set]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/bias_set.asm.txt
[city-offset]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/city_offset.asm.txt
[offset]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/offset_lookup.asm.txt
[city-init]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/city_initializer_span.asm.txt
[model]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/city_model_update.asm.txt
[model-init]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/city_model_init.asm.txt
[selection]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/city_selection.asm.txt
[reconcile]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/live_reconcile.asm.txt
[refresh]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/clock_refresh.asm.txt
[manual]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/manual_dst.asm.txt
[zone-set]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/zone_set.asm.txt
[normalized]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/normalized_clock.asm.txt
[field]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/field_get.asm.txt
[adjusted-read]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/adjusted_read.asm.txt
[adjusted-set]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/adjusted_set.asm.txt
[raw-read]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/raw_read_wrapper.asm.txt
[bank-read]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/pmu_bank_read.asm.txt
[bank-write]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/pmu_bank_write.asm.txt
[hardware]: ../../../ipod-firmware-lab/notes/itunesdb/hardware-clock-provenance.md
[play]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/play.asm.txt
[skip]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/skip.asm.txt
[mac]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/mac_wrapper.asm.txt
[counts-read]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/counts_read.asm.txt
[counts-write]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/counts_write.asm.txt
[leaf]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/smart_track_leaf.asm.txt
[day]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/smart_day.asm.txt
[adapter]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/smart_adapter.asm.txt
[bound]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/smart_bound.asm.txt
[compare]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/smart_compare.asm.txt
[import]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/track_import_span.asm.txt
[constructor]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/track_constructor.asm.txt
[extension]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/track_extension_ensure.asm.txt
[clock-mac]: ../../../ipod-firmware-lab/artifacts/classic24-calendar-contract-20261105-v4/clock_mac.asm.txt
