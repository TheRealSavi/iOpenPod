# Nano 3 and Nano 4 Preferences: full-file inventory pass

This pass is **not a complete interpretation of Preferences**. It establishes a
whole-file coverage ledger, closes the Clicker route labels on both exact latest
firmwares, binds the Backlight selector to its native labels, and recovers the
different sparse language catalogs. Unresolved bytes remain Unknown Data, not
padding. The inventory is evidence for review, not a writer allowlist.

## Inputs and reproducibility

All paths beginning with `artifacts/`, `scripts/`, or `Nano*FW/` below are relative
to the sibling `C:/Users/JohnG/Coding/ipod-firmware-lab` workspace.

| Target | Latest release | OSOS SHA-256 | Preferences extent | Version |
| --- | --- | --- | --- | --- |
| Nano 3, updater 26 | 1.1.3 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` | `0xb88` / 2952 | `0x3c` |
| Nano 4, updater 31 | 1.0.4 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` | `0xb90` / 2960 | `0x3e` |

The independent runtime maps are `Nano3FW/evidence/runtime-map.json` and
`Nano4FW/evidence/runtime-map.json`. DRAM begins at runtime `0x08000000`, from raw
offset `0xf8dc` and `0xe800`, respectively. The Preferences payload is **owner+4**;
the library's owner pointer is **library+0xce8**. Every offset in the inventory is
file-relative. Owner metadata after the payload is not part of Preferences.

The final [field inventory][inventory] and [native receipt][receipt] retain the
measured values, source hashes, adapters and byte partitions used below.

The last eight bytes of the Nano 4 input remain unreliable. Native probes reject
reads overlapping the conservative guard `0x085707f1..0x08570808` and execution in
that interval. No conclusion here requires those bytes.

New reproducible evidence:

- `scripts/ghidra/PreferencesNanoFullInventory.java`: read-only owner-member
  access export. Nano 3 yielded 161 recognized functions; Nano 4 yielded 65.
- `scripts/research_preferences_nano34_full.py`: hash-bound original ARM/Thumb
  instruction probes and resource-bank decoder, using Unicorn 2.1.4 and
  Capstone 5.0.6. It records external adapters and executed instruction addresses.
- `scripts/build_preferences_nano34_inventory.py`: conservative byte ledger,
  with no classification of unreferenced bytes as padding.
- `artifacts/preferences-nano34-complete-20261107-final-v2/receipt.json`: 53 Nano 3
  and 54 Nano 4 cases, 371 and 504 distinct original instructions executed.
- The same directory contains `inventory.json`, independent resource catalogs,
  language catalogs, synthetic default snapshots, and executed-address lists.
- Static exports remain in `preferences-nano{3,4}-full-inventory-20261107`,
  `preferences-nano{3,4}-domain-callers-20261107`,
  `preferences-nano{3,4}-modern-ui-20261107`,
  `preferences-nano{3,4}-resource-domains-20261107`, and
  `preferences-nano4-recovered-domains-20261107` under `artifacts/`.

The Nano 4 recovery changed only the existing isolated Ghidra project copy under
`artifacts/preferences-nano5-project-20261107`; the original image and original
project were preserved. There was no physical device I/O.

Reproduce the final native run and inventory in a new directory:

```powershell
uv run scripts/research_preferences_nano34_full.py --output artifacts/NEW-nano34
uv run python scripts/build_preferences_nano34_inventory.py --directory artifacts/NEW-nano34
```

The root review reran all 107 cases after formatting and added an assertion that
each tested UI mutation preserves every payload byte outside its field. The
inventory builder rejects an existing inventory instead of overwriting it.

## What the native probes do and do not establish

The probes execute original preference store instructions, native UI dispatch,
and native label-selection branches. The Clicker experiment begins with
`0xa5a50000`, exercises all four choices, and asserts that only the intended low
bits change. It independently executes the modern UI's label conversion.

Synthetic adapters supply the library, player, UI object, resource lookup, and
platform defaults. Notifications and unrelated services are recorded no-ops.
The modern-label experiment supplies a controlled legacy property result at the
virtual-call boundary; it does not claim to execute the entire GUI framework.
This proves the firmware's mapping between choice, stored value, and label. It
does not prove physical speaker output, elapsed display timeout, live adoption
of a Host edit, or every downstream side effect.

Defaults snapshots are conditional on their recorded adapters: for example the
synthetic maximum-volume service returns 256. Board-dependent defaults were not
resolved by substituting the synthetic snapshot for a hardware fact.

## Newly closed domains

### Clicker: same file representation and route meaning

Both latest targets store a little-endian `u32` at `0xafc`. Its low two bits are:

| Saved low bits | Meaning | Native menu index |
| --- | --- | --- |
| 0 | Off | 3 |
| 1 | Speaker | 0 |
| 2 | Headphones | 1 |
| 3 | Both | 2 |

The generic setter accepts a full word. The actual menu preserves bits 2–31;
those bits have not been proven unused. A Host editor must therefore update the
low-bit mask, preserving the rest. The initializer stores 3 on both targets.

