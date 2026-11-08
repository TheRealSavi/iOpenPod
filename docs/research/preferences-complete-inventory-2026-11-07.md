# Latest firmware Preferences inventory

This investigation targets every stored preference and its value domain on the
latest retained firmware for Mini 1/2, Nano 1/3/4/5/6/7, Video 5/5.5 and Classic
6/6.5/7/7.5. The user's “6.6” is interpreted as the previously studied 120 GB
Classic 6.5. Nano 7 includes both updater families 37 and 39. Release identities
and the independently retained Apple catalog are in the
[latest-firmware coverage report](preferences-model-coverage-2026-11-07.md).

The target is complete understanding. An inventoried byte or registered key is
not necessarily an understood preference. Reports retain unresolved intervals,
unknown enum meanings and untraced effects explicitly; zero initialization and
absence from a simple accessor search do not establish unused padding.

## Five dedicated investigations

| Group | Exact targets | Field inventory and evidence |
| --- | --- | --- |
| Nano 1, Mini 1, Mini 2 | Nano 1 / 1.3.1; both Minis / 1.4.1 | [First pass](preferences-mini-nano1-complete-2026-11-07.md), [consumer and whole-file follow-up](preferences-mini-nano1-deep-followup-2026-11-07.md) |
| Nano 3, Nano 4 | Nano 3 / 1.1.3; Nano 4 / 1.0.4 | [First pass](preferences-nano34-complete-2026-11-07.md), [scalar/keyed-store supplement](preferences-nano34-consumers-2026-11-07.md), [slideshow, coupling and cache effects](preferences-nano34-effects-2026-11-07.md) |
| Nano 5, Nano 6, Nano 7 | 1.0.2, 1.2, 1.0.4; Nano 7 refresh / 1.1.2 | [First pass](preferences-nano567-complete-2026-11-07.md), [consumers, providers and timezone catalog](preferences-nano567-consumers-2026-11-07.md) |
| Video 5, Video 5.5 | 1.3, updater families 13/20/25 | [First pass](preferences-video-complete-2026-11-07.md), [volume, Photo, Radio and cache consumers](preferences-video-deep-followup-2026-11-07.md), [owner, cache and artist paths](preferences-owner-state-and-cache-2026-11-07.md) |
| Classic 6, 6.5, 7, 7.5 | 1.1.2, 2.0.1, 2.0.4, 2.0.5 | [First pass](preferences-classic-complete-2026-11-07.md), [compound state and consumer follow-up](preferences-classic-structures-2026-11-07.md) |

Each investigation binds findings to exact image hashes and runtime maps. Native
execution means original instructions in bounded offline harnesses with disclosed
service adapters. It does not mean a full boot, measured hardware behavior, or
proof that a connected iPod adopts a Host edit immediately.

## Findings that change the model

| Group | Examples established in this pass |
| --- | --- |
| Mini 1/2, Nano 1 | Forced `0xB0B` selects prefix-normalized artist keys when available; `0xB20` is the weekday origin with a modulo-seven rendering consumer. The latest loader still consumes `0x10` for old-format volume migration. Nano 1's Nike receiver byte is a sticky receiver-seen latch. Photo music modes and volume-limit arithmetic now have native consumer evidence. |
| Nano 3/4 | Slideshow duration is signed seconds on both, but transition tables, defaults and runtime fallbacks differ. Nano 4 Caption and Subtitle toggles treat malformed bytes differently. Native observers persist coupled changes. `0xB4C` invokes Track Extras Cache on Nano 3, while Nano 4's immediate setter only saves the byte and marks dirty. |
| Nano 5/6/7 | Recovered Nano 5's missing `Radio.LivePause` tail: captured ordinary catalogs now contain 53, 89, 102 and 102 entries, plus Nano 6's four timer entries. Fitness weight is a binary64 kilogram value inside an int64 container. Language, speech and clock-format settings have coupled behavior. Timezone values are city IDs; every image contains IDs 1..205, despite Nano 5's registered maximum of 204. |
| Video 5/5.5 | The second volume word is stereo balance. Volume-limit sidecars have a separate 32-byte record and can reassert a limit. Photo duration uses selectors rather than Classic's signed seconds. Radio regions have exact native channel grids. Forced flags control a cached media-source path and normalized artist keys. `Device/clock` remains the owner of persistent per-city alarms. |
| Classic 6/6.5/7/7.5 | Native slideshow duration is signed seconds at `0xB3E`; `0xB3B/0xB49` encode transitions. Captions/Subtitles enable paths clear and persist the other control. `0xB4C` controls Track Extras Cache; the independently traced Classic 6.5 participant caches artwork. Full raw-byte domains differ from the current UI's supported values. |

All details, defaults, address traces and qualification limits are in the
corresponding group reports. A table row is not an assertion that every field in
that group has been decoded.

The next unresolved work is specific, rather than a generic “unknown preferences”
bucket:

