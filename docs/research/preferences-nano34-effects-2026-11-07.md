# Nano 3 and Nano 4: slideshow and coupled video preferences

This third pass independently traces the latest Nano 3 and Nano 4 images into
their consumers. Nano 4 has a different slideshow transition domain, a different
caption/subtitle toggle path, and a different immediate effect for the byte at
`0xB4C`. Shared file offsets do not establish shared behavior.

This supplements [the initial inventory](preferences-nano34-complete-2026-11-07.md)
and [the scalar, menu and keyed-store pass](preferences-nano34-consumers-2026-11-07.md).
It supersedes any provisional mapping that gives Nano 4 the Nano 3 transition
values. It does not claim that the whole Preferences file is understood.

## Evidence and verification

| Target | Latest image | SHA-256 | Preferences extent |
| --- | --- | --- | --- |
| Nano 3 | updater26, 1.1.3, `Nano3FW/decrypted/osos.bin` | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` | `0xB88` / 2,952 bytes |
| Nano 4 | updater31, 1.0.4, `Nano4FW/decrypted/osos.bin` | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` | `0xB90` / 2,960 bytes |

All addresses below are runtime addresses in those exact images. File offsets
are relative to the payload of `iPod_Control/Device/Preferences`; the native
owner points four bytes before that payload. Source images and existing evidence
were preserved. There was no physical device I/O or application behavior change.
Memory/file offsets and raw byte pairs are hexadecimal. Value-domain tables
otherwise use decimal numbers, so effect 25 is byte `19`.

The sibling `ipod-firmware-lab` contains the reproducible evidence under
`artifacts/preferences-nano34-effects-20261107/native-final-v2/`:

- `slideshow/nano3-effects.json`: 4,179 native cases.
- `slideshow/nano4-effects.json`: 3,923 native cases.
- `coupling/coupling.json`: 2,048 native cases for each image.
- `cache/cache.json`: 1,036 native cases for each image.
- `inventory-supplement.json`: storage, setter, UI and effect domains, exact
  offsets, defaults with provenance, and unresolved questions.
- `receipt.json`: hashes of scripts, native exports and final evidence files.

Total: **14,270 native cases**. Mutations assert the complete Preferences payload,
including unrelated bytes. Read-only getters and duration scheduling preserve
the payload. Probes pin the original images and runtime maps, compare exported
instruction bytes to mapped original bytes, and record executed addresses.
Additional complete Thumb switch spans are explicitly hashed where Ghidra's
function boundary stops before the cases.

These are bounded native executions. Model lookup, collection selection, random
input, unsigned division, timer calls, notification delivery, iterator services
and participant callbacks have explicit synthetic boundaries. The real firmware
OS, display, audio decoder and movie renderer were not run. All three native
harnesses were checked for unclassified external no-op calls: none occurred;
the coupling harness only uses its identified UI-notification no-op.

## Photo timing

Both images independently use a **signed byte of seconds at `0xB3E`**. The reset
default is `3`. The complete UI domain is:

| Stored value | UI label | Scheduling |
| --- | --- | --- |
| 0 | Manual | Return without scheduling |
| 2 | 2 Seconds | 2,000 milliseconds |
| 3 | 3 Seconds | 3,000 milliseconds |
| 5 | 5 Seconds | 5,000 milliseconds |
| 10 | 10 Seconds | 10,000 milliseconds |
| 20 | 20 Seconds | 20,000 milliseconds |

The native writer stores a byte without validating that domain. The consumer
first tests for zero. Thus Manual wins even when an album-duration override is
enabled. Otherwise an enabled override reads an album `u32` duration and clamps
it to at least two seconds. Without the override it uses the signed preference
byte. It multiplies by 1,000 and passes the 32-bit result to two timer services.

All 256 raw bytes were tested with override disabled and with album durations
0, 1, 2 and 17. Negative signed values produce wrapped timer arguments; they are
not sanctioned UI values. Downstream timer treatment of those arguments remains
outside this probe. A host parser should preserve them and present a usable
fallback, without making device access fail.

| Operation | Nano 3 | Nano 4 |
| --- | --- | --- |
| Settings cache getter | `0815F638` | `081425C0` |
| Duration getter | `081DFFD4` | `081AB318` |
| Duration writer | `081DFFEC` | `081AB32E` |
| UI row selection | `08221E08` | `081DB02E` |
| Scheduling consumer | `080F40FC` | `080F6B04` |
| Album override flag in consumer object | `+142` | `+E3` |
| Album object pointer | `+13C` | `+DC` |
| Album seconds | album `+8C8` | album `+B50` |

