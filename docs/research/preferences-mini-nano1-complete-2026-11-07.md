# Mini 1, Mini 2 and Nano 1: whole Preferences inventory pass

Research date: 2026-11-07. **This is an explicitly incomplete whole-file
inventory, not a claim that every preference is decoded.** The filename records
the requested complete-inventory objective. Every byte is accounted for as a
mapped field or an unresolved interval; no unidentified byte is called padding.

This pass expands the previous four-control qualification with original UI
execution, complete serializers, complete English resource-directory extraction,
menu records, typed accessor candidates, and a separate byte-coverage inventory.
It makes no device changes and adds no application writing behavior.

## Exact inputs and reproducibility

Only the latest catalog-qualified releases are in scope. Updater identifiers
within a model are independently loaded and checked even where payloads are
identical. Mini 2 is **not** treated as byte-identical to Mini 1.

| Model | Updaters | Release | Preferences extent/version | OSOS SHA-256 |
| --- | --- | --- | --- | --- |
| Mini 1 | 3, 6 | 1.4.1 | `0xB3C` / `0x16` | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` |
| Mini 2 | 7 | 1.4.1 | `0xB3C` / `0x16` | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` |
| Nano 1 | 14, 17 | 1.3.1 | `0xB64` / `0x37` | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` |

The [previous Mini/Nano qualification](preferences-mini1-nano1-2026-11-07.md)
records Apple catalog provenance, independent package identity checks, startup
maps and prior native cases. The
[Mini 2/Video qualification](preferences-mini-video-writes-2026-11-07.md) supplies
the independently pinned Mini 2 baseline.

Run from the sibling firmware lab, always using new output directories:

```powershell
uv run scripts/research_preferences_mini_nano1_full.py --output artifacts/NEW-survey
uv run scripts/inventory_preferences_mini_nano1_full.py --survey artifacts/NEW-survey --output artifacts/NEW-inventory
```

The [native receipt](../../../ipod-firmware-lab/artifacts/preferences-mini-nano1-full-20261107-final-v3/initial-survey.json)
records **366 passing cases**: 64 for each Mini input and 87 for each Nano input.
The [machine-readable inventory](../../../ipod-firmware-lab/artifacts/preferences-mini-nano1-inventory-20261107-final-v3/field-inventory.json)
contains separate target hashes, extents, default bytes, field domains, effects,
evidence, partial/resolved status, and integer start/end-exclusive intervals.
Per-input `*-native-cases.json`, `*-menus.json`, `*-resource-types.json`,
`*-resources.json`, `*-defaults.bin`, and `*-accessor-candidates.json` sit beside
the receipt. Candidate accessors are search results, **not** automatically
classified Preferences fields: many unrelated objects have the same offsets.

The [probe](../../../ipod-firmware-lab/scripts/research_preferences_mini_nano1_full.py)
uses Unicorn 2.1.4 / Capstone 5.0.7 and existing pinned memory-map loaders. Every
executed non-adapter four-byte instruction has an address and hash in the receipt.
Filesystems, allocation, UI notifications, hardware queries, Nike UI lookup,
receiver effects and unrelated playback consumers have explicit adapters. These
are bounded original-instruction tests, not a full boot or a physical persistence
test. The [inventory builder](../../../ipod-firmware-lab/scripts/inventory_preferences_mini_nano1_full.py)
refuses output-directory overwrite and records its own and the survey's hashes.

## What is now measured

All offsets below refer to `iPod_Control/Device/Preferences`, whose payload begins
at owner `+8`. A source expression at owner `+0xB04`, for example, means file
`+0xAFC`. Multi-byte scalar storage is little-endian.

| Model | File bytes | Bytes assigned an individual field/structure | Bytes with resolved stated representation/meaning | Unmapped bytes | Unresolved bytes, including partial fields |
| --- | ---: | ---: | ---: | ---: | ---: |
| Mini 1 / each input | 2,876 | 598 | 545 | 2,278 | 2,331 |
| Mini 2 | 2,876 | 598 | 545 | 2,278 | 2,331 |
| Nano 1 / each input | 2,916 | 637 | 558 | 2,279 | 2,358 |

These deliberately conservative metrics count a whole masked field as unresolved
if any of its bits remain unexplained. The EQ text buffer contributes 510 bytes
of known string representation; that does not mean 510 independent settings were
decoded. Whole-file bulk copying/default zeroing is not semantic understanding.
The number of bytes proved to be padding is **zero**.

Native defaults are byte-identical across Mini 1/3, Mini 1/6 and Mini 2/7:
SHA-256 `3f59c88758284982e8d60a1b9bdc5f35606b99e1a111823bf90a909d7e21e002`.
Nano defaults under the recorded zero-valued hardware/region adapters have hash
`acb635e01fc7ec481c993d213a9e7960d31ba9da8f9cd160e2f70b6097a786d4`.
Identical default bytes establish neither identical code nor all runtime domains.

## Newly qualified common settings

| File field | Storage/default | Offered values and meaning |
| --- | --- | --- |
| Backlight Timer `0xAF0` | u32; Mini default `0`, Nano default `4` | **Mini:** `0` Off, `2` 2 seconds, `3` 5 seconds, `4` 10 seconds, `5` 20 seconds, `6` Always On. **Nano:** `0` Off, `2` 2 seconds, `3` 5 seconds, `4` 10 seconds, `5` 15 seconds, `6` 20 seconds, `8` Always On. |
| Contacts Sort `0xB0C` | u16; default `0` | `0` First Last, `1` Last, First. |
| Contacts Display `0xB14` | u16; default `0` | `0` First Last, `1` Last, First; independent of sort. |
| Clock format `0xB1C` | u32; default `0` | Bit 0: `0` 12-hour, `1` 24-hour. |
| Time in Title `0xB1C` | Same parent word | Bit 1: `0` Off, `1` On. Upper 30 bits remain unresolved and are preserved. |
| Audiobooks `0xB38` | **signed i8**; default `0` | `-1`/`FF` Slower, `0` Normal, `1` Faster. |

The Backlight ordinals are selectors, not second counts. In particular, saved
`5` and `6` mean different things on Mini and Nano. Selector `1` is accepted by
the simple setter but is absent from both current visible menus; it must not be
invented as an offered value. Nano selector `7` also exists in internal policy
logic but is absent from its current Backlight Timer submenu.

These mappings come from actual menu descriptors, including private negative
string IDs. Looking only at positive `Str` IDs misses the labels and incorrectly
makes the choices look like contiguous numeric ranges. Mini Backlight submenu
`0xFFFFFFAA`, Nano `0xFFFFFF95`, and their owning Settings menus are retained in
the per-target `*-menus.json` files. Native callbacks plus whole-file serializers
verify every listed choice and exact preservation outside its field.

The [Mini Settings callback](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000c5098.c),
[Nano Settings callback](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000ed5d4.c),
[Mini contact consumer](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000cbda4.c),
and [Mini audiobook protocol handler](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/00079e34.c)
tie saved values to consumers. The last handler explicitly bounds its signed
speed input to `-1..1`. A simple byte setter's ability to retain another bit
pattern does not make that pattern a meaningful speed setting.

Existing qualification remains: Repeat u32 `0x14` is `0` Off / `1` All / `2` One;
Shuffle uses bytes `0x18` and `0x8A`; Sound Check is byte `0xB16`; Clicker is the
low two bits of u32 `0xAFC`, `0` Off / `1` Speaker / `2` Headphones / `3` Both.
Language is a sparse **u32** at `0xAF8`; every exact localized label and offered
code is retained in the inventory. The Mini language subset has 14 choices and
Nano has 21; unused codes are not additional languages.

## Main Menu is a mask, with different offerings

The Mini visible mask at u32 `0xB2C` has these named controls:

| Mask | Label | Mask | Label |
| --- | --- | --- | --- |
| `00000001` | Music | `00000002` | Artists |
| `00000004` | Albums | `00000008` | Songs |
| `00000010` | Genres | `00000020` | Composers |
| `00000040` | Clock | `00000080` | Contacts |
| `00000100` | Calendar / Calendars alias | `00000200` | Extras |
| `00000400` | Notes | `00000800` | Games |
| `00001000` | Backlight | `00002000` | Sleep |
| `00008000` | Playlists | `00040000` | Audiobooks |
| `00080000` | Shuffle Songs | `00400000` | Podcasts |

The [Mini mask function](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000684e4.c)
also maps `0x25F9/0x25FA` to `0x10000/0x20000`; their current visible labels are
not established. Do not assign a guessed name to those bits. Nano has additional
named offerings, including Photos, Compilations, Screen Lock, Stopwatch, Radio
and Nike+iPod; the exact per-target masks and labels are in the machine inventory.
Both enabled and disabled operations were executed against a patterned word to
check that each operation preserved unrelated bits. Residual bits remain unknown.

## EQ and leading data: structure versus assumption

The global EQ enable byte is `0x8E0`. File `0x8EA` holds a u16 code-unit count,
followed by UTF-16LE text at `0x8EC`. The bounded resource-name conversion accepts
up to 255 code units, occupying 510 text bytes through `0xAEA` exclusive. This
pass does **not** call the following two bytes alignment padding.

The [Mini counted copy](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000470ec.c)
copies the count and exactly that many 16-bit characters; it does not clamp a
corrupt count. The full native writers were tested with counts 0, 8, 13 and 255,
including unchanged trailing bytes. A 255-character synthetic name tests copying
and bounds, not acceptance by the EQ registry. Valid EQ selection is an exact
localized compiled-name lookup, as shown by the
[Mini lookup/application path](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000beee0.c)
and the earlier [Mini 2 EQ investigation](../../../ipod-firmware-lab/notes/eq-mini2.md).
The 22 English presets run from Acoustic through Vocal Booster; their complete
strings are retained. They are not interchangeable with Classic numeric IDs.

The [Mini player initializer](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/00049710.c)
adopts saved volume, EQ name and EQ enable. A failed EQ lookup clears the saved
name count and retries. The
[full writer](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000dd840.c)
overlays live volume words, live EQ enable, and the live EQ name when its
ownership flag is set. Editing the on-disk copy while the retained owner is
active therefore does not guarantee the edit survives the next native save.

The large leading ranges before `0x8E0` are still mostly unresolved. Searches
were made across the full decompiler corpus, the complete dirty-setter call set,
defaults, loaders, player initialization and the complete save workflow. There
is **no established pointer chain** assigning them to playback bookmarks,
resume paths or an array of user preferences. In particular,
[Mini save orchestration](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000ddc1c.c)
writes [Play Counts](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000dda2c.c)
and [On-The-Go information](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000dd954.c)
through separate sidecars. Their owner dirty flags `+0xB45/+0xB46` lie outside
Preferences. Similar offsets in unrelated objects cannot supply missing labels.

## Nano 1 photo, radio and Nike structures

Nano appends substantial state after the shared `0xB38` audiobook byte.

| File range | Representation / meanings | Evidence and remaining limit |
| --- | --- | --- |
| `0xB39` | TV Out: `0` Off, `1` On, `2` Ask | Inherited photo dispatcher; **not offered in Nano's current visible photo submenu**. Hardware capability must still be respected. |
| `0xB3A` | TV signal: `0` NTSC, `1` PAL | Region-dependent default. Same visibility limit. |
| `0xB3B` | Transition mode: `0` Off, `1` Random, `2` Specific | Coupled with `0xB49`. |
| `0xB3C` / `0xB3D` | Shuffle Photos / Repeat, bytes `0/1` | Separate slideshow behaviors. |
| `0xB3E` | Time Per Slide: `0` Manual, `1` 2s, `2` 3s, `3` 5s, `4` 10s, `5` 20s | Default `2` = 3s. Native converter returns zero for other selectors too; that does not offer those selectors. |
| `0xB3F` | Music mode, branches `0..4` | Dynamic music-list labels and all source cases remain incomplete. |
| `0xB40..0xB48` | 64-bit slideshow playlist identity | Coupled to music mode `2`. |
| `0xB48` | Compilations byte `0/1` | Normal Settings menu property `0x60EA`. |
| `0xB49` | Specific transition ID | Visible: `1` Wipe across, `2` Wipe down, `3` Wipe from center, `6` Push across, `8` Push down. `FF` accompanies Off/Random. Hidden dispatcher IDs require consumer qualification. |
| `0xB4A` | Alternative backlight policy | `0` Always Off, `7` While Playing, `8` Always On, `9` On Keypress; distinct from `0xAF0`. Current product exposure unresolved. |
| `0xB4B` | Large Album Art: `0` Off, `1` On | Native menu `0x6022`, negative string `0xFFFFFF5C`, property `0x6005`. Both callback/save choices preserve every unrelated byte; downstream artwork effect remains untraced. |
| `0xB4C..0xB4E` | Two separate boolean properties | `0x60E9`, `0x60EB`; precise product labels/effects still incomplete. |
| `0xB4E` | Radio Region: `0` USA, `1` Japan, `2` Europe | Accessory-dependent; default derives from region word. |
| `0xB50..0xB54` | Volume Limit u32, default `100` | Complete lock/clamp interaction still needed before Host authoring. |
| `0xB54` | Saved brightness byte, default `100` | Hardware service path and saved-field commit are not yet fully joined. UI adjustment clamps the hardware request to at least 4. |
| `0xB55..0xB60` | **11-byte Nike+iPod settings block** | Original UI callbacks and original block commit newly tested. |
| `0xB60` | Nike receiver/availability latch, default `0` | Set to `1` on the studied receiver/retained-availability path; full reset behavior remains open. |

Intervals in this table use end-exclusive notation. The photo fields are traced
through the [compound save](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000eebd0.c),
[property callback](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000cddc4.c),
[seconds converter](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000ce724.c),
[transition setter](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000ce9e4.c)
and [transition normalizer](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000ce784.c).
These are static traces in this pass, not additional emulated slideshow tests.
An unsupported specific transition resets mode to Off and ID to `FF` on the
studied lookup path. Coupled writes must preserve that relationship.

Nike is particularly easy to misidentify as lock data or reserved bytes:

| Offset | Values | Use |
| --- | --- | --- |
| `0xB55` | `0` Kilometers, `1` Miles | Distance display/entry units. Toggling also converts and clamps live workout targets. |
| `0xB56` | `0` Female, `1` Male, `2` Off | Spoken Feedback voice; UI cycles through all three. |
| `0xB57` | **`0` On, `1` Off** | Remote Commands; inverted boolean. |
| `0xB58..0xB60` | LE 64-bit track identity | Selected PowerSong, not a timestamp. |

The [Nike callback](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a3e3c.c)
edits the first three bytes and invokes the
[11-byte commit](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000ee9d8.c).
The [PowerSong selector](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a3bf8.c)
supplies the remaining eight bytes. Exact resource getters establish
[distance labels](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a4cf0.c),
[voice labels](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a57c4.c)
and the [inverted remote labels](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a5234.c).
The block default is zero except Miles becomes `1` when the region predicate
`0x20F4C` is true. Native tests cover both unit transitions, all voice transitions,
both remote transitions and exact 11-byte serialization with a nonzero track ID.

## Load/reset behavior and unresolved legacy clock fields

The previous note's current-version preservation finding needs a qualification:
the loader **always forces file bytes `0x91`, `0xB0A` and `0xB0B` to `1`** in the
studied current-format path. New native probes start all three at zero and verify
that normalization on every input. Their complete meanings remain unresolved;
they are not ordinary user toggles.

Version zero, empty file or a nonzero reset word causes defaults; oversized reads
are clamped. Exact current payloads generally survive load, subject to the three
forced flags and later adoption consumers such as EQ. Current profile qualification
still requires exact file extent/version. Historical migration branches are not
new supported Host-writing profiles.

Several familiar offsets also appear in the inherited Settings interface:
`0xAF4` sleep selector, `0xB02` font selector, `0xB18` packed alarm flags,
`0xB20` week-start selector, `0xB22` alarm time word and `0xB24..0xB2C` alarm
playlist identity. Their accessors and partial bit operations are recorded in
the inventory. Current Alarm menus use separate application property IDs
(`0x458F` on Mini; `0x61F6` and other clock properties on Nano). These IDs require
tracing through the owning application; their difference alone does not prove
that an inherited Preferences field is unused.

In particular, the earlier [Mini 2 scheduling evidence][mini2-alarm] already
connects `0xB22` to Settings property `0x282B` and next-occurrence calculation
`0x000D88BC`; callback `0x0007D410` reacts to that property. This pass does not
invalidate that evidence or the existing narrowly qualified Mini 2 alarm-minute
editor. It does not extend that qualification to Mini 1 or Nano 1. Current menu
bridges and complete enable/sound persistence remain separate questions. No
uncertain clock/timezone field gains authoring support in this pass. Datetime
interpretation must remain nonblocking.

## Exact gaps and next questions

The following **unmapped intervals** are shared by Mini and Nano; ends are
exclusive:

```text
[010,014) [019,08A) [08B,091) [092,8E0) [8E1,8EA)
[AEA,AEC) [B01,B02) [B09,B0A) [B0E,B10) [B17,B18)
[B1A,B1C) [B21,B22) [B31,B38)
```

Mini additionally has `[B39,B3C)`. Nano additionally has `[B4F,B50)` and
`[B61,B64)`. The JSON's `unresolved_ranges` also includes partially understood
fields and is the authoritative conservative coverage partition. Bytes not
mentioned in a short table are therefore still accounted for explicitly.

The next pass should answer these bounded questions:

1. Establish owner-pointer provenance for the large leading intervals, including
   code using computed indices, aliases and raw memory copies. Determine whether
   they are consumed legacy state or retained opaque storage; lack of direct
   references is not proof of padding.
2. Trace the complete Backlight timer consumer for hidden selectors and the
   physical Contrast clamp; distinguish reachable controls from retained generic
   dispatch branches on Nano's color display.
3. Qualify EQ registry construction, non-English names, renamed/invalid-name
   adoption and all buffer boundaries independently on Mini 1 and Nano 1, matching
   the deeper existing Mini 2 EQ evidence.
4. Trace the current Alarm/Clock application persistence and legacy compatibility
   fields together, including `B18`, `B20`, `B22` and timezone selector adoption.
   Do not substitute a legacy Preferences field for the current alarm sidecar.
5. Complete Nano slideshow music-mode labels, hidden transition effects, hardware
   gating, the artwork consumer for `B4B`, the two unnamed boolean properties at
   `B4C..B4D`, Volume Limit lock handling,
   and brightness persistence. Execute the compound photo callback rather than
   inferring support from its scalar setters.
6. Finish Nike receiver-latch lifecycle, PowerSong deletion/remapping behavior and
   region-driven defaults. The 11-byte block is now structurally and semantically
   identified; peripheral interaction is still a separate qualification.

The concrete shared writing candidates from this pass are the exact offered
Backlight choices, Contacts Sort/Display and signed Audiobook speed. Clock and
menu fields require masked edits, and hardware/application-specific structures
require their remaining adoption checks. None of these findings justifies
discarding Unknown Data or manufacturing a default preferences file.

[mini2-alarm]: ../../../ipod-firmware-lab/notes/mini2-calendar-alarm-2026-11-06.md#alarm-clock-settings-scheduling-and-wake-boundary