Nano 3: menu dispatcher `0x0815de94`, setter `0x08046bec`, modern display provider
`0x081dd768`, modern property `0x8912`, legacy property `0x608c`, choices
`0x608d..0x6090`. Nano 4: dispatcher `0x08141324`, setter `0x080597d8`, modern
provider `0x081a90e8`, modern property `0x9827`, legacy property `0x9d97`, choices
`0x9d98..0x9d9b`. Each image's own English bank supplies the labels; neither result
was borrowed from Classic, Video, Mini, or another Nano.

Resource records also bind the visible `Clicker` title to modern properties
`0x8912` and `0x9827`. UI visibility can still depend on other firmware state.

### Backlight timeout: values are not durations or string order

Both targets use `u32le` at `0xaf0`, initialized to 3. Executing each exact
firmware's preference query gives:

| Saved value | Native label |
| --- | --- |
| 0 | Off |
| 1 | 2 Seconds |
| 2 | 5 Seconds |
| 3 | 10 Seconds |
| 4 | 20 Seconds |
| 5 | 30 Seconds |
| 6 | Always On |
| 8 | 15 Seconds |

Value 7 and values 9–10 request no string in this query. They must not be assigned
invented meanings. The stored word and setter accept more values than the
documented labels; the probes also demonstrate direct dispatch accepting 7.
That acceptance does not make it an ordinary UI choice.

The current Nano 4 menu helper table at runtime `0x08457670` has seven entries
covering values 0–6. Native helpers `0x081aa894`, `0x081aa8cc`, and `0x081aad7c`
bound the table by seven. The 15-second branch therefore exists outside that
seven-entry menu helper. Full menu reachability for value 8, and every timeout
consumer's exceptional-value handling, remain unresolved. Do not infer UI
offered values merely from the string pool.

Nano 3 query `0x0815ceb4` and Nano 4 query `0x081406d4` independently establish the
table above. Their setting dispatchers use legacy properties `0x6031` and
`0x9d3b` respectively and subtract `0x6032` / `0x9d3c` from explicit choice IDs.

There is **another Backlight-related byte at `0xb4a`**. Native dispatch cycles it
`0 -> 10 -> 9 -> 6 -> 0`; its default is 9 on Nano 3 and 10 on Nano 4. Visible
resource sources bind this other property to a `Backlight` label using
`0x6004` / `0x9d0a`. It is distinct from the timeout word. Its complete context,
consumer behavior, and interactions are not yet qualified for writing.

### Language: sparse, model-specific catalogs

Both store `u32le` at `0xaf8`, initialized to zero, but the same number does not
always select the same language. The exact native catalog has 21 rows on Nano 3
and 22 on Nano 4. The menu order is also different from the saved-number order.

| Language | Nano 3 saved value | Nano 4 saved value |
| --- | --- | --- |
| English / English (US) | 0 | 0 |
| English (UK) | absent | 1 |
| Danish | 1 | 2 |
| German | 3 | 4 |
| Spanish | 4 | 5 |
| Finnish | 5 | 6 |
| French | 8 | 9 |
| Italian | 9 | 10 |
| Japanese | 10 | 11 |
| Korean | 11 | 12 |
| Dutch | 13 | 14 |
| Norwegian | 14 | 15 |
| Portuguese | 15 | 16 |
| Swedish | 16 | 17 |
| Simplified Chinese | 17 | 18 |
| Traditional Chinese | 18 | 19 |
| Czech | 19 | 20 |
| Greek | 20 | 21 |
| Hungarian | 21 | 22 |
| Polish | 22 | 23 |
| Russian | 23 | 24 |
| Turkish | 24 | 25 |

Nano 3's catalog starts at runtime `0x089e105c`. Nano 4's starts at `0x08457568`.
Rows contain a native string ID, locale-provider FourCC, and legacy choice ID.
The JSON includes every row, original-language label, address, locale FourCC,
choice ID, and stored value. English's provider key is zero; the UK provider is
`enGB`. Do not substitute an arbitrary host locale identifier for the firmware
provider key.

All dispatched indices 0–24 / 0–25 were independently executed. They are stored
even where the corresponding number is absent from the offered catalog. Thus
"the setter accepted it" is insufficient qualification for a Host language
editor. Nano 3 language application `0x081dfd94` searches its 21-row table,
falls back to the first row if unmatched, selects the resource provider, updates
the saved property, and notifies other components. The other dependent effects,
regional defaults, and Nano 4 application path require a further consumer pass.

## Existing qualified fields and persistence

The earlier [Nano 3/4/5 report](preferences-nano345-2026-11-07.md) remains the
source for Repeat, Shuffle, EQ, Sound Check, Brightness, file lifecycle, native
reader/writer tests, and existing Host restrictions. This pass does not weaken
those restrictions.

- Repeat `u32le+0x14`: 0 Off, 1 All, 2 One; UI order is Off, One, All.
- Shuffle bytes `0x18` and `0x8a`: Off 0/0, Songs 1/0, Albums 1/1. An already-Off
  no-op may preserve the irrelevant album byte.