| Group | Remaining contracts to establish |
| --- | --- |
| Mini 1/2, Nano 1 | Indirect consumers of the large leading binary regions; forced `0x91/0xB0A`; volume balance and PIN/editor behavior; localized EQ and prefix rules; Nano 1 cache participants, `0xB4D`, brightness persistence and transition effects. |
| Nano 3/4 | Remaining binary structures and indirect accesses; Nano 4 keyed registration discovery and music class 5/6 meanings/runtime switch; Nano 3 non-UI transition renderers and concrete cache participant; `0xB48` consumers and Nano 4 `0xB4C` adoption; malformed-value event/load ordering. |
| Nano 5/6/7 | Indirect/dynamic registrations and unknown binary fields; remaining Bluetooth/video/fitness consumers and unit bounds; complete locale-change lifecycle; original DST rule evaluation and timer end states; timezone override precedence, kind-1 extra word and the apparent Cape Town package mapping discrepancy. |
| Video 5/5.5 | Complete Clock collection lifecycle, city pairs and alarm sound/selection domains; transition ID 7 and renderer effects; transient music-row adoption; volume/PIN validation, identity word, failure recovery and physical channel assignment; Calendar week-start consumer and Search/brightness hardware gates. |
| Classic 6/6.5/7/7.5 | Large indirect structures and remaining mask bits; full observer registration and movie rendering; Photo music classes 5/6 and per-image runtime parity; cache startup adoption/eviction; activity-policy precedence; volume balance, PIN and 7.5 EU predicates/confirmation. |

All groups still need physical Host-edit adoption evidence. These gaps are not
closed by matching offsets, identical default files or a setter accepting every
bit pattern. The group reports retain exact next entry points and byte/key
inventories, including partially understood fields.

Nano 3/4's second pass adds a separate [machine inventory][nano34-supplement]
and [258-case receipt][nano34-receipt]. It proves Photo Shuffle/Repeat at
`0xB3C/0xB3D` through each firmware's current controls and persistence helper.
Nano 4's six recovered named settings use XML in `Device/iPodSettings` without
the later models' `.xml` suffix. The first-pass byte counts remain a frozen
checkpoint; the supplement's named bytes are not added as fully understood
semantic coverage.

The continuation retains separate, immutable evidence checkpoints:

| Investigation | Validation recorded | Scope of the new evidence |
| --- | --- | --- |
| Mini 1/2 and Nano 1 | 12,831 native cases | Full loader/saver preservation, migration, artist-key selection, weekday rendering, Nano Photo modes, volume limits, brightness boundary and receiver latch. |
| Nano 3 and Nano 4 | 14,270 native cases | Signed Photo duration, complete transition UI and runtime selection, music storage, Caption/Subtitle coupling and the different immediate cache-control effects. |
| Video owner/cache/text paths | 3,075 native cases | Forced loader flags, cached media-source eligibility and `MFIL` conversion, plus normalized artist string-pool selection; no physical cache or complete normalization-grammar claim. |
| Video volume, Photo and Radio | 24,390 native cases | Full raw-word balance/packing behavior, volume-limit arithmetic and lock record, Photo modes and transitions, Radio grids, artwork-cache controls and corrected weekday property. |
| Four Classics | 25,726 native cases | Compound slideshow mutation, duration/transition consumers, Captions/Subtitles persistence, cache controls and two Classic 6.5 artwork-format lookups. |
| Nano 5/6/7 and refresh | Consumer/provider probes; all 205 cities per image; complete selected zone/rule parsing | 61 scoped field annotations, exact radio/photo/fitness domains, language/speech compatibility, signed minute-offset arithmetic and native parser-to-city-vector linkage. |

These are bounded original-instruction cases with disclosed adapters, not counts
of understood preferences. Mini's updated inventory still has 2,325 unresolved
bytes of 2,876; Nano 1 has 2,342 of 2,916, including partial fields. A large part
of each file remains unexplained. No newly surveyed interval is called padding
because it happens to be zero or lacks a discovered reader. Earlier group
reports are frozen checkpoints; follow-ups explicitly supersede provisional
field names and retain the evidence for each correction.

The [consolidated Video machine inventory][video-combined] merges both Video
investigations without changing the conservative 559 resolved / 2,365 unresolved
byte count. It incorporates the peer-reviewed u32 overflow and unmasked channel
packing contract. Raw volume/balance extremes cannot be described solely by the
simple equations for ordinary listening levels.

Nano 7 and its refresh also required a research-harness correction: two moved
service addresses had made the refresh's synthetic initial volume appear zero.
The corrected 16-case native pass establishes provider-derived volume values on
both images. The [current Nano 5/6/7 inventory][nano567-current] keeps those values
symbolic and records synthetic observations separately. The earlier apparent
default difference is superseded; it is not a firmware behavior difference.

## What “all possible values” must describe