Own-image resource ITEM 57 on Nano 3 and ITEM 84 on Nano 4 supply the six labels.
The receipts retain the resource payload hashes, SORC bindings and native row
results. Invalid UI row indices leave the payload unchanged in these probes.

## Photo transitions: different complete UI tables

Two bytes form the setting: `0xB3B` is the mode and `0xB49` is the effect.
The getter returns logical `-1` when mode is `FF`; otherwise it returns the
unsigned effect byte. The writer stores `FF` only for an exact full-width `-1`
argument. Every other input stores mode `FE` and its low eight bits as the effect.
Consequently a direct input `255` is different from `-1`.

| UI label | Nano 3 logical value | Nano 4 logical value |
| --- | --- | --- |
| None | 0 | 25 |
| Random | -1 | -1 |
| Cross Fade | 14 | Not offered |
| Fade To Black | 5 | Not offered under this label |
| Zoom Out | 24 | Not offered under this label |
| Wipe Across | 1 | Not offered |
| Wipe Center | 3 | Not offered |
| Dissolve | Not offered | 26 |
| Slide | Not offered | 27 |
| Push | Not offered | 6 |
| Fade Through Black | Not offered under this label | 5 |
| Zoom | Not offered under this label | 21 |

Random writes mode/effect `FF/19` on Nano 3, but `FF/1C` on Nano 4. Reset defaults
also differ: Nano 3 uses `FF/19`, while Nano 4 uses `FE/1A` (Dissolve).

This is independently bound through each image's resource catalog, not translated
from another model. Nano 3 ITEM 56 and Nano 4 ITEM 83 contain the ordered labels.
Nano 3 menu rows use title-SORC word 26 within their ITEM blocks; these particular
compact Nano 4 ITEM blocks use word 1. Those layouts are not assumed for all ITEMs.

The actual transition-selection consumers add these rules:

- Nano 3 `080F35B0` returns Cross Fade `14` for its first-frame flag. Otherwise
  explicit IDs pass through. A negative direction-state byte swaps `1 ↔ 15` and
  `18 ↔ 19`. Names and renderer behavior of other non-UI IDs remain unresolved.
- Nano 4 `080F6464` returns None `25` for its first-frame flag. It accepts explicit
  IDs `25, 26, 27, 6, 5, 21`; every other explicit byte falls back to `25`.
- Both random paths choose from five non-None effects. Nano 3's table is
  `[14, 5, 24, 1, 3]`; Nano 4's is `[26, 27, 6, 5, 21]`. They select random input
  modulo five and advance to the next table entry when that repeats the previous
  effect. The random generator's distribution was not investigated.

| Operation | Nano 3 | Nano 4 |
| --- | --- | --- |
| Transition getter | `081E01F8` | `081AB4D0` |
| Transition writer | `081E0218` | `081AB4EE` |
| UI row selection | `0822BD3C` | `081E5FF8` |
| Runtime effect selection | `080F35B0` | `080F6464` |

The probes cover every raw effect byte, every mode byte, the full UI tables,
invalid rows, direct wide writer arguments, all raw first-frame effects, Nano 3
reverse selection, and random selection with repeated/non-repeated prior effects.
They prove selection and fallback behavior, not the pixel output of each renderer.

## Photo music and compound persistence

`0xB3F` is a raw byte returned as signed `i8`; `0xB40..0xB47` is an eight-byte
little-endian identity. Both writers accept all low-byte modes and copy all 64 ID
bits. The mode determines what the identity represents. The 256-mode getter
probes check signed extension and complete ID copying independently on both images.

The slideshow settings cache contains these independently verified coordinates:

| Cache offset | File offset | Width | Meaning |
| --- | --- | --- | --- |
| `+0` | `B39` | 1 | TV Out |
| `+1` | `B3A` | 1 | TV Signal |
| `+2` | `B3C` | 1 | Photo Shuffle |
| `+3` | `B3D` | 1 | Photo Repeat |
| `+4` | `B3E` | 1 | Time Per Slide |
| `+5` | `B3F` | 1 | Music mode |
| `+6` | `B3B` | 1 | Transition mode |
| `+8` | `B40` | 8 | Music identity |
| `+10` | `B49` | 1 | Transition effect |

The compound save tail is `0815F6DC` on Nano 3 and `08142624` on Nano 4. A native
settings action can copy the full group from its cache. Native probes seed a
coherent cache and patterned payload, then assert that all bytes outside the
intended changed fields remain exact. This is not evidence that a host should
overwrite the whole group from stale state.