- Sound Check `u8+0xb16`: 0 Off, 1 On.
- Brightness `u8+0xb54`: wheel bounds 0–100; default 50 on Nano 3, 40 on Nano 4.
- EQ `u16le+0xb60`: Off 0 and the 22 proven preset values 100–121. Unknown words
  can display Off without being erased until an explicit selection.
- Version `u32le+0` and reset request `u32le+4` govern loading/reset behavior.
- The full writer overlays the current live volume at `u32le+8`.

Current load also forces bytes `0x91`, `0xb0a`, and `0xb0b` to one. Their meanings
are not established here; Host serialization must not imitate that normalization.
No checksum was observed in the studied read/save bodies. A successful Host file
write does not demonstrate adoption by an already-loaded owner object; a later
native save can replace it.

## Coverage and remaining questions

The machine inventory contains exact integer offsets and widths, observed
default bytes with qualifications, evidence addresses, domains where resolved,
and the full unresolved ranges. A named field can still have unresolved effects;
for example the live volume's hardware maximum is not fully modeled. Counts are
unions of byte ranges, so overlapping access fragments are counted only once.

| Coverage | Nano 3 | Nano 4 |
| --- | --- | --- |
| File bytes | 2952 | 2960 |
| Fields / access fragments indexed | 62 | 52 |
| Bytes explicitly discovered by the conservative accessor/default scan | 136 | 119 |
| Bytes assigned a semantic field name | 34 | 34 |
| Bytes with the stated representation resolved | 18 | 18 |
| Unresolved bytes, including partially understood named fields | 2934 | 2942 |
| Proven padding bytes | 0 | 0 |

Bulk zeroing, reading, and saving covers the entire payload but does not identify
the purpose of its individual bytes. The discovery scan only recognizes simple
owner expressions in exported functions; it undercounts indirect structured
blocks and missed Thumb functions. The difference between 136 and 119 is a
research coverage difference, not evidence that Nano 4 contains fewer settings.

The conservative unresolved partition includes the entire Clicker word because
its upper 30 bits remain unexplained. It also includes live volume, Backlight and
language while their noted domain/dependency questions remain. Naming these
fields does not remove their unresolved parts from the ledger. The resolved
representation count describes the stated saved-value contract, not proof of
every hardware effect or live adoption path.

The next pass must answer these questions independently on each latest image:

1. What do all indirect structures before `0xaec` represent, including the
   `0x8ea` length-like halfword and adjacent large block? Which are resume/state
   data rather than user choices, and what bounds validate their contents?
2. What do the remaining initialized fields and accessors in `0xaf4..0xb8f`
   mean? Every unresolved range is enumerated in the JSON; none is silently
   treated as reserved. The tail extensions and different defaults must remain
   model-specific.
3. Bind every Main Menu / Music Menu item identity to its actual mask and label,
   including capability-gated items. Nano 3 mapper `0x080b76ac` has a recovered
   switch, but its labels and all UI-offered combinations still need closure.
   Nano 4 uses `0x080be5a4` plus menu selector `0x080cc0a8`.
4. Finish TV Out, TV Signal, TV Screen, Fit to Screen, Captions, Subtitles,
   alternate audio, and photo/slideshow domains. English resource records now
   bind these labels to native property IDs; a label binding alone does not prove
   saved field, full value set, or runtime effect.
5. For Nano 4, finish Audio Crossfade, Shake, Energy Saver, Rotate, Spoken Menus,
   Font Size, Preview Panel, and Sort Contacts. The resource catalog establishes
   their existence and property IDs without assigning guessed offsets or ranges.
6. Complete Backlight timing consumers and the separate `0xb4a` mode; verify
   ordinary availability of the 15-second timeout branch.
7. Complete language provider/catalog dependencies, regional default selection,
   out-of-catalog behavior, and notifications after a language change.
8. Reconcile clock/date/city/DST settings with the owning clock application and
   all other files. Do not import Classic offsets, city conventions, or the
   historical generic Nano 3 `0x6bc` DST claim into this Preferences model.

The report does not claim zero unknown preferences. It supplies precise gaps and
original-code entry points so the next investigation can reduce them without
inventing meanings. Unrecognized or inconsistent datetime bytes must remain
preserved and non-blocking in iOpenPod.

## Second consumer pass

The [consumer supplement](preferences-nano34-consumers-2026-11-07.md) adds native
menu visibility domains, photo/video scalar fields, and six settings in Nano 4's
separate `iPod_Control/Device/iPodSettings` XML file. This report and its coverage
numbers remain a frozen **first-pass** inventory; its 18 resolved representation
bytes are not a whole-investigation coverage total. The supplement deliberately
distinguishes named bytes, mapped mask bits, and unresolved consumer behavior.

[inventory]: ../../../ipod-firmware-lab/artifacts/preferences-nano34-complete-20261107-final-v2/inventory.json
[receipt]: ../../../ipod-firmware-lab/artifacts/preferences-nano34-complete-20261107-final-v2/receipt.json