The inventory separates four contracts:

1. **Stored representation:** file-relative offset, width, signedness, byte order,
   mask, string encoding or XML namespace/key. Packed fields and larger structures
   retain their internal boundaries.
2. **Firmware validation:** accepted numeric ranges, string comparisons, fallback
   branches, coercions, masked bits and loader behavior. A setter that stores any
   byte does not give every byte a defined user-facing meaning.
3. **UI choices:** the choices actually offered on that firmware and hardware,
   linked through menu resources and callbacks to their saved representation.
   Display order need not equal the saved integer.
4. **Effect and lifecycle:** consumers, coupled changes, notifications, dirty
   state, persistence and adoption. A setting's name alone does not prove its
   hardware effect, and a constructor default may depend on region or a provider.

Identifiers such as Playlist and Track identities have domains rather than a
finite menu of universal values. A complete account must describe their type,
lookup rules, sentinel values and missing-reference behavior. Named string
registrations alone do not establish a closed enumeration.

## Reconstructing the Classic menu evidence

The root investigation independently indexes resource banks in all four pinned
Classic images. Each image contains 21 structurally valid banks with string
resources; the bank containing the English `January` string is unique in each.
These are resource counts, not preference counts:

| Updater family | English bank file offset | String entries | Captured ITEM rows |
| --- | --- | --- | --- |
| 24 | `0x39E574` | 1,080 | 425 |
| 33 | `0x3FBAF8` | 1,102 | 433 |
| 35 | `0x40B130` | 1,112 | 436 |
| 38 | `0x40D074` | 1,143 | 438 |

The bank header has little-endian u32 version, data offset and type count.
The type directory identifies a FourCC, entry count and bank-relative table.
Each table row carries a resource ID, data-relative offset and byte length.
The scans validate every referenced range and reject duplicate type/ID pairs.
Simple `SORC` blocks connect a string handle to a display destination; `ITEM`
records can instead reference properties that a callback supplies dynamically.
This distinction prevents a nearby English string from becoming an invented
saved-value mapping. See the hash-bound [bank survey][classic-banks] and
[menu graph][classic-menus].

A separate [leaf-getter survey][classic-getters] retains 28/29/29/30 narrow
three-instruction candidates on families 24/33/35/38. It subtracts the observed
four-byte owner header when proposing file offsets. These remain discovery hints
until the actual Preferences owner and callers are bound; they are not semantic
coverage or a complete list of accesses.

## Relationship to iOpenPod support

The [Preferences API contract](../ipod-preferences.md) describes fields that the
application currently edits. Research findings do not automatically enlarge that
write surface. A new editable setting needs its own qualified target, complete
mutation contract, source-preservation checks and proportionate tests.

One existing qualification was corrected: the Video alarm page now shows the
Preferences value as a read-only **Clock alarm snapshot**, which can be disabled
or out of date. Native startup loads per-city alarms from `Device/clock`, so
patching Preferences alone does not
edit the selected saved alarm. Calendar editing remains available, including
when the captured alarm minute is unrecognized. The low-level raw field codec
remains byte-preserving; application workflow qualification is separate. See
[ADR-0247](../adr/0247-manage-extras-through-qualified-lossless-file-edits.md).

The correction passed 85 focused Registry, codec, virtual Storage, GUI and
controller tests, plus 11 translation tests. The regression cases include an
invalid retained alarm minute, a disabled midnight snapshot, an unavailable
snapshot, successful subsequent Calendar publication, and unchanged Preferences
and `clock` bytes. Mypy passed across 1,409 source files.

Datetime uncertainty remains nonblocking for Library loading and Sync. Retaining
an unknown clock field is preferable to assigning a guessed timezone or correcting
its bytes. File-integrity validation for an explicit edit remains separate from
datetime interpretation.

This pass performs no physical device writes. Large legacy structures, indirect
consumers and Host-edit adoption must remain visible research questions until
their behavior is demonstrated.

[classic-banks]: ../../../ipod-firmware-lab/artifacts/preferences-classic-resource-banks-20261107/banks.json
[classic-menus]: ../../../ipod-firmware-lab/artifacts/preferences-classic-resource-menus-20261107/menu-links.json
[classic-getters]: ../../../ipod-firmware-lab/artifacts/preferences-classic-leaf-inventory-20261107/candidates.json
[nano34-supplement]: ../../../ipod-firmware-lab/artifacts/preferences-nano34-consumers-20261107/native-final-v1/inventory-supplement.json
[nano34-receipt]: ../../../ipod-firmware-lab/artifacts/preferences-nano34-consumers-20261107/native-final-v1/receipt.json
[video-combined]: ../../../ipod-firmware-lab/artifacts/preferences-video-consolidated-20261107-final-v3/field-inventory.json
[nano567-current]: ../../../ipod-firmware-lab/artifacts/nano567-preferences-round2-20261107-final-inventory-v3/inventory.json