Nano 3's dynamic selection callback `0822E790` writes mode `3` with ID zero for
the distinguished playlist selected by predicate `0829EE20`; otherwise it writes
mode `2` and the full playlist identity returned by `0829ED60`. Special-row
callback `0822E82C` maps row 0 to mode 4 and row 1 to mode 1.

Nano 3's runtime music consumer `080F31C4` was statically traced:

| Mode | Runtime behavior |
| --- | --- |
| 0 | Use the photo album's associated playlist/track IDs; fall back to Off if unavailable |
| 1 | Stop playback and set runtime mode to Off |
| 2 | Select the saved 64-bit playlist identity |
| 3 | Select the last playlist when the collection is nonempty; otherwise Off |
| 4 | Return before changing current playback: Now Playing |
| 5–255 | Fall through to Off |

The persisted reset value is mode 1 and identity zero on both images. Mode 0 is
a provider case, not a newly exposed host UI choice. The exact user-facing name of
the distinguished `Library+D28` playlist remains independently unbound here.

Nano 4 introduces additional real branches. Callback `081E8E18` uses native
predicate `082589CC` to recognize the distinguished `Library+D28` playlist and
write mode 3/ID zero. Otherwise it reads playlist member `+1B0` through
`08258864`. A zero member selects mode 2 and the full identity at member `+30`.
A nonzero member selects mode 5 or 6 and is zero-extended into the saved 64-bit
field. Predicate `08258A7E` chooses mode 6 when playlist member `+1B8` or `+1BC`
is nonzero; otherwise it chooses mode 5.

Nano 4 selection initialization `081E8C00` separately matches those same mode/ID
rules. Special-row callback `081E8EF8` independently maps row 0 to mode 4 and row
1 to mode 1, both with zero identity. Resource ITEM 85 contains Now Playing/Off
as its first two rows; the final controller-to-ITEM 85 binding remains a follow-up.
The full switch at runtime consumer `080F6074` and the human meanings of class
modes 5/6 still need investigation. These are not declared unsupported merely
because Nano 3 lacks their branches.

Music storage/getters were executed; these dynamic playlist classifiers and the
Nano 3 playback paths were statically traced. That distinction is retained in
the machine inventory.

## Captions and subtitles: persistence follows live notifications

Both images store Captions at `0xB74` and Subtitles at `0xB86`, one byte each.
Both default to zero and offer Off/On. Their saved setters can retain non-Boolean
bytes, so the actual UI behavior for malformed values matters.

| Action | Nano 3 | Nano 4 |
| --- | --- | --- |
| Toggle Captions | zero → 1; every nonzero → 0 | zero → 1; every nonzero → 0 |
| Toggle Subtitles | zero → 1; every nonzero → 0 | exact 1 → 0; every other byte → 1 |
| Enable one while other is 1 | Clear other | Clear other |
| Enable one while other is 2 or 255 | Explicitly clear other | Preserve malformed other byte |

Nano 3's legacy settings handler `0815DE94`, properties `60F1`/`60F3`, writes the
requested setting and calls the media service. When enabling it, the UI explicitly
asks the other live setter to store zero. Media notifications then drive observer
`0815FD1C`, which compares the live value's `==1` Boolean against the cached byte
and persists a changed result. The UI cache coordinates are `+98`/`+9A`.

Nano 4's current string-event dispatcher `081C9C00` routes
`HandleCaptionSettingsChanged` to `081AAC4C` and
`HandleSubtitleSettingsChanged` to `081AAF9C`. These toggle the live service,
not the legacy handler directly. The live setters only clear the opposite mode
when the requested full argument and the opposite live byte are both exactly 1.
Native observer `08142BC0` then persists the notification result. Its cache bytes
are `+8C`/`+8E`; the decompiler initially missed the switch body, so the harness
binds and executes the complete original span.

| Native component | Nano 3 | Nano 4 |
| --- | --- | --- |
| Media singleton | `0824F298` | `0820B830` |
| Constructor-installed vtable | `089BAAF8` | `084404B0` |
| Caption setter/getter slots | `+EC` / `+F0` | `+10C` / `+110` |
| Subtitle setter/getter slots | `+FC` / `+100` | `+11C` / `+120` |
| Live Caption/Subtitle bytes | `+44` / `+46` | `+67` / `+69` |
| Caption/Subtitle notification | `5000D` / `5000F` | `50012` / `50014` |
| Settings observer | `0815FD1C` | `08142BC0` |

For each image, the native probe tests both settings with every initial raw byte
and opposite values 0, 1, 2 and 255. It executes the original toggle, media
setter/getter and persistence observer. The real subject dispatch is replaced by
an explicit FIFO replay after the UI returns. Payload bytes, live state, UI cache
and dirty state are all checked. This demonstrates persistence coupling under
that delivery boundary, not OS dispatch timing or subtitle decoding.

## `0xB4C` and `0xB48`: shared offsets, different evidence

Nano 3's `0xB4C` setter `08046B7C` is now independently connected to the native
service named **TTrackExtrasCache** in constructor `081AA050`:

1. Compare the stored byte against the full requested argument; equal is a no-op.
2. A changed nonzero argument invokes `081A99A0`: sum registered participant
   budgets, reserve aggregate memory, call each participant's vtable `+10`, and
   set service `+64` to 1.
3. Zero invokes `081A9AAC` with mode 1: clear service `+64`, save mode in `+65`,
   call each participant's `+14`, and release aggregate storage. The additional
   `+24` clear callback belongs to mode 0 and is not used by this preference.
4. Store the argument's low byte and mark preferences dirty.

This full-width comparison matters outside the UI domain: input 256 can enable
the service while storing byte zero. The native probe covers all 256 byte inputs
plus 256, 257 and `FFFFFFFF`, against old bytes 0, 1, 2 and 255. Original loops
execute with two synthetic participant budgets 7 and 11, verifying aggregate
reservation 18 and the actual start/pause callback sequence.

Native registration `08069E0C` identifies participant 0, allocating its object
through constructor `0820B420` before registration `081A9DBC`. Its concrete
artwork behavior has not been independently established in this Nano image; a
Classic participant's meaning is not imported as proof.

Nano 4's corresponding setter `08059794` compares, stores and marks dirty but
has **no cache-service call**. The same 1,036 input/state combinations were
executed. This only proves the immediate setter behavior; it does not establish
that the byte has no later consumer. Nano 4 property `9DC8` and Nano 3 property
`60BB` still lack a bound human UI label. Both bytes default to 1.

The byte at `0xB48` defaults to zero and remains semantically unresolved.
Nano 3 setter `08046E3C`, getter `08031F9C`, refresh `08160204`, and property
`60BC` establish storage and a legacy cache. Nano 4 setter `08059A60` and property
`9DC9` establish its analogous route. Neither is renamed Photo Shuffle or Photo
Repeat; those fields are independently at `B3C` and `B3D`.

## Scope of coverage and remaining work

This supplement names or refines 16 bytes across nine fields. That is neither
16 fully understood bytes nor a replacement full-file coverage total. Music
class identities, non-UI Nano 3 renderer meanings, cache participants and both
unbound legacy controls still have semantic gaps. Initial full-file access and
semantic coverage remain in the earlier inventory; initialized zero bytes are
not promoted to padding. The separate Nano 4 extensionless
`iPod_Control/Device/iPodSettings` store and its six previously verified
registrations are unchanged by this pass.

The next bounded entry points are:

- Nano 3: finish participant `0820B420` and its installed callbacks to bind
  concrete TTrackExtrasCache payloads; find semantic consumers of `08031F9C`;
  name non-UI transition IDs accepted by `080F35B0`.
- Nano 4: recover the complete `080F6074` music switch and its resolver calls;
  identify the class fields behind `08258864`/`08258A7E`; finish controller-to-
  ITEM 85 binding; find adoption/read consumers of `B4C` and `B48`.
- Both: independently bind the distinguished `Library+D28` playlist name;
  verify actual event subscription and load/adoption ordering for malformed
  simultaneous caption/subtitle bytes.
- Nano 4 keyed settings: continue registration and effect-consumer discovery
  from `082092A8`/`08209354` and the six registration sites already documented.
  This checkpoint deliberately did not open another broad registration branch.

No datetime parsing or validation behavior was changed. Unknown or malformed
preference values should remain preserved and non-blocking; the evidence here
does not justify a new load error or silently normalizing unrelated settings.

## Reproduction

From the application repository, format/check the four sibling lab scripts with
its locked Ruff environment. From the lab repository, choose a new output
directory; each command refuses to overwrite an existing result:

```powershell
uv run scripts/research_preferences_nano34_effects.py --output artifacts/preferences-nano34-effects-20261107/reproduction/slideshow
uv run scripts/research_preferences_nano34_coupling.py --output artifacts/preferences-nano34-effects-20261107/reproduction/coupling
uv run scripts/research_preferences_nano34_cache.py --output artifacts/preferences-nano34-effects-20261107/reproduction/cache
uv run scripts/build_preferences_nano34_effects_inventory.py --directory artifacts/preferences-nano34-effects-20261107/reproduction
```

The native scripts declare isolated research-tool dependencies; application
dependencies were not changed. Static exports in the parent artifact directory
are also receipt-bound, including the recovered Nano 4 special-row instructions.
